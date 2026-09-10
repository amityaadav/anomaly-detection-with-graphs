"""Streamlit dashboard for the anomaly detection demo.

Provides four views:
1. Dependency Graph — interactive visualization of the Neo4j service graph
2. Failure Injection — toggle failure scenarios via SSM flags
3. Service Health — invoke Lambdas and see structured log output
4. Agent Triage — trigger the Strands agent and display the incident report

Run locally:
    streamlit run dashboard/app.py

Path: dashboard/app.py
"""

import json
import os
import sys
import time

import boto3
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

st.set_page_config(page_title="Anomaly Detection Demo", layout="wide")

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


@st.cache_resource
def get_ssm_client():
    return boto3.client("ssm", region_name=AWS_REGION)


@st.cache_resource
def get_lambda_client():
    return boto3.client("lambda", region_name=AWS_REGION)


@st.cache_resource
def get_neo4j_driver():
    from neo4j import GraphDatabase
    ssm = get_ssm_client()
    prefix = os.environ.get("SSM_PREFIX", "/anomaly-demo")
    uri = ssm.get_parameter(Name=f"{prefix}/neo4j-uri", WithDecryption=True)["Parameter"]["Value"]
    password = ssm.get_parameter(Name=f"{prefix}/neo4j-password", WithDecryption=True)["Parameter"]["Value"]
    return GraphDatabase.driver(uri, auth=("neo4j", password))


def load_scenarios() -> dict:
    path = os.path.join(os.path.dirname(__file__), "..", "injection", "scenarios.json")
    with open(path) as f:
        return json.load(f)["scenarios"]


# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------
st.sidebar.title("Anomaly Detection")
page = st.sidebar.radio(
    "Navigate",
    ["Dependency Graph", "Failure Injection", "Service Health", "Agent Triage"],
)

# ---------------------------------------------------------------------------
# Page 1: Dependency Graph
# ---------------------------------------------------------------------------
if page == "Dependency Graph":
    st.header("Service Dependency Graph")
    st.caption("36 nodes across 6 architectural layers — data from Neo4j")

    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            nodes_result = session.run(
                "MATCH (n) RETURN n.id AS id, n.name AS name, n.layer AS layer, labels(n) AS labels"
            )
            nodes = [dict(r) for r in nodes_result]

            edges_result = session.run(
                """
                MATCH (a)-[r]->(b)
                RETURN a.id AS source, b.id AS target,
                       type(r) AS rel_type,
                       r.type AS dep_type,
                       r.criticality AS criticality
                """
            )
            edges = [dict(r) for r in edges_result]

        layer_order = ["edge", "domain", "platform", "middleware", "storage", "external"]
        layer_colors = {
            "edge": "#4A90D9",
            "domain": "#50C878",
            "platform": "#FF8C42",
            "middleware": "#9B59B6",
            "storage": "#E74C3C",
            "external": "#95A5A6",
        }

        col1, col2 = st.columns([2, 1])

        with col1:
            st.subheader("Nodes by Layer")
            for layer in layer_order:
                layer_nodes = [n for n in nodes if n["layer"] == layer]
                if layer_nodes:
                    color = layer_colors.get(layer, "#888")
                    st.markdown(
                        f"**{layer.upper()}** "
                        f"<span style='color:{color}'>({len(layer_nodes)} nodes)</span>",
                        unsafe_allow_html=True,
                    )
                    cols = st.columns(min(len(layer_nodes), 5))
                    for i, node in enumerate(layer_nodes):
                        with cols[i % 5]:
                            st.markdown(
                                f"<div style='background:{color}22; border-left:3px solid {color}; "
                                f"padding:8px; margin:4px 0; border-radius:4px;'>"
                                f"<strong>{node['name']}</strong><br/>"
                                f"<small>{node['id']}</small></div>",
                                unsafe_allow_html=True,
                            )

        with col2:
            st.subheader("Graph Stats")
            st.metric("Total Nodes", len(nodes))
            st.metric("Total Edges", len(edges))
            st.metric("Layers", len(layer_order))

            st.subheader("Edge Types")
            crit_counts = {}
            for e in edges:
                c = e.get("criticality", "unknown")
                crit_counts[c] = crit_counts.get(c, 0) + 1
            for crit, count in sorted(crit_counts.items()):
                if crit:
                    st.markdown(f"- **{crit}**: {count}")

        st.subheader("Dependency Explorer")
        node_names = sorted([n["id"] for n in nodes])
        selected = st.selectbox("Select a node to see its dependencies", node_names)

        if selected:
            with driver.session() as session:
                deps_result = session.run(
                    """
                    MATCH (s {id: $id})-[r:DEPENDS_ON]->(dep)
                    RETURN dep.id AS target, dep.name AS name,
                           r.type AS type, r.criticality AS criticality
                    ORDER BY r.criticality
                    """,
                    id=selected,
                )
                deps = [dict(r) for r in deps_result]

                upstream_result = session.run(
                    """
                    MATCH (upstream)-[r:DEPENDS_ON]->(s {id: $id})
                    RETURN upstream.id AS source, upstream.name AS name,
                           r.type AS type, r.criticality AS criticality
                    ORDER BY r.criticality
                    """,
                    id=selected,
                )
                upstreams = [dict(r) for r in upstream_result]

            dep_col, up_col = st.columns(2)
            with dep_col:
                st.markdown(f"**{selected}** depends on ({len(deps)}):")
                for d in deps:
                    icon = "🔴" if d["criticality"] == "critical" else "🟡" if d["criticality"] == "degraded" else "⚪"
                    st.markdown(f"{icon} **{d['name']}** — {d['type']} ({d['criticality']})")

            with up_col:
                st.markdown(f"Services depending on **{selected}** ({len(upstreams)}):")
                for u in upstreams:
                    icon = "🔴" if u["criticality"] == "critical" else "🟡" if u["criticality"] == "degraded" else "⚪"
                    st.markdown(f"{icon} **{u['name']}** — {u['type']} ({u['criticality']})")

    except Exception as e:
        st.error(f"Could not connect to Neo4j: {e}")
        st.info("Make sure NEO4J_URI and credentials are configured in SSM Parameter Store.")

# ---------------------------------------------------------------------------
# Page 2: Failure Injection
# ---------------------------------------------------------------------------
elif page == "Failure Injection":
    st.header("Failure Injection Control Panel")
    st.caption("Toggle failure scenarios on/off — changes take effect immediately via SSM flags")

    scenarios = load_scenarios()
    ssm = get_ssm_client()

    for scenario_id, scenario in scenarios.items():
        with st.expander(f"**{scenario['name']}** — {scenario_id}", expanded=False):
            st.markdown(scenario["description"])

            flags = scenario["ssm_flags"]
            flag_name = list(flags.keys())[0]

            try:
                resp = ssm.get_parameter(Name=flag_name)
                current = resp["Parameter"]["Value"].lower() == "true"
            except Exception:
                current = False

            status_text = "🔴 ACTIVE" if current else "🟢 Inactive"
            st.markdown(f"**Status:** {status_text}")

            st.markdown("**Expected symptoms:**")
            for symptom in scenario["expected_symptoms"]:
                icon = "❌" if symptom["type"] == "error" else "⚠️" if symptom["type"] in ("degraded", "timeout") else "✅"
                st.markdown(f"- {icon} **{symptom['service']}**: {symptom['message']}")

            col_on, col_off = st.columns(2)
            with col_on:
                if st.button(f"Inject {scenario_id}", key=f"inject_{scenario_id}", type="primary"):
                    for param, value in flags.items():
                        ssm.put_parameter(Name=param, Value=value, Type="String", Overwrite=True)
                    st.success(f"Failure '{scenario['name']}' injected.")
                    st.rerun()
            with col_off:
                if st.button(f"Clear {scenario_id}", key=f"clear_{scenario_id}"):
                    for param in flags:
                        ssm.put_parameter(Name=param, Value="false", Type="String", Overwrite=True)
                    st.success(f"Failure '{scenario['name']}' cleared.")
                    st.rerun()

    st.divider()
    col_all_on, col_all_off = st.columns(2)
    with col_all_on:
        if st.button("Inject ALL scenarios", type="primary"):
            for scenario in scenarios.values():
                for param, value in scenario["ssm_flags"].items():
                    ssm.put_parameter(Name=param, Value=value, Type="String", Overwrite=True)
            st.success("All failure scenarios injected.")
            st.rerun()
    with col_all_off:
        if st.button("Clear ALL scenarios"):
            for scenario in scenarios.values():
                for param in scenario["ssm_flags"]:
                    ssm.put_parameter(Name=param, Value="false", Type="String", Overwrite=True)
            st.success("All failure scenarios cleared.")
            st.rerun()

# ---------------------------------------------------------------------------
# Page 3: Service Health
# ---------------------------------------------------------------------------
elif page == "Service Health":
    st.header("Service Health Check")
    st.caption("Invoke each Lambda and see its response")

    services = [
        "order", "payment", "cart", "inventory", "shipping",
        "user", "search", "notification", "pricing", "recommendation",
    ]

    test_events = {
        "order": {"action": "create", "user_id": "test-user", "items": [{"product_id": "p1", "quantity": 1}]},
        "payment": {"order_id": "test-order", "amount": 29.99, "currency": "USD"},
        "cart": {"action": "get", "user_id": "test-user"},
        "inventory": {"action": "check", "product_id": "test-product"},
        "shipping": {"order_id": "test-order", "destination": {"zip": "21201"}},
        "user": {"action": "get", "user_id": "test-user"},
        "search": {"query": "test product"},
        "notification": {"type": "email", "recipient": "test@example.com", "template_id": "welcome"},
        "pricing": {"product_id": "test-product", "quantity": 1},
        "recommendation": {"user_id": "test-user", "limit": 3},
    }

    if st.button("Check All Services", type="primary"):
        lambda_client = get_lambda_client()
        progress = st.progress(0)

        for i, svc in enumerate(services):
            progress.progress((i + 1) / len(services))
            col_name, col_status, col_detail = st.columns([1, 1, 3])

            with col_name:
                st.markdown(f"**{svc}**")

            try:
                resp = lambda_client.invoke(
                    FunctionName=f"anomaly-demo-{svc}",
                    InvocationType="RequestResponse",
                    Payload=json.dumps(test_events.get(svc, {})),
                )
                payload = json.loads(resp["Payload"].read())
                status_code = payload.get("statusCode", 0)

                with col_status:
                    if status_code == 200:
                        st.success("200 OK")
                    else:
                        st.error(f"{status_code}")

                with col_detail:
                    body = json.loads(payload.get("body", "{}"))
                    if "error" in body:
                        st.markdown(f"❌ `{body['error'][:100]}`")
                    else:
                        st.json(body)

            except Exception as e:
                with col_status:
                    st.error("FAIL")
                with col_detail:
                    st.markdown(f"❌ `{str(e)[:100]}`")

        progress.empty()

# ---------------------------------------------------------------------------
# Page 4: Agent Triage
# ---------------------------------------------------------------------------
elif page == "Agent Triage":
    st.header("Agent Triage")
    st.caption("Trigger the Strands agent to diagnose a failure scenario")

    scenarios = load_scenarios()
    scenario_names = {sid: s["name"] for sid, s in scenarios.items()}

    selected_scenario = st.selectbox(
        "Select a failure scenario to diagnose",
        options=list(scenario_names.keys()),
        format_func=lambda x: f"{x} — {scenario_names[x]}",
    )

    scenario = scenarios[selected_scenario]
    st.markdown(f"**Description:** {scenario['description']}")
    st.markdown(f"**Expected root cause:** `{scenario['expected_root_cause']}`")
    st.markdown(f"**Affected services:** {', '.join(scenario['affected_services'])}")

    st.divider()

    col_inject, col_triage = st.columns(2)

    with col_inject:
        st.subheader("Step 1: Inject Failure")
        if st.button("Inject this scenario", key="triage_inject", type="primary"):
            ssm = get_ssm_client()
            for param, value in scenario["ssm_flags"].items():
                ssm.put_parameter(Name=param, Value=value, Type="String", Overwrite=True)
            st.success(f"Injected: {scenario['name']}")

    with col_triage:
        st.subheader("Step 2: Run Triage Agent")
        if st.button("Invoke Agent", key="triage_run", type="primary"):
            lambda_client = get_lambda_client()

            alarm_sns_event = {
                "Records": [{
                    "Sns": {
                        "Message": json.dumps({
                            "AlarmName": f"anomaly-demo-{scenario['expected_root_cause']}-failure",
                            "AlarmDescription": scenario["description"],
                            "NewStateValue": "ALARM",
                            "Trigger": {
                                "MetricName": "Errors",
                                "Dimensions": [{
                                    "name": "FunctionName",
                                    "value": f"anomaly-demo-{scenario['affected_services'][0]}",
                                }],
                            },
                        })
                    }
                }]
            }

            with st.spinner("Agent is diagnosing the incident..."):
                try:
                    resp = lambda_client.invoke(
                        FunctionName="anomaly-demo-agent-trigger",
                        InvocationType="RequestResponse",
                        Payload=json.dumps(alarm_sns_event),
                    )
                    payload = json.loads(resp["Payload"].read())
                    body = json.loads(payload.get("body", "{}"))

                    if "report" in body:
                        st.subheader("Incident Report")
                        st.markdown(body["report"])
                    elif "error" in body:
                        st.error(f"Agent error: {body['error']}")
                    else:
                        st.json(body)

                except Exception as e:
                    st.error(f"Failed to invoke agent: {e}")

    st.divider()
    if st.button("Clear this scenario", key="triage_clear"):
        ssm = get_ssm_client()
        for param in scenario["ssm_flags"]:
            ssm.put_parameter(Name=param, Value="false", Type="String", Overwrite=True)
        st.success(f"Cleared: {scenario['name']}")
