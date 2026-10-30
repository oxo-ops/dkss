# M06 車検証満了日の誤表記修正と残る設計判断

## この差分で解消する問題

車両マスタの `inspection_expiry` を元にした通知と点検画面が「12か月点検期限」と表示していた。満了日の意味を変更せず、該当する表示を「車検証満了日」に訂正する。新たな満了日通知、点検画面の証明書欄、計画JSの満了日説明、計画画面の通知ルール説明が対象。

これはM06の独立した先行修正であり、車検／12か月点検の保存種別分離・旧行の根拠判定・年間表の分類・通知終了判定の解消を意味しない。12month行の全件保留や再分類は行わない。

## 通知の変更範囲

文言のみ。phaseキー、日付閾値、bucket、revision、送信済み判定、ended_status、read、通知リンク、定期実行の入力signatureには変更なし。旧通知本文は保存済みのままとし、書換えや一括再通知はしない。通知の終了判定は後述の設計判断を残す。既存の誤った終了判定がこのPRで直ったと扱わない。

## 確認

基準main: `0857396a9d96aa3d8a588cdaef879255716a21c1`（#346を含む）。

- ローカル初回は追加4件＋通知回帰38件の計42件成功（67.912秒）。通知ルール説明の追加修正後は専用4件を再実行し成功（7.693秒）。件数を合算して独立46件とは数えない。
- `test_m06_certificate_expiry_labels`: 新規通知の意味、旧通知と配信receipt/readの保持、証明書欄、閾値とphaseキーの保持。
- `test_inspection_alerts`: 会社／営業所／管理者境界、二重配信防止、週次間隔、既存通知状態の回帰。
- `node --check static/js/vehicle_inspection_plans.js`、`git diff --check`。
- 新規一時SQLiteと架空データ。HTTP fixtureはCSRF無効。PG競合・実ブラウザ・本番配信受入は含めない。
- U32専用試験は実行しない。全体回帰は通常CIに委ねる。

## DB既存列・制約の確認（実装前の設計案）

| 対象 | 既存の仕組み | 再利用可否／残る問題 |
| --- | --- | --- |
| Plan | company/vehicle/kind/period_keyの一意制約 | 2種別で同月保存できる。制約変更不要 |
| Execution | company/vehicle/kind/performed_dateの一意制約 | 2種別で同日保存できる。制約変更不要 |
| PeriodicRecord | source_draft_id/source_record_indexの一意制約、details_json | 同じ原本の別確認明細を別indexとして保存可能。ただし既存indexを勝手に複製しない |
| PlanEvent | before/afterを含むdetail_json | 新規予定の明示種別を監査情報として記録可能。旧イベントのafter.kindも同一化済みの場合は原入力の復元不可 |
| Execution | kind、plan_id、source_record_id、next_month、factory、note、created_by/at | 手動実績に解釈版や根拠を保持する独立JSON列なし。noteへの機械マーカー混入や作成日時だけの推定は採用しない |
| ExecutionEvidence | execution_id主キー、document_idは非unique、証明書根拠 | 同じ原本参照は複数Executionから可能。ただし既存certificate専用検証を12か月点検の確認済み根拠へ流用しない |
| 共通整備案件 | 現行ExecutionからMaintenanceへの明示参照なし | 同時実施の2実績を同じ整備案件から参照するための参照設計が必要 |

推奨設計案（未承認・未実装）:

1. Plan/Executionの保存kindを勝手に再分類せず、確認種別と根拠を明示的に保持するnullableなcontext列を追加する案を比較する。新規行だけ独立種別の確認情報を記録し、旧NULLは「不明」ではなく「既存根拠の照合対象」とする。
2. PeriodicRecordは既存details_jsonを再利用。PlanEventの既存JSON再利用とPlan専用列追加の読取負荷・整合性を比較する。単純な全12month一律未確認は不可。
3. 同時案件はExecutionにnullableなmaintenance_record_id参照を追加する案を比較する。登録時に会社・車両を照合し、2実績を明示的に関連付ける。片方の保存で他方を自動完了させない。
4. nullable追加だけでもDDL/migrationに該当する。列名・制約・監査・既存値保全・旧版互換・ロールバック設計の承認前にmodel/schema/migrationを変更しない。今回のPRには含めない。

## 旧行の判定と通知の最小変更案（未実装）

- 原本、登録済み確認JSON、監査の原入力、証明書根拠を同一会社・車両・対象行で照合する。OCR抽出値だけを人が確定した事実と扱わず、食い違いは自動分類しない。
- 車検と確定できる行だけ車検期限判定に使用。12か月点検と確定できる行では `certificate_updated` を終了根拠から除き、対応する12か月実績・予定のみで判定する。
- 根拠未確定行は承認済みの「車検／12か月点検・区分未確認」を表示する。ただし、その行の新規通知・終了判定・再通知方針は未決。既存通知の終了・再開を勝手に選ばない。
- 既存Delivery/ExpiryDeliveryのID、phase、bucket、送信日を維持して重複を抑止。既にended_statusが保存された通知を自動で再開しない。未終了通知の誤終了防止と、既終了通知を再開しない扱いを区別する。
- 区分未確認行を12か月/車検のどちらの完了根拠にも使わない場合、現行のexpiry_is_planned/has_actualによる抑制が外れて新たな通知が発生し得る。ここを一律に適用せず、旧receipt単位の互換方針の承認が必要。

残る受入: 新規2種別保存、別日／同日2実績、同じ案件／原本参照、確定済み旧行保持、区分未確認表示、年間表・カルテ・Excelの一貫分類、通知の誤終了防止と重複防止、会社境界／認可／状態遷移。
