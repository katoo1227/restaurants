import boto3
import os
import json
import requests
import urllib.parse
import re
from datetime import datetime, time, timedelta


def lambda_handler(event, context):

    # Lambdaクライアント
    lambda_client = boto3.client("lambda")

    try:
        pass
    except Exception as e:
        msg = f"""
{str(e)}

関数名：{context.function_name}
イベント：{json.dumps(event)}
"""
        payload = {"type": 2, "msg": msg}
        lambda_client.invoke(
            FunctionName=os.environ["ARN_LAMBDA_LINE_NOTIFY"],
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode("utf-8"),
        )

    return {
        "statusCode": 200,
        "body": "Process Complete",
    }