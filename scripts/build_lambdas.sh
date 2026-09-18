#!/usr/bin/env bash
# Build Lambda deployment packages for all services.
# Each package includes: handler.py, shared/, and pip dependencies.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICES_DIR="$REPO_ROOT/services"
BUILD_DIR="$REPO_ROOT/.build"

SERVICES=(order payment cart inventory shipping user search notification pricing recommendation)

rm -rf "$BUILD_DIR"

for svc in "${SERVICES[@]}"; do
    dest="$BUILD_DIR/$svc"
    mkdir -p "$dest"

    # Copy handler
    cp "$SERVICES_DIR/$svc/handler.py" "$dest/"

    # Copy shared module
    cp -r "$SERVICES_DIR/shared" "$dest/shared"

    # Determine pip dependencies from imports
    deps=""
    if grep -q "import redis" "$SERVICES_DIR/$svc/handler.py"; then
        deps="$deps redis"
    fi
    if grep -q "import psycopg2" "$SERVICES_DIR/$svc/handler.py"; then
        deps="$deps psycopg2-binary"
    fi
    if grep -q "import requests" "$SERVICES_DIR/$svc/handler.py"; then
        deps="$deps requests"
    fi

    if [ -n "$deps" ]; then
        pip install --target "$dest" --quiet --upgrade $deps
    fi

    echo "Built: $svc (deps:${deps:- none})"
done

echo "All packages built in $BUILD_DIR/"
