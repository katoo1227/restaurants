import boto3
import os
import json
from hotpepper_api_client import HotpepperApiClient
from db_client import DbClient
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

    Returns
    -------
    list[Genre]
    """
    # ホットペッパーAPIからジャンル一覧を取得
    api_client = HotpepperApiClient(
        os.environ["PARAMETER_STORE_NAME_HOTPEPPER_API_KEY"]
    )
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
    # SQL
    values_row_str = f"({', '.join(['?'] * 2)})"
    sql = f"""
INSERT INTO
    genre_master (code, name)
VALUES
    {', '.join([values_row_str] * len(genres))}
ON DUPLICATE KEY UPDATE name = VALUES(name);
    """

    # パラメータ
    params = []
    for g in genres:
        params.extend([g.code, g.name])

    db_client = DbClient(
        os.environ["ENV"],
        os.environ["SAKURA_DATABASE_API_KEY_PATH"],
        os.environ["SAKURA_DATABASE_API_URL"]
    )
    db_client.handle(sql, params)
