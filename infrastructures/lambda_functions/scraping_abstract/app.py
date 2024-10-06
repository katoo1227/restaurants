import boto3
import os
import json
import requests
import re
import time
from bs4 import BeautifulSoup
from db_client import DbClient
from pydantic import BaseModel


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
    name: str
    thumbnail_url: str | None

# DBクライアント
DB_CLIENT = DbClient(
    os.environ["ENV"],
    os.environ["SAKURA_DATABASE_API_KEY_PATH"],
    os.environ["SAKURA_DATABASE_API_URL"],
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

        # 概要情報の取得
        abstracts = get_abstract_info(param_arr[0], int(param_arr[1]))

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
    # SQL
    sql = f"""
SELECT
    kind,
    param
FROM
    update_tasks
WHERE
    kind = ?
ORDER BY
    created_at ASC
LIMIT
    1;
"""

    # パラメータ
    params = [os.environ["NAME_TASK_SCRAPING_ABSTRACT_DB"]]
    res = DB_CLIENT.select(sql, params)

    # 無ければ空オブジェクトで返却
    if len(res["data"]) == 0:
        return {}

    return Task(**res["data"][0])


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


def get_abstract_info(service_area_code: str, page_num: int) -> list[Abstract]:
    """
    概要情報を取得

    Parameters
    ----------
    serviec_area_code: str
        サービスエリアコード
    page_num: int
        ページ数

    Returns
    -------
    list[Abstract]
    """

    # URL
    url = f"https://www.hotpepper.jp/{service_area_code}/lst/bgn{page_num}/"

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

        # 飲食店名
        name = link.text.strip()

        # 結果配列に格納
        results.append(
            Abstract(
                id=id,
                name=name,
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
        # ファイル名の前方一致で検索し、あれば削除する
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
    # SQL
    values_row_str = f"({', '.join(['?'] * 3)})"
    sql = f"""
INSERT INTO
    restaurants (id, name, is_thumbnail)
VALUES
    {', '.join([values_row_str] * len(abstracts))}
ON DUPLICATE KEY UPDATE name = VALUES(name), is_thumbnail = VALUES(is_thumbnail);
"""
    # パラメータ
    params = []
    for a in abstracts:
        is_thumbnail = 0
        if type(a.thumbnail_url) == str:
            is_thumbnail = 1
        params.extend([a.id, a.name, is_thumbnail])

    DB_CLIENT.handle(sql, params)


def register_tasks_scraping_detail(ids: list[str]) -> None:
    """
    詳細情報スクレイピングタスクの登録

    Parameters
    ----------
    ids: list[str]
        飲食店IDリスト
    """
    # SQL
    values_row_str = f"({', '.join(['?'] * 2)})"
    sql = f"""
INSERT INTO
    update_tasks (kind, param)
VALUES
    {', '.join([values_row_str] * len(ids))}
ON DUPLICATE KEY UPDATE kind = VALUES(kind), param = VALUES(param);
    """
    # パラメータ
    params = []
    for id in ids:
        params.extend([os.environ["NAME_TASK_SCRAPING_DETAIL_DB"], id])

    DB_CLIENT.handle(sql, params)


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
    # SQL
    sql = """
DELETE FROM
    update_tasks
WHERE
    kind = ?
    AND param = ?;
"""

    # パラメータ
    params = [kind, param]
    DB_CLIENT.handle(sql, params)


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
