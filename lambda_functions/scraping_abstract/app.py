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


@dataclass
class UpsertData(DSArea):
    """
    upsertデータのベース
    """

    id: str
    is_notified: int
    is_thumbnail: int
    created_at: str
    updated_at: str


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
        register_restaurants(abstracts, task.params)

        # 詳細情報スクレイピングタスクの登録
        restaurant_ids = [a.id for a in abstracts]
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
        概要情報リスト
    """
    s3 = boto3.client("s3")
    abstracts_len = len(abstracts)
    for i, a in enumerate(abstracts):
        # サムネ画像URLがなければもともとの画像を削除
        # try catchでいきなりdelete_itemの場合、拡張子がjpgとは限らない可能性がある
        # ファイル名の前方一致でで検索し、あれば削除する
        if a.thumbnail_url == "":
            res = s3.list_objects_v2(
                Bucket=os.environ["NAME_IMAGES_BUCKET"],
                Prefix=f"thumbnails/{a.id}",
                MaxKeys=1,
            )

            # なければスキップ
            if "Contents" not in res:
                continue

            # ファイルの削除
            print(res["Contents"][0]["Key"])
            s3.delete_object(
                Bucket=os.environ["NAME_IMAGES_BUCKET"], Key=res["Contents"][0]["Key"]
            )
            continue

        # サムネ画像を取得して保存
        img = requests.get(a.thumbnail_url)
        _, ext = os.path.splitext(a.thumbnail_url)
        boto3.client("s3").put_object(
            Bucket=os.environ["NAME_IMAGES_BUCKET"],
            Key=f"thumbnails/{a.id}{ext}",
            Body=img.content,
        )

        # 最後でなければ1秒待つ
        if i + 1 != abstracts_len:
            time.sleep(1)


def register_restaurants(abstracts: list[Abstract], params: DSAreaPageNum) -> None:
    """
    restaurantsへの登録

    Parameters
    ----------
    abstracts: list[Abstract]
        概要情報リスト
    params: DSAreaPageNum
        page_num付きエリアパラメータ
    """
    dynamodb = boto3.client("dynamodb")
    table_name = os.environ["NAME_DYNAMODB_RESTAURANTS"]

    # パーティションキーで検索
    ids = [{"id": dynamodb_types.serialize(a.id)} for a in abstracts]
    id_res = dynamodb.batch_get_item(RequestItems={table_name: {"Keys": ids}})
    records = id_res["Responses"][table_name]

    # 今の日時
    tz = pytz.timezone("Asia/Tokyo")
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

    # upsertデータの作成
    upsert_datas = []
    for a in abstracts:

        # upsertデータのベースdict
        upsert_base = {
            "id": a.id,
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
            "is_thumbnail": a.thumbnail_url != "",
            "updated_at": now,
        }

        # レコードが存在しているか
        record_row = None
        for r in records:
            item = dynamodb_types.deserialize_dict(r)
            if a.id == item["id"]:
                record_row = item
                break

        is_thumbnail = a.thumbnail_url != ""

        if record_row is None:
            # レコードがないので追加対象
            upsert_add = {
                "is_notified": 0,
                "created_at": now,
            }
            upsert_data = upsert_base | upsert_add
        else:
            # カラムが不足or値が違えば更新対象
            is_update = False
            for key in asdict(params).keys():
                if key not in record_row or record_row[key] != getattr(params, key):
                    is_update = True
                    break
            else:
                if (
                    "is_thumbnail" not in record_row
                    or record_row["is_thumbnail"] != is_thumbnail
                ):
                    is_update = True
            if is_update == False:
                continue

            # upsertデータの作成
            upsert_add = {
                "is_notified": record_row["is_notified"],
                "created_at": record_row["created_at"],
            }
            upsert_data = upsert_base | upsert_add

        # upsertデータへ追加
        # 構造体を通すことで、型やキーのチェックができる
        upsert_datas.append(
            {
                "PutRequest": {
                    "Item": dynamodb_types.serialize_dict(
                        asdict(UpsertData(**upsert_data))
                    )
                }
            }
        )

    # 一括upsert
    # batch_write_itemは一度に25件までしか追加できないため
    if len(upsert_datas) == 0:
        return
    for i in range(0, len(upsert_datas), 25):
        batch = upsert_datas[i : i + 25]
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
