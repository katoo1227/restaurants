import os
import re
import json
import boto3
from pydantic import BaseModel, ValidationError
from handler_s3_sqlite import HandlerS3Sqlte


class EventParams(BaseModel):
    """
    イベントパラメータ
    """

    lat: float
    lng: float
    lat_min: float
    lat_max: float
    lng_min: float
    lng_max: float


class Restaurant(BaseModel):
    """
    飲食店データ
    """

    id: str
    latitude: float
    longitude: float


def lambda_handler(event, context):

    response = {
        "statusCode": 200,
        "headers": {"Access-Control-Allow-Origin": "null"},
        "body": "NG",
    }

    try:
        # オリジンの設定
        origin = set_origin(event)
        if origin is None:
            return response
        response["headers"]["Access-Control-Allow-Origin"] = origin

        # パラメータの取得
        evt = get_params(event)

        # 緯度経度の範囲内の飲食店を取得
        response["body"] = json.dumps(get_restaurants(evt))
    except Exception as e:
        response["statusCode"] = 500
        payload = {"function_name": context.function_name, "msg": str(e)}
        boto3.client("lambda").invoke(
            FunctionName=os.environ["ARN_LAMBDA_ERROR_COMMON"],
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode("utf-8"),
        )

    return response


def set_origin(evt: dict) -> str | None:
    """
    オリジンの取得

    Parameters
    ----------
    evt: dict
        イベントパラメータ

    Returns
    -------
    str
        オリジン名。不正ならNone
    """
    allowed_origins = os.environ["FRONTEND_DOMAIN"].split(",")

    # Lambda単体のテストやコマンドライン対策
    if "headers" not in evt:
        return None

    # 許可されていないオリジンであれば終了
    origin = evt["headers"].get("origin", "")
    if origin not in allowed_origins:
        return None

    return origin


def get_params(evt: dict) -> EventParams:
    """
    パラメータの検証

    Parameters
    ----------
    evt: dict
        イベントパラメータ

    Returns
    -------
    EventParams
    """
    # bodyがなければエラー
    if "body" not in evt:
        raise Exception(
            f"イベントパラメータにbodyがない。パラメータ：{json.dumps(evt)}"
        )

    body = json.loads(evt["body"])

    # 最大と最小が逆であれば正す
    if body["lat_max"] < body["lat_min"]:
        lat_tmp = body["lat_max"]
        body["lat_max"] = body["lat_min"]
        body["lat_min"] = lat_tmp
    if body["lng_max"] < body["lng_min"]:
        lng_tmp = body["lng_max"]
        body["lng_max"] = body["lng_min"]
        body["lng_min"] = lng_tmp

    try:
        return EventParams(**body)
    except ValidationError as e:
        raise Exception(f"{str(e.json())}")


def get_restaurants(evt: EventParams) -> list[dict]:
    """
    緯度経度の範囲内の飲食店を取得

    Parameters
    ----------
    evt: EventParams

    Returns
    -------
    list
    """

    hss = HandlerS3Sqlte(
        os.environ["NAME_BUCKET_DATABASE"],
        os.environ["NAME_FILE_DATABASE"],
        os.environ["NAME_LOCK_FILE_DATABASE"],
    )

    # SQL
    sql = f"""
SELECT
    id,
    name,
    latitude,
    longitude,
    genre_code,
    parking,
    is_thumbnail,
    (
        6371 * acos(
            cos(radians(?)) * cos(radians(latitude)) * cos(radians(longitude) - radians(?))
            + sin(radians(?)) * sin(radians(latitude))
        )
    ) AS distance
FROM
    restaurants
WHERE
    latitude BETWEEN ? AND ?
    AND longitude BETWEEN ? AND ?
LIMIT 2000;
"""
    params = [
        evt.lat,
        evt.lng,
        evt.lng,
        evt.lat_min,
        evt.lat_max,
        evt.lng_min,
        evt.lng_max,
    ]
    res = hss.exec_query(sql, params)

    # ジャンル名とコードのマッピング
    genre_codes = list(set([r[4] for r in res]))
    sql = f"""
SELECT
    code,
    name
FROM
    genre_master
WHERE
    code IN ({', '.join(['?'] * len(genre_codes))});
"""
    genre_res = hss.exec_query(sql, genre_codes)
    genre_name_codes = {r[0]: r[1] for r in genre_res if r != ""}

    return [
        {
            "id": r[0],
            "name": r[1],
            "lat": r[2],
            "lng": r[3],
            "genre_name": genre_name_codes[r[4]],
            "parking": r[5],
            "is_thumbnail": r[6]
        }
        for r in res
    ]
