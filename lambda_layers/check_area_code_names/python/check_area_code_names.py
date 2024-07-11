import json
import re

def check_area_code_names(e: dict) -> None:
    """
    各エリアコードとエリア名のチェック

    Parameters
    ----------
    e: dict
        イベントパラメータ

    Raises:
        Exception
    """
    # チェック対象のキーと正規表現パターン
    key_patterns = {
        "large_service_area_code": r"SS[0-9]{2}",
        "large_service_area_name": r".+",
        "service_area_code": r"SA[0-9]{2}",
        "service_area_name": r".+",
        "large_area_code": r"Z[0-9]{3}",
        "large_area_name": r".+",
        "middle_area_code": r"Y[0-9]{3}",
        "middle_area_name": r".+",
        "small_area_code": r"X[A-Z0-9]{3}",
        "small_area_name": r".+"
    }
    for key, pattern in key_patterns.items():
        # keyがない場合
        if key not in e:
            raise Exception(f"{key}がありません。{json.dumps(e)}")

        # 正規表現パターンにマッチしない場合
        if not re.match(pattern, e[key]):
            raise Exception(f"{key}の値が不正です。{json.dumps(e)}")