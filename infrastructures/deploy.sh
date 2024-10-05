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
    base_path="./template_base.yml"

    # 出力先
    yml_path="./template.yml"

    # 「$file: ~~」をテンプレートに展開
    yq '(.. | select(has("$file"))) |= load(.$file) | .Resources = (.Resources[] as $item ireduce ({}; . * $item))' "$base_path" >"$yml_path"

    echo "$yml_path"
}

# Lambdaレイヤーのデプロイ出力を取得
get_lambda_layers_deployment_outputs() {
    env=$1

    stack_name="RestaurantsLambdaLayers${env^}"
    res=$(sam list stack-outputs --stack-name $stack_name --output json)
    declare -A outputs
    while IFS="=" read -r key value; do
        outputs["$key"]="$value"
    done < <(echo "$res" | jq -r '.[] | "\(.OutputKey)=\(.OutputValue)"')

    echo "$(declare -p outputs)"
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

# テンプレート内の置換
replace_template() {
    # Cloudfront画像リファラー制限文字列
    replace_images_referers "$1" "$2"

    # フロントエンドのドメイン
    replace_frontend_domains "$1" "$2"

}

# Cloudfront画像リファラー制限文字列の置き換え
replace_images_referers() {
    # 置き換え文字列
    str=\''https://${Route53Frontend}/'\'

    # 開発環境の場合はローカル環境のリファラーも追加
    if [ $1 == "dev" ]; then
        IFS=',' read -r -a urls <<< "$LOCAL_FRONTEND_REFERERS"
        for url in "${urls[@]}"; do
            str+=", '$url/'"
        done
    fi

    # テンプレートファイルに対して置換処理
    sed -i "s|{{replace_images_access_referers}}|$str|" "$2"
}

# フロントエンドのドメイン
replace_frontend_domains() {
    # 置き換え文字列
    str='https://${Route53Frontend}'

    # 開発環境の場合はローカル環境のリファラーも追加
    if [ $1 == "dev" ]; then
        str+=",$LOCAL_FRONTEND_REFERERS"
    fi

    # テンプレートファイルに対して置換処理
    sed -i "s|{{replace_frontend_domains}}|$str|" "$2"
}

# ビルド・デプロイ
build_deploy() {
    env=$1

    # outputsの展開
    eval "$2"

    sam build --template-file "$yml_path"
    sam deploy \
        --config-env=$env \
        --parameter-overrides EnvironmentType=$env \
        TaskNameRegisterTasksPages="RegisterTasksPages${env^}" \
        TaskNameScrapingAbstract="ScrapingAbstract${env^}" \
        TaskNameScrapingDetail="ScrapingDetail${env^}" \
        ArnAcmSslCertficateTokyo=$(get_certificated_arn "ap-northeast-1") \
        ArnAcmSslCertficateUsEast=$(get_certificated_arn "us-east-1") \
        ParameterStoreNameLineNotifyRestaurants="${PARAMETER_STORE_NAME_LINE_NOTIFY_RESTAURANTS}" \
        ParameterStoreNameLineNotifyError="${PARAMETER_STORE_NAME_LINE_NOTIFY_ERROR}" \
        ParameterStoreNameLineNotifyWarning="${PARAMETER_STORE_NAME_LINE_NOTIFY_WARNING}" \
        ParameterStoreNameHotpepperApiKey="${PARAMETER_STORE_NAME_HOTPEPPER_API_KEY}" \
        ParameterStoreNameGcpApiKey="${PARAMETER_STORE_NAME_GCP_API_KEY}" \
        ParameterStoreNameSakuraDatabaseApiKey="${PARAMETER_STORE_NAME_SAKURA_DATABASE_API_KEY}" \
        SakuraDatabaseApiUrl="${SAKURA_HANDLE_DB_API_URL}" \
        Domain="${DOMAIN}" \
        FrontendBasicAuthorization=$(get_basic_authorization) \
        S3BucketPrefix="$S3_BUCKET_PREFIX" \
        LambdaLayerHotpepperApiClient=${outputs["ArnHotpepperApiClient"]} \
        LambdaLayerSqliteClient=${outputs["ArnSqliteClient"]} \
        LambdaLayerDbClient=${outputs["ArnDbClient"]} \
        LambdaLayerDynamodbTypes=${outputs["ArnDynamodbTypes"]}
}

# デプロイ処理
deploy() {

    env=$1

    # SAMテンプレートの作成
    yml_path=$(create_template)

    # Lambdaレイヤーのデプロイ出力を定数にセット
    outputs=$(get_lambda_layers_deployment_outputs $env)

    # テンプレート内の置換
    replace_template "$env" "$yml_path"

    # SAM ビルド・デプロイ
    build_deploy "$env" "$outputs"
}

# 環境設定ファイルの読み込み
env=$(check_env $1)

# 環境設定ファイルの読み込み
source "./deploy_${env}.env"

# デプロイ
deploy $env
