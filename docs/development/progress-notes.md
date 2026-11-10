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
読み取り専用表示。CASTTIME／DELAY／CANCEL への自動代入はしない（#109）。

### P1-C MOB配置編集の観測根拠表示（2026-11-03）

配置手動設定エディタにも同様の読み取り専用観測根拠を追加。追跡ピーク・初回座標・再観測間隔を
見せつつ amount／delay1／delay2／x／y へは自動代入しない（#110）。

### タイマー編集の演出ラベル拡張（2026-11-03）

手動タイマー編集画面が emotion／effect／解除以外で KeyError になっていたのを修正。
採用可能な全種別に日本語ラベルを出し、外部採用案内にも event_marker を追記（#111）。

### テスト整理（#109–#111 後 / 2026-11-03）

観測根拠・タイマーラベルの文言検証を unit に集約。GUI は配線のみ。
配置根拠を独立 unit へ分離し、外部採用案内は定数化。ソース読込照合を削除（#112）。

### CI offscreen Qt 警告と progressbar 役割（2026-11-03）

offscreen QPA の `propagateSizeHints()`/`raise()` をテスト側で抑制し、`show_panel` は
offscreen で raise_/activate しない。GUI 比較の 09D1 progressbar 期待を comment に更新（#103 後の取り残し）。
`run_tests` の Targets を1モジュール1行にし、CI ログの途中切れを「colored_speech で停止」と
誤認しないようにする（実ハングは GUI 側の offscreen 警告以降）。

### CI hang since Actions #135（shop ActorID / QMessageBox）（2026-11-03）

#89 の配置ヘッダ ActorID 必須化以降、World 由来の shop/会話 `npc` に `actor_id` が載らず
`ShopExportDialog.generate` が ValueError → `QMessageBox.warning` で offscreen CI が
30分タイムアウトしていた。entity→npc へ `actor_id` をコピーし、export は record 側を
フォールバックに使う（#114）。bundle の `shop_name_for`／barter `hidden_definition` も
同フォールバックへ揃え、欠落時は除外記録へ回す。`render_npc_file` は `npc.actor_id is None`
でも会話／寄与の ActorID へ落とす（`.get` の default では None を置換できない）。
bundle の並びキーも reference の明示 None より npc 側の有効 ActorID を使う。

### offscreen generate の QMessageBox（2026-11-03）

shop／MOB skill・spawn／timer の `generate()` 失敗は `gui.qt_messages.warning` 経由とし、
`QT_QPA_PLATFORM=offscreen` ではモーダルを出さない。プレビュー付き編集は本文にエラーを残す。

### MOB配置観測の非同期保存（2026-11-03）

`MobSpawnPanel.save` を skill／combat と同じ `export_report`／`prepare_mob_export` 経路へ揃える。
spawn は `records` 件数で凍結判定（`events` なし）。

### ショップ観測の非同期保存（2026-11-03）

`ShopPanel.save` も同じ共有 `export_report` スロットへ揃える（ダイアログ前に snapshot 凍結）。
候補テキスト出力と amount／delay 補完は対象外。失敗は `gui.qt_messages.warning`。

## v0.0.8保存到達点（2026-11-03）

詳細は[保存記録](../releases/v0.0.8.md)。手動タイマー境界・クエスト年表・MOB編集根拠・
ActorID／offscreen CI対策・共有非同期保存までをソースZIPへ保存。v0.0.4–v0.0.7 ZIPは変更しない。
次の着手は「次の着手単位」を正とする（実機確認、視覚エフェクト出典待ち）。

### 実機15MiB生ログとGUI再生上限（2026-11-03）

実使用ログ（約16MiB／約2.2万パケット）が既定のGUI再生上限（2万パケット）で開けない。
設定→記録でパケット件数・RAW合計をローカル拡張できるようにし、CLI
`python -m tools.analyze_session` でのJSON変換手順を再解析資料へ明示した。

### トネリコ木会話とナビ 08E2（2026-11-03）

`prt_fild05` の `小さなトネリコの木#c1p1`（class 10620／ActorID 6979）会話で、
「一緒に行く」後に RECV `08E2`（27B）→ close → cutin解除 → `0092` warp（`ygg_edge`）を確認。
フレーミング欠落・未知ID停止はなし（replay errors 0）。公式
`PACKET_ZC_NAVIGATION_ACTIVE` と rAthena `navigateto`／`clif_navigateTo` に合わせ構造化。
会話中は `navigation_action` として会話へ紐付け（コメントのみ）。会話外は
`navigation_active`。続き採取（ygg_fruit／ygg_roots）でも同様。
同セッションの `ナビエル` は `0144` viewpoint と mes の `<NAVI>` タグ（本文保持のみ）。
詳細は[未対応通知](../npc/unsupported-notifications.md#クライアントナビ開始08e2)。

### 視界外 cloak／出現options（2026-11-04）

作業仮説（クライアント cloakoff リストは MAP 滞在限定・移動で消失、再シードは到着付近
OnTouch 等）を対話復元メモへ記載。再出現で `initial_options` の hide/cloak と今回
options が食い違う場合は `visibility_action`（`basis=appearance_vs_initial`）として
会話外観測のみ残し、タイマー cloak 命令には出さない。調査地点#ch01_1 は初回 cloaked→
0229 off、同MAP再出現は出現時点で非cloak。同セルの `#ch1evt_*`（class 139）を
`colocated_touch_npcs` として併記。OnTouch→リスト命令生成は未実装。

### actorコメント／ignorepacket flag／showevent・status抑制（2026-11-04）

観測ログの `// {actor_id}` 系を名称取得時 `名称(actor_id), x, y` へ。ignorepacket は
PacketID ごとの flag（&1 ログ、&2 SQLite 非保存）とパケット詳細からの追加 UI。
showevent（0446）は `showevent_flag` 変化時のみログ、9999 は spawn 無しなら観測ログのみ。
update_status（00B0系）は HP/SP 等を抑制し Zeny／EXP を残す（#126）。

## v0.0.9保存到達点（2026-11-04）

詳細は[保存記録](../releases/v0.0.9.md)。ナビ08E2・cloak併記・actorコメント／ignore flag・
showeventflag・update_status抑制・大容量再生上限までをソースZIPへ保存。v0.0.4–v0.0.8 ZIPは変更しない。
次の着手は「次の着手単位」を正とする（実機確認、視覚エフェクト出典待ち）。

### Auriga UI命令（auriga/auriga#97 / 2026-11-05）

Auriga に `navigateto`／`progressbar_npc`／`viewpointmap`／`camerainfo` が追加された。
KYRiE は会話内 08E2→`navigateto`、会話元 09D1→`progressbar_npc` を生成する。
タイマーの progressbar コメント採用と秒数≠OnTimer は維持。viewpointmap は 0144 と区別できないため未生成。
0A78 camerainfo は観測ログへ暫定追加（`@camerainfo`、f32 3値）。本文命令化はしない。

### Zeny／BaseExp／JobExp 差分の命令化（2026-11-06）

00B0/00B1/0ACB の残高変化で、ログイン等の初回読み込み以外の差分を扱う。
Zenyは観測ログでも `set Zeny,Zeny+1000;` 形式。BaseExp/JobExpの増加は戦闘洪水を避け、
観測ログには出さず会話資源への紐づけ＋採用時のみ `getexp` 化する。
減少EXPと差分不明は観測コメントのまま。

### 大容量・短時間多パケットの追加耐性（2026-11-06）

#129 の表 thrash 修正後も、表示更新ジョブ中の退避停止と診断ラベル毎パケット更新が
洪水時の負荷源になり得た。退避はジョブ取消＋stale化して継続し、進捗表示を間引く。
パネル再描画は250msタイマーで既に間引き済み（revision未変化なら各パネルが省略）。

### 観測ログ切り詰め時のスクロール（2026-11-06）

実機で本文容量調整の `setPlainText` 後にスクロールが先頭（最古）へ飛ぶ報告。
追従中は切り詰め／再構築後に末尾へ戻す。

### 大容量取得時の応答なし（2026-11-06）

v0.0.9 で約5万件・メモリ上限到達・Land Protector 等の skillunit 多発時に
「応答なし」報告（生ログなし）。最新ページが insertRow のみで行数上限を超え、
上限後の毎パケット退避がページ数振動付きの全再構築を繰り返していた。
退避を表更新より先にし、行数を1000件で付け外し追従するよう修正（#129）。
観測本文の toPlainText 切り詰めも間引く。追加の洪水耐性は #131。

### 0ACC 経験値通知の観測ログ抑制（2026-11-06）

00B0系差分の getexp 抑制後も、戦闘の 0ACC Experience gain が観測ログへ
`getexp` を出していた。0ACC は表示テンプレートを空にし、命令化は会話資源採用のみ（#133）。

### v0.0.9後の点検まとめ（2026-11-06）

Open issues なし。#128–#133 を main へ反映済み（Auriga #97 命令、洪水耐性、
Zeny／EXP方針、0ACC抑制、観測ログ末尾固定）。文書の正本は
[次の着手単位](development-roadmap.md#次の着手単位) を更新して揃えた。
次スナップショット v0.0.10 は利用者指示で作成する。

### 文書分割・GUI UX の検討（2026-11-06）

利用者／開発ドキュメント分割、GUI発見性の方針を
[packaging-docs-gui-ux.md](packaging-docs-gui-ux.md) に整理。**EXE化・EXE配布はしない**と確定。
docs 目次を利用者／仕様契約／開発の入口に再編。実装は v0.0.10 スナップショット後。

## v0.0.10保存到達点（2026-11-06）

詳細は[保存記録](../releases/v0.0.10.md)。#128–#135（Auriga #97、洪水耐性、Zeny／EXP、
0ACC、docs同期、EXE化なし方針）までをソースZIPへ保存。v0.0.4–v0.0.9 ZIPは変更しない。
利用感変更（GUI P2・ガイド純化）の前基準点。次の着手は「次の着手単位」を正とする。

### GUI P2-1 と操作ガイド純化（2026-11-06 / v0.0.10後）

ヘルプメニュー（操作ガイド／About）、主要ヘッダー toolTip、状態ラベルクリックで診断。
`gui-workspace.md` から未実装予定・旧検証件数の段を除去。EXE化なしを操作ガイドにも明記。

### GUI P2-2 ショートカットと開始前確認（2026-11-06）

F5 観測開始／F8 停止／Ctrl+Shift+O 生ログ（入力欄編集中は無効）。
開始前チェックリストは案内のみで capture／display 設定を自動変更しない。
既読は `user_settings.json` の `startup_checklist_seen`。offscreen では自動表示しない。

### ignorepacket ローカル化と不在時プリセット（2026-11-06）

`config/ignorepacket.json` を Git／スナップショット対象外にし、不在時は
`IgnorePacket.ensure_default_file` で空プリセットのみ生成（既存非上書き）。
ZIP へ空 ignorepacket を注入しない。雛形は `ignorepacket.example.json`。

### GUI P2-3 タブ初期プリセット（2026-11-06）

`user_settings.workspace_preset`（`observe`／`restore`）で起動時の前面タブのみ切替。
観測中心=観測ログ、復元中心=会話・コード。設定→表示コンボと作業→タブ初期表示。
全タブは残し、パネル非表示や生成規則は変えない。プロジェクトの `view.tab` が優先。

### P2完了後の着手単位再同期（2026-11-06）

#136–#139（v0.0.10、Help、ショートカット、ignorepacket ローカル化、P2-3）反映後、
「次の着手単位」から完了した GUI P2 を外し、実機確認・観測のみ維持・任意 docs 移動へ整理。
open Issue 空のため post-P2 backlog を Actions で再登録。

### OnTouch入場枠と演出（2026-11-06）

範囲は入場セルの軸オフセットを候補とし、両軸非ゼロで暫定解除。カバレッジは外側→内側のみ入場。
一意入場時は cloak／effect／viewpoint を warp と同様に OnTouch枠（`touch_range_entry`）。
同セル同時候補は `simultaneous_colocated_touch_candidates`。リスト命令・キュー順は発明しない。

### OnTouch再入場・未観測cloakoff・名簿・プレイヤー除外（2026-11-06〜07）

再入場は `ontouch_reentry` で別 OnTouch 枠。未観測 0x0229 は同セッション後観測で
`cloakoffnpc "名"; // actor_id`（複数ログ横断はしない）。ワークスペースNPC名簿は
他取得の同 ActorID 名ヒントのみ（#147）。プレイヤー waitingroom／スキルは NPC 出力外。
本人スキルは使用 SEND なしのときだけ `skill` 候補（#148）。

## v0.0.11保存到達点（2026-11-07）

詳細は[保存記録](../releases/v0.0.11.md)。#137–#148（GUI P2、OnTouch枠、名簿、
プレイヤー除外）までをソースZIPへ保存。v0.0.4–v0.0.10 ZIPは変更しない。
次の着手は「次の着手単位」を正とする。

### export／bundle 観測一貫性（2026-11-07 / v0.0.11後）

warpのみ OnTouch の native `warp` 行を個別NPC保存にも適用（bundle と同判定）。
全件 callshop／barter 前置に個別と同じ review・品名ヘッダを残す。
個別 shop／barter と手動タイマー候補も会話／bundle と同じ本人情報保護を適用。
全件出力へ touch_warp_inferences を渡し選定理由を維持。shop／barter も script_indent を共有。
merge_dialogues も protection_identity を適用。
CLI merge／session も touch 根拠を渡す。タイマー候補も script_indent を共有。
GUI 統合JSONへ protection_identity を記録。
