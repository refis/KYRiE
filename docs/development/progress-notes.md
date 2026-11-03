# 保存後の経過メモ

[資料一覧](../README.md) · [開発計画](development-roadmap.md) · [採取リスト](../capture/raw-packet-collection-checklist.md)

development-roadmap.md 本体の「次の着手単位」とは別に、v0.0.5 保存以降の採取・点検メモを時系列で残す。
仕様の正本は各機能 docs と releases。ここは経過の索引として扱う。

## v0.0.5保存到達点（2026-10-30）

MAP・クエスト・ナビゲーションの名称／参考資料検索を完了。詳細は[保存記録](../releases/v0.0.5.md)。
資料と実観測は分離し、ナビID・MOB複合値や説明からサーバー側処理を推定しない。
次は実パケット採取リストの未検証経路を、該当場面が確認できたものから優先する（0x0B79／exchange は当面保留）。
stateiconimginfo の画像名辞書化は行わない。視覚エフェクト日本語は出典確認まで空のまま。
手元 `.reference`／`client` は読取専用利用可・原資料はリポジトリ外。
0B38 は PacketLength 未登録のため構造追認の優先対象にしない。
経路探索・クエスト説明全文表示は任意の後続機能。実機・Auriga・新規環境確認の保留は維持する。


### 未採取条件の現状と点検修正（2026-10-30）

既存2ログの再解析でメニュー／next未応答終了と0BA2は再確認。数値／文字inputとその未応答終了、
0BA1/0BA3/0BB5、02F2/09D1は実例なし。再採取の優先順は[採取リスト](../capture/raw-packet-collection-checklist.md)末尾へ反映。
新規実例がない仕様は推定で拡大しない。点検中に見つかった会話解析CLIの旧式保存を共通方式へ統一し、
入力・config上書き拒否、元ログ／定義変更検知、保存失敗時の既存結果保持を追加した。対象3項目通過。

### 採取リスト再優先（2026-11-01 / Issue #46）

20261101-194609-edbe9ab0で数値input（0142／0143）と数値未応答終了（約180秒）を確認。
全会話16件と getitem2 review（期限付き item 100736×3）も記録。文字input、0B38未鑑定、
0BA1/0BA3/0BB5、02F2/09D1、0x0B79は引き続き未採取。
同ログの RECV 0x0B0E×1（close直後504byte／20商品）は `clif_barterlist` としてデコード済み。
0x0B79は `clif_expanded_barterlist` に基づくデコードを合成で契約確認（実機ログは未採取）。
近傍 0x0A30 は名前応答。次の最小1本は文字inputの正常→未応答→正常。
ハッシュと採取メモは[採取リスト](../capture/raw-packet-collection-checklist.md)の 2026-11-01 節。ログ本体はリポジトリ外。

### 文字input／shop・barter／02C1実機（2026-11-02）

20261102-171318-9aba07f0で文字inputの正常→未応答（約180秒）→正常、通常shop（00C6×2）、
0x0B0E×2、実機 0x0B56×3 を確認。20261102-173136-edcd6b68で 02C1 MOB colored_speech×1
（会話外・unittalk非生成）を確認。0x0B79／exchange は未採取のまま（2026-11-02 時点で取得検証保留）。
ハッシュと採取メモは[採取リスト](../capture/raw-packet-collection-checklist.md)の 2026-11-02 節。ログ本体はリポジトリ外。


### O2: 会話JSONの必要時整形（2026-10-30）

非表示の全演出JSONと選択会話の根拠JSONは、表示／本文要求時に整形する方式へ変更。
統合モードの通常根拠→統合根拠の二重シリアライズを除去。ストア実体・revision・選択・資料参照・統合状態を照合する。
GUI更新前の受信更新も表示前に同期する。モデル・全件保存・命令生成を変更しない。
関連7項目を確認。合成5,000観測・非表示20更新で整形20回を初回表示の1回へ削減し、918,306文字のJSONが一致。
非表示更新約0.18ms、初回表示約86ms、再取得約3.2ms。取得・全GUI更新やピークメモリの性能を表す計測ではない。
初回表示の大規模整形、統合計算、タイムライン再構築のUI負荷と履歴保持量は引き続き最適化対象。

## v0.0.7保存到達点（2026-11-02）

詳細は[保存記録](../releases/v0.0.7.md)。shop/barter・display_only観測・MapTypeProperty・
履歴退避（#77）・docs整理（#81）までをソースZIPへ保存。v0.0.4–v0.0.6 ZIPは変更しない。
次の着手は「次の着手単位」を正とする（実機確認、視覚エフェクト出典待ち）。

### O2続き（#85 / 2026-11-02）

演出JSONの差分キー抑止と `profile_memory_eviction` を追加。既定上限 50000 は維持。
会話64件以上の統合は MergeWorker へ移し、完了キー不一致は破棄。残る実機ピークに基づく上限変更は任意。

### P1-B 手動タイマー境界（#96–#107 / 2026-11-03）

会話外の classchange／visibility／viewpoint／event_marker／npc_display を実行命令候補へ、
effect_value／hat_effect／colored_speech／progressbar／cutin／mapcell／viewpoint未対応値を
コメント採用へ揃えた。sound／music／progress_action 等の拒否は維持。
roadmap の MARiA 差分表・P1-B・次の着手単位を現行コードに再同期（#108）。

### P1-C MOBスキル編集の観測根拠表示（2026-11-03）

手動設定エディタ上部に、開いた時点で固定した観測根拠（詠唱通知・個体内間隔・cancel件数等）を
読み取り専用表示。CASTTIME／DELAY／CANCEL への自動代入はしない。
