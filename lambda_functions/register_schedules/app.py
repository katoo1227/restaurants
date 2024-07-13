import json
import os
import boto3
from boto3.dynamodb.types import TypeDeserializer
from decimal import Decimal
import pytz
from datetime import datetime, time, timedelta
from dataclasses import dataclass


@dataclass
class TaskTmp:
    """
    RestaurantsTasksTmpテーブルのレコード返り値の構造体
    """

    params_id: str
    exec_arn: str
    params: dict


def lambda_handler(event, context):

    try:
        # イベントパラメータのチェック
        check_event(event)

        # 一時テーブルから該当タスクを取得
        tasks = get_tasks_from_tmp(event["kind"])

        # スケジュール登録
        register_schedules(event["kind"], tasks)

        # 一時テーブルから該当タスクを削除
        delete_tasks_to_tmp(event["kind"], tasks)

    except Exception as e:
        # Lambdaクライアント
        lambda_client = boto3.client("lambda")
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


def check_event(event: dict) -> None:
    """
    イベントパラメータのチェック

    Parameters
    ----------
    event: dict
        イベントパラメータ

    Raises:
        Exception
    """
    if "kind" not in event:
        raise Exception(f"kindがありません。{json.dumps(event)}")

    # 許可されたkindのうちのどれかかの判定
    approval_kinds = [
        "RegisterTasksTmpScrapingAbstractPages",
        "ScrapingAbstract",
        "ScrapingDetail",
    ]
    if event["kind"] not in approval_kinds:
        raise Exception(f"kindの値が不正です。{json.dumps(event)}")


def get_tasks_from_tmp(kind: str) -> list[TaskTmp]:
    """
    一時テーブルからタスクを取得

    Parameters
    ----------
    kind: str
        タスクの種類

    Returns
    -------
    list[TaskTmp]
    """
    # 該当レコードを取得
    dynamodb = boto3.client("dynamodb")
    res = dynamodb.query(
        TableName=os.environ["NAME_DYNAMODB_TABLE_TASKS_TMP"],
        KeyConditionExpression="kind = :kind",
        ExpressionAttributeValues={":kind": {"S": kind}},
    )

    # TaskTmp型に変換して返す
    return [
        TaskTmp(i["params_id"]["S"], i["exec_arn"]["S"], i["params"]["M"])
        for i in res["Items"]
    ]


def register_schedules(kind: str, tasks: list[TaskTmp]) -> None:
    """
    スケジュールの登録

    Parameters
    ----------
    kind: str
        スケジュールの種類
    tasks: list[TaskTmp]
        タスク一覧
    """

    # EventBridge Schedulerクライアント
    scheduler = boto3.client("scheduler")

    # スケジュールの実行時間
    current_date = datetime.now(pytz.timezone("Asia/Tokyo")).date()
    if kind == "RegisterTasksTmpScrapingAbstractPages":
        start_datetime = datetime.combine(current_date, time(1, 0))
        role_arn = os.environ[
            "ARN_IAM_ROLE_INVOKE_REGISTER_TASKS_TMP_SCRAPING_ABSTRACT_PAGES"
        ]
    elif kind == "ScrapingAbstract":
        start_datetime = datetime.combine(current_date, time(0, 10))
        role_arn = os.environ["ARN_IAM_ROLE_INVOKE_SCRAPING_ABSTRACT"]
    elif kind == "ScrapingDetail":
        start_datetime = datetime.combine(current_date, time(0, 10))
        role_arn = os.environ["ARN_IAM_ROLE_INVOKE_SCRAPING_DETAIL"]
    else:
        raise Exception(f"想定外のkindが渡されました。{kind}")

    # dynamoDBデシリアライザー
    td = TypeDeserializer()

    # 1分ずつずらしながらスケジュール登録
    for i, task in enumerate(tasks):
        # スケジュール実行日時
        jst = start_datetime + timedelta(minutes=i)

        # イベントパラメータを扱いやすいjsonに変換
        params = {}
        for key, value in task.params.items():
            v = td.deserialize(value)
            # 数値の場合はDecimal型になるので、intかfloatに変換
            if isinstance(v, Decimal):
                if int(v) == v:
                    v = int(v)
                else:
                    v = float(v)
            params[key] = v

        # スケジュールの作成
        scheduler.create_schedule(
            ActionAfterCompletion="DELETE",
            ClientToken="string",
            Name=f"{kind}_{task.params_id}",
            GroupName=os.environ["NAME_SCHEDULE_GROUP"],
            ScheduleExpression=f"cron({jst.minute} {jst.hour} {jst.day} {jst.month} ? {jst.year})",
            ScheduleExpressionTimezone="Asia/Tokyo",
            FlexibleTimeWindow={"Mode": "OFF"},
            State="ENABLED",
            Target={
                "Arn": task.exec_arn,
                "Input": json.dumps(params),
                "RoleArn": role_arn,
            },
        )


def delete_tasks_to_tmp(kind: str, tasks: list[TaskTmp]) -> None:
    """
    一時テーブルからタスクを削除

    Parameters
    ----------
    kind: str
        タスクの種類
    tasks: list[TaskTmp]
        タスクリスト
    """
    dynamodb = boto3.client("dynamodb")

    # 削除データの作成
    delete_requests = [
        {
            "DeleteRequest": {
                "Key": {"kind": {"S": kind}, "params_id": {"S": t.params_id}}
            }
        }
        for t in tasks
    ]

    # 削除リクエストを分割してバッチ処理
    # batch_write_itemは一度に25件までしか削除できないため
    for i in range(0, len(delete_requests), 25):
        batch = delete_requests[i : i + 25]
        dynamodb.batch_write_item(
            RequestItems={os.environ["NAME_DYNAMODB_TABLE_TASKS_TMP"]: batch}
        )
