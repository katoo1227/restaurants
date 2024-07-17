import boto3
import os
import json
import requests
import urllib.parse
import re
import dynamodb_types
from dataclasses import dataclass, asdict
from ds_area import DSArea


@dataclass
class EventParam:
    """
    イベントパラメータ構造体
    """

    middle_area_code: str

    def __post_init__(self):
        if not re.match(r"Y\d{3}", self.middle_area_code):
            raise Exception("middle_area_codeが不正です。")


def lambda_handler(event, context):

    try:

        # パラメータが不正なら終了
        if "middle_area_code" not in event:
            raise Exception("middle_area_codeがありません。")
        params = EventParam(middle_area_code=event["middle_area_code"])

        # 小エリア一覧を取得
        small_areas = get_small_areas(params.middle_area_code)

        # 小エリアごとのタスクスケジュールを登録
        register_tasks(small_areas)

        # EventBridgeスケジュールを登録
        register_schedule()

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


def get_small_areas(code: str) -> list[DSArea]:
    """
    小エリア一覧を取得

    Parameters
    ----------
    code: str
        中エリアコード

    Returns
    -------
    list[DSArea]
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
        DSArea(
            large_service_area_code=a["large_service_area"]["code"],
            large_service_area_name=a["large_service_area"]["name"],
            service_area_code=a["service_area"]["code"],
            service_area_name=a["service_area"]["name"],
            large_area_code=a["large_area"]["code"],
            large_area_name=a["large_area"]["name"],
            middle_area_code=a["middle_area"]["code"],
            middle_area_name=a["middle_area"]["name"],
            small_area_code=a["code"],
            small_area_name=a["name"],
        )
        for a in data["results"]["small_area"]
    ]


def register_tasks(small_areas: list[DSArea]) -> None:
    """
    タスクを登録

    Parameters
    ----------
    small_areas: list[DSArea]
        小エリアリスト
    """
    dynamodb = boto3.client("dynamodb")

    # 追加データの作成
    put_datas = []
    for a in small_areas:

        # 追加
        put_datas.append(
            {
                "PutRequest": {
                    "Item": dynamodb_types.serialize_dict(
                        {
                            "kind": os.environ["NAME_TASK_REGISTER_PAGES"],
                            "params_id": a.small_area_code,
                            "params": asdict(a),
                        }
                    )
                }
            }
        )

    # DynamoDBへの追加
    dynamodb.batch_write_item(
        RequestItems={os.environ["NAME_DYNAMODB_TABLE_TASKS"]: put_datas}
    )


def register_schedule() -> None:
    """
    スケジュールを登録
    """
    payload = {
        "task": "register",
        "name": os.environ["NAME_TASK_REGISTER_PAGES"],
        "target_arn": os.environ["ARN_LAMBDA_REGISTER_PAGES"],
        "invoke_role_arn": os.environ["ARN_IAM_ROLE_INVOKE_REGISTER_PAGES"],
    }
    boto3.client("lambda").invoke(
        FunctionName=os.environ["NAME_LAMBDA_HANDLER_SCHEDULES"],
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
