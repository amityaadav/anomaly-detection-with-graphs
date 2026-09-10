"""Strands agent for incident triage of cascading microservice failures.

This agent combines Neo4j graph traversal with CloudWatch log analysis
to diagnose the root cause when a CloudWatch alarm fires.  It:

1. Receives an alarm payload (service name, metric, description).
2. Queries the dependency graph to understand what the failing service
   depends on and what depends on it.
3. Pulls recent error logs from CloudWatch to find the actual failures.
4. Traces the cascade path to identify the root cause.
5. Produces a structured incident report with root cause, blast radius,
   and recommended remediation.

Model: Ollama Cloud (qwen3:32b) via the Strands OllamaModel provider.
"""

import os

import boto3
from strands import Agent
from strands.models.ollama import OllamaModel

_ssm = boto3.client("ssm")
SSM_PREFIX = os.environ.get("SSM_PREFIX", "/anomaly-demo")

from tools.neo4j_tool import (
    get_service_info,
    trace_cascade,
    get_blast_radius,
    get_dependency_path,
)
from tools.cloudwatch_tool import (
    get_recent_errors,
    get_latency_stats,
    get_dependency_errors,
)

SYSTEM_PROMPT = """You are an expert Site Reliability Engineer (SRE) agent that
triages incidents in a microservices architecture. You have access to two sets
of tools:

**Graph tools** (Neo4j):
- get_service_info: Look up a service and its direct dependencies.
- trace_cascade: Find all services affected when a component fails.
- get_blast_radius: Get summary counts of affected services and layers.
- get_dependency_path: Find the shortest path between two services.

**Log tools** (CloudWatch):
- get_recent_errors: Fetch error/degraded logs for a specific service.
- get_latency_stats: Get latency percentiles for a service.
- get_dependency_errors: Search all services for errors involving a dependency.

When you receive an alarm, follow this diagnostic workflow:

1. IDENTIFY: Parse the alarm to determine which service or component triggered it.
2. INVESTIGATE: Use get_recent_errors on the alarming service to see what's failing.
3. TRACE DEPENDENCIES: Use get_service_info to understand what the service depends on.
4. FIND ROOT CAUSE: If errors mention a dependency, use get_dependency_errors to check
   if that dependency is failing across multiple services. Work your way down the
   dependency chain until you find the component where errors originate.
5. ASSESS IMPACT: Use get_blast_radius on the root cause to understand the full impact.
6. EXPLAIN THE PATH: Use get_dependency_path to show how the root cause reaches
   the originally alarming service.

Produce a structured incident report with these sections:

**Incident Summary**
- Triggering alarm and affected service
- Severity assessment (P1/P2/P3/P4)

**Root Cause**
- The component where the failure originates
- What type of failure it is (connection_pool_exhausted, dns_resolution_failed, etc.)

**Blast Radius**
- Total services affected (critical vs. degraded vs. optional)
- Which architectural layers are impacted
- The cascade path from root cause to the triggering service

**Remediation**
- Immediate actions to restore service
- Longer-term fixes to prevent recurrence

Keep your analysis concise and actionable. Use the tools systematically — don't guess
when you can query the graph or logs."""


def create_agent() -> Agent:
    """Create and return the triage agent with all tools wired up.

    The Ollama Cloud API key is read from SSM Parameter Store at
    runtime (/anomaly-demo/ollama-api-key).  Host and model come
    from environment variables (non-secret).

    Returns:
        A configured Strands Agent ready to receive incident prompts.

    Path: agent/agent.py
    """
    ollama_host = os.environ.get("OLLAMA_HOST", "https://api.ollama.com")
    model_id = os.environ.get("OLLAMA_MODEL", "qwen3:32b")

    resp = _ssm.get_parameter(
        Name=f"{SSM_PREFIX}/ollama-api-key", WithDecryption=True,
    )
    api_key = resp["Parameter"]["Value"]

    model = OllamaModel(
        host=ollama_host,
        model_id=model_id,
        ollama_client_args={"headers": {"Authorization": f"Bearer {api_key}"}} if api_key else None,
        max_tokens=4096,
        temperature=0.1,
    )

    agent = Agent(
        model=model,
        tools=[
            get_service_info,
            trace_cascade,
            get_blast_radius,
            get_dependency_path,
            get_recent_errors,
            get_latency_stats,
            get_dependency_errors,
        ],
        system_prompt=SYSTEM_PROMPT,
    )

    return agent


def run_triage(alarm_payload: dict) -> str:
    """Run the triage agent on an alarm payload and return the report.

    This is the main entry point called by the trigger Lambda.

    Args:
        alarm_payload: Dict with keys like 'service', 'alarm_name',
            'description', 'metric', 'state'.

    Returns:
        The agent's incident report as a string.

    Path: agent/agent.py
    """
    agent = create_agent()

    prompt = (
        f"A CloudWatch alarm has fired. Triage this incident:\n\n"
        f"Alarm Name: {alarm_payload.get('alarm_name', 'unknown')}\n"
        f"Service: {alarm_payload.get('service', 'unknown')}\n"
        f"Description: {alarm_payload.get('description', 'No description')}\n"
        f"Metric: {alarm_payload.get('metric', 'unknown')}\n"
        f"Current State: {alarm_payload.get('state', 'ALARM')}\n\n"
        f"Diagnose the root cause, assess the blast radius, and provide "
        f"a remediation plan."
    )

    result = agent(prompt)
    return str(result)
