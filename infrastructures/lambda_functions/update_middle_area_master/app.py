import boto3
import os
import json
from hotpepper_api_client import HotpepperApiClient
from db_client import DbClient
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
    values_row_str = f"({', '.join(['?'] * 3)})"
    sql = f"""
INSERT INTO
    middle_area_master (code, name, large_area_code)
VALUES
    {', '.join([values_row_str] * len(middle_areas))}
ON DUPLICATE KEY UPDATE name = VALUES(name), large_area_code = VALUES(large_area_code);
"""

    # パラメータ
    params = []
    for a in middle_areas:
        params.extend([a.code, a.name, a.large_area_code])

    db_client = DbClient(
        os.environ["ENV"],
        os.environ["SAKURA_DATABASE_API_KEY_PATH"],
        os.environ["SAKURA_DATABASE_API_URL"],
    )
    db_client.handle(sql, params)
