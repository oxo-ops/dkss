# Q10 業務フロー総合テスト（2026-10-28）

調査開始main: `6d7d8c9ccc7bd661cd86a6b5fa68b99da2a7c668`（PR #272）。
広範囲の299件を検証したmain: `6c13df3859b0c6b7e2c35bfe360f4a15ff7bc85e`（PR #274・#275反映後）。
最終追従main: `c7efecbc3ede1c7c44855d1f768544531eee3172`（PR #276・#277反映後）。
調査中のmain更新は差分を確認してfast-forwardで追従した。後者の変更は点検原本の参照境界と乗務員の無事故日数表示であり、追加10件と原本・日付の関連テストを追従後に再実行する。
変更は `tests/test_q10_business_flows.py` と本記録だけ。アプリコード・画面・DB定義・本番データを変更しない。
Q06の一次判定（33テーブル55列、必須テーブル化0件）はそのまま引き継ぐ。

## 調査と分類

「検証済み」は下表の特定条件で、実ルートと一時SQLiteを実行した意味。実ブラウザ、本番環境、実PostgreSQLまで合格した意味ではない。
仕様の照合対象はリポジトリ内の仕様・設計資料と既存契約テスト。過去チャットに置かれた仕様書PDF原本（v0.21〜0.25）はこのcheckoutに存在せず、原本全ページとの再照合は未実施。

| 業務フロー | 仕様・既存の根拠 | 今回の分類と追加の理由 |
| --- | --- | --- |
| 日常点検→提出→承認・差戻し | `daily_inspection_defaults.py`、`dkss_app/checklists.py:8314`、`docs/quality/Q05-checklist-business-dates-20261027.md:15`。`test_q02_daily_inspection_flow.py:150`、`test_q02_checklist_boundaries.py:194,257`、`test_workflow_regressions.py:942,971` | 通常承認、順序、差戻し後の承認枠初期化、再送拒否は既存で検証済み。明示的に必須設定した項目の不足→送信拒否→補完して再開を追加。標準テンプレート全項目の必須化は行わない |
| 不具合→整備→再確認→運行判断 | `dkss_app/checklists.py:3686,3870,4331`、`test_q02_daily_inspection_flow.py:164,184`、`test_q02_vehicle_workflow_boundaries.py:343,352` | 正常・再確認異常・再整備と再送は既存で検証済み。判断commit前、整備INSERT後、再確認イベントINSERT後の失敗と再試行、commit後の外部通知失敗を追加 |
| 車両登録→マスタ変更→履歴・関連保持 | `dkss_app/vehicle_master.py:1884`、`test_workflow_regressions.py:738,832`、`test_q04_master_rename.py:47,63,90`、`test_q04_master_delete.py:47,79`、`test_q04_master_rollback.py:156` | 各処理の境界・履歴保持は既存で検証済み。HTTPで新車両登録→OCR点検登録→営業所・車種名変更→同一ID・原本・点検履歴維持という接続部分を追加。Q04の処理自体は変更しない |
| 日報取込→本人特定→本人・管理者閲覧 | `docs/driving-report-import.md:13`、`docs/driving-admin-self.md:5`、`docs/driving-person-vehicles.md:7`。`test_driving_identity_resolution.py:140,146,152,157`、`test_driving_report_readership.py:44,87,132` | 氏名一意照合、例外選択・保留、失効と権限は既存で検証済み。実取込で作られた対応を使って本人一覧・詳細、別人拒否、管理者の会社全体一覧・詳細を連続確認する経路を追加 |
| 原本→OCR→確認→登録 | `docs/document_import_queue.md:9`、`docs/driving-report-readback.md:5`、`test_document_import_queue.py:46,70,80`、`test_workflow_regressions.py:410,503,516`、`test_q02_import_worker_access.py:151,167` | 受付永続化、読取部分失敗・再試行、取消・権限失効は既存で検証済み。非同期受付→実worker→確認編集→INSERT後失敗→同じ原本で再試行→原本取得→再送拒否、および日付不足からの再開を追加 |
| 整備→請求書追加→訂正・再取込→費用 | `docs/quality/Q07-invoice-lifecycle-20261028.md:14`、`docs/quality/Q07-invoice-reimports-20261028.md`。`test_q07_invoice_lifecycle.py:94,141,244,261,275`、`test_q07_invoice_reimports.py:120,196,219`、`test_domain_consistency.py:87,137` | 既存テストが追加・訂正連鎖・再取込・不足値・途中失敗・集計一致を扱っており再実装しない。今回は既存テストを再実行 |
| 通知発生→閲覧→既読・削除・復元 | `dkss_app/checklists.py:4390`、`test_q02_notification_boundaries.py:122,144,160,180,203` | 受信者境界・削除版数・一括操作は既存で検証済み。実運行判断から生じた通知のプレビュー（未読維持）→既読→削除→削除中既読拒否→版数付き復元と、元点検・イベントの不変性を接続テストで追加 |

表内の既存ファイルは `tests/` 配下。行番号は上記main、追加テストは本PRの版を参照。

## 追加10件

`tests/test_q10_business_flows.py` は既存シナリオのbuilderを借用する。既存TestCaseを継承せず、その既存テストを新ファイル内に二重収集しない。

1. `test_configured_required_daily_answer_blocks_submit_then_can_resume` — 必須設定した点検の不足時は400、状態・履歴・通知が不変。回答補完後に承認待ちになる。
2. `test_judgment_commit_failure_preserves_answers_events_and_notice_then_retries` — 判断commit前のDB失敗で500。全関連状態を戻し、外部通知なし、再試行後の判断イベントは1件。
3. `test_repair_post_insert_failure_rolls_back_maintenance_and_can_retry_once` — 整備INSERT実行後にDB失敗。整備・点検・履歴・通知を戻す。再試行で整備1件、古い再送409、再確認後に運行可。
4. `test_external_judgment_delivery_failure_keeps_committed_notice_and_replay_is_fenced` — 外部配信の時点で別DB接続から承認済みを確認。配信例外後も業務成功302と内部通知1件を保持。再送409、追加配信なし。
5. `test_recheck_event_insert_failure_keeps_defect_open_then_retry_clears_it` — 再確認イベントINSERT後に失敗しても不具合は再確認待ちのまま。再試行で解消、整備は1件、古い再送409、当初の×回答は変えない。
6. `test_generated_judgment_notice_preview_read_delete_restore_keeps_business_result` — 実通知で閲覧から復元まで確認。通知の既読状態は復元後も保持し、元点検・イベント・運行可の判定は不変。
7. `test_queue_to_confirmation_sql_failure_keeps_source_then_retry_and_replay` — 実受付・workerからの確認保存で点検INSERT後に失敗。原本を保ちpreviewへ戻り、編集値と原文を分離して再登録。原本取得が元bytesと一致し、再送409で1件を維持。
8. `test_queue_to_confirmation_missing_date_preserves_original_and_resumes` — 日付不足400。原本保持、未登録のまま、補完した同じフォームで登録可能。
9. `test_registered_vehicle_keeps_imported_history_and_original_after_master_renames` — 新規登録した車両の営業所・車種名を変更しても、取り込んだ点検の親ID・内容・原本・履歴画面を維持。
10. `test_confirmed_report_auto_identity_person_admin_and_unrelated_reader` — 取込→自動本人対応→本人/管理者の閲覧と別人の404。閲覧後も日報の内容と原本は不変。

故障注入は一時SQLiteのSQLAlchemyイベントと外部配信モックのみ。故障を注入したフックが実際に1回到達したこともassertする。
既存のHTTPステータス、集計の意味、元回答、原文、権限を変えずに検証する。

## 発見した不具合・担当境界

追加経路で新規のアプリ不具合は再現していない。アプリ修正は0件。
Q08で発見済みの旧利用者への通知混入は、この10件の合格によって解消したとは判定しない。旧利用者・再作成アカウントの経路はQ08の修正と検証に委ね、通知・認証コードを編集しない。
Q03・Q04・Q05・Q08・Q11の実装ファイルとDB構造も編集しない。

確認済みのマージ済みPRは、OCR接続 #245・#265、本人特定 #244・#262、取込途中の権限失効 #270、マスタ #243・#247・#250・#258・#268、費用 #267・#269。
調査中に #274（削除車両の分析閲覧）、#275（費用の表示日付/精度）がmainへマージされたため、最終検証では両方の追加テストも対象に含める。
続いて #276（点検原本の車両所属照合）、#277（乗務員の業務日付）がマージされたため、追加10件と各PRの境界テストで差分を検証する。
未マージの #273（マスタとお知らせの競合）は取り込まない。各PRのコードをQ10から再実装・変更しない。

テスト作成時、標準テンプレートに必須項目があるという仮定、管理者の無条件会社全体表示という仮定、履歴一覧に点検明細全文が出るという仮定は既存実装・仕様と一致しなかった。
それぞれ明示的な必須設定のfixture、会社全体を指定する既存操作、履歴概要と点検詳細の別画面での検証に修正した。アプリの仕様や合格条件を緩めたものではない。

## 未検証・仕様確認待ち

| 区分 | 残る項目・理由 |
| --- | --- |
| 未検証 | 実PostgreSQLでの同時操作・deadlock/ロック、プロセス強制終了・通信断、実ブラウザからのCSRF付き操作。今回のHTTPテストはSQLite・TESTINGであり、この実証にはならない |
| 未検証 | 実資料のOCR精度・本人名照合・業務受入、実メール/Web Pushの到達。外部処理はモックし、本番と実個人情報を利用していない |
| 担当依存 | Q08の旧利用者への通知混入、Q03/Q04/Q05/Q11の未マージ変更を含む統合確認。並行担当の修正を先取りしない |
| 仕様確認待ち | 標準日常点検で空欄をどこまで認めるかの業務受入基準。現在の標準項目に全件必須フラグがないため、必須化を推測して実装しない。設定された必須項目の不足拒否は検証済み |
| 仕様確認待ち | 外部配信失敗後の自動再送回数・到達保証・表示。今回は内部通知と業務状態の保持を検証し、配信到達や自動再送を保証しない |
| 資料未取得 | 仕様書PDF原本との全ページ再照合。リポジトリ内の抜粋・仕様記録を超えて確認済みとしない |

Q10の今回の自動回帰テスト追加に残る実装は0時間。
上記の運用受入までを含む残調査・検証は概算2〜4人日（16〜32時間）:
仕様原本/受入条件の照合4〜8h、隔離PostgreSQLとブラウザでの異常・並行試験8〜16h、各担当マージ後の統合再確認4〜8h。
資料提供・隔離環境準備・他担当の完了待ちは含まない。Q08の修正工数や本番操作はこの見積もりに含めない。

## 検証結果

実行結果と再現コマンドは、この節の確定結果を参照。実行していない全件回帰・本番検証を成功扱いしない。

- 広範囲確認版main `6c13df3` でPython **299件成功（追加10件・既存289件）、失敗0・エラー0・skip0**。3つの独立プロセスで一時SQLiteを使用。
- 点検・接続: 111件、取込・本人閲覧: 75件、マスタ・費用・通知・分析境界: 113件。
- 最終追従版main `c7efecb` で、追加10件を含む原本・日付の関連 **38件成功、失敗0・エラー0・skip0**。後者で299件全体を再実行したという意味ではない。
- JavaScript 18件成功。`node tests/responsive_layout_js.cjs` の2つのPASSも確認。これは画面を開くブラウザE2E試験ではない。
- 生成スキーマは既存資料とバイト一致。ステージ済み差分の `git diff --cached --check` 成功。
- アプリのSQLAlchemyErrorログ・外部配信例外ログの一部は、意図的な故障注入で発生させたもの。テスト失敗件数とは区別する。
- 調査開始時のmainでの試行・初期fixture修正・途中停止した収集は上記件数へ加算しない。全リポジトリの `unittest discover` 完走は今回未実施。

再現する場合、requirementsを導入し、ルートとtestsをPYTHONPATHへ追加する。AWS_EC2_METADATA_DISABLED=true、OPENAI_API_KEY/SMTP_HOST/S3_BUCKET_NAME/VAPID_PRIVATE_KEY/VAPID_PUBLIC_KEYは空で実行する。
実際の選択実行ではローカルのcollectorで各module自身のTestCaseだけを収集した。fixtureとしてimportされた別moduleのTestCaseを追加収集しない。以下の明示的なclass指定で同じ299件を再現できる。

```sh
python -m unittest -v test_q10_business_flows.DailyFlowFailuresTests test_q10_business_flows.QueuedImportFlowTests test_q10_business_flows.ImportedDrivingReadFlowTests test_q02_daily_inspection_flow.Q02DailyInspectionFlowTests test_q02_vehicle_workflow_boundaries.Q02VehicleWorkflowBoundaryTests test_q02_checklist_boundaries.Q02ChecklistBoundaryTests test_workflow_regressions.WorkflowRegressionTests
python -m unittest -v test_document_import_queue.DocumentImportQueueTests test_document_import_queue.DocumentImportTransportTests test_import_flow.ImportFlowTests test_driving_identity_resolution.DrivingIdentityTests test_driving_report_readership.DrivingReadershipTests test_q02_import_worker_access.Q02ImportWorkerAccessTests
python -m unittest -v test_q04_master_rename.MasterRenameIntegrityTests test_q04_master_delete.MasterDeleteIntegrityTests test_q04_master_rollback.MasterRollbackIntegrityTests test_q07_invoice_lifecycle.InvoiceLifecycleTests test_q07_invoice_reimports.InvoiceReimportTests test_domain_consistency.DomainConsistencyTests test_q02_notification_boundaries.Q02NotificationBoundaryTests test_q07_cost_display_consistency.CostDisplayConsistencyTests test_q02_analysis_boundaries.Q02AnalysisBoundaryTests
python -m unittest -v test_q10_business_flows test_q02_import_document_boundaries.Q02ImportDocumentBoundaryTests test_q05_additional_boundaries.TimingBoundaryTests test_q05_additional_boundaries.DisplayAndInputBoundaryTests
node --test tests/document_import_queue_js.cjs tests/driving_report_insights_js.cjs tests/vehicle_karte_selector_js.cjs tests/invoice_summary_ui_js.cjs
node tests/responsive_layout_js.cjs
python tools/generate_schema_docs.py /tmp/q10-schema.md
git diff --no-index -- docs/database_schema.md /tmp/q10-schema.md
```
