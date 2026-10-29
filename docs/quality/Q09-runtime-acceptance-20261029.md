# Q09 開発基盤と運用構成の確認

調査基準はmain `288261d0549d7660466f4edc7bd7b30ec9e640a6`。Q05の開発・最終統合受入完了を保持し、別作業として確認した。品質改善計画「Q09 開発基盤と運用構成」の第三者起動、環境分離、変更履歴と失敗時手順の追跡を対象とする。

## 完了済みと未検証の区分

| 項目 | 現状・根拠 | 今回の扱い |
|---|---|---|
| factory/import分離 | mainの`b34864e`、`test_application_foundation.py`。importだけでDBに接続/初期化しない | 再実装しない。新しい依存環境で代表試験を確認 |
| 永続OCRキュー・タイムアウト対策 | mainの`cc0c563`、#245、`document_import_queue.md`。受付/lease/再試行の既存試験あり | 逐次読取・所有権等の仕様は変更しない |
| 実worker停止/再開・復旧 | Q11資料に通常停止・強制停止・lease失効等4ケース成功の既存記録 | Q11の復旧リハーサルを再実行しない |
| 新環境の導入・起動・設定・停止の入口 | root READMEなし。構造資料に依存導入・設定一覧・停止・CI切分けが不足 | READMEと運用手順を追加。Windowsの新規環境で確認 |
| 起動時DB変更の説明 | factoryとGunicornを混同すると、起動だけでDB無変更と誤読する。`gunicorn.conf.py`は2種の初期化後にOCR開始 | 構造/OCR資料へ現在の範囲を追記。hookそのものは変更しない |
| 障害ログ | OCRループとlease heartbeatの`logger.exception`が例外本文を出力 | 架空秘密値で各1件失敗を先に再現し、段階/例外種別のログへ最小修正 |
| 依存更新・CodeQL・依存監査 | Dependabot、regression、CodeQL、pip-auditの既存workflowあり。新しい基盤は不要 | 実行条件・失敗stepの追跡手順を文書化。既存CIを利用 |
| DB変更管理 | 専用CLIと表/列/索引検査はあるが共通版台帳はない。init-dbには複数commitあり | 索引と部分適用時の扱いを文書化。新移行基盤は導入しない |
| 6処理・388件・ハーネス | 移行主管が別作業で検証中。Q09開始時の記録ではハーネス修正後のDB検証は未完了 | 実行・改修・保護DB接続を行わない。最新完了報告を主管から受領する |
| #313・#317等の移行統合 | main反映と既存手順/対象版の一致は別。版ごとに適用範囲が異なる | 各資料とCLIの入口を追跡し、主管の順序を独断で再定義しない |
| 配備構成と運用責任者 | 実際のWeb/専用OCR台数、プロセス管理、ログ保管/通知先はrepoだけでは確定しない | 運用主管待ち。実サービスへ接続して調査しない |

既存根拠は`docs/application_architecture.md`、`docs/document_import_queue.md`、`docs/quality/Q11-operational-readiness-20261028.md`、各Q02/Q03/Q04/Q08資料とworkflow。GitHub連携の検索ではPRが取得されなかったため、その結果を担当不在の根拠にせず、通常のPR一覧画面と各PRを追加照合した。オープン#327/#326/#325はQ03/Q08の本人境界、#324はQ12、#323は運転分析、#320はWord資料、#318は旧Q05ブランチだった。各headをfetchして変更ファイルを比較し、今回8ファイルとの重複はなかった。#320は複数merge-baseの警告が出たため、単一の差分を全履歴の保証としない。移行主管の作業記録も読取照合した。品質改善計画Word、仕様書、Q05成果、他担当worktreeは変更していない。

## 修正と再現

製品変更は`document_import_worker.py`のループ例外と`document_import_queue.py`のlease更新例外の2ハンドラーだけ。`logger.exception`を段階マーカー＋`error_type`へ変更した。後者は既存job IDも保持する。SQL引数・接続情報を含み得る例外本文/tracebackを出さない。

`tests/test_q09_worker_diagnostics.py`に2件追加した。修正前はそれぞれ架空秘密値がログへ出て失敗した。修正後は次のiteration継続・rollbackと、実heartbeatスレッドの障害後もモックOCR結果が保存されることを確認した。heartbeat試験は待機を短縮するが、実スレッド・既存処理を使用し、外部AIには接続しない。既存試験の削除・期待値緩和、lease値・会社境界・権限・集計の変更はない。

新しい`README.md`から`docs/runtime_operations.md`へ接続し、新規SQLiteに限定したPowerShell手順、Windows/Linuxの違い、組込と明示的worker、設定表、停止とtimeoutの違い、CI調査、DB変更の調査索引をまとめた。既存2資料の歴史的検証結果は削除せず、現行起動の補足だけを加えた。

## 今回の検証結果

新規`q09-venv`にPython 3.12と現行`requirements.txt`を導入し成功。既存Q05仮想環境を新環境の証拠には使わない。依存解決の一部はpipのキャッシュ利用だが、venvは新規でsystem-site-packagesなし。`pip check`も成功した。

新規一時SQLiteだけで次の5項目が成功した。

1. 依存整合性。
2. 新規空DBの`flask init-db`と完了マーカー。
3. 明示的OCRコマンドの登録。
4. loopback Webの`GET /login` HTTP200とフォーム描画。
5. 実組込OCRの空キュー起動・停止、thread終了。

これは既存DBへの6移行処理実行ではない。新規DBは終了後に削除し、Web/workerも停止した。プロセス環境はOS基本変数（WindowsのSYSTEMROOT等を含む）と架空設定に限定し、既存DB/S3/外部API設定を引き継がない。

修正後の関連試験は新環境で29件成功、43.747秒、スキップなし。
`test_q09_worker_diagnostics` 2件、`test_application_foundation`、`test_document_import_queue`を実行した。既存受入全体や移行主管の388件を再実行したものではない。

ローカル証跡はこの作業のoutputs配下に保持する。

- `Q09-dependency-install-20261029.log`
- `Q09-fresh-smoke-20261029.json`
- `Q09-worker-before-20261029.log`（ループの修正前失敗、架空値のみ）
- `Q09-heartbeat-before-20261029.log`（lease更新の修正前失敗、架空値のみ）
- `Q09-related-after-20261029.log`

Linuxで現在版のGunicorn/専用OCRを実起動した結果とは区別する。既存の過去Gunicorn試験・Q11停止受入は再利用し、運用版のプロセス管理/実停止時間は運用主管の証跡待ちとする。外部AI/SMTP/S3の実接続、既存移行検証DB、本番接続、デプロイは行っていない。

## 残工数と判断待ち

初回報告時点（head `ff6142a`）では、独立ブランチ`fix/q09-runtime-handover-20261029`をpush済みで、GitHub連携APIのPR作成は403、通常ブラウザも未ログインだったため、PR未作成・CI未確認と報告した。これはその時点の記録として保持する。認証情報の探索・再認証は行っていない。

その後、利用者が作成済みの[既存PR #329](https://github.com/oxo-ops/dkss/pull/329)を確認した。head `ff6142a37fd1576dd2892911a4fdb4c800d9366a`の全8チェック（regression、CodeQL、Analyze Python、pip-audit、identity、postgres 2件、browser）が成功した。全体回帰は[当該run](https://github.com/oxo-ops/dkss/actions/runs/40815558240/job/123255652245)で成功を確認し、失敗の再実行は行っていない。

仕上げ作業ではmain `15a197142e3d1b30197f75cfd05f156aaf6a2c0e`を旧ブランチへ通常mergeしたが、その間に#329が旧head `ff6142a`でmainへマージされた（merge commit `1741c64426f75f682a331f99b9249a45caf7a612`）。追加コミット`eb0a99017b2f1c44afde26328246a759daae93f7`は#329のマージ内容に含まれない。旧ブランチ・同コミット・証跡を保持している。

利用者の指示で、最新main `1741c64426f75f682a331f99b9249a45caf7a612`から後続ブランチ`test/q09-linux-runtime-followup-20261029`を作成し、未反映の本資料・運用索引・Linux試験の3ファイルだけを取り込んだ。README・OCR製品修正・既存Q09診断試験は差分に含めず、#329を再オープンしない。#327のCSV移行入口、旧NULL保留、旧版への切戻し時のCSV私有経路停止条件を運用索引へ追記した。移行や追加移行受入は実行していない。

現在版Linuxの実Gunicornと明示OCR起動の証拠不足を補うため、`test_q09_linux_runtime.py`を既存回帰CIへ自動収集される1件として追加した。新規一時SQLite、非loopback接続の遮断、既定gthread/1/4、ログインHTTP200、組込/明示OCR heartbeat、通常SIGTERMの終了コード0を確認する。実配備時間や台数の測定ではなく、Q11の強制停止/復旧・lease失効試験も再実施しない。Windowsの局所確認は既存Q09 2件成功・Linux専用1件skip。追加後headのLinux実行結果と必要チェックは後続PRの新しいheadで判定し、旧#329の成功を転用しない。後続PRの最終番号・head・CI証跡は引継ぎ報告へ記録する。

基準mainを構成する#322の最終head `30f33a3329a6b422162ba13887b2799a07c7ec6e`ではregression、CodeQL、Analyze Python、pip-audit成功をGitHubで確認した。これは今回のQ09 headの成功を意味しない。依存監査/CodeQLの既存構成は利用可能だが、Q09変更のCI合格判定はPR作成後に行う。

初回のQ09残工数2〜4人時は当時の見積として保持する。#331の最終head `3454ad9d0f88d265b891fd9f0d465f6b049a1e1d`は全4チェック成功、Linux追加1件もskipではなく成功し、マージ済みである。今回、起動・移行・既存試験を再実行していない。

現行のQ09状態は**確認済み範囲の整備完了／実環境の運用証拠待ち**。残1〜2人時は、資料提供後の運用構成・主管証跡の照合と引継ぎ確定の枠であり、確認済み開発の未完了工数ではない。実台数・停止管理・再起動policy・ログ保管/障害通知の担当と証跡は未確認のまま保持する。

Q04入口は、担当共有の契約表v1（`Q04-entry-contract-1741c64-20261029/01-contract.txt`、`02-owner-files.txt`）と2026-10-29の指示により、**契約案確定・実装指示済み**である。主管所有の小さなライブラリ入口とQ04の薄いアダプタ/同一接続フックを既存移行本体へ接続する方針であり、実装・隔離受入・本番適用が完了したとの判定ではない。本番値・担当者/実行job/保存先の指名・承認は別の前提として残る。

Q04入口の旧9〜14人時は契約時の見積へ置換し、加算しない。Q04純増4〜7人時と主管4〜6人時を含む計画総枠が8〜13人時であり、4〜7と8〜13も加算しない。この移行入口の工数をQ09残1〜2人時へ重複計上せず、主管の既存計画へ集約する。主管所有資料は本訂正で変更しない。移行主管の6処理/388件・追加受入、Q11復旧、本番作業は再実施しない。

共通の移行版台帳や推移依存の完全lockを追加するかは、現状の手順で不足が残る場合の判断事項であり今回の前提ではない。Q09全体・本番運用を完了と断定しない。Q05は完了のまま保持する。
