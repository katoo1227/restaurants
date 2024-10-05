import boto3
import os
import json
from hotpepper_api_client import HotpepperApiClient
from db_client import DbClient
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
    api_client = HotpepperApiClient(
        os.environ["PARAMETER_STORE_NAME_HOTPEPPER_API_KEY"]
    )
    res = api_client.get_service_areas()
    return [
        ServiceArea(
            code=r["code"],
            name=r["name"],
            large_service_area_code=r["large_service_area"]["code"],
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
    values_row_str = f"({', '.join(['?'] * 3)})"
    sql = f"""
INSERT INTO
    service_area_master (code, name, large_service_area_code)
VALUES
    {', '.join([values_row_str] * len(service_areas))}
ON DUPLICATE KEY UPDATE name = VALUES(name), large_service_area_code = VALUES(large_service_area_code);
"""

    # パラメータ
    params = []
    for a in service_areas:
        params.extend([a.code, a.name, a.large_service_area_code])

    db_client = DbClient(
        os.environ["ENV"],
        os.environ["SAKURA_DATABASE_API_KEY_PATH"],
        os.environ["SAKURA_DATABASE_API_URL"],
    )
    db_client.handle(sql, params)
