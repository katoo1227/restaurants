import json
import boto3
import requests
from http import HTTPStatus
from pydantic import BaseModel


class Query(BaseModel):
    """
    クエリ
    """

    sql: str
    params: list


class DbClient:

    # SSMクライアント
    _ssm = boto3.client("ssm")

    def __init__(self, env: str, api_key_path: str, api_url: str):

        # API URL
        self._api_url = api_url

        # ヘッダー
        api_key_res = self._ssm.get_parameter(Name=api_key_path, WithDecryption=True)
        self._headers = {
            "Content-Type": "application/json",
            "X-Api-Key": api_key_res["Parameter"]["Value"],
            "Env": env,
        }

        # ペイロードの初期化
        self._payload_init = {"sql": "", "params": [], "is_select": 0}

    def select(self, sql: str, params: list) -> dict:
        """
        SELECT句を発行

        Parameters
        ----------
        sql: str
            SQL
        params: list
            パラメータ

        Returns
        -------
        dict
        """
        # リクエストボディ
        payload = self._payload_init
        payload["sql"] = sql
        payload["params"] = params
        payload["is_select"] = 1

        # POSTリクエストを送信
        res = requests.post(
            self._api_url,
            headers=self._headers,
            json=payload,
        )

        # レスポンスのチェック
        self.__check_response(res)

        return res.json()

    def handle(self, sql: str, params: list) -> dict:
        """
        SELECT句以外を発行

        Parameters
        ----------
        sql: str
            SQL
        params: list
            パラメータ

        Returns
        -------
        dict
        """
        # リクエストボディ
        payload = self._payload_init
        payload["sql"] = sql
        payload["params"] = params
        payload["is_select"] = 0

        # POSTリクエストを送信
        res = requests.post(
            self._api_url,
            headers=self._headers,
            json=payload,
        )

        # レスポンスのチェック
        self.__check_response(res)

        return res.json()

    def __check_response(self, r: requests.models.Response) -> None:
        """
        レスポンスのチェック

        Parameters
        ----------
        r: requests.models.Response
            レスポンス

        Raises
        ------
        Exception
        """
        # ステータスコードが正常なら終了
        if r.status_code == HTTPStatus.OK:
            return

        # 必要なキーがない場合はエラー
        res_json = r.json()
        for key in ["result", "data"]:
            if key not in res_json:
                raise Exception(f"返り値に{key}がありません。{json.dumps(r)}")

        # ステータスコードが失敗
        raise Exception(f"DB操作に失敗しました。{json.dumps(r)}")