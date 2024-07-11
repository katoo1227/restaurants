import boto3
import os
import json
import requests
import re
from datetime import datetime, time, timedelta
from bs4 import BeautifulSoup
import pytz
from check_area_code_names import check_area_code_names


def lambda_handler(event, context):

    # Lambdaクライアント
    lambda_client = boto3.client("lambda")

    try:
        # イベントパラメータのチェック
        check_area_code_names(event)

        # ページ数を取得
        page_num = get_page_num(
            event["service_area_code"],
            event["middle_area_code"],
            event["small_area_code"],
        )

        # タスクを登録
        register_tasks(event, page_num)
    except Exception as e:
        msg = f"""
{str(e)}

関数名：{context.function_name}
イベント：{json.dumps(event)}
"""
        payload = {"type": 2, "msg": msg}
        lambda_client.invoke(
            FunctionName=os.environ["ARN_LAMBDA_LINE_NOTIFY"],
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode("utf-8"),
        )

    return {
        "statusCode": 200,
        "body": "Process Complete",
    }


def get_page_num(
    service_area_code: str, middle_area_code: str, small_area_code: str
) -> int:
    """
    ページ数を取得

    Parameters
    ----------
    service_area_code: str
        サービスエリアコード
    middle_area_code: str
        中エリアコード
    small_area_code: str
        小エリアコード

    Returns
    -------
    int
        ページ数
    """
    # URL
    url_arr = [
        "https://www.hotpepper.jp/",
        service_area_code,
        middle_area_code,
        small_area_code,
        "bgn1",
    ]
    url = "/".join(url_arr) + "/"

    # HTML解析
    html = requests.get(url)
    soup = BeautifulSoup(html.content, "html.parser")

    # ページ数を取得
    lh27 = soup.select_one(".searchResultPageLink .lh27")
    if lh27 is None:
        raise Exception(
            f"ページ数の取得に失敗しました。.searchResultPageLink .lh27がありません。"
        )
    match = re.search(r"1/(\d+)ページ", lh27.text)
    if match is None:
        raise Exception(
            f"「1/(\d+)ページ」の形でページ数を取得できませんでした。{lh27.text}"
        )

    return int(match.group(1))


def register_tasks(event: dict, page_num: int) -> None:
    """
    タスクを登録
    Parameters
    ----------
    event: dict
        イベントパラメータ
        large_service_area_code: str
            大サービスエリアコード
        large_service_area_name: str
            大サービスエリア名
        service_area_code: str
            サービスエリアコード
        service_area_name: str
            サービスエリア名
        large_area_code: str
            大サービスエリアコード
        large_area_name: str
            大サービスエリア名
        middle_area_code: str
            中エリアコード
        middle_area_name: str
            中エリア名
        small_area_code: str
            小エリアコード
        small_area_name: str
            小エリア名
    page_num: int
        ページ数
    """
    client = boto3.client("scheduler")

    # 03:00から1分ずつずらしながらページ数分のタスク登録
    current_date = datetime.now(pytz.timezone("Asia/Tokyo")).date()
    am3 = datetime.combine(current_date, time(3, 0))
    for i in range(1, page_num + 1):
        jst = am3 + timedelta(minutes=i)
        client.create_schedule(
            ActionAfterCompletion="DELETE",
            ClientToken="string",
            Name=f"ScrapingAbstract_{event['small_area_code']}_page{i}",
            GroupName=os.environ["SCHEDULE_GROUP_NAME"],
            ScheduleExpression=f"cron({jst.minute} {jst.hour} {jst.day} {jst.month} ? {jst.year})",
            ScheduleExpressionTimezone="Asia/Tokyo",
            FlexibleTimeWindow={"Mode": "OFF"},
            State="ENABLED",
            Target={
                "Arn": os.environ["ARN_LAMBDA_REGISTER_TASK_SCRAPING_ABSTRACT_PAGES"],
                "Input": json.dumps(event | {"page_num": i}),
                # EventBridgeに付与するIAMロール
                "RoleArn": os.environ["ARN_IAM_ROLE_INVOKE_SCRAPING_ABSTRACT"],
            },
        )
