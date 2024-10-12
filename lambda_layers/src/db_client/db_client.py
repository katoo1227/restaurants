import boto3
import os
import json
import time
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

    # キャッシュの有効期限（秒）
    _cache_duration = 86400

    # キャッシュファイル
    _api_key_cache_path = "/tmp/api_key.json"

    def __init__(self, env: str, api_key_path: str, api_url: str):

        # API URL
        self._api_url = api_url

        # ヘッダー
        self._headers = {
            "Content-Type": "application/json",
            "Env": env,
            "X-Api-Key": self.__getApiKey(api_key_path),
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

        # ステータスコードが失敗
        data = r.__dict__["_content"].decode("utf-8")
        raise Exception(f"DB操作に失敗しました。{data}")

    def __getApiKey(self, api_key_path: str) -> str:
        """
        APIキーを取得

        Parameters
        ----------
        api_key_path: str
            SSMパラメータキーパス

        Returns
        -------
        str
        """
        now = time.time()

        # ファイルがある場合
        if os.path.exists(self._api_key_cache_path):
            with open(self._api_key_cache_path, "r", encoding="utf-8") as file:
                data = json.load(file)
                # 有効なら返す
                if now <= int(data["expire"]):
                    return data["data"]

        # SSMパラメータストアからAPIキーを取得
        res = self._ssm.get_parameter(Name=api_key_path, WithDecryption=True)

        # キャッシュの生成
        data = {"data": res["Parameter"]["Value"], "expire": now + self._cache_duration}
        with open(self._api_key_cache_path, "w", encoding="utf-8") as json_file:
            json.dump(data, json_file)

        return res["Parameter"]["Value"]
