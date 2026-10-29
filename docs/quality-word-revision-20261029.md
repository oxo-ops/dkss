# 両Word 担当成果統合・変更報告（確認用）

照合基準：2026年10月29日14:26 JST、main `7583e45f440146068a25c527c40aafa384019b9a`。以後の進展は今回の確認範囲外。正式版番号・承認日は変更していない。本番復旧は未完了・P1保留であり、ローカル／合成DB隔離検証・CI・マージを本番受入へ読み替えていない。

## 成果物と保全

### 品質改善計画

保存先：`C:\Users\takah\Documents\Codex\2026-10-28\dx-oxo-ops-dkss-q02-q03\outputs\輸送版DX_品質改善と検証計画_担当成果統合_確認用_20261029.docx`

SHA-256：`68bb727d49884e973ced29a28bfe22284e4477a941ce6a279fac7db9007a4ba1`

ページ数：31。構成：25章・24表・0図。

保全した元ファイル：`C:\Users\takah\Documents\Codex\2026-10-28\dx-oxo-ops-dkss-q02-q03\outputs\輸送版DX_品質改善と検証計画_受入結果追補_確認用_20261029.docx`

元SHA-256：`bd1ca960ef87da9222e9f8670877e1d3d48f5a9d2928e6e753b5afdce4803349`（再照合一致）。

### システム仕様書

保存先：`C:\Users\takah\Documents\Codex\2026-10-28\dx-oxo-ops-dkss-q02-q03\outputs\輸送版DX_システム仕様書_v0.25基準_業務方針統合_確認用_20261029.docx`

SHA-256：`081990f7490c72f1b1422ac7f203da978c5bed2a6cb2d3be601935d9819f5d3a`

ページ数：75。構成：19章・2表・2図。

保全した元ファイル：`C:\Users\takah\Documents\Codex\2026-10-28\dx-oxo-ops-dkss-q02-q03\outputs\輸送版DX_システム仕様書_v0.25基準_追加差分追補_確認用_20261029.docx`

元SHA-256：`b7b8665c311e5feb6cc03cddacd6879116222072a2f365628742ad305a27d1db`（再照合一致）。

## 品質改善計画の最新状態・残工数

既存表・過去の試験／工数は時点記録として保全し、現在値を本文の最新追補と24章で区別した。古い「#314未マージ」「SQLite未修正」等24箇所にも旧記録表示を追加した。以下は担当報告の見積枠であり、作業中の消化実績が未分離の項目を精算済み残時間とは扱わない。

|対象|確認済み状態・残条件|今回の見積枠（人時）|
|---|---|---|
|Q01|既存本番読取結果は当時の結果。完全live SHA・元role/search_path・追加移行証拠など不足部分を確認|未再見積|
|Q02|#307・#313・#321 main反映、対象CI・隔離受入成功。全経路／本番受入は別|未再見積|
|Q03|#314・#325・#327・#330・#333等main反映。固定bdab9d8の実ブラウザ6条件は2合格・4未達。古版安全承認302変換、車両409の具体案内不足は修正中|ブラウザ4–7＋言語assert0.5–1＝4.5–8。別判断10–16|
|Q04|#317の世代対策はmain。固定288261dのPG240件成功は既存証跡。会社内名称索引診断は別責務。新版入口契約v1採用、実装中・未受入|主管4–6＋Q04側4–7＝8–13（旧9–14を置換）|
|Q05|#312まで実装・自動テスト・ブラウザ受入完了。正式仕様書／本番受入は別|開発0|
|Q06|JSON棚卸し完了、必要テーブル化0。将来の型／容量／性能変更は別|開発0|
|Q07|M06とM07は未解決。M07は請求書単位訂正＋合計再計算を採用し実装中。原本・履歴・手入力費用を保持|M07 18–30（旧15–26を置換）|
|Q08|#326 News、#337 status省略時の旧NULL保持はmain。unknownの一覧・通知・AI等の判断は残る|既知修正0。残判断は未再見積|
|Q09|#329・#331・#332・#338 main、Linux実起動・通常停止を確認。実配備・ログ運用・主管証拠待ち|1–2（旧2–4を置換）、HTTP開発0|
|Q10|既知不具合修正・隔離PG／代表統合受入完了、開発完了。追加仕様・業務／運用受入は別|開発0、別枠4–8暫定|
|Q11|運用受入待機。実S3・実容量・旧版操作・配備条件worker・業務RPO/RTO未受入|12–21据置|
|Q12〔リリース・引継ぎ〕|既存番号を維持。未解決条件・責任者・本番受入待ち|他枠との共通作業未分離、再見積待ち|
|Q12〔表示性能改善〕|#319・#334等main。条件付きPC改善、mobile高速化未達。実機・配信層・S3・実容量PG・並行負荷未受入|9–17（旧10–18を置換）|
|日報manual|#335対象5経路の保存時世代保護はmain。旧UUID不明登録待ちの根拠付き回復は採用方針、未実装|既知修正0、回復仕様整理1–2。実装／実データ受入は未見積|

重複排除：Q06→M07、Q05→Q09、Q10→Q03/Q07への担当替えを追加工数にしない。日報#335の完了修正・既存240件／6処理・旧成功群・CSV追加受入を再実装／再受入と重複加算しない。Q04側4–7は8–13の内数。Q09の旧HTTP8–16を足さない。Q11と性能の共有環境準備、Q01/Q02/Q08、旧本人回復等は未分離・未再見積のため、重複排除済み総残工数と総週数は未確定。旧138–228／166–274／ID化48–80は歴史的計画枠であり現在残ではない。

## 重要な検証結果と採用根拠

- Q03：担当ブラウザ受入報告と最小修正指示。保存保護とブラウザ案内／応答の未達を分け、通常承認回答版・通知設定親の初回重複防止を対象範囲で評価。同世代全リスト後勝ち・受付冪等性は判断待ち。
- Q08：利用者採用の「編集時status省略なら保存値を保持」に基づく#337。旧NULLを未対応へ自動変換しない。専用16件・CIは実配信や全画面E2Eではない。
- Q12表示性能：#334／担当受入記録。Chrome156、架空200台、原本707,343B、PC1440×1000/DPR1 n5、mobile390×844/DPR2 n3、150ms・200,000B/s・CPU4倍。PC reload4.905→2.941秒、画像326,830B、CLS0.02730→0.00463。SQL29→30。mobile4.991→5.079秒で受入保留。既存#309/#315のgzip等と測定条件を混ぜない。
- 移行：固定288261dの388実行＝387成功・1言語依存assert失敗、error/skip0。厳密な例外型＋SQLSTATE55P03の独英限定確認は別試行、元388全成功にはしない。
- CSV追加：#327の追加DDLを新規合成DBのdump／復元で確認。旧68表49行、原本4件SHA一致、nullable列・索引、既存UUID/JSON、旧NULL保持、再実行、DDL故障rollback／再試行、選定HTTP4件。保護対象DB・実運用バックアップの復元や本番適用ではない。
- Q06/Q10：担当最終報告、Q06 inventory、Q10追加受入記録。開発残0と追加業務／運用受入を分離。以前の不合格は旧時点として残す。
- M07：担当チャットで採用された請求書単位訂正・合計再計算。140の差額を推定配賦せず根拠待ち、再アップロード／二重入力／整備再完了を要求しない。実装中の試験を最終受入としない。

## 実施順序と本番復旧

1. 直接ログイン復旧L：現18ae141b維持を第一候補に、既確認事実の不足証跡だけを補う。Q04新版入口完成待ちを直接復旧の前提にしない。
2. 並行：Q03ブラウザ未達、Q07 M07、Q08残方針、旧manual回復、表示性能の未受入を進める。
3. 新版配備R：採用版／manifest、Q04入口、CSV追加DDL・旧NULL保留、旧フォーム失効・版統一を照合する。
4. 停止・整合バックアップ・切戻し・承認条件を揃え、限定ログイン、通常業務／OCR再開、Q11業務受入、リリース承認を別々に判定する。

本番確認事実は10月29日の利用者報告時点：SHA18ae141b、Auto-Deploy Off、接続先/schema確認、user.account_identity・Q03列・OCR owner_identity等欠落、checklist_event.created_at VARCHAR(30)、PITR3日、旧export10月27日16:50。これらを一律未確認へ戻さない。完全SHA／全Web・worker・jobと設定版、元role/search_pathと表解決、M01の6表8列3索引・権限／保持比較の不足は別。最新export・実復元・本番移行・ログイン復旧は未完了。M01では既存UUID・認証・通知・監査を保持し、NULLへの新UUID付与と旧本人の推定紐付けを区別する。#336はCI成功・未マージの条件資料で、実施承認ではない。

## 仕様書の変更範囲

03章：#335の日報manualの保存時署名・期待UUID・共有人物ロック・日報版確認と、旧manualの根拠付き回復方針（未実装）を分離。

06章：採用されたM07の請求書単位訂正・合計再計算と原本／履歴／手入力費用保持を追補。現コードを正式仕様へ追認せずM06/M07の不一致を維持。

06章：#337の編集status省略時保持・旧NULL未確認表示・明示正規状態変更を記録。未知状態の一覧／通知／AI方針は未決。

07・09章：#334の認可後lossless480/960px候補、原本fallback／ピンチ切替、原本SHA・no-storeと認可／世代境界を記録。性能測定・試験件数・見積は品質改善計画へ分離。

16章：CSV追加隔離適用と本番未適用、Q04入口の採用方針・実装未完了、旧本番確認事実とログイン復旧の保持条件、#338によるLinux成功記録訂正を追補。

18・19章：未達／未決事項と確認用履歴を更新。S87–S91で根拠を対応付けた。旧S82などの過去記録は最新対象修正と時点区分し、F/U/K番号・本文を変更していない。正式承認済み正本の認定はしていない。

## 保全・全ページ表示確認

Word COMの読取専用PDF出力後、全31ページ＋全75ページを画像表示して確認した。空白ページ・ページ外文字なし。既存章見出し・表XMLを維持し、仕様書の図・F/U/K番号付き既存本文も維持。品質改善計画のdocument.xml以外18部品、仕様書24部品は元とバイト一致。新規追補は既存段落スタイルを継承し、ヘッダー・フッター・正式版番号・承認日・過去改訂履歴を保持した。元Word2本のSHAを再計算し不変を確認した。製品テスト再実行・製品コード／DB／Excel／Render／品質担当外資料の変更は行っていない。

## PRとCI（照合基準時点）

既存#296/#306/#316/#322/#328/#339は過去時点の報告。今回の差分は既存#320へ統合し、新規PRは作成しない。Word実物はこの端末のoutputsに保存し、GitHubには報告を保存する。

|PR|状態|対象headのchecks|
|---|---|---|
|[#314](https://github.com/oxo-ops/dkss/pull/314)|マージ済み / `d183d7d95ef7`|success:11|
|[#317](https://github.com/oxo-ops/dkss/pull/317)|マージ済み / `83986e1ded83`|success:14|
|[#319](https://github.com/oxo-ops/dkss/pull/319)|マージ済み / `adcd810db251`|success:8|
|[#321](https://github.com/oxo-ops/dkss/pull/321)|マージ済み / `b37c531c0813`|success:8|
|[#323](https://github.com/oxo-ops/dkss/pull/323)|マージ済み / `6e76518347fa`|success:7|
|[#324](https://github.com/oxo-ops/dkss/pull/324)|マージ済み / `76904dedbbc1`|success:8|
|[#325](https://github.com/oxo-ops/dkss/pull/325)|マージ済み / `6c11e9d46447`|success:10|
|[#326](https://github.com/oxo-ops/dkss/pull/326)|マージ済み / `266a59934a1d`|success:10|
|[#327](https://github.com/oxo-ops/dkss/pull/327)|マージ済み / `6cd76fbd59a2`|success:13|
|[#329](https://github.com/oxo-ops/dkss/pull/329)|マージ済み / `ff6142a37fd1`|success:8|
|[#330](https://github.com/oxo-ops/dkss/pull/330)|マージ済み / `47fb098f9843`|success:11|
|[#331](https://github.com/oxo-ops/dkss/pull/331)|マージ済み / `3454ad9d0f88`|success:4|
|[#332](https://github.com/oxo-ops/dkss/pull/332)|マージ済み / `283ed0d1fce9`|success:9|
|[#333](https://github.com/oxo-ops/dkss/pull/333)|マージ済み / `fb381bcf294e`|success:12|
|[#334](https://github.com/oxo-ops/dkss/pull/334)|マージ済み / `1217f5ffc1f2`|success:10|
|[#335](https://github.com/oxo-ops/dkss/pull/335)|マージ済み / `c3f39e1b72bd`|success:10|
|[#336](https://github.com/oxo-ops/dkss/pull/336)|未マージ / `392713d94be3`|success:4|
|[#337](https://github.com/oxo-ops/dkss/pull/337)|マージ済み / `21f5d221f932`|success:10|
|[#338](https://github.com/oxo-ops/dkss/pull/338)|マージ済み / `64a88654979b`|success:4|
|[#339](https://github.com/oxo-ops/dkss/pull/339)|マージ済み / `e5ef2f7afb17`|success:4|
|[#340](https://github.com/oxo-ops/dkss/pull/340)|未マージ / `eb0a99017b2f`|なし|

#340は旧Q09枝で新しい成果として重複計上しない。報告PR自身の更新後head・CIは提出記録で追記し、自動マージは行わない。

---

## 以下は前回までの報告（各時点の記録）

# 品質改善Word 受入結果追補・時点整理 2026年10月29日

照合基準：2026-10-29 09:25 JST、main `3582b969a79ce4f9a5b57e6d8171368a72607464`。アプリ試験は書記作業で再実行していない。各担当の固定版の結果、現在のPRメタデータ・head checksを照合した。今回以降の更新は次回照合対象。

## Word実物と保全

ファイル名：`輸送版DX_品質改善と検証計画_受入結果追補_確認用_20261029.docx`

保存先：`C:\Users\takah\Documents\Codex\2026-10-28\dx-oxo-ops-dkss-q02-q03\outputs\輸送版DX_品質改善と検証計画_受入結果追補_確認用_20261029.docx`

SHA-256：`bd1ca960ef87da9222e9f8670877e1d3d48f5a9d2928e6e753b5afdce4803349`

元28ページ版（08:23 JST時点、08:44状態変化追記を含む）：`C:\Users\takah\Documents\Codex\2026-10-28\dx-oxo-ops-dkss-q02-q03\outputs\輸送版DX_品質改善と検証計画_進展反映_確認用_20261029.docx`。SHA-256 `a93aa3e2fefa94b07af5bb5490ea2fd47f4597b2dc703ea47c96d9023985ddec`。原本を変更せず保全した。過去の21:31・07:49版も変更していない。

## #316と報告の重複整理

#316はhead75d83400147b6b4b1854deb9f8476b797c9a802dのCodeQL・Analyze Python・pip-audit・regression成功後に外部マージ済み。今回の追補はそのマージに含まれないため、最新mainから独立ブランチを作り、同じ `docs/quality-word-revision-20261029.md` 1件だけを更新する。#296は旧21:31記録（クローズ済み）、#306は07:49記録（マージ済み）、#316は08:23記録（マージ済み）として保持し、再計上・重複ファイルを増やさない。新規PRは今回の未反映差分1件のみ。Wordはローカル確認用実物であり、この報告PRにバイナリを収録したとは扱わない。

## 章別変更・採用根拠・未完了条件

| 章 | 更新・根拠 | 受入の境界・残条件 |
|---|---|---|
| 冒頭・1・8 | main3582b969／09:25 JSTへ基準更新。旧追補と旧PR本文を時点区分。#316のCI・マージ確認 | 正式版1.21・承認日は変更せず、正本認定もしない |
| 3 Q02 | #313 head a0703accが照合中にマージ。受付UUIDを固定し処理・公開・確認・原本等で会社＋UUIDを照合。専用CIを含むhead checks成功。旧#307ドラフト記録に08:23時点を明記 | 旧NULL受付は保留し自動補完しない。停止・バックアップ・明示移行、本番適用は未実施。登録済み会社共有原本は維持 |
| 3 Q03・Q04／20 | #314 head0645bdddは未マージ・ドラフト、09:25の全体回帰等は実行中。候補のOffice/Vehicle/Userロック順対策、担当PG216件・本人世代83件等の成功は候補の証拠 | 旧ロック競合・回帰失敗をmainの解消へ認定しない。Q04 SQLite営業所ID再利用・旧削除フォーム混同は未解決。実容量・複数タブ等も未受入 |
| 3 Q05／17 | #312 headb7190220、merge599e568。実装・自動テスト・ブラウザ受入完了、開発残0人時。CI Chromium151／Chrome156で各76ケース、Tokyo→Honolulu、PC1440×1000／mobile390×844・touch DPR2。PG7件・cold/warm各16要求8接続 | 正式仕様書反映・本番受入は別。旧時刻帯不明値を推定変換しない |
| 4 Q08 No.11 | #310 head38487b20、mergecc4b8d7。点検候補・訂正権限の別UUID継承を防止。両DB新規34＋基盤8の担当証拠、対象CI成功 | 本番移行は未実施。旧本人不明の訂正を保留し件数影響確認、停止・バックアップ・明示移行が必要 |
| 4 運転分析 No.10 | #311 head4d567f8b、merge7a3a265。旧UUID未確定日報は本人閲覧を保留。会社・現UUID・原本指紋を個人一覧/詳細/集計/出力/AIで確認。両DB47件、ブラウザ4シナリオの担当成功、head CI成功 | 管理者の再承認・本番データ影響確認は未実施。会社集計・元値を維持し、氏名から自動補完しない |
| 4 Q10 | #294 head5439d8adと#313がマージ。cc4b8d7＋OCR修正の隔離PG18.6で元12失敗を含む29件すべて成功、error/skip0、38.756秒。最終headの専用PG・browser・回帰等すべて成功 | 旧0832720／0732c71eの12失敗を過去記録として保存。現main全件を今回再実行した意味ではない。#307単独マージを総合合格根拠にしない。実OCR・実配信・実端末・既存DB移行・業務判定は残る |
| 4 Q12〔表示性能改善〕 | #309通知アイコン、#315 PDF選択時viewer読込をマージ、各head CI成功。限定条件と初回/warmを分離（下記） | PC再表示の性能受入は保留。実Safari/Android・S3・運用PG・実配信層は未検証。Q12〔リリース・引継ぎ〕は既存番号のまま別名参照 |
| 21・25 | 横断判定を上記へ更新。Render原因調査・隔離移行検証と本番の未確認を分離 | Q11は環境・運用責任者・承認条件待ち、残12〜21人時据え置き。M06/M07不一致は維持。全体完了・本番受入完了とはしない |

## Q12の条件と計測値

#309：gzip前main0832720→a625044、PC1440×1000／mobile390×844、150ms・下り200,000B/s・CPU4倍、各3回。38pxの通知アイコン原本145,127Bに対し派生76/152/304pxを使用。DPR1/2は2,236B、DPR3/4は5,650B。初回load中央値PC7,682.5→6,761.4ms、mobile7,401.2→6,874.7ms。warm画像0Bは両版同じ、mobile load802.1→856.9msで速度改善を保証しない。SQL4・CLSほぼ0は不変。#305gzipとの効果合算をしない。

#315：main eb48566→1748db8、同PC/mobile・低速条件、交互各3回。不要なPDFモジュール912,220Bを除去し、初回load中央値PC13,445.1→8,574.7ms、mobile13,374.7→8,571.2ms。FCP差は小さく約5秒の初期描画短縮とはしない。追加warm各5回ではPC5,449→5,734ms、mobile5,782→5,141ms。原画像707,343Bの再取得とリソース開始時刻差が支配し、PC再表示の性能受入は保留。マージ/CI成功と性能受入を別判定にする。旧設定値はpregzip、最新通常PC280.3/mobile292msと異条件で直接比較しない。

## Renderの検証と本番保留

担当のvalidation_report.txt／実施判定表／管理者確認手順を読取照合。固定main599e568／PG18.6の架空旧形式fixtureで既存5移行CLI、再実行、復元・値保持、ログイン/MFAなど8ケースと既存79件が成功。起動hookだけではuser.account_identity欠落が残ることも再現した。66表・47行・原本5件の小規模検証で、本番全量・配備を再現したものではない。#313の追加移行は配備版に合わせ別途照合する。

T01配備確認・T02対象DB確認・T03読取診断は未確認、移行開始は保留。対象DB/schema/元search_path確定前はT03実行不可。通信エラー・ブラウザ安全制御は調査環境の制約であり、本番の追加原因と断定しない。管理者の証跡・停止/バックアップ/復旧承認・移行後起動/ログイン確認が必要で、本番スキーマ確認・移行・ログイン復旧は未完了。接続情報や秘密値は本報告に収録しない。

## PR最終headとCI証跡

| PR | head | 状態 | head checks |
|---|---|---|---|
| [#312](https://github.com/oxo-ops/dkss/pull/312) | `b719022034a07854385ed9c6e7727ce8142b3907` | マージ済み | 全check成功 [postgres-dates](https://github.com/oxo-ops/dkss/actions/runs/40789154473/job/123169747831) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40789154531/job/123169747634) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40789149555/job/123169737298) |
| [#310](https://github.com/oxo-ops/dkss/pull/310) | `38487b207e2a9637c94b292793bcfc4ce19e0620` | マージ済み | 全check成功 [regression](https://github.com/oxo-ops/dkss/actions/runs/40787963736/job/123165806106) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40787963836/job/123165805734) |
| [#311](https://github.com/oxo-ops/dkss/pull/311) | `4d567f8b5aaf6f6cbd955829da081b8f76a701a7` | マージ済み | 全check成功 [regression](https://github.com/oxo-ops/dkss/actions/runs/40789688650/job/123171514885) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40789688625/job/123171514858) |
| [#309](https://github.com/oxo-ops/dkss/pull/309) | `3f36925e9c2a7f1f2079ad31c2df3d8911cf9f8e` | マージ済み | 全check成功 [regression](https://github.com/oxo-ops/dkss/actions/runs/40787759978/job/123165139438) |
| [#315](https://github.com/oxo-ops/dkss/pull/315) | `65b2218ad0cc754eb093f60fc2f9a60b5a562069` | マージ済み | 全check成功 [identity](https://github.com/oxo-ops/dkss/actions/runs/40790692433/job/123174883357) / [document-display](https://github.com/oxo-ops/dkss/actions/runs/40790651272/job/123174744703) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40790651296/job/123174744696) |
| [#313](https://github.com/oxo-ops/dkss/pull/313) | `a0703acc81a473043d1c3a84bdcdcea27161b5ce` | マージ済み | 全check成功 [postgres](https://github.com/oxo-ops/dkss/actions/runs/40791370288/job/123177126617) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40791370323/job/123177126600) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40791370275/job/123177126377) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40791370241/job/123177126197) |
| [#314](https://github.com/oxo-ops/dkss/pull/314) | `0645bdddc067c0ac6a257bcfdee64200f62b6a89` | ドラフト・未マージ | postgres-masters:in_progress / identity:in_progress / postgres-identity:in_progress / regression:in_progress / postgres-dates:in_progress / browser:in_progress [identity](https://github.com/oxo-ops/dkss/actions/runs/40793794415/job/123185180938) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40793794315/job/123185180815) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40793794355/job/123185180742) / [postgres-dates](https://github.com/oxo-ops/dkss/actions/runs/40793794306/job/123185180712) / [browser](https://github.com/oxo-ops/dkss/actions/runs/40793794315/job/123185180496) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40793794252/job/123185180193) |
| [#294](https://github.com/oxo-ops/dkss/pull/294) | `5439d8ade9a5219e7dbf8189a11f50ed7cbdc46c` | マージ済み | 全check成功 [identity](https://github.com/oxo-ops/dkss/actions/runs/40791377264/job/123177150915) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40791377154/job/123177150102) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40791377212/job/123177150086) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40791377198/job/123177149883) / [browser](https://github.com/oxo-ops/dkss/actions/runs/40791377154/job/123177149788) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40791377159/job/123177149611) |
| [#316](https://github.com/oxo-ops/dkss/pull/316) | `75d83400147b6b4b1854deb9f8476b797c9a802d` | マージ済み | 全check成功 [regression](https://github.com/oxo-ops/dkss/actions/runs/40791596996/job/123177897629) |

#313は09:15にはドラフト未マージ、#294・#316も未マージだったが、09:25再取得でマージを確認。過去時点を遡って変更せず区分した。#314は候補成功後さらにmainを取り込み、上記最新headはCI途中である。

## 読み取った主な資料

- mainの `docs/quality/Q05-scheduled-acceptance-20261029.md`、`driving-no10-readership-20261029.md`。
- mainの `docs/quality/Q02-import-owner-generation-fix-20261029.md`、`Q10-two-fixes-acceptance-20261029.md`、過去記録の `Q10-acceptance-20261028.md`／`Q10-handoff-20261029.md`。
- #309/#315のPR本文・diff・測定条件、各最終headチェック。#314候補の専用CIとQ03担当の途中報告。
- Render担当成果物 `validation_report.txt`、`production_preflight_handover.txt`、`render_admin_confirmation.txt`。本番接続は実施していない。

## Word保存・全ページ確認

22か所を局所更新し、既存段落変更13。25章・24表・改訂履歴・書式を保持。全24表XML一致、document.xml以外の18部品バイト一致、変更対象外本文は内容と順序の一致を検査した。元28ページ版SHA-256不変。

Word 16読取専用PDF出力と同梱ラスタ化を使用し、全30ページのネイティブ画素画像を表示確認。文字重なり・欠落・表の崩れは確認されず、ページ外文字0・空白ページ0。既存の表・段落の改ページは保持した。正式版番号・承認日、製品コード・DB・テスト・システム仕様書・Excelは編集していない。

残作業は各章の実環境受入・移行/旧データ判断・未マージ候補の確定後の再照合。今回の文書追補と表示確認は完了し、品質改善全体や本番受入の完了は宣言しない。
