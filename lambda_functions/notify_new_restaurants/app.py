import boto3
import os
import json
from datetime import datetime
import pytz
from pydantic import BaseModel
from handler_s3_sqlite import HandlerS3Sqlte


class Restaurant(BaseModel):
    """
    飲食店構造体
    """

    id: str
    name: str
    genre_code: str
    sub_genre_code: str | None
    address: str


HSS = HandlerS3Sqlte(
    os.environ["NAME_BUCKET_DATABASE"],
    os.environ["NAME_FILE_DATABASE"],
    os.environ["NAME_LOCK_FILE_DATABASE"],
)


def lambda_handler(event, context):

    success_response = {
        "statusCode": 200,
        "body": "Process Complete",
    }

    try:
        # 未通知の飲食店を取得
        yet_notifieds = get_yet_notifieds()
        print(yet_notifieds)

        # 未通知がなければ終了
        if len(yet_notifieds) == 0:
            notify_line_no_exists()
            return success_response

        # 新規飲食店の通知
        notify_line_restaurants(yet_notifieds)

        # is_notifiedの更新
        update_is_notified(yet_notifieds)

    except Exception as e:
        payload = {"function_name": context.function_name, "msg": str(e)}
        boto3.client("lambda").invoke(
            FunctionName=os.environ["ARN_LAMBDA_ERROR_COMMON"],
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode("utf-8"),
        )

    return success_response


def get_yet_notifieds() -> list[Restaurant]:
    """
    未通知の飲食店を取得

    Returns
    -------
    list[Restaurant]
    """
    # 未通知の飲食店を取得
    sql = """
SELECT
    id,
    name,
    genre_code,
    sub_genre_code,
    address
FROM
    restaurants
WHERE
    is_notified = 0;
"""
    restaurants = HSS.exec_query(sql)
    return [
        Restaurant(
            id=r[0], name=r[1], genre_code=r[2], sub_genre_code=r[3], address=r[4]
        )
        for r in restaurants
    ]


def notify_line_no_exists() -> None:
    """
    新規飲食店がなかった通知
    """
    msg = "新規の飲食店はありませんでした。"
    payload = {"type": 3, "msg": msg}
    boto3.client("lambda").invoke(
        FunctionName=os.environ["ARN_LAMBDA_LINE_NOTIFY"],
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )


def notify_line_restaurants(restaurants: list[Restaurant]) -> None:
    """
    新規飲食店の通知

    Parameters
    ----------
    restaurants: list[Restaurant]
    """
    # ジャンルマスタを全て取得
    sql = f"""
SELECT
    code,
    name
FROM
    genre_master;
"""
    res = HSS.exec_query(sql)
    genres = {r[0]: r[1] for r in res if r != ""}

    # 通知メッセージ
    msg = "新しい飲食店が登録されました。"
    for r in restaurants:
        genre_str = genres[r.genre_code]
        if r.sub_genre_code is not None:
            genre_str += "、" + genres[r.sub_genre_code]
        msg += f"""
■店名：{r.name}
・ジャンル：{genre_str}
・住所：{r.address}
https://www.hotpepper.jp/str{r.id}/
"""
    payload = {"type": 1, "msg": msg.strip()}
    boto3.client("lambda").invoke(
        FunctionName=os.environ["ARN_LAMBDA_LINE_NOTIFY"],
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )


def update_is_notified(restaurants: list[Restaurant]) -> None:
    """
    通知済みステータスの変更

    Parameters
    ----------
    restaurants: list[Restaurant]
    """
    # 今の日時
    tz = pytz.timezone("Asia/Tokyo")
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

    sql = f"""
UPDATE
    restaurants
SET
    is_notified = 1,
    updated_at = '{now}'
WHERE
    id IN ({",".join([f"'{r.id}'" for r in restaurants])});
"""
    HSS.exec_query_with_lock(sql)
