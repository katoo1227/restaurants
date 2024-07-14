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


def serialize(item: dict) -> dict:
    """
    シリアライズ（調整を行わないので実質ラッパー関数）

    Parameters
    ----------
    item: dict
        python用dict

    Returns
    -------
    dict
        DynamoDB JSON
    """
    return TypeSerializer().serialize(item)


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

    # 数値の場合はDecimal型になるので、intかfloatに変換
    if isinstance(v, Decimal):
        if int(v) == v:
            v = int(v)
        else:
            v = float(v)

    return v
