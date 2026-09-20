"""Lambda functions for domain services and the agent trigger."""

import os

from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as _lambda,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_sns as sns,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct


class ServicesStack(Stack):
    def __init__(
        self, scope: Construct, id: str, vpc, data_stack, **kwargs
    ) -> None:
        super().__init__(scope, id, **kwargs)

        # SNS topic for CloudWatch alarms to trigger the agent
        self.alert_topic = sns.Topic(
            self,
            "AlertTopic",
            topic_name="anomaly-demo-alerts",
        )

        # Shared Lambda execution role
        lambda_role = iam.Role(
            self,
            "LambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole"
                ),
            ],
        )

        # Allow Lambdas to read SSM parameters
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter", "ssm:GetParametersByPath"],
                resources=[f"arn:aws:ssm:*:{self.account}:parameter/anomaly-demo/*"],
            )
        )

        # Allow Lambdas to read secrets from Secrets Manager at runtime
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    f"arn:aws:secretsmanager:*:{self.account}:secret:anomaly-demo/*",
                ],
            )
        )

        # cloudwatch:PutMetricData does not support resource-level permissions
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
                conditions={
                    "StringEquals": {
                        "cloudwatch:namespace": "AnomalyDemo",
                    }
                },
            )
        )

        # Security group for Lambda functions inside the VPC
        lambda_sg = ec2.SecurityGroup(
            self,
            "LambdaSg",
            vpc=vpc,
            description="Lambda functions - outbound to VPC resources",
            allow_all_outbound=True,
        )

        # Domain service Lambda stubs
        # Secrets (PG, Neo4j, Redis passwords) are read at runtime via
        # Secrets Manager — never passed as env vars.
        service_names = [
            "order", "payment", "cart", "inventory", "shipping",
            "user", "search", "notification", "pricing", "recommendation",
        ]

        self.service_lambdas = {}
        for svc in service_names:
            fn = _lambda.Function(
                self,
                f"Fn-{svc}",
                function_name=f"anomaly-demo-{svc}",
                runtime=_lambda.Runtime.PYTHON_3_12,
                handler="handler.lambda_handler",
                code=_lambda.Code.from_asset(f"../.build/{svc}"),
                role=lambda_role,
                vpc=vpc,
                vpc_subnets=ec2.SubnetSelection(
                    subnet_type=ec2.SubnetType.PUBLIC,
                ),
                security_groups=[lambda_sg],
                allow_public_subnet=True,
                timeout=Duration.seconds(30),
                memory_size=128,
                environment={
                    "SERVICE_NAME": svc,
                    "SSM_PREFIX": "/anomaly-demo",
                    "REDIS_HOST": data_stack.ec2_instance.instance_private_ip,
                    "PG_ENDPOINT": data_stack.rds_instance.db_instance_endpoint_address,
                    "NEO4J_URI": f"bolt://{data_stack.ec2_instance.instance_private_ip}:7687",
                },
            )
            self.service_lambdas[svc] = fn

        # Ollama API key — stored in Secrets Manager, read at runtime by agent
        ollama_api_key = (
            os.environ.get("OLLAMA_API_KEY")
            or self.node.try_get_context("ollama_api_key")
            or "none"
        )
        secretsmanager.CfnSecret(
            self,
            "OllamaApiKey",
            name="anomaly-demo/ollama-credentials",
            secret_string=f'{{"api_key":"{ollama_api_key}"}}',
            description="Ollama Cloud API key for the triage agent",
        )

        # Agent trigger Lambda (invoked by SNS when CloudWatch alarm fires)
        agent_role = iam.Role(
            self,
            "AgentLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole"
                ),
            ],
        )
        agent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter", "ssm:GetParametersByPath"],
                resources=[f"arn:aws:ssm:*:{self.account}:parameter/anomaly-demo/*"],
            )
        )
        agent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    f"arn:aws:secretsmanager:*:{self.account}:secret:anomaly-demo/*",
                ],
            )
        )
        agent_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:StartQuery",
                    "logs:GetQueryResults",
                    "logs:DescribeLogGroups",
                ],
                resources=[
                    f"arn:aws:logs:*:{self.account}:log-group:/aws/lambda/anomaly-demo-*",
                    f"arn:aws:logs:*:{self.account}:log-group:/aws/lambda/anomaly-demo-*:*",
                ],
            )
        )

        self.agent_lambda = _lambda.Function(
            self,
            "Fn-agent-trigger",
            function_name="anomaly-demo-agent-trigger",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=_lambda.Code.from_asset("../agent/trigger_lambda"),
            role=agent_role,
            timeout=Duration.seconds(120),
            memory_size=256,
            environment={
                "SSM_PREFIX": "/anomaly-demo",
                "OLLAMA_MODEL": "qwen3:32b",
                "OLLAMA_HOST": "https://api.ollama.com",
            },
        )

        # Wire SNS -> agent trigger
        self.alert_topic.add_subscription(
            __import__(
                "aws_cdk.aws_sns_subscriptions", fromlist=["LambdaSubscription"]
            ).LambdaSubscription(self.agent_lambda)
        )
