import boto3
import os
import json
import requests
import re
from bs4 import BeautifulSoup
import dynamodb_types
import dataclasses
from ds_area import DSArea


@dataclasses.dataclass
class Task:
    kind: str
    params_id: str
    params: DSArea


def lambda_handler(event, context):

    success_response = {
        "statusCode": 200,
        "body": "Process Complete",
    }

    try:

        # タスクの取得
        task = get_task_abstract_pages()

        # 該当レコードがなければスケジュールを削除
        if task == {}:
            delete_schedule()
            return success_response

        # ページ数を取得
        page_num = get_page_num(
            task.params.service_area_code,
            task.params.middle_area_code,
            task.params.small_area_code,
        )

        # 概要情報スクレイピングタスクを登録
        register_tasks_scraping_abstract(task.params, page_num)

        # ページごとの登録タスクを削除
        delete_task_abstract_pages(task.kind, task.params_id)

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


def get_task_abstract_pages() -> Task:
    """
    ページごとの登録タスクを取得

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

    res = dynamodb_types.deserialize_dict(res["Items"][0])
    return Task(
        kind=res["kind"], params_id=res["params_id"], params=DSArea(**res["params"])
    )


def delete_schedule() -> None:
    """
    スケジュールの削除
    """
    payload = {"task": "delete", "name": os.environ["NAME_TASK_REGISTER_PAGES"]}
    boto3.client("lambda").invoke(
        FunctionName=os.environ["NAME_LAMBDA_HANDLER_SCHEDULES"],
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )


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


def register_tasks_scraping_abstract(params: DSArea, page_num: int) -> None:
    """
    タスクを登録

    Parameters
    ----------
    params: DSArea
        パラメータ
    page_num: int
        ページ数
    """

    # paramsカラムの共通の値
    params_common = {}
    for key in ["large_service", "service", "large", "middle", "small"]:
        code_key = f"{key}_area_code"
        name_key = f"{key}_area_name"
        params_common[code_key] = getattr(params, code_key)
        params_common[name_key] = getattr(params, name_key)

    # 追加データの作成
    put_requests = [
        {
            "PutRequest": {
                "Item": dynamodb_types.serialize_dict(
                    {
                        "kind": os.environ["NAME_TASK_SCRAPING_ABSTRACT"],
                        "params_id": f"{params.small_area_code}_{i}",
                        "params": params_common | {"page_num": i},
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


def delete_task_abstract_pages(kind: str, params_id: str) -> None:
    """
    ページごとの登録タスクを削除

    Parameters
    ----------
    kind: str
        タスクの種類

    params_id: str
        パラメータID
    """
    boto3.client("dynamodb").delete_item(
        TableName=os.environ["NAME_DYNAMODB_TABLE_TASKS"],
        Key=dynamodb_types.serialize_dict({"kind": kind, "params_id": params_id}),
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
        FunctionName=os.environ["NAME_LAMBDA_HANDLER_SCHEDULES"],
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
