# Q07 原本の再アップロードと読取訂正の組合せ

実施日：2026-10-28  
基準 main：`b9be875`（PR #266 まで）  
関連：PR #267（費用確認のライフサイクル15件）は別変更。この追加に #267 のテストコード依存なし。

## 結果と範囲

新規 `tests/test_q07_invoice_reimports.py` の12件と既存関連66件、計78件成功。
実際の受付・ワーカー・確認登録・読取訂正・取消ルートを、一時SQLite DBと架空PDFで検証。
外部の分類とOCRだけをモックし、有料呼出し・実データ利用なし。
アプリのコード・画面・DB・業務フローは変更しない。既存の保護動作を固定するテストと、未解決の組合せの記録を追加する。

| 新規テスト | 確認結果 |
| --- | --- |
| new_upload_of_same_bytes_after_amount_read_correction_is_rejected | 読取額100→125への訂正後も、ファイル名を変えた同じ原本の新しい受付は409。原本・訂正額を保持 |
| other_admin_same_company_reupload_is_still_duplicate | 同じ会社の別管理者による再受付も409。原本は元の利用者で再取得・照合 |
| two_receipts_before_confirm_skip_second_before_ocr | 同じ原本を別受付で2回送信。先に登録後、残りはOCRせずskipped。計上は1回 |
| two_previews_before_confirm_cannot_register_same_source_twice | 2回ともOCR完了後でも、片方登録後の再登録は入力検証400、重複の理由を確認。添付・費用を増やさない |
| content_read_correction_after_addition_keeps_later_correction_valid | 元請求500＋追加30→内容だけ訂正→追加請求を20へ訂正で520。原本・履歴を保持 |
| amount_read_correction_before_addition_is_the_recorded_baseline | 元請求100→読取訂正120→追加30→追加請求を20へ訂正で140。加算前120が履歴に記録される |
| amount_read_correction_after_addition_blocks_ambiguous_ledger_replacement | 100＋追加30→合計を直接140へ読取訂正→追加請求の差し替えは履歴不一致400。140と確認待ち状態を保持。下記の制約を記録 |
| stale_read_edit_cannot_overwrite_added_cost | 追加前の古い訂正画面では追加後130を上書きできず409 |
| read_edit_database_failure_preserves_original_and_cost | 読取訂正の保存失敗で金額・履歴をロールバックし、原本を保持 |
| pending_attachment_cancel_allows_one_fresh_import_of_same_source | 未反映添付を明示取消→同じ原本を新規受付・再登録・追加反映できる。以後の再受付は409 |
| read_corrected_primary_source_cannot_be_cancelled_and_discard_edits | 読取訂正済みの主原本の取消は409。訂正済みの記録・金額・原本を保持 |
| legacy_upload_confirm_also_rejects_same_source | 従来の同期取込でも、登録済み原本の重複登録を確認時に400で拒否 |

各テスト名には `test_` を付ける。金額確認は同じ車両・当月・営業所 A の登録先合計、年別費用、分析、ダッシュボード集計の一致を確認。原本保持はバイト一致と実際の取得ルートの応答で検証。
400と409を混同しない：入力検証時に重複を見つけた場合は既存仕様の400、受付時や登録済み状態との衝突は409。

## 残る制約：追加反映後の金額の読取訂正

再現：元100＋追加30＝130 → 整備実績の読取訂正画面で合計140へ保存 → 追加請求30を20へ訂正しようとすると、登録済み費用140と反映履歴130が一致せず停止。

合計の直接訂正は保存されるが、確認済み請求書の履歴を更新しない。このため、その後の請求差し替えを続けられない組合せがある。元請求の訂正か、追加請求の訂正かを自動推測して履歴を書き換える変更はしていない。

このテストが成功することは、この制約が解消されたことを意味しない。二重計上・誤った差し替えを拒否して現状を保持することの確認。Q07の未解決事項として、金額の読取訂正と確定済み請求履歴をどう整合させるかを継続確認する。内容だけの訂正、追加反映前の金額訂正とは区別する。

## 実行と未確認

```sh
PYTHONPATH=tests python -m unittest \
  test_q07_invoice_reimports test_q07_cost_dates test_document_import_queue \
  test_document_kind_recovery test_document_connections test_invoice_plan_actuals \
  test_domain_consistency -v
```

78件は上記の関連テスト数で、費用専用78件ではない。
`forced Q07 read rollback` と既存の `ValueError: forced` 等は障害を意図的に再現する成功テスト。
PR #267 は検証中に Regression Tests / Dependency Audit / CodeQL の成功をGitHubで確認。ただし、その時点のmainへのマージや本番配備を意味しない。

PostgreSQLでの並列受付・同時訂正、実ブラウザ・出力、異なるバイト列に再作成された同内容の請求書の意味的重複検出は未確認。逐次テストを並列競合の保証としない。
正式な全体仕様書・共有品質改善計画の正本はこの変更では上書きしない。Q07全体を完了扱いしない。
