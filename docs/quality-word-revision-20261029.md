# 品質改善Wordの進展反映と報告集約 2026年10月29日

照合基準：2026-10-29 08:23 JST、main `40ac8acc2a00f27256b69c1444b253ce22502c95`。実装・PRマージ・対象head CI・本番受入を別々に判定する。アプリ試験は書記作業で再実行していない。正式版番号・承認日は更新していない。

## 最新Wordと保全

ファイル：`輸送版DX_品質改善と検証計画_進展反映_確認用_20261029.docx`

保存先：`C:\Users\takah\Documents\Codex\2026-10-28\dx-oxo-ops-dkss-q02-q03\outputs\輸送版DX_品質改善と検証計画_進展反映_確認用_20261029.docx`

SHA-256：`b76d4c99bfb570df193c62306e2516e4967c712de046276ea27c48a86a52a457`

前回07:49 JSTのWord：`輸送版DX_品質改善と検証計画_main照合改訂_確認用_20261029.docx`、SHA-256 `39aa281ca65bf96ad3a57dc0ac8846a3d120b71ec2a7990e826ba36aa1db24b7`。元ファイルを変更せず保全。10月28日21:31 JSTのWord（SHA-256 `1eff1989735ef0b08a8e9b204b991bfc066e83ebbbcf849e89bceebffbb75fe7`）も不変。

## 報告の重複整理

新規PRを作成せず、既存PR #306の同じ報告ファイルを更新する。#296は2026年10月28日21:31 JST、#306の前コミット644857aは10月29日07:49 JSTの記録として保存し、最新版レビューを#306へ集約する。旧#296の履歴・報告・Wordを削除せず、旧時点を明示して重複レビュー対象から外す。以前の報告を最新状態として併記しない。

## 章別変更・根拠・残条件

| 反映先 | 確認した進展 | 未完了と受入の境界 |
|---|---|---|
| 冒頭・1章・8章 | 基準mainと時刻を更新し、過去追補・PR本文の旧状態を区分。既存#306を最新版報告窓口に指定 | 正式版番号・承認日・正本認定は未設定 |
| 3章 Q02 | #307 head82be1aa3は日常点検500を対象とするドラフト・未マージ。32文字日時を保持してVARCHAR(40)へ拡幅する候補と明示移行手順 | 担当候補単独25成功・OCR4失敗はmain受入ではない。08:23時点の全体回帰は実行中。既存PG移行・旧値・SQLite互換・Q10再受入が必要 |
| 3章 Q03・20章 | #283がmerge939dd06でmain反映済みへ更新。head2236a578の両DB受入・CI成功を引継ぐ | 実配信・本番移行・実規模停止時間は未受入。非同期取込所有者等の別課題は解決済みにしない |
| 3章 Q04 | #304読取専用診断がmain反映済み。追加16件（SQLite11・PG5）の担当報告、最終head CI成功を確認 | SQLiteの最大営業所ID削除・同名同ID再登録後、旧削除POSTで新営業所／新車両割当が消失する問題は未修正。診断0終了やPG成功で代替しない。他4マスタ・世代保護・履歴・他社境界の再受入が必要 |
| 3・17章 Q05 | #298・#292マージ、各最終headの専用／全体CI成功。未来日を開始予定表示、開始前ランキング対象外、当日0日へ更新 | #292の旧headの失敗記録と区別。ブラウザ時刻帯・PC／mobileの再受入は担当が実施中で最終証拠未確定。旧日時の作成根拠照合は未完了 |
| 4章 Q10 | #294の確定受入不合格を保持し、#307候補との関係を追補。#299 U40計画回収もmainへ反映済み | #294はmain037ab51／head0732c71eの29件中12失敗。現在mainで全件再受入した記録ではない。OCR中の別UUIDへの旧受付・未登録原本継承を維持。実帳票・実AI・最低記録量は未決 |
| 4章 Q12〔表示性能改善〕 | #302の指摘一覧派生画像、#303のmobile配置をmain反映済みへ更新。最終head CI成功と限定計測を採用 | 原本／認可保持、実S3・実機・多数予定・エラー・文字拡大等を残条件として保持。旧Q12〔リリース・引継ぎ〕の番号・工数・役割は変えない |
| 4章 Q12・最新main追加 | #305公開CSS／JS2ファイルgzipがマージ済み、対象head CI成功。展開後の元バイト一致 | PR本文の暫定load値を確定効果に採用せず、実配信エッジ・本番効果は未確認 |
| 21・25章 | 横断状態と残存リスクを更新 | Q04 SQLite・Q10 OCR等を未解決。Q11待機・12〜21人時、M06／M07未解決を維持。全体完了／本番受入は宣言しない |

## Q12の測定条件と結果

#302：main037ab51とheade13ac70、架空200台・合成画像12枚1600×1000・一覧10件、PC／mobile、低速150ms・下り200,000B/s・CPU4倍、各3回。再表示load中央値はPC36,662→1,214ms、mobile36,533→1,069ms。HTML SQLは10→10、再表示CLS全条件0。単一画像のローカル原本21SQL→派生7SQLは別測定であり、直接配信するS3経路へ一般化しない。原本SHA維持、詳細・スクロール後画像・戻る操作、Fake S3、変換上限の担当確認を採用。実S3・本番SLAではない。

#303：架空200台・営業所未設定・予定0件の同じ低速条件、各3回。mobile再表示CLS中央値約0.0581→約0.00038、load777.7→775.3ms、HTML SQL14→14。通信短縮を主張しない。機能試験は実API応答を保持するinterceptionあり、性能計測はinterceptionなし。期限切れCookie由来のログイン画面測定を除外し、認証チェック後の取り直した値だけを採用。多数予定・大きな件数表示・エラー・文字拡大・実機Safariは未受入。

#305：公開CSS834,485→118,923B、JS103,926→21,144B、展開後は元と完全一致する担当証拠。確定比較値のない暫定load短縮は採用しない。

## PRと対象head checkの直接照合

| PR | head | 状態 | CI |
|---|---|---|---|
| [#283](https://github.com/oxo-ops/dkss/pull/283) | `2236a5786a15af902df65f0b7c715da12cb25b37` | マージ済み | 対象head checkすべて成功 [regression](https://github.com/oxo-ops/dkss/actions/runs/40779948626/job/123138787675) |
| [#298](https://github.com/oxo-ops/dkss/pull/298) | `990050a99dad527299fa860df6235531e9727ade` | マージ済み | 対象head checkすべて成功 [regression](https://github.com/oxo-ops/dkss/actions/runs/40779669732/job/123137838168) |
| [#292](https://github.com/oxo-ops/dkss/pull/292) | `92b5f05b3befe69b950dd55f96305eb60757eee1` | マージ済み | 対象head checkすべて成功 [regression](https://github.com/oxo-ops/dkss/actions/runs/40785175971/job/123156440849) / [postgres-dates](https://github.com/oxo-ops/dkss/actions/runs/40785175925/job/123156440426) |
| [#304](https://github.com/oxo-ops/dkss/pull/304) | `c0bb90507391b8b752a52862b34ffe99c7f5061e` | マージ済み | 対象head checkすべて成功 [regression](https://github.com/oxo-ops/dkss/actions/runs/40783732990/job/123151585281) |
| [#302](https://github.com/oxo-ops/dkss/pull/302) | `e13ac70e3ed119c7221e9276c6413df05e6728ba` | マージ済み | 対象head checkすべて成功 [regression](https://github.com/oxo-ops/dkss/actions/runs/40781054125/job/123142540333) |
| [#303](https://github.com/oxo-ops/dkss/pull/303) | `f4caa12bdf6df0f477b7c307a5955aeb19124763` | マージ済み | 対象head checkすべて成功 [planner-layout](https://github.com/oxo-ops/dkss/actions/runs/40783692349/job/123151448753) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40783692300/job/123151448276) |
| [#305](https://github.com/oxo-ops/dkss/pull/305) | `3a5455b45b8f98490abc6ee7ab9f87a3061e73c0` | マージ済み | 対象head checkすべて成功 [regression](https://github.com/oxo-ops/dkss/actions/runs/40785708832/job/123158237399) |
| [#307](https://github.com/oxo-ops/dkss/pull/307) | `82be1aa3f4f3640d3bddfba1bc70124fde4e93cd` | ドラフト・未マージ | regression:in_progress [postgres](https://github.com/oxo-ops/dkss/actions/runs/40786409811/job/123160593906) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40786409697/job/123160593348) |
| [#294](https://github.com/oxo-ops/dkss/pull/294) | `0732c71eb54cf0d0ec4ca968001abf59e5b4006f` | ドラフト・未マージ | postgres:failure [postgres](https://github.com/oxo-ops/dkss/actions/runs/40780574642/job/123140936395) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40780574632/job/123140935972) |
| [#299](https://github.com/oxo-ops/dkss/pull/299) | `6222cfff5d7d4fe1cae668ea9553564b0171ac0b` | マージ済み | 対象head checkすべて成功 [regression](https://github.com/oxo-ops/dkss/actions/runs/40782274242/job/123146659721) |

PR本文には過去の「ドラフト」「未マージ」「CI失敗」が残るものがある。上表はGitHubの現在メタデータとそのhead checkで確認し、本文の過去状態とは区別した。CIは対象headの証拠で、実環境受入・今回main全体の再試験ではない。

## 一次資料・保全・表示確認

main内：Q03-approval-person-identity、Q04-master-preflight-20261029、Q05-scheduled-safe-start／usage-summary-race、q12-attachment-thumbnails／mobile-planner-stability／public-assetsの各技術資料。#307は同PRの本文・差分とhead状態、#294は確定本文と前回担当report/results（main037ab51）。Q05は最新担当チャットのブラウザ再受入中連絡を最終合格と扱わず、未確定として記録した。

各PRの受入件数・集計対象・版は重複があるため加算しない。担当範囲の製品修正・DB操作・アプリ試験は今回実施していない。

既存25章・24表・改訂履歴・書式を保持。19箇所を局所更新し、既存段落変更は14。全24表はXML一致、document.xml以外の18部品はバイト一致、変更対象外本文は同一内容・同一順序を検査。旧Word2点のハッシュ不変。

Word 16の読取専用PDF出力と同梱ラスタ化処理で全28ページを表示確認済み。ページ外文字0・空白ページ0。既存章・表の欠落や文字重なりは確認されなかった。システム仕様書・Excel・製品コード・DB・テストは変更していない。

本改訂は上記時点の確認用記録であり、以後のPR更新は次回照合対象。品質改善全体・本番受入・正式承認の完了を示さない。
