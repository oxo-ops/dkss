# Q05 共通利用集計の初回作成競合（2026-10-29）

基準main: `25972cde39eba1454d9e3392d870af51872a07a7`。
PR #291 はマージ済み。運転分析fixtureを再実装しない。
PR #292 の未来起算日表示とは独立した修正である。
調査時の未マージPR #283/#290/#293/#295/#297 に audit.py の同等修正はなかった。
呼出元は調査のみとし、他担当が変更中の dashboard.py 等は編集しない。

## 再現と既存の意味

`audit.update_company_usage_summary` は会社別に一意の行を検索し、なければ単純INSERTしていた。
PostgreSQL 18.6、READ COMMITTED、実8接続で最初のSELECT完了をバリア同期すると
UNIQUE `company_usage_summary_company_code_key` 違反を再現できる。
実ダッシュボード8並列では7要求がHTTP500となった。
既存行も、42回から4回ログインを加えるべき試験で43回となり、更新が失われた。
変更前の新規20テストは16合格・4失敗（30.782秒）。

集計定義を維持する:

- `user_count`: 同一会社のUser全件。
- `vehicle_count`: 同一会社かつ deleted=False。削除済みを除く既存条件を維持。
- `checklist_result_count`: 同一会社のChecklistResultとVehicleChecklistResultの合計。
- `login_count`: 通常/MFAログイン成功時のみ加算。ダッシュボードでは加算しない。
- 日時2列は従来のサーバーnaive文字列形式を維持。時刻帯修正を混ぜない。

`dashboard.dashboard` は集計後にcommitする。
`auth.login` / `auth.mfa` はUserの認証更新・login_success監査・集計を同じcommitで確定する。
関数内で外側全体をcommit/rollbackすると、この原子性を壊すため採用しない。
既存のNULL/空会社早期returnも維持。

## 方式比較

| 方式 | 評価 |
| --- | --- |
| INSERT失敗後にsession.rollbackして再取得 | 外側のUser更新・監査を巻き戻すので不採用 |
| PostgreSQL UPSERT DO UPDATE | 同時加算は可能だが、既存ORM更新・集計・再読込までSQLへ組み直す必要があるため今回不採用 |
| ON CONFLICT DO NOTHING + 行ロック再取得 | 安全な候補。ただし方言別INSERTを追加する必要がある。競合後の再SELECTも必要 |
| SAVEPOINT内INSERT + 競合時に再取得 + 行ロック | 採用。既存document_sources.store_sourceと同じ局所回復方式を利用でき、既存集計式を維持できる |

`SELECT FOR UPDATE` と `populate_existing()` で既存行を会社単位でロックし、
待機前に読み込まれたORMの古い値も再読込する。
行がない場合のみPostgreSQLのSAVEPOINT内でINSERT/flushする。
競合時はSAVEPOINTだけが巻き戻り、勝者の行を再取得してロックし、集計と加算を継続する。
再取得できなければ元のIntegrityErrorを再送出する。無制限再試行や例外の黙殺はしない。
ロックは呼出元のcommit/rollbackまで有効。会社別に分離される。

SQLiteは既存の作成方式を維持する。SQLiteのlegacy transaction modeでは、
外側でまだDMLをしていない状態のSAVEPOINT releaseが外側rollbackの意味を変え得るため、
共通エンジン設定を変更せずPostgreSQLだけを対象にした。
外側に他の書込みがない場合の作成取消しもSQLite/PG双方で試験する。

公式根拠:
[SQLAlchemy SAVEPOINTと外側トランザクション](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#using-savepoint)、
[PostgreSQL READ COMMITTEDと競合後の可視性](https://www.postgresql.org/docs/current/transaction-iso.html#XACT-READ-COMMITTED)、
[SQLite legacy transaction modeのSAVEPOINT制約](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#legacy-transaction-mode-with-the-sqlite3-driver)。
採用設計はアプリ既定のREAD COMMITTEDを前提とする。分離レベルを変更する場合の
serialization/deadlock等のトランザクション再試行は呼出元の責任であり、ここで自動化しない。

## 試験

`test_usage_summary.py` はSQLiteとPGで同じ会社別集計・ログイン・監査・rollback/retryを実行する。
`test_usage_summary_postgres.py` は専用loopback DB `dkss_q05_ci` 内のランダムな私有schemaだけを作成/削除する。
本番URL、既存会社データ、既存schemaは使用しない。

- 初回作成、既存行の再集計、削除車両除外、複数会社。
- 作成/更新/監査/User変更の一括rollback、明示的な再試行、1トランザクション内の複数加算。
- 通常ログインとMFAで成功時だけ回数・監査が増える実HTTP試験。
- 初回8並列、会社別8並列、既存行の古いORM状態からの8並列更新、実HTTP8並列。
- 作成側が未commitでrollbackした場合に待機側が1回だけ作成・commitできること。
- 別種の作成エラーは伝播し、呼出元rollbackで監査も残らないこと。

初期の修正後21テストは全合格（44.040秒）。通常/MFAの実HTTP試験を追加後は
専用CIと関連回帰の結果をPRへ記録する。期待値緩和・失敗テスト削除はない。

## #292の受入順序

1. この独立修正PRのレビュー・main反映を待つ（自動マージしない）。
2. 反映後、#292を最新mainへ更新する。他担当との競合があれば統合せず報告する。
3. #292既存のPostgreSQL専用CI、全体回帰、実ブラウザPC/モバイル表示・ブラウザ時刻帯変更を再実行する。

今回この順序の2以降は前倒ししない。#292の既存失敗試験は変更しない。
本番操作・配備・main直接pushは行わない。
