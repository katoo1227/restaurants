import boto3
import os
import json
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime


def lambda_handler(event, context):
    # Lambdaクライアント
    lambda_client = boto3.client("lambda")

    try:
        # イベントパラメータのチェック
        event_check(event)

        # 詳細情報の取得
        info = get_detail_info(event["id"])

        # 飲食店情報の更新
        update_restaurant(event["id"], info)
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


def event_check(event: dict) -> None:
    """
    イベントパラメータのチェック

    Parameters
    ----------
    event: dict
        イベントパラメータ
    """
    if "id" not in event:
        raise Exception(f"idがありません{json.dumps(event)}")

    if not re.match(r"J\d+", event["id"]):
        raise Exception(f"idの値が不正です。{json.dumps(event)}")


def get_detail_info(id: str) -> dict:
    """
    詳細情報を取得

    Parameters
    ----------
    id: str
        飲食店ID

    Returns
    -------
    dict
        name: str
            飲食店名
        genre: str
            ジャンル
        sub_genre: str
            サブジャンル
        address: str
            住所
        open_hours: str
            営業時間
        close_days: str
            定休日情報
    """
    # 返り値の初期化
    result = {
        "name": "",
        "genre": "",
        "sub_genre": "",
        "address": "",
        "open_hours": "",
        "close_days": "",
    }

    # URL
    url = f"https://www.hotpepper.jp/str{id}"

    # HTML解析
    html = requests.get(url)
    soup = BeautifulSoup(html.content, "html.parser")

    # 飲食店名
    name_dom = soup.select_one("h1.shopName")
    if name_dom is None:
        raise Exception(f"飲食店名の取得失敗。{url}")
    result["name"] = name_dom.text

    # ジャンル・サブジャンル
    section_blocks = soup.select(".jscShopInfoInnerSection .shopInfoInnerSectionBlock")
    if len(section_blocks) == 0:
        raise Exception(f"ジャンル・サブジャンルの取得失敗。{url}")
    for dl_tag in section_blocks:
        dt = dl_tag.select_one("dt")
        if dt is None:
            raise Exception(
                f"ジャンル・サブジャンルのセクションタイトルの取得失敗。{url}\n{str(dl_tag)}"
            )

        # ジャンルでなければスキップ
        if dt.text != "ジャンル":
            continue

        genre_titles_dom = dl_tag.select(".shopInfoInnerItemTitle")
        genre_titles_dom_len = len(genre_titles_dom)
        if genre_titles_dom_len == 0:
            raise Exception(
                f"ジャンル・サブジャンルの値の取得失敗。{url}\n「.shopInfoInnerItemTitle」が存在しない。"
            )

        # ジャンル
        genre_link = genre_titles_dom[0].select_one("a")
        if genre_link is None:
            raise Exception(f"ジャンルの値の取得失敗。{url}\n<a>が存在しない。")
        result["genre"] = genre_link.text.strip()

        # サブジャンル
        if genre_titles_dom_len == 2:
            sub_genre_link = genre_titles_dom[1].select_one("a")
            if sub_genre_link is None:
                raise Exception(f"サブジャンルの値の取得失敗。{url}\n<a>が存在しない。")
            result["sub_genre"] = sub_genre_link.text.strip()

    # 住所・営業時間・定休日
    info_tables = soup.select(".infoTable")
    if len(info_tables) == 0:
        raise Exception(
            f"住所・営業時間・定休日の取得失敗。{url}\nページ下部に詳細情報がない。"
        )
    for table in info_tables:

        # 飲食店情報の表でなければスキップ
        if table["summary"] != "お店情報":
            continue

        # 行の取得
        trs = table.select("tr")
        if len(trs) == 0:
            raise Exception(f"お店情報の表に行がない。{url}")

        # 項目名
        for tr in trs:
            th = tr.select_one("th")
            if th is None:
                raise Exception(f"お店情報に項目がない行がある。{url}")

            # 取得対象でなければスキップ
            item_name = th.text.strip()
            if item_name not in ["住所", "営業時間", "定休日"]:
                continue

            td = tr.select_one("td")
            if td is None:
                raise Exception(f"住所の取得に失敗。{url}\n{str(tr)}")
            item_value = td.text.strip()

            # 住所
            if item_name == "住所":
                result["address"] = td.text.strip()

            # 営業時間
            if item_name == "営業時間":
                result["open_hours"] = td.decode_contents(formatter="html").strip()

            # 定休日
            if item_name == "定休日":
                result["close_days"] = td.decode_contents(formatter="html").strip()

    return result


def update_restaurant(id: str, info: dict) -> None:
    """
    飲食店テーブルの更新

    Parameters
    ----------
    id: str
        飲食店ID
    info: dict
        name: str
            飲食店名
        genre: str
            ジャンル
        sub_genre: str
            サブジャンル
        address: str
            住所
        open_hours: str
            営業時間
        close_days: str
            定休日情報
    """
    dynamodb = boto3.client("dynamodb")
    res = dynamodb.get_item(
        TableName=os.environ["NAME_DYNAMODB_RESTAURANTS"], Key={"id": {"S": id}}
    )
    if "Item" not in res:
        raise Exception(f"飲食店データの取得に失敗。{id}のレコードが存在しない。")

    # put対象かの判定
    record = res["Item"]
    if (
        "name" not in record
        or info["name"] != record["name"]
        or "address" not in record
        or info["address"] != record["address"]
        or "open_hours" not in record
        or info["open_hours"] != record["open_hours"]
        or "close_days" not in record
        or info["close_days"] != record["close_days"]
    ):
        dynamodb.put_item(
            TableName=os.environ["NAME_DYNAMODB_RESTAURANTS"],
            Item={
                "id": {"S": id},
                "name": {"S": info["name"]},
                "address": {"S": info["address"]},
                "open_hours": {"S": info["open_hours"]},
                "close_days": {"S": info["close_days"]},
                "updated_at": {"S": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
            },
        )
