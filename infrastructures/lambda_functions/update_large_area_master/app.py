import boto3
import os
import json
from hotpepper_api_client import HotpepperApiClient
from db_client import DbClient
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
    api_client = HotpepperApiClient(
        os.environ["PARAMETER_STORE_NAME_HOTPEPPER_API_KEY"]
    )
    res = api_client.get_large_areas()
    return [
        LargeArea(
            code=r["code"], name=r["name"], service_area_code=r["service_area"]["code"]
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
    values_row_str = f"({', '.join(['?'] * 3)})"
    sql = f"""
INSERT INTO
    large_area_master (code, name, service_area_code)
VALUES
    {', '.join([values_row_str] * len(large_areas))}
ON DUPLICATE KEY UPDATE name = VALUES(name), service_area_code = VALUES(service_area_code);
"""

    # パラメータ
    params = []
    for a in large_areas:
        params.extend([a.code, a.name, a.service_area_code])

    db_client = DbClient(
        os.environ["ENV"],
        os.environ["SAKURA_DATABASE_API_KEY_PATH"],
        os.environ["SAKURA_DATABASE_API_URL"],
    )
    db_client.handle(sql, params)
