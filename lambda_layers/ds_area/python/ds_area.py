import json
import re
from dataclasses import dataclass, asdict


@dataclass
class DSArea:
    """
    エリア構造体
    """

    large_service_area_code: str
    large_service_area_name: str
    service_area_code: str
    service_area_name: str
    large_area_code: str
    large_area_name: str
    middle_area_code: str
    middle_area_name: str
    small_area_code: str
    small_area_name: str

    def __post_init__(self):
        """
        値のチェック

        Raises
        ------
        Exception
        """
        patterns = {
            "large_service_area_code": r"SS[0-9]{2}",
            "service_area_code": r"SA[0-9]{2}",
            "large_area_code": r"Z[0-9]{3}",
            "middle_area_code": r"Y[0-9]{3}",
            "small_area_code": r"X[A-Z0-9]{3}",
        }
        for k, r in patterns.items():
            v = getattr(self, k)
            if not re.match(r, v):
                raise Exception(f"{k}の値が不正です。{json.dumps(asdict(self))}")
