import boto3
import os
import json
from hotpepper_api_client import HotpepperApiClient
from db_client import DbClient
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
    api_client = HotpepperApiClient(
        os.environ["PARAMETER_STORE_NAME_HOTPEPPER_API_KEY"]
    )
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
    values_row_str = f"({', '.join(['?'] * 2)})"
    sql = f"""
INSERT INTO
    large_service_area_master (code, name)
VALUES
    {', '.join([values_row_str] * len(large_service_areas))}
ON DUPLICATE KEY UPDATE name = VALUES(name);
"""

    # パラメータ
    params = []
    for a in large_service_areas:
        params.extend([a.code, a.name])

    db_client = DbClient(
        os.environ["ENV"],
        os.environ["SAKURA_DATABASE_API_KEY_PATH"],
        os.environ["SAKURA_DATABASE_API_URL"],
    )
    db_client.handle(sql, params)
