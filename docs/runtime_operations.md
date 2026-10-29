# 開発環境と運用構成の確認手順

この手順は新しいローカル環境の立ち上げと、既存構成の調査に使用します。本番・既存の移行検証DB・S3には接続しません。既存環境への移行、バックアップ・復旧、配備は各主管の手順と承認に従います。DB変更の一括実行基盤は追加していません。

## 新しいローカル環境

Python 3.12を使用し、リポジトリを新しいディレクトリへ取得します。以下はWindows PowerShell用です。依存の取得先は公開パッケージ配布元です。アプリの外部AI・通知・S3への接続とは区別します。

```powershell
git clone https://github.com/oxo-ops/dkss.git dkss-q09-local
Set-Location dkss-q09-local
git rev-parse HEAD  # 作業記録へ完全SHAを記載する
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m pip check

# 新規の使い捨てDBだけを指定する。接続設定・秘密値の一覧を表示しない。
$localDbDir = Join-Path ([IO.Path]::GetTempPath()) ('dkss-local-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $localDbDir | Out-Null
$localDbFile = Join-Path $localDbDir 'new.db'
if (Test-Path -LiteralPath $localDbFile) { throw 'New database required' }
$env:DATABASE_URL = 'sqlite:///' + $localDbFile.Replace('\','/')
$env:SECRET_KEY = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
$env:ITC_INITIAL_PASSWORD = 'Local-Only-' + [guid]::NewGuid().ToString('N') + '!'
$env:RENDER = ''
$env:RATELIMIT_STORAGE_URI = 'memory://'
$env:AWS_EC2_METADATA_DISABLED = 'true'
$env:S3_BUCKET_NAME = ''
$env:OPENAI_API_KEY = ''
$env:SMTP_HOST = ''
$env:VAPID_PRIVATE_KEY = ''
$env:VAPID_PUBLIC_KEY = ''
$env:DOCUMENT_IMPORT_WORKER_ENABLED = '0'
$env:MFA_ENABLED = 'false' # この使い捨て環境だけ。運用設定へ転記しない
& .\.venv\Scripts\python.exe -m flask --app app init-db
& .\.venv\Scripts\python.exe -m flask --app app run --host 127.0.0.1 --port 5000 --no-reload
```

`DATABASE_INITIALIZED`を確認してから`http://127.0.0.1:5000/login`を開きます。`init-db`は新規DBにテーブルと初期管理者を作ります。空でないDBへ同じ例を転用しません。秘密値は一時シェル内に保持し、コミット・ログ・画面共有へ出しません。Flaskは開発サーバーです。終了は実行中の端末でCtrl+C、不要になった環境はシェルを閉じます。DBは今回作った一時フォルダーだけにあります。

この手順では実OCR・外部配信を行いません。特に一部のWindows向けAI処理は環境変数が空でも既存のOS設定へフォールバックするため、「空にしたからすべてのAI操作が安全」とは扱いません。取込の確認は既存のモック付き試験を使います。既存OS設定・認証ファイルを探索する必要はありません。

代表試験は同じ仮想環境で次のとおりです。各試験が専用の一時SQLiteやモックを使うことを確認してから実行します。

```powershell
$env:PYTHONPATH = '.;tests'
& .\.venv\Scripts\python.exe -m unittest test_application_foundation test_document_import_queue test_q09_worker_diagnostics -v
```

全体回帰の標準は`.github/workflows/regression-tests.yml`です。PostgreSQL専用試験は別の使い捨てサービスを使います。これらを移行検証DBや本番DBで実行しません。

## WebとOCRワーカー

| 用途 | 実装と起動方法 | 停止と注意点 |
|---|---|---|
| Windowsでの開発Web | `python -m flask --app app run --host 127.0.0.1 --no-reload` | 端末でCtrl+C。開発確認用 |
| LinuxのWeb | `gunicorn -c gunicorn.conf.py app:app`（Procfileと同じ） | 管理するmasterプロセスへSIGTERM。実際のサービス管理者・停止方法は配備構成で確定する |
| 組込OCR | Gunicornの`post_worker_init`から起動。開発Flaskでは取込・statusアクセス時にも起動要求される | `worker_exit`が停止イベントを設定。factory/importだけではOCRは開始しない |
| 明示的なOCRプロセス | 同じアプリ版・承認済みDB設定で`python -m flask --app app document-import-worker` | Ctrl+CまたはSIGTERMで停止イベントを設定。実行中処理の終了は即時ではない |

GunicornはLinuxで使用します。Windowsにパッケージを導入できてもGunicornの起動成功を意味しません。構成は既定1プロセス・各4スレッド、`gthread`、health timeout 120秒、graceful timeout 30秒です。プロセスを増やすと組込OCR読取スレッドも増えます。デフォルトの1プロセス内では逐次読取ですが、全配備で1並列を保証する設定ではありません。

専用OCRを使う構成ならWeb側の`DOCUMENT_IMPORT_WORKER_ENABLED=0`で組込を止め、明示的CLIだけを管理します。このフラグは`start_worker`の自動開始を抑えるもので、明示的な`document-import-worker`コマンドは抑止しません。`TESTING=True`も組込OCRを抑止します。サービスの自動再起動、台数、実行権限、停止担当は運用側の確定事項であり、リポジトリに外部プロセスマネージャー設定はありません。

`stop_worker`は停止・wakeイベントを設定し、進行中のAI呼出しを強制中断したり待ち合わせたりしません。Gunicornの30秒とAIタイムアウトの既定600秒は別の上限です。停止時に処理が中断される可能性とleaseによる再取得は[OCRキュー仕様](document_import_queue.md)に従います。実停止・復旧リハーサル、強制停止、課金重複の受入はQ11の既存範囲です。

## 設定項目

根拠は`dkss_app/__init__.py`、`gunicorn.conf.py`、`document_import_worker.py`、AI・通知モジュールです。設定の存在・用途だけを記録し、値の一括表示はしません。`.env`の自動読込を前提にせず、サービス管理または起動シェルから渡します。

| 項目 | 必須条件・既定・意味 |
|---|---|
| `SECRET_KEY` | 全環境で必須。未設定ならfactoryが停止。利用者セッションの鍵であり検証鍵を運用へ流用しない |
| `DATABASE_URL` | `RENDER=true`で必須（factoryの明示URI設定を除く）。ローカル未指定は`instance/dkss.db`のため、検証では新規DBを明示する |
| `ITC_INITIAL_PASSWORD` | `init-db`で初期管理者が存在しない場合だけ必須。既存管理者のパスワード更新用ではない |
| `RENDER` | 文字列`true`で本番用Cookie/設定ガード。環境の識別・承認の代用ではない |
| `RATELIMIT_STORAGE_URI` | 既定`memory://`。`RENDER=true`では共有ストレージ設定が必須。URL自体が秘密値を含み得る |
| `MFA_ENABLED` | 既定`true`。新規ローカル例のfalseを運用へ適用しない |
| `DOCUMENT_IMPORT_WORKER_ENABLED` | 既定`1`、文字列`0`で組込OCRを抑止 |
| `WEB_CONCURRENCY` / `WEB_THREADS` | 既定1/4。整数。変更はOCR並列数・メモリも含めて判断 |
| `DOCUMENT_AI_TIMEOUT_SECONDS` | 対応OCRの既定600秒、30〜1800秒。Web health timeoutや全バッチ完了時間と区別 |
| `OPENAI_API_KEY` | 実AI処理を使う場合。Webの構築・モック試験には不要 |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` | メール利用時。port既定587。未設定でも内部通知とメール配送は別判定 |
| `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_SUBJECT` | Web Push利用時。公開鍵と秘密鍵の取扱いを区別 |
| `S3_BUCKET_NAME`, `AWS_REGION`, AWS認証設定 | S3利用時。region既定ap-northeast-1。bucket指定時はfactoryでboto3 clientを構築し得るため、検証ではbucketを空にする |

## 障害の切り分けとログ

最初に「どの完全SHA・どの環境識別子・どの処理段階で停止したか」を記録します。パスワード、接続URL、全環境変数、未加工SQL引数・原本を報告へ貼りません。

| 症状・マーカー | 確認する内容 |
|---|---|
| `SECRET_KEY environment variable is required` | 鍵が存在するかだけ確認。値を表示しない |
| 共有`RATELIMIT_STORAGE_URI` / `DATABASE_URL`が必要という起動エラー | `RENDER`条件と設定元。接続URLの表示や認証の反復試行は不要 |
| `DATABASE_INITIALIZED` | 当該コマンドの完了。既存DBの全専用移行が完了した証明ではない |
| `OCR_WORKER_STARTED` / `OCR_WORKER_HEARTBEAT` | 起動とqueued/reading/failed、RSSの推移。heartbeatは通常約60秒単位で、長い処理中の常時出力を保証しない |
| `OCR_WORKER_ITERATION_FAILED error_type=...` | ループ段階と例外種別。次のiterationは継続。SQL・認証情報を含み得る例外本文/tracebackは出さない |
| `OCR_JOB_HEARTBEAT_FAILED job_id=... error_type=...` | 個別jobのlease更新段階で失敗。既存のrollback・後続処理を維持。例外本文/tracebackは出さない |
| `OperationalError` / `ProgrammingError`等 | 承認済みスキーマ証跡・権限・接続設定の有無と照合。型だけでDB原因を確定せず、移行主管へ返す |
| queuedが続く | 組込無効フラグ、専用worker有無、Web稼働状態、対象版・lease情報を既存手順で確認。jobを直接書き換えない |

今回のログ保護はOCRループとlease更新の例外ハンドラーに限定します。他の全経路や基盤側のログの秘密値非表示を保証するものではありません。詳細診断が必要な場合も、管理された環境で許可された最小情報を収集します。

## 依存更新とCIの追跡

- 依存版の入口は`requirements.txt`。Dependabotは`.github/dependabot.yml`でpipとGitHub Actionsを毎週月曜に確認します。推移依存をすべて固定するlockfileはなく、`pip check`成功と完全に同一の解決結果は別です。
- 全体回帰は`regression-tests.yml`。Python 3.12、Python試験、Node試験、構造inventoryとスキーマ資料生成差分を確認します。Node実行は現在runnerの同梱版に依存し、ここで版固定を追加していません。
- `codeql.yml`はPython解析、mainへのpush・main宛PR・毎週月曜00:30 UTCに実行。
- `dependency-audit.yml`は`pip-audit -r requirements.txt`、mainへのpush・PR・毎週月曜00:00 UTCに実行。脆弱性DBとの通信が必要です。実サービス接続を禁止するローカル確認では再実行せず、GitHubの結果を参照します。
- [Actions一覧](https://github.com/oxo-ops/dkss/actions)と[PR一覧](https://github.com/oxo-ops/dkss/pulls)で、対象head完全SHA、workflow、run URL、失敗step、結論を記録します。旧head成功と新head未完了を混同しません。

失敗時は、依存導入/通信失敗、テスト失敗、CodeQL権限/解析/検出、pip-auditの導入/通信/脆弱性検出を分けて確認します。pip-audit検出はpackage・導入版・advisory・修正版候補を記録し、無条件の無視や期待値の緩和は行いません。修正は独立PRでレビューし、自動マージやmainへの直接pushは行いません。第三者に共有するログは秘密値を確認・除外します。

## DB変更を追跡する入口

既存構成は専用CLI・カラム/表/制約の検査による追加処理で、全移行に共通する版番号台帳やAlembic基盤はありません。`create_all`は既存表の全不足列を補う処理ではありません。`init-db`の途中には複数commitがあり、全体を一括rollbackできるとは扱いません。

| 処理の入口 | 内容・適用済みを調べる根拠 |
|---|---|
| `flask --app app init-db` | 新規bootstrapと従来の互換処理。`database.py`、`__init__.py`。既存DB向けの万能移行コマンドではない |
| `flask --app app upgrade-account-identity` | Q08 UUID列・旧所有権の保留。`account_identity.py`とQ08資料。列の存在だけで証跡の妥当性まで認定しない |
| `tools/upgrade_safety_identities.py` | Q03安全管理の識別列。専用URLを必須とし、`safety_identity.py`が既存表/列を検査 |
| `flask --app app init-driving-access` | 日報閲覧UUID証跡・旧訂正識別。`driving_access.py`と`driving_vehicle_links.py` |
| `flask --app app init-checklist-notify-identities` | 通知割当のUUID証跡。`checklist_notify_identity.py`。旧本人を推定しない |
| `tools/upgrade_checklist_event_timestamps.py` | 文字列長40への対応。`checklist_event_storage.py`が型/長さを検査。UTC/JST変換ではない |
| `tools/upgrade_import_owners.py` | Q02受付UUID証跡。専用URL必須。`import_owner.py`、Q02 #313資料 |
| `tools/upgrade_master_generations.py` | Q04マスタ世代列・一意制約等の検査。専用URL/対象名/非本番確認が必要、`--check`は読取確認。#317の資料を参照 |
| `flask --app app upgrade-domain-storage` | 原本保存/分析キャッシュ用の既存処理。保存先変更は今回の対象外 |

これは**調査用の索引で、上から一括実行する順序ではありません**。配備SHAごとの適用順序・適用済み判定・失敗時復帰は移行主管が管理します。旧版の5処理手順へ#313や#317を独断で付け足しません。安全な再実行可否も処理ごとに異なり、UUIDの旧データ補完を推定で行いません。

移行主管へ渡す記録は、対象完全SHA、関連PR、対象表/列/索引、処理入口、前後のスキーマと原値比較、終了コード・成功マーカー、部分適用の有無です。失敗時はwriter再開や自動再試行を止め、途中commitの可能性を確認して主管の復帰手順に従います。Q11のバックアップ・復旧手順を別実装しません。

factory/`app.py`のimportはDB初期化を行いません。一方、`gunicorn.conf.py`の`post_worker_init`は日報閲覧・連結表の初期化/一部追加変更を呼びます。OCRを無効にしてもこのDB処理は止まりません。アプリ構築、開発Flask、Gunicorn worker起動、明示的移行を区別し、Gunicorn起動を既存DBの無変更診断として使わないでください。

## Renderログイン障害の復旧確認（2026-10-29）

移行主管のローカル復旧資料の更新分を、この既存報告へ集約します。第一候補は**利用者報告の現在版`18ae141b`を維持するログイン復旧**です。最新mainへの更新、Q04・CSVを含む全移行を前提にしません。復旧対象の完全SHAと実対象の最終照合は未完了で、**P1（移行開始承認）は保留**です。以下は確認範囲の記録であり、本番接続・Render操作・停止・移行・デプロイの開始指示ではありません。

### 利用者報告で確認済みの事実と、不足証拠

出典は2026年10月29日の利用者報告と、その09:54 JSTの保全記録です。書記・移行主管による再測定ではありません。記録時刻を実測時刻へ置き換えず、報告時点の確認済み事実を現在の全サービスへ外挿しません。

| 項目 | 利用者報告時点の確認済み事実 | 追加で必要な不足分だけ |
|---|---|---|
| T01 稼働版・設定 | 稼働短縮SHA`18ae141b`、Auto-Deploy Off | 完全live SHA、全Web／worker／jobの版と設定反映版の対応、既報後の変更有無、証跡ID |
| T02 DB・schema | 本番DB接続先・schemaの識別は確認済み | 既存の制限付き証跡への参照、元runtime role／options／search_path、同名表の実解決先 |
| T03 実スキーマ | `user.account_identity`、Q03関連列、`vehicle_document_import_draft.owner_identity`等の欠落、`checklist_event.created_at`が`VARCHAR(30)` | Q03個別欠落列、復旧対象版に必要な残りの列・索引・制約と既存値保持の前提 |

Q03全20列の欠落や、未提示の表・索引の状態を推定しません。接続先・role等の実値、接続URL、認証情報、業務行は共有資料へ転記せず、既存の制限付き証跡で照合します。リポジトリ内で短縮SHAを完全値へ解決できても、実live完全SHAの確認証拠にはしません。

主管保管の既存資料では、`render_admin_confirmation.txt`のT01 A/B・T02 A/B、`production_preflight_handover.txt`の01〜03、`recovery_checklist.txt`のB/C/E-1が該当します。管理者は上表の対応・照合成否、確認者、確認日時、非秘密の証跡ID、不足理由を既存判定表へ返します。既報のOffへの再変更や、確認済みDB／schemaの実値の再送は求めません。新たな操作・接続が必要な不足分は、対象と範囲が承認されるまで未確認として止めます。

### M01：ログイン欠落に直接対応する既存処理

既存の`flask --app app upgrade-account-identity`（[実装](../dkss_app/account_identity.py)）を直接修復の候補とします。次の6表8列3索引について、報告済みの欠落と未提示部分を分けて現状を整理します。コマンドを実行する指示ではありません。

| 表 | 必要列 |
|---|---|
| `user` | `account_identity VARCHAR(36)` |
| `notification` | `owner_identity VARCHAR(36)` |
| `news` | `owner_identity VARCHAR(36)` |
| `push_subscription` | `owner_identity VARCHAR(36)` |
| `audit_log` | `actor_identity VARCHAR(36)`、`actor_name VARCHAR(200)` |
| `vehicle_maintenance_record_event` | `actor_identity VARCHAR(36)`、`actor_name VARCHAR(200)` |

追加列はnullableです。索引は`uq_user_account_identity(account_identity)`が一意、`ix_notification_owner_identity(company_code, owner_identity)`と`ix_push_owner_identity(company_code, owner_identity)`が非一意です。基礎表の存在、既存列の型・NULL等、索引の完全定義・valid/ready、既存UUIDの異常・重複を承認済みの証跡で確認します。同名の誤定義を`IF NOT EXISTS`で修復できるとは扱いません。

保持条件は、**NULLだったUserの`account_identity`への初期UUID付与だけを許容し、既存UUID・認証値・通知・監査・履歴を保持すること**です。旧通知等の所有者をusernameから補完しません。既存値の前後比較と、6表のALTER／索引作成、UserのSELECT／UPDATEに必要な承認済み権限を確認します。runtimeへの権限昇格、基礎表不足の`init-db`による即興補完は行いません。

### 再開範囲と、採用版による追加条件

| 範囲 | 選定する条件 |
|---|---|
| 限定ログイン受入 | M01対象・実行権限・保持前提を確認し、既存の停止／整合バックアップ／隔離復元／失敗時復旧とP1承認を満たした後、制御した入口だけでログイン・CSRF・実SMTP/MFA・監査を受け入れる。一般業務writer・OCR・通知・定期jobは停止を維持する |
| 通常業務の再開 | Q03個別欠落列、日時幅30と報告版コードの要件40の相違、日報・点検通知等の未提示定義を対象版と照合し、必要な既存移行だけを選ぶ。ログイン成功を業務全体の合格証明にしない |
| OCRの再開 | OCR受付の`owner_identity`は報告版のソースにも存在するため、報告欠落への対応と既存lease／原本／二重処理防止の再開条件を別に満たす。M01の直接修復と混同しない |
| Q04／CSV対応版の採用 | その版を選び、実DBに必要な準備が不足する場合だけ追加移行を選ぶ。CSV所有者移行はOCRとは別表であり、旧NULLを補完しない |

停止・保全・限定権限・復元・中止／切戻しは既存の[Q11運用受入](quality/Q11-operational-readiness-20261028.md)と[復旧手順](quality/Q11-recovery-automation-20261028.md)、主管のチェックリストD/E/G、引渡し手順05〜08を再利用します。対象版に必要な条件だけを選定し、P2（通常再開承認）と段階再開は限定ログイン受入から分けます。Gunicornの起動時DDLを移行や無変更診断の代用にしません。旧認可へ切り戻す場合は、関連私有経路・旧writerを止め、追加列・UUID・証跡・原本を削除しません。

### Q04本番入口は別作業

`18ae141b`に解決する解析ソースにはQ04の`master_generation`がなく、M01にもQ04依存はありません。実稼働版との最終照合後、その版を維持してM01でログインを修復する方針なら、**Q04本番入口の整備待ちは不要**です。Q04対応版を採用し、実5マスタの準備不足により適用が必要な場合だけ、その版の準備阻害条件になります。既にreadinessを満たすなら移行入口の実行は不要です。

Q04設計報告の方針は、承認要件を満たす主管共通基盤があればQ04アダプタを優先し、なければ薄い専用入口を検討することです。方式は未決・未実装で、ローカル専用のrehearsal/Q11資材を本番基盤とは扱いません。主管／DBAが対象・方式・承認manifestを確定し、Q04担当が既存`upgrade_storage`／`validate_storage`へ委譲する最小差分、Q11／運用が保全・限定権限・停止復帰条件を担当します。非本番CLIのguard解除やURL／DB名偽装、一時Pythonでの直接呼出しは採りません。

必要と決定・実装承認された場合の追加受入は、接続前後の対象／role／schema／TLS／承認拒否、同一接続での5表LOCK後・DDL前のOID／状態再照合、読取計画のtransaction解放、既存値保持、権限／lock異常時の停止、commit応答・台帳保存喪失時の成否不明判定と読取復帰に限定します。既存の移行本体・バックアップ・試験を重複実装しません。

### 完了済み証跡と現在の判定

- 旧5コマンドの隔離検証79件、復旧チェックリスト、既報6処理／62表保持は完了として再利用します。
- 固定`288261d`の388件は387成功・Q03の1失敗で凍結し、元結果・ログを保持します。Q03は独語メッセージと英語assertの差を実例外型／SQLSTATE `55P03`で切り分け、テスト専用の最小案を別途検証済みです。担当Q03へ集約し、元388件へ成功を合算しません。
- `1741c64426f75f682a331f99b9249a45caf7a612`の#327追加隔離受入は、新規合成バックアップの復元先で保持・定義・再実行・DDL rollback／再開と選定4HTTPケースを完了。実運用backup・実容量・Render遮断／切戻し・実SMTP受入の成功証明ではありません。
- 本追記で既存検証・本番操作を実施していません。P1保留を維持し、不足証拠と対象版・再開範囲を運用責任者が確定するまで移行・公開・配備へ進めません。

## 未確定事項と担当境界

Q09の今回確認は新規Windows/Python環境と架空SQLite、模擬故障、CI証跡です。Linuxでの現在版Web/専用OCRの実停止時間、運用サービスの台数・管理者・再起動policy、ログ保管/通知先は運用主管の確認待ちです。Linuxでの過去のGunicorn確認はOCR資料に記載済みで、現在版の新規実測と区別します。

移行主管の6処理・388件検証/実行ハーネス、Q11の復旧、Q12性能、Q02/Q03/Q08の権限修正は再実装・再実行しません。Q05は完了状態を維持します。既存移行検証DB4件や本番DB、本番S3を第三者の起動試験に利用しないことが、この手順の前提です。
