"""Service stub — to be implemented in week 2.

See services/order/handler.py for the full pattern.
"""
import json

def lambda_handler(event, context):
    return {"statusCode": 200, "body": json.dumps({"status": "stub"})}
