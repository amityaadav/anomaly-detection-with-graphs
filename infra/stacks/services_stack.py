"""Lambda functions for domain services and the agent trigger.

Stub — will be fully implemented in week 2 when service handlers are built.
"""

from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as _lambda,
    aws_iam as iam,
    aws_ssm as ssm,
    aws_sns as sns,
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

        # Allow Lambdas to write CloudWatch logs with custom metrics
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
            )
        )

        # Domain service Lambda stubs
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
                code=_lambda.Code.from_asset(f"../services/{svc}"),
                role=lambda_role,
                timeout=Duration.seconds(30),
                memory_size=128,
                environment={
                    "SERVICE_NAME": svc,
                    "SSM_PREFIX": "/anomaly-demo",
                },
            )
            self.service_lambdas[svc] = fn

        # Agent trigger Lambda (invoked by SNS when CloudWatch alarm fires)
        self.agent_lambda = _lambda.Function(
            self,
            "Fn-agent-trigger",
            function_name="anomaly-demo-agent-trigger",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=_lambda.Code.from_asset("../agent/trigger_lambda"),
            role=lambda_role,
            timeout=Duration.seconds(120),
            memory_size=256,
            environment={
                "SSM_PREFIX": "/anomaly-demo",
            },
        )

        # Wire SNS → agent trigger
        self.alert_topic.add_subscription(
            __import__(
                "aws_cdk.aws_sns_subscriptions", fromlist=["LambdaSubscription"]
            ).LambdaSubscription(self.agent_lambda)
        )
