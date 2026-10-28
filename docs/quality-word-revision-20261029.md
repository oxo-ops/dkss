# 品質改善Wordのmain照合改訂報告 2026年10月29日

照合基準：2026-10-29 07:49 JST、main `037ab518305430a794571f89ba3aacc8bf0dbab6`。2026年10月28日21:31 JSTのWordを保全し、別ファイルで確認用改訂を作成した。正式版番号・承認日は未設定。今回の書記作業ではアプリ試験を再実行していない。

更新Word：`輸送版DX_品質改善と検証計画_main照合改訂_確認用_20261029.docx`

保存先：`C:\Users\takah\Documents\Codex\2026-10-28\dx-oxo-ops-dkss-q02-q03\outputs\輸送版DX_品質改善と検証計画_main照合改訂_確認用_20261029.docx`

SHA-256：`39aa281ca65bf96ad3a57dc0ac8846a3d120b71ec2a7990e826ba36aa1db24b7`

保全した旧Word：`輸送版DX_品質改善と検証計画_重要検証結果反映_確認用_20261028.docx`、SHA-256 `1eff1989735ef0b08a8e9b204b991bfc066e83ebbbcf849e89bceebffbb75fe7`。

## 章別更新と判定

| 更新先 | 採用した結果と残る条件 |
|---|---|
| 冒頭・1章 | 基準mainと日時を更新。「#285等の未マージ調査」を修正。旧結果・SHA・表は各時点の履歴として保持。 |
| 3章 Q03・20章 | #283 head2236a578の最終追加受入34件・全CI成功、draft解除を一次報告とGitHubで確認。以前の受入不合格は旧結果として保持。未マージでありmain反映済みにはしない。合成復元と本番移行・実規模停止時間を分離。 |
| 3章 Q04 | #273のお知らせ営業所ロック・通知一括保存と、#295の不正索引検出をマージ済みへ更新。#295担当報告はPG211件、全体1387件実行・20skip。自動索引修復はなく実DB棚卸し・承認済み修復手順が必要。 |
| 3・17章 Q05 | #298 head990050a9の全CI成功・未マージと、#292ドラフト・日付PG／回帰失敗を区別。#298反映後の#292再受入は未実施。旧日時の根拠不明を補完しない。 |
| 4章 Q08・Q09 | #297の確定済み日報・点検通知の世代証跡をマージ済みとして反映。旧権限の再承認・明示初期化・停止と切戻し条件を追補。本人復元は仕様案で未実装。未紐付け旧日報の氏名照合・非同期取込所有者・旧フォームの世代競合は残る。 |
| 4章 Q10 | #294 head0732c71e、main037ab51に対するPG29件中17成功・12失敗、ブラウザ6件・Q08 PG世代境界19件成功を担当資料で確認。全体回帰1392成功・別途29クラスskipでも受入不合格。日時32文字とVARCHAR(30)不整合、同名別UUIDへの旧受付／未登録原本継承の2問題を維持。 |
| 4章 Q12 | 番号を変えず「Q12〔リリース・引継ぎ〕」「Q12〔表示性能改善〕」を併記する参照区分を明示。旧工程・工数・表はリリース・引継ぎに属し、性能改善へ移さない。新しい正式IDは未決。 |
| 4章 Q12 表示性能 | #290・#293の限定計測と#300の結合確認を反映。原画像派生とCSS読込位置の改善を分離。#300マージ前後のmain tree差分0をgitで確認し、新たな製品変更・性能効果を加算しない。 |
| 8・21・25章 | 出典、旧Word保全、残存リスク、横断受入条件を更新。M06／M07未解決、Q11待機・12〜21人時を維持。品質改善全体・本番受入を完了としない。 |

## Q12測定の範囲

main内の `docs/q12-performance-20261028.md` と `docs/q12-inspection-first-paint-20261028.md` を根拠とする。架空200台、原画像2,627,384B、Chrome PC／mobile模擬、低速150ms・下り1.6Mbps・CPU4倍、各条件1回の比較。#290は設定再表示loadがPC14,211→776ms、mobile約14,214→782ms。#293はPC点検計画再表示CLS0.2293→0.0005、低速mobile初回0.1940→0.0601。SLA・統計的な保証、SQL改善・全体load改善を示す値ではない。

mobile非同期描画CLS約0.058、多数予定、実機Safari／Android、実S3、実PG／同時負荷、配信層の検証は残る。#290／#293の本文に残る古いheadの失敗・ドラフト記述と、下記の最終head CI成功・マージを分離した。

## PRとCIの直接確認

以下は各PR headのcheckであり、今回のmain全体再実行・本番受入ではない。CodeQLには同一workflow由来の別check名があるため、check数を試験件数として扱わない。

| PR | 最終確認head | 状態 | CIの状態 |
|---|---|---|---|
| [#273](https://github.com/oxo-ops/dkss/pull/273) | `bb8ff6a16022d823323e6641a7cdf02fb5de08ca` | マージ済み | 対象checkすべて成功 [regression](https://github.com/oxo-ops/dkss/actions/runs/40695194426/job/122839987531) |
| [#283](https://github.com/oxo-ops/dkss/pull/283) | `2236a5786a15af902df65f0b7c715da12cb25b37` | レビュー可能・未マージ | 対象checkすべて成功 [postgres-identity](https://github.com/oxo-ops/dkss/actions/runs/40779948986/job/123138787978) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40779948626/job/123138787675) |
| [#290](https://github.com/oxo-ops/dkss/pull/290) | `ba173cc47b527cc69850fbbad401fee9ca4a59ca` | マージ済み | 対象checkすべて成功 [regression](https://github.com/oxo-ops/dkss/actions/runs/40777300237/job/123129789402) |
| [#292](https://github.com/oxo-ops/dkss/pull/292) | `92ca66e239689916a99cbc1a32be13d3a44cbd7c` | ドラフト・未マージ | 未合格：postgres-dates,regression [postgres-dates](https://github.com/oxo-ops/dkss/actions/runs/40690079262/job/122822348642) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40690079100/job/122822347856) |
| [#293](https://github.com/oxo-ops/dkss/pull/293) | `e7f12b0c082ba5ca16a0a626014daa2f999c8434` | マージ済み | 対象checkすべて成功 [regression](https://github.com/oxo-ops/dkss/actions/runs/40778455206/job/123133727721) |
| [#294](https://github.com/oxo-ops/dkss/pull/294) | `0732c71eb54cf0d0ec4ca968001abf59e5b4006f` | ドラフト・未マージ | 未合格：postgres [postgres](https://github.com/oxo-ops/dkss/actions/runs/40780574642/job/123140936395) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40780574632/job/123140935972) |
| [#295](https://github.com/oxo-ops/dkss/pull/295) | `54b4e1fd72e14637d67090e0fc5a19b0d41884b6` | マージ済み | 対象checkすべて成功 [regression](https://github.com/oxo-ops/dkss/actions/runs/40778357842/job/123133396620) |
| [#297](https://github.com/oxo-ops/dkss/pull/297) | `87c6a92e29c7ccb2a0620a280d5766fbf900fad3` | マージ済み | 対象checkすべて成功 [regression](https://github.com/oxo-ops/dkss/actions/runs/40776585676/job/123127356503) |
| [#298](https://github.com/oxo-ops/dkss/pull/298) | `990050a99dad527299fa860df6235531e9727ade` | レビュー可能・未マージ | 対象checkすべて成功 [regression](https://github.com/oxo-ops/dkss/actions/runs/40779669732/job/123137838168) / [usage-summary](https://github.com/oxo-ops/dkss/actions/runs/40779669783/job/123137837853) |
| [#300](https://github.com/oxo-ops/dkss/pull/300) | `d80b78315c70fbc38e17de81353ee8abd02eaab2` | マージ済み | 対象checkすべて成功 [regression](https://github.com/oxo-ops/dkss/actions/runs/40778461430/job/123133749648) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40778454883/job/123133732365) |
| [#301](https://github.com/oxo-ops/dkss/pull/301) | `bc67e4bcd4af1e7a22dc1cbbfc0fb0bb0271210a` | マージ済み | 対象checkすべて成功 [regression](https://github.com/oxo-ops/dkss/actions/runs/40777268294/job/123129682287) |

## 一次資料と保全確認

main内：Q04-PR273-integration-20261028.md、Q08-person-history-and-recovery-20261028.md、Q12の上記2資料、実装差分と移行手順。Q03は担当outputsのQ03-final-integration-report-ja.mdとQ03-final-validation-state.json（2236a578）。Q05は共通集計競合修正報告と担当の990050a9再受入24件成功連絡、最新head check。Q10はQ10-acceptance-20261029-report.txt／results.json（0732c71e、基準main037ab51）。異なる対象版の試験件数を重複加算していない。

既存25章のHeading1、24表、改訂履歴表、変更対象外本文を保持。24箇所の局所更新で、既存段落変更20。全24表はXML一致、document.xml以外の18部品はバイト一致、元本文の非対象要素は同一内容・順序。旧Wordハッシュ不変。システム仕様書・Excel・製品コード・DB定義・テストは編集していない。

表示確認：Word 16で読取専用PDF出力し、同梱ラスタ化処理で全ページ画像を作成して確認した。ページ数・ページ外文字・空白ページの最終結果は下記に記録する。

全27ページを表示確認済み。ページ外文字0、空白ページ0。章・表の欠落や文字重なりは確認されなかった。

残作業：Q03のレビュー／マージと実環境受入、Q05依存PR反映後の再受入、Q10重大2問題の担当修正後再受入、Q04実DB索引・復旧手順、Q08旧記録・再承認・本人復元方針、Q11再開条件、Q12残存表示・実機／負荷の合意条件。正式承認・正本認定は行っていない。
