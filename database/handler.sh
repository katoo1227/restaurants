#!/bin/bash

DB_DIR="$(pwd)/database"
DB_NAME="database.sqlite3"
DB_PATH="${DB_DIR}/${DB_NAME}"

# パラメータのチェック
check_params() {
    # パラメータなければ終了
    if [ "$#" == 0 ]; then
        echo "ex)bash database.sh connect"
        exit 1
    fi
}

# タスクの取得
check_task() {
    allowed_tasks=("connect" "init" "download" "upload")
    if [ "$1" != "connect" ] \
        && [ "$1" != "init" ] \
        && [ "$1" != "download" ] \
        && [ "$1" != "upload" ]; then
        echo "ex)bash database.sh connect"
        exit 1
    fi
}

# 環境の取得
check_env() {
    if [ "$1" != "dev" ] && [ "$1" != "prod" ]; then
        echo "ex)bash database.sh download dev"
        exit 1
    fi
}

# DBファイルパスのチェック
check_db_path() {
    if [ ! -e "$DB_PATH" ]; then
        echo "${DB_PATH}がありません"
        exit 1
    fi
}

# DB接続
connect_db() {
    sqlite3 "$DB_PATH" \
        -cmd ".headers on" \
        -cmd ".mode column" \
        -cmd "PRAGMA foreign_keys=true;"
}

# DBの初期化
init_db() {
    sqlite3 "$DB_PATH" < "${DB_DIR}/database.sql"
}

# S3バケット名の取得
get_s3_bucket_name() {
    env="$1"
    outputs=$(sam list stack-outputs --stack-name "RestaurantsInfrastructures${env^}" --output json)
    echo $outputs | jq -r --arg key "NameDatabaseBucket" '.[] | select(.OutputKey == $key) | .OutputValue'
}

# DBのダウンロード
download_db() {
    bucket_name=$(get_s3_bucket_name "$1")
    aws s3 cp "s3://${bucket_name}/${DB_NAME}" "${DB_PATH}"
}

# DBのアップロード
upload_db() {
    bucket_name=$(get_s3_bucket_name "$1")
    aws s3 cp "${DB_PATH}" "s3://${bucket_name}/${DB_NAME}"
}

# パラメータのチェック
check_params $@

# タスクのチェック
check_task "$1"
task="$1"

# 環境のチェック
if [ "$task" == "download" ] || [ "$task" == "upload" ]; then
    check_env "$2"
    env="$2"
fi

# DBファイルパス
check_db_path

case "$task" in
    connect)
        connect_db
        ;;
    init)
        init_db
        ;;
    download)
        download_db "$env"
        ;;
    upload)
        upload_db "$env"
        ;;
esac