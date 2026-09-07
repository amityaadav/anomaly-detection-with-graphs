"""CloudWatch alarms and metric filters for the 5 war room scenarios.

Stub — will be fully implemented in week 3.
"""

from aws_cdk import (
    Stack,
    Duration,
    aws_cloudwatch as cw,
    aws_cloudwatch_actions as cw_actions,
    aws_logs as logs,
)
from constructs import Construct


class ObservabilityStack(Stack):
    def __init__(
        self, scope: Construct, id: str, services_stack, **kwargs
    ) -> None:
        super().__init__(scope, id, **kwargs)

        alert_topic = services_stack.alert_topic

        # Create error rate alarms for key services
        # These fire when a Lambda's error count exceeds threshold
        monitored_services = [
            "order", "payment", "cart", "search", "pricing",
            "shipping", "notification", "inventory", "user",
        ]

        for svc in monitored_services:
            fn = services_stack.service_lambdas.get(svc)
            if not fn:
                continue

            # Alarm: error count > 3 in 1 minute
            alarm = cw.Alarm(
                self,
                f"Alarm-{svc}-errors",
                alarm_name=f"anomaly-demo-{svc}-errors",
                metric=fn.metric_errors(period=Duration.minutes(1)),
                threshold=3,
                evaluation_periods=1,
                comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            )

            alarm.add_alarm_action(cw_actions.SnsAction(alert_topic))
