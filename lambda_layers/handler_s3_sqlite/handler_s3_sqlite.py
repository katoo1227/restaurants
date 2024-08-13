import boto3
import time
import sqlite3


class HandlerS3Sqlte:

    # S3クライアント
    _s3 = boto3.client("s3")

    def __init__(self, bucket_name: str, db_name: str, lock_name: str):
        self._bucket_name = bucket_name
        self._db_name = db_name
        self._lock_name = lock_name
        self._db_path = f"/tmp/{self._db_name}"

    def exec_query_with_lock(self, sql: str) -> None:
        """
        ロックを伴うクエリを発行
        select以外の全ての操作はこのメソッドにより行われる

        Parameters
        ----------
        sql: str
            発行するSQL文
        """
        try:
            # ロックを伴うダウンロード
            self._download_database_with_lock()

            # sqliteに接続
            conn = sqlite3.connect(self._get_db_path())
            cursor = conn.cursor()
            # 外部キー制約の有効化
            cursor.execute("PRAGMA foreign_keys = 1")
            cursor.execute(sql)
            conn.commit()

            # アップロード
            self._upload_database()
        except Exception as e:
            # ロックを解除して呼び出し元でエラーをスロー
            self._delete_lock()
            raise Exception(f"クエリ発行エラー。{e}\n{sql}")

    def exec_query(self, sql: str) -> list:
        """
        ロックを伴うクエリを発行
        selectの操作はこのメソッドにより行われる

        Parameters
        ----------
        sql: str
            発行するSQL文

        Returns
        -------
        list
        """
        try:
            # ダウンロード
            self._download_database()

            # sqliteに接続
            conn = sqlite3.connect(self._get_db_path())
            cursor = conn.cursor()
            res = cursor.execute(sql)
        except Exception as e:
            # 呼び出し元でエラーをスロー
            raise Exception(f"クエリ発行エラー。{e}\n{sql}")

        return res.fetchall()

    def _get_db_path(self) -> str:
        """
        DBダウンロードパスを取得

        Retruns
        -------
        str
        """
        return self._db_path

    def _download_database(self) -> None:
        """
        S3からDBファイルをダウンロード
        """
        self._s3.download_file(
            self._bucket_name, self._db_name, self._db_path
        )

    def _download_database_with_lock(self) -> None:
        """
        S3からロックを作成してDBファイルをダウンロード
        """
        # ロックが解除されるまで待機
        while self._is_lock():
            time.sleep(0.3)

        # ロックを作成
        self._create_lock()

        # ダウンロード
        self._download_database()

    def _upload_database(self) -> None:
        """
        S3へDBファイルをアップロード
        """
        # アップロード
        self._s3.upload_file(self._db_path, self._bucket_name, self._db_name)

        # ロックを解除
        self._delete_lock()

    def _is_lock(self) -> bool:
        """
        ロック中かどうかを判定

        Returns
        -------
        bool
            ロック中であればTrue
        """

        try:
            self._s3.head_object(Bucket=self._bucket_name, Key=self._lock_name)
            return True
        except self._s3.exceptions.ClientError:
            return False

    def _create_lock(self) -> None:
        """
        ロックファイルを作成
        """
        self._s3.put_object(Bucket=self._bucket_name, Key=self._lock_name)

    def _delete_lock(self) -> None:
        """
        ロックファイルを削除

        Parameters
        ----------
        bucket_name: str
            バケット名

        lock_file_name: str
            ロックファイル名
        """
        self._s3.delete_object(Bucket=self._bucket_name, Key=self._lock_name)
