# Anomaly detection with graphs

An agent-powered incident triage system that uses graph traversal to diagnose cascading failures across microservices. Built to prove that graph-based dependency traversal beats flat steering files for root cause analysis — delivering deterministic paths, token efficiency, and precise blast radius identification.

## The thesis

When multiple services alert simultaneously during an incident, traditional approaches load a massive steering file describing every possible failure path into the agent's context. This project demonstrates a better approach: the agent queries a Neo4j dependency graph to traverse only the relevant nodes, finding the shared upstream root cause in seconds.

## Architecture

```
Lambda functions (10 real service stubs)
  │ real HTTP calls, real Redis/PG operations
  │ real structured CloudWatch logs
  ▼
EC2 t3.micro (Docker Compose)
  ├── Neo4j Community (dependency graph)
  └── Redis (shared cache layer)

RDS db.t3.micro
  └── PostgreSQL (shared database)

CloudWatch Alarms → SNS → Agent Lambda
                            │
                  ┌─────────┴─────────┐
                  ▼                   ▼
           Ollama Cloud         Neo4j (EC2)
          (reasoning)        (graph traversal)
                  │                   │
                  └─────────┬─────────┘
                            ▼
                   Diagnosis from real
                   logs + real graph
```

## War room scenarios

| # | Scenario | Root cause | Teams affected |
|---|----------|-----------|----------------|
| 1 | Redis cache storm | Redis Cluster 2 memory pressure | Orders, Commerce, Discovery, Pricing |
| 2 | PG pool exhaustion | PostgreSQL connection saturation | Orders, Payments, Logistics, Platform |
| 3 | Kafka partition lag | Kafka leader rebalancing | Engagement, Compliance (silent) |
| 4 | Vault rotation failure | Stale secrets post-rotation | Payments, Logistics |
| 5 | DNS resolution flap | Intermittent DNS failures | Payments, Logistics, Engagement, Commerce |

## Prerequisites

- Python 3.11+
- Node.js 18+ (for CDK)
- Docker and Docker Compose
- AWS CLI configured
- AWS CDK CLI (`npm install -g aws-cdk`)

## Local development

```bash
# Clone
git clone https://github.com/amityaadav/anomaly-detection-with-graphs.git
cd anomaly-detection-with-graphs

# Copy env template
cp .env.example .env
# Edit .env with your values

# Start local Neo4j + Redis
docker-compose up -d

# Install Python dependencies
pip install -r requirements.txt

# Seed the graph
python graph/seed.py --local

# Test agent locally
cd agent && python agent.py --scenario redis2
```

## AWS deployment

Infrastructure deploys via GitHub Actions on push to `main`. See `.github/workflows/` for details.

```bash
# Manual deploy (if needed)
cd infra
pip install -r requirements.txt
cdk bootstrap
cdk deploy --all
```

## Injecting failures

```bash
# Enable a failure scenario
python injection/inject.py --scenario redis2 --action enable

# Disable it
python injection/inject.py --scenario redis2 --action disable
```

## Cost

Designed for $0 on AWS free tier. Destroy stack when not in use:

```bash
# Via GitHub Actions: trigger the "Destroy stack" workflow
# Or manually:
cd infra && cdk destroy --all
```

## Tech stack

- **Agent framework:** Strands Agents SDK
- **LLM:** Ollama Cloud (free tier)
- **Graph database:** Neo4j Community Edition
- **Infrastructure as code:** AWS CDK (Python)
- **CI/CD:** GitHub Actions
- **Services:** AWS Lambda (Python)
- **Observability:** CloudWatch Logs + Alarms
- **Config management:** AWS SSM Parameter Store
