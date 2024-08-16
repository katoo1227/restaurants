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
        "headers": {
            "Access-Control-Allow-Origin": "null"
        },
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

def set_origin(evt: dict) -> str|None:
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

    origin = evt['headers'].get('origin', '')
    if origin in allowed_origins:
        return origin
    else:
        return None

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
        raise Exception(f"イベントパラメータにbodyがない。パラメータ：{json.dumps(evt)}")

    body = json.loads(evt["body"])

    # middle_area_codeのチェック
    # TODO EventParams内でチェックするよう修正
    if not re.match(r"Y\d{3}", body["middle_area_code"]):
        raise Exception(f"middle_area_codeが{str(r"Y\d{3}")}にマッチしない。{body["middle_area_code"]}")

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
    *
FROM
    restaurants
WHERE
    latitude BETWEEN ? AND ?
    AND longitude BETWEEN ? AND ?;
"""
    params = [evt.lat_min, evt.lat_max, evt.lng_min, evt.lng_max]
    res = hss.exec_query(sql, params)
    print(res)
    # # 緯度経度それぞれの検索
    # lats = get_restaurants_lat_lng("lat", evt.middle_area_code, evt.lat_min, evt.lat_max)
    # lngs = get_restaurants_lat_lng("lng", evt.middle_area_code, evt.lng_min, evt.lng_max)

    # # どちらにも該当した飲食店を抽出
    # result = []
    # for lat in lats:
    #     for lng in lngs:
    #         if lat.id == lng.id:
    #             result.append(lat.__dict__)
    #             break

    # return result


# def get_restaurants_lat_lng(kind: str, middle_area_code: str, min: float, max: float) -> list[Restaurant]:
#     """
#     緯度または経度を指定して飲食店を取得

#     Parameters
#     ----------
#     kind: str
#         lat or lng
#     middle_area_code: str
#         中エリアコード
#     min: float
#         最小値
#     max: float
#         最大値

#     Returns
#     -------
#     list[Restaurant]
#     """
#     # lat or lngでなければエラー
#     if kind not in ["lat", "lng"]:
#         raise Exception(f"kindの値が不正。{kind}")

#     # 取得するカラム
#     projection_columns = [
#         "id",
#         "latitude",
#         "longitude",
#     ]

#     # フィルター用カラム
#     filter_columns = [
#         "#n", # nameは予約語なのでプレースホルダーを使用
#         "genre",
#         "sub_genre",
#         "address",
#         "open_hours",
#         "close_days",
#         "is_thumbnail",
#         "parking",
#     ]

#     # 緯度or経度によって変更
#     if kind == "lat":
#         index_name = os.environ["NAME_DYNAMODB_GSI_MIDDLE_AREA_CODE_LATITUDE"]
#         sort_key = "latitude"
#         filter_columns.append("longitude")
#     else:
#         index_name = os.environ["NAME_DYNAMODB_GSI_MIDDLE_AREA_CODE_LONGITUDE"]
#         sort_key = "longitude"
#         filter_columns.append("latitude")

#     res = boto3.client('dynamodb').query(
#         TableName=os.environ["NAME_DYNAMODB_RESTAURANTS"],
#         IndexName=index_name,
#         KeyConditionExpression=f"middle_area_code = :middle_area_code AND {sort_key} BETWEEN :min AND :max",
#         ExpressionAttributeValues={
#             ":middle_area_code": dynamodb_types.serialize(middle_area_code),
#             ":min": dynamodb_types.serialize(min),
#             ":max": dynamodb_types.serialize(max)
#         },
#         ProjectionExpression=",".join(projection_columns),
#         FilterExpression=" AND ".join([f"attribute_exists({c})" for c in filter_columns]),
#         ExpressionAttributeNames={"#n": "name"}
#     )

#     return [Restaurant(**dynamodb_types.deserialize_dict(i)) for i in res["Items"]]
