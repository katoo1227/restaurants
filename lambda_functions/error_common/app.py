import json
import boto3
import os
import time
from datetime import datetime
from dataclasses import dataclass, asdict


@dataclass
class EventParams:
    """
    イベントパラメータ構造体
    """

    function_name: str
    msg: str


def lambda_handler(event, context):

    try:

        # パラメータチェック
        params = EventParams(**event)

        # メッセージ内容
        msg = f"""
{params.msg}

関数名：{params.function_name}
イベント：{json.dumps(asdict(params))}
"""

        # ログ記載
        write_log(params.function_name, msg)

        # line_notifyの実行
        line_notify(msg)

    except Exception as e:
        # メール通知？
        print(e)

    return {
        "statusCode": 200,
        "body": "Process Complete",
    }


def write_log(function_name: str, msg: str) -> None:
    """
    CloudWatchログに記載

    Parameters
    ----------
        function_name: str
            エラーが発生したLambda関数名
        msg: str
            メッセージ
    """
    # Boto3 クライアント
    logs = boto3.client("logs")

    # ストリームがなければ作成
    res = logs.describe_log_streams(
        logGroupName=os.environ["NAME_CLOUDWATCH_LOG_GROUP"],
        logStreamNamePrefix=function_name,
        limit=1
    )
    if len(res["logStreams"]) == 0:
        logs.create_log_stream(
            logGroupName=os.environ["NAME_CLOUDWATCH_LOG_GROUP"],
            logStreamName=function_name,
        )

    # ログの記載
    logs.put_log_events(
        logGroupName=os.environ["NAME_CLOUDWATCH_LOG_GROUP"],
        logStreamName=function_name,
        logEvents=[{"timestamp": int(time.time()) * 1000, "message": msg}],
    )


def line_notify(msg: str) -> None:
    """
    LINE通知

    Parameters
    ----------
    msg: str
        エラーメッセージ
    """
    payload = {"type": 2, "msg": msg}
    boto3.client("lambda").invoke(
        FunctionName=os.environ["ARN_LAMBDA_LINE_NOTIFY"],
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
