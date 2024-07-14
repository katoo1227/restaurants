#!/bin/bash

# Lambda関数へのテストイベントのセット
# sam deployが完了していることが前提
#
# Usage:
# bash set_lambda_events.sh
#
# Parameters:
#   <env> デプロイ先環境。dev or prodのみ受付
#
# Examples:
#   bash deploy.sh dev


# Lambda関数にテストイベントを設定
#
# Arguments:
#   $1 - template.yml内のリソース名（Lambda関数名でないことに注意）
#   $2 - スタック出力キー
set_test_events() {
    echo -e "\e[32mSet Test Events - $1 - Start\e[0m"

    # ARN
    arn=$(echo $outputs | jq -r --arg key "$2" '.[] | select(.OutputKey == $key) | .OutputValue')

    # CodeUri
    yq_path=".Resources.$1.Properties.CodeUri"
    code_uri=$(yq $yq_path template.yml)

    # テストイベントファイル一覧
    test_events_path="${code_uri}test_events"
    test_event_files=$(find "$test_events_path" -type f -name "*.json")

    # テストイベントの設定
    new_evts=()
    while IFS= read -r path; do
        test_event_name=$(basename "$path" .json)
        new_evts+=("$test_event_name")
        sam remote test-event put "$arn" --force --name "$test_event_name" --file "$path"
    done < <(find "$test_events_path" -type f -name "*.json")

    # 更新されていないテストイベントを削除
    old_evts=($(sam remote test-event list $arn))
    for old in "${old_evts[@]}"; do
        skip=false
        for new in "${new_evts[@]}"; do
            if [[ "$new" == "$old" ]]; then
                skip=true
                break
            fi
        done
        if [ "$skip" = false ]; then
            sam remote test-event delete "$arn" --name "$old"
        fi
    done

    echo -e "\e[32mSet Test Events - $1 - Complete\e[0m"
}

# 引数が1つでないと終了
if [ $# -ne 1 ]; then
    echo "ex)bash deploy.sh dev"
    exit 1
fi

# 引数が "dev" または "prod" でない場合の処理
env=$1
if [ "$env" != "dev" ] && [ "$env" != "prod" ]; then
    echo "ex)bash deploy.sh dev"
    exit 1
fi

# スタックの出力を取得
env_for_stack=$(echo "${env^}")
stack_name="RestaurantsDeploy$env_for_stack"
outputs=$(sam list stack-outputs --stack-name $stack_name --output json)

# LambdaLineNotifyのテストイベントの設定
set_test_events "LambdaLineNotify" "ArnLambdaLineNotify"

# LambdaErrorCommonのテストイベントの設定
set_test_events "LambdaErrorCommon" "ArnLambdaErrorCommon"

# RegisterSchedulesのテストイベントの設定
set_test_events "LambdaRegisterSchedules" "ArnLambdaRegisterSchedules"

# LambdaRegisterSmallAreasのテストイベントの設定
set_test_events "LambdaRegisterSmallAreas" "ArnLambdaRegisterSmallAreas"

# LambdaRegisterAbstractPagesのテストイベントの設定
set_test_events "LambdaRegisterAbstractPages" "ArnLambdaRegisterAbstractPages"

# ScrapingAbstractのテストイベントの設定
set_test_events "LambdaScrapingAbstract" "ArnScrapingAbstract"

# ScrapingDetailのテストイベントの設定
set_test_events "LambdaScrapingDetail" "ArnScrapingDetail"