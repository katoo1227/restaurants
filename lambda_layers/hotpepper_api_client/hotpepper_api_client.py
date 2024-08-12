import boto3
import requests
import urllib.parse


class HotpepperApiClient:
    def __init__(self, ssm_path: str):
        self._api_url_base = "https://webservice.recruit.co.jp/hotpepper"
        self._api_key = self._get_api_key(ssm_path)

    def _get_api_key(self, ssm_path) -> str:
        """
        APIキーをSystems Managerから取得

        Returns
        -------
        str
        """
        res = boto3.client("ssm").get_parameter(Name=ssm_path, WithDecryption=True)
        return res["Parameter"]["Value"]

    def get_genres(self) -> list:
        """
        ジャンル一覧を取得

        Returns
        -------
        list
        """
        # API URL
        api_url = f"{self._api_url_base}/genre/v1/"

        api_params = urllib.parse.urlencode({"key": self._api_key, "format": "json"})
        api_url = f"{api_url}?{api_params}"

        response = requests.get(api_url)
        return response.json()
