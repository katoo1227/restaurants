import boto3
import os
import json
import dynamodb_types
from handler_s3_sqlite import HandlerS3Sqlte
from pydantic import BaseModel


class EventParam(BaseModel):
    """
    イベントパラメータ構造体
    """

    middle_area_code: str


def lambda_handler(event, context):

    try:

        # パラメータを構造体に適用
        params = EventParam(**event)

        # 小エリア一覧を取得
        small_areas = get_small_area_codes(params)

        # 小エリアごとのタスクを登録
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


def get_small_area_codes(params: EventParam) -> list[str]:
    """
    小エリアコード一覧を取得

    Parameters
    ----------
    code: EventParam

    Returns
    -------
    list[str]
    """

    sql = f"""
SELECT
    code
FROM
    small_area_master
WHERE
    middle_area_code = '{params.middle_area_code}';
"""
    hss = HandlerS3Sqlte(
        os.environ["NAME_BUCKET_DATABASE"],
        os.environ["NAME_FILE_DATABASE"],
        os.environ["NAME_LOCK_FILE_DATABASE"]
    )
    res = hss.exec_query(sql)

    return [r[0] for r in res]


def register_tasks(small_areas: list[str]) -> None:
    """
    タスクを登録

    Parameters
    ----------
    small_areas: list[str]
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
                            "param": a,
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
        "target_arn": os.environ["ARN_LAMBDA_REGISTER_TASKS_PAGES"],
        "invoke_role_arn": os.environ["ARN_IAM_ROLE_INVOKE_REGISTER_PAGES"],
    }
    boto3.client("lambda").invoke(
        FunctionName=os.environ["ARN_LAMBDA_HANDLER_SCHEDULES"],
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
