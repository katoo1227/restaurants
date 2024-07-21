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
from ds_area import DSArea


@dataclass
class DSAreaPageNum(DSArea):
    page_num: int

    def __post_init__(self):
        super().__post_init__()
        if not isinstance(self.page_num, int) or self.page_num < 0:
            raise Exception(f"page_numの値が不正です。{json.dumps(asdict(self))}")


@dataclass
class IdParams:
    id: str


@dataclass
class Task:
    kind: str
    params_id: str
    params: DSAreaPageNum | IdParams


@dataclass
class Abstract:
    id: str
    thumbnail_url: str


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
        abstracts = get_abstract_info(
            task.params.service_area_code,
            task.params.middle_area_code,
            task.params.small_area_code,
            task.params.page_num,
        )

        # サムネ画像をS3へ保存
        put_thumbnails(abstracts)

        # restaurantsへの登録
        restaurant_ids = [a.id for a in abstracts]
        register_restaurants(restaurant_ids, task.params)

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
        kind=res["kind"],
        params_id=res["params_id"],
        params=DSAreaPageNum(**res["params"]),
    )


def delete_schedule() -> None:
    """
    スケジュールの削除
    """
    payload = {"task": "delete", "name": os.environ["NAME_TASK_SCRAPING_ABSTRACT"]}
    boto3.client("lambda").invoke(
        FunctionName=os.environ["ARN_LAMBDA_HANDLER_SCHEDULES"],
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )


def get_abstract_info(
    service_area_code: str, middle_area_code: str, small_area_code: str, page_num: int
) -> list[Abstract]:
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
    list[Abstract]
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

    restaurants = soup.select(".shopDetailCoreInner")
    if len(restaurants) == 0:
        raise Exception(f"「.shopDetailCoreInner」が存在しません。{url}")

    # サムネ画像と飲食店IDを取得
    results = []
    for r in restaurants:
        # サムネ画像
        thumbnail_url = ""
        img = r.select_one(".shopPhotoMain img")
        if img is not None:
            thumbnail_url = img.get("src")

        # 飲食店ID
        link = r.select_one(".shopDetailStoreName a")
        if link is None:
            raise Exception(f"「.shopDetailStoreName a」が存在しません。{url}")
        match = re.search(r"/str(J\d+)/", link.get("href"))
        if match is None:
            raise Exception(f"飲食店IDの取得に失敗しました。{str(link)}")
        id = match.group(1)
        try:
            results.append(
                Abstract(
                    id=id,
                    thumbnail_url=thumbnail_url,
                )
            )
        except Exception as e:
            print(e)

    return results


def put_thumbnails(abstracts: list[Abstract]) -> None:
    """
    サムネ画像をS3へ保存

    Parameters
    ----------
    abstracts: list[Abstract]
    """
    for a in abstracts:
        if a.thumbnail_url == "":
            continue
        img = requests.get(a.thumbnail_url)
        _, ext = os.path.splitext(a.thumbnail_url)
        boto3.client("s3").put_object(
            Bucket=os.environ["NAME_IMAGES_BUCKET"],
            Key=f"thumbnails/{a.id}{ext}",
            Body=img.content,
        )


def register_restaurants(restaurant_ids: list[str], params: DSAreaPageNum) -> None:
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
                            "large_service_area_code": params.large_service_area_code,
                            "large_service_area_name": params.large_service_area_name,
                            "service_area_code": params.service_area_code,
                            "service_area_name": params.service_area_name,
                            "large_area_code": params.large_area_code,
                            "large_area_name": params.large_area_name,
                            "middle_area_code": params.middle_area_code,
                            "middle_area_name": params.middle_area_name,
                            "small_area_code": params.small_area_code,
                            "small_area_name": params.small_area_name,
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
        FunctionName=os.environ["ARN_LAMBDA_HANDLER_SCHEDULES"],
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
