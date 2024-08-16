import boto3
import os
import json
from datetime import datetime
import pytz
from hotpepper_api_client import HotpepperApiClient
from handler_s3_sqlite import HandlerS3Sqlte
from pydantic import BaseModel


class LargeServiceArea(BaseModel):
    """
    大サービスエリア
    """

    code: str
    name: str


def lambda_handler(event, context):

    try:

        # 大サービスエリア一覧を取得
        large_service_areas = get_large_service_areas()

        # 大サービスエリア一覧を更新
        update_large_service_areas(large_service_areas)

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


def get_large_service_areas() -> list[LargeServiceArea]:
    """
    大サービスエリア一覧を取得

    Returns
    -------
    list[LargeServiceArea]
    """
    # ホットペッパーAPIから大サービスエリア一覧を取得
    api_client = HotpepperApiClient(os.environ["PARAMETER_STORE_NAME_HOTPEPPER_API_KEY"])
    res = api_client.get_large_service_areas()
    return [
        LargeServiceArea(
            code=r["code"],
            name=r["name"],
        )
        for r in res["results"]["large_service_area"]
    ]


def update_large_service_areas(large_service_areas: list[LargeServiceArea]) -> None:
    """
    大サービスエリア一覧を更新

    Parameters
    ----------
    large_service_areas: list[LargeServiceArea]
        大サービスエリア一覧
    """
    query = get_upsert_query(large_service_areas)
    hss = HandlerS3Sqlte(
        os.environ["NAME_BUCKET_DATABASE"],
        os.environ["NAME_FILE_DATABASE"],
        os.environ["NAME_LOCK_FILE_DATABASE"],
    )
    hss.exec_query_with_lock(query[0], query[1])


def get_upsert_query(large_service_areas: list[LargeServiceArea]) -> tuple:
    """
    upsertを行うSQLとパラメータを取得

    Parameters
    ----------
    large_service_areas: list[LargeServiceArea]
        大サービスエリア一覧

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
    values_row_str = f"({', '.join(['?'] * 4)})"
    sql = f"""
INSERT INTO
    large_service_area_master(code, name, created_at, updated_at)
VALUES
    {', '.join([values_row_str] * len(large_service_areas))}
ON CONFLICT(code) DO UPDATE SET
    name = excluded.name,
    updated_at = excluded.updated_at;
"""

    # パラメータ
    params = []
    for a in large_service_areas:
        params.extend([a.code, a.name, now, now])

    return sql, params
