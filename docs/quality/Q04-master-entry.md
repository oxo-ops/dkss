# Q04マスタ世代：承認された対象だけに到達するライブラリ入口

本入口は本番適用の承認ではない。本番job・秘密値・認証取得・証跡保管サービスを含まない。
`18ae141b`を維持するログイン直接復旧（既存`upgrade-account-identity`）は、この入口の完成待ちにしない。
Q04対応版を選び、5表の世代準備が不足すると診断した場合だけ移行入口を必要とする。
台帳名は「技術移行選定台帳／M07：Q04マスタ世代」。仕様書M07の請求訂正とは別である。

## 担当とファイル

| 担当 | ファイル | 責務 |
|---|---|---|
| 主管 | `tools/migration_entry.py` | manifest/承認・対象照合・実行結果・読取証拠の比較 |
| Q04 | `tools/migration_adapters/q04_master_generations.py` | 明示schema/guardで本体へ1回だけ委譲 |
| Q04 | `dkss_app/master_generations.py` | 同一接続の任意guardを2か所で呼ぶ |
| 主管 | `tests/test_migration_entry.py` | オフライン承認/証跡/再実行禁止の差分受入 |
| Q04 | `tests/test_q04_master_generation_entry.py` | フック/SQLite/新規隔離PGの差分受入 |

既存のDDL、NULLへのUUID初期付与、5表のロック順序、commit/rollbackを再利用する。
本体の従来呼出しは任意引数省略で互換を維持する。非本番CLI/読取診断の制限は変更しない。
主管の進行中ログイン復旧資料やQ03/Q08/CSV/Q11処理をここで変更・再実装しない。
全移行registry、独立CLI、自動選定/再試行/再開、bootstrap、修復、復旧実行は提供しない。

## 呼出し契約

`execute_q04(*, engine, manifest: bytes, approval: dict, evidence: EvidencePort) -> dict`

主管が専用Engineと既存認証/証跡保管先への接続口を提供する。EngineはPostgreSQL/psycopg2、
READ COMMITTED、非autocommit、SQL/poolログ無効で使用する。資格情報や接続URLは返却・記録しない。
`manifest`は承認後に不変としたUTF-8 JSONの正確なbytesへのSHA-256で固定する。
入口・アダプタ・本体ファイルのSHA-256も照合する。全processの成果物/設定版統一は別の運用前提。

`EvidencePort`は主管の**信頼された保存先**への契約であり、利用者が任意JSONを自己承認する仕組みではない。

- `read(ref) -> dict`：承認記録/既存診断/停止・復旧証跡を読む。
- `claim(pending) -> receipt_ref`：対象/attemptを原子的・永続的に予約しPENDINGを保存する。
  既使用attemptと未解除対象を拒否する。保存失敗・応答不明も停止し、DB本体へ進まない。
- `append(event) -> receipt_ref`：永続保存のACK後に戻る。同一event IDは同じ内容だけ許容し、上書きを拒否。
  **FINALでも対象予約を自動解除しない**。保存済みFINALのACKだけが失われる場合にも再実行を防ぐ。

本ライブラリには予約解除APIがない。正当な次回適用/適用済み確認も、主管が前回状態を照合し、
新baseline/新P1/新attemptで別途手動判断する。UNKNOWNや未完PENDINGを自動解除してはならない。
テスト用`MemoryEvidence`はこの契約のモデルであり、本番用永続化アダプタではない。
本番job/既存保存先の実バインド・耐障害性/排他の受入は主管の残条件である。

必須manifestフィールドはコードの`_approved()`で厳格に検証する。未知キー/重複キー、
`example_only=true`、期限外承認、digest/参照不一致、表の過不足は接続前に拒否する。

| 部分 | 必須内容 |
|---|---|
| 基本 | format_version=1、operation=`q04.master_generations.v1`、example_only=false、台帳、attempt_id |
| release | 完全source_commit、entry_sha256、adapter_sha256、core_sha256 |
| target | ref、provider_resource_ref、secret_ref、scope、snapshot |
| snapshot | endpoint/port/DB、session/current role、primary、明示schema/OID、元search_path/effective_schemas、isolation/read_only/TLS、接続パラメータdigest、固定5表OID/定義digest/権限/索引valid-ready |
| evidence | T01/T02/T03、baseline、privileges、writer_stop、backup_restore、form_revocation、rollback_write_restrictionsの各ref/digest |
| approval | P1_ref、window_start_utc、window_end_utc |
| 外側approval | approval_ref、approver_ref、manifest_sha256、target_ref、source_commit、valid_until_utc、P1_APPROVED |

架空値による完成形は`tests/q04_entry_fixture.py`の`manifest_for(fake_snapshot())`と`approve()`を参照。
実値・承認を生成するコマンドではない。参照先の診断等は別JSONのcanonical digestでも固定する。
`isolated-test`はloopback・`q04_entry_` DB/schemaだけ。`production-approved`はTLS使用に加え
実接続の`sslmode=verify-full`を要求する。本番のprovider資源との対応は既存T02証跡で確定する。

## 同一接続の2段階guard

本体が接続/transactionを所有し、外側の別接続で確認して済ませない。

1. **CONNECTED**：実接続直後、明示schemaと元path/対象/role/5表を照合。boundedな読取のため
   transaction-local statement timeoutを設定するが、search_pathは一致させるために書き換えない。
   対象一致後に安定したtarget/operationキーの非待機advisory transaction lockを取得する。
2. **LOCKED**：既存本体が5表ACCESS EXCLUSIVEを取得した後、最初のDDL/UUID更新より前。
   同じconnection/transactionでcatalogを読み直し、期待OID/定義と実保持lockを照合する。
   承認/期限/参照も再照合し、待機中の失効を拒否する。

PG lock_timeout=2s、statement_timeout=15sと既存本体の順序は維持する。
snapshot取得は固定対象の照合であり、別の広範な診断/修復器ではない。schema所有者/ACL/DBAの
同時変更、全writer/reader停止、restart経路凍結、proxyとproviderの対応は運用側でも保証する。
通常runtimeにDDL権限を付与しない。PGのALTER権限を任意のGRANTで補える前提にしない。

## 結果と確認できる限界

返却値にはattempt/digest/対象別名、status、commit_state、完了guard段階、固定failure_code、
取得可能なSQLSTATE、既存report、証跡参照を含む。対象不一致は`rejected_fields`に表/属性名だけを
残し、実値を出さず原因箇所を示す。例外本文/完全URL/業務行は一般ログへ出さない。
契約不正は固定コードの`ContractError`で接続前拒否。実行中の例外は結果へ分類する。

| status / commit_state | 確認根拠 |
|---|---|
| APPLIED / ACKNOWLEDGED | 既存本体の検証・commitが正常復帰しFINAL保存もACK |
| ALREADY_APPLIED / ACKNOWLEDGED | 承認対象が一致、正常復帰reportで全5表追加/付与0、FINALもACK |
| REJECTED / NOT_COMMITTED | guard拒否、commit開始なし、rollback通知に加え同じ生存DBAPI接続のIDLEを確認 |
| ABORTED_CONFIRMED / NOT_COMMITTED | 本体のcommit前障害で上記rollback根拠を確認 |
| OUTCOME_UNKNOWN / UNKNOWNまたはNOT_CONFIRMED | commit開始後の例外、接続喪失、rollback完了を証明できない場合 |
| OUTCOME_UNKNOWN / ACKNOWLEDGED | 本体commitは正常復帰したがFINAL保存/応答が失敗 |
| OUTCOME_UNKNOWN / NOT_ATTEMPTED | claim保存/応答不明。本体未呼出しだが予約状態の確認が必要 |

FINAL保存失敗が確認済みrollback後に発生した場合もstatusはOUTCOME_UNKNOWNとし、
既知のcommit_state=NOT_COMMITTEDは維持する。DB状態と記録状態を混同しない。

SQLAlchemy commit/rollbackイベントはDBAPI呼出し**前**に発火する。rollbackイベントだけでは
成功としない。commitイベントが発火した場合は、送信前故障で実際には未commitでもUNKNOWNとする。
反対にcommit応答喪失後にDBがIDLEでも、未commitとは認定しない。自動retry/再開はしない。
強制終了ならPENDING/guard途中記録が残る。FINAL欠落を未反映の証明にはしない。

`reconcile_q04(*, attempt, readback_ref, evidence)`は既存の承認済み読取証拠を比較するだけ。
新しいDB接続/移行/復旧/予約解除は行わない。storage状態と当該attemptのcommit証明を別に返し、
常にresume_allowed=false。新規UUIDの期待値等が残っていない場合、readiness成功だけで
当該attemptのcommitを証明しない。確定主張にはattempt/target/digestが一致するtransaction証跡も必要。

## 既存証拠と残条件

T01の18ae141b/Auto-Deploy Off、T02のDB/schema識別、T03のaccount_identity/Q03/OCR owner欠落と
日時VARCHAR(30)は報告時点の確認済み事項として保持する。一律未確認に戻さない。
不足は完全live SHA/全process・設定版、元role/options/pathと表解決、既存制限付き証跡参照、
選定時の5表OID/定義/権限/世代状態、停止/保全/P1/P2・旧フォーム失効/切戻し書込制限である。

Q04のmaster_generation NULLへの初期付与は、Q03/Q08人物UUIDやCSV旧owner NULL保留とは別処理。
CSVの非修飾参照へQ04明示schemaの合格を流用しない。Q11の保全・復旧手順は再利用し、
復元世代/同じ署名鍵では古いフォームが失効するとは限らない。鍵fallback/sessionを含む失効方針を
主管が承認し、切戻し先の保護前writer/旧CSV私有経路への書込を禁止する。

差分受入は新入口・guardに限定する。既存240件、6処理、CSV追加受入はローカルで再実行しない。
新専用CIは新規`q04_entry_ci`サービスと自身で作成したランダムschemaだけを使用・削除する。
既存CI/テストの条件は変更しない。自動起動する通常PRチェックは新入口差分結果と分けて報告する。
