from boto3.dynamodb.types import TypeSerializer, TypeDeserializer
from decimal import Decimal


def serialize_dict(item: dict) -> dict:
    """
    辞書型のシリアライズ
        例）
        {
            "aaa": "qwe",
            "bbb": "asd"
        }
        ↓
        {
            "aaa": {"S": "qwe"},
            "bbb": {"S": "asd"}
        }

    Parameters
    ----------
    items: dict
        シリアライズしたいdict

    Returns
    -------
    dict
    """
    return {k: serialize(v) for k, v in item.items()}


def serialize(item: int | float | dict) -> dict:
    """
    シリアライズ（調整を行わないので実質ラッパー関数）

    Parameters
    ----------
    item: int|float|dict
        DynamoDB JSONに変換する値

    Returns
    -------
    dict
        DynamoDB JSON
    """
    # floatの場合のみシリアライズを使わずに手動で設定
    if type(item) == float:
        return {"N": str(item)}
    else:
        return TypeSerializer().serialize(item)


def deserialize_dict(item: dict) -> dict:
    """
    辞書型のデシリアライズ
        例）
        {
            "aaa": {"S": "qwe"},
            "bbb": {"S": "asd"}
        }
        ↓
        {
            "aaa": "qwe",
            "bbb": "asd"
        }

    Parameters
    ----------
    items: dict
        デシリアライズしたいdict

    Returns
    -------
    dict
    """
    return {k: deserialize(v) for k, v in item.items()}


def deserialize(item: dict) -> dict:
    """
    デシリアライズ

    Parameters
    ----------
    items: dict
        DynamoDB JSON

    Returns
    -------
    dict
        python用dict
    """
    # デシリアライズ
    v = TypeDeserializer().deserialize(item)

    return convert_decimal_to_int_or_float(v)


def convert_decimal_to_int_or_float(v):
    """
    再帰的にDecimal型をint or floatに変換

    Parameters
    ----------
    v: mixed
        値

    Returns
    -------
    mixed
    """
    # dictはキーごとのループで自身を呼ぶ
    if isinstance(v, dict):
        return {key: convert_decimal_to_int_or_float(value) for key, value in v.items()}

    # listは値ごとのループで自信を呼ぶ
    elif isinstance(v, list):
        return [convert_decimal_to_int_or_float(item) for item in v]

    # Decimalはint or floatに変換
    elif isinstance(v, Decimal):
        if int(v) == v:
            return int(v)
        else:
            return float(v)

    # その他はそのまま返す
    else:
        return v
