import boto3
import os
import json
import requests
import re
from bs4 import BeautifulSoup
import dynamodb_types
from pydantic import BaseModel
from handler_s3_sqlite import HandlerS3Sqlte


class Task(BaseModel):
    """
    タスク構造体
    """
    kind: str
    param: str


def lambda_handler(event, context):

    success_response = {
        "statusCode": 200,
        "body": "Process Complete",
    }

    try:

        # タスクの取得
        task = get_task()

        # 該当レコードがなければスケジュールを削除
        if task == {}:
            delete_schedule()
            return success_response

        # ページ数を取得
        page_num = get_page_num(task.param)

        # 概要情報スクレイピングタスクを登録
        register_tasks_scraping_abstract(task.param, page_num)

        # タスクを削除
        delete_task(task.kind, task.param)

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


def get_task() -> Task:
    """
    タスクを取得

    Returns
    -------
    Task
    """
    res = boto3.client("dynamodb").query(
        TableName=os.environ["NAME_DYNAMODB_TABLE_TASKS"],
        KeyConditionExpression="kind = :kind",
        ExpressionAttributeValues={
            ":kind": dynamodb_types.serialize(os.environ["NAME_TASK_REGISTER_PAGES"])
        },
        Limit=1,
    )

    # なければ空オブジェクトで返却
    if len(res["Items"]) == 0:
        return {}

    return Task(**dynamodb_types.deserialize_dict(res["Items"][0]))


def delete_schedule() -> None:
    """
    スケジュールの削除
    """
    payload = {"task": "delete", "name": os.environ["NAME_TASK_REGISTER_PAGES"]}
    boto3.client("lambda").invoke(
        FunctionName=os.environ["ARN_LAMBDA_HANDLER_SCHEDULES"],
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )


def get_page_num(small_area_code: str) -> int:
    """
    ページ数を取得

    Parameters
    ----------
    small_area_code: str
        小エリアコード

    Returns
    -------
    int
        ページ数
    """

    # ページURLに必要なデータを取得
    sql = f"""
SELECT
    service.code AS service_area_code,
    middle.code AS middle_area_code,
    small.code AS small_area_code
FROM
    small_area_master small
    INNER JOIN middle_area_master middle ON small.middle_area_code = middle.code
    INNER JOIN large_area_master large ON middle.large_area_code = large.code
    INNER JOIN service_area_master service ON large.service_area_code = service.code
WHERE
    small_area_code = '{small_area_code}';
"""
    hss = HandlerS3Sqlte(
        os.environ["NAME_BUCKET_DATABASE"],
        os.environ["NAME_FILE_DATABASE"],
        os.environ["NAME_LOCK_FILE_DATABASE"]
    )
    res = hss.exec_query(sql)

    # URL
    url_arr = [
        "https://www.hotpepper.jp",
        res[0][0],
        res[0][1],
        res[0][2],
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
    match = re.search(r"1/([0-9]+)ページ", lh27.text)
    if match is None:
        raise Exception(
            f"「1/([0-9]+)ページ」の形でページ数を取得できませんでした。{lh27.text}"
        )

    return int(match.group(1))


def register_tasks_scraping_abstract(small_area_code: str, page_num: int) -> None:
    """
    タスクを登録

    Parameters
    ----------
    small_area_code: str
        小エリアコード
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
                        "param": f"{small_area_code}_{i}"
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


def delete_task(kind: str, param: str) -> None:
    """
    タスクを削除

    Parameters
    ----------
    kind: str
        タスクの種類

    param: str
        パラメータ
    """
    boto3.client("dynamodb").delete_item(
        TableName=os.environ["NAME_DYNAMODB_TABLE_TASKS"],
        Key=dynamodb_types.serialize_dict({"kind": kind, "param": param}),
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
