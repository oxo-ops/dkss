# 輸送版DX 仕様書とmainの整合性確認

確認日：2026年10月28日（日本時間）。コード基準：main `6d7d8c9ccc7bd661cd86a6b5fa68b99da2a7c668`（PR #272まで）。

最終追加照合：main `c7efecbc3ede1c7c44855d1f768544531eee3172`（PR #277まで）。以下の19章照合は初回基準を保持し、追加差分だけを末尾の追補へ記録する。

仕様書v0.18と添付v0.25を重要な比較資料として全19章照合し、[両資料の内容・更新履歴の比較一覧](specification-version-comparison-20261028.md)と[章別変更案](specification-change-proposals-20261028.md)を作成した。利用者の補足により、正本は現時点で未確定として扱う。v0.25に新しい内容が含まれるという調査結果と、正式な正本の選定を区別する。どちらのWordも更新・版上げしていない。

## 正本と参照版

| 資料 | 確認できたこと | 今回の扱い |
| --- | --- | --- |
| システム仕様書の正本 | 現時点で未確定との利用者補足 | v0.18・v0.25のいずれも独断で正本にしない |
| transport_dx_system_spec_v0.18_20261025.docx | Downloads内の実物と全19章・改訂履歴・S01〜S45・U01〜U39・K01〜K20を確認 | 重要な比較資料。v0.25との共通・置換・追加を照合 |
| 輸送版DX_システム仕様書_v0.25_20261028.docx | 本体01〜19章、F番号、U01〜U40、K01〜K58、S01〜S67、19章の改訂履歴を確認 | 照合用参照版。正本とは扱わない |
| 別紙1〜5・登録待ち車両と資料紐付け仕様 | 本体に参照あり。同版資料一式は未照合 | 本体との同版性・同期状態は未確認。今回の比較対象へ混在させない |
| 品質改善と検証計画Word | システム仕様書と別の管理資料 | 今回の仕様比較・更新案の採用根拠から除外。内容・進捗を転記せず未編集 |
| mainのdocs | Markdown40ファイルと性能測定JSON2ファイルを棚卸し | 技術記録。各文書の基準版を保持し、現在の状態と区別 |

参照ファイルのSHA-256（元ファイルは変更していない）：

- 仕様書v0.25：`d10255a317481e64654e37bd3e1f322a08cfad48b06ad6530a7b59955831b365`
- 仕様書v0.18：`213bd0c320bd97ca4f4fbddf85f36e7cb709a684784b7226faa8728584a2997b`

v0.23は初回の本人確認を必須としていたが、v0.24で一意に特定できる日報の初回自動表示へ改訂され、v0.25で整備後請求書の実施済み表示・点検計画からの原本参照が追加されている。古いS番号や版の記録を削除せず、後続改訂を対応付ける。添付内の「実行する」「反映する」等は当時の資料内容として読み、今回の作業指示には採用していない。

## 状態の読み方

- **A 確定仕様としての採用記述を確認した事項**：両資料の共通記述、またはv0.25の後続採用記述。資料に書かれていることと、正本・正式な承認版の確定を区別し、新しい業務判断は追加しない。
- **B 実装状況**：基準mainのコード・既存テスト・対象版のCIから確認できる範囲。main反映、試験成功、実環境受入、配備を分ける。
- **C 未決定事項**：業務・移行・運用判断の不足。技術的な未検証はBの未検証としても記録し、採用済みの業務ルールを未決へ戻さない。

この作業ではコード・DB定義・テスト・画面資材・管理Excel・品質改善計画Wordを変更していない。アプリ起動、DB接続、試験再実行、有料AI、本番操作は行っていない。以下の成功件数は既存の記録・CIの読取結果であり、今回の再実行結果ではない。

## 19章の照合結果

| 章 | 章名 | 結果と変更案の要点 | 根拠 |
| --- | --- | --- | --- |
| 01 | 文書概要 | 旧基準を履歴化し、今回のコード基準を追加。正本・参照版・配備版を区別 | R01、R02 |
| 02 | システム概要 | app.py集中の現在形を見直し、factory・責務別モジュールを記載 | R03 |
| 03 | 利用者と権限 | Aを維持。本人自動特定と現在の認可再照合のBを追加 | R04、R05 |
| 04 | 業務仕様 | 請求書と点検修理接続のBを追加。判断・再確認の分離は維持 | R06、R07 |
| 05 | 機能一覧 | v0.25でF093が追加されていることをv0.18と対照確認。既存IDを維持し、別紙1の同期は保留 | R01 |
| 06 | 機能仕様 | 日報、OCR、請求書、整備接続、マスタ、AIの状態を局所追記。車検統合は不一致として残す | R04〜R11 |
| 07 | 画面仕様 | 日報主要導線、候補訂正、OCR画面内進捗、請求書概要のBを追加 | R04、R06、R08 |
| 08 | データ仕様 | 40モデルは旧版集計と明記。現在の生成資料66テーブル、IDと文字列の併存を記録 | R03、R05、R07、R09 |
| 09 | ファイル仕様 | 一般添付とOCR受付上限を分離。共有原本・再送のBを追記 | R08、R10 |
| 10 | 外部連携仕様 | 外部AIへの送信と結果保存の境界を追記。AIRIA等の未決は維持 | R05、R08 |
| 11 | 通知仕様 | 本人宛操作・候補・ITCお知らせの境界試験を追記。旧履歴と実配信は未確定 | R05、R12 |
| 12 | 帳票仕様 | 日報の本人範囲と保留、点検Excelの範囲表示を追記。一般整備概要はExcel対象外 | R04、R06、R13 |
| 13 | 非機能要件 | 性能測定の条件と限定PostgreSQL試験を区別。SLA・負荷を確定しない | R09、R10、R14 |
| 14 | セキュリティ | MFA失敗回数の永続監査・ロック、認可取消し、CSRFのBを追記 | R05、R12 |
| 15 | 障害時仕様 | 紙・Excelの業務原則を維持。OCR再開と総合復旧の未確認を区別 | R08、R15 |
| 16 | 運用と保守 | 初期化・移行・ワーカーの現行コードと、両仕様書の復旧未決条件を整理 | R03、R08〜R10、R15 |
| 17 | 制約と前提 | 配備・実設定・契約の未確認を維持。コード確認を運用開始へ読み替えない | R01、R15 |
| 18 | 未決事項 | U番号を維持し、判断待ち・実装あり・未試験を整理。新U番号は採番しない | R01、R04〜R15 |
| 19 | 改訂履歴 | 正本へ適用してから履歴を追加。今回は調査・変更案のみの記録 | R01、R02 |

全章の一次照合を実施したことは、全機能の動作検証・別紙全セル照合・業務受入完了を意味しない。

## 不一致と重複と欠落

| ID | 対象 | 観測事実と取扱い |
| --- | --- | --- |
| D01 | 01・02・07・08・18 | 参照コードが7d53c6b、feb5eff、c811829等に分散。過去時点を維持し、今回の基準SHAを別に置く。正式運用版は決定しない |
| D02 | 02・08 | app.py集中・40モデル462カラムは旧版。現在はfactory・モジュール分離、生成資料は66テーブル。モデル数・表数・本番表数を同じ母集団にしない |
| D03 | 06・18 | PR #148の「未マージ」は当時の状態。2026-10-26にマージ済み。現在のコードに結果鮮度の照合あり。個別挙動の本番受入は未確認 |
| D04 | 03・06〜08・18 | S66の本人自動特定は#244でmain反映。技術資料には手動確認必須と自動表示が併記され、表現が矛盾。後続の自動特定を優先する旨の技術変更案を用意 |
| D05 | 06・08 | 点検とカルテの接続を一律「未完」とする記述に対し、関連モデルと点検修理の引継ぎ処理が存在。存在する経路だけBへ移す。全経路完成とはしない |
| D06 | 06・08・18 | Aでは車検と12か月点検を独立管理。現在の`normalize_kind()`は`vehicle_inspection`を`12month`へ変換し、年間区分を共有する。採用仕様へ追認せず、意味・表示・実施連動への影響を照合待ちとする |
| D07 | 06・18・K57 | 元請求100＋追加30→読取合計140→追加請求30を20へ訂正すると、反映履歴130との不一致で400。二重計上防止の拒否試験は成功しているが、訂正継続の制約は未解消。正式な業務仕様にはしない |
| D08 | 06・18 | リスク説明と評価表を一律「適用未確認／未実装」とする旧記述に対し、risk_contractと行列評価コードが存在。ただし同梱policyはdraft・規則空・期間未設定。評価方式の採用・実車適用は未決 |
| D09 | docsの試験記録 | 「今回未反映」「PostgreSQL未検証」が当時の記録として残る。PR #228、#258、#259、#264、#268の後続反映と限定CIを別記。全業務のPostgreSQL合格へ拡張しない |
| D10 | 13・16 | 構造資料の「起動時DDLなし」はfactory/import範囲では確認できるが、現在のGunicorn worker初期化には日報・連結テーブル初期化呼出しがある。起動全体の保証と区別する |
| D11 | 03・06・07・08・18 | 本人特定・候補・権限・集計の説明が複数章に重複。参照元を残し、同じAを一度定義して各章ではBと残条件だけを追記する案とする |
| D12 | 08・11・14 | Notification等のusername参照と、DrivingReportReader.user_id等が併存。旧通知・承認JSON・表示名を現ユーザーへどう引き継ぐかの決定根拠が不足 |
| D13 | 文書一式 | 正本は未確定。v0.18・v0.25本体は比較済み。別紙1〜5・登録待ち仕様の同版性と元の合意資料の一部は未確認。S番号の引用だけで元資料を再検証したとは扱わない |

## 未決定事項と未検証範囲

| 関連 | 判断・確認が必要な事項 | 現時点で確定しないこと |
| --- | --- | --- |
| Q03・U19・U21 | 本人ID化の対象列、氏名・ログインID変更、削除再登録、当時表示と現在参照、併存・移行・切戻し | 全username参照の一括ID化、旧履歴の新アカウントへの自動移管 |
| Q03・Q08・U08・U15・U21 | 旧通知の宛先、旧承認者・候補JSON、同名ID再利用、保存期間、閲覧範囲、表示名不足 | 旧通知・承認履歴の自動書換え、履歴の削除・統合 |
| Q04・U02・U23 | 名称参照と履歴スナップショットの分類、納入先等の残経路、同一会社複合参照、年間区分の意味 | 名称参照を直ちに不具合と判定、全マスタID移行 |
| Q05・U03・U16・U18・U19 | 過去日時の基準、回答番号の旧形式、snapshot更新、実施者と代理入力者、実データの補正根拠 | 過去値の推定補完、日時型への一括変換 |
| Q07・U22・U32 | 読取金額訂正と確定請求履歴の整合、意味的重複、税・端数・配分、既存部品同期の網羅 | D07を許容業務仕様に変更、請求取消の自動逆仕訳 |
| Q08・U21 | 監査と業務履歴の保持・再現、NULL・論理削除・再登録、重要操作の記録漏れ | 不明な過去日時や作成者の創作 |
| Q10・Q11・U01・U04・U05・U36 | PostgreSQLの残る競合・移行・負荷、実ブラウザ・実資料・実AI、ワーカー停止・再開、DB＋添付＋設定＋鍵の総合復旧 | 限定CIによる全業務合格、本番採用、RPO/RTO・200同時利用保証 |
| U02・U11・U12・U14 | 業務権限・委任、運用窓口・実作業者・代替、受付時間、開始判断者 | 役割・担当・期限の独断割当 |
| U09・U13・U31・U39・U40 | AIRIA方式・契約、SMTP/Push実配信、メーカー資料適用、評価規則・期間、最低記録量 | 全メーカー取得、承認済みリスク基準、運転者責任・故障確率の確定 |

## 証拠台帳

コードリンクは全て基準mainの不変SHAを使用する。技術資料のローカル相対リンクは本ブランチから確認できる。PRのマージはGit履歴で照合し、主要PRはGitHubメタデータのmerged=trueとも照合した。

| 根拠 | 資料とコード | 確認範囲 |
| --- | --- | --- |
| R01 | 仕様書v0.18と添付v0.25の01〜19章・改訂履歴・参照資料、今回の利用者補足 | 資料内の採用記述と内容の新旧を確認。正本は未確定。品質改善計画は別管理として除外 |
| R02 | [main基準](https://github.com/oxo-ops/dkss/tree/6d7d8c9ccc7bd661cd86a6b5fa68b99da2a7c668)、[PR #272](https://github.com/oxo-ops/dkss/pull/272)、[PR #148](https://github.com/oxo-ops/dkss/pull/148) | main到達とマージ状態。#148のmergeは`3f867d590cf40b79240a49b1e1165d3a240821be` |
| R03 | [構造](application_architecture.md)、[ER・列定義](database_schema.md)、[factory](https://github.com/oxo-ops/dkss/blob/6d7d8c9ccc7bd661cd86a6b5fa68b99da2a7c668/dkss_app/__init__.py)、[Gunicorn](https://github.com/oxo-ops/dkss/blob/6d7d8c9ccc7bd661cd86a6b5fa68b99da2a7c668/gunicorn.conf.py) | 入口、明示初期化、worker hook、現在の生成表数 |
| R04 | [本人表示](driving-admin-self.md)、[複数車両](driving-person-vehicles.md)、[集計保留](driving-spec-gaps-20261028.md)、[導線](driving-analysis-navigation.md)、[PR #244](https://github.com/oxo-ops/dkss/pull/244)、[PR #262](https://github.com/oxo-ops/dkss/pull/262)、[PR #271](https://github.com/oxo-ops/dkss/pull/271) | 自動特定、本人集計と権限の分離、画面・戻り先 |
| R05 | [取込中の失効](q02_import_midflight_revocation_20261028.md)、[PR #270](https://github.com/oxo-ops/dkss/pull/270)、[認可コード](https://github.com/oxo-ops/dkss/blob/6d7d8c9ccc7bd661cd86a6b5fa68b99da2a7c668/dkss_app/access.py)、[日報認可](https://github.com/oxo-ops/dkss/blob/6d7d8c9ccc7bd661cd86a6b5fa68b99da2a7c668/dkss_app/driving_access.py) | 現利用者・会社とジョブの段階境界。外部送信取消しの保証なし |
| R06 | [請求書実施概要](quality/invoice-plan-summary-20261028.md)、[PR #251](https://github.com/oxo-ops/dkss/pull/251)、[請求書境界](q02_invoice_plan_boundaries_20261028.md)、[計画境界](q02_inspection_plan_boundaries_20261028.md) | 実施済み・日付不明・原本・通常整備と予定の分離 |
| R07 | [モデル](https://github.com/oxo-ops/dkss/blob/6d7d8c9ccc7bd661cd86a6b5fa68b99da2a7c668/dkss_app/models.py)、[カルテ処理](https://github.com/oxo-ops/dkss/blob/6d7d8c9ccc7bd661cd86a6b5fa68b99da2a7c668/dkss_app/vehicle_karte.py)、[点検](https://github.com/oxo-ops/dkss/blob/6d7d8c9ccc7bd661cd86a6b5fa68b99da2a7c668/dkss_app/checklists.py) | VehicleMaintenanceInspectionLink、carry_inspection_repair_to_maintenance、persist_vehicle_inspection_repair。全経路の完成判定はしない |
| R08 | [OCRキュー](document_import_queue.md)、[共通整合性](domain_consistency_20261027.md)、[現在のキュー](https://github.com/oxo-ops/dkss/blob/6d7d8c9ccc7bd661cd86a6b5fa68b99da2a7c668/dkss_app/document_import_queue.py)、[PR #245](https://github.com/oxo-ops/dkss/pull/245)、[PR #265](https://github.com/oxo-ops/dkss/pull/265) | 永続受付、上限、リース・再開、元画面内進捗。外部OCRは別途受入 |
| R09 | [PR #258](https://github.com/oxo-ops/dkss/pull/258)、[#259](https://github.com/oxo-ops/dkss/pull/259)、[#264](https://github.com/oxo-ops/dkss/pull/264)、[#268](https://github.com/oxo-ops/dkss/pull/268)、[初期化](https://github.com/oxo-ops/dkss/blob/6d7d8c9ccc7bd661cd86a6b5fa68b99da2a7c668/dkss_app/database.py)、[マスタ](https://github.com/oxo-ops/dkss/blob/6d7d8c9ccc7bd661cd86a6b5fa68b99da2a7c668/dkss_app/masters.py) | 営業所・車種の会社内一意索引、対象行ロック、関連保存の共有ロック、限定PostgreSQL試験 |
| R10 | [共通整合性](domain_consistency_20261027.md)、[旧日付費用](quality/Q07-cost-date-consistency-20261028.md)、[費用訂正](quality/Q07-invoice-lifecycle-20261028.md)、[再取込制約](quality/Q07-invoice-reimports-20261028.md)、[PR #261](https://github.com/oxo-ops/dkss/pull/261)、[#267](https://github.com/oxo-ops/dkss/pull/267)、[#269](https://github.com/oxo-ops/dkss/pull/269) | 費用日付・原本共有・逐次再送・ロールバックとD07 |
| R11 | [点検計画](https://github.com/oxo-ops/dkss/blob/6d7d8c9ccc7bd661cd86a6b5fa68b99da2a7c668/vehicle_inspection_plans.py)、[リスク計算](https://github.com/oxo-ops/dkss/blob/6d7d8c9ccc7bd661cd86a6b5fa68b99da2a7c668/vehicle_risk_assessment.py)、[同梱policy](https://github.com/oxo-ops/dkss/blob/6d7d8c9ccc7bd661cd86a6b5fa68b99da2a7c668/vehicle_risk_policy.json) | normalize_kind、certificate_evidence、評価コードと不活性draftを分離 |
| R12 | [MFA](q02_mfa_cookie_replay_20261027.md)、[候補API](q02_directory_boundaries_20261028.md)、[整備知識](q02_knowledge_boundaries_20261028.md)、[お知らせ](q02_news_boundaries_20261028.md)、[PR #228](https://github.com/oxo-ops/dkss/pull/228) | 通知・認証・原本境界。旧通知移行・実配送・全業務競合の保証なし |
| R13 | [退避差分の反映](preserved_local_changes_20261027.md)、[日報詳細](driving-report-detail-ui.md)、[燃料](driving-fuel-evidence.md)、[比較](driving-report-comparisons.md) | 出力条件・原文と数値・現在表現と旧表現の衝突 |
| R14 | [読取性能](read_path_performance_20261025.md)、[JSON](read_path_performance_20261025.json)、[分析再利用JSON](analysis_read_cache_20261027.json)、[日付記録](quality/Q05-checklist-business-dates-20261027.md)ほか下記Q05資料 | 一時SQLite・逐次・外部呼出し0と境界日付。性能保証にはしない |
| R15 | 両仕様書の13・15〜18章、U05・U06・U12〜U14 | 共通の障害時業務・運用・復旧未決条件。品質改善計画の復旧進捗は仕様本文へ取り込まない |

### 既存CIの直接確認

| 対象 | 対象head・結果 | 証拠と限界 |
| --- | --- | --- |
| #228 | `a870414a2b9b3ee3d024daaccfa7d7a33274169c`、postgres-mfa success | [専用ジョブ](https://github.com/oxo-ops/dkss/actions/runs/40488740632/job/122137032590)。4件はテスト定義に対応。MFAだけの専用環境 |
| #268 | `1f82b6c182b5c0c2ff1c491751f0a6ba2d8e74fb`、postgres-masters success | [専用ジョブ](https://github.com/oxo-ops/dkss/actions/runs/40671840117/job/122760294562)。取得ログは前半省略あり。後半の16・4・16・8件は各OK。PostgreSQL 18.6。SQLite85件＋基盤8件は別ステップ |
| #270 | `7d46ea5d4904f7cb4c8b649a040d61c8dac85f5f`、regression・pip-audit・Analyze Python・CodeQL success | [回帰ジョブ](https://github.com/oxo-ops/dkss/actions/runs/40672210037/job/122761554127)。PR headの結果。配備確認ではない |
| #272 | `1447f8157791f8a28c1e0fc1c36a86ba64ef1398`、regression・pip-audit・Analyze Python・CodeQL success | [回帰ジョブ](https://github.com/oxo-ops/dkss/actions/runs/40672565455/job/122762787325)。PR headの結果。main SHA自体の全試験再実行とはしない |

総試験件数や工程の進捗は品質改善計画から転記しない。上表のCIと対象テスト定義を個別の実装状況の証拠とし、異なる環境・時点・関連試験の件数を重複加算しない。

### 今回の対象から除外したPR

初回確認時点で#273（お知らせとマスタ競合調査）、#274（削除車両の分析アクセス）、#275（整備分析日付・精度）はopenだった。#274〜#277は後続確認でマージを確認したため、下記追補にのみ追加する。最終一覧確認時にopenの#273・#278（Q11架空データ復旧試験）のコード・調査結果を実装済み事実へ取り込んでいない。特に#278の試験報告をmainの復旧能力や正式なRPO/RTOの証明にしない。#279は本変更案のPRである。

## docs棚卸し

以下は初回基準mainに存在する40件。古い文書の本文を一括更新せず、作成時の状態・試験件数は履歴として保持する。本PRはこの照合記録・章別変更案・両版比較の3ファイルのみを対象とする。

- 構造・DB・計測：application_architecture.md、database_schema.md、refactoring_plan.md、analysis_service_extraction_20261025.md、analysis_summary_extraction_20261025.md、dashboard_services.md、read_path_performance_20261025.md、domain_consistency_20261027.md。
- 日報：driving-report-import.md、driving-report-readback.md、driving-report-comparisons.md、driving-report-detail-ui.md、driving-approved-layout.md、driving-admin-self.md、driving-person-vehicles.md、driving-fuel-evidence.md、driving-request-reads.md、driving-spec-gaps-20261028.md、driving-analysis-navigation.md。
- 取込・車両・過去差分：document_import_queue.md、ocr-searchable-select.md、vehicle-couplings.md、preserved_local_changes_20261027.md。
- Q02：q02_mfa_cookie_replay_20261027.md、q02_directory_boundaries_20261028.md、q02_import_midflight_revocation_20261028.md、q02_inspection_plan_boundaries_20261028.md、q02_invoice_plan_boundaries_20261028.md、q02_knowledge_boundaries_20261028.md、q02_news_boundaries_20261028.md。
- quality/Q05：Q05-date-validation-20261027.md、Q05-dashboard-tokyo-20261027.md、Q05-checklist-business-dates-20261027.md、Q05-operation-chronology-20261027.md、Q05-inspection-date-contracts-20261027.md、Q05-document-completion-dates-20261027.md。
- quality/請求：invoice-plan-summary-20261028.md、Q07-cost-date-consistency-20261028.md、Q07-invoice-lifecycle-20261028.md、Q07-invoice-reimports-20261028.md。

JSON2件はread_path_performance_20261025.json、analysis_read_cache_20261027.json。backend・samples・concurrent_requests・external_callsを確認し、逐次SQLite測定であることを照合した。

## 最終main追加照合

作業中に進んだmainの差分を再取得し、コード・追加テスト・追加技術資料を読取確認した。第一追補は#274・#275、最終追補は下記の#276・#277。業務Aと既知のD06・D07は変更しない。

| PRとmerge SHA | Bとして確認した追加内容 | 関連章・残る範囲 |
| --- | --- | --- |
| [#274](https://github.com/oxo-ops/dkss/pull/274)、`2ad5462e264872fea6ec8ae1917f0ead76808cea` | 分析ページ本体の車両取得にもdeleted=Falseを加え、削除済みは集計・描画前に404。一般利用者の有効車両閲覧は維持。追加3件と関連22件成功は当該技術資料の報告 | 03・06・14・18章。過去履歴の消去ではなく現行ページの認可境界。外部AI・本番・PG受入は未完了 |
| [#275](https://github.com/oxo-ops/dkss/pull/275)、`6c13df3859b0c6b7e2c35bfe360f4a15ff7bc85e` | maintenance_cost_dateへ費用日付の読取を共通化し、分析期間・月別・内訳と費用画面等を統一。ダッシュボードの吹き出しは小数2桁まで保持し末尾0を除去。追加7件・関連200件成功は当該資料の報告 | 04・06・07・08・13・18章。保存値・原本・DB型を変更せず、D07の費用履歴不一致は未解消 |

追加出典：

- [Q02削除車両の技術記録](https://github.com/oxo-ops/dkss/blob/6c13df3859b0c6b7e2c35bfe360f4a15ff7bc85e/docs/q02_deleted_analysis_page_20261028.md)、[分析コード](https://github.com/oxo-ops/dkss/blob/6c13df3859b0c6b7e2c35bfe360f4a15ff7bc85e/dkss_app/analysis.py)、tests/test_q02_analysis_boundaries.py。
- [Q07費用表示の技術記録](https://github.com/oxo-ops/dkss/blob/6c13df3859b0c6b7e2c35bfe360f4a15ff7bc85e/docs/quality/Q07-cost-display-consistency-20261028.md)、vehicle_analysis_dates.py、vehicle_analysis_summary.py、dkss_app/maintenance_facts.py、dkss_app/dashboard.py、tests/test_q07_cost_display_consistency.py（いずれも追補SHAの差分を確認）。

GitHubメタデータで両PRのmerged=trueとmerge SHAを確認した。追補のテストは今回再実行しておらず、CI成功の独立確認も初回の上表とは別に扱う。対象試験の件数を最終mainの全試験数・全経路網羅としない。技術資料は初回40件にこの2件を加え42件となる（本PRの仕様管理3ファイルは含めない）。

### PR #276・#277の最終追補

最終fetchで追加された2件をGit履歴・実装差分・追加試験・追加資料で照合した。参照時点をこのSHAで固定し、その後の変更は別回の照合対象とする。

- [#276](https://github.com/oxo-ops/dkss/pull/276)、merge `299e07604a37a9883adae7dc9b6deff009f4f0e7`：点検記録IDからの原本取得で、現在の車両が同一会社に存在し、完了原本の取込結果recordsにもその車両があることを検証。不正構造・紐付け不一致は404。削除状態・ハッシュ・日報経路のルール変更ではない。追加5件・関連67件成功は技術資料の報告であり、今回の再実行ではない。03・06・09・14・18章のBへ追記する。
- [#277](https://github.com/oxo-ops/dkss/pull/277)：乗務者一覧の無事故日数も日本時間の当日と起算日のdate差で計算する。保存起算日、365日による年・日表記、空欄・不正値・未来値の既存扱いは維持。追加13件、関連25件成功は資料報告。初回既存247件は文字コードエラー1件を含むFAILEDで、その1件のUTF-8再実行成功と全件再実行を混同しない。06・07・13・18章のBへ追記する。

出典は追補SHAのdocs/q02_inspection_source_membership_20261028.md、docs/quality/Q05-driver-business-date-20261028.md、dkss_app/vehicle_imports.py、dkss_app/masters.py、tests/test_q02_import_document_boundaries.py、tests/test_q05_additional_boundaries.py。追加資料内の「PR未作成・push失敗」は作成時点の記録であり、現在のマージ状態とは区別する。最終mainの既存技術資料はMarkdown44件、測定JSON2件（本PRの仕様管理3ファイルを除く）。

## 残作業

1. 正本の選定・承認・保管方法を確認する。比較済みv0.18とv0.25は保持し、後続資料と別紙1〜5の対象版・更新履歴・競合を確認する。
2. 章別変更案と両資料間の相違を、今後確定する文書管理・業務判断の担当者が確認する。D06の車検と12か月点検、D07の費用訂正制約はAを変更せず、業務判断と開発側の確認へ渡す。
3. U番号・F番号・K番号を維持して、採用された局所変更だけを正本へ反映する。新S番号・改訂版・承認日は管理者が確定後に採番する。
4. 別紙の機能・画面・データ・外部連携・非機能と受入記録を同期し、Wordはレンダリングと全ページ確認を実施する。
5. mainが進んだ場合は新たなマージだけを追加照合する。未実施試験、未取得資料、未決判断を完了へ変更しない。
