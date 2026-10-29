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
| `HTTP_UNEXPECTED_ERROR stage=request error_type=...` | マージ済み#332のHTTP共通例外。例外本文・SQL引数・チェーンを記録せず、既存のrollbackと応答を維持。[既存報告](quality/Q09-http-diagnostics-20261029.md)を参照 |
| `OperationalError` / `ProgrammingError`等 | 承認済みスキーマ証跡・権限・接続設定の有無と照合。型だけでDB原因を確定せず、移行主管へ返す |
| queuedが続く | 組込無効フラグ、専用worker有無、Web稼働状態、対象版・lease情報を既存手順で確認。jobを直接書き換えない |

ログ保護の対象は、#329のOCRループ・lease更新の2経路と、#332のHTTP共通例外ハンドラーを分けて記録します。他の全経路や基盤側を含む全ログの対策完了を保証するものではありません。詳細診断が必要な場合も、管理された環境で許可された最小情報を収集します。

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
| `tools/upgrade_operation_csv_owners.py` | #327の運行CSV受付UUID証跡。`Q03_CSV_OWNER_MIGRATION_DATABASE_URL`必須で`DATABASE_URL`へフォールバックしない。`operation_csv_owner.py`が既存表、nullable文字列列（36文字以上）、会社/所有者の非一意索引とPG索引のvalid/readyを検査。旧NULLは補完しない |
| `tools/upgrade_master_generations.py` | Q04の世代列追加・未付与世代の初期付与と、通常表/世代の欠落・不正・重複の検証。専用URL/対象名/非本番確認が必要、`--check`は読取確認。会社内名称一意索引の定義・valid/ready診断は別責務（#295／#304、`tools/q04_master_preflight.py`）。[世代の既存報告](quality/Q04-master-generations-20261029.md)と[診断の既存報告](quality/Q04-master-preflight-20261029.md)を参照 |
| `flask --app app upgrade-domain-storage` | 原本保存/分析キャッシュ用の既存処理。保存先変更は今回の対象外 |

これは**調査用の索引で、上から一括実行する順序ではありません**。配備SHAごとの適用順序・適用済み判定・失敗時復帰は移行主管が管理します。旧版の5処理手順へ#313や#317を独断で付け足しません。安全な再実行可否も処理ごとに異なり、UUIDの旧データ補完を推定で行いません。

#327の追加条件は[CSV所有者の既存手順](quality/Q03-operation-csv-owner-20261029.md#移行主管への追加受入適用条件)を正とします。新列は`vehicle_operation_import_draft.owner_identity VARCHAR(36) NULL`、索引は`ix_operation_csv_company_owner(company_code, owner_identity)`です。既存CSV表がなければ停止し、新アプリ起動前に列を準備します。旧NULL受付は原本・作成者文字列・状態・関連記録を保持したまま、私有preview/result/confirm/APIを404で保留します。username・数値ID・氏名で所有者を補完しません。完了済みの会社共有原本は既存会社・車両境界を維持し、私有受付の継承と区別します。

切戻し時も列・索引・原本・旧行を削除しません。旧版はusername認可へ戻るため、単純なアプリ巻戻しでCSV私有経路を再開してはいけません。CSV受付・preview・confirm・APIを停止した状態を維持するか、UUID照合を保持した修正版へ戻します。旧NULLの確認・回復は別の根拠付き手続きです。固定288261dの6処理・388件にはこの追加移行を含めず、主管の追加受入をQ09で再実行しません。

移行主管へ渡す記録は、対象完全SHA、関連PR、対象表/列/索引、処理入口、前後のスキーマと原値比較、終了コード・成功マーカー、部分適用の有無です。失敗時はwriter再開や自動再試行を止め、途中commitの可能性を確認して主管の復帰手順に従います。Q11のバックアップ・復旧手順を別実装しません。

factory/`app.py`のimportはDB初期化を行いません。一方、`gunicorn.conf.py`の`post_worker_init`は日報閲覧・連結表の初期化/一部追加変更を呼びます。OCRを無効にしてもこのDB処理は止まりません。アプリ構築、開発Flask、Gunicorn worker起動、明示的移行を区別し、Gunicorn起動を既存DBの無変更診断として使わないでください。

## 未確定事項と担当境界

Q09の初回確認は新規Windows/Python環境と架空SQLite、模擬故障でした。既存Linux CIはfactory/キュー試験が中心で、過去の実Gunicorn受入を現在版の起動証明とは扱いません。追加の`tests/test_q09_linux_runtime.py`はLinuxの既存回帰CIで、新規一時SQLite、非loopback接続を遮断した子プロセスを使い、現在のGunicorn（gthread/1/4）、組込OCR、ログインHTTP200、明示OCR CLI、通常SIGTERM終了を確認します。Windowsではこの1件は明示的skipです。結果は各headのregressionログの`Q09_LINUX_RUNTIME_OK`と試験結果で判定します。実配備の停止時間、運用サービスの台数・管理者・再起動policy、ログ保管/通知先は未確認のまま運用主管へ残します。

移行主管の6処理・388件検証/実行ハーネス、Q11の復旧、Q12性能、Q02/Q03/Q08の権限修正は再実装・再実行しません。Q05は完了状態を維持します。既存移行検証DB4件や本番DB、本番S3を第三者の起動試験に利用しないことが、この手順の前提です。
