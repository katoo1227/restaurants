import boto3
import os
import json
import requests
import urllib.parse
import re


def lambda_handler(event, context):

    # Lambdaクライアント
    lambda_client = boto3.client("lambda")

    try:
        # パラメータが不正なら終了
        if "middle_area_code" not in event or not re.match(
            r"Y\d{3}", event["middle_area_code"]
        ):
            raise Exception("middle_area_codeが不正です。")

        # 小エリア一覧を取得
        small_areas = get_small_areas(event["middle_area_code"])

        # 小エリアごとのタスクスケジュールを登録
        register_tasks_tmp(small_areas)

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


def get_small_areas(code: str) -> list:
    """
    小エリア一覧を取得

    Parameters
    ----------
    code: str
        中エリアコード

    Returns
    -------
    list
        code: str 小エリアコード
        name: str 小エリア名
    """
    # API URL
    api_url = "https://webservice.recruit.co.jp/hotpepper/small_area/v1/"

    # APIキー
    res = boto3.client("ssm").get_parameter(
        Name="/restaurants/api_key/hotpepper", WithDecryption=True
    )
    api_key = res["Parameter"]["Value"]

    api_params = urllib.parse.urlencode(
        {"key": api_key, "middle_area": code, "format": "json"}
    )
    api_url = f"{api_url}?{api_params}"

    response = requests.get(api_url)
    data = response.json()
    return [
        {
            "small_area_code": a["code"],
            "small_area_name": a["name"],
            "middle_area_code": a["middle_area"]["code"],
            "middle_area_name": a["middle_area"]["name"],
            "large_area_code": a["large_area"]["code"],
            "large_area_name": a["large_area"]["name"],
            "service_area_code": a["service_area"]["code"],
            "service_area_name": a["service_area"]["name"],
            "large_service_area_code": a["large_service_area"]["code"],
            "large_service_area_name": a["large_service_area"]["name"],
        }
        for a in data["results"]["small_area"]
    ]


def register_tasks_tmp(small_areas: list) -> None:
    """
    タスクを登録

    Parameters
    ----------
    small_areas: list
        [
            large_service_area_code: str
                大サービスエリアコード
            large_service_area_name: str
                大サービスエリア名
            service_area_code: str
                サービスエリア名
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
        ]
    """
    dynamodb = boto3.client("dynamodb")

    # 追加データの作成
    put_datas = []
    for a in small_areas:
        # paramsカラムの値
        params = {}
        for key in ["large_service", "service", "large", "middle", "small"]:
            params[f"{key}_area_code"] = {"S": a[f"{key}_area_code"]}
            params[f"{key}_area_name"] = {"S": a[f"{key}_area_name"]}

        # 追加
        put_datas.append(
            {
                "PutRequest": {
                    "Item": {
                        "kind": {"S": "RegisterTasksTmpScrapingAbstractPages"},
                        "params_id": {"S": a["small_area_code"]},
                        "exec_arn": {
                            "S": os.environ[
                                "ARN_LAMBDA_REGISTER_TASK_SCRAPING_ABSTRAT_PAGES"
                            ]
                        },
                        "params": {"M": params},
                    }
                }
            }
        )

    # DynamoDBへの追加
    dynamodb.batch_write_item(
        RequestItems={os.environ["NAME_DYNAMODB_TABLE_TASKS_TMP"]: put_datas}
    )
