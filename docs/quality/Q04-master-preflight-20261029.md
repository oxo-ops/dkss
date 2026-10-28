# Q04 マスタ管理の導入前診断と受入条件

調査基点はmain `037ab51`（#273・#295・#297・#301反映済み）。本番へ接続せず、所有する使い捨てSQLiteとPostgreSQL 18.6だけで確認した。既存データ・索引の自動修復、削除、移行は行わない。

## 仕様と現行コードの区別

Downloadsの仕様書v0.25とv0.18を読み取り専用で照合した。正本未確定という既存の[仕様照合記録](../specification-review-20261028.md)を維持し、いずれかを独断で正本としない。SHA-256はv0.25が `d10255a317481e64654e37bd3e1f322a08cfad48b06ad6530a7b59955831b365`、v0.18が `213bd0c320bd97ca4f4fbddf85f36e7cb709a684784b7226faa8728584a2997b`。

v0.25の本文直下OOXMLブロックB0336では営業所異動後もVehicle.idで計画を保持し、当時の所属を履歴として残し、他社移管を自動で行わない。B0393〜B0394・B0414ではバックアップ取得と復旧可能性、DB・添付・設定・鍵、会社境界、RPO/RTOの受入を区別している。ブロック番号は同SHAの照合位置で、ページ番号ではない。5マスタの文字列照合・変更拒否・割当解除の詳細は `masters.py` と既存試験を実装根拠として示し、新しい業務仕様にはしない。

## 再現した不足と影響範囲

#295の `init_db()` は索引名を含むRuntimeErrorで不正・無効索引を検出するが、最初のエラーで停止する。重複の会社・名称、関連行、実際の索引定義を一覧にはしない。初期化にはDDLと初期データ登録・commitが含まれ、導入前の読み取り専用診断には使用できない。

変更前mainの使い捨てSQLiteでVehicle.officeを存在しない名称へ変更したところ、`init_db()` は成功し、その参照を残した。既存の起動検査が全参照検査ではないことの再現であり、起動処理へ修復や参照検査を追加する理由とはしない。今回追加するのは独立した `tools/q04_master_preflight.py` とそのテスト・CIだけ。アプリの起動・ルート・モデル・Q03/Q08/Q11のコードは変更しない。

## 検査範囲

| 対象 | 診断する内容 | 判定上の注意 |
| --- | --- | --- |
| 5マスタ共通 | 同一会社・同一名称の重複、NULL/空白だけの名称・会社、存在しない会社 | SQLの等値・GROUP BYを使用。他社の同名は重複ではない。大文字小文字や全角半角を勝手に正規化しない |
| 5マスタの索引 | `uq_<table>_company_name` の存在、一意性、company_code/name列、部分条件 | 実定義と期待定義を出す。修復しない |
| PostgreSQLの索引 | pg_index.indisvalid / indisready | 実際に失敗したCREATE UNIQUE INDEX CONCURRENTLYの残骸でも検証 |
| 営業所 | vehicle.office / user.office / driver.office / patrol_result.office / checklist_result.target_office / office宛news.target_value | 同一会社内の非空参照。office宛Newsの空宛先も異常。任意の未設定は許容 |
| 車種 | vehicle.type / vehicle_type_import_mapping.vehicle_type_name | 他社にだけ同名があっても不正参照として検出 |
| 納入先・内容区分 | patrol_result.delivery_place / content_type | 非空の文字列参照。対象別の必須入力など、フォーム検証全体を代替しない |
| 免許種別 | driver.licenses_json内のtype | 不正JSON、配列/要素型不正、空type、同一会社にないtypeを検出 |
| 表示順 | 5マスタのmaster_display_order | 不正JSON、重複ID、削除済み・他社IDを検出。一部の並び順だけの保存は許容 |
| 当時の営業所 | vehicle_maintenance_record.invoice_details_json.cost_attribution.office（cost_officeプロパティの保存先） | 現マスタにない名称はinfoのhistorical_name。誤って破損扱い・現在名への書換えをしない |

会社・名称・行IDのサンプルと件数、索引名、実定義/期待定義、有効性をJSONで出す。重複は会社と名称で対象を絞り込め、参照異常は元表と列・行IDで調査できる。サンプルは既定10件、最大100件。件数は検査全体、サンプルは一部であり、全行のエクスポートではない。業務上の会社コード・マスタ名を含むため管理者向けの制限された場所に保存する。接続URL・パスワード・利用者氏名の列は出力しない。

代表的なcodeは `duplicate_name`、`missing_reference`、`index_missing`、`index_definition`、`index_invalid`、`invalid_json`、`invalid_order`。#295の停止メッセージに出た索引名と、この一覧のindex/tableを対応させる。tableとマスタの対応はoffice＝営業所、vehicle_type＝車種、delivery_place＝納入先、license_type＝免許種別、patrol_content_type＝内容区分。

## 読み取り専用の実行方法

DBA承認済みの隔離された非本番コピーだけを使う。既定のDATABASE_URLへフォールバックしない。接続URLは専用環境変数 `Q04_PREFLIGHT_DATABASE_URL`、DB名又はSQLiteファイル名は必須引数で明示する。URLをコマンド引数や共有ログへ出さない。本作業では下記の専用fixture以外へ接続していない。

```bash
# 承認された秘密管理経路でQ04_PREFLIGHT_DATABASE_URLを設定しておく。
python tools/q04_master_preflight.py --confirm-nonproduction \
  --expected-database dkss_q04_ci --schema public > master-preflight.json
# SQLiteの一貫した復元コピーの場合（環境変数を明示して切替済み）
python tools/q04_master_preflight.py --confirm-nonproduction \
  --expected-database q04_snapshot.sqlite > master-preflight-sqlite.json
```

PostgreSQLはloopbackかつ `q04_` で始まるDB名又は `dkss_q04_ci` だけを許可し、接続後もcurrent_databaseを照合する。URLのquery overrideを拒否する。default_transaction_read_onlyとREPEATABLE READ/READ ONLYを設定し、statement timeout 15秒・lock timeout 2秒でスナップショットを読む。SQLiteは既存ファイルをmode=roとquery_onlyで開き、明示BEGINの中で読む。どちらも最後にrollbackし、アプリのcreate_app/init_dbは呼ばない。実容量や複製方式、ポート転送の先が非本番であることの確認はDBAの責任として残る。

終了0は「対象範囲にerrorなし」で、履歴infoや未検査範囲の業務受入完了を意味しない。終了1は要調査の整合性問題あり。終了2は未完了・接続/権限/スキーマ不一致など。欠落表/列やRLSがあればcomplete=falseとし、部分的に読めたことを正常としない。RLSは所有者で全件が見える場合でも保守的に未完了とする。DB接続失敗時は秘密を含むdriverエラー本文を出さない。

## PostgreSQLとSQLiteの境界

両方でデータ重複、今回の文字列/JSON参照、索引の定義を診断する。PostgreSQLでは実カタログの有効/ready状態と一貫したread-onlyトランザクションを検証した。SQLiteには同じinvalid/ready状態やPostgreSQLの行ロック・deadlockはなく、それらの検証の代用にはしない。SQLiteのDB全体の物理破損検査、独自collation・拡張・全FK、既存表以外の業務データ全件、添付・S3、全JSON内の参照は範囲外。WALを含む整合するコピーの取得はQ11の復旧手順側で行う。

## 変更・削除・再登録の既存試験と不足

既存の `test_q04_master_rename/delete/rollback`、PostgreSQLの `delivery_integrity`、`named_master_gaps`、`driver_license_links`、`master_reuse_and_reverse`、`history_master_links`、`vehicle_batch_master_links`、`news_office/resilience` は再実装しない。営業所・車種の割当更新/解除、費用の当時営業所保全、履歴/お知らせ利用中の変更拒否、納入先・免許・内容区分の変更/削除とJSON、同名再登録と旧ID、他社不変、途中失敗rollback、同時保存の順序を対象にしている。

今回の不足は「変更経路が正しくても、既に不正なDBや復元コピーを読取診断できない」点だった。追加試験では5マスタの複数異常の一括検出、他社名での誤充足防止、履歴名の誤判定防止、JSONと表示順、欠落スキーマ、file hash不変、DB側の書込拒否、実invalid索引のOID/行不変、RLSとスナップショットを確認する。

**同名再登録の世代を文字列だけから証明することはできない。** 既存DBで一度切れた参照が後から同名マスタと一致した場合、診断だけで正当な関連かを判定しない。免許・内容区分を含む利用中保護の経路試験と、旧ID/当時表示・監査の業務照合を実環境受入へ残す。未知のレガシー値・Q03/Q08移行後の履歴・実容量/限定権限は、架空DBでの成功から完了扱いにしない。

現行の初期ITC管理者はoffice="ITC"を持つ一方、対応する営業所がない構成を架空の実アプリDBで確認した。この場合もmissing_referenceとして要調査を表示し、管理用会社の例外を勝手に実装しない。管理用表示か業務上の所属か、受入責任者が判断し、根拠付きの例外又は承認済みの是正作業へ分ける。

## Q03・Q08・Q11との依存

確認時点でQ03 #283は未マージ（head `2236a57`、非ドラフト）。対象移行・本人IDと履歴の扱いは同PRの担当範囲で、今回のコマンドは人物の氏名・usernameからUUIDを補完しない。反映後は専用移行の順序・再実行・旧履歴保全を担当手順と照合し、必要な結合差分だけ再検証する。

Q08 #285/#297はmain反映済み。UUID世代、確定済み日報の閲覧証跡、チェックリスト通知宛先の保全はQ08の既存検証と[復元仕様案](Q08-person-history-and-recovery-20261028.md)を使う。本診断の0終了で本人識別まで正常と判定しない。未確定レガシーの氏名照合等の残条件も担当文書のまま維持する。

Q11 #278の復旧とreadiness資材は、全表件数/ハッシュ、sequence、FK、添付、owner/ACL/RLS等の担当範囲。本診断はマスタ文字列参照の補助であり、Q11のバックアップ/restoreを再実装・実行しない。[Q11受入手順](Q11-operational-readiness-20261028.md)に従い、一貫したバックアップ取得→通知/workerを止めた隔離環境への復元→Q11比較→本診断→本人識別/業務画面の受入という順で証跡をそろえる。runtimeへのDDL権限追加で診断を通さない。

## 導入の受入条件と残工数

1. リリースSHA、仕様参照版、DB/schema、会社数/件数、owner/role、拡張・照合順序、原本保管、停止/再開担当を確定する。
2. DBA承認の非本番復元コピーで診断し、complete=true、全errorの解消又は根拠付きの例外承認、historical_name等の個別受入を記録する。異常は修正責任者・根拠・対象会社/行・復旧手順を決め、別途承認された作業で扱う。診断ツールで修復しない。
3. Q03/Q08の本人世代と監査、マスタ変更・削除・再登録後の業務表示/帳票/履歴、旧cookie/旧ID/他社の拒否を代表ケースで受入する。
4. Q11のバックアップ復元、元DB/添付不変、限定ロール、実容量の実測、RPO/RTO・再開判断を確認する。正常データの起動と、不正索引での停止時に管理者が対象と原因を特定できることを確認する。

このPRの架空DB診断機能を除くQ04残工数は、対象データと環境が提供済みで追加不具合がない前提で、既存データ棚卸し/判定2〜4人時、Q03/Q08反映後の結合受入1〜2人時、Q11連携と実容量/限定権限・停止復旧確認2〜4人時、合計 **5〜10人時** が目安。異常データの修復設計・他担当の改修・正式仕様判断・環境/承認待ち・実容量の処理経過時間は別。現段階で本番導入可とは判定しない。
