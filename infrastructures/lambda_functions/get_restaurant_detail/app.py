import os
import json
import boto3
from pydantic import BaseModel, ValidationError
from db_client import DbClient


class EventParams(BaseModel):
    """
    イベントパラメータ
    """

    id: str


class Image(BaseModel):
    """
    画像データ
    """

    order_num: int
    alt: str


class Detail(BaseModel):
    """
    飲食店データ
    """

    name: str
    genre: str
    sub_genre: str | None
    address: str
    latitude: float
    longitude: float
    open_hours: str
    close_days: str
    parking: str
    images: list[dict]


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
        d = get_detail(evt.id)
        response["body"] = json.dumps(d.__dict__)
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

    try:
        return EventParams(**body)
    except ValidationError as e:
        raise Exception(f"{str(e.json())}")


def get_detail(id: str) -> Detail:
    """
    緯度経度の範囲内の飲食店を取得

    Parameters
    ----------
    evt: EventParams

    Returns
    -------
    Detail
    """

    # SQL
    sql = """
SELECT
    r.name,
    g1.name AS genre,
    g2.name AS sub_genre,
    r.address,
    r.latitude,
    r.longitude,
    r.open_hours,
    r.close_days,
    r.parking,
    i.order_num,
    i.name AS alt
FROM
    restaurants r
    INNER JOIN genre_master g1 ON r.genre_code = g1.code
    LEFT JOIN genre_master g2 ON r.sub_genre_code = g2.code
    LEFT JOIN images i USING (id)
WHERE
    r.id = ?
    AND r.is_complete = 1
ORDER BY
    i.order_num ASC;
"""

    # パラメータ
    params = [id]

    # DBから取得
    db_client = DbClient(
        os.environ["ENV"],
        os.environ["SAKURA_DATABASE_API_KEY_PATH"],
        os.environ["SAKURA_DATABASE_API_URL"],
    )
    res = db_client.select(sql, params)

    # 最初の飲食店レコード
    r = res["data"][0]
    r_dict = {
        "name": r["name"],
        "genre": r["genre"],
        "sub_genre": r["sub_genre"],
        "address": r["address"],
        "latitude": float(r["latitude"]),
        "longitude": float(r["longitude"]),
        "open_hours": r["open_hours"],
        "close_days": r["close_days"],
        "parking": r["parking"],
    }

    r_dict["images"] = []

    # 画像がない場合はここで返す
    if r["order_num"] is None:
        return Detail(**r_dict)

    # 順番に格納
    for r in res["data"]:
        # 型チェックのため、構造体を通す
        image = Image(order_num=r["order_num"], alt=r["alt"])
        r_dict["images"].append(image.__dict__)

    return Detail(**r_dict)
