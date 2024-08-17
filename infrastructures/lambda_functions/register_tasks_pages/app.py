import boto3
import os
import json
import requests
import re
from bs4 import BeautifulSoup
import dynamodb_types
from pydantic import BaseModel
from handler_s3_sqlite import HandlerS3Sqlte

class EventParam(BaseModel):
    """
    イベントパラメータ構造体
    """

    middle_area_code: str

class Task(BaseModel):
    """
    タスク構造体
    """
    kind: str
    param: str

HSS = HandlerS3Sqlte(
    os.environ["NAME_BUCKET_DATABASE"],
    os.environ["NAME_FILE_DATABASE"],
    os.environ["NAME_LOCK_FILE_DATABASE"],
)

def lambda_handler(event, context):

    success_response = {
        "statusCode": 200,
        "body": "Process Complete",
    }

    try:

        # パラメータを構造体に適用
        params = EventParam(**event)

        # 必要なエリアコード一覧を取得
        areas = get_area_codes(params.middle_area_code)

        # ページ数を取得
        page_num = get_page_num(
            areas[0],
            params.middle_area_code,
            areas[1]
        )

        # 概要情報スクレイピングタスクを登録
        register_tasks_scraping_abstract(params.middle_area_code, page_num)

        # スケジュールを登録
        register_schedule()

    except Exception as e:
        payload = {"function_name": context.function_name, "msg": str(e)}
        boto3.client("lambda").invoke(
            FunctionName=os.environ["ARN_LAMBDA_ERROR_COMMON"],
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode("utf-8"),
        )

    return success_response

# エリア一覧を取得
def get_area_codes(middle_area_code: str) -> tuple:
    """
    必要なエリア一覧を取得

    Parameters
    ----------
    small_area_code: str
        中エリアコード

    Returns
    -------
    tuple
        str
            サービスエリアコード
        list[str]
            エリアリスト
    """
    sql = """
SELECT
    service.code,
    small.code
FROM
    small_area_master small
    INNER JOIN middle_area_master middle ON small.middle_area_code = middle.code
    INNER JOIN large_area_master large ON middle.large_area_code = large.code
    INNER JOIN service_area_master service ON large.service_area_code = service.code
WHERE
    middle.code = ?;
"""

    res = HSS.exec_query(sql, [middle_area_code])
    return res[0][0], [r[1] for r in res]

def get_page_num(
    service_area_code: str,
    middle_area_code: str,
    small_area_codes: list[str]) -> int:
    """
    ページ数を取得

    Parameters
    ----------
    service_area_code: str
        サービスエリアコード
    middle_area_code: str
        中エリアコード
    areas: list[str]
        小エリアコードリスト

    Returns
    -------
    int
        ページ数
    """

    # URL
    url_arr = [
        "https://www.hotpepper.jp",
        service_area_code,
        middle_area_code,
        "_".join(small_area_codes),
        'bgn1'
    ]
    url = "/".join(url_arr)

    # HTML解析
    html = requests.get(url)
    soup = BeautifulSoup(html.content, "html.parser")

    # ページ数を取得
    lh27 = soup.select_one(".searchResultPageLink .lh27")
    if lh27 is None:
        raise Exception(
            f"ページ数の取得に失敗しました。.searchResultPageLink .lh27がありません。"
        )
    match = re.search(r"1/([0-9]+)ページ", lh27.text)
    if match is None:
        raise Exception(
            f"「1/([0-9]+)ページ」の形でページ数を取得できませんでした。{lh27.text}"
        )

    return int(match.group(1))


def register_tasks_scraping_abstract(middle_area_code: str, page_num: int) -> None:
    """
    タスクを登録

    Parameters
    ----------
    middle_area_code: str
        中エリアコード
    page_num: int
        ページ数
    """

    # 追加データの作成
    put_requests = [
        {
            "PutRequest": {
                "Item": dynamodb_types.serialize_dict(
                    {
                        "kind": os.environ["NAME_TASK_SCRAPING_ABSTRACT"],
                        "param": f"{middle_area_code}_{i}"
                    }
                )
            }
        }
        for i in range(1, page_num + 1)
    ]

    # 追加リクエストを分割してバッチ処理
    # batch_write_itemは一度に25件までしか追加できないため
    for i in range(0, len(put_requests), 25):
        batch = put_requests[i : i + 25]
        boto3.client("dynamodb").batch_write_item(
            RequestItems={os.environ["NAME_DYNAMODB_TABLE_TASKS"]: batch}
        )

def register_schedule() -> None:
    """
    スケジュールを登録
    """

    payload = {
        "task": "register",
        "name": os.environ["NAME_TASK_SCRAPING_ABSTRACT"],
        "target_arn": os.environ["ARN_LAMBDA_SCRAPING_ABSTRACT"],
        "invoke_role_arn": os.environ["ARN_IAM_ROLE_INVOKE_SCRAPING_ABSTRACT"],
    }
    boto3.client("lambda").invoke(
        FunctionName=os.environ["ARN_LAMBDA_HANDLER_SCHEDULES"],
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
