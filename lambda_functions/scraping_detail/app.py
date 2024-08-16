import boto3
import os
import json
import requests
import time
import urllib.parse
from bs4 import BeautifulSoup
import dynamodb_types
from http.client import RemoteDisconnected
from pydantic import BaseModel
from handler_s3_sqlite import HandlerS3Sqlte
from datetime import datetime
import pytz


class Task(BaseModel):
    """
    タスク構造体
    """
    kind: str
    param: str

class Image(BaseModel):
    """
    画像構造体
    """
    url: str
    alt: str

class Detail(BaseModel):
    """
    詳細情報構造体
    """
    name: str
    genre: str
    sub_genre: str|None
    address: str
    latitude: float
    longitude: float
    open_hours: str
    close_days: str
    parking: str

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

        # 画像情報を更新
        put_images(task.param)

        # 詳細情報の取得
        info = get_detail_info(task.param)

        # 飲食店情報の更新
        update_restaurant(task.param, info)

        # タスクの削除
        delete_task(task.kind, task.param)
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
    タスクの取得

    Returns
    -------
    Task
    """
    res = boto3.client("dynamodb").query(
        TableName=os.environ["NAME_DYNAMODB_TABLE_TASKS"],
        KeyConditionExpression="kind = :kind",
        ExpressionAttributeValues={
            ":kind": dynamodb_types.serialize(os.environ["NAME_TASK_SCRAPING_DETAIL"])
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
    payload = {"task": "delete", "name": os.environ["NAME_TASK_SCRAPING_DETAIL"]}
    boto3.client("lambda").invoke(
        FunctionName=os.environ["ARN_LAMBDA_HANDLER_SCHEDULES"],
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )


def put_images(id: str) -> None:
    """
    画像情報を更新

    Parameters
    ----------
    id: str
        飲食店ID
    """

    s3 = boto3.client("s3")

    # 写真一覧URL
    url = f"https://www.hotpepper.jp/str{id}/photo/"

    # HTMLを取得
    html = requests.get(url)

    # ステータスが200以外の場合は画像がないので既存の画像を削除
    if html.status_code != 200:
        # もともとなければ何もしない
        res = s3.list_objects_v2(
            Bucket=os.environ["NAME_BUCKET_IMAGES"], Prefix=f"images/{id}/"
        )
        if "Contents" not in res:
            return

        # 画像フォルダごと削除
        delete_objects = [{"Key": obj["Key"]} for obj in res["Contents"]]
        s3.delete_objects(
            Bucket=os.environ["NAME_BUCKET_IMAGES"], Delete={"Objects": delete_objects}
        )

        # imagesテーブルから削除
        sql = f"""
DELETE FROM
    images
WHERE
    id = ?;
"""
        HSS.exec_query_with_lock(sql, [id])
        return

    # HTML解析
    try:
        soup = BeautifulSoup(html.content, "html.parser")
    except RemoteDisconnected as e:
        raise Exception(f"{e}\n{url}")

    # 「.jsc-photo-list」での検索
    is_jsc_photo_list = False
    jsc_photo_list = soup.select(".jsc-photo-list")
    jsc_photo_list_len = len(jsc_photo_list)
    if jsc_photo_list_len != 0:
        is_jsc_photo_list = True

    # 「.jsc-photo-list-elm」での検索
    is_jsc_photo_list_elm = False
    jsc_photo_list_elm = soup.select(".jsc-photo-list-elm")
    jsc_photo_list_elm_len = len(jsc_photo_list_elm)
    if jsc_photo_list_elm_len != 0:
        is_jsc_photo_list_elm = True

    # いずれも取得できていなければエラー
    if is_jsc_photo_list == False and is_jsc_photo_list_elm == False:
        raise Exception(f"飲食店画像一覧の取得に失敗。{id}")

    # 画像URLとaltを格納
    img_infos = []
    if is_jsc_photo_list:
        for elm in jsc_photo_list:
            img_path = elm.get("data-src")
            if img_path is None:
                raise Exception(f"飲食店画像URLの取得に失敗。{str(elm)}")

            # URLが相対パスの場合と絶対パスの場合がある
            if img_path.startswith("https://"):
                img_url = img_path
            else:
                img_url = f"https://www.hotpepper.jp{img_path}"
            img_infos.append(
                Image(
                    **{
                        "url": img_url,
                        "alt": elm.get("data-alt")
                    }
                )
            )
    if is_jsc_photo_list_elm:
        for elm in jsc_photo_list_elm:
            img_infos.append(
                Image(
                    **{
                        "url": elm.get("data-src"),
                        "alt": elm.get("data-alt")
                    }
                )
            )

    # もともとの枚数より少なければ、その分を削除
    sql = f"""
SELECT
    COUNT(0) AS cnt
FROM
    images
WHERE
    id = ?;
"""
    res = HSS.exec_query(sql, [id])

    items_len = res[0][0]
    img_infos_len = len(img_infos)
    if img_infos_len < items_len:
        # S3内の飲食店画像一覧を取得
        s3_res = s3.list_objects_v2(
            Bucket=os.environ["NAME_BUCKET_IMAGES"],
            Prefix=f"images/{id}",
        )
        if "Contents" not in s3_res:
            raise Exception(f"Imagesバケット内の画像取得に失敗。{f"images/{id}"}")

        # imagesテーブルから削除
        sql = f"""
DELETE FROM
    images
WHERE
    id = ?
    AND order_num >= ?;
"""
        params = [id, items_len - img_infos_len]
        HSS.exec_query_with_lock(sql, params)

        # S3画像の削除
        for i in range(items_len - img_infos_len):
            order = img_infos_len + i + 1
            for c in s3_res["Contents"]:
                if c["Key"].startswith(f"images/{id}/{order}"):
                    _, ext = os.path.splitext(c["Key"])
                    s3.delete_object(
                        Bucket=os.environ["NAME_BUCKET_IMAGES"], Key=f"images/{id}/{order}{ext}"
                    )
                    break

    # 画像を取得して保存
    for i, img_info in enumerate(img_infos):
        image = requests.get(img_info.url)
        if image.status_code != 200:
            raise Exception(f"飲食店画像の取得に失敗。id: {id}, url: {img_info.url}")
        _, ext = os.path.splitext(img_info.url)
        boto3.client("s3").put_object(
            Bucket=os.environ["NAME_BUCKET_IMAGES"],
            Key=f"images/{id}/{i + 1}{ext}",
            Body=image.content,
        )

        # 最後でなければ1秒待つ
        if i + 1 != img_infos_len:
            time.sleep(1)

    # imageテーブルを更新
    query = get_images_upsert_sql(id, img_infos)
    HSS.exec_query_with_lock(query[0], query[1])

    return img_infos_len

def get_images_upsert_sql(id: str, images: list[Image]) -> tuple:
    """
    imagesテーブルのupsertのSQL文を取得

    Parameters
    ----------
    id: str
        飲食店ID
    images: list[Image]
        画像情報リスト

    Returns
    -------
    tuple
        sql: SQL文
        params: placeholderの値
    """
    # 今の日時
    tz = pytz.timezone("Asia/Tokyo")
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

    # SQL
    values_row_str = f"({', '.join(['?'] * 5)})"
    sql =  f"""
INSERT INTO
    images(id, order_num, name, created_at, updated_at)
VALUES
    {', '.join([values_row_str] * len(images))}
ON CONFLICT(id, order_num) DO UPDATE SET
    name = excluded.name,
    updated_at = excluded.updated_at;
"""

    # パラメータ
    params = []
    for i, image in enumerate(images):
        params.extend([id, i + 1, image.alt, now, now])

    return sql, params


def get_detail_info(id: str) -> Detail:
    """
    詳細情報を取得

    Parameters
    ----------
    id: str
        飲食店ID

    Returns
    -------
    Detail
    """
    # 返り値の初期化
    result = {
        "name": "",
        "genre": "",
        "sub_genre": None,
        "address": "",
        "latitude": 0,
        "longitude": 0,
        "open_hours": "",
        "close_days": "",
        "parking": "",
    }

    # URL
    url = f"https://www.hotpepper.jp/str{id}"

    # HTML解析
    html = requests.get(url)
    try:
        soup = BeautifulSoup(html.content, "html.parser")
    except RemoteDisconnected as e:
        raise Exception(f"{e}\n{url}")

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

        genre_titles_dom = dl_tag.select(".shopInfoInnerItem")
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
        # JSレンダリングされているため取得不可
        # if genre_titles_dom_len == 2:
        #     sub_genre_link = genre_titles_dom[1].select_one("a")
        #     if sub_genre_link is None:
        #         raise Exception(f"サブジャンルの値の取得失敗。{url}\n<a>が存在しない。")
        #     result["sub_genre"] = sub_genre_link.text.strip()

    # 住所・営業時間・定休日
    info_tables = soup.select(".infoTable")
    if len(info_tables) == 0:
        raise Exception(
            f"住所・営業時間・定休日の取得失敗。{url}\nページ下部に詳細情報がない。"
        )
    for table in info_tables:

        # 飲食店情報の表でなければスキップ
        if table["summary"] != "お店情報" and table["summary"] != "設備":
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
            if item_name not in ["住所", "営業時間", "定休日", "駐車場"]:
                continue

            td = tr.select_one("td")
            if td is None:
                raise Exception(f"住所の取得に失敗。{url}\n{str(tr)}")

            # 住所
            if item_name == "住所":
                result["address"] = td.text.strip()

            # 営業時間
            if item_name == "営業時間":
                result["open_hours"] = td.decode_contents(formatter="html").strip()

            # 定休日
            if item_name == "定休日":
                result["close_days"] = td.decode_contents(formatter="html").strip()

            # 駐車場
            if item_name == "駐車場":
                result["parking"] = td.text.strip()

    # 緯度・経度
    if result["address"] != "":
        # Google Geocoding APIで住所から緯度・経度を取得
        res = boto3.client("ssm").get_parameter(
            Name=os.environ["PARAMETER_STORE_NAME_GCP_API_KEY"],
            WithDecryption=True,
        )
        url_params = {"address": result["address"], "key": res["Parameter"]["Value"]}
        url = f"https://maps.googleapis.com/maps/api/geocode/json?{urllib.parse.urlencode(url_params)}"
        response = requests.get(url)

        # 正しく取得できていなければ例外を投げる
        data = response.json()
        try:
            lat = data["results"][0]["geometry"]["location"]["lat"]
            lng = data["results"][0]["geometry"]["location"]["lng"]
        except KeyError:
            raise Exception(f"緯度経度の取得に失敗。\n{id}\n{url}")

        result["latitude"] = lat
        result["longitude"] = lng

    return Detail(**result)


def update_restaurant(id: str, info: Detail) -> None:
    """
    飲食店テーブルの更新

    Parameters
    ----------
    id: str
        飲食店ID
    info: Detail
        詳細情報
    """

    # ジャンルをコードに変換
    genres = [info.genre]
    if info.sub_genre is not None:
        genres.extend(info.sub_genre)

    # SQL
    sql = f"""
SELECT
    code,
    name
FROM
    genre_master
WHERE
    name IN ({', '.join(['?'] * len(genres))});
"""
    res = HSS.exec_query(sql, genres)
    genre_name_codes = {
        r[1]: r[0]
        for r in res if r != ""
    }
    genre_code = genre_name_codes[info.genre]
    sub_genre_code = None
    if info.sub_genre is not None:
        sub_genre_code = genre_name_codes[info.sub_genre]

    # restuarants_tmpテーブルの更新
    sql = f"""
UPDATE
    restaurants_tmp
SET
    name = ?,
    genre_code = ?,
    sub_genre_code = ?,
    address = ?,
    latitude = ?,
    longitude = ?,
    open_hours = ?,
    close_days = ?,
    parking = ?
WHERE
    id = ?;
"""
    params = [
        info.name,
        genre_code,
        sub_genre_code,
        info.address,
        info.latitude,
        info.longitude,
        info.open_hours,
        info.close_days,
        info.parking,
        id
    ]
    HSS.exec_query_with_lock(sql, params)


def delete_task(kind: str, id: str) -> None:
    """
    タスクの削除

    Parameters
    ----------
    kind: str
        タスクの種類

    id: str
        飲食店ID
    """
    boto3.client("dynamodb").delete_item(
        TableName=os.environ["NAME_DYNAMODB_TABLE_TASKS"],
        Key=dynamodb_types.serialize_dict({"kind": kind, "param": id}),
    )
