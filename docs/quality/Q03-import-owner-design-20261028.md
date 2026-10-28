# Q03 取込所有者の内部ID参照

承認候補の修正に続く設計調査。Q02との重複を避け、取込所有者のアプリ改修・DB移行はこのPRで行わない。

## 現在の参照とQ02の既存保護

- `models.py`のVehicleDocumentImportDraft.created_by_username、VehicleOperationImportDraft.created_by_username、VehicleImportPending.created_by_username、VehicleImportPendingRecord.created_by_usernameが所有者参照となる。
- `document_import_queue.py`のenqueue、delete_receipt、batch_status、retry_failed、lightweight_queryが会社＋usernameを使う。
- `document_import_routes.py`のown_batch、recent_importsが所有者判定を利用し、登録・取消し・再試行・原本確認へつながる。
- `vehicle_imports.py`は確認画面・原本・確定・種別変更・保留処理等で会社＋created_by_usernameを照合する。
- `document_import_queue.py:owner_available`は現在の会社有効状態、Userの存在・ロール・ロックを処理境界で再確認する。Q02の削除・ロック・降格・処理中失効の対策は既に存在し、再実装しない。
- 会社内でAを削除し、別User.idの管理者Bが同じusernameを登録する場合、現在の所有者判定は世代を区別するIDを保存していない。同一会社での所有者交替の全実ルート再現は未実施であり、修正済みとは扱わない。

## 次の最小設計

1. 受付時にowner_user_idを固定する。created_by_usernameは表示・操作時の証跡として保持する。削除により所有者IDをNULL化したり別人へ置き換えたりしない。
2. HTTPとワーカーの両方で、会社＋owner_user_id＋現在ロール・ロック・会社有効状態を判定する。受付件数制限、upload_key再送、バッチ取消し、再試行、原本参照も同じIDへ統一する。
3. 分類・抽出・プレビュー確定・種別変更の各境界で同じowner_user_idを再確認する。Q02のowner_availableを置き換える場合は、その既存試験と処理中失効の保証を維持する。
4. Pending群と再振分け先へ同じ所有者IDを引き継ぐ。usernameから新しい所有者を取り直さない。
5. 旧取込の所有者IDはusernameだけで補完しない。管理者による根拠付きの引継ぎ手順が必要。登録済み原本を会社内で共有する既存仕様と、未登録原本の所有者限定仕様を混同しない。

## 必要な回帰テスト

| 境界 | 検証 |
| --- | --- |
| HTTPの受付・状況取得・プレビュー・原本 | A受付後に削除、同一usernameの管理者Bを作成。Bが旧バッチ・原本を取得できず、新しいバッチだけ扱える。 |
| 再試行・削除・確定・種別変更 | 同一usernameのBや他社同名UserのPOSTで旧データ・処理状態・原本を変更しない。upload_keyを再送してもAの受付をBのものとして返さない。 |
| 分類・抽出中 | 処理途中でAを削除しBを登録しても、Aの結果をBの権限で公開しない。既存のロック・降格・会社停止の試験も維持する。 |
| 保留・複数資料・再振分け | 元のowner_user_idを維持し、別会社・別アカウントへの混入や一部保存を防ぐ。 |
| 正常系・復帰 | 同じUser.idをロック解除したAは現権限で再試行できる。別IDの新規アカウントを同じ人と自動判定しない。 |
| 移行・切戻し | 追加列・新旧JSON・原本・結果不変、冪等性、PostgreSQL同時処理を確認。列は削除せず、旧コードへの切戻し時に漏えいを再開しない保守手順を用意する。 |

改修・回帰の概算は3～5人日。旧所有者の根拠確認・引継ぎツールは別途1～2人日以上で、対象件数に依存する。Q02と担当ファイル・処理境界の設計を合意してから実装する。Notification・Push・通知配信はQ08の担当を維持する。
