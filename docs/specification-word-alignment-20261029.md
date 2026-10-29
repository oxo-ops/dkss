# システム仕様書・業務方針統合追補（2026-10-29 14:26 JST）

今回の両文書の成果物・SHA・状態・受入境界・採用根拠・全ページ確認・PR一覧は[品質改善計画との統合報告](quality-word-revision-20261029.md)へ集約。既存PR #320で両報告を管理し、新規PRを作成しない。

仕様書：`輸送版DX_システム仕様書_v0.25基準_業務方針統合_確認用_20261029.docx`、75ページ。SHA-256 `081990f7490c72f1b1422ac7f203da978c5bed2a6cb2d3be601935d9819f5d3a`。元73ページ版を不変で保全。19章・2表・2図・改訂履歴・書式・F/U/K番号・正式版番号・承認日を保持。

03章#335、06章M07採用方針／旧manual回復／#337、07/09章#334、16章CSV追加隔離適用・Q04入口・ログイン復旧条件、18/19章未決／履歴、S87–S91を局所追補。M06/M07・Q03ブラウザ未達・旧本人回復未実装・本番復旧未完了を明記し、試験件数・担当工数・進捗は品質改善計画へ分離。全75ページを表示確認した。

---

## 以下は前回までの報告（各時点の記録）

# システム仕様書Word 追加差分追補報告 2026年10月29日13時50分

本追補は前回11:04 JST・main288261dの70ページ版からの追加差分である。前回Wordと下記の前回報告は変更せず保全した。新しい正式版・承認日・正本の認定は行わず、品質改善Word・Excel・製品コード・DB・Render設定は変更していない。

## 保存実物と基準

- 更新版ファイル：`輸送版DX_システム仕様書_v0.25基準_追加差分追補_確認用_20261029.docx`
- 保存先：`C:\Users\takah\Documents\Codex\2026-10-28\dx-oxo-ops-dkss-q02-q03\outputs\輸送版DX_システム仕様書_v0.25基準_追加差分追補_確認用_20261029.docx`
- SHA-256：`b7b8665c311e5feb6cc03cddacd6879116222072a2f365628742ad305a27d1db`
- 最終実物は73ページ。全ページ表示確認済み。19章・2表・2図・既存改訂履歴・書式・F/U/K番号・正式版番号・承認日を維持。
- 保全した70ページ版：`C:\Users\takah\Documents\Codex\2026-10-28\dx-oxo-ops-dkss-q02-q03\outputs\輸送版DX_システム仕様書_v0.25基準_整合追補_確認用_20261029.docx`
- 保全版SHA-256（不変）：`213224216beb487033a9e98518c8258034f4bec4db75982f1edf4d4dc4d21462`
- 最終照合基準：2026年10月29日13:50 JST、main `bdab9d85159d2091e1e3b09ed1f49e395eef3167`。初回13:31のmain1741c64確認から、提出前の追加マージを反映した。基準以降の変更は次回照合とする。
- 対象：#323・#324・#325・#326・#327・#329。#330・#331・#332は初回未マージだったが13:50には全てマージ済み。新たにmainへ入った#333も差分・資料・最終head CIを確認した。
- GitHubコネクタ接続エラーのため、認証済みGitのfetchとGitHub RESTメタデータ／checksを読取照合。製品の再実行・DB適用・外部サービス操作は行っていない。

## 採用根拠と状態区分

既存業務仕様を変更する独断判断は行っていない。以下は主にB（main実装・対象試験）の追加であり、実装の存在、対象head CI成功、担当の隔離受入、実運用環境での適用／業務受入を別判定にした。試験件数・工数・性能測定の詳細はシステム仕様書へ転記していない。

|根拠|採用した確認済み事項|残る条件・範囲外|
|---|---|---|
|[#323](https://github.com/oxo-ops/dkss/pull/323)|AI振り返りの古い入力は再表示へ復帰。BFCache復元時は作成中のGET状況確認だけを再開。復元だけでPOST／新規有料生成を行わない|コントローラーと模擬HTTP応答のChrome検証。実画面全体の新規データ受入・実AI接続ではない|
|[#324](https://github.com/oxo-ops/dkss/pull/324)|共通車両ヘッダー／使用車両切替でtruck表示用96/192/384px PNGをsrc/srcset使用。原本・他車種・寸法保持|低速Chrome／架空データの条件付き効果。通常条件の一貫した高速化・全再表示改善は確認されず、mobile戻る時の原本再取得・CLS・実S3／実機／配信層は残受入|
|[#325](https://github.com/oxo-ops/dkss/pull/325)|パトロールnew・車両回答save-one/save-detailで保存前操作者UUID／会社／現在権限等を再照合し保持。消失・不一致409 rollback|操作者の保護であり対象者の表示〜保存の選択世代や全保存経路の完了ではない。DDL追加なし|
|[#326](https://github.com/oxo-ops/dkss/pull/326)|News新規／宛先変更で署名付き選択証跡と現在人物を保存前照合、人物ロック維持。古いPOSTを部分保存せず拒否|動的配信・編集時再通知なし・保存済み旧UUIDを維持。誤配送済みデータの自動是正なし。日報手動設定は対象外。DDL追加なし|
|[#327](https://github.com/oxo-ops/dkss/pull/327)|運行実績CSV受付専用owner_identity／会社所有者索引。新規HTTP受付UUID固定、旧NULL404保留、私有受付のno-storeと会社共有完了原本の区別|追加移行は前回リハーサル対象外。主管のバックアップ複製先追加受入・本番適用は完了証拠未確認|
|[#329](https://github.com/oxo-ops/dkss/pull/329)|README・運用手順、factory/import／Gunicorn hook／組込／明示OCRの境界。OCRループ／lease例外ログの限定秘匿|初回資料のPR未作成は旧時点。新規Windows／架空SQLiteの確認は配備・実停止時間・Q11復旧ではない|
|[#330](https://github.com/oxo-ops/dkss/pull/330)|安全／通常車両のapproval_versionをロック下で保存直前照合。全列＋最新イベントによる旧版・欠落・改変は409 rollback|一般承認・会社境界・本人UUID・先頭未承認順を維持。標準日常点検専用判断、差戻し自体の条件は変更せず、全競合解決ではない|
|[#331](https://github.com/oxo-ops/dkss/pull/331)|CSV追加移行の運用索引反映。非loopback遮断・新規SQLiteで現行Linuxの実Gunicorn／OCR／通常SIGTERMを確認する試験と最終head回帰CI成功|Linux個別成功マーカーの生ログ取得はHTTP401で不可。試験追加・CI成功と個別ログ検証を区別。配備台数・実停止時間・復旧受入は未確認|
|[#332](https://github.com/oxo-ops/dkss/pull/332)|HTTP共通例外ログを固定イベント・段階・error_typeに限定し、既存rollback／HTML・API応答／復帰案内を保持|架空値・一時SQLiteの再現／試験。実際の本番漏えい・全ログ監査完了は認定しない|
|[#333](https://github.com/oxo-ops/dkss/pull/333)|通知設定初回並行保存の親行重複防止。Vehicle→User→設定で直列化し各保存の本人証跡を保持|同世代全リスト後勝ちは未解決の業務判断。既存重複の自動整理なし。安全新規フォームの受付冪等性は別課題|

## CSV追加移行の4区分

|区分|確認した状態|
|---|---|
|コード|#327マージ済み。vehicle_operation_import_draft.owner_identity VARCHAR(36) NULL、非一意索引ix_operation_csv_company_owner(company_code, owner_identity)。OCR受付テーブルとは別|
|手順|tools/upgrade_operation_csv_owners.pyと専用Q03_CSV_OWNER_MIGRATION_DATABASE_URLが存在。DATABASE_URL fallbackなし。書込停止・既存バックアップ／baseline準備・列準備後の新アプリ切替。#331で運用索引にも反映|
|隔離適用|担当の使い捨てSQLite／PG・CI所有schemaによる列追加、旧原値保持、再実行、既存移行との順序独立、不整合拒否・異常rollbackの成功報告と当該head CIを確認。前回main288261dの移行リハーサルの成功へ混ぜない。移行主管のバックアップ複製先での追加受入は完了証跡未確認|
|本番適用|本作業では未実施。最新の適用済みschema・実行記録・アプリ切替・ログイン復旧・受入完了の証跡は未確認。CLIの存在／マージ／CIを適用完了へ読み替えない|

旧NULLを氏名・username・数値IDから補完しない。列・索引・原本・旧行を保持する。切戻し時に旧username認可を再開しないよう、CSV私有経路を停止するかUUID照合を維持した版を使用する。主管の適用順序・承認を本書で独断確定しない。

## 章別変更と保持

|章|今回の局所変更|
|---|---|
|表紙・01|13:50のmainと追補範囲、初回13:31からのPR状態更新、#320／#328の別範囲を明記|
|03|保存時操作者の追加保護、通常承認の回答版照合。対象外経路を明示|
|06|CSV受付UUIDと旧NULL保留・確定／再送・車両追加APIの対象範囲|
|07|AI再表示／ページ復元とtruck派生アイコンの実装。実測条件と未受入環境を分離|
|08・09|CSV専用追加DDLと私有受付／会社共有完了原本・no-storeの区分|
|11|News宛先の世代照合、通知設定親の初回並行保存、残る後勝ち判断|
|14・15|OCR／HTTP診断ログの保護範囲、CSV切戻し条件|
|16|CSVコード・手順・隔離適用・本番適用を4区分。実行環境／停止の境界、Render旧確認事実と現在未確認の区別|
|17・18|追加マージの時点、日報手動設定・M06/M07・復元／受入等の残課題|
|19・参照|確認用追補履歴とS81〜S86を追加。正式版／承認日は変更なし|

02・04・05・10・12・13は前回基準以降の差分から直接変更する根拠がなく維持。全19章を差分観点で確認し、前回までの本文・決定済みルール・F/U/K段落はそのまま保持。24箇所の編集／追記で、既存段落の変更は表紙2箇所と本番確認段落1箇所のみ。新しい参照見出しは本文と離れないよう局所的に連結した。

## 本番の報告時点と未確認部分

10月29日の利用者報告で、本番SHA18ae141b、Auto-Deploy Off、接続先／schema確認済み、user.account_identity・Q03関連列・vehicle_document_import_draft.owner_identity等の欠落、checklist_event.created_at VARCHAR(30)、PITR過去3日、旧エクスポート10月27日16:50は確認済み事実として維持した。これらを未確認へ戻していない。

当時の最新エクスポート・隔離復元・本番DB移行・ログイン復旧は未完了との報告だった。今回のGitHub照合では、それ以降の本番状態や各完了結果を更新できる証跡は取得していない。本番が現在も旧SHAと再測定したものではなく、本番復旧完了とも判断していない。

## 維持した未決・残作業

- 日報本人閲覧の手動設定はdriving_access.assignのexpected_identity未指定経路等が残る。前回から当該製品経路の変更なし。News宛先・操作者・CSV・通常承認・通知設定の修正を根拠に解消済みとしない。
- M06の車検／12か月点検正規化、M07の合計訂正後の請求差替えと履歴整合は、解消差分・受入証跡がなく未解決を維持。現行の拒否や内部区分を正式業務仕様へ追認しない。
- 旧本人の根拠付き復元、旧通知／承認の保留解除、対象者選択の未保護経路、同世代通知設定の競合方針、安全フォーム冪等性、既存重複親整理は別課題／判断待ち。コード修正は行わない。
- 運用責任者・台数・ログ管理・承認条件、RPO/RTO、実S3・実容量・旧版での画面／登録／添付、配備条件下ワーカー停止再開、本番業務受入を既存条件どおり維持。
- 正本の正式認定、別紙1〜5の実物を伴う同期、CSV追加移行の主管受入・本番適用証跡の反映は残作業。

## 物理・構造確認

Word16の読取専用PDF出力と同梱render_docx.pyのラスタ化処理を使用。73ページすべてを表示確認。最終局所書式調整で変わった59〜61ページを再表示確認し、他70ページは直前確認済み画像とバイト単位一致。ページ外文字0、空白ページ0。既存の明示改ページと短いページは保持した。

19章の見出し列・2表のXMLは一致。2図を保持し、document.xml以外の24パッケージ部品はバイト単位一致。変更対象外の全要素は正規化XMLの原順序で一致。全F/U/K番号付き段落は本文ごと前回Wordと一致。改訂履歴の旧段落を削除していない。前回70ページWordと品質改善Wordのハッシュ不変を確認した。製品テスト・移行適用は今回再実行していない。

## 報告PRの範囲整理

#328は前回の仕様書報告でマージ済み、#320は未マージの旧品質改善Word報告（docs/quality-word-revision-20261029.md、08:23基準）である。双方のファイルと対象時点を比較し、今回の仕様書追加差分と重複しないと判断した。#320への便乗・品質改善報告更新・同一差分の複数PR作成は行わない。独立ブランチdocs/spec-followup-20261029で既存docs/specification-word-alignment-20261029.mdへ本節を追補し、前回報告を下にそのまま保つ。リポジトリへは報告1ファイルのみ、Wordは上記outputs保存で管理する。

## 最終headとCI証跡

13:50確認分（#333の詳細は同mainに含まれることも確認）。対象headの全チェックsuccessを確認。CI成功と本番受入は別状態。

|PR|最終head|確認したチェック|
|---|---|---|
|[#323](https://github.com/oxo-ops/dkss/pull/323)|`6e76518347fa998769d1cf5e7840eff3ea0445f2`|[regression](https://github.com/oxo-ops/dkss/actions/runs/40805041589/job/123227425973) / [CodeQL](https://github.com/oxo-ops/dkss/runs/123222122507) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40805041612/job/123221842664) / [browser](https://github.com/oxo-ops/dkss/actions/runs/40805041612/job/123221842436) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40805041685/job/123221842343) / [readership](https://github.com/oxo-ops/dkss/actions/runs/40805041596/job/123221842335) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40805041595/job/123221842278)|
|[#324](https://github.com/oxo-ops/dkss/pull/324)|`76904dedbbc1df82b669b82f5926e6a5cc6a5558`|[CodeQL](https://github.com/oxo-ops/dkss/runs/123233431708) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40808541430/job/123233153283) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40808535467/job/123233130394) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40808535507/job/123233130235) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40808535380/job/123233130131) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40808535460/job/123233129884) / [document-display](https://github.com/oxo-ops/dkss/actions/runs/40808535399/job/123233129858) / [browser](https://github.com/oxo-ops/dkss/actions/runs/40808535380/job/123233129650)|
|[#325](https://github.com/oxo-ops/dkss/pull/325)|`6c11e9d46447b18249f9a37a637600ee6fb4fe09`|[CodeQL](https://github.com/oxo-ops/dkss/runs/123232122856) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40808112825/job/123231786176) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40808112758/job/123231786006) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40808112709/job/123231785708) / [postgres-masters](https://github.com/oxo-ops/dkss/actions/runs/40808112689/job/123231785702) / [browser](https://github.com/oxo-ops/dkss/actions/runs/40808112618/job/123231785554) / [postgres-identity](https://github.com/oxo-ops/dkss/actions/runs/40808112706/job/123231785531) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40808112620/job/123231785507) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40808112687/job/123231785506) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40808112618/job/123231785306)|
|[#326](https://github.com/oxo-ops/dkss/pull/326)|`266a59934a1d18003c66ff5ca6128fba5eb094ca`|[regression](https://github.com/oxo-ops/dkss/actions/runs/40808856716/job/123238972666) / [postgres-identity](https://github.com/oxo-ops/dkss/actions/runs/40809213934/job/123235287905) / [CodeQL](https://github.com/oxo-ops/dkss/runs/123234386600) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40808856746/job/123234155151) / [browser](https://github.com/oxo-ops/dkss/actions/runs/40808856633/job/123234155012) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40808856633/job/123234154746) / [postgres-masters](https://github.com/oxo-ops/dkss/actions/runs/40808856613/job/123234154708) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40808856661/job/123234154687) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40808856658/job/123234154623) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40808856610/job/123234154519)|
|[#327](https://github.com/oxo-ops/dkss/pull/327)|`6cd76fbd59a2a1fed3350d54ba36256254fc8ac3`|[CodeQL](https://github.com/oxo-ops/dkss/runs/123242750290) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40811443998/job/123242450556) / [browser](https://github.com/oxo-ops/dkss/actions/runs/40811443998/job/123242450365) / [postgres-identity](https://github.com/oxo-ops/dkss/actions/runs/40811443892/job/123242450076) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40811444006/job/123242449755) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40811443967/job/123242449713) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40811443889/job/123242449678) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40811443935/job/123242449587) / [postgres-csv-owner](https://github.com/oxo-ops/dkss/actions/runs/40811443968/job/123242449484) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40811443903/job/123242449468) / [postgres-mfa](https://github.com/oxo-ops/dkss/actions/runs/40811443964/job/123242449400) / [postgres-masters](https://github.com/oxo-ops/dkss/actions/runs/40811443879/job/123242449398) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40811443912/job/123242449200)|
|[#329](https://github.com/oxo-ops/dkss/pull/329)|`ff6142a37fd1576dd2892911a4fdb4c800d9366a`|[CodeQL](https://github.com/oxo-ops/dkss/runs/123255948404) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40815558240/job/123255652245) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40815558236/job/123255652154) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40815558164/job/123255652089) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40815558217/job/123255651992) / [browser](https://github.com/oxo-ops/dkss/actions/runs/40815558236/job/123255651936) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40815558161/job/123255651928) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40815558167/job/123255651689)|
|[#330](https://github.com/oxo-ops/dkss/pull/330)|`47fb098f98435e4cf2d4209f2b8287a605cba9a1`|[CodeQL](https://github.com/oxo-ops/dkss/runs/123263664714) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40817895456/job/123263205540) / [browser](https://github.com/oxo-ops/dkss/actions/runs/40817895285/job/123263205264) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40817895317/job/123263205136) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40817895351/job/123263205094) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40817895285/job/123263205067) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40817895282/job/123263204990) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40817895248/job/123263204860) / [postgres-csv-owner](https://github.com/oxo-ops/dkss/actions/runs/40817895236/job/123263204818) / [postgres-identity](https://github.com/oxo-ops/dkss/actions/runs/40817895247/job/123263204772) / [postgres-masters](https://github.com/oxo-ops/dkss/actions/runs/40817895245/job/123263204662)|
|[#331](https://github.com/oxo-ops/dkss/pull/331)|`3454ad9d0f88d265b891fd9f0d465f6b049a1e1d`|[CodeQL](https://github.com/oxo-ops/dkss/runs/123262817219) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40817706491/job/123262583033) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40817706520/job/123262583006) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40817706513/job/123262582788)|
|[#332](https://github.com/oxo-ops/dkss/pull/332)|`283ed0d1fce96b7a70747e35f06a767ea03c0855`|[CodeQL](https://github.com/oxo-ops/dkss/runs/123263055198) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40817738640/job/123262687839) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40817738490/job/123262687067) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40817738382/job/123262686837) / [postgres-csv-owner](https://github.com/oxo-ops/dkss/actions/runs/40817738376/job/123262686687) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40817738235/job/123262686240) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40817738303/job/123262686190) / [browser](https://github.com/oxo-ops/dkss/actions/runs/40817738235/job/123262685955) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40817738250/job/123262685797)|
|[#333](https://github.com/oxo-ops/dkss/pull/333)|`fb381bcf294e4a9f8dd415f1316e13b26d56441b`|[CodeQL](https://github.com/oxo-ops/dkss/runs/123264222677) / [Analyze Python](https://github.com/oxo-ops/dkss/actions/runs/40818105510/job/123263894819) / [postgres-notify-setting](https://github.com/oxo-ops/dkss/actions/runs/40818105465/job/123263894538) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40818105408/job/123263894365) / [regression](https://github.com/oxo-ops/dkss/actions/runs/40818105380/job/123263894217) / [postgres-masters](https://github.com/oxo-ops/dkss/actions/runs/40818105373/job/123263894059) / [browser](https://github.com/oxo-ops/dkss/actions/runs/40818105298/job/123263893983) / [pip-audit](https://github.com/oxo-ops/dkss/actions/runs/40818105310/job/123263893764) / [identity](https://github.com/oxo-ops/dkss/actions/runs/40818105327/job/123263893681) / [postgres](https://github.com/oxo-ops/dkss/actions/runs/40818105298/job/123263893662) / [postgres-csv-owner](https://github.com/oxo-ops/dkss/actions/runs/40818105324/job/123263893602) / [postgres-identity](https://github.com/oxo-ops/dkss/actions/runs/40818105311/job/123263893590)|

---

## 前回記録 2026年10月29日11時04分

以下は#328に保存した当時の報告をそのまま保持する。以降の状態は上記最新追補を参照する。

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
