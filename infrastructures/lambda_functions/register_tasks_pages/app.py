import boto3
import os
import json
import requests
import re
from bs4 import BeautifulSoup
from db_client import DbClient
from pydantic import BaseModel


class EventParam(BaseModel):
    """
    イベントパラメータ構造体
    """

    service_area_code: str


def lambda_handler(event, context):

    success_response = {
        "statusCode": 200,
        "body": "Process Complete",
    }

    try:

        # パラメータを構造体に適用
        params = EventParam(**event)

        # ページ数を取得
        page_num = get_page_num(params.service_area_code)

        # 概要情報スクレイピングタスクを登録
        register_tasks_scraping_abstract(params.service_area_code, page_num)

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


def get_page_num(service_area_code: str) -> int:
    """
    ページ数を取得

    Parameters
    ----------
    service_area_code: str
        サービスエリアコード

    Returns
    -------
    int
        ページ数
    """

    # URL
    url = f"https://www.hotpepper.jp/{service_area_code}/lst/bgn1/"

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


def register_tasks_scraping_abstract(service_area_code: str, page_num: int) -> None:
    """
    タスクを登録

    Parameters
    ----------
    service_area_code: str
        サービスエリアコード
    page_num: int
        ページ数
    """
    # SQL
    values_row_str = f"({', '.join(['?'] * 2)})"
    sql = f"""
INSERT INTO
    update_tasks (kind, param)
VALUES
    {', '.join([values_row_str] * page_num)}
ON DUPLICATE KEY UPDATE kind = VALUES(kind), param = VALUES(param);
    """

    # パラメータ
    params = []
    for i in range(1, page_num + 1):
        params.extend(["ScrapingAbstract", f"{service_area_code}_{str(i)}"])

    db_client = DbClient(
        os.environ["ENV"],
        os.environ["SAKURA_DATABASE_API_KEY_PATH"],
        os.environ["SAKURA_DATABASE_API_URL"],
    )
    db_client.handle(sql, params)


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
