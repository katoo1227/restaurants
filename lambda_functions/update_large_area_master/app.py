import boto3
import os
import json
from datetime import datetime
import pytz
from hotpepper_api_client import HotpepperApiClient
from handler_s3_sqlite import HandlerS3Sqlte
from pydantic import BaseModel


class LargeArea(BaseModel):
    """
    大エリア
    """

    code: str
    name: str
    service_area_code: str


def lambda_handler(event, context):

    try:

        # 大エリア一覧を取得
        large_areas = get_large_areas()

        # 大エリア一覧を更新
        update_large_areas(large_areas)

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


def get_large_areas() -> list[LargeArea]:
    """
    大エリア一覧を取得

    Returns
    -------
    list[LargeArea]
    """
    # ホットペッパーAPIから大エリア一覧を取得
    api_client = HotpepperApiClient(os.environ["PARAMETER_STORE_NAME_HOTPEPPER_API_KEY"])
    res = api_client.get_large_areas()
    return [
        LargeArea(
            code=r["code"],
            name=r["name"],
            service_area_code=r["service_area"]["code"]
        )
        for r in res["results"]["large_area"]
    ]


def update_large_areas(large_areas: list[LargeArea]) -> None:
    """
    大エリア一覧を更新

    Parameters
    ----------
    large_areas: list[LargeArea]
        大エリア一覧
    """
    sql = get_upsert_sql(large_areas)
    hss = HandlerS3Sqlte(
        os.environ["NAME_BUCKET_DATABASE"],
        os.environ["NAME_FILE_DATABASE"],
        os.environ["NAME_LOCK_FILE_DATABASE"],
    )
    hss.exec_query_with_lock(sql)


def get_upsert_sql(large_areas: list[LargeArea]) -> str:
    """
    upsertを行うSQLを作成

    Parameters
    ----------
    large_areas: list[LargeArea]
        大エリア一覧

    Returns
    -------
    str
    """

    # 今の日時
    tz = pytz.timezone("Asia/Tokyo")
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

    # 引数をVALUES部分に置換
    values_arr = []
    for a in large_areas:
        values_arr.append(
            "(" + ",".join([f"'{a.code}'", f"'{a.name}'", f"'{a.service_area_code}'", f"'{now}'", f"'{now}'"]) + ")"
        )
    values = ",".join(values_arr)

    sql = f"""
INSERT INTO large_area_master(code, name, service_area_code, created_at, updated_at)
VALUES
{values}
ON CONFLICT(code) DO UPDATE SET
    name = excluded.name,
    updated_at = excluded.updated_at;
"""
    return sql
