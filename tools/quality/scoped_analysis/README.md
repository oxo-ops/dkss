# 少数車両の自動分析受入：オフライン準備

## 今回の完成範囲

既存の全車両ワーカーを有効化せず、会社・車両ID・入力版・モデル・最大呼出し数・最大出力・見積予算を明示した単発受入のガードを合成データで確認する。ワーカー、DB、設定、UIは変更しない。既存分析モジュールに送信しない request 組立て入口を追加し、通常送信と同じ instructions/schema/圧縮を再利用する。

**これは本番実行コマンドではない。** 実DB reader、実AI transport、保存adapterは搭載しない。`synthetic_call` は `SYNTHETIC_` 会社のみ受け付ける。文字列接頭辞は本番データ判定の証明ではなく、試験側の約束である。CI は全ネットワークと子プロセス起動を別途禁止する。外部呼出しのない契約試験を実際の情報隔離や課金抑止の証明に読み替えない。

ガードは1〜5車両の正確な会社・ID・版の組に限定し、未知モデル、request変更、画像・tools等の未対応body、出力/回数/見積超過をcallback前に拒否する。各呼出しの見積額を先に予約し、通信結果不明時は試行全体を停止、予約額を返さず再送しない。結果本文・対象ID・原文はreceiptに格納しない。

メモリー内の単一所有者用であり、並列実行・プロセス再起動・電源断・複数PCからの再実行に耐える台帳ではない。実送信に使う前に、これらのケースを含めた永続予約と照合が必要。単にオブジェクトを作り直して再送してはいけない。

## 費用の根拠と限界

`input_usd_per_million` / `output_usd_per_million` は操作者が確認したモデルのUSD単価であり、出典・基準日を必須とする。入力トークン上限は、完全なrequestの instructions、input、schema、プロトコル分を含む確認済みカウントを将来のadapterが供給する。文字数・UTF-8バイト数をtoken数として代用しない。出力上限には課金対象reasoning/outputを含める必要がある。

見積 microUSD = ceil(入力token上限 × 入力単価 + 最大出力token × 出力単価)。入力は割引無しで計算する。これは上限前提と単価が正しい場合の見積であり、税・為替・APIの請求方法・不明なprovider料金を保証しない。test値の単価やモデル名は架空で、本番見積ではない。

1件の分析で複数回呼び出す場合はpartial/review/finalの**全呼出しごと**に予約が必要。入力変更後に前回カウントを流用しない。中途失敗でも利用料金が発生し得る。既存の1分1ジョブは金額上限ではない。

## 実受入までの最小接続手順（未実装・未承認実行）

1. 本人が利用できる認証経路で、対象会社・代表車両を限定し、現在の原記録を読み取り確認。未加工原文・資格情報をGitHubへ保存しない。
2. 対象の入力payloadと正確な版を既存readerで取得。readerは対象以外を読まないという意味ではない。同型式比較は同一会社の比較対象データを使うため、送信する比較情報の範囲も確認する。ガードに渡す `observed_target` はrequestの自己申告ではなくreaderの検証結果でなければならない。body内容と対象の結びつきもadapterで照合する。
3. 実モデル、単価、完全requestのtoken上限と呼出し計画から見積を作る。対象・送信データ・金額/回数・停止条件を確認してから実行許可を得る。今回その承認取得も実呼出しもしていない。
4. 一意の受入IDを持つ永続台帳へ予約してから、許可対象のAPIへ1回だけ送信。並行/再起動/不明結果時に再送しない。保存adapterは既存claim/lease/原記録再照合を維持し、直書きしない。
5. 同じ車両の通常画面で、根拠・優先度・日時・費用/履歴を照合。実token・所要時間・失敗を安全な集計だけで記録する。AI提案を運行可否の自動判定へ転用しない。
6. 少数受入後にだけ、全体台数・日次量・Web/DB負荷を見て自動化ONを判断する。新しい有料サービスはこの準備に不要。実API利用と既存容量の費用は別。

## 合成検証

`python tests/run_scoped_analysis_pilot_tests.py`

テストはネットワーク・子プロセス起動を audit hook で拒否し、scope/版違い、body変更、モデル/tools/画像、未知token、出力/費用/回数上限、重複、不明結果停止を検証する。本番DB・実API・通知へは接続しない。通常ワーカーや既存合格試験の再実行は不要。


## 追加済み：既存分析への adapter と限定読取の接続点

`prepare_vehicle_karte_analysis_request(payload, model=...)` は既存の1呼出し用bodyを返す。APIキーやWindowsレジストリを読まず、URL送信もしない。2バッチ以上は一部だけ出して合格扱いにせず拒否する。根拠無しも拒否する。`adapter.prepare_scoped_request` は対象会社/車両と**payload全体のdigest**を確認後、そのbodyをローカルtoken counterへ渡し、既存Trialの見積ガードに接続する。queueのfingerprintとこの全体digestは別物である。

合成統合試験では、同じpayloadで通常生成が送信直前に組み立てるbodyとdry bodyが完全一致することを確認（HTTP関数は捕捉して停止、実送信無し）。実プロンプト・JSON schema・引用根拠・wire圧縮を含む。16試験とネットワーク/プロセス禁止を確認したが、実モデルのtoken数、請求額、生成品質は未確認。

### なぜ既存CLI/通常GETをそのまま限定読取に使わないか

- `vehicle_analysis_repository.VehicleAnalysisInputRepository.load` は会社/車両で整備・運行・部品・不具合・定期点検を限定する。部品は親整備も同じ会社/車両で照合する。この既存readerを捨てて独自SQLを増やす必要はない。
- ただし `dkss_app.analysis.get_vehicle_karte_analysis_job_data` は `get_vehicle_karte_peer_comparison` を呼ぶ。後者は同一会社の車両一覧を取得し、同型式/登録年の比較車両の運行・整備等を読む。実行対象5台と比較読取5台は同義ではない。対象だけを承認して既定比較を送信してはいけない。
- `build_vehicle_karte_analysis_payload` にも点検整備リンク・運転日報・点検結果・取込原本参照等の追加読取がある。最初のrepositoryのみをmock/置換しても全読取境界を証明できない。
- 通常GETの `AnalysisReadProjectionService.read` はキャッシュ `put` を行い得る。読取専用試行では通常GETキャッシュ経路もジョブqueue/claim/save経路も流用しない。

### 実データ読取を接続する最小変更案（未実行）

1. `create_app(initialize_database=False)` を利用し、init-db/ワーカーCLIを起動しない。専用の新基盤ではなく既存アプリcontextと既存input serviceを使う。現在のコードでもこのfactory既定は初期化無し。ただし接続先やhookを確認せず本番で起動しない。
2. 認証済み操作者の利用可能会社内で1〜5台を決め、Vehicle検索を会社+ID+非削除に限定。実行台数に加え、同一会社の比較cohortのID集合も明示する。比較無しを選ぶなら、比較不足を明示し、本番と同等の分析精度とは呼ばない。
3. `get_vehicle_karte_peer_comparison` に任意の限定cohortを受け取る入口を追加する場合、車両一覧の取得**前**にSQLのID条件を入れる。後から結果だけ削る実装は不可。既存VehicleAnalysisInputServiceのread_comparison依存へ渡し、payload builderの追加読取も同一transaction内に閉じる。必要なのはこの小さなapp adapterであり、全体ワーカーONや新しいworker/Redisではない。
4. PostgreSQLの明示READ ONLY + REPEATABLE READ transactionで全組立てを行い、成功/失敗ともROLLBACK。キャッシュ更新や暗黙flushがあれば失敗として検出し、書込許可で回避しない。SQLite合成試験だけでPostgreSQL読取専用を保証しない。
5. 読み取ったVehicleの会社/IDとpayload digestをセットで受け取る。任意入力の自己申告を信頼済み読取の証明にしない。生payloadや原文をGitHub/標準出力に残さず、会社・車両数・各資料種別件数・hashのみ監査する。比較cohortも検証済み結果から構成する。
6. 上記をfixture DBで統合し、別会社/別車両混入、比較範囲逸脱、同時更新、書込企図時の拒否を確認後に読取実行へ進む。今回は本番接続禁止のため実読取はしていない。既存の会社境界テストを再利用し、無関係な全体試験を追加しない。

**残る具体的境界**：このPRはSQL transaction/cohort制約を実装したDB readerではない。現在のアプリに対する限定読取adapterの上記変更・合成DB試験と、実モデル向けのtoken counter、実送信前の永続予約が残る。実行時の保存は既存claim/source再検証を外さず、初回は生成結果を保存せず閲覧する受入に限定できる。キャッシュや確認済み優先度の仕組みを別実装で置き換えない。
