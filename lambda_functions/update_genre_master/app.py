import boto3
import os
import json
from datetime import datetime
import pytz
from hotpepper_api_client import HotpepperApiClient
from handler_s3_sqlite import HandlerS3Sqlte
from pydantic import BaseModel


class Genre(BaseModel):
    """
    ジャンル
    """

    code: str
    name: str


def lambda_handler(event, context):

    try:

        # ジャンル一覧を取得
        genres = get_genres()

        # ジャンル一覧を更新
        update_genres(genres)

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


def get_genres() -> list[Genre]:
    """
    ジャンル一覧を取得

    Parameters
    ----------
    code: str
        中エリアコード

    Returns
    -------
    list[Genre]
    """
    # ホットペッパーAPIからジャンル一覧を取得
    api_client = HotpepperApiClient(os.environ["PARAMETER_STORE_NAME_HOTPEPPER_API_KEY"])
    res = api_client.get_genres()
    return [
        Genre(
            code=r["code"],
            name=r["name"],
        )
        for r in res["results"]["genre"]
    ]


def update_genres(genres: list[Genre]) -> None:
    """
    ジャンル一覧を更新

    Parameters
    ----------
    genre: list[Genre]
        ジャンル一覧
    """
    sql = get_upsert_sql(genres)
    hss = HandlerS3Sqlte(
        os.environ["NAME_BUCKET_DATABASE"],
        os.environ["NAME_FILE_DATABASE"],
        os.environ["NAME_LOCK_FILE_DATABASE"],
    )
    hss.exec_query_with_lock(sql)


def get_upsert_sql(genres: list[Genre]) -> str:
    """
    upsertを行うSQLを作成

    Parameters
    ----------
    genre: list[Genre]
        ジャンル一覧

    Returns
    -------
    str
    """

    # 今の日時
    tz = pytz.timezone("Asia/Tokyo")
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

    # 引数をVALUES部分に置換
    values_arr = []
    for g in genres:
        values_arr.append(
            "(" + ",".join([f"'{g.code}'", f"'{g.name}'", f"'{now}'", f"'{now}'"]) + ")"
        )
    values = ",".join(values_arr)

    sql = f"""
INSERT INTO genre_master(code, name, created_at, updated_at)
VALUES
{values}
ON CONFLICT(code) DO UPDATE SET
    name = excluded.name,
    updated_at = excluded.updated_at;
"""
    return sql
