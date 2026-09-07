"""SNS trigger Lambda — invokes the Strands agent. Week 3."""
import json

def lambda_handler(event, context):
    return {"statusCode": 200, "body": json.dumps({"status": "stub"})}
