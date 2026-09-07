"""VPC and security group setup for the demo."""

from aws_cdk import Stack, aws_ec2 as ec2
from constructs import Construct


class NetworkStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # VPC with public + private subnets (free tier: no NAT Gateway)
        # Using a single public subnet to avoid NAT Gateway charges ($0.045/hr)
        self.vpc = ec2.Vpc(
            self,
            "DemoVpc",
            max_azs=2,
            nat_gateways=0,  # Avoid charges — Lambdas use public subnets
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
            ],
        )

        # Security group for EC2 (Neo4j + Redis)
        self.ec2_sg = ec2.SecurityGroup(
            self,
            "Ec2Sg",
            vpc=self.vpc,
            description="EC2 running Neo4j and Redis",
            allow_all_outbound=True,
        )

        # Neo4j Bolt
        self.ec2_sg.add_ingress_rule(
            ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            ec2.Port.tcp(7687),
            "Neo4j Bolt from VPC",
        )

        # Neo4j Browser (for local dev — restrict to your IP in production)
        self.ec2_sg.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(7474),
            "Neo4j Browser",
        )

        # Redis
        self.ec2_sg.add_ingress_rule(
            ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            ec2.Port.tcp(6379),
            "Redis from VPC",
        )

        # SSH (restrict to your IP in production)
        self.ec2_sg.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(22),
            "SSH access",
        )

        # Security group for RDS
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
