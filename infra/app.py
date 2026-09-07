#!/usr/bin/env python3
"""CDK app entry point — wires all stacks together."""

import aws_cdk as cdk

from stacks.network_stack import NetworkStack
from stacks.data_stack import DataStack
from stacks.services_stack import ServicesStack
from stacks.observability_stack import ObservabilityStack

app = cdk.App()

env = cdk.Environment(
    account=app.node.try_get_context("account") or None,
    region=app.node.try_get_context("region") or "us-east-1",
)

network = NetworkStack(app, "AnomalyDemo-Network", env=env)

data = DataStack(
    app,
    "AnomalyDemo-Data",
    vpc=network.vpc,
    env=env,
)

services = ServicesStack(
    app,
    "AnomalyDemo-Services",
    vpc=network.vpc,
    data_stack=data,
    env=env,
)

observability = ObservabilityStack(
    app,
    "AnomalyDemo-Observability",
    services_stack=services,
    env=env,
)

app.synth()
