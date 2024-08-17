import boto3
import requests
import urllib.parse


class HotpepperApiClient:
    def __init__(self, ssm_path: str):
        self._api_url_base = "https://webservice.recruit.co.jp/hotpepper"
        self._api_key = self._get_api_key(ssm_path)

    def get_genres(self) -> dict:
        """
        ジャンル一覧を取得

        Returns
        -------
        dict
        """
        url = f"{self._api_url_base}/genre/v1/"
        return self._exec_api(url)

    def get_large_service_areas(self) -> dict:
        """
        大サービスエリア一覧を取得

        Returns
        -------
        dict
        """
        url = f"{self._api_url_base}/large_service_area/v1/"
        return self._exec_api(url)

    def get_service_areas(self) -> dict:
        """
        サービスエリア一覧を取得

        Returns
        -------
        dict
        """
        url = f"{self._api_url_base}/service_area/v1/"
        return self._exec_api(url)

    def get_large_areas(self) -> dict:
        """
        大エリア一覧を取得

        Returns
        -------
        dict
        """
        url = f"{self._api_url_base}/large_area/v1/"
        return self._exec_api(url)

    def get_middle_areas(self) -> dict:
        """
        中エリア一覧を取得

        Returns
        -------
        dict
        """
        url = f"{self._api_url_base}/middle_area/v1/"
        return self._exec_api(url)

    def get_small_areas(self, start: int, count: int) -> dict:
        """
        中エリア一覧を取得

        Parameters
        ----------
        start: int
            開始位置

        count: int
            取得件数

        Returns
        -------
        dict
        """
        url = f"{self._api_url_base}/small_area/v1/"
        params = {"start": start, "count": count}
        return self._exec_api(url, params)

    def _get_api_key(self, ssm_path) -> str:
        """
        APIキーをSystems Managerから取得

        Returns
        -------
        str
        """
        res = boto3.client("ssm").get_parameter(Name=ssm_path, WithDecryption=True)
        return res["Parameter"]["Value"]

    def _exec_api(self, u: str, p: dict = {}) -> dict:
        """
        APIを実行

        Parameters
        ----------
        u: str
            URL
        p: dict
            パラメータ

        Returns
        -------
        dict
        """
        params = p | {"key": self._api_key, "format": "json"}
        api_params = urllib.parse.urlencode(params)
        api_url = f"{u}?{api_params}"

        response = requests.get(api_url)
        return response.json()