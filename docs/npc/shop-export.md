# 通常shopとcallshopの編集用出力

[資料一覧へ](../README.md) · [プロジェクトREADME](../../README.md)

NPC → ショップ観測 → 保存… → Aurigaショップ候補… を選択する。
商品一覧1件に対する候補を生成し、観測記録そのものは変更しない。
配置のみ・会話NPCとまとめる場合は「出力 → 配置付きNPCコードを全件出力…」を使用する。
全件出力は観測商品IDの未照合候補と明記し、個別出力のDB対応確認とは区別する。

## 2つの形式

初回NPC状態と根拠パケットはショップ観測にも保存し、確認画面の配置元に表示する。
後続のhideoff/cloakoff相当の状態更新があっても初回値を維持する。
callshopの会話NPCはscript(HIDDEN)／script2(CLOAKED)の出現定義に対応する。
会話なしの通常shopにはAuriga上の状態指定構文がないため、初回HIDDEN／CLOAKEDの候補は
全行コメントで保存する。状態を捨てて通常表示にしたり、未観測の会話やOnInitを追加したりしない。
注意文はconfig/auriga/shops.jsonのinitial_state_reviewで変更できる。

- 会話なし: 配置付きshop NPC定義。通常の会話scriptは生成しない。
- 会話あり: 通常NPCの配置・観測本文と、非配置の別shop定義を同じファイルへ出力する。
  選択した観測経路のショップ遷移位置でclose2、callshop、endを生成する。

callshopの呼出し先は候補用のGPA_Sから始まる名前で、観測商品の内容と配置から生成する。
これは元の隠れたショップ名ではない。既存NPCとの名前衝突は導入前に確認する。
呼出しは元の会話末尾のendの後ろへ付け足さず、選択肢・入力ブロック内の観測位置に置く。
未選択分岐は従来どおり未観測として残す。起因・変数・報酬条件は生成しない。
複数経路をまとめたcallshop出力は未対応で、まずショップ一覧に対応する単一経路を使う。

## 確認する値

対象選択と購入応答が一致した一覧を使う。表示IDはクライアント側の値なので、
出力先DBとの一致を確認し、画面のチェックを有効にしてから生成する。
未確認のままIDを自動変換しない。別IDへの変換表は未実装。
価格は割引価格ではなく通知された基本価格を使う。重複ID・範囲外の価格やIDは生成を停止する。

## 品名（資料）の併記

候補ヘッダへ `// 品名（資料）: <client_item_id>=<識別済名称>; …` を付ける。
shop／callshop宣言の数値IDと価格は変えない。未登録IDは `未登録` と書き、名称を発明しない。
GUIのショップ観測表「品名（資料）」列と同じ client_names 辞書を使う。
未鑑定名称は採用しない。DB IDへの変換やコード引数の書換えではない。

マップ・座標・向き・外見・名前が必要。
マップ未観測時だけ、利用者が確認したマップ名を入力できる。候補には「利用者入力」と明記する。
NPC名の#接尾辞からマップを推測しない。観測済みマップの書換えはしない。
それ以外の配置項目は既存の[NPC配置出力](npc-file-export.md)と同じ検証を行う。
対象未解決の一覧から座標・名前を仮作成することはない。

## 会話との対応

RECV 00C4をショップ遷移の境界として保持し、一覧にconversation_idと
conversation_link_basisを記録する。GUI・CLIのショップ解析で同じ対応を行う。
会話開始だけで本文がない経路は会話なしの候補となる。
本文を観測した経路を、本文を捨てたshop NPCへ自動置換しない。
未応答プロンプトや会話解析問題が残る場合はcallshop候補を生成しない。

通常の会話終了通知の後にショップが開く場合、別の会話・マップ切替を挟まず
同じフローで2秒以内ならsame_flow_after_closeとして関連付け候補を残す。
終了前に00C4を受信したactive_dialogueとは区別する。
00C4/00C5を挟まずRECV 00C6（または0B77）だけが届く経路も、同じ2秒枠なら
after_close_listとしてcallshop候補に含める。一覧パケットをshop_opened境界とし、
close2継続の一種として扱う。対象選択付きのselector_and_buy_replyとは区別する。
これは時間的な候補であり、元のcallshop実装やNPC起因を確定する判定ではない。
期限外や関連会話がない場合は、近傍NPCの台詞を借りてcallshop本文を作らない。
別NPCの操作が混じった可能性は根拠で確認する。

非配置の`- shop`定義は、callshopを使う配置NPCの直前へ出力する。
Auriga未実装のbarter／exchangeなどは、観測できた場合のみ`//- barter`／`//- exchange`
として同じく非配置行で残し、実行可能な命令へ昇格しない。未観測の交換行は作らない。

close/close2の元の命令は通信だけで確定せず、出力では会話を閉じて呼び出すための
編集用構造としてclose2を使用する。タッチ範囲・タイマー・スクリプト移動は復元しない。
callshopのtypeは省略して取引メニューを開く。購入専用や売却専用の元コードを推測しない。

## barter一覧（0x0B0E / 0x0B56）

いずれも close 応答後2秒以内なら after_close_list として会話へ結ぶ。
非配置の`//- barter GPA_B…`を配置NPCの前へ出し、本文側は`close2`と`// callbarter`コメントを置く。
在庫`0xFFFFFFFF`は`-1`、通貨精錬`0`は脚本慣例の`-1`へ写す。Auriga未実装のため常にコメント。

### RECV 0x0B0E（clif_barterlist）

ヘッダ4byte（ID・長さ）のあと、商品行は固定25byte。
`nameid u32` / `type u8` / `stock u32` / `currency_itemid u32` / `currency_amount u32` /
`weight u32` / `index u32`。長さは `4 + 件数×25`。zeny欄はなく、出力では zeny=0・通貨1件として写す。
20261101-194609-edbe9ab0で悔恨の侯爵#tor 会話#4の close 直後に1件（504byte＝20商品）を確認。

### RECV 0x0B56（拡張barter・旧レイアウト）

件数 u32 のあと、商品26byte＋通貨12byte×N（viewSprite／locationなし）。

### RECV 0x0B79（拡張barter・clif_expanded_barterlist）

提供ソースの PACKETVER 分岐を、長さが過不足なく消費できる一意レイアウトだけ採用する。
曖昧・不一致は失敗させ、未観測行は作らない。

- `>=20260107`: 商品ヘッダ36byte（currency_count@+28、refine@+32）+ 通貨12byte×N
- `>=20250402`: 商品ヘッダ36byte（refine@+28、currency_count@+32）+ 通貨12byte×N
- `>=20210203`: 商品ヘッダ32byte（currency_count@+28、refineなし）+ 通貨12byte×N

look／equip／refine は観測保持。脚本候補の商品行は従来どおり `ID:在庫:zeny { 通貨… }`。
実機ログの 0x0B79 は未採取（合成で契約確認）。0x09CF／0x09D0・0x0A30 は barter としない。

書式はconfig/auriga/barters.json。

## 書式と検証

shop宣言と注意文はconfig/auriga/shops.json、callshopや本文はconfig/auriga/dialogue.jsonで変更できる。
生成ファイルはUTF-8。ログ・生成書式への上書きは拒否する。
元ログ、ショップJSONと会話JSONも保管する。プロジェクトは生成ファイル自体を保持せず、
shops.jsonの書式ファイルも現時点のプロジェクト参照集合には含まない。

構文は[Auriga公式リファレンス](https://github.com/auriga/auriga/blob/master/doc/script_ref.txt)を照合した。
Auriga本体での読込・実行確認は未実施。導入前の検証環境での確認が必要。
shopグループで回帰。2形式、呼出しの到達位置、基本価格、ID確認、配置不足、誤対応・未応答拒否、
終了通知を挟む経路、00C4なしafter_close_list、期限切れ、GUI生成・保存を検証した。

20261027-175743-38a7ccc0では、5一覧が会話13・14・16・24・25に対応した。
いずれもopenのみでショップへ遷移する観測で、本文ありcallshopの実例ではない。
ショップNPCのマップが未観測、商品IDのDB対応も未確認なので、実ログ由来の宣言は自動生成していない。
会話あり形式は合成データで検証し、出力例を.reference/shop-callshop-example.txtへ保存した。

close応答後の演出を経てshopへ移る場合は、先に生成したclose2を重複させない。
途中でmesを再受信して会話表示が再開した場合は、shop直前に再度close2を置く。
この表示状態は分岐ごとに保持し、別の選択肢へ引き継がない。
