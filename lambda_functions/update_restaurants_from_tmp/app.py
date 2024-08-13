import boto3
import os
import json
from datetime import datetime
import pytz
from pydantic import BaseModel
from handler_s3_sqlite import HandlerS3Sqlte


class RestaurantTmp(BaseModel):
    """
    RestaurantTmp構造体
    """
    id: str
    name: str
    small_area_code: str
    genre_code: str
    sub_genre_code: str|None
    address: str
    latitude: float
    longitude: float
    open_hours: str
    close_days: str
    parking: str
    is_thumbnail: int


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
        # tmpテーブルからデータを取得
        tmps = get_from_tmp()

        # 飲食店テーブルへ反映
        update_restaurants(tmps)

    except Exception as e:
        payload = {"function_name": context.function_name, "msg": str(e)}
        boto3.client("lambda").invoke(
            FunctionName=os.environ["ARN_LAMBDA_ERROR_COMMON"],
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode("utf-8"),
        )

    return success_response

def get_from_tmp() -> list[RestaurantTmp]:
    """
    tmpテーブルからデータを取得

    Returns
    -------
    list[RestaurantTmp]
    """
    sql = """
SELECT
    id,
    name,
    small_area_code,
    genre_code,
    sub_genre_code,
    address,
    latitude,
    longitude,
    open_hours,
    close_days,
    parking,
    is_thumbnail
FROM
    restaurants_tmp
WHERE
    name <> ''
    AND small_area_code <> ''
    AND genre_code <> ''
    AND address <> ''
    AND latitude <> 0
    AND longitude <> 0;
"""
    res = HSS.exec_query(sql)
    return [
        RestaurantTmp(
            id=r[0],
            name=r[1],
            small_area_code=r[2],
            genre_code=r[3],
            sub_genre_code=r[4],
            address=r[5],
            latitude=r[6],
            longitude=r[7],
            open_hours=r[8],
            close_days=r[9],
            parking=r[10],
            is_thumbnail=r[11]
        )
        for r in res
    ]

def update_restaurants(tmps: list[RestaurantTmp]) -> None:
    """
    飲食店テーブルへ反映

    Parameters
    ----------
    tmps: list[RestaurantTmp]
        tmpテーブルデータ
    """
    # 今の日時
    tz = pytz.timezone("Asia/Tokyo")
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    values_arr = []
    for t in tmps:
        sub_genre = "NULL"
        if t.sub_genre_code is not None:
            sub_genre = f"'{t.sub_genre_code}'"
        values_arr.append(
            f"('{t.id}', '{t.name}', '{t.small_area_code}', '{t.genre_code}', {sub_genre}, '{t.address}', {t.latitude}, {t.longitude}, '{t.open_hours}', '{t.close_days}', '{t.parking}', {t.is_thumbnail}, '{now}', '{now}')"
        )

    sql = f"""
INSERT INTO
    restaurants (
        id,
        name,
        small_area_code,
        genre_code,
        sub_genre_code,
        address,
        latitude,
        longitude,
        open_hours,
        close_days,
        parking,
        is_thumbnail,
        created_at,
        updated_at
    )
VALUES
    {",".join(values_arr)}
ON CONFLICT(id) DO UPDATE SET
    name = excluded.name,
    small_area_code = excluded.small_area_code,
    genre_code = excluded.genre_code,
    sub_genre_code = excluded.sub_genre_code,
    address = excluded.address,
    latitude = excluded.latitude,
    longitude = excluded.longitude,
    open_hours = excluded.open_hours,
    close_days = excluded.close_days,
    parking = excluded.parking,
    is_thumbnail = excluded.is_thumbnail,
    updated_at = excluded.updated_at;
"""
    HSS.exec_query_with_lock(sql)