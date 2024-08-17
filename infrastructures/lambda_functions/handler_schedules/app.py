import json
import os
import boto3
from dataclasses import dataclass, asdict


@dataclass
class RegisterParams:
    """
    登録パラメータ構造体
    """

    task: str
    name: str
    target_arn: str
    invoke_role_arn: str


@dataclass
class DeleteParams:
    """
    削除パラメータ構造体
    """

    task: str
    name: str


def lambda_handler(event, context):

    try:
        # イベントパラメータをタスクパラメータに変換
        task = conv_task_params(event)

        if isinstance(task, RegisterParams):
            # 登録
            register_schedule(task)
        elif isinstance(task, DeleteParams):
            # 削除
            delete_schedule(task)
        else:
            # 念のため例外をスロー
            raise Exception(f"予期しないパラメータ。{type(task)}")

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


def conv_task_params(event: dict) -> RegisterParams | DeleteParams:
    """
    イベントパラメータをタスクパラメータに変換

    Parameters
    ----------
    event: dict
        イベントパラメータ

    Returns
    -------
    RegisterParams | DeleteParam
    """
    task = None

    # 登録
    try:
        task = RegisterParams(**event)
        if task.task != "register":
            task = None
    except TypeError:
        pass

    # 削除
    try:
        task = DeleteParams(**event)
        if task.task != "delete":
            task = None
    except TypeError:
        pass

    # どちらでもなければエラー
    if task is None:
        raise Exception(f"タスクの判定に失敗。{json.dumps(event)}")

    return task


def register_schedule(task: RegisterParams) -> None:
    """
    スケジュールの登録

    Parameters
    ----------
    task: RegisterParams
    """
    scheduler = boto3.client("scheduler")

    # スケジュールを検索し、なければ登録
    try:
        scheduler.get_schedule(
            GroupName=os.environ["NAME_SCHEDULE_GROUP"],
            Name=task.name,
        )
    except scheduler.exceptions.ResourceNotFoundException:
        # スケジュールがない場合はResourceNotFoundExceptionとなる
        # ここでスケジュール登録を行う
        scheduler.create_schedule(
            ActionAfterCompletion="DELETE",
            ClientToken="string",
            Name=task.name,
            GroupName=os.environ["NAME_SCHEDULE_GROUP"],
            ScheduleExpression="cron(* * ? * * *)",
            ScheduleExpressionTimezone="Asia/Tokyo",
            FlexibleTimeWindow={"Mode": "OFF"},
            State="ENABLED",
            Target={
                "Arn": task.target_arn,
                "RoleArn": task.invoke_role_arn,
            },
        )


def delete_schedule(task: DeleteParams) -> None:
    """
    スケジュールの削除

    Parameters
    ----------
    task: DeleteParams
    """
    scheduler = boto3.client("scheduler")
    try:
        scheduler.delete_schedule(
            Name=task.name,
            GroupName=os.environ["NAME_SCHEDULE_GROUP"],
        )
    except scheduler.exceptions.ResourceNotFoundException:
        # TODO: ErrorCommonを通すことで詳細情報を通知メッセージを入れられる
        msg = f"スケジュールが削除済みです。{json.dumps(asdict(task))}"
        payload = {"type": 3, "msg": msg}
        boto3.client("lambda").invoke(
            FunctionName=os.environ["ARN_LAMBDA_LINE_NOTIFY"],
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode("utf-8"),
        )

