# Q11 実環境相当の復旧検証に向けた準備

ローカル検証の基準mainは `c7efecbc3ede1c7c44855d1f768544531eee3172`（PR #277まで）、確認日は2026年10月28日JST。PR #278の確認対象headは `e461a9339a78f1716c3dedc8c6df38888287d851`。その22ケースは再実装せず、追加スクリプトから起動しない。追加作業はmainから分けた独立ブランチで、運用準備・限定権限・実ワーカー停止の検証だけを扱う。既存CIがPRに対して自動起動する場合は、その結果を区別して確認する。

## PR278と全体回帰の確認

PR #278の[全体回帰CI](https://github.com/oxo-ops/dkss/actions/runs/40678687645/job/122783524455)は成功した。Pythonは1,127件、347.914秒、失敗0、skip 5。skipはQ02 MFAとQ04マスターの専用PostgreSQL環境を必要とする5クラスで、今回の回帰jobでは想定されたもの。JS・スキーマ生成差分・アーキテクチャ確認も成功した。Q11専用CI、CodeQL、依存監査も成功しており、CI失敗の原因調査が必要な状態は確認されなかった。mainの#276は原本閲覧の車両所属確認、#277は運転者の営業日計算の変更で、追加資材の変更範囲と重複しない。

既存の根拠はPR #278の `tools/q11_recovery.py` と `docs/quality/Q11-recovery-*`。今回のスクリプトは同PRのbootstrap（Git blob `8bc201d336d45d92a393221b5745f71e25f3ab15`）を読み取り、クラスタ作成・架空fixture生成を再利用する。復元試験や原本検出器の別実装は追加しない。製品コード・業務仕様・データ定義の変更はない。

## 環境管理者に受け取る条件

秘密情報ではなく、次の承認済み設定・判断を受け取る。未提出なら該当する実環境検証を始めない。

| 項目 | 必要な情報 | 主な判断者 |
| --- | --- | --- |
| S3 | 検証専用account、caller/role、profile、region、source/restore bucketとowner、試験prefix、Versioning/保持/暗号化、KMS key、ネットワーク制約 | 環境管理者・IAM/鍵管理者 |
| PostgreSQL | 検証専用接続先、実運用と合わせるmajor/minor、provider、encoding/locale/collation、extensionと版、owner/migration/runtime/backup/restoreの役割、ACL/RLS、認証方式 | DBA |
| 容量と負荷 | 検証で再現する件数・原本サイズ分布・会社数・保持世代・圧縮率・IOPS/帯域・同時処理、使用可能ディスク/WAL/temp上限 | DBA・環境管理者 |
| 旧版 | 配布物またはGit SHA、依存版、DB互換性、必要なセキュリティ修正、旧設定、再導入手順 | リリース責任者 |
| OCR | 組込/専用workerのプロセス構成・台数、管理ツール、停止/強制停止/再起動権限、graceful timeout、再起動policy、AI模擬接続先 | アプリ運用担当 |
| 業務受入 | RPO/RTO、復旧対象時点、再入力の扱い、欠損許容、業務再開の承認者と代理人 | 業務責任者 |

AWS認証・短期token・DBパスワード・本番dumpを資料やチャットへコピーしない。今回、AWSや既存DBサービスには接続せず、作業フォルダ内の新しいloopbackクラスタだけを使用した。

## PostgreSQLの限定権限とACL

PR #278は `--no-owner --no-privileges` の基本復元であり、運用のowner/ACL保持の代わりにはならない。追加の `tools/q11_pg_readiness.py` で、架空owner・runtime・backup・restore・拒否確認ロールを作り、実際に各LOGINで接続して確認する。runtimeをownerのメンバーにはしない。restore専用ロールだけが明示的に `SET ROLE q11_owner` できる構成は検証fixtureの条件であり、実運用のロール構成の提案を勝手に適用するものではない。

実施する項目は次のとおり。

1. 正のbackup/restoreを行う前に、runtimeのCREATE/SET ROLE、backupのDELETE、backupのSELECT不足を拒否することを確認する。
2. backupロールで `pg_dump -Fc` を実行し、ownerとACLを保持する。必要な権限が欠けたdumpの非ゼロ終了を検出する。RLSによる部分dumpを全件バックアップと扱わない。[pg_dump](https://www.postgresql.org/docs/18/app-pgdump.html)
3. DBAが別の空DBを用意し、承認されたrestore/migrationロールで `pg_restore --role=OWNER --single-transaction --exit-on-error` を実行する。通常のACL検証ではno-owner/no-privilegesを付けない。勝手にsuperuserへ昇格して通さない。[pg_restore](https://www.postgresql.org/docs/18/app-pgrestore.html)
4. owner、schema/table/sequence/functionのACL、grantor・grantee・grant option、default ACL、role membership、extension名・版・schema・ownerを比較する。NULLのfunction ACLは「権限なし」ではなく既定ACLとして展開して比較し、生のACLはinventoryにも残す。[権限](https://www.postgresql.org/docs/18/ddl-priv.html)
5. restore後に将来用の架空表・serial sequence・関数をownerで新規作成し、runtimeのINSERT/nextval/EXECUTE、backupのSELECT、未許可ロールの拒否を確認する。default privilegeは実際にオブジェクトを作るownerについて確認する。[ALTER DEFAULT PRIVILEGES](https://www.postgresql.org/docs/18/sql-alterdefaultprivileges.html)
6. 別の空DBで意図的にACLを省略して復元し、runtimeが読めなくなることを確認する。これは負の試験であり、権限を広げて正常扱いにしない。

追加SQL `tools/q11_pg_inventory.sql` は、名前が `q11_` で始まり、DBコメントが `Q11_SYNTHETIC_ONLY`、指定したDB名と一致する検証DBだけを許可する読み取り専用の採取用SQL。DBサイズ、locale/encoding、roleの権限属性、membership、extension、owner/ACL/default ACL、RLS policyを採取し、秘密のパスワード列は取得しない。コメント設定は検証専用DBの作成時にDBAが行い、既存の他用途DBへ勝手に設定しない。接続先確認はSQL実行より前に行う必要がある。

```bash
# 接続は、DBAが承認した検証専用接続設定だけを使う。
# 例中のDB名は架空fixture用。運用先を推測して代入しない。
psql -X -qAt -v ON_ERROR_STOP=1 -v q11_expected_db=q11_acl_restore \
  -d q11_acl_restore -f tools/q11_pg_inventory.sql > inventory.txt
```

実行の際は明示した検証host/port/userと承認済みの認証経路を用い、既定接続へフォールバックしない。標準出力に業務データは含まないが、ロール・schema名等の環境情報として保管範囲を管理する。

## 拡張と実容量の手順

拡張はDBAから提供された一覧・版を検証環境に用意する。fixtureでは利用可能なtrusted extensionのhstoreを使った。これは実運用でhstoreが必要であるという判断ではない。非trusted extensionやprovider制限がある場合はDBAの事前作成手順を決め、runtimeへsuperuserを与えない。[CREATE EXTENSION](https://www.postgresql.org/docs/18/sql-createextension.html)

実容量の試験は未実施。対象の容量条件が未提供のため、架空fixtureの小規模結果から本番所要時間を外挿しない。

1. DBAと業務担当が、架空データで再現する会社数、履歴件数、原本のサイズ分布、同一原本の重複率、保存世代を確定する。原本はfixtureの生成器で作り、本番原本を複製しない。
2. 検証用DB/ディスク/WAL/temp/backup領域の予算を決め、途中停止する空き容量閾値と監視担当を定める。元DB・復元先・dump・WAL・索引作成・一時領域を同時に持てる条件をDBAが確認する。サイズ倍率を固定値で推測しない。
3. 承認された件数まで段階的に投入し、inventoryのDB/表/索引/TOASTサイズ、dump実サイズ、転送量、restore中のCPU/IO/WAL/tempのピークを採取する。件数・ハッシュの合格条件はPR #278の既存ツールを利用する。
4. 同じ容量・権限で正常復元し、正しいlimited runtimeで主要業務操作を行う。単なるsuperuserのSELECT成功では受入しない。
5. 失敗注入は容量制限付きの使い捨てvolume/tablespaceか専用quotaで行い、共有の実ディスクを埋めない。限定ロールの権限不足も独立した空DBで行う。復元先を公開せず、元DB不変・非ゼロ終了・復元やり直しを確認する。
6. 実測時間をRTOと比較する。dump終了時間だけを復旧時間としない。認証・ACL・原本・画面・ワーカー確認までを含める。

## 旧版へ戻した後の画面と操作

旧版SHAは未指定。共有原本導入前のSHAを自動的に選ばない。mainの#276は点検原本閲覧の車両所属確認を追加しているため、戻す版でも会社/車両境界の期待動作を維持できるか、リリース責任者が確認する。セキュリティ上必要な境界を古い版に合わせて緩めない。

書込と全OCRワーカー停止→新コードでインライン原本復元→全件確認→旧版配置の順は既存 `docs/domain_consistency_20261027.md:44–54` に従う。追加表・版数は削除しない。現行コードでの復元成功を旧版アプリの動作成功と混同しない。

| 確認画面/操作 | 架空fixtureと合格条件 |
| --- | --- |
| ログイン、MFA、ログアウト、権限失効 | A/B社、管理者/一般ユーザー、停止ユーザー。検証用メール捕捉先を使い、既存CSRF/MFA条件を維持。別会社・失効後の原本閲覧を拒否 |
| ダッシュボード、車両カルテ、整備履歴、分析 | 日付、旧営業所帰属、未確定値、ゼロ、保存済みAI結果が戻す前と一致。現在の所属から履歴を推測で補完しない |
| 車両/運転者の登録・編集 | 新しいIDに衝突がなく、会社と確認済み属性が保持され、再起動後も再表示可能 |
| 資料取込・受付一覧・preview・修正・確認 | 請求書、点検、日報、車検証の代表架空資料。旧版が持つ経路を固定し、確認保存の二重送信で業務行が重複しない |
| PDF原本と車両別原本リンク | 既存共有原本・インライン原本・複数参照・同一digestの別会社を用意。digest一致、削除非復活、車両所属が外れた参照の拒否を確認 |
| 再試行・受付削除 | 成功済みを再処理せず、失敗分のみ再試行。削除した受付が後着結果で復活しない |
| マニュアル、プロフィール画像 | 会社別キーと旧キー、ローカルfallback、署名URLの期限・他社拒否・metadataを確認 |
| お知らせ/通知の添付、チェックリスト評価基準 | A/B社、宛先制限、閲覧ロール、添付のダウンロードと変更・削除を既存仕様どおりに確認 |
| 安全パトロール/対策添付、安全/車両チェックリスト結果、整備添付 | 原本サイズ・ハッシュ、参照元、会社境界を照合し、新規架空添付の保存→取得→削除を確認 |
| Excel/CSV等の既存出力 | 件数・対象会社・日付・不明/ゼロの扱いを戻す前と比較。取得できない列を仮に埋めない |

実際のfixture ID、URL、actor、操作前後の行数とdigest、画面結果、再開担当の判定を記録する。添付の所在を確認する根拠は `dkss_app/storage.py:340–558`、原本ルートは `dkss_app/routes.py:284–345`。画面試験は今回未実施。

## OCRワーカーの停止と再開

既存設定の根拠は `docs/domain_consistency_20261027.md:31–33`、`gunicorn.conf.py:5–24`、`dkss_app/document_import_worker.py:14–85`。専用CLIは `dkss_app/__init__.py:111–121` でSIGTERM/SIGINTをstop eventへ変換する。stop eventは処理ループ境界で参照されるため、実行中AIを即座に中止するものではない。既定heartbeatは15秒、leaseは120秒、中断上限は3回（`document_import_queue.py:24–25,365–377`）。値は実際の配備設定を運用担当に確認し、短く書き換えて試験を通さない。

1. 検証用プロセス管理ツールの一覧からWeb内蔵readerと全専用workerのPID/台数・自動再起動policyを記録する。Webの `DOCUMENT_IMPORT_WORKER_ENABLED=0` は専用プロセスを止める操作ではない。停止中に管理ツールが勝手に再起動しない条件を決める。
2. 課金APIと実メール等を接続せず、ローカルのAI模擬処理で「受信済み、結果保存前」の境界を作る。ジョブID、attempts、lease期限、呼出し回数を記録する。tokenや抽出内容を共有ログへ転記しない。
3. 新規受付を停止し、1件を実行中に管理ツールの通常停止を要求する。実行中処理が返り、結果が1回保存されて次のジョブを取らず終了することを確認する。graceful timeoutがAI待ちより短い場合は強制終了へ移ることを実測する。
4. 別の未確認ジョブで、heartbeatによりleaseが伸びることを観測後、対象workerだけを強制終了する。原本とreading状態はDBに残り、未期限のleaseを後継workerが奪わないことを確認する。
5. 本来のlease期限を待って後継workerが再取得し、attemptsが増えてpreviewへ到達することを確認する。外部処理は再呼出しされ得る。呼出し2回を不具合として隠したり、業務登録の1回性と同一視しない。
6. 自動確認保存は行わず、利用者の確認を実行する別シナリオで業務行の重複がないことを確認する。古いtokenのfinish拒否・中断3回の上限・明示再試行はPR #278の既存試験を利用し、別実装しない。
7. ネットワーク断/タイムアウトは検証専用proxyまたは模擬APIで行う。会社・利用者の失効、受付削除、失敗分だけの再試行、再起動policyまで確認する。管理ツール全体や共用ネットワークを停止しない。

今回の `tools/q11_worker_readiness.py` は実 `run_worker` と実heartbeat/leaseを用いるが、通常停止は同じstop eventへの要求であり、配備用SIGTERM・Gunicorn・サービス管理ツールの組合せは未検証。Windowsの子プロセス強制終了も検証する。実有料APIへの接続・本番workerの操作は行わない。

## 人が決める受入条件

| 決める事項 | 記録すべき内容と承認者 |
| --- | --- |
| RPO | 許容する受付/確認済みデータの損失時間と例外、期間の計測点。業務責任者が承認し、不明値を0としない |
| RTO | 障害検知/復旧宣言のどちらから計るか、どの業務の再開を終了点とするか、許容時間。業務責任者と運用責任者 |
| 復旧対象時点 | DBのsnapshotまたはPITR目標、S3の世代manifest、書込凍結時刻の対応。DBAと原本管理担当が整合を確認 |
| 受付の再実施 | 選んだ時点以後の受付/確認の取扱い、二重受付・外部API再課金・再入力の承認。業務責任者 |
| 旧版の適用可否 | SHA、依存、認証/会社境界、データ互換、再導入条件。リリース責任者 |
| 業務再開 | 原本・件数・ACL・画面・workerの証跡を誰が確認し、誰が書込を開けるか。責任者と代理人 |
| 不合格時 | 原本不一致、説明不能な欠損、別会社公開、必要権限不足、RPO/RTO超過、未確認の重要画面があれば保留。別の復元先/世代を選ぶ承認経路 |
| 証跡と片付け | 保管期間、閲覧者、検証用VersionId・marker・DB/クラスタの終了/削除担当。運用責任者 |

時刻はUTCとJSTの対応を記録する。S3側とDB側の採取時刻があるだけでは同一時点の整合性を証明しない。失った受付を推測で作り直したり、欠損ファイルに合わせて元manifestを書き換えたりしない。

## 再現と依存関係

追加スクリプトのbootstrapはPR #278の未改変ファイルを要求する。#278がmainへまだ入っていない場合は、そのheadからファイルを検証用フォルダへ取得し、`--bootstrap`で渡す。新ブランチに#278のコードを複製してコミットしない。ロード前にGit blobを照合し、違う版は実行前に拒否する。

```powershell
python tools/q11_pg_readiness.py --bootstrap C:/verified-pr278/q11_recovery.py `
  --pg-bin 'C:/Program Files/PostgreSQL/18/bin' --work-dir work/q11-pg-new
python tools/q11_worker_readiness.py --bootstrap C:/verified-pr278/q11_recovery.py `
  --pg-bin 'C:/Program Files/PostgreSQL/18/bin' --work-dir work/q11-worker-new
```

アプリrequirementsを導入したPython 3.12を使う。work-dirは毎回新規。PostgreSQLへの環境変数は除去し、接続先はbootstrapが新規起動するloopbackクラスタに限定される。PGの試験はローカルtrust認証の下での認可確認であり、実際のSCRAM/TLS/認証期限の確認ではない。失敗時はJSONとコマンドログを保存し、所有するworkerとクラスタを停止する。起動したデータディレクトリを自動削除しない。

S3の実行条件と詳細手順は [Q11-s3-rehearsal-20261028.md](Q11-s3-rehearsal-20261028.md)。認証情報と運用条件が不足している現在は、同手順のAWSコマンドを実行しない。

`.github/workflows/q11-readiness.yml` は、固定した#278のbootstrapだけを取得して追加試験を行う。#278の22ケースは起動しない。CIも新規クラスタ・架空データ・模擬AIに限定し、実施状態はこの追加PRのチェック結果で確認する。

## 今回の実施結果

PostgreSQL 18.6、Python 3.12.14、Windows上の新規loopbackクラスタに、架空の2社のfixtureだけを生成して追加試験を行った。既存の22ケースはローカルでは再実行していない。

| 試験 | 結果と証拠の意味 |
| --- | --- |
| 限定権限・ACL・拡張・inventory | **11ケース成功、11.670秒**。limited backupでdump成功、limited restoreがownerへ明示SET ROLEして復元成功（0.597秒）。owner/ACL/default ACL/extensionの比較一致。runtimeのDML/sequence/hstore利用成功、CREATE/ownerへのSET ROLEはSQLSTATE42501。backupの書込とSELECT欠落、未承認restore role、ACL省略後のruntime読取を拒否。将来の表/sequence/関数への権限も確認 |
| inventoryの誤接続先ガード | 指定DB名の不一致でpsqlが非ゼロ終了。正常側はREAD ONLYで採取。`psql \quit`に終了コードを渡す方法ではなく、ON_ERROR_STOP下の明示エラーで停止する |
| 実worker停止・再開 | **4ケース成功、149.077秒**。通常stop eventで実行中の処理完了後に終了。17秒のAI待ちで15秒heartbeatによるlease更新を観測し、実子プロセスを強制終了。120秒のleaseを変更せず自然失効を待ち、その間は後継workerが再取得しないことを確認 |
| 再取得と重複 | 期限後にpreviewへ復帰、attempts=2、同じ資料への模擬AI呼出し2回、draft1行、業務行0、実API呼出し0。外部処理が一回だけ行われる保証ではない。利用者の二重確認保存の試験は含まない |
| bootstrapの検証 | 未知のbootstrapと不存在ファイルをロード前に拒否する単体2件を追加。未知のPythonが実行されず、クラスタへ進まないことを確認 |

両クラスタと起動したworkerは終了・停止済み。生ACLはinventory、比較前後はcatalog JSON、成否と所要時間はJSON/consoleログに保管した。最初の開発実行では所有sequenceの移管順やACLのNULL/既定表現差、psqlの停止条件を検出して補助資材を修正し、上表は修正後に全件実行した結果。製品コードの不具合と混同しない。function ACLは既定値を展開した実効privilege・grantor/grantee/grant optionを比較し、単に差を無視していない。

追加PRの最初のUbuntu CIでは、子プロセス起動時に補助スクリプト側のEvent参照が先に解放され、POSIX semaphoreの復元がFileNotFoundErrorになった。制御イベントを全子プロセスの終了まで保持する修正を追加した。製品コード、15秒heartbeat、120秒lease、拒否/重複の判定条件は変更していない。修正後のCI実施状態はPRのチェックで確認する。

## 更新後の残作業と見積もり

| 残作業 | 人時 | 依存する未提出情報 |
| --- | --- | --- |
| 検証専用S3での実IAM/VersionId/marker/SSE/署名URLとDB時点整合の受入 | 4–6 | account/role/bucket/prefix/region、保持・暗号鍵・認証条件 |
| 旧版SHA確定、依存・互換性、切戻し後の代表画面/登録/添付 | 2–4 | 承認された旧版と必要なセキュリティ修正 |
| 実環境相当のPG/provider/拡張/ACL/認証条件、実容量と容量制限試験 | 1–3 | DBAの環境台帳、容量分布、専用quota/volumeと性能条件 |
| 配備用管理ツールのSIGTERM/強制停止/再起動policy、検証proxyでの障害 | 1–2 | worker構成・台数・停止猶予・権限・模擬接続先 |
| 復元したサービスでの会社境界と業務上の参照、利用者確認保存の受入 | 2–3 | 代表資料・actor・画面URL・受入担当 |
| RPO/RTO・復旧対象時点・再入力・再開可否を決定し通し訓練 | 2–3 | 業務/運用責任者と承認基準 |
| 合計 | **12–21人時（1.5–2.625人日）** | |

前回16–26人時から4–5人時の削減を見込む残作業の再見積もり。上記の環境と担当が利用でき、重大な新規不具合がない前提で、外部の準備待ち時間や実容量の長い転送待ちは含めない。手順準備・局所検証の完了は、実S3・実容量・旧版画面・運用判断の完了を意味しない。
