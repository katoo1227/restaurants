# 全国レストラン

## デプロイ
```sh
# 開発環境
bash deploy.sh dev

# 本番環境
bash deploy.sh prod
```

## Lambda関数へテストイベントの登録
```sh
# 開発環境
bash set_lambda_test_events.sh dev
# 本番環境
bash set_lambda_test_events.sh prod
```