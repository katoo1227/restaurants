import json
import requests
import textwrap
import boto3

# 通知タイプ：通常
NOTIFY_TYPE_NORMAL = 1

# 通知タイプ：エラー
NOTIFY_TYPE_ERROR = 2

# 通知タイプ：警告
NOTIFY_TYPE_WARNING = 3

# 一度に送れる最大文字数
MAX_STR_LENGTH = 1000

# Notify URL
NOTIFY_URL = "https://notify-api.line.me/api/notify"


def lambda_handler(event, context):

    try:

        # パラメータが不正なら終了
        if "type" not in event or "msg" not in event:
            raise Exception(f"パラメータが不正です。{json.dumps(event)}")

        # typeの値チェック
        if event["type"] not in [NOTIFY_TYPE_NORMAL, NOTIFY_TYPE_ERROR, NOTIFY_TYPE_WARNING]:
            raise Exception(f"typeの値が不正です。{json.dumps(event)}")

        # LINE Notifyトークンを取得
        if event["type"] == NOTIFY_TYPE_NORMAL:
            token_path = "/line_notify/restaurants/token"
        elif event["type"] == NOTIFY_TYPE_ERROR:
            token_path = "/line_notify/error_notify/token"
        else:
            token_path = "/line_notify/warning_notify/token"
        res = boto3.client("ssm").get_parameter(Name=token_path, WithDecryption=True)
        token = res["Parameter"]["Value"]

        # 通知
        requests.post(
            NOTIFY_URL,
            headers={"Authorization": f"Bearer {token}"},
            data={"message": arrangeNotifyMsg(event["msg"])},
        )

    except Exception as e:
        # メール通知？
        print(e)
        pass

    return {
        "statusCode": 200,
        "body": "Process Complete",
    }


def arrangeNotifyMsg(msg: str) -> str:
    """
    通知メッセージを調整

    Parameters
    ----------
    msg: str
        変換前のメッセージ

    Returns
    -------
    str
    """
    # 前後のスペースを削除
    msg = msg.strip()

    # 最初は改行を挿入
    msg = f"\n{msg}"

    # メッセージが最大を超えていたら切り取り
    msg = textwrap.dedent(msg[:MAX_STR_LENGTH])

    return msg
