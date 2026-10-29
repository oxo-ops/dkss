# システム仕様書Word 整合追補報告（2026年10月29日）

## 判定と成果物

対象はシステム仕様書のみ。v0.25基準の前回確認用Wordを局所更新した。正本の認定、正式版番号・承認日の付与は行っていない。品質改善Wordは改訂保留を維持し、Excel・製品コード・DB・テストは変更していない。

- 出力Word：`C:\Users\takah\Documents\Codex\2026-10-28\dx-oxo-ops-dkss-q02-q03\outputs\輸送版DX_システム仕様書_v0.25基準_整合追補_確認用_20261029.docx`
- SHA-256：`213224216beb487033a9e98518c8258034f4bec4db75982f1edf4d4dc4d21462`
- 保存した前回Word：`C:\Users\takah\Documents\Codex\2026-10-28\dx-oxo-ops-dkss-q02-q03\outputs\輸送版DX_システム仕様書_v0.25基準_確認用改訂_20261028.docx`
- 前回Word SHA-256：`2b90878587ed5b209640a1cb3e529221fd44fd1db735d0de7999f8f22555a7e6`
- 添付v0.25原本：`C:\Users\takah\Downloads\輸送版DX_システム仕様書_v0.25_20261028.docx`
- 添付原本 SHA-256：`d10255a317481e64654e37bd3e1f322a08cfad48b06ad6530a7b59955831b365`
- 照合基準：2026年10月29日11:04 JST、main `288261d0549d7660466f4edc7bd7b30ec9e640a6`。12:15 JSTの再fetchでも同一SHAを確認。
- 作業ブランチ：`docs/spec-alignment-20261029`。リポジトリへは本報告書だけを保存する。Word実物は上記ローカル出力で管理する。

PostgreSQL移行は、架空データを用いたローカルのSQLite／実PostgreSQLエンジンでの隔離検証段階。本番移行・本番ログイン復旧・業務受入の完了とは記載していない。

## 確認した資料

- [PR #279](https://github.com/oxo-ops/dkss/pull/279)のv0.18／v0.25比較、仕様書整合性確認、章別変更案。v0.18を保持したv0.25を比較基準とし、正本判断は保留。
- 前回確認用システム仕様書Wordの全19章、改訂履歴、参照S01〜S73。今回参照S74〜S80を追加。
- `docs/quality/`のQ03承認人物参照・フォーム世代、Q04マスタ世代・read-only診断、Q02日時幅・所有者・ロック順、Q05安全開始日・受入、Q08本人履歴、運転分析No.10、Q11復旧の技術記録。
- 上記固定mainの権限・取込・通知・マスタ世代・明示移行・車両点検／費用履歴コードと対象試験、各マージ済みPR本文と最終headのチェック状態。
- Render担当のローカル隔離移行報告と、利用者から提供された10月29日の本番確認報告。本番の追加調査・操作は本作業では実施していない。

## 採用根拠と状態区分

A（確定業務方針）は既存決定事項および一次資料に記録された利用者指示だけに限定した。未来の無事故開始日の事前登録・開始予定表示は#292/#312の記録、旧日報の氏名だけによる自動公開を保留する方針は#311の10月29日利用者指示に基づく。後者は旧S66方針を時点区分して保持し、現在の判定をS79へ接続した。

B（実装・試験）は次のマージ済みPRの対象範囲に限定する。各最終headのチェックは11:04 JST時点で全てsuccess。チェック成功はローカル対象試験の証拠であり、本番移行・総合受入を意味しない。

|対象|マージ済みPR|Wordへの反映・限界|
|---|---|---|
|本人・通知の世代|#285・#283・#297|UUIDによる会社／本人照合、旧証跡の保留。本人復元機能・実配信受入は別|
|フォーム世代|#314|人物選択の署名・操作時本人／権限再確認。既知競合の409とrollback。全経路保護の主張はしない|
|マスタ|#295・#304・#317|索引検査・read-only診断・5マスタ世代。旧ID再利用による対象競合を修正、全複合FKや本番適用は未保証|
|日付|#292・#298・#312|未来開始日の明示方針、初回集計競合対策。旧時刻帯根拠不明は保留|
|OCR・日時|#307・#313・#321|日時幅／保存、所有者UUID、会社ロック昇格回避と排他取得後再読込。外部OCR精度・課金一回保証は未受入|
|点検・日報|#310・#311|別UUIDへの候補／訂正権限の継承防止、本人証跡不明の日報閲覧保留。根拠付き再承認・本番影響確認は必要|
|表示|#309・#315・#319|既存認可を維持した表示経路改善。先行fit後に到着するPDFページの表示対策を含む。効果の本番負荷・実機保証なし|
|運用支援|#286|復旧支援資産のmain反映。運用責任者・環境・RPO/RTOによる業務受入は未完了|

11:04 JST時点の未マージ#318・#320は独立した実装済み成果に含めていない。#322はマージ済みで、品質改善Wordの既存報告として保持する。本報告はその後継品質報告や重複更新ではない。

## 章別変更一覧

|章|名称|今回の扱い|
|---|---|---|
|01|文書概要|照合基準とA/B/C区分、旧証跡と未マージ除外を明記|
|02|システム概要|起動時初期化と明示DB移行、ローカル検証と本番適用の境界|
|03|利用者と権限|本人UUID・旧権限保留・フォーム世代と操作時権限再確認|
|04|業務仕様|照合のみ。既存業務ルールを維持し直接編集なし|
|05|機能一覧|照合のみ。既存F番号・別紙参照を維持し直接編集なし|
|06|機能仕様|5マスタ世代、未来起算日、OCR所有者・ロック順、日報本人認可|
|07|画面仕様|マージ済み画面改善と表示性能の適用範囲、負荷・実機未受入を分離|
|08|データ仕様|モデル上のUUID／世代／日時列と既存DBの適用状況を分離|
|09|ファイル仕様|未登録原本の本人所有と登録済み会社共有原本の既存認可を区別|
|10|外部連携仕様|非同期公開時の本人再確認、実外部配信・取消／課金保証の未確認|
|11|通知仕様|通知・Push・履歴のアカウント世代と旧設定の再確認|
|12|帳票仕様|UUID未確定時の本人CSV／PDF保留と旧表示名・履歴の保持|
|13|非機能要件|ローカルPG検証と本番負荷・SLA・RPO/RTOの未受入を分離|
|14|セキュリティ|署名と認可を区別し、ロック／世代保護の対象経路を限定|
|15|障害時仕様|復旧支援資産と運用受入、バックアップ対象・旧版再開条件を分離|
|16|運用と保守|各明示移行／readinessと実環境適用の境界、Q04 CLIの非本番制限|
|17|制約と前提|ローカル検証・実環境未適用、未マージPRを成果に含めない前提|
|18|受入条件|M06/M07未解決、本人復元等未決、K31/K48/K50/K52をS79へ整合|
|19|改訂履歴|正式版・承認日を変えず確認用追補の時点と範囲を追加|

表紙の照合基準・旧改訂概要、参照S74〜S80も更新。計53箇所（既存段落34箇所の局所編集と追記）。旧S66の自動公開方針は削除せず「旧方針／2026年10月28日時点」と区分し、本文・データ・帳票・受入条件の矛盾を解消した。既存F/U/K番号・別紙参照を維持。

## 未解決・未受入

- M06：車検と12か月点検の独立原則に対し、現行正規化に`vehicle_inspection → 12month`が残る。
- M07：請求金額の合計訂正後、請求差替えと反映済み履歴の整合が未解決。保護的拒否を正式な訂正業務仕様として追認しない。今回main差分で当該解決の根拠は確認できない。
- 旧本人の証拠付き復元、旧通知／承認の保留解除、代理実施者、パトロール等の未対象人物選択、旧オフセットなし日時、リスク基準は判断・確認待ち。
- Q04のマスタ世代移行CLIは現行技術資料で非本番コピー限定。本番の実行順序・承認済み移行手順を本書から推定しない。
- Renderの本番SHA18ae141b、Auto-Deploy Off、DB/schema確認、本人UUID関連列・OCR所有者列欠落、checklist_event.created_at VARCHAR(30)、PITR過去3日、旧エクスポート10月27日16:50は「利用者提供の本番確認結果」としてローカル隔離検証と分離。最新エクスポート・隔離復元・本番DB移行・ログイン復旧の完了証拠は未確認。
- 実S3・実容量・旧版の画面／登録／添付・配備条件下のワーカー停止再開、業務RPO/RTO・責任者・承認条件による本番受入は未実施。
- 正式な正本承認と別紙1〜5の実物を伴う整合確認は残作業。取得していない別紙を推測で更新していない。

## 保存・表示検証

- Word 16の読取専用PDF出力で70ページを確認し、全ページを画像表示で確認。最終K31修正は52ページのみの画像差分で、当該ページも再確認した。余白外文字0、空白ページ0。元文書にある明示改ページ・短いページは維持。
- 19章の見出し順序、2表のXML、2図、既存改訂履歴を保持。非編集対象要素は原順序で一致。`word/document.xml`以外の24パッケージ部品はバイト単位一致し、書式・画像・関係定義を維持。
- 前回Wordと添付原本のSHA-256一致を再確認。品質改善Wordの直近保存実物もSHA-256一致（`bd1ca960ef87da9222e9f8670877e1d3d48f5a9d2928e6e753b5afdce4803349`）。
- 文書のみの変更のため製品テストは再実行していない。採用した試験結果は各PRの対象版に帰属させ、件数・工数・詳細進捗をシステム仕様書へ転記していない。

## PR最終head・チェック証跡

|PR|最終head|確認したチェック|
|---|---|---|
|[#283](https://github.com/oxo-ops/dkss/pull/283)|`2236a5786a15af902df65f0b7c715da12cb25b37`|全success：[CodeQL](https://github.com/oxo-ops/dkss/runs/123139288011) / [postgres-identity](https://github.com/oxo-ops/dkss/actions/runs/40779948986/job/123138787978) / [postgres-masters](https://github.com/oxo-ops/dkss/actions/runs/40779948656/job/123138787933) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40779948528/job/123138787709) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40779948626/job/123138787675) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40779948702/job/123138787599) / [postgres-mfa](https://github.com/oxo-ops/dkss/actions/runs/40779948667/job/123138787360) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40779948520/job/123138787148)|
|[#285](https://github.com/oxo-ops/dkss/pull/285)|`73fa933d1f0ef2c66142e1ecfaefbfbbe1449220`|全success：[CodeQL](https://github.com/oxo-ops/dkss/runs/122803108853) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40684322000/job/122802691489) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40684321931/job/122802691457) / [postgres-masters](https://github.com/oxo-ops/dkss/actions/runs/40684321864/job/122802691257) / [postgres-mfa](https://github.com/oxo-ops/dkss/actions/runs/40684321901/job/122802690869) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40684321859/job/122802690850) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40684321815/job/122802690519)|
|[#286](https://github.com/oxo-ops/dkss/pull/286)|`06143235d99c938642d2f98dd62df83cc2547f7f`|全success：[CodeQL](https://github.com/oxo-ops/dkss/runs/122796515044) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40682383899/job/122796074955) / [readiness](https://github.com/oxo-ops/dkss/actions/runs/40682384086/job/122796074727) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40682383960/job/122796074465) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40682383853/job/122796074364) / [recovery](https://github.com/oxo-ops/dkss/actions/runs/40682383885/job/122796074055)|
|[#292](https://github.com/oxo-ops/dkss/pull/292)|`92b5f05b3befe69b950dd55f96305eb60757eee1`|全success：[CodeQL](https://github.com/oxo-ops/dkss/runs/123156799029) / [postgres-masters](https://github.com/oxo-ops/dkss/actions/runs/40785175975/job/123156441258) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40785175971/job/123156440849) / [postgres-dates](https://github.com/oxo-ops/dkss/actions/runs/40785175925/job/123156440426) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40785175928/job/123156440378) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40785175841/job/123156440336) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40785175839/job/123156440109)|
|[#294](https://github.com/oxo-ops/dkss/pull/294)|`5439d8ade9a5219e7dbf8189a11f50ed7cbdc46c`|全success：[CodeQL](https://github.com/oxo-ops/dkss/runs/123177522364) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40791377264/job/123177150915) / [postgres-mfa](https://github.com/oxo-ops/dkss/actions/runs/40791377160/job/123177150552) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40791377154/job/123177150102) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40791377212/job/123177150086) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40791377197/job/123177150039) / [postgres-identity](https://github.com/oxo-ops/dkss/actions/runs/40791377211/job/123177150003) / [postgres-masters](https://github.com/oxo-ops/dkss/actions/runs/40791377183/job/123177149988) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40791377198/job/123177149883) / [browser](https://github.com/oxo-ops/dkss/actions/runs/40791377154/job/123177149788) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40791377158/job/123177149721) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40791377159/job/123177149611)|
|[#295](https://github.com/oxo-ops/dkss/pull/295)|`54b4e1fd72e14637d67090e0fc5a19b0d41884b6`|全success：[CodeQL](https://github.com/oxo-ops/dkss/runs/123133830780) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40778358025/job/123133396727) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40778357854/job/123133396664) / [postgres-masters](https://github.com/oxo-ops/dkss/actions/runs/40778357933/job/123133396650) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40778357842/job/123133396620) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40778357852/job/123133396488) / [postgres-masters](https://github.com/oxo-ops/dkss/actions/runs/40778350753/job/123133372074)|
|[#297](https://github.com/oxo-ops/dkss/pull/297)|`87c6a92e29c7ccb2a0620a280d5766fbf900fad3`|全success：[CodeQL](https://github.com/oxo-ops/dkss/runs/123127663282) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40776585858/job/123127356772) / [postgres-mfa](https://github.com/oxo-ops/dkss/actions/runs/40776585665/job/123127356582) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40776585676/job/123127356503) / [postgres-masters](https://github.com/oxo-ops/dkss/actions/runs/40776585703/job/123127356363) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40776585672/job/123127355880) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40776585522/job/123127354945)|
|[#298](https://github.com/oxo-ops/dkss/pull/298)|`990050a99dad527299fa860df6235531e9727ade`|全success：[CodeQL](https://github.com/oxo-ops/dkss/runs/123138168578) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40779669648/job/123137838697) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40779669731/job/123137838499) / [postgres-mfa](https://github.com/oxo-ops/dkss/actions/runs/40779669848/job/123137838450) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40779669834/job/123137838309) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40779669732/job/123137838168) / [usage-summary](https://github.com/oxo-ops/dkss/actions/runs/40779669783/job/123137837853)|
|[#304](https://github.com/oxo-ops/dkss/pull/304)|`c0bb90507391b8b752a52862b34ffe99c7f5061e`|全success：[CodeQL](https://github.com/oxo-ops/dkss/runs/123151904840) / [postgres-masters](https://github.com/oxo-ops/dkss/actions/runs/40783733008/job/123151585739) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40783733028/job/123151585593) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40783733023/job/123151585469) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40783732990/job/123151585281) / [postgres-masters](https://github.com/oxo-ops/dkss/actions/runs/40783729806/job/123151575734)|
|[#307](https://github.com/oxo-ops/dkss/pull/307)|`82be1aa3f4f3640d3bddfba1bc70124fde4e93cd`|全success：[CodeQL](https://github.com/oxo-ops/dkss/runs/123161030035) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40786409829/job/123160594676) / [postgres-mfa](https://github.com/oxo-ops/dkss/actions/runs/40786409897/job/123160594225) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40786409836/job/123160594152) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40786409811/job/123160593906) / [postgres-masters](https://github.com/oxo-ops/dkss/actions/runs/40786409723/job/123160593897) / [postgres-identity](https://github.com/oxo-ops/dkss/actions/runs/40786409736/job/123160593475) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40786409697/job/123160593348) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40786409652/job/123160593228)|
|[#309](https://github.com/oxo-ops/dkss/pull/309)|`3f36925e9c2a7f1f2079ad31c2df3d8911cf9f8e`|全success：[CodeQL](https://github.com/oxo-ops/dkss/runs/123165479541) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40787759940/job/123165144544) / [planner-layout](https://github.com/oxo-ops/dkss/actions/runs/40787759945/job/123165140059) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40787759933/job/123165139504) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40787759978/job/123165139438)|
|[#310](https://github.com/oxo-ops/dkss/pull/310)|`38487b207e2a9637c94b292793bcfc4ce19e0620`|全success：[CodeQL](https://github.com/oxo-ops/dkss/runs/123166137412) / [postgres-masters](https://github.com/oxo-ops/dkss/actions/runs/40787963962/job/123165806336) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40787963736/job/123165806106) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40787963836/job/123165805734) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40787963741/job/123165805601) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40787963727/job/123165805416)|
|[#311](https://github.com/oxo-ops/dkss/pull/311)|`4d567f8b5aaf6f6cbd955829da081b8f76a701a7`|全success：[CodeQL](https://github.com/oxo-ops/dkss/runs/123171858725) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40789688720/job/123171515322) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40789688748/job/123171515206) / [readership](https://github.com/oxo-ops/dkss/actions/runs/40789688630/job/123171515058) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40789688650/job/123171514885) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40789688625/job/123171514858)|
|[#312](https://github.com/oxo-ops/dkss/pull/312)|`b719022034a07854385ed9c6e7727ce8142b3907`|全success：[CodeQL](https://github.com/oxo-ops/dkss/runs/123170128031) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40789154472/job/123169748182) / [postgres-dates](https://github.com/oxo-ops/dkss/actions/runs/40789154473/job/123169747831) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40789154531/job/123169747634) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40789154562/job/123169747597) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40789149555/job/123169737298)|
|[#313](https://github.com/oxo-ops/dkss/pull/313)|`a0703acc81a473043d1c3a84bdcdcea27161b5ce`|全success：[CodeQL](https://github.com/oxo-ops/dkss/runs/123177496122) / [postgres-masters](https://github.com/oxo-ops/dkss/actions/runs/40791370358/job/123177126788) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40791370288/job/123177126617) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40791370323/job/123177126600) / [postgres-identity](https://github.com/oxo-ops/dkss/actions/runs/40791370305/job/123177126539) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40791370307/job/123177126535) / [postgres-mfa](https://github.com/oxo-ops/dkss/actions/runs/40791370338/job/123177126528) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40791370275/job/123177126377) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40791370281/job/123177126331) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40791370241/job/123177126197)|
|[#314](https://github.com/oxo-ops/dkss/pull/314)|`d183d7d95ef7bab40d3ee08b88152f5d759f9b0a`|全success：[CodeQL](https://github.com/oxo-ops/dkss/runs/123186333761) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40794032691/job/123185969430) / [postgres-masters](https://github.com/oxo-ops/dkss/actions/runs/40794032637/job/123185969385) / [postgres-identity](https://github.com/oxo-ops/dkss/actions/runs/40794032492/job/123185969147) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40794032513/job/123185969104) / [browser](https://github.com/oxo-ops/dkss/actions/runs/40794032513/job/123185969073) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40794032536/job/123185968998) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40794032557/job/123185968966) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40794032508/job/123185968919) / [postgres-dates](https://github.com/oxo-ops/dkss/actions/runs/40794032490/job/123185968901) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40794032554/job/123185968890)|
|[#315](https://github.com/oxo-ops/dkss/pull/315)|`65b2218ad0cc754eb093f60fc2f9a60b5a562069`|全success：[CodeQL](https://github.com/oxo-ops/dkss/runs/123175123336) / [planner-layout](https://github.com/oxo-ops/dkss/actions/runs/40790695548/job/123174893985) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40790692433/job/123174883357) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40790651362/job/123174744907) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40790651267/job/123174744803) / [document-display](https://github.com/oxo-ops/dkss/actions/runs/40790651272/job/123174744703) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40790651296/job/123174744696)|
|[#317](https://github.com/oxo-ops/dkss/pull/317)|`83986e1ded8336cd103f61e6637992a70a0c220b`|全success：[CodeQL](https://github.com/oxo-ops/dkss/runs/123191088184) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40795482285/job/123190823734) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40795482383/job/123190823271) / [postgres-identity](https://github.com/oxo-ops/dkss/actions/runs/40795482326/job/123190823262) / [postgres-mfa](https://github.com/oxo-ops/dkss/actions/runs/40795482340/job/123190823197) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40795482309/job/123190823111) / [postgres-masters](https://github.com/oxo-ops/dkss/actions/runs/40795482229/job/123190823019) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40795482323/job/123190822851) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40795482141/job/123190822770) / [postgres-dates](https://github.com/oxo-ops/dkss/actions/runs/40795482250/job/123190822722) / [browser](https://github.com/oxo-ops/dkss/actions/runs/40795482126/job/123190822596) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40795482127/job/123190822344) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40795482126/job/123190822248) / [postgres-masters](https://github.com/oxo-ops/dkss/actions/runs/40795478204/job/123190809352)|
|[#319](https://github.com/oxo-ops/dkss/pull/319)|`adcd810db251b9346a3f8e3104bbcddd4ccee937`|全success：[CodeQL](https://github.com/oxo-ops/dkss/runs/123186854098) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40794233583/job/123186651729) / [document-display](https://github.com/oxo-ops/dkss/actions/runs/40794204210/job/123186548713) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40794203413/job/123186546312) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40794202346/job/123186543321) / [browser](https://github.com/oxo-ops/dkss/actions/runs/40794201823/job/123186541366) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40794201823/job/123186541027) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40794201505/job/123186539885)|
|[#321](https://github.com/oxo-ops/dkss/pull/321)|`b37c531c08133d0d4a085ee09481836e37da76b5`|全success：[CodeQL](https://github.com/oxo-ops/dkss/runs/123191719196) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40795652113/job/123191380611) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40795652166/job/123191380159) / [browser](https://github.com/oxo-ops/dkss/actions/runs/40795652113/job/123191380025) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40795652186/job/123191379947) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40795652117/job/123191379884) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40795652128/job/123191379850) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40795652109/job/123191379761)|
|[#322](https://github.com/oxo-ops/dkss/pull/322)|`30f33a3329a6b422162ba13887b2799a07c7ec6e`|全success：[CodeQL](https://github.com/oxo-ops/dkss/runs/123193078569) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40796081695/job/123192771324) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40796081712/job/123192771094) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40796081728/job/123192770773)|
