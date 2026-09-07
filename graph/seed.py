"""Seed the Neo4j graph with the full service dependency topology."""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase


def seed_graph(uri: str, user: str, password: str) -> None:
    """Read seed.cypher and execute it against Neo4j."""
    cypher_path = Path(__file__).parent / "seed.cypher"
    cypher_text = cypher_path.read_text()

    # Split on semicolons and filter empty statements
    statements = [s.strip() for s in cypher_text.split(";") if s.strip()]

    driver = GraphDatabase.driver(uri, auth=(user, password))

    with driver.session() as session:
        for i, stmt in enumerate(statements):
            # Skip pure comment blocks
            lines = [ln for ln in stmt.splitlines() if not ln.strip().startswith("//")]
            if not any(ln.strip() for ln in lines):
                continue
            try:
                session.run(stmt)
            except Exception as e:
                print(f"Error on statement {i + 1}: {e}")
                print(f"Statement: {stmt[:120]}...")
                sys.exit(1)

    # Verify
    with driver.session() as session:
        node_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        rel_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]

    driver.close()
    print(f"Seeded successfully: {node_count} nodes, {rel_count} relationships")


def main():
    parser = argparse.ArgumentParser(description="Seed Neo4j dependency graph")
    parser.add_argument(
        "--local",
        action="store_true",
        help="Use local .env file for connection details",
    )
    parser.add_argument("--uri", default=None, help="Neo4j Bolt URI")
    parser.add_argument("--user", default="neo4j", help="Neo4j username")
    parser.add_argument("--password", default=None, help="Neo4j password")
    args = parser.parse_args()

    if args.local:
        env_path = Path(__file__).parent.parent / ".env"
        load_dotenv(env_path)

    uri = args.uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = args.user or os.getenv("NEO4J_USER", "neo4j")
    password = args.password or os.getenv("NEO4J_PASSWORD")

    if not password:
        print("Error: NEO4J_PASSWORD required (via --password, .env, or env var)")
        sys.exit(1)

    print(f"Connecting to {uri} as {user}...")
    seed_graph(uri, user, password)


if __name__ == "__main__":
    main()
