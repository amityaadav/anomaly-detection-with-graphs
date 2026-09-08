"""Neo4j graph traversal tools for the Strands agent.

These tools let the agent query the service dependency graph stored in
Neo4j to understand relationships, trace cascading failure paths, and
calculate blast radius when a component goes down.

The graph schema (seeded by graph/seed.cypher):
  - Nodes carry labels like :Service, :Database, :Cache, :Queue, etc.
  - Every node has `name` (unique id) and `layer` properties.
  - DEPENDS_ON edges have `type` (sync/async/cache/config) and
    `criticality` (critical/degraded/optional).
  - ROUTES_TO edges connect the API Gateway to domain services.
"""

import os

import boto3
from neo4j import GraphDatabase
from strands import tool

_ssm = boto3.client("ssm")
_ssm_cache: dict[str, str] = {}
SSM_PREFIX = os.environ.get("SSM_PREFIX", "/anomaly-demo")


def _get_ssm_param(name: str) -> str:
    full = f"{SSM_PREFIX}/{name}"
    if full not in _ssm_cache:
        resp = _ssm.get_parameter(Name=full, WithDecryption=True)
        _ssm_cache[full] = resp["Parameter"]["Value"]
    return _ssm_cache[full]


def _get_driver():
    uri = _get_ssm_param("neo4j-uri")
    password = _get_ssm_param("neo4j-password")
    return GraphDatabase.driver(uri, auth=("neo4j", password))


@tool(name="get_service_info")
def get_service_info(service_name: str) -> dict:
    """Look up a single service node and its direct dependencies.

    Args:
        service_name: The graph node name, e.g. 'payment', 'redis2', 'pgpri'.

    Returns:
        Dict with node properties plus a list of direct dependencies
        (each showing the target name, edge type, and criticality).
    """
    driver = _get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (s {name: $name})
            OPTIONAL MATCH (s)-[r:DEPENDS_ON]->(dep)
            RETURN s.name AS name,
                   labels(s) AS labels,
                   s.layer AS layer,
                   collect({
                       target: dep.name,
                       type: r.type,
                       criticality: r.criticality
                   }) AS dependencies
            """,
            name=service_name,
        )
        record = result.single()
    driver.close()

    if not record:
        return {"error": f"No node named '{service_name}' found in the graph."}

    deps = [d for d in record["dependencies"] if d["target"] is not None]
    return {
        "name": record["name"],
        "labels": record["labels"],
        "layer": record["layer"],
        "dependencies": deps,
    }


@tool(name="trace_cascade")
def trace_cascade(failed_component: str) -> dict:
    """Trace the cascading impact of a failed component upstream.

    Walks the graph *backwards* along DEPENDS_ON edges to find every
    service that depends (directly or transitively) on the failed
    component.  Groups results by criticality so the agent can
    distinguish hard outages from degraded behaviour.

    Args:
        failed_component: Name of the component that is down,
            e.g. 'pgpri', 'redis2', 'kafka'.

    Returns:
        Dict with critical_path (services that will break),
        degraded_path (services that will degrade), and
        optional_path (services with optional dependency).
    """
    driver = _get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH path = (upstream)-[:DEPENDS_ON*1..5]->(target {name: $name})
            WITH upstream, target,
                 [r IN relationships(path) | r.criticality] AS crits,
                 length(path) AS depth
            RETURN DISTINCT upstream.name AS service,
                   labels(upstream) AS labels,
                   upstream.layer AS layer,
                   crits,
                   depth
            ORDER BY depth
            """,
            name=failed_component,
        )
        records = list(result)
    driver.close()

    critical, degraded, optional = [], [], []
    for rec in records:
        entry = {
            "service": rec["service"],
            "labels": rec["labels"],
            "layer": rec["layer"],
            "depth": rec["depth"],
        }
        crits = rec["crits"]
        if "critical" in crits:
            critical.append(entry)
        elif "degraded" in crits:
            degraded.append(entry)
        else:
            optional.append(entry)

    return {
        "failed_component": failed_component,
        "critical_path": critical,
        "degraded_path": degraded,
        "optional_path": optional,
        "total_affected": len(critical) + len(degraded) + len(optional),
    }


@tool(name="get_blast_radius")
def get_blast_radius(failed_component: str) -> dict:
    """Calculate the blast radius: how many services and layers are affected.

    This is a higher-level summary than trace_cascade, giving the agent
    quick numbers to include in an incident report.

    Args:
        failed_component: Name of the failed component.

    Returns:
        Dict with counts by criticality, affected layers, and the full
        list of affected service names.
    """
    cascade = trace_cascade(failed_component=failed_component)
    if "error" in cascade:
        return cascade

    all_affected = cascade["critical_path"] + cascade["degraded_path"] + cascade["optional_path"]
    layers = sorted(set(e["layer"] for e in all_affected if e.get("layer")))
    services = [e["service"] for e in all_affected]

    return {
        "failed_component": failed_component,
        "total_affected": len(all_affected),
        "critical_count": len(cascade["critical_path"]),
        "degraded_count": len(cascade["degraded_path"]),
        "optional_count": len(cascade["optional_path"]),
        "affected_layers": layers,
        "affected_services": services,
    }


@tool(name="get_dependency_path")
def get_dependency_path(source: str, target: str) -> dict:
    """Find the shortest dependency path between two nodes.

    Useful when the agent needs to explain *how* a low-level failure
    reaches a user-facing service.

    Args:
        source: Starting node name (usually the user-facing service).
        target: Ending node name (usually the failed component).

    Returns:
        Dict describing each hop in the shortest path.
    """
    driver = _get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH path = shortestPath(
                (s {name: $source})-[:DEPENDS_ON*1..10]->(t {name: $target})
            )
            RETURN [n IN nodes(path) | n.name] AS nodes,
                   [r IN relationships(path) |
                       {type: r.type, criticality: r.criticality}
                   ] AS edges
            """,
            source=source,
            target=target,
        )
        record = result.single()
    driver.close()

    if not record:
        return {"error": f"No path from '{source}' to '{target}'."}

    hops = []
    nodes = record["nodes"]
    edges = record["edges"]
    for i, edge in enumerate(edges):
        hops.append({
            "from": nodes[i],
            "to": nodes[i + 1],
            "type": edge["type"],
            "criticality": edge["criticality"],
        })

    return {"source": source, "target": target, "hops": hops, "depth": len(hops)}
