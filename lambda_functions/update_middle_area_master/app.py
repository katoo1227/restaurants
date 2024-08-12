import boto3
import os
import json
from datetime import datetime
import pytz
from hotpepper_api_client import HotpepperApiClient
from handler_s3_sqlite import HandlerS3Sqlte
from pydantic import BaseModel


class MiddleArea(BaseModel):
    """
    中エリア
    """

    code: str
    name: str
    large_area_code: str


def lambda_handler(event, context):

    try:

        # 中エリア一覧を取得
        middle_areas = get_middle_areas()

        # 中エリア一覧を更新
        update_middle_areas(middle_areas)

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


def get_middle_areas() -> list[MiddleArea]:
    """
    中エリア一覧を取得

    Returns
    -------
    list[MiddleArea]
    """
    # ホットペッパーAPIから中エリア一覧を取得
    api_client = HotpepperApiClient(os.environ["PARAMETER_STORE_NAME_HOTPEPPER_API_KEY"])
    res = api_client.get_middle_areas()
    return [
        MiddleArea(
            code=r["code"],
            name=r["name"],
            large_area_code=r["large_area"]["code"]
        )
        for r in res["results"]["middle_area"]
    ]


def update_middle_areas(middle_areas: list[MiddleArea]) -> None:
    """
    中エリア一覧を更新

    Parameters
    ----------
    middle_areas: list[LargeArea]
        中エリア一覧
    """
    sql = get_upsert_sql(middle_areas)
    hss = HandlerS3Sqlte(
        os.environ["NAME_BUCKET_DATABASE"],
        os.environ["NAME_FILE_DATABASE"],
        os.environ["NAME_LOCK_FILE_DATABASE"],
    )
    res = hss.exec_query_with_lock(sql)

    # エラーがあればスロー
    if res is not None:
        raise res


def get_upsert_sql(middle_areas: list[MiddleArea]) -> str:
    """
    upsertを行うSQLを作成

    Parameters
    ----------
    middle_areas: list[MiddleArea]
        中エリア一覧

    Returns
    -------
    str
    """

    # 今の日時
    tz = pytz.timezone("Asia/Tokyo")
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

    # 引数をVALUES部分に置換
    values_arr = []
    for a in middle_areas:
        values_arr.append(
            "(" + ",".join([f"'{a.code}'", f"'{a.name}'", f"'{a.large_area_code}'", f"'{now}'", f"'{now}'"]) + ")"
        )
    values = ",".join(values_arr)

    sql = f"""
INSERT INTO middle_area_master(code, name, large_area_code, created_at, updated_at)
VALUES
{values}
ON CONFLICT(code) DO UPDATE SET
    name = excluded.name,
    updated_at = excluded.updated_at;
"""
    return sql
