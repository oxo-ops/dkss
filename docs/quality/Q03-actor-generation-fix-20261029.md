# Q03 認証後の操作者入替

基準main 288261d。#283/#285/#297/#314を再実装せず、未保護だったパトロール新規と車両回答保存を既存のperson_selection.validate(actor_only=True)へ接続する。

修正前は、認証後～view前にAを削除し同username・同数値IDで別UUIDのBを作ると、パトロールnew/save-oneとも302で受理し、BのUUIDを操作者として新規保存した。SQLite/PostgreSQL各4件中、正常2件成功・保護期待2件失敗を確認した。

## 最小変更

- パトロールnewは参照Office/納入先/内容区分の検証・ロック後、添付アップロードや行作成前に操作者を照合する。
- 車両save-one/save-detailは既存の車両更新ロック・結果ロック/状態確認後、回答・コメント・添付の変更前に照合する。同じ「回答保存」の2エンドポイントを揃える。
- 認証UUID・会社・現在role/lock/password_changed_atを保存時に再照合し、不一致・本人消失はrollbackして409。PG FOR SHARE、SQLite BEGIN IMMEDIATEを既存実装のまま使用し、検証後の削除/降格も保存まで待たせる。
- 共通のperson_selection.py、Q08の通知配送・監査、マスタ処理、削除制限、一般承認条件は変更しない。新しいフォームパラメータやスキーマ/移行は不要。

## 回帰

test_q03_actor_generation.pyでSQLite/PG各27件。元の失敗2件を名前付き回帰として固定し、save-detail、本人消失、ロック、降格、同世代改姓/更新、他社、INSERT後の異常rollback/再試行を確認する。業務結果・イベント・通知・監査の全列スナップショットを比較する。

検証直後の別接続DELETE/role UPDATEがPG SQLSTATE 55P03、SQLite database is lockedとなることを実際に確認し、正当な元処理は成功する。ロックやSQL結果の代替は行わない。既存のQ03 PostgreSQL CIへ27件を追加する。

修正後54件成功（73.343秒）。本番や既存検証4DBを使用せず、新規専用クラスタ127.0.0.1:55434/dkss_q03_testと一時SQLiteで実行した。関連CIはPR headで別途記録する。

これは固定288261dの6処理統合移行リハーサル後の追加アプリ修正であり、そのリハーサルで検証済みとは扱わない。DDLの再適用は不要。未確定CSV所有者は別PR、パトロール対象者の表示～保存の選択競合や別の操作者経路は本修正の完了範囲に含めない。
