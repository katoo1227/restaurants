import boto3
import os
import json
from datetime import datetime
import pytz
from hotpepper_api_client import HotpepperApiClient
from handler_s3_sqlite import HandlerS3Sqlte
from pydantic import BaseModel
import time

# 1回のAPI実行で取得する件数
GET_NUM_BY_EXEC = 1000


class SmallArea(BaseModel):
    """
    小エリア
    """

    code: str
    name: str
    middle_area_code: str


def lambda_handler(event, context):

    try:

        # 小エリア一覧を取得
        small_areas = get_samll_areas_all()

        # 小エリア一覧を更新
        update_small_areas(small_areas)

    except Exception as e:
        payload = {"function_name": context.function_name, "msg": str(e)}
        boto3.client("lambda").invoke(
            FunctionName=os.environ["ARN_LAMBDA_ERROR_COMMON"],
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode("utf-8"),
        )

    return {
        "statusCode": 200,
        "body": "Process Complete",
    }


def get_samll_areas_all() -> list[SmallArea]:
    """
    小エリア一覧を全て取得

    Returns
    -------
    list[SmallArea]
    """
    # 全件数と開始位置（初期値）
    all_num = 1000
    start = 1

    # ホットペッパーAPIから小エリア一覧を取得
    small_areas = []
    api_client = HotpepperApiClient(
        os.environ["PARAMETER_STORE_NAME_HOTPEPPER_API_KEY"]
    )
    while start <= all_num:
        # APIの結果を結果配列に追加
        res = api_client.get_small_areas(start, GET_NUM_BY_EXEC)
        small_areas.extend(
            [
                SmallArea(
                    code=r["code"],
                    name=r["name"],
                    middle_area_code=r["middle_area"]["code"],
                )
                for r in res["results"]["small_area"]
            ]
        )

        # 全件数と開始位置を更新
        all_num = res["results"]["results_available"]
        start += GET_NUM_BY_EXEC

        # 1秒待つ
        time.sleep(1)

    return small_areas


def update_small_areas(samll_areas: list[SmallArea]) -> None:
    """
    小エリア一覧を更新

    Parameters
    ----------
    samll_areas: list[SmallArea]
        小エリア一覧
    """
    query = get_upsert_query(samll_areas)
    hss = HandlerS3Sqlte(
        os.environ["NAME_BUCKET_DATABASE"],
        os.environ["NAME_FILE_DATABASE"],
        os.environ["NAME_LOCK_FILE_DATABASE"],
    )
    hss.exec_query_with_lock(query[0], query[1])


def get_upsert_query(samll_areas: list[SmallArea]) -> tuple:
    """
    upsertを行うSQLとパラメータを取得

    Parameters
    ----------
    samll_areas: list[SmallArea]
        小エリア一覧

    Returns
    -------
    tuple
        sql: SQL文
        params: placeholderの値
    """

    # 今の日時
    tz = pytz.timezone("Asia/Tokyo")
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

    # SQL
    values_row_str = f"({', '.join(['?'] * 5)})"
    sql = f"""
INSERT INTO
    small_area_master(code, name, middle_area_code, created_at, updated_at)
VALUES
    {', '.join([values_row_str] * len(samll_areas))}
ON CONFLICT(code) DO UPDATE SET
    name = excluded.name,
    updated_at = excluded.updated_at;
"""
    # パラメータ
    params = []
    for a in samll_areas:
        params.extend([a.code, a.name, a.middle_area_code, now, now])

    return sql, params
