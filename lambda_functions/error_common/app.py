import json
import boto3
import os
from datetime import datetime


def lambda_handler(event, context):

    try:

        # パラメータチェック
        check_params(event)

        # メッセージ内容
        msg = f"""
{event["msg"]}

関数名：{event["function_name"]}
イベント：{json.dumps(event)}
"""

        # S3バケットへのファイル追加
        put_file(event["function_name"], msg)

        # line_notifyの実行
        line_notify(msg)

    except Exception as e:
        # メール通知？
        print(e)

    return {
        "statusCode": 200,
        "body": "Process Complete",
    }


def check_params(event: dict):
    """
    パラメータチェック

    Parameters
    ----------
    event: dict
    """
    for key in ["function_name", "msg"]:
        if key not in event:
            raise Exception(f"{key}が指定されていません。{json.dumps(event)}")
        if type(event[key]) != str:
            raise Exception(f"{key}の値がstringではありません。{json.dumps(event)}")


def put_file(function_name: str, msg: str) -> None:
    """
    S3へファイルを追加

    Parameters
    ----------
    function_name: str
        エラーが起きたLambda関数名
    msg: str
        エラーメッセージ
    """
    # ファイル名
    file_name = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_{function_name}.txt"
    boto3.client("s3").put_object(
        Bucket=os.environ["NAME_S3_BUCKET_ERROR_LOGS"], Key=file_name, Body=msg
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
