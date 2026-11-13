# 少数車両の自動分析受入：オフライン準備

## 今回の完成範囲

既存の全車両ワーカーを有効化せず、会社・車両ID・入力版・モデル・最大呼出し数・最大出力・見積予算を明示した単発受入のガードを合成データで確認する。ワーカー、DB、設定、UIは変更しない。既存分析モジュールに送信しない request 組立て入口を追加し、通常送信と同じ instructions/schema/圧縮を再利用する。

**これは本番実行コマンドではない。** 限定PostgreSQL readerを追加（隔離CI検証対象）。実AI transport、保存adapterは搭載しない。`synthetic_call` は `SYNTHETIC_` 会社のみ受け付ける。文字列接頭辞は本番データ判定の証明ではなく、試験側の約束である。CI は全ネットワークと子プロセス起動を別途禁止する。外部呼出しのない契約試験を実際の情報隔離や課金抑止の証明に読み替えない。

ガードは1〜5車両の正確な会社・ID・版の組に限定し、未知モデル、request変更、画像・tools等の未対応body、出力/回数/見積超過をcallback前に拒否する。各呼出しの見積額を先に予約し、通信結果不明時は試行全体を停止、予約額を返さず再送しない。結果本文・対象ID・原文はreceiptに格納しない。

初期の `Trial` はメモリー内の単一所有者用であり、並列実行・プロセス再起動・電源断・複数PCからの再実行に耐える台帳ではない。後述の `Ledger` は単機の永続予約を追加するが、実送信前の対象/費用/運用境界の照合は引き続き必要。単にオブジェクトを作り直して再送してはいけない。

## 費用の根拠と限界

`input_usd_per_million` / `output_usd_per_million` は操作者が確認したモデルのUSD単価であり、出典・基準日を必須とする。入力トークン上限は、完全なrequestの instructions、input、schema、プロトコル分を含む確認済みカウントを将来のadapterが供給する。文字数・UTF-8バイト数をtoken数として代用しない。出力上限には課金対象reasoning/outputを含める必要がある。

見積 microUSD = ceil(入力token上限 × 入力単価 + 最大出力token × 出力単価)。custom-unverified の単価は未検証。公式profileは下記の保守的予約を使う。これは上限前提と単価が正しい場合の見積であり、税・為替・APIの請求方法・不明なprovider料金を保証しない。test値の単価やモデル名は架空で、本番見積ではない。

1件の分析で複数回呼び出す場合はpartial/review/finalの**全呼出しごと**に予約が必要。入力変更後に前回カウントを流用しない。中途失敗でも利用料金が発生し得る。既存の1分1ジョブは金額上限ではない。

## 実受入までの最小接続手順（実送信は未搭載・未実行）

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

### 実データ読取の接続手順（限定reader実装済み、本番未実行）

1. `create_app(initialize_database=False)` を利用し、init-db/ワーカーCLIを起動しない。専用の新基盤ではなく既存アプリcontextと既存input serviceを使う。現在のコードでもこのfactory既定は初期化無し。ただし接続先やhookを確認せず本番で起動しない。
2. 認証済み操作者の利用可能会社内で1〜5台を決め、Vehicle検索を会社+ID+非削除に限定。実行台数に加え、同一会社の比較cohortのID集合も明示する。比較無しを選ぶなら、比較不足を明示し、本番と同等の分析精度とは呼ばない。
3. `get_vehicle_karte_peer_comparison` に任意の限定cohortを受け取る入口を追加する場合、車両一覧の取得**前**にSQLのID条件を入れる。後から結果だけ削る実装は不可。既存VehicleAnalysisInputServiceのread_comparison依存へ渡し、payload builderの追加読取も同一transaction内に閉じる。必要なのはこの小さなapp adapterであり、全体ワーカーONや新しいworker/Redisではない。
4. PostgreSQLの明示READ ONLY + REPEATABLE READ transactionで全組立てを行い、成功/失敗ともROLLBACK。キャッシュ更新や暗黙flushがあれば失敗として検出し、書込許可で回避しない。SQLite合成試験だけでPostgreSQL読取専用を保証しない。
5. 読み取ったVehicleの会社/IDとpayload digestをセットで受け取る。任意入力の自己申告を信頼済み読取の証明にしない。生payloadや原文をGitHub/標準出力に残さず、会社・車両数・各資料種別件数・hashのみ監査する。比較cohortも検証済み結果から構成する。
6. 上記をfixture DBで統合し、別会社/別車両混入、比較範囲逸脱、同時更新、書込企図時の拒否を確認後に読取実行へ進む。今回は本番接続禁止のため実読取はしていない。既存の会社境界テストを再利用し、無関係な全体試験を追加しない。

**残る具体的境界**：`reader.read_scoped_inputs(ReadScope(company, targets, comparison_ids))` にSQL transaction/cohort制約を実装。呼出し元が認証済みの会社権限を解決する必要がある（この関数は認証routeではない）。fresh session必須、PostgreSQL以外拒否、REPEATABLE READ/READ ONLY、commit/flush/transaction置換拒否、常にrollback。ORM criteriaで全会社列と車両参照列を対象+比較cohortへ制約する。会社共通知識は保持するため「全テーブルを5車両分しか読まない」という保証ではない。任意の悪意あるコードが別connectionでSQLを発行することを防ぐDB権限境界ではない。隔離PostgreSQLで実アプリ組立て・対象外ORM行の非取得・SQLSTATE25006・同時更新snapshotを検証する専用CIを追加した。単機の永続予約は後述のLedgerに実装。実モデル向けtoken counterと実送信の配線が残る。実行時の保存は既存claim/source再検証を外さず、初回は生成結果を保存せず閲覧する受入に限定できる。キャッシュや確認済み優先度の仕組みを別実装で置き換えない。

隔離CI以外のDBには未接続。ローカルで既存の宣言済み依存入り環境を利用できたため、先にFlask欠落で止まったprompt/schema影響試験9件もネットワーク禁止下で成功。ローカルにPostgreSQLサーバが無いためPG部分の成否は専用CIで判定する。

## 送信前の永続予約と保存経路（非本番検証）

既存 `VehicleAnalysisJobRepository` の lease/token、input hash、保存前の車両行ロック・確認済み根拠再照合は結果の所有権と鮮度を守る。一方、lease期限切れ後の再試行でAPI料金が二重発生しない保証はない。そこで**承認された単発受入だけ**のローカルSQLite台帳 `ledger.Ledger` を追加した。新しいRenderサービス、キュー、Redis、本番テーブルは不要。

- `Ledger.create(path, policy)` は新規fileのみ（既存を上書きしない）。POSIXローカル永続ディスクに0600で作成し、SQLite FULL synchronous、directory fsyncを行う。現在Windows/network drive/multi-hostは検証外。
- 再開は `Ledger(path, policy)` のみ。存在しない・壊れた・別policyのfileを自動再作成しない。同一object利用中のfile置換も拒否。新規instanceで同policyの空台帳に差し替えられた場合は検出できない。承認試行の台帳パスを固定して保全する必要がある。**環境消失時に別fileを作って再送しない**。台帳消失は照合が済むまで停止条件。
- `reserve_exact_body(approved_request, actual_body_json, observed_target=...)` は承認済みの完全な送信JSONが変わっていないことを先に確認。入力計数も同じJSONに対応する必要がある。通常HTTPとdry adapterのシリアライズを一致させた。
- scope/model/token/費用を既存Trialで検証し、BEGIN IMMEDIATE内で累積予約額・呼出し数・request重複を確認。予約COMMITが戻ってからだけtransportへ進む。同時に2所有者が試みても1予約だけ。
- reservedのまま再開／uncertainは試行全体を停止。自動retry・予約返却はしない。returnedも利用額を減らさず、同requestを再送しない。台帳はraw本文・秘密値・応答本文を保存しない。
- returnedは**応答が戻ったという記録だけ**で、モデル応答の妥当性・アプリ保存完了を意味しない。保存に失敗しても自動再生成せず、既存結果と台帳を照合する。ハードウェア電源断、悪意あるfile改ざん、別ホストや別台帳での二重実行、provider側の厳密な一回課金は保証しない。

合成試験は永続化後callback、再open後の重複拒否、予約後未完了で再openした場合の全停止、timeout記録、2接続競合、累積上限、policy違い、file置換、完全body違いを確認する。実プロセスkill・停電試験ではなく、未完了予約を残した再openでcrash windowを模擬する。

### 既存保存・通常画面の連携証拠と境界

`test_scoped_analysis_saved_flow.py` は既存の実fixtureを利用し、進行確認POST→通常入力→既存job claim→完全bodyに対する永続予約→合成HTTP応答→既存保存→通常analysis APIの65点→dashboard同一proposal ID/65点→overview/analysis通常ページを検証。再jobを試みても台帳が二度目のtransport完了前に拒否し、保存済み結果はbyte一致で残る。既存のlease/source/入力世代の検証を置き換えていない。

**限定comparisonのpilot結果を、そのまま通常画面の完成結果として保存する機能は追加していない。** 上記保存試験は通常入力そのものと承認bodyが一致する場合の接続である。限定cohortで通常入力が変わるなら結果は別扱いにし、通常保存には同じ対象・入力・比較範囲の再検証が必要。今のreader→dry requestは読取受入用で、既存jobを本番で呼ぶ承認/入口ではない。

実課金用transportは未搭載。実モデルに対応した正確なtoken上限・単価・対象/比較範囲・予算承認が揃って初めて実送信の配線を検討する。通知/OCRなど別の課金呼出しをこの台帳が一括抑止するものではない。実受入でも全体自動分析フラグは変更しない。


## 2026-11-12 公式価格 profile（本番モデルの指定ではない）

公式確認: [モデル](https://developers.openai.com/api/docs/models/gpt-6.1-sol)、[価格](https://developers.openai.com/api/docs/pricing)、[キャッシュ](https://developers.openai.com/api/docs/guides/prompt-caching)、[service_tier](https://developers.openai.com/api/reference/resources/responses/methods/create)。

`SOL_STANDARD_30M` は gpt-6.1-sol / 通常 api.openai.com Responses endpoint / Standard / 既定30mに限定。入力$2・出力$10/百万tokenが基準だが、入力全体を30m書込総単価$2.50で予約する。$2への加算ではなく置換で、キャッシュ割引は予算に見込まない。1,000入力+6,000出力は62,500microUSD。実測請求ではない。

入力272,000tokenまでは短context、272,001以上は拒否。公式長contextは全requestの入力/キャッシュ2倍・出力1.5倍だが今回は非対応。出力128,000超も拒否。12h、Fast、Flex/Batch、Ultrafast、地域/FedRAMP endpointはこのprofile非対応。地域/FedRAMP10%割増を黙って通常単価にしない。

送信bodyのservice_tierは明示的なdefaultを要求し、未指定/autoは拒否（project既定がStandardとは限らない）。任意のprompt_cache_options追加も拒否し既定30mに固定。既存dry/通常生成bodyにはservice_tierがないため、このprofileでは現在のadapter出力は拒否される。通常生成を勝手に変更せず、将来の限定transportで明示tierを加えた最終bodyを再カウント・再hashして予約する必要がある。endpointフィールドは予定先の契約であり、実接続先の証明ではない。live transportは未搭載。

単価は確認日のsnapshotで、将来価格や本番モデル/請求条件を自動保証しない。既存台帳はpolicy digestが変われば拒否する。台帳を新規作成し直して累積予算を消してはいけない。今回の変更はGitHub正式編集で保存しCI検証、ローカル実行環境は利用不可のためローカル合格とは報告しない。

### Final wire boundary (synthetic only)

`final_gate.synthetic_final_call` exercises the final serialized UTF-8 bytes,
exact Responses URL, approved model / `service_tier=default`, output limit,
body hash, full-body input recount and durable reservation in one path. The fake
transport sees the same immutable `Envelope` only after reservation commits.
Failures after that point remain uncertain and block retries. Endpoint variants,
changed bytes, changed count source and a count above the approved bound are
rejected before reservation. Real company targets are always rejected.

This is not a live sender, tokenizer attestation, provider billing guarantee or
normal full-analysis replacement. The injected counter and callback remain
synthetic test seams. The existing offline builder deliberately does not add a
service tier implicitly: a future authorized live pilot must explicitly prepare
its final body, count/hash that body and bind the approved endpoint and token
counting method before reserving. Live headers/authentication, actual endpoint
configuration, audited provider-compatible token bounds and HTTP behavior
(including no redirects/retries) remain unverified. No production enable switch
or real API call was added.


### Mock HTTP/count integration candidate

`http_candidate.SyntheticHTTPTrial` now connects the existing final gate and
ledger to a count-response parser and HTTP request/response serializer. It has
no CLI, app hook, environment/credential reader or default network connection.
The caller must inject a mock connection factory; tests deny all network and
process creation. Literal synthetic authorization is not a usable credential.
One synthetic target and one generation are allowed. The helper fixes hostname,
paths, timeout and verified TLS context; non-200 (including redirect/429), bad
count and oversized reply fail without redirect/retry. Generation failures leave
the existing reservation uncertain. Count failure stops the object, but count
attempts are not durably reserved across new objects; this is not live approval.

The count request carries model, instructions, input, text/schema and reasoning
from the final body, matching the [official count API](https://developers.openai.com/api/reference/resources/responses/subresources/input_tokens/methods/count).
The integer response is bound to final request bytes before the existing gate;
mock count values are not measured production tokens or verified provider bills.
A future real trial needs explicit permission for this additional count request's
data disclosure as well as the generation. No real count API was called.

The saved-flow test now exercises this same HTTP helper with the original
claim/save/result API/dashboard flow and verifies a replay makes no more HTTP
calls. That test uses the pre-existing synthetic company A/custom-price fixture;
it does not prove the whole SyntheticHTTPTrial/final_gate to production save
path. No scoped pilot result is installed as a complete ordinary analysis.
Local network-denied tests cover HTTP/count (9) and existing final gate (8).
The full saved-flow test is subject to the exact new-head CI result, not claimed
from local syntax validation. Real target/cohort selection, model verification,
credentials, count/generation authorization and live scoped job integration remain.

## Explicit job bridge candidate (not deployed or authorized to execute)
`ScopedJobBridge` can be passed explicitly as `analysis_adapter` to one existing
`run_vehicle_karte_analysis_job` invocation. No route, CLI, worker flag, environment
switch, or startup call is added. The ordinary service still owns claim/lease,
confirmation reconciliation and fenced save. The bridge checks state company/ID
before claim, rebuilds the **ordinary complete** input, rejects changed revisions
or acceptance-limited comparison, and matches final request bytes to the counted,
approved request. It does not promote a limited peer result to a normal result.

The single-call generator seam uses no global monkeypatch or credential lookup.
It adds Standard tier only to this explicit bridge path; ordinary generation is
unchanged. A durable reservation commits before the injected transport. An
uncertain response consumes the reservation and must not be retried/refunded.
`ResponsesHTTPS` supplies a fixed verified-TLS destination, one attempt, bounded
response, no proxy/redirect/retry, no provider error-body logging, and no automatic
credential acquisition. It is never called by the module or tests with real HTTP.

Prerequisites remain **unfulfilled**: verified live model/settings; authorized
company/vehicle and complete ordinary comparison input; actual full-input token
count tied to the exact request; approved disclosure and budget; fixed single-host
ledger and recovery owner. `COUNT_SOURCE` is an evidence label, not proof that
counting or approval occurred. Token counting itself can disclose input and is
not performed by this bridge. No production invocation is provided. The local
ledger still is not provider exactly-once billing protection.

### Persistent job hold (required schema migration; not applied)
The bridge commits `vehicle_karte_analysis.pilot_hold` before claiming the job.
A normal repository claim requires NULL; only that explicit pilot repository
uses the matching hold. Worker selection also excludes held jobs. The hold is
independent of status, retry time, lease and input hash: successful save, failure,
process death/lease expiry, source deletion and requeue never clear it. A new
pilot object cannot implicitly resume a held job. No automatic release function
is provided. Reconcile provider billing, durable ledger and saved result, then
obtain explicit operator release before clearing a specific hold.

This adds a nullable column, so the additive SQL migration in `migrations/` must
be reviewed/applied before this code is deployed. **Do not run a trial with old
workers/code present**: stop/drain old execution first, migrate, deploy all job
callers, then verify hold enforcement. Old binaries cannot enforce a new hold.
No migration, deployment, hold, or release has been applied to production here.

### Normal preflight and durable count candidate
See `PREEXECUTION.md` for the authorization, complete ordinary comparison scope,
company maintenance knowledge, separate count/generation budgets and rollout
sequence. `preflight.read_normal_input` is PostgreSQL READ ONLY/fresh-session only
and does not substitute the earlier scoped reader. `count_material` constructs
the exact normal request/count bodies offline. `count_transport` adds an explicit
one-count transport behind a separate durable reservation, with no credential
lookup or automatic app hook. Only injected synthetic transports have run here.
These additions do not mean provider counting, input disclosure authorization,
spending authorization, or production migration/execution has occurred.
