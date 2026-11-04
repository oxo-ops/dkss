# WORLEX限定復元資材

## 現在の状態

本番への取込はまだ実行していません。このZIPには実バックアップ、実データ行、パスワード、接続URLを含めていません。

- ローカル単体・安全確認9件: 合格。
- 合成SQLiteで実際のパスワード認証と主要10画面: 合格。PostgreSQL試験の代わりにはしません。
- 実バックアップのローカル型変換確認: 4,100行/37非空テーブル、ユーザー15人、車両565件（有効289/削除276）、運行2,571件、空車台番号11件のNULL化、旧車両ラベル241件の保持を確認。
- PostgreSQL統合試験10シナリオ: 未実行。ローカル環境では既知のPostgreSQLソケット制限があります。GitHub書込権限が403のため、この資材をこちらから公開していません。
- 同梱policy.jsonは未検証版です。本番CLIはPOSTGRES_CI_SEAL_REQUIREDで停止し、接続しません。全PostgreSQL試験成功後にだけsealed-policy.jsonが出力されます。

## 本人操作が必要な最短手順: 専用ブランチへコードをpush

既存DKSSリポジトリの作業ツリーがクリーンであることを確認してください。mainは変更しません。既存の作業がある場合は別の作業用cloneで実行してください。

1. 次の固定コミットから専用ブランチを作ります。

   git switch -c verify/worlex-restore-20261104 008ed6e41352a852828f10193972e6e415f9a20e

2. このZIPをリポジトリ直下へ展開します。新規に置かれるものは、worlex-scoped-restore-20261104/ と .github/workflows/worlex-restore-postgres.yml のみです。元のアプリファイルは書き換えません。

3. 次の対象だけをcommit/pushします。実バックアップ、.env、接続文字列を追加しないでください。

   git add worlex-scoped-restore-20261104 .github/workflows/worlex-restore-postgres.yml
   git commit -m "Add synthetic WORLEX restore acceptance"
   git push -u origin verify/worlex-restore-20261104

専用ブランチへのpushで「Synthetic WORLEX Scoped Restore」が起動します。default branchへの登録やmainへのmergeは不要です。Actionsの実行URLを共有してください。

この試験は、ジョブが新規作成したPostgreSQL18コンテナ以外へ接続できません。実バックアップは読みません。固定アプリ948ファイルのSHA256を確認し、毎回新しい空DBへ合成データのみを作ります。全19テストが実行され、スキップ0・失敗0の場合だけ、本番用の検証情報sealed-policy.jsonを成果物へ出します。失敗時にcandidate-policy.jsonを本番へ流用してはいけません。

## PostgreSQLで必須の検証

1. 15ユーザー、565車両、2,571運行、合成通知・PDF・営業所の取込と全値照合、他社/ITC保持、生成IDの次回採番。
2. INSERT・互換列追加・分析トリガー・シーケンスRESTART後の強制失敗ですべてロールバック。
3. 再実行拒否。
4. 大小文字違いのworlexが既存なら拒否。
5. 数値ID衝突なら拒否。
6. 他のDBクライアント接続が残っていれば拒否。
7. 必須インデックスなどスキーマ差分があれば拒否。
8. 未検証スキーマ情報なら拒否。
9. 読取専用のコミット結果照合と改変された復元行の拒否。
10. 合成パスワードでログイン、主要10画面、他社車両へのアクセス拒否。

## PostgreSQL合格後の本番実行

ユーザー承認済みのWORLEX限定復元だけを行います。下記は運用担当/助手用で、CI成功前に実行しないでください。

1. Actionsの成功コミットとtested-code-sha256.jsonを確認し、同じランナーを使う。sealed-policy.jsonをこのディレクトリのpolicy.jsonとして配置する。未検証版からの手動の検証済みフラグ追加は禁止。
2. アプリ、Gunicorn、ジョブ、アラート/取込ワーカー、cronなど新DBのすべての書込み元を停止し、DB接続プールを切断する。新旧のバックアップや旧DBには操作しない。停止の確認なしに--writers-stoppedを付けない。
3. 正規の安全な資格情報入力を使い、WORLEX_NEW_DATABASE_URLをプロセス環境だけに設定する。チャット、シェル履歴、ログ、GitHub、ファイルに秘密を貼らない。DATABASE_URLは使用しません。接続先は以下に固定されています。

   host: dpg-dbkk5juc6qcc73am01r0-a.oregon-postgres.render.com
   database: dkss_db_new_20261103
   user: dkss_db_new_20261103_user
   PostgreSQL18 / TLS verify-full

4. requirements-runner.txtの依存関係と公式PostgreSQL18 pg_restoreを用意する。アプリのinit-dbは呼ばない。
5. 読取専用のinspectを一度行う。パスは実際のローカル位置に置き換える。

   python worlex_restore.py inspect --archive "BACKUP.tar.gz" --pg-restore "PATH/pg_restore" --plan "worlex-plan.json" --report "preflight.json"

6. 事前検証結果、停止状態、復元範囲が承認内容と一致することを確認したうえで、一度だけexecuteする。

   python worlex_restore.py execute --archive "BACKUP.tar.gz" --pg-restore "PATH/pg_restore" --plan "worlex-plan.json" --report "restore-result.json" --writers-stopped

7. アプリを再開する前に、同じ計画に対する読取専用verifyを行う。

   python worlex_restore.py verify --archive "BACKUP.tar.gz" --pg-restore "PATH/pg_restore" --plan "worlex-plan.json" --report "verify-result.json"

8. コミット/照合成功後にアプリを再開し、本人の資格情報を安全な入力経路で使って実WORLEXログインと車両・運行・主要業務画面を確認する。MFAはOffのまま。実ログインは利用履歴を更新するため、厳密な取込直後の全値比較より後に行う。

途中で停止/失敗/切断があったら、自動再実行しません。計画の.execution.jsonは一度の試行を記録します。コミット結果が不明な場合はverifyで読み取り照合し、不一致の理由を調べます。別名の計画や削除で再実行防止を回避してはいけません。

## 保持と本人確認制限

- アーカイブ全体をDBへ流し込まず、COPYデータのみをパラメータとして読み、WORLEXだけをINSERTする。
- ITCのusername=itc / role=itc、他社、全体管理行を保持する。既存WORLEX/大小文字違い、IDや一意キーの衝突は上書きせず停止する。
- 元の数値車両ID・関連ID・実車台番号・有効/削除状態を保持する。空文字車台番号11件だけNULL化する。旧ラベルはnullable vehicle.vehicle_idに保持する。
- 世代UUIDは復元対象ユーザー/マスタにだけ発行し、計画に固定する。過去通知、個人下書き、過去の作業者/所有者はユーザー名から新UUIDへ結び付けない。
- 過去通知・個人用下書き・リマインダー設定の一部は本人確認待ちとして利用制限を維持する。未確認事項として分けて報告する。
- 原本PDF/CSVを再取込・再キュー投入せず、元の状態とバイト列を保持する。
- 共有シーケンスは巻き戻さず、トランザクション内のALTER SEQUENCE RESTARTのみで調整する。setval/nextvalを復元処理から呼ばない。
- 新しいバックアップの取得やバックアップの経過日数は、この復旧の追加条件ではない。
