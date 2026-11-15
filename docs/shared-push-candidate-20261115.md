# 共用端末 Push の取り違え防止候補（非本番）

## 範囲と目的

共用タブレットで A がログアウト・B へ交代した後、A 宛ての通知本文が端末に届く経路を狭める。通常の通知機能は変更しない。`SHARED_PUSH_CANDIDATE` は既定未設定（OFF）であり、TESTING と隔離済み session-authority candidate が必要。本番への設定追加・DB移行・デプロイ・通知送信はしていない。

購読と認証セッションの結び付けは独立 metadata の候補表。通常の `db.create_all()` では作成されず、試験のみ明示作成する。元の購読表に列を追加しない。

## 候補の実挙動

- 実 `/api/push/subscribe` で会社・本人・endpoint の指紋・認証セッションへ紐付ける。保存と紐付けは同一トランザクション。
- logout、本人交代、idle/absolute期限超過、紐付けなしは送信対象外。送信直前にDB判定する。
- endpoint の別人への引き継ぎ・owner不明の旧購読の取り込みは409で拒否。勝手に他人の購読を解除しない。
- unsubscribeとprovider 404/410では紐付けも削除。行IDが再利用されても別endpointは指紋不一致で送信しない。
- 候補で出すPushは「DKSS／お知らせがあります。ログインして確認してください。」のみ。本人名、個人本文、未読件数、個別業務リンクを載せない。タップ先は `/notifications` で、現在ログインしている本人の権限で再表示する。
- 候補OFF時は従来の本文・リンク・未読数を維持する。個人端末の既存運用を一律に汎用化する変更ではない。

## 限界・未受入

1. DB判定と外部Push送信は非原子的。判定直後に交代すると汎用通知が届く可能性は残る。旧利用者の本文・未読数は候補payloadに含まれないが、「何か通知があった」というタイミングまでは秘匿しない。
2. 既に配送済み・候補適用前に配送待ちになった個人本文の通知は撤回できない。この実装だけで切替前通知の安全移行を完了とはしない。
3. 共用か個人かの利用者向け選択UIは未実装。候補フラグはテスト全体に適用する実験用で、公開設定として利用しない。
4. B が旧endpointで409となった後のブラウザ購読更新UXは未実装。試験では別endpointでBの登録が成功することのみ確認。実ユーザーへ手動操作を押し付ける完成仕様ではない。
5. 実機のSW更新、OS通知欄、オフライン配送、通知クリック、多タブ、画面遷移中の表示は未受入。汎用payloadは既存SWでも個人内容を持たない設計だが、実機保証とは別。
6. session-authority自体も非本番候補であり、並行作業中の認証・書込境界検証が依存事項。

## 検証

合成データ＋一時SQLite、実Flask login/subscribe/logout/notification routes、Push transportは全てmock。本人交代 A→B 後のA非送信・B旧endpoint拒否・B新endpoint登録・Bの通知APIにAの秘密非表示を検査。外部送信なし。

PostgreSQL18用の独立CIワークフローを追加。loopback `dkss_q02_ci` と各試験固有schemaに限定し、URLがなければfallbackしない。CIはまだ実行しておらず、SQLite成功をPG成功と表現しない。

### 今回の実測結果

- 新規共用Push試験16件成功。独立レビュー側も16件成功。
- 共用Push・既存通知権限境界・通知失敗の秘密非表示・session authorityの関連回帰を合算し、76件実行、成功（1件は既存PG並行試験のSQLiteスキップ）。
- 独立レビューで発見した購読行ID再利用問題を修正後、旧bindingが残った場合でも別endpointは送信0件を再現確認。
- 検証コマンド: `PYTHONPATH=tests:. python -m unittest test_shared_push_candidate test_q02_notification_boundaries test_notification_delivery_safe_logging test_session_authority_candidate -q`。
