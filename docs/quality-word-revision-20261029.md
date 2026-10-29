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
