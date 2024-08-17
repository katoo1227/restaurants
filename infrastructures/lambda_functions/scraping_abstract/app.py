import boto3
import os
import json
import requests
import re
import time
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


class Abstract(BaseModel):
    """
    概要情報構造体
    """

    id: str
    small_area_name: str
    thumbnail_url: str | None


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
        # タスクの取得
        task = get_task()

        # 該当レコードがなければスケジュールを削除
        if task == {}:
            delete_schedule()
            return success_response

        # パラメータを分割
        param_arr = task.param.split("_")
        if len(param_arr) != 2:
            raise Exception(f"paramが不正です。{task.param}")

        # 必要なエリアコード一覧を取得
        areas = get_area_codes(param_arr[0])

        # 概要情報の取得
        abstracts = get_abstract_info(areas[0], param_arr[0], int(param_arr[1]), areas[1])

        # サムネ画像をS3へ保存
        put_thumbnails(abstracts)

        # restaurantsへの登録
        register_restaurants(abstracts)

        # 詳細情報スクレイピングタスクの登録
        register_tasks_scraping_detail([a.id for a in abstracts])

        # 概要情報スクレイピングタスクの削除
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
            ":kind": dynamodb_types.serialize(os.environ["NAME_TASK_SCRAPING_ABSTRACT"])
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
    payload = {"task": "delete", "name": os.environ["NAME_TASK_SCRAPING_ABSTRACT"]}
    boto3.client("lambda").invoke(
        FunctionName=os.environ["ARN_LAMBDA_HANDLER_SCHEDULES"],
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )


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


def get_abstract_info(
    service_area_code: str,
    middle_area_code: str,
    page_num: int,
    small_area_codes: list[str]
) -> list[Abstract]:
    """
    概要情報を取得

    Parameters
    ----------
    serviec_area_code: str
        サービスエリアコード
    middle_area_code: str
        中エリアコード
    page_num: int
        ページ数
    small_area_codes: list[str]
        小エリアコードリスト

    Returns
    -------
    list[Abstract]
    """

    # URL
    url_arr = [
        "https://www.hotpepper.jp",
        service_area_code,
        middle_area_code,
        "_".join(small_area_codes),
        f"bgn{page_num}"
    ]
    url = "/".join(url_arr)

    # HTML解析
    html = requests.get(url)
    soup = BeautifulSoup(html.content, "html.parser")

    restaurants = soup.select(".shopDetailCoreInner")
    if len(restaurants) == 0:
        raise Exception(f"「.shopDetailCoreInner」が存在しません。{url}")

    # サムネ画像と飲食店IDを小エリア名を取得
    results = []
    for r in restaurants:
        # サムネ画像
        thumbnail_url = None
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

        # 小エリア名
        genre_name = r.select_one(".parentGenreName")
        if genre_name is None:
            raise Exception(f"「.parentGenreName」が存在しません。{url}")
        genre_name_arr = genre_name.text.split("｜")
        if len(genre_name_arr) != 2:
            raise Exception(f"小エリアの値を取得できません。{url}")
        small_area_name = genre_name_arr[1]

        # 結果配列に格納
        results.append(
            Abstract(
                id=id,
                small_area_name=small_area_name,
                thumbnail_url=thumbnail_url,
            )
        )

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
        if a.thumbnail_url is None:
            res = s3.list_objects_v2(
                Bucket=os.environ["NAME_BUCKET_IMAGES"],
                Prefix=f"thumbnails/{a.id}",
                MaxKeys=1,
            )

            # なければスキップ
            if "Contents" not in res:
                continue

            # ファイルの削除
            s3.delete_object(
                Bucket=os.environ["NAME_BUCKET_IMAGES"], Key=res["Contents"][0]["Key"]
            )
            continue

        # サムネ画像を取得して保存
        img = requests.get(a.thumbnail_url)
        _, ext = os.path.splitext(a.thumbnail_url)
        boto3.client("s3").put_object(
            Bucket=os.environ["NAME_BUCKET_IMAGES"],
            Key=f"thumbnails/{a.id}{ext}",
            Body=img.content,
        )

        # 最後でなければ1秒待つ
        if i + 1 != abstracts_len:
            time.sleep(1)


def register_restaurants(abstracts: list[Abstract]) -> None:
    """
    restaurantsへの登録

    Parameters
    ----------
    abstracts: list[Abstract]
        概要情報リスト
    """
    # 小エリア名とコードのdictを作成
    small_area_names = list(
        set(
            [a.small_area_name for a in abstracts]
        )
    )
    sql = f"""
SELECT
    code,
    name
FROM
    small_area_master
WHERE
    name IN ({', '.join(['?'] * len(small_area_names))});
"""
    res = HSS.exec_query(sql, small_area_names)
    small_area_name_codes = {
        r[1]: r[0]
        for r in res if r != ""
    }

    # SQL
    values_row_str = f"({', '.join(['?'] * 3)})"
    sql = f"""
INSERT INTO
    restaurants_tmp(id, small_area_code, is_thumbnail)
VALUES
    {', '.join([values_row_str] * len(abstracts))}
ON CONFLICT(id) DO UPDATE SET
    small_area_code = excluded.small_area_code,
    is_thumbnail = excluded.is_thumbnail;
"""

    # パラメータ
    params = []
    for a in abstracts:
        is_thumbnail = 0
        if a.thumbnail_url is not None:
            is_thumbnail = 1
        params.extend([a.id, small_area_name_codes[a.small_area_name], is_thumbnail])
    hss = HandlerS3Sqlte(
        os.environ["NAME_BUCKET_DATABASE"],
        os.environ["NAME_FILE_DATABASE"],
        os.environ["NAME_LOCK_FILE_DATABASE"],
    )
    hss.exec_query_with_lock(sql, params)


def register_tasks_scraping_detail(ids: list[str]) -> None:
    """
    詳細情報スクレイピングタスクの登録

    Parameters
    ----------
    ids: list[str]
        飲食店IDリスト
    """

    # 追加データの作成
    put_requests = [
        {
            "PutRequest": {
                "Item": dynamodb_types.serialize_dict(
                    {"kind": os.environ["NAME_TASK_SCRAPING_DETAIL"], "param": id}
                )
            }
        }
        for id in ids
    ]

    # batch_write_itemは一度に25件までしか追加できないため
    for i in range(0, len(put_requests), 25):
        batch = put_requests[i : i + 25]
        boto3.client("dynamodb").batch_write_item(
            RequestItems={os.environ["NAME_DYNAMODB_TABLE_TASKS"]: batch}
        )


def delete_task(kind: str, param: str) -> None:
    """
    概要情報スクレイピングタスクの削除

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
        "name": os.environ["NAME_TASK_SCRAPING_DETAIL"],
        "target_arn": os.environ["ARN_LAMBDA_SCRAPING_DETAIL"],
        "invoke_role_arn": os.environ["ARN_IAM_ROLE_INVOKE_SCRAPING_DETAIL"],
    }
    boto3.client("lambda").invoke(
        FunctionName=os.environ["ARN_LAMBDA_HANDLER_SCHEDULES"],
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
