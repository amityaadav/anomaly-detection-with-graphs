"""VPC and security group setup."""

from aws_cdk import Stack, aws_ec2 as ec2
from constructs import Construct


class NetworkStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        allowed_ip = self.node.try_get_context("allowed_ip")
        if not allowed_ip:
            raise ValueError(
                "CDK context 'allowed_ip' is required. "
                "Deploy with: cdk deploy -c allowed_ip=YOUR.IP.HERE"
            )
        allowed_cidr = f"{allowed_ip}/32"

        self.vpc = ec2.Vpc(
            self,
            "DemoVpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
            ],
        )

        self.ec2_sg = ec2.SecurityGroup(
            self,
            "Ec2Sg",
            vpc=self.vpc,
            description="EC2 running Neo4j and Redis",
            allow_all_outbound=True,
        )

        self.ec2_sg.add_ingress_rule(
            ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            ec2.Port.tcp(7687),
            "Neo4j Bolt from VPC",
        )

        self.ec2_sg.add_ingress_rule(
            ec2.Peer.ipv4(allowed_cidr),
            ec2.Port.tcp(7474),
            "Neo4j Browser",
        )

        self.ec2_sg.add_ingress_rule(
            ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            ec2.Port.tcp(6379),
            "Redis from VPC",
        )

        self.ec2_sg.add_ingress_rule(
            ec2.Peer.ipv4(allowed_cidr),
            ec2.Port.tcp(22),
            "SSH access",
        )

        self.ec2_sg.add_ingress_rule(
            ec2.Peer.ipv4(allowed_cidr),
            ec2.Port.tcp(8501),
            "Streamlit dashboard",
        )

        self.rds_sg = ec2.SecurityGroup(
            self,
            "RdsSg",
            vpc=self.vpc,
            description="RDS PostgreSQL",
            allow_all_outbound=True,
        )

        self.rds_sg.add_ingress_rule(
            ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            ec2.Port.tcp(5432),
            "PostgreSQL from VPC",
        )
