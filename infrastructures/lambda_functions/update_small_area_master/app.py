import boto3
import os
import json
from hotpepper_api_client import HotpepperApiClient
from db_client import DbClient
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
    values_row_str = f"({', '.join(['?'] * 3)})"
    sql = f"""
INSERT INTO
    small_area_master (code, name, middle_area_code)
VALUES
    {', '.join([values_row_str] * len(samll_areas))}
ON DUPLICATE KEY UPDATE name = VALUES(name), middle_area_code = VALUES(middle_area_code);
"""
    # パラメータ
    params = []
    for a in samll_areas:
        params.extend([a.code, a.name, a.middle_area_code])

    db_client = DbClient(
        os.environ["ENV"],
        os.environ["SAKURA_DATABASE_API_KEY_PATH"],
        os.environ["SAKURA_DATABASE_API_URL"],
    )
    db_client.handle(sql, params)
