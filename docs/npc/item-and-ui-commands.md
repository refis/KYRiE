# 所持品・装備・倉庫・床アイテム・待機室の復元

[資料一覧へ](../README.md) · [会話復元](dialogue-restoration.md)

生成内容は観測に基づく編集用候補。会話中はOnTouch候補も含む。
起因・隠れた変数条件は復元せず、命令の成立条件と元Packetを保持する。
cutincardはユーザー指定により実装対象外。既存のcutin（表示位置4を含む）は維持する。

## 条件と出力

- openstorage: 会話の有無を条件にしない。0x00F2を倉庫開状態の候補とし、
  0x00F8で閉じるまでの数量更新では重複生成しない。倉庫種別・呼出元までは確定しない。
  会話外では未所属候補、会話中では本文へ保存する。通常の観測表示も最初のopenstorageだけにする。
- openreform: RECV 0x0B8F（ZC_OPEN_REFORM_UI、固定6バイト、ITID u32）を
  `openreform {item_id};` 候補とする。Auriga未実装のため常に確認用コメントで残す。
  会話の有無を条件にせず、close応答後2秒以内ならclose2継続へ帰属できる。
  rAthenaの`item_reform`相当の観測であり、Reformレシピや成功率は復元しない。
- sc_end: 会話中の本人向け0x0196/0x043F/0x0983の終了通知を、状態異常ID変換表でSC番号へ変換する。
  他人への通知や未対応IDを自分向けの終了命令に置き換えない。
- getitem/getitem2: 会話中の成功した入手通知。通常アイテムはgetitem、鑑定・精錬・属性・カードを
  持つものはgetitem2。ランダムオプション・grade・期限・bindingを持ち、getitem2で表せない場合は確認用コメントとする。
  アイテムIDはクライアント観測値の候補であり、対象DBとの一致を保証しない。
- delitem/delequip: 会話中の消失通知と、所持品Indexに対応する観測済みItemIDが必要。
  装備中の部位を特定できる場合はdelequip、それ以外はdelitem候補。
  装備個体・部位・IDが不足する場合は引数を補わずコメントへ残す。
  倉庫移動、カート移動（所持品⇔カート）、観測した捨て操作に対応する増減を
  NPC報酬・消費へ変換しない。カートSEND（0x0126/0x0127）は取得世代・flow・MAP世代・
  数量・確認できるIndexで応答と照合し、カートIndexと所持品Indexを同一視しない。
  曖昧な対応は実行可能命令にせず未確定として残す。
- successrefitem/failedrefitem/downrefitem: 会話中の0x0188と装備部位の対応が必要。
  downrefitemは観測した精錬前後の差分を使い、差分不明ならコメントとする。
  successrefitemも前値が分かる場合は+1との整合を確認する。
  命令自身が変更・削除を行うため、対応する先行unequip/delitem/delequipは確認用へ移して重複処理を防ぐ。
- unequip: 成功した解除応答で装備部位が分かり、同じ接続・MAP世代に対応する解除SENDがない場合。
  操作SENDは対応する応答まで保持し、遅い応答を単なる時間切れでスクリプト由来にしない。
- sit/stand: 本人への姿勢通知で、対応する操作SENDがない場合。
  会話中なら本文、会話外なら未所属命令候補へ保存する。他プレイヤーの姿勢を転用しない。

入力待ち中に届いた命令は実際の返信後のブロックへ仮配置し、その旨をコメントに残す。
通常close後の無関係な入手・状態通知から会話を再開しない。
openstorage／openreformは既存のclose応答後2秒以内の帰属候補へ関連付けるが、タイムアウト疑いのcloseは再開しない。
送信・受信の半接続名が異なってもflowで照合する。接続・capture・MAP世代を越えて操作を借用しない。

## 交換系（未実装）

RECV 0x0B56（ZC_NPC_EXPANDED_BARTER_MARKET_ITEMINFO、可変長）はKYRiE未デコード。
rAthenaのpackets.hppではitems_count付きの拡張barter一覧（nameid/type/amount/weight/index/zenyと
通貨配列）として定義され、新しいPACKETVERでは0x0B79へ移行する。
Aurigaの`- barter`宣言やcallshop相当の復元経路はまだない。未観測行を捏造しない。

## 床アイテム

床アイテム履歴・モンスタードロップ一覧／集計の増設は対象外（利用者指定、2026-10-29）。
モンスタードロップの整理は公式データ参照を基本とする。以下はNPCのdropitem候補に必要な既存処理。

既知MOB死亡・捨て操作を伴う出現はdropitemから除く。同一flow・MAP世代で前後を照合し、
後続の死亡通知で対応が分かった候補も確認用へ戻す。相関窓は判定設定のcorrelation_ms（既定2000ms）。
この値をNPCタイマーに転用しない。MAP入場直後の床アイテムは、既存物の視界内出現との区別が
できないため確認用とする。床IDの重複通知も重複生成しない。

総寿命はユーザー指定の60000ms。Aurigaのdropitemのtick引数はflooritem_lifetimeへの加算値なので、
指定総寿命から想定基本寿命を引いた値を出力する。参照Auriga/conf/battle_auriga.confの基本値は60000msで、
通常の生成引数は0となる。出力コメントにも総寿命・想定基本寿命を残す。
対象サーバーの基本寿命が異なる場合は判定設定を合わせる。未確認ならnullにすると引数を補わず確認用にできる。
インスタンス内のscript命令ではMAPを正規化し、getmdmapnameを使う。

## waitingroom

0x00D7の所有者を同一世代のNPCと確認できた場合に、titleとlimitを個体情報へ保存する。
配置だけのNPCも本文をendで終了してからOnInitへwaitingroomを出す。
会話がある場合は会話の終了命令を維持し、OnInitを追加する。
同じtitle/limitは重複させず、異なる観測値は確認用ブロックで残す。
参加人数・chat_idは根拠として保持するが、未観測のイベントラベル・課金・開始条件は生成しない。
通常shopへ付いた初期化は既存制約どおり確認用コメントとし、補助NPCを捏造しない。

所有者がNPCと確認できた待機室通知だけを観測ログから隠す。生ログ・パケット表/HEX・個体根拠は残す。
他プレイヤーのチャットや未確認の所有者は、この規則だけでは隠さない。

## 設定・根拠・検証

- config/auriga/script_commands.json: 相関窓、操作PacketID、Aurigaの部位変換、総寿命・基本寿命。
  部位順はAuriga/src/map/buildin_item.cのequip_posに従い、pc.c内部の順番とは分ける。
  操作IDは既知の形式のみ登録する。位置が異なる新形式をID追加だけで対応済みにしない。
  cart_from_body / cart_to_body にカート移動SENDを置き、倉庫open状態抑止とは別に照合する。
- config/auriga/dialogue.json: script_getitem等と確認用コメントの書式。
- config/auriga/entity_metadata.json: waitingroomとOnInitの書式。
- config/auriga/status_ids.json / config/rathena/status_ids.json: 状態異常のクライアントアイコン→SC変換（エミュレータ切替で選択）。

設定変更後はログを再解析する。CLI解析は判定設定のSHA256も保存する。
会話のactions、dialogues.script_command_observations、script_command_candidatesへ元Packetと生成文を保持する。
NPCが特定できない命令を近くのNPCへ自動で貼り付けない。容量超過は明示し、完全な会話と扱わない。
所持品番号が消失後に再利用された場合も、以前の装備部位を借りない。

検証はpython -m tools.run_tests commandsで命令機能を選択できる。
装備・精錬・倉庫・姿勢・waitingroom等は合成パケットで成立／除外を確認した。
20261028-012526-0abe69d9では解析問題0、getitem11件・dropitem9件、141配置・配置除外12件を確認。
このログに精錬・waitingroomの実例はない。Auriga実環境での実行確認は未実施。
最新出力はall-placed-npc-script-commands-merged.txt/jsonとindividual版。
