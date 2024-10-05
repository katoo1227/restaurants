import os
import json
import boto3
from pydantic import BaseModel, ValidationError
from db_client import DbClient


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
    name: str
    latitude: float
    longitude: float
    genre_name: str
    parking: str
    is_thumbnail: int
    distance: float


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
    list[dict]
    """

    # SQL
    sql = """
SELECT
    r.id,
    r.name,
    r.latitude,
    r.longitude,
    g.name AS genre_name,
    r.parking,
    r.is_thumbnail,
    (
        6371 * acos(
            cos(radians(?)) * cos(radians(r.latitude)) * cos(radians(r.longitude) - radians(?))
            + sin(radians(?)) * sin(radians(r.latitude))
        )
    ) AS distance
FROM
    restaurants r
    INNER JOIN genre_master g ON r.genre_code = g.code
WHERE
    r.is_complete = 1
    AND r.latitude BETWEEN ? AND ?
    AND r.longitude BETWEEN ? AND ?
ORDER BY
    distance ASC
LIMIT
    2000;
"""

    # パラメータ
    params = [
        evt.lat,
        evt.lng,
        evt.lng,
        evt.lat_min,
        evt.lat_max,
        evt.lng_min,
        evt.lng_max,
    ]

    # DBから取得
    db_client = DbClient(
        os.environ["ENV"],
        os.environ["SAKURA_DATABASE_API_KEY_PATH"],
        os.environ["SAKURA_DATABASE_API_URL"],
    )
    res = db_client.select(sql, params)

    return [
        Restaurant(
            id=r["id"],
            name=r["name"],
            latitude=float(r["latitude"]),
            longitude=float(r["longitude"]),
            genre_name=r["genre_name"],
            parking=r["parking"],
            is_thumbnail=r["is_thumbnail"],
            distance=r["distance"],
        ).__dict__
        for r in res["data"]
    ]
