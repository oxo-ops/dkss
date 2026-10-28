# Q07 請求費用の反映・訂正・再送・取消の回帰検証

実施日：2026-10-28  
基準 main：`8fe148f`（PR #263 まで、Q07 日付修正 PR #261 を含む）  
対象：`dkss_app/vehicle_documents.py` の既存費用確認と取込・取消ルート  
品質改善計画の参照：Library version 25、本文版 1.19、Q07 は「一部実装あり」。

## 結果

この変更は回帰テストと検証記録の追加のみ。アプリの仕様・画面・DB・既存データの変更なし。
`tests/test_q07_invoice_lifecycle.py` に実際の Flask ルートを通す 15 件を追加。
独立した一時 SQLite DB と架空データを使用し、実データ・外部 OCR・有料 AI 呼出しなし。

同じ車両・当月・営業所 A の条件で、登録先整備の合計、概要、費用の年別・月別、分析、ダッシュボードの集計関数が一致することを各遷移後に確認。全期間と当月の違いが出ない単一当月レコードを使用する。
金額の反映によって整備中の状態や交換部品を勝手に変更しないことも検証する。

| 追加テスト | 確認した内容 |
| --- | --- |
| initial_addition_correction_chain_and_replay | 初回100→追加30→追加分を20に訂正→再訂正25で125。再送は400、二重反映なし |
| replacing_initial_invoice_preserves_other_additions_and_components | 初回請求を訂正しても他の追加請求・費目内訳が残る |
| correction_can_recover_previously_unknown_components | 訂正版の内訳が揃えば、不明だった内訳を復元できる |
| failed_correction_rolls_back_both_documents_and_history | 保存失敗時は新旧請求書の状態・関連・履歴・金額を全て戻し、再試行できる |
| legacy_baseline_and_unknown_components_survive_correction | 既存500＋追加30→20に訂正で520。既存費用を保持し、不明な費目は不明 |
| zero_invoice_and_corrected_zero_are_known | 初回0・0への訂正を不明額と混同しない |
| validation_probe_rolls_back_entire_correction | 入力確認だけでは費用・請求状態・イベントを保存しない |
| stale_total_and_superseded_selection_cannot_write | 古い合計・既に差し替え済みの請求書を使った更新を拒否 |
| tampered_original_or_payload_cannot_apply_costs | 原本ハッシュ不一致・保存明細不一致を拒否 |
| changed_ledger_or_target_blocks_correction | 集計対象と反映履歴の不一致を検出し、差し替えを停止 |
| inconsistent_components_and_missing_total_cannot_be_confirmed | 合計不明・内訳合計不一致は反映しない |
| addition_overflow_is_atomic | 加算で登録上限を超えると金額・請求状態を変えない |
| database_failure_keeps_review_retryable | 追加反映の保存失敗も原子的に戻し、再試行時に一度だけ反映 |
| import_resubmit_and_already_recorded_do_not_double_count | 同じ確認要求の再送は409。「登録済みとして確認」の再送も追加計上しない |
| pending_cancel_preserves_existing_costs_and_confirmed_cancel_is_blocked | 未反映資料の取消は元の整備500を保持。反映済み資料の取消は409で保護 |

各テスト名には `test_` 接頭辞が付く。原本保持の対象では、保存済み原本を実際の取得ルートで開き、SHA-256 が一致することを確認。
取消は既存仕様どおり：未反映の取込資料を明示取消した場合、その資料は deleted になり、原本を消去する。反映済み費用の自動逆仕訳は実装せず、409 の保護を検証する。

## 実行

```sh
PYTHONPATH=tests python -m unittest \
  test_q07_invoice_lifecycle test_q07_cost_dates test_domain_consistency \
  test_document_connections test_invoice_plan_actuals test_vehicle_overview \
  test_vehicle_analysis_summary test_driving_maintenance_context -v
```

関連 136 件成功（新規 15 件＋既存 121 件）。全件が費用専用テストという意味ではない。
保存失敗テストの `forced Q07 rollback` / `forced Q07 correction rollback`、既存の `ValueError: forced` は意図的に発生させた例外。最終判定はテストの OK で確認する。
既存 CI は unittest discover で新しいテストファイルも収集する。CI 成功・main 反映・本番配備は別に確認する。

## 未確認と次の範囲

- このテストは OCR 後の確認データから開始する。新たなアップロード要求としての同一原本再取込、OCR・手動読取訂正と費用確認履歴の組合せは未網羅。
- 新規取込時に整備レコードへ直接付く請求書と、確認待ち添付請求書の違いを残す。直接付く元請求書を既存の差し替え候補へ追加する変更はしていない。
- 金額の表示 DOM・CSV/PDF 出力、複数車両・長期間・営業所履歴を組み合わせた比較は未網羅。今回の一致は上記の集計関数と登録先 DB 値についての確認。
- PostgreSQL の同時更新・デッドロック・並列再送は未検証。SQLite 逐次試験を競合試験の代わりにしない。
- 反映済み請求書の取消・逆仕訳は既存仕様で停止することを確認しただけで、取消可能にしたという意味ではない。
- Q07 全体の完了、本番反映の完了は宣言しない。他チャットの Q02/Q04/OCR 作業を変更しない。
