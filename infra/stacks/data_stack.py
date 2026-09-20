"""EC2 (Neo4j + Redis via Docker Compose), RDS PostgreSQL, SSM parameters."""

from aws_cdk import (
    Stack,
    CfnOutput,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_rds as rds,
    aws_ssm as ssm,
    aws_secretsmanager as secretsmanager,
    RemovalPolicy,
    Duration,
)
from constructs import Construct


class DataStack(Stack):
    def __init__(
        self, scope: Construct, id: str,
        vpc: ec2.Vpc, ec2_sg: ec2.SecurityGroup, rds_sg: ec2.SecurityGroup,
        **kwargs,
    ) -> None:
        super().__init__(scope, id, **kwargs)

        neo4j_password = self.node.try_get_context("neo4j_password")
        if not neo4j_password:
            raise ValueError(
                "CDK context 'neo4j_password' is required. "
                "Deploy with: cdk deploy -c neo4j_password=YOUR_PASSWORD"
            )

        self.pg_secret = secretsmanager.Secret(
            self,
            "PgCredentials",
            secret_name="anomaly-demo/rds-credentials",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"username":"postgres"}',
                generate_string_key="password",
                exclude_punctuation=True,
                password_length=32,
            ),
        )

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

        key_pair = ec2.KeyPair(
            self,
            "DataInstanceKeyPair",
            key_pair_name="anomaly-demo-ec2-key",
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
            key_pair=key_pair,
            require_imdsv2=True,
        )

        self.ec2_instance.role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter", "ssm:PutParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/anomaly-demo/*"
                ],
            )
        )

        self.ec2_instance.role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[
                    f"arn:aws:lambda:{self.region}:{self.account}:function:anomaly-demo-*"
                ],
            )
        )

        self.pg_secret.grant_read(self.ec2_instance.role)

        # Elastic IP - stable public address across stop/start cycles (free while attached)
        eip = ec2.CfnEIP(self, "DataInstanceEIP", domain="vpc")
        ec2.CfnEIPAssociation(
            self, "DataInstanceEIPAssoc",
            allocation_id=eip.attr_allocation_id,
            instance_id=self.ec2_instance.instance_id,
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
            security_groups=[rds_sg],
            allocated_storage=20,
            max_allocated_storage=20,
            database_name="demo",
            credentials=rds.Credentials.from_secret(self.pg_secret),
            publicly_accessible=False,
            storage_encrypted=True,
            removal_policy=RemovalPolicy.DESTROY,
            deletion_protection=False,
            backup_retention=Duration.days(1),
        )

        # -----------------------------------------------------------
        # Auto-setup: tools, repo, graph seeding, DB schema, Streamlit
        # Runs once on instance creation; on stop/start Docker and
        # systemd handle restarts automatically.
        # -----------------------------------------------------------
        user_data.add_commands(
            "yum install -y git python3-pip",
            "git clone https://github.com/amityaadav/anomaly-detection-with-graphs.git"
            " /home/ec2-user/anomaly-detection-with-graphs || true",
            "chown -R ec2-user:ec2-user /home/ec2-user/anomaly-detection-with-graphs",
            "pip3 install streamlit neo4j boto3 psycopg2-binary",
        )

        # Wait for Neo4j container, then seed the graph
        user_data.add_commands(
            'for i in $(seq 1 30); do'
            ' curl -sf http://localhost:7474 > /dev/null 2>&1 && break;'
            ' echo "Waiting for Neo4j ($i/30)..."; sleep 10; done',
            "cd /home/ec2-user/anomaly-detection-with-graphs &&"
            " python3 graph/seed_http.py --host localhost --from-ssm"
            " || echo 'Neo4j seeding deferred - seed manually after deploy'",
        )

        # Create PostgreSQL orders table (retries while RDS provisions)
        user_data.add_commands(
            f"export PG_HOST={self.rds_instance.db_instance_endpoint_address}",
            "python3 << 'PYEOF'",
            "import psycopg2, boto3, os, time, json",
            "sm = boto3.client('secretsmanager', region_name='us-east-1')",
            "for attempt in range(12):",
            "    try:",
            "        secret = json.loads(sm.get_secret_value(",
            "            SecretId='anomaly-demo/rds-credentials')['SecretString'])",
            "        pw = secret['password']",
            "        conn = psycopg2.connect(host=os.environ['PG_HOST'], port=5432,",
            "            dbname='demo', user='postgres', password=pw, connect_timeout=10)",
            "        cur = conn.cursor()",
            "        cur.execute('CREATE TABLE IF NOT EXISTS orders "
            "(id TEXT PRIMARY KEY, payload JSONB, created_at TIMESTAMPTZ DEFAULT NOW())')",
            "        conn.commit(); conn.close()",
            "        print('Orders table ready'); exit(0)",
            "    except Exception as e:",
            "        print(f'DB setup attempt {attempt+1}/12: {e}')",
            "        time.sleep(10)",
            "print('DB setup deferred'); exit(0)",
            "PYEOF",
        )

        # Streamlit dashboard as a systemd service (auto-starts on boot)
        user_data.add_commands(
            "cat > /etc/systemd/system/streamlit.service << 'SVCEOF'",
            "[Unit]",
            "Description=Streamlit Dashboard",
            "After=network.target docker.service",
            "Wants=docker.service",
            "",
            "[Service]",
            "Type=simple",
            "User=ec2-user",
            "WorkingDirectory=/home/ec2-user/anomaly-detection-with-graphs/dashboard",
            "Environment=NEO4J_URI=bolt://localhost:7687",
            "Environment=SSM_PREFIX=/anomaly-demo",
            "Environment=AWS_DEFAULT_REGION=us-east-1",
            "ExecStart=/usr/local/bin/streamlit run app.py"
            " --server.port 8501 --server.address 0.0.0.0 --server.headless true",
            "Restart=always",
            "RestartSec=5",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "SVCEOF",
            "systemctl daemon-reload",
            "systemctl enable streamlit",
            "systemctl start streamlit",
        )

        # -----------------------------------------------------------
        # SSM Parameters — endpoints for Lambdas to discover
        # -----------------------------------------------------------
        ssm.StringParameter(
            self,
            "Neo4jUri",
            parameter_name="/anomaly-demo/neo4j-uri",
            string_value=f"bolt://{eip.ref}:7687",
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
            string_value=eip.ref,
        )

        ssm.StringParameter(
            self,
            "PgEndpoint",
            parameter_name="/anomaly-demo/pg-endpoint",
            string_value=self.rds_instance.db_instance_endpoint_address,
        )

        ssm.StringParameter(
            self,
            "PgSecretArn",
            parameter_name="/anomaly-demo/pg-secret-arn",
            string_value=self.pg_secret.secret_arn,
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
        CfnOutput(self, "EC2PublicIp", value=eip.ref)
        CfnOutput(
            self, "RDSEndpoint", value=self.rds_instance.db_instance_endpoint_address
        )
        CfnOutput(
            self,
            "EC2KeyPairId",
            value=key_pair.key_pair_id,
            description="Retrieve private key: aws ssm get-parameter "
            "--name /ec2/keypair/<this-value> --with-decryption "
            "--query Parameter.Value --output text",
        )
