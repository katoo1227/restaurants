import boto3
import os
import json
from datetime import datetime
import pytz
from hotpepper_api_client import HotpepperApiClient
from handler_s3_sqlite import HandlerS3Sqlte
from pydantic import BaseModel


class ServiceArea(BaseModel):
    """
    サービスエリア
    """

    code: str
    name: str
    large_service_area_code: str


def lambda_handler(event, context):

    try:

        # サービスエリア一覧を取得
        service_areas = get_service_areas()

        # サービスエリア一覧を更新
        update_service_areas(service_areas)

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


def get_service_areas() -> list[ServiceArea]:
    """
    サービスエリア一覧を取得

    Returns
    -------
    list[ServiceArea]
    """
    # ホットペッパーAPIからサービスエリア一覧を取得
    api_client = HotpepperApiClient(os.environ["PARAMETER_STORE_NAME_HOTPEPPER_API_KEY"])
    res = api_client.get_service_areas()
    return [
        ServiceArea(
            code=r["code"],
            name=r["name"],
            large_service_area_code=r["large_service_area"]["code"]
        )
        for r in res["results"]["service_area"]
    ]


def update_service_areas(service_areas: list[ServiceArea]) -> None:
    """
    サービスエリア一覧を更新

    Parameters
    ----------
    service_areas: list[ServiceArea]
        サービスエリア一覧
    """
    query = get_upsert_query(service_areas)
    hss = HandlerS3Sqlte(
        os.environ["NAME_BUCKET_DATABASE"],
        os.environ["NAME_FILE_DATABASE"],
        os.environ["NAME_LOCK_FILE_DATABASE"],
    )
    hss.exec_query_with_lock(query[0], query[1])


def get_upsert_query(service_areas: list[ServiceArea]) -> tuple:
    """
    upsertを行うSQLとパラメータを取得

    Parameters
    ----------
    service_areas: list[ServiceArea]
        サービスエリア一覧

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
    service_area_master(code, name, large_service_area_code, created_at, updated_at)
VALUES
    {', '.join([values_row_str] * len(service_areas))}
ON CONFLICT(code) DO UPDATE SET
    name = excluded.name,
    updated_at = excluded.updated_at;
"""
    # パラメータ
    params = []
    for a in service_areas:
        params.extend([a.code, a.name, a.large_service_area_code, now, now])

    return sql, params
