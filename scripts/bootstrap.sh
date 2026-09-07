#!/bin/bash
set -e
echo "=== Anomaly Detection Demo — Bootstrap ==="
echo "1. Checking prerequisites..."
python3 --version || { echo "Python 3.11+ required"; exit 1; }
node --version || { echo "Node 18+ required"; exit 1; }
docker --version || { echo "Docker required"; exit 1; }
aws --version || { echo "AWS CLI required"; exit 1; }
echo "2. Installing Python dependencies..."
python3 -m pip install -r requirements.txt
echo "3. Starting local Docker services..."
docker compose up -d
echo "4. Waiting for Neo4j to be ready..."
sleep 15
echo "5. Seeding the graph..."
python graph/seed.py --local
echo "=== Bootstrap complete ==="
echo "Neo4j Browser: http://localhost:7474"
echo "Redis: localhost:6379"
echo "PostgreSQL: localhost:5432"
