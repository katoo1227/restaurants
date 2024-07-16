import boto3
import os
import json
import dynamodb_types
from datetime import datetime
import pytz
from dataclasses import dataclass, asdict


@dataclass
class Restaurant:
    id: str
    name: str
    genre: str
    sub_genre: str
    address: str
    latitude: float
    longitude: float
    open_hours: str
    close_days: str
    parking: str
    created_at: str


def lambda_handler(event, context):

    success_response = {
        "statusCode": 200,
        "body": "Process Complete",
    }

    try:
        # 未通知の飲食店を取得
        yet_notified_restaurants = get_yet_notified_restaurants()

        # 未通知がなければ終了
        if len(yet_notified_restaurants) == 0:
            notify_line_no_exists()
            return success_response

        # 新規飲食店の通知
        notify_line_restaurants(yet_notified_restaurants)

        # is_notifiedの更新
        update_is_notified(yet_notified_restaurants)

    except Exception as e:
        payload = {"function_name": context.function_name, "msg": str(e)}
        boto3.client("lambda").invoke(
            FunctionName=os.environ["ARN_LAMBDA_ERROR_COMMON"],
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode("utf-8"),
        )

    return success_response


def get_yet_notified_restaurants() -> list[Restaurant]:
    """
    未通知の飲食店を取得

    Returns
    -------
    list[Restaurant]
    """
    # 取得するカラム一覧
    columns = [
        "id",
        "#n", # nameは予約語なのでプレースホルダーを使用
        "genre",
        "sub_genre",
        "address",
        "latitude",
        "longitude",
        "open_hours",
        "close_days",
        "parking",
        "created_at",
    ]

    res = boto3.client("dynamodb").query(
        TableName=os.environ["NAME_DYNAMODB_RESTAURANTS"],
        IndexName=os.environ["NAME_DYNAMODB_GSI_RESTAURANTS"],
        KeyConditionExpression="is_notified = :is_notified",
        ExpressionAttributeValues={
            ":is_notified": dynamodb_types.serialize(0),
        },
        ProjectionExpression=",".join(columns),
        FilterExpression=" AND ".join([f"attribute_exists({c})" for c in columns]),
        ExpressionAttributeNames={"#n": "name"},
    )

    # 通常のdictの形に変換して返す
    results = []
    for item in res["Items"]:
        i = dynamodb_types.deserialize_dict(item)
        results.append(
            Restaurant(
                id=i["id"],
                name=i["name"],
                genre=i["genre"],
                sub_genre=i["sub_genre"],
                address=i["address"],
                latitude=i["latitude"],
                longitude=i["longitude"],
                open_hours=i["open_hours"],
                close_days=i["close_days"],
                parking=i["parking"],
                created_at=i["created_at"],
            )
        )
    return results


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
    msg = "新しい飲食店が登録されました。"
    for s in restaurants:
        genre_str = s.genre
        if s.sub_genre != "":
            genre_str += "、" + s.sub_genre
        msg += f"""
■店名：{s.name}
・ジャンル：{genre_str}
・住所：{s.address}
https://www.hotpepper.jp/str{s.id}/
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

    # 更新データの作成
    update_datas = []
    for r in restaurants:
        item = asdict(r) | {"is_notified": 1, "updated_at": now}
        update_datas.append(
            {"PutRequest": {"Item": dynamodb_types.serialize_dict(item)}}
        )

    # DynamoDBへの更新
    # batch_write_itemは一度に25件までしか更新できないため
    if len(update_datas) > 0:
        for i in range(0, len(update_datas), 25):
            batch = update_datas[i : i + 25]
            boto3.client("dynamodb").batch_write_item(
                RequestItems={os.environ["NAME_DYNAMODB_RESTAURANTS"]: batch}
            )
