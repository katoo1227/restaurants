#!/bin/bash

# AWSへのデプロイスクリプト
#
# Usage:
#   bash deploy.sh <env>
#
# Parameters:
#   <env> デプロイ先環境。dev or prodのみ受付
#
# Examples:
#   bash deploy.sh dev

# 環境設定ファイルの読み込み
check_env() {
    # 引数が1つでないと終了
    if [ $# -ne 1 ]; then
        echo "ex)bash deploy.sh dev"
        exit 1
    fi

    # "dev" または "prod" でない場合の処理
    if [ "$1" != "dev" ] && [ "$1" != "prod" ]; then
        echo "ex)bash deploy.sh dev"
        exit 1
    fi

    # 環境名を出力
    echo "$1"
}

# Lambdaレイヤーの作成
make_lambda_layers() {
    # 各レイヤーディレクトリのループ
    for dir in ./src/*; do
        python_dir="$dir/python"

        # pythonディレクトリの作り直し
        rm -rf "$python_dir"
        mkdir -p "$python_dir"

        # ソースコードの配置
        cp $dir/*.py $python_dir

        # requirements.txtがあればpip install
        if [ -f "${dir}/requirements.txt" ]; then
            pip install --upgrade -r "${dir}/requirements.txt" -t "$python_dir"
        fi
    done
}

# ビルド・デプロイ
build_deploy() {
    env=$1
    sam build \
        --template-file "./template.yml"

    sam deploy \
        --config-env "$env" \
        --parameter-overrides "EnvironmentType=$env"
}

# デプロイ処理
deploy() {

    env=$1

    # Lambdaレイヤーの作成
    make_lambda_layers

    # SAM ビルド・デプロイ
    build_deploy $env
}

# 環境設定ファイルの読み込み
env=$(check_env $1)

# 環境設定ファイルの読み込み
source "./deploy_${env}.env"

# デプロイ
deploy $env
