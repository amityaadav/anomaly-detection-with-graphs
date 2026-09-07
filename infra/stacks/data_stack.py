"""EC2 (Neo4j + Redis via Docker Compose), RDS PostgreSQL, SSM parameters."""

from aws_cdk import (
    Stack,
    CfnOutput,
    SecretValue,
    aws_ec2 as ec2,
    aws_rds as rds,
    aws_ssm as ssm,
    RemovalPolicy,
    Duration,
)
from constructs import Construct


class DataStack(Stack):
    def __init__(self, scope: Construct, id: str, vpc: ec2.Vpc, ec2_sg: ec2.SecurityGroup, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        neo4j_password = self.node.try_get_context("neo4j_password") or "DemoGraph2026!"
        pg_password = self.node.try_get_context("pg_password") or "DemoPostgres2026!"

        # -----------------------------------------------------------
        # EC2 instance: Neo4j + Redis via Docker Compose
        # t3.micro = free tier eligible (750 hrs/month for 12 months)
        # -----------------------------------------------------------
        user_data = ec2.UserData.for_linux()
        user_data.add_commands(
            "yum update -y",
            "yum install -y docker",
            "systemctl start docker",
            "systemctl enable docker",
            "usermod -aG docker ec2-user",
            # Install Docker Compose v2
            'mkdir -p /usr/local/lib/docker/cli-plugins',
            'curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 '
            '-o /usr/local/lib/docker/cli-plugins/docker-compose',
            'chmod +x /usr/local/lib/docker/cli-plugins/docker-compose',
            # Create compose file
            "mkdir -p /opt/demo",
            f"""cat > /opt/demo/docker-compose.yml << 'COMPOSE'
services:
  neo4j:
    image: neo4j:5-community
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      - NEO4J_AUTH=neo4j/{neo4j_password}
      - NEO4J_server_memory_heap_initial__size=200m
      - NEO4J_server_memory_heap_max__size=200m
      - NEO4J_server_memory_pagecache_size=50m
    volumes:
      - neo4j_data:/data
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    command: redis-server --maxmemory 48mb --maxmemory-policy allkeys-lru
    restart: unless-stopped

volumes:
  neo4j_data:
COMPOSE""",
            "cd /opt/demo && docker compose up -d",
        )

        self.ec2_instance = ec2.Instance(
            self,
            "DataInstance",
            vpc=vpc,
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T3, ec2.InstanceSize.MICRO
            ),
            machine_image=ec2.AmazonLinuxImage(
                generation=ec2.AmazonLinuxGeneration.AMAZON_LINUX_2023,
            ),
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            user_data=user_data,
            security_group=ec2_sg,
        )

        # -----------------------------------------------------------
        # RDS PostgreSQL — db.t3.micro free tier (750 hrs/month)
        # -----------------------------------------------------------
        self.rds_instance = rds.DatabaseInstance(
            self,
            "DemoPostgres",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_16_4,
            ),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T3, ec2.InstanceSize.MICRO
            ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            allocated_storage=20,
            max_allocated_storage=20,
            database_name="demo",
            credentials=rds.Credentials.from_password(
                username="postgres",
                password=SecretValue.unsafe_plain_text(pg_password),
            ),
            publicly_accessible=True,  # For local dev access — lock down for production
            removal_policy=RemovalPolicy.DESTROY,
            deletion_protection=False,
            backup_retention=Duration.days(0),  # No backups — demo only
        )

        # -----------------------------------------------------------
        # SSM Parameters — endpoints for Lambdas to discover
        # -----------------------------------------------------------
        ssm.StringParameter(
            self,
            "Neo4jUri",
            parameter_name="/anomaly-demo/neo4j-uri",
            string_value=f"bolt://{self.ec2_instance.instance_public_ip}:7687",
        )

        ssm.StringParameter(
            self,
            "Neo4jPassword",
            parameter_name="/anomaly-demo/neo4j-password",
            string_value=neo4j_password,
        )

        ssm.StringParameter(
            self,
            "RedisHost",
            parameter_name="/anomaly-demo/redis-host",
            string_value=self.ec2_instance.instance_public_ip,
        )

        ssm.StringParameter(
            self,
            "PgEndpoint",
            parameter_name="/anomaly-demo/pg-endpoint",
            string_value=self.rds_instance.db_instance_endpoint_address,
        )

        ssm.StringParameter(
            self,
            "PgPassword",
            parameter_name="/anomaly-demo/pg-password",
            string_value=pg_password,
        )

        # Failure injection flags (default: disabled)
        for flag in [
            "redis2-failure",
            "pgpri-failure",
            "kafka-failure",
            "vault-failure",
            "dns-failure",
        ]:
            ssm.StringParameter(
                self,
                f"Flag-{flag}",
                parameter_name=f"/anomaly-demo/flags/{flag}",
                string_value="false",
            )

        # -----------------------------------------------------------
        # Outputs
        # -----------------------------------------------------------
        CfnOutput(self, "EC2PublicIp", value=self.ec2_instance.instance_public_ip)
        CfnOutput(
            self, "RDSEndpoint", value=self.rds_instance.db_instance_endpoint_address
        )
