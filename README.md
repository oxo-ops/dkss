# 輸送版DX 開発と運用の入口

Python 3.12と`requirements.txt`を使用します。新しいローカル環境での依存導入・起動・停止・代表試験、設定項目、CI障害の確認先は[開発と運用の手順](docs/runtime_operations.md)を参照してください。

- [アプリの構造と初期化](docs/application_architecture.md)
- [OCR受付・ワーカーの仕組み](docs/document_import_queue.md)
- [DBモデル定義](docs/database_schema.md)
- [Q09の確認結果と担当境界](docs/quality/Q09-runtime-acceptance-20261029.md)

`init-db`は新規の空DBを作る手順と、既存DBの移行手順を区別して使用します。既存DBに起動確認や回帰試験を向けないでください。Gunicorn起動フックには一部のDB初期化が含まれるため、Web起動自体を読み取り専用の診断として使用できません。
