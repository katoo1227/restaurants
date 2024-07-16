import boto3
import os
import json
import requests
import re
import time
from datetime import datetime
from bs4 import BeautifulSoup
import dynamodb_types
import pytz
from dataclasses import dataclass, asdict


@dataclass
class AreaParams:
    large_service_area_code: str
    large_service_area_name: str
    service_area_code: str
    service_area_name: str
    large_area_code: str
    large_area_name: str
    middle_area_code: str
    middle_area_name: str
    small_area_code: str
    small_area_name: str
    page_num: int


@dataclass
class IdParams:
    id: str


@dataclass
class Task:
    kind: str
    params_id: str
    params: AreaParams | IdParams


def lambda_handler(event, context):

    success_response = {
        "statusCode": 200,
        "body": "Process Complete",
    }

    try:
        # タスクの取得
        task = get_task_scraping_abstract()

        # 該当レコードがなければスケジュールを削除
        if task == {}:
            delete_schedule()
            return success_response

        # 概要情報の取得
        restaurant_ids = get_restaurant_ids(
            task.params.service_area_code,
            task.params.middle_area_code,
            task.params.small_area_code,
            task.params.page_num,
        )

        # restaurantsへの登録
        register_restaurants(restaurant_ids)

        # restaurants_areasへの登録
        register_restaurants_areas(
            {k: v for k, v in asdict(task.params).items() if k != "page_num"},
            restaurant_ids,
        )

        # 詳細情報スクレイピングタスクの登録
        register_tasks_scraping_detail(restaurant_ids)

        # 概要情報スクレイピングタスクの削除
        delete_task_scraping_abstract(task.kind, task.params_id)

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


def get_task_scraping_abstract() -> Task:
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
            ":kind": dynamodb_types.serialize(os.environ["NAME_TASK_SCRAPING_ABSTRACT"])
        },
        Limit=1,
    )

    # なければ空オブジェクトで返却
    if len(res["Items"]) == 0:
        return {}

    res = dynamodb_types.deserialize_dict(res["Items"][0])
    return Task(
        kind=res["kind"], params_id=res["params_id"], params=AreaParams(**res["params"])
    )


def delete_schedule() -> None:
    """
    スケジュールの削除
    """
    payload = {"task": "delete", "name": os.environ["NAME_TASK_SCRAPING_ABSTRACT"]}
    boto3.client("lambda").invoke(
        FunctionName=os.environ["NAME_LAMBDA_HANDLER_SCHEDULES"],
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )


def get_restaurant_ids(
    service_area_code: str, middle_area_code: str, small_area_code: str, page_num: int
) -> list[str]:
    """
    概要情報を取得

    Parameters
    ----------
    service_area_code: str
        サービスエリアコード
    middle_area_code: str
        中エリアコード
    small_area_code: str
        小エリアコード
    page_num: int
        何ページ目か

    Returns
    -------
    list
        飲食店IDリスト
    """
    # URL
    url_arr = [
        "https://www.hotpepper.jp",
        service_area_code,
        middle_area_code,
        small_area_code,
        f"bgn{page_num}",
    ]
    url = "/".join(url_arr) + "/"

    # HTML解析 2回目以降のアクセスは結果が変わらないので、2回アクセスする
    html = requests.get(url)
    time.sleep(1)
    html = requests.get(url)
    soup = BeautifulSoup(html.content, "html.parser")

    # 飲食店名リンクを取得
    links = soup.select(".shopDetailStoreName a")
    if len(links) == 0:
        raise Exception(f"「.shopDetailStoreName a」が存在しません。{url}")

    # 結果配列を作成
    results = []
    for a in links:
        match = re.search(r"/str(J\d+)/", a.get("href"))
        if match is None:
            raise Exception(f"飲食店IDの取得に失敗しました。{str(a)}")
        results.append(match.group(1))

    return results


def register_restaurants(restaurant_ids: list[str]) -> None:
    """
    restaurantsへの登録

    Parameters
    ----------
    restaurant_ids: list
        飲食店IDリスト
    """
    dynamodb = boto3.client("dynamodb")
    table_name = os.environ["NAME_DYNAMODB_RESTAURANTS"]

    # パーティションキーで検索
    ids = [{"id": dynamodb_types.serialize(id)} for id in restaurant_ids]
    id_res = dynamodb.batch_get_item(RequestItems={table_name: {"Keys": ids}})
    records = id_res["Responses"][table_name]

    # 今の日時
    tz = pytz.timezone("Asia/Tokyo")
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

    # 追加データの作成
    add_datas = []
    record_ids = [dynamodb_types.serialize(r["id"]) for r in records]
    for id in restaurant_ids:
        # 登録済みであれば、上書きさせないためスキップ
        if id in record_ids:
            continue
        add_datas.append(
            {
                "PutRequest": {
                    "Item": dynamodb_types.serialize_dict(
                        {
                            "id": id,
                            "is_notified": 0,
                            "created_at": now,
                            "updated_at": now,
                        }
                    )
                }
            }
        )

    # DynamoDBへの追加
    # batch_write_itemは一度に25件までしか追加できないため
    if len(add_datas) > 0:
        for i in range(0, len(add_datas), 25):
            batch = add_datas[i : i + 25]
            boto3.client("dynamodb").batch_write_item(
                RequestItems={os.environ["NAME_DYNAMODB_RESTAURANTS"]: batch}
            )


def register_restaurants_areas(event: dict, restaurant_ids: list[str]):
    """
    restaurants_areasテーブルの登録

    Parameters
    ----------
    event: dict
        large_service_area_code: str
            大サービスエリアコード
        large_service_area_name: str
            大サービスエリア名
        service_area_code: str
            サービスエリアコード
        service_area_name: str
            サービスエリア名
        large_area_code: str
            大エリアコード
        large_area_name: str
            大エリア名
        middle_area_code: str
            中エリアコード
        middle_area_name: str
            中エリア名
        small_area_code: str
            小エリアコード
        small_area_name: str
            小エリア名
    restaurant_ids: list
        飲食店IDリスト
    """

    # 1回につき100レコードを最大とするために分割する
    # 数が多いとバリデーションエラーとなる模様
    restaurant_ids_list = [
        restaurant_ids[i : i + 5] for i in range(0, len(restaurant_ids), 5)
    ]

    # 更新データの作成
    area_categories = ["large_service", "service", "large", "middle", "small"]
    for ac in area_categories:
        code_key = f"{ac}_area_code"
        name_key = f"{ac}_area_name"
        update_datas = []
        for ids in restaurant_ids_list:
            for id in ids:
                update_datas.append(
                    {
                        "PutRequest": {
                            "Item": dynamodb_types.serialize_dict(
                                {
                                    "area_category": ac,
                                    "code_restaurant_id": f"{event[code_key]}#{id}",
                                    "restaurant_id": id,
                                    "code": event[code_key],
                                    "name": event[name_key],
                                }
                            )
                        }
                    }
                )

        # DynamoDBの一括更新
        # batch_write_itemは一度に25件までしか更新できないため
        for i in range(0, len(update_datas), 25):
            batch = update_datas[i : i + 25]
            boto3.client("dynamodb").batch_write_item(
                RequestItems={os.environ["NAME_DYNAMODB_RESTAURANTS_AREAS"]: batch}
            )


def register_tasks_scraping_detail(ids: list[str]) -> None:
    """
    詳細情報スクレイピングタスクの登録

    Parameters
    ----------
    ids: list[str]
        飲食店IDリスト
    """

    # 追加データの作成
    put_datas = []
    for id in ids:
        task = Task(
            kind=os.environ["NAME_TASK_SCRAPING_DETAIL"],
            params_id=id,
            params=IdParams(id=id),
        )
        put_datas.append(
            {"PutRequest": {"Item": dynamodb_types.serialize_dict(asdict(task))}}
        )

    # batch_write_itemは一度に25件までしか追加できないため
    for i in range(0, len(put_datas), 25):
        batch = put_datas[i : i + 25]
        boto3.client("dynamodb").batch_write_item(
            RequestItems={os.environ["NAME_DYNAMODB_TABLE_TASKS"]: batch}
        )

def delete_task_scraping_abstract(kind: str, params_id: str) -> None:
    """
    概要情報スクレイピングタスクの削除

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
        "name": os.environ["NAME_TASK_SCRAPING_DETAIL"],
        "target_arn": os.environ["ARN_LAMBDA_SCRAPING_DETAIL"],
        "invoke_role_arn": os.environ["ARN_IAM_ROLE_INVOKE_SCRAPING_DETAIL"],
    }
    boto3.client("lambda").invoke(
        FunctionName=os.environ["NAME_LAMBDA_HANDLER_SCHEDULES"],
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )