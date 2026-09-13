"""Seed Neo4j via HTTP Transaction API (no cypher-shell needed).

Parses seed.cypher and sends statements to Neo4j's HTTP endpoint.
Safe for memory-constrained environments (t3.micro) since it uses
lightweight HTTP calls instead of spawning a JVM.

Usage from CloudShell:
    python3 graph/seed_http.py --host <EC2-IP> --password <neo4j-password>

Or read password from SSM:
    python3 graph/seed_http.py --host <EC2-IP> --from-ssm
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
import base64


def parse_cypher(filepath: str) -> list[str]:
    """Parse seed.cypher into individual Cypher statements.

    Relationship CREATEs like ``CREATE (cdn)-[:DEPENDS_ON ...]->(dns)``
    reference variables from earlier statements. Since each HTTP request
    is a separate transaction, we rewrite them as
    ``MATCH (cdn {id:'cdn'}), (dns {id:'dns'}) CREATE (cdn)-[:...]->(dns)``
    so they resolve via property lookup instead.
    """
    with open(filepath) as f:
        content = f.read()

    content = re.sub(r"//.*", "", content)

    rel_pattern = re.compile(
        r"CREATE\s+\((\w+)\)\s*-\s*(\[.*?\])\s*->\s*\((\w+)\)"
    )

    statements = []
    for raw in content.split(";"):
        stmt = raw.strip()
        if not stmt:
            continue
        stmt = " ".join(stmt.split())
        m = rel_pattern.match(stmt)
        if m:
            src, rel, tgt = m.group(1), m.group(2), m.group(3)
            stmt = (
                f"MATCH ({src} {{id: '{src}'}}), ({tgt} {{id: '{tgt}'}}) "
                f"CREATE ({src})-{rel}->({tgt})"
            )
        statements.append(stmt)
    return statements


def send_statements(host: str, password: str, statements: list[str], batch_size: int = 50):
    """Send Cypher statements to Neo4j HTTP Transaction API in batches."""
    url = f"http://{host}:7474/db/neo4j/tx/commit"
    credentials = base64.b64encode(f"neo4j:{password}".encode()).decode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {credentials}",
    }

    total = len(statements)
    errors_found = []

    for i in range(0, total, batch_size):
        batch = statements[i : i + batch_size]
        batch_num = i // batch_size + 1
        batch_total = (total + batch_size - 1) // batch_size

        payload = json.dumps(
            {"statements": [{"statement": s} for s in batch]}
        ).encode()

        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                errs = result.get("errors", [])
                if errs:
                    errors_found.extend(errs)
                    print(f"  [{batch_num}/{batch_total}] {len(batch)} statements — {len(errs)} error(s)")
                    for e in errs:
                        print(f"    {e.get('code')}: {e.get('message', '')[:120]}")
                else:
                    print(f"  [{batch_num}/{batch_total}] {len(batch)} statements — OK")
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"  [{batch_num}/{batch_total}] HTTP {e.code}: {body[:200]}")
            sys.exit(1)

    return errors_found


def get_password_from_ssm(prefix: str = "/anomaly-demo") -> str:
    """Read Neo4j password from SSM Parameter Store."""
    import boto3
    ssm = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    resp = ssm.get_parameter(Name=f"{prefix}/neo4j-password", WithDecryption=True)
    return resp["Parameter"]["Value"]


def verify(host: str, password: str):
    """Count nodes and edges to verify seeding."""
    url = f"http://{host}:7474/db/neo4j/tx/commit"
    credentials = base64.b64encode(f"neo4j:{password}".encode()).decode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {credentials}",
    }
    payload = json.dumps({
        "statements": [
            {"statement": "MATCH (n) RETURN count(n) AS nodes"},
            {"statement": "MATCH ()-[r]->() RETURN count(r) AS edges"},
            {"statement": "MATCH (n) RETURN DISTINCT n.layer AS layer, count(n) AS count ORDER BY count DESC"},
        ]
    }).encode()

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())

    nodes = result["results"][0]["data"][0]["row"][0]
    edges = result["results"][1]["data"][0]["row"][0]
    layers = result["results"][2]["data"]

    print(f"\n  Nodes: {nodes}")
    print(f"  Edges: {edges}")
    print("  Layers:")
    for row in layers:
        layer, count = row["row"]
        print(f"    {layer}: {count}")


def main():
    parser = argparse.ArgumentParser(description="Seed Neo4j via HTTP API")
    parser.add_argument("--host", required=True, help="Neo4j host IP")
    parser.add_argument("--password", help="Neo4j password")
    parser.add_argument("--from-ssm", action="store_true", help="Read password from SSM")
    parser.add_argument("--cypher", default=os.path.join(os.path.dirname(__file__), "seed.cypher"),
                        help="Path to seed.cypher file")
    parser.add_argument("--batch-size", type=int, default=30, help="Statements per HTTP request")
    args = parser.parse_args()

    if args.from_ssm:
        print("Reading password from SSM Parameter Store...")
        password = get_password_from_ssm()
    elif args.password:
        password = args.password
    else:
        parser.error("Provide --password or --from-ssm")

    print(f"Parsing {args.cypher}...")
    statements = parse_cypher(args.cypher)
    print(f"  Found {len(statements)} statements")

    clear_stmts = [s for s in statements if "DETACH DELETE" in s.upper()]
    create_stmts = [s for s in statements if s.upper().startswith("CREATE")]
    index_stmts = [s for s in statements if "INDEX" in s.upper()]

    print(f"\n[1/4] Clearing existing data ({len(clear_stmts)} statements)...")
    if clear_stmts:
        send_statements(args.host, password, clear_stmts, batch_size=10)

    node_stmts = [s for s in create_stmts if "]->" not in s and "INDEX" not in s.upper()]
    rel_stmts = [s for s in create_stmts if "]->" in s]

    print(f"\n[2/4] Creating nodes ({len(node_stmts)} statements)...")
    if node_stmts:
        errs = send_statements(args.host, password, node_stmts, batch_size=args.batch_size)
        if errs:
            print(f"  WARNING: {len(errs)} node creation errors")

    print(f"\n[3/4] Creating relationships ({len(rel_stmts)} statements)...")
    if rel_stmts:
        errs = send_statements(args.host, password, rel_stmts, batch_size=args.batch_size)
        if errs:
            print(f"  WARNING: {len(errs)} relationship creation errors")

    print(f"\n[4/4] Creating indexes ({len(index_stmts)} statements)...")
    if index_stmts:
        send_statements(args.host, password, index_stmts, batch_size=10)

    print("\nVerifying...")
    verify(args.host, password)
    print("\nDone!")


if __name__ == "__main__":
    main()
