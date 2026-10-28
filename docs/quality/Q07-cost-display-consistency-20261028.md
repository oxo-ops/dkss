# Q07 分析の費用日付とダッシュボード表示精度

実施日：2026-10-28  
基準 main：`de2bcc5`（PR #267 まで）

## 不具合と修正

1. 旧データの入庫日が `2026/10/28` や `2026/10/28 12:00:00` の場合、費用画面・ダッシュボードには500.01円を計上する一方、分析の期間内整備費・月別費用・費用内訳から漏れる。前後に空白がある日付や、入庫日が空白だけで完了日を使う場合も不一致がある。
2. ダッシュボードのSVG吹き出しは小数を整数に丸め、保存額500.01円が500円と表示される。登録と他画面は小数2桁まで対応している。

修正前に、実際の分析ページ・費用ページ・ダッシュボードのHTML応答を使うテストで再現。新規7件のうち5件で失敗（subTestを含む失敗報告は9件）。修正後に全7件成功。

- 整備費用の日付判定を `vehicle_analysis_dates.maintenance_cost_date` に共通化。既存 `maintenance_facts.cost_date` は同じ公開関数として残し、この共通処理へ委譲する。
- 分析の期間選択・月別費用・日付不明件数と、画面の費目内訳を同じ判定に揃える。
- 分析集計の独立モジュールはFlaskやアプリ状態を読み込まないまま維持する。運行・部品・故障の日付や分析期間入力の許容形式は広げない。
- ダッシュボード吹き出しは保存額の小数2桁までを表示し、不要な末尾ゼロを除く。500.01→500.01、0.50→0.5、0→0。万円表示の軸目盛は変更しない。

データの書換え、DB移行、原本の変更、新しい画面・操作・出力は追加しない。
入庫日が空なら完了日を使う。空でない不正な入庫日を、完了日や請求日で置き換えない。
ゼロ円と不明額、負の調整額、期間・会社・車両・明示された架空資料の除外条件を維持する。

## 回帰テスト

`tests/test_q07_cost_display_consistency.py`：

| テスト | 確認する結果 |
| --- | --- |
| legacy_dates_reach_analysis_kpi_month_and_component_display | ハイフン・スラッシュ・日時・前後の空白付きの既存日付でも、分析KPI・月別・費目合計と費用画面が500.01で一致。費目欄がHTMLへ出る |
| blank_arrival_uses_completion_consistently_without_changing_data | 入庫日None・空文字・空白だけでは、旧形式の完了日を使用。既存値自体は変更しない |
| invalid_nonblank_arrival_is_not_replaced_by_valid_completion | 2月30日の入庫日は不明のまま。期間内は対象外、全期間費用には保持 |
| dashboard_tooltip_preserves_decimal_amount_like_cost_page | 実ダッシュボードのSVG titleが500.01円。小額・ゼロ・負額・小数末尾も保持 |
| dashboard_formatting_does_not_cap_aggregate_at_one_record_limit | 複数記録の合算が単一記録の上限を超えても表示を欠落させない |
| unknown_zero_and_negative_adjustment_keep_distinct_totals | ゼロと不明額の件数を区別し、負の調整額も分析KPI・内訳と一致 |
| period_company_vehicle_and_synthetic_exclusions_still_agree | 指定期間外・他社・別車両・明示された架空資料を混ぜても対象条件を維持 |

各テスト名には `test_` を付ける。一時SQLite DB・架空データを使用。外部AI・実車データ・本番DBは使用しない。

```sh
PYTHONPATH=tests python -m unittest \
  test_q07_cost_display_consistency test_q07_cost_dates test_q07_invoice_lifecycle \
  test_domain_consistency test_document_connections test_invoice_plan_actuals \
  test_vehicle_overview test_vehicle_analysis_summary test_driving_maintenance_context \
  test_vehicle_analysis_service test_analysis_result_consistency test_analysis_read_cache \
  test_application_foundation -v
```

関連200件成功（新規7件＋既存193件）。全件が費用専用テストという意味ではない。別プロセスで分析モジュールの単独importも確認し、Flask・dkss_appが読み込まれないことを検証。既存障害注入テストのforced例外は最終のOKで判定する。

## 対象外・残事項

- 費用専用のCSV/PDF集計出力は、今回確認したルート・画面には見当たらない。請求書原本PDFは集計出力とは区別する。新しい出力機能を作らない。
- 既存AI結果を再生成する変更はしない。今回変更するのは集計の読取と金額表示。保存済みAI結果の更新は現行の管理に従う。
- PostgreSQLの並列更新、実ブラウザ・本番配備は未確認。今回の画面確認はFlaskで描画した実HTML応答。
- PR #269で記録した「追加請求反映後に合計を直接読取訂正すると、後続の請求差し替えが履歴不一致で停止する」制約は、この変更で解消していない。
- Q07全体の完了を意味しない。共有品質改善計画や全体仕様書は古い版で上書きしない。
