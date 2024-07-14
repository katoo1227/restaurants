import boto3
import os
import json
import requests
import re
import time
from datetime import datetime
from bs4 import BeautifulSoup
from check_area_code_names import check_area_code_names


def lambda_handler(event, context):

    # Lambdaクライアント
    lambda_client = boto3.client("lambda")

    try:
        # イベントパラメータのチェック
        event_check(event)

        # 概要情報の取得
        restaurant_ids = get_restaurant_ids(
            event["service_area_code"],
            event["middle_area_code"],
            event["small_area_code"],
            event["page_num"],
        )

        # restaurantsへの登録
        register_restaurants(restaurant_ids)

        # restaurants_areasへの登録
        register_restaurants_areas(
            {k: v for k, v in event.items() if k != "page_num"},
            restaurant_ids,
        )

        # restaurants_tasks_tmpへの登録
        register_tasks_tmp(restaurant_ids)

    except Exception as e:
        payload = {"function_name": context.function_name, "msg": str(e)}
        boto3.client("lambda").invoke(
            FunctionName=os.environ["ARN_LAMBDA_ERROR_COMMON"],
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode("utf-8"),
        )

    return {
        "statusCode": 200,
        "body": "Process Complete",
    }


def event_check(event: dict) -> None:
    """
    イベントパラメータのチェック

    Parameters
    ----------
    event: dict
        イベントパラメータ

    Raises
    ------
        Exception
    """
    # エリアコードとエリア名のチェック
    check_area_code_names(event)

    # page_numのチェック
    if "page_num" not in event:
        raise Exception(f"page_numがありません。{json.dumps(event)}")
    if type(event["page_num"]) != int or event["page_num"] <= 0:
        raise Exception(f"page_numの値が不正です。{json.dumps(event)}")


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
    ids = [{"id": {"S": id}} for id in restaurant_ids]
    id_res = dynamodb.batch_get_item(RequestItems={table_name: {"Keys": ids}})
    records = id_res["Responses"][table_name]

    # 今の日時
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 追加データの作成
    add_datas = []
    record_ids = [r["id"]["S"] for r in records]
    for id in restaurant_ids:
        if id in record_ids:
            continue
        add_datas.append(
            {
                "PutRequest": {
                    "Item": {
                        "id": {"S": id},
                        "is_notified": {"N": "0"},
                        "created_at": {"S": now},
                        "updated_at": {"S": now},
                    }
                }
            }
        )

    # DynamoDBへの追加
    if len(add_datas) > 0:
        dynamodb.batch_write_item(RequestItems={table_name: add_datas})


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
    dynamodb = boto3.client("dynamodb")

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
                item = {
                    "area_category": {"S": ac},
                    "code_restaurant_id": {"S": f"{event[code_key]}#{id}"},
                    "restaurant_id": {"S": id},
                    "code": {"S": event[code_key]},
                    "name": {"S": event[name_key]},
                }
                update_datas.append({"PutRequest": {"Item": item}})

        # DynamoDBの一括更新
        dynamodb.batch_write_item(
            RequestItems={os.environ["NAME_DYNAMODB_RESTAURANTS_AREAS"]: update_datas}
        )


def register_tasks_tmp(ids: list[str]) -> None:
    """
    restaurants_tasks_tmpへの登録

    Parameters
    ----------
    ids: list[str]
        飲食店IDリスト
    """
    dynamodb = boto3.client("dynamodb")

    # 追加データの作成
    put_datas = []
    for id in ids:
        item = {
            "kind": {"S": "ScrapingDetail"},
            "params_id": {"S": id},
            "exec_arn": {"S": os.environ["ARN_LAMBDA_SCRAPING_DETAIL"]},
            "params": {"M": {"id": {"S": id}}},
        }
        put_datas.append({"PutRequest": {"Item": item}})

    # DynamoDBへの追加
    dynamodb.batch_write_item(
        RequestItems={os.environ["NAME_DYNAMODB_TABLE_TASKS_TMP"]: put_datas}
    )
