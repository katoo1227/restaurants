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

# SAMテンプレートの作成
create_template() {
    # ベースパス
    base_path="$(pwd)/template_base.yml"

    # 出力先
    yml_path="$(pwd)/template.yml"

    # 「$file: ~~」をテンプレートに展開
    yq '(.. | select(has("$file"))) |= load(.$file) | .Resources = (.Resources[] as $item ireduce ({}; . * $item))' "$base_path" > "$yml_path"

    echo "$yml_path"
}

# ACMのSSL証明書ARNを取得
get_certificated_arn() {
    arn=$(aws acm list-certificates --region "$1" | jq -r --arg domain "*.$DOMAIN" '.CertificateSummaryList[] | select(.DomainName == $domain) | .CertificateArn')
    if [ -z "$arn" ]; then
        echo ACM SSL Certificate was not found.
        exit 1
    fi
    echo "$arn"
}

# Basic認証情報を取得
get_basic_authorization() {
    aws ssm get-parameter \
        --name "${PARAMETER_STORE_NAME_BASIC_AUTH_BASE64}" \
        --with-decryption \
        --query "Parameter.Value" \
        --output text
}

# ビルド・デプロイ
build_deploy() {
    env=$1
    sam build --template-file "$yml_path"
    sam deploy \
        --config-env=$env \
        --parameter-overrides EnvironmentType=$env \
            TaskNameRegisterPages="RegisterPages${env^}" \
            TaskNameScrapingAbstract="ScrapingAbstract${env^}" \
            TaskNameScrapingDetail="ScrapingDetail${env^}" \
            ArnAcmSslCertficateTokyo=$(get_certificated_arn "ap-northeast-1") \
            ArnAcmSslCertficateUsEast=$(get_certificated_arn "us-east-1") \
            ParameterStoreNameLineNotifyRestaurants="${PARAMETER_STORE_NAME_LINE_NOTIFY_RESTAURANTS}" \
            ParameterStoreNameLineNotifyError="${PARAMETER_STORE_NAME_LINE_NOTIFY_ERROR}" \
            ParameterStoreNameLineNotifyWarning="${PARAMETER_STORE_NAME_LINE_NOTIFY_WARNING}" \
            ParameterStoreNameHotpepperApiKey="${PARAMETER_STORE_NAME_HOTPEPPER_API_KEY}" \
            ParameterStoreNameGcpApiKey="${PARAMETER_STORE_NAME_GCP_API_KEY}" \
            Domain="${DOMAIN}" \
            FrontendBasicAuthorization=$(get_basic_authorization) \
            S3BucketPrefix="$S3_BUCKET_PREFIX"
}

# S3画像格納バケットに初期ディレクトリを配置
init_s3_images() {
    env=$1

    stack_name="RestaurantsDeploy${env^}"
    outputs=$(sam list stack-outputs --stack-name $stack_name --output json)
    bucket_name=$(echo $outputs | jq -r --arg key "NameImagesBucket" '.[] | select(.OutputKey == $key) | .OutputValue')
    aws s3api put-object --bucket "$bucket_name" --key "thumbnails/"
    aws s3api put-object --bucket "$bucket_name" --key "images/"
}

# デプロイ処理
deploy() {

    env=$1

    # SAMテンプレートの作成
    yml_path=$(create_template)

    # SAM ビルド・デプロイ
    build_deploy $env

    # S3画像格納バケットに初期フォルダの設置
    init_s3_images $env
}

# 環境設定ファイルの読み込み
env=$(check_env $1)

# 環境設定ファイルの読み込み
source "$(pwd)/deploy_${env}.env"

# デプロイ
deploy $env