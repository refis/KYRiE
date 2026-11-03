# 会話の観測経路とAurigaコード候補

[資料一覧へ](../README.md) · [プロジェクトREADME](../../README.md)

## イベントアイコン（0446）

0x0446は14バイト固定。ActorID・座標・state・kindを `event_marker` として構造化保持する。
単独の showevent は出さない（手動タイマーもコメント採用のみ）。
ただし会話中（close2判定中含む）の setquest／delquest の後に観測した場合は関連付けし、
該当NPCの `OnQuestInfo:` へ `showevent` と `// {quest_id}: {x}, {y}` を追加する。
（[タイマー候補](event-timer-candidates.md)）。対照表は[未対応通知](unsupported-notifications.md)。

## 色付きユニット発言（02C1）

0x02C1は PacketLength `-1`。表示定義どおり actor_id@4・color@8・text@12 を
`colored_speech` として構造化保持する。008D `unittalk` とは別観測で、実行命令は出さない
（コメントのみ。詳細は[未対応通知](unsupported-notifications.md)）。
実機例: 20261102-173136-edcd6b68（MOB／会話外・color `0x000000FF`）。

## 帽子エフェクト（0A3B）

0x0A3Bは PacketLength `-1` だが、表示定義どおり全長11バイト（length@2=11、actor_id@4、
enabled@8、effect_id@9）だけを `hat_effect` として構造化保持する。
実行の hateffect 命令は出さない。手動タイマーではコメント採用のみ。
未知長・追加フィールドは推測せず拒否する。対照表は[未対応通知](unsupported-notifications.md)。

## 値付きエフェクト

0x0284は14バイト固定で、ActorID（offset 2）、エフェクトID（offset 6）、追加値（offset 10）を保持する。
同梱MARiAとローカルAuriga clif_misceffect_valueの送信構造を照合した。
effect_valueとして通常付与・解除から区別し、追加値の異なる通知を同一演出へまとめない。
会話・入力待ち・別の既知NPCへの外部候補を保持し、値・ID・有無・順序の相違を反復照合する。

ローカルAurigaにはmisceffect_valueスクリプト命令の登録が確認できないため、生成は観測コメントまでとする。
追加値を捨ててmisceffectへ置き換えない。観測窓の比較には残す。手動タイマーではコメント採用のみで、
実行命令へ落とさず黙って省略もしない。書式はdialogue.jsonのeffect_value／external_effect_valueと
event_timers.jsonのeffect_value。
全370テスト通過。合成パケット・GUIで検証し、実クライアント／Aurigaでの実行確認は未実施。
既存ログ20261027-193248-fcdc039cで会話外の1件（effect_id=657、value=90406）も保持確認。
再解析は会話6件・統合2群・会話解析問題0件。元ログは変更せず別レポートへ保存した。

## エフェクト解除

0x0B0Dは10バイト固定、ActorIDがoffset 2、エフェクトIDがoffset 6の解除通知として扱う。
同梱MARiAとAuriga clif.cの送信処理・delmisceffect命令を照合した。
effect（付与）とeffect_remove（解除）を分離し、同じIDでも同一演出へまとめない。
会話NPC自身の解除はdelmisceffect候補、入力待ちは並行観測、別の既知NPCへの解除は
外部呼出しの未確定候補としてコメントで保持する。個体世代・MAP・取得範囲の既存検証を適用する。
解除の有無・ID・順序・付与との違いを演出照合へ含める。タイマー比較にも保持し、
採用試行と全時刻を明示確認した場合のみdelmisceffectを生成する。書式はdialogue.json／event_timers.json。
全367テスト通過。合成パケット・GUIで検証し、実クライアント／Auriga本体での実行確認は未実施。

## 会話中の別NPCへの演出（外部呼出し候補）

「会話・コード → 外部演出候補」で、会話ごとの受信対象・演出・Packet番号を確認できる。
行を選び「演出の根拠パケット」「直前会話の根拠パケット」で受信位置へ移動する。
統合チェックONでは統合元の全候補を列挙し、同経路の演出不一致を注意として表示する。
不一致件数には外部以外の演出も含む。会話の切替で古い選択・詳細・移動ボタンを消去する。
このタブで起因を確定したり、候補を実行命令へ採用したりはしない。

会話NPCは現在の視界観測区間と一致する場合に限り関連付ける。消滅後に会話との継続が確認できない通知は
古い会話へ追加せず、会話外観測として保持する。同じActorIDの再観測はIDの再発行と断定せず、別の観測区間として保存する。
conversation_entity_keyとtarget_entity_keyに取得・接続・MAP世代・ActorID・個体世代を記録し、
生成・統合時にも会話／対象スナップショットとの一致を検証する。確認一覧にも受信対象の個体世代を表示する。

同じ取得・通信フロー・MAP世代で、会話中NPCとは別の既知NPCへ届いたemotion・effect・sound・
showmessage・unittalkは、会話を切り替えずexternal_presentationsへ保持する。
actor_idとnpcは受信対象、conversation_actor_idはその時点の会話NPCであり、呼出し元を証明する値ではない。
cause_confirmed=falseとし、他ユーザー操作の混入可能性を残す。
対象未解決・MOB・別フロー・別MAP世代は、このNPC外部呼出し候補へ自動で含めない。

0x008Dのunittalkは総パケット長・ActorID・CP932本文を検証する。会話NPC自身の通知は通常の演出と同様に扱い、
別NPCの通知は外部候補とする。既存の0x08B3はshowmessageの候補として区別する。

Aurigaと同梱MARiAを照合し、emotion/misceffect/showmessageのNPC名指定、unittalkのunit_id指定を候補へ反映する。
既定の出力はコメント。GUIの対象別通知で emotion／effect／effect_remove／overhead／unittalk を
行ごとに `adoption_confirmed` したときだけ実行命令候補へ切り替える（cause_confirmedは常にfalse）。
unittalkの採用時は実行時ActorIDを固定せず getnpcid(0,NPC名) の候補を前置コメント欄へ出す。
sound／effect_value／event_marker は採用不可。インスタンスMAPでは名前参照にgetmdnpcnameを使う。
入力応答の順序・会話終了判定は変更しない。書式はconfig/auriga/dialogue.jsonのexternal_*／adopted_external_*。

## アナウンスの観測（2026-10-28追加）

0x009Aのbroadcastと0x01C3/0x040Cの装飾付きannounceを、本文・装飾値・根拠パケット付きで
会話外演出の観測JSONへ保持する。総パケット長、最小レイアウト、末尾NUL、CP932を検証する。
009Aの既知接頭辞blue/ssss/toolは本文から分離してbroadcast_prefixに保持する。
装飾付き通知はcolorとfont_type/font_size/font_align/font_yをそのまま保持する。

ActorIDを含まないため、パケット自身の対象はtarget_observed=falseとする。
同一取得・同一フローの会話中に受信した場合は、会話の関連観測として本文へ含める。
入力待ち中は並行演出へ分離し、応答リンクと実行順を変更しない。単独受信は対象未特定で保持する。
本文・装飾値・有無の違いを既存の演出照合で検出し、本文経路の矛盾はインデント付き{}で併記する。
入力待ち中の相違は並行演出の比較根拠に残す。announceだけでclose2へ変更しない。
タイマー比較では、選択した同一取得・同一フローの観測窓に含まれるannounceを比較する。
配信範囲やNPC起因は受信パケットだけでは確定しない。表示は既存の外部display.jsonを使用する。
既存009Aの整形表示は接頭辞による書式切替に未対応で、意味解析の保持とは別扱い。

同梱MARiAのannounce読取とローカルAuriga clif_GMmessage/clif_announceの送信レイアウトを照合。
追加ログ20261028-012526-0abe69d9には01C3が31件あり、別レポート
session-analysis-announcement-associated-review.jsonで検証した。31件中、会話本文1件・入力待ち1件を関連付けた。
会話90件・統合34群・会話解析問題0件。040Cと接頭辞の分岐は合成データで検証。全341テスト通過。
元イベントスクリプトから処理やタイマー値を補完していない。

「会話・コード」で会話を選び、コード候補・根拠JSONを確認する。
コード保存は選択中の会話、会話JSON保存は保持している全会話が対象。
「根拠パケット」は「時間経過」の選択行へ移動する。未選択なら会話の最初へ移動する。
表示プロファイルを変更しても会話の解析結果は変わらない。

## 外部ファイル

`config/auriga/dialogue.json` が生成命令・コメントのテンプレート。
編集後「生成形式を再読込」で反映する。`{text}` 等の指定済みフィールドだけを
利用できる。属性参照・式・変換指定は認めない。文字列は生成器で引用・エスケープする。
単一パケット表示の `config/auriga/display.json` とは役割を分ける。

生成物はNPC本体へ挿入する**観測経路の候補**。配置宣言や元の条件式は生成しない。
同じ接続・取得世代で確認できたNPCの名前・座標・外見等は会話JSONのnpcに保存する。
不明な名前・マップを補完しない。

## 対応と境界

- SEND: 0090開始、00B8選択、00B9次へ、0143数値入力、01D5文字入力、0146終了。
- RECV: 00B4/0972台詞、00B5/0973次へ、00B6終了、08D6消去、00B7メニュー、
  0142数値入力、01D4文字入力、01B3カットイン。
- 0972はtypeがoffset8、文字列がoffset9。文字列はcp932を厳密に解読する。
- 各ステップは時刻・会話開始との差・送受信・取得元・接続・パケット番号を持つ。
- TCPの両方向に共通のflow_idを付け、各方向のSYNが変われば接続世代を更新する。
  未指定の旧PacketEventではconnectionでのみ関連付ける。SQLiteの既存列は変更しない。
- キャプチャ世代・接続・NPCを区別する。マップ移動、別NPCの会話、再取得は
  それまでの会話を完成扱いにしない。途中取得の会話には開始未観測を記録する。
- 最新の待機要求に対する応答だけを関連付ける。別NPCの応答や範囲外の選択は
  分岐の根拠にしない。末尾の空項目は連続する場合も除去し、途中の空項目は未対応として停止する。
- 選択済みの分岐だけに続きの台詞を置く。未選択の分岐はコメントとend。
  応答未観測、応答との間に別イベントがある場合はコード化をそこで停止する。
- 入力応答後も{}ブロックで続きを出力し、入力数・文字をコメントに残す。
  起因・元変数・条件の判定は生成対象外。`gpa`入力変数は生成器が付けた仮名。
  close/close2はcloseボタンへの送信応答と後続受信の順序から選択する。
  カットインの表示状態だけではclose2にしない。詳細は[終了応答の扱い](dialogue-closing.md)。
- セッションは最大2000、全ステップ100000、1会話2048。上限では追加を停止し、
  問題をJSONへ記録する。未知ID後の再同期や欠損バイト補完は行わない。

複数選択肢は`set '@menu,select("…","…");`と`switch ('@menu)`、単一または全応答同一ならラベルなしmenuを使用する。
矛盾する観測は開始直後を含め、条件を付けないインデント付き{}ブロックで併記する。
Aurigaのmenu/switch/cutin/close系構文は
[公式スクリプトリファレンス](https://github.com/auriga/auriga/blob/master/doc/script_ref.txt)
を参照。Auriga本体での実行確認は未実施。

## 保存ログから再構築

```powershell
python -m tools.analyze_dialogues logs/SESSION/capture.jsonl --definitions client/PacketLength.extracted.txt --output logs/SESSION/dialogues.json
python -m tools.analyze_dialogues logs/SESSION/capture.jsonl --definitions client/PacketLength.extracted.txt --output logs/SESSION/dialogues-rathena.json --emulator rathena
```

再解析用本文を保存したログが必要。入力ログは変更しない。
出力には会話JSON、Auriga本文候補、TCP再生の診断を含む。
会話が正常でも、別接続のTCP解析エラーがなくなることを意味しない。

2026-10-27検証: 20261027-064450-e05d0fb7は1会話18ステップ、次へ2回、選択2回、
マップ移動で終了。20261026-223425-131e9688は1会話15ステップ、次へ1回、選択1回、
終了応答まで観測。両ログの会話解読・関連付け問題は0件。

会話の入力待ち／入力なし区間と反復比較を追加した。
操作と解釈は[時間経過ガイド](dialogue-timing.md)を参照。
同じNPCの観測経路をまとめる候補生成を追加した。
使い方・識別範囲・書式は[分岐統合ガイド](dialogue-merging.md)を参照。
起因・変数・隠れた条件式の判定は生成対象外。
close応答後のワープ命令候補は[終了応答の扱い](dialogue-closing.md)を参照。
rAthena会話コード生成は今後の対象。

### 外見変更通知01B0（2026-10-28）

11bytesのActorID（offset 2/u32）、type（offset 6/u8）、外見値（offset 7/u32）を保持する。
MARiAの01B0処理と既存表示定義を照合。受信時のNPC・接続・取得世代で関連付ける。
会話中は時系列ステップ、入力待ち中は本文から分離した並行演出、会話外は演出観測一覧へ保持する。
同じ会話経路で外見変更の有無・値が異なれば、他演出と同様に反復矛盾の確認対象とする。
会話本文では対象NPC名が分かる場合に `setnpcdisplay "名前",class;` を出す。
条件式は生成しない。手動タイマー候補でも同一対象・会話外採用時は setnpcdisplay を出す
（[タイマー候補](event-timer-candidates.md)）。kind 値は根拠として保持する。
ignorepacketのNPC演出リストで非表示にできるが、根拠・解析は保持する。

### プログレスバー通知（2026-10-28）

02F0は10bytesで色（offset 2/u32）と秒数（offset 6/u32）を保持する。
ActorIDがないため、会話中でもNPCへ割り当てず、対象未特定の演出一覧へ保存する。
対象付き09D1は14bytesでActorID（offset 2/u32）、色（offset 6/u32）、秒数（offset 10/u32）。
同じNPCの会話中なら時系列ステップ、入力待ちなら並行演出、別NPCや会話外なら演出一覧へ保持する。
入力応答リンクは変更せず、対象付き通知の反復差は他演出と同様に比較する。

02F0のレイアウトはMARiAとローカルAurigaのclif_progressbarを照合した。
09D1は既存display.jsonのレイアウトに対応する。保存済み実ログ3件には両通知がなく、
検証は合成パケット・GUI・既存ログ回帰まで。09D1の現クライアント実動作は追加ログで確認する。
通知の秒数は観測フィールドであり、サーバー待機・イベントタイマー設定を確定しない。
会話コード生成は外部テンプレートprogressbarによる観測コメントのみとし、
progressbar/sleep/OnTimer命令は生成しない。手動タイマー命令化も未対応。
受信一覧の既存MARiA形式表示と、会話コード生成の対応範囲は異なる。

### BGM通知（2026-10-28）

07FEは26bytesで、offset 2から固定24bytesのCP932曲名を保持する。
0B8Cは可変長で、offset 2/u16がIDとLengthを含む総長、offset 4/u8が通知種別、
offset 5以降がCP932曲名。総長不一致・短いパケット・不正な文字列は問題として記録する。
07FEに通知種別は存在しないためmode=nullとし、0と同一視しない。
空の曲名や0B8Cの未知の種別値も観測値として保持し、意味を推測しない。

MARiAの07FE/0B8C処理と既存display.jsonを照合し、07FEはローカルAurigaの
clif_musiceffectとも照合した。どちらもNPCのActorIDを持たないため、
会話中・close応答待ちでもNPCへ割り当てず、対象未特定の演出一覧と根拠JSONへ保持する。
入力応答・会話分岐・close2判定を変更せず、会話コードへmusiceffectを追加しない。
NPC演出の非表示リストには連動せず、非表示にする場合はPacketIDを指定する。
手動NPCタイマー候補の基準点・命令生成にも採用しない。

合成パケットとGUIで、固定長・可変長、通知種別、文字列、不正構造、
入力待ち・終了待ちの分離と非表示後の根拠保持を検証した。
既存ログ3件にBGM通知がないため、現クライアントでの実動作確認は未完了。

### マップマーカー0144（2026-10-28）

23bytesで、実行元ID（offset 2/u32）、種別（6/u32）、X（10/u32）、Y（14/u32）、
マーカーID（18/u8）、色（19/u32）を保持する。MARiA・既存表示定義と、ローカルAurigaの
buildin_viewpoint → clif_viewpointを照合し、Aurigaでは実行元NPCのst->oidがID欄へ渡ることを確認した。
受信一覧のactor_idはこの実行元IDであり、マーカー位置にいる個体のIDと推定しない。

会話中の同一NPCなら時系列ステップ、入力待ちなら並行演出、別NPC・会話外なら演出一覧へ保持する。
同経路の反復差は演出不一致として比較する。種別1（表示）・2（削除）、XYが0〜1023、
マーカーIDが0〜255の通知は外部テンプレートviewpointで命令候補を出す。
それ以外はviewpoint_observationによるコメントへ残し、元の受信値を失わない。
根拠では32bit色を保持し、出力はMARiA同様に下位24bitを0xRRGGBBとして用いる。
起因・条件・マーカー維持時間は生成しない。手動タイマーへの採用も未対応。

NPC別ignorepacketの対象だが、非表示でも根拠とコード生成は保持する。
既存ログ3件に0144はなく、合成パケットとGUIによる検証まで。現クライアント・Auriga実行は未確認。

### 頭上メッセージ08B3（2026-10-28）

可変長でoffset 2/u16が総長（ID・Lengthを含む）、offset 4/u32が表示対象ActorID、
offset 8以降がCP932文字列。最小9bytesと総長一致・文字コードを検証する。
MARiAのshowscript処理と、ローカルAurigaのclif_showscript・buildin_showmessageを照合した。

同じNPCとの会話中はmesと区別したoverheadステップとして保持し、
外部テンプレートoverheadからshowmessageの候補を出す。対象名は省略し実行中のNPCを対象とする。
引用符・改行は他の会話文字列と同様にエスケープする。
プレイヤーや別個体の通知、入力待ち・close応答前の演出を本文へ混ぜない。
同経路で文面や有無が異なれば反復比較で演出不一致として確認できる。
NPC別ignorepacketの対象だが、非表示でも根拠は保持する。
手動タイマーへの命令採用、元の起因・表示条件の復元は未対応。

通常の演出と異なりActorIDはoffset 4にあるため、対象位置を共通定義で使用する。
合成パケットで入力応答の保持・別個体分離・不正構造・close応答後の継続を検証した。
既存ログ3件に08B3はなく、現クライアントとAuriga本体での動作確認は未完了。

### 末尾に連続する空選択肢（2026-10-28）

20261028-012526-0abe69d9に、末尾に5個または8個のコロンが続く00B7を確認した。
5通知すべてで後続00B8の対象NPCが一致し、非空の先頭4項目または3項目内の番号へ応答していた。
末尾の空項目だけを除外し、先行する項目の番号は変えない。途中や先頭の空項目、
全項目が空のメニューは従来どおり拒否する。除外した末尾項目への応答も有効扱いにしない。
原文はsteps[].fields.textと元パケットへ保持し、推測した選択肢を補わない。

修正後のsession-analysis-menu-review.jsonは93会話、会話解析問題1件、統合34グループ、
生成エラー0件。修正前のsession-analysis.jsonは比較用に保持する。
参考のnpc_memorial_horroroftoy.scから処理・タイマー値・条件を転用していない。
観測済み配置の宣言を加えた[編集用NPCファイル](npc-file-export.md)は生成できる。
[会話中の所持品・Zeny・マップ遷移](dialogue-resource-observations.md)も、根拠付き観測コメントとして保存する。
経過時間をsleep/OnTimerに変換していない。MOB集計は専用のMOB画面へ分離した。

## 会話中のNPC演出

MARiAのレイアウトに基づき、RECV `0x00C0`（7バイト）のエモーションと
`0x01D3`（35バイト）の効果音を、会話本文候補とタイムラインへ追加する。
同じ取得世代・接続フローで会話中のNPC IDと対象IDが一致し、入力待ちではない場合に限る。
通知だけから新しい会話を作らず、他のNPC・MOB・プレイヤーの演出は関連付けない。
会話終了後・マップ切替後の通知も本文へ追加しない。

`config/auriga/dialogue.json` の `emotion` / `sound` で出力書式を変更できる。
旧プロファイルには同梱の既定値を補う。文字列は引用・エスケープして生成する。
効果音は24バイトのcp932名、モード0/1/2、32bit間隔を保持する。
終端NULのない24バイト名も扱い、未対応モード・不正文字列・長さ不一致は解析問題として停止する。
根拠には元パケット番号・時刻・接続・値を保持し、統合時も演出の違いを別観測として残す。

Aurigaの `emotion <n>`（実行NPCが対象）、
`soundeffect <name>,<type>[,<interval>]` は
[公式リファレンス](https://github.com/auriga/auriga/blob/master/doc/script_ref.txt)で照合した。
音の繰返し間隔は通知された引数であり、サーバーイベントのOnTimerや待機時間ではない。
対象が一致することは会話が演出の原因であることの証明ではなく、編集用候補として扱う。

入力待ち中の並行演出は、入力後へ移動すると順序を変えてしまうため本文候補へ挿入しない。
別の観測列へ保持し、時間経過表と「並行・会話外演出」に表示する。
入力待ち中の反復照合も行う。詳細は[演出照合ガイド](dialogue-merging.md#入力待ち中の並行演出)を参照。
会話外の演出も記録するが、基準操作が不明なため反復比較は未対応。
不明対象の通知や文字列を診断メッセージへ流さない。

合成データで対象分離・入力待ち除外・不正データ・旧書式互換・単一／統合生成・GUI保存を確認。
全206テスト通過。既存2ログには今回取り込める会話中演出はなく、生成コードは従来と一致した。
実ゲームでの今回の演出取り込み、およびAuriga本体での実行確認は未実施。

## 会話中のアクションと状態異常ID

通常の0x02F0通知は`progressbar 秒数,色;`を会話本文へ生成する。
0x09D1のNPC対象付きバーは、参照したAurigaに対象指定命令がないため引き続き観測コメントとする。
NPC用通知をプレイヤー用待機命令へ置き換えない。

0x0229のhide／cloakビット差分はhideonnpc、hideoffnpc、cloakonnpc、cloakoffnpcを生成する。
会話相手自身は引数を省略し、他のNPCは観測したNPC名を指定する。unittalkも会話相手自身は
指定なし、他のNPCは`unittalk getnpcid(0,NPC名),文字列;`とする。
他NPCは同一capture・flow・MAP世代の現在の個体であることを確認する。
インスタンス名は完全な接尾辞だけを除去し、命令のNPC参照ではgetmdnpcnameを使用する。

会話内の追加アクションはConversation.actionsに受信Packetの根拠とともに保存する。
プログレスバー、表示状態、状態異常を入力応答のstepsへ挿入しないため、next/input等の返信対応は維持される。
本文へは受信順で取り込み、同じアンカーのクエスト命令等との順序も維持する。
入力待ち中に受信したものは実際の応答後に仮配置し、その旨をコメントに残す。
未応答の場合は応答を捏造せず、元の観測をJSONとコードの観測コメントへ保持する。
会話中に他ユーザーの操作が混入し得ることは変わらず、起因確定とは扱わない。
反復時の値・対象・有無の相違は統合時の比較対象とする。

状態異常は0x043F／0x0983のうち、会話中のプレイヤー本人への通知を対象とする。
別プレイヤーの状態を本人へ転用しない。生のtickは保持するが意味比較のキーから外す。
変換表はconfig/auriga/status_ids.jsonとconfig/rathena/status_ids.jsonに分離した。
参照版のAuriga StatusIconChangeTableとstatus.hから、クライアントSI→スクリプトSCの
一意な643対応（うち非同一数値570件）を登録し、曖昧な3アイコンは別管理する。
元ソースのSHA256と、解析に使った変換表のSHA256も記録する。

ID対応が分かっても、受信のvalue1等がスクリプト引数と一致するとは限らない。
argument_policy=reviewを基本とし、参照実装でicon_val1=val1を確認した
SC_MONSTER_TRANSFORM・SC_ACTIVE_MONSTER_TRANSFORM・SC_HAT_EFFECTだけをval1_onlyとした。
そのうえでvalue2/value3が0、通常の時間値を持つ場合に`sc_start 変換後ID,時間,value1;`を生成する。
変換済みの終了通知は`sc_end 変換後ID;`とする。特殊時間値9999、未対応引数・ID、
多義的なアイコンは確認用コメントへ残す。未観測のレベル・val4・起因条件は補わない。
rAthena表は本家 master（commit d4b8e7b8）の EFST→SC 一意対応を一回照合した静止表で、
Auriga番号は流用しない。曖昧アイコンはambiguousへ分離。argument_policyはreviewを基本とし、
status.yml Flags.SendVal1が確認できた SC_MONSTER_TRANSFORM / SC_ACTIVE_MONSTER_TRANSFORM のみ
val1_only。GUIのエミュレータ切替で生成プロファイルごと切り替える（sendは共有）。
Icon 12（EFST_INC_AGI）と50（EFST_NOEQUIPWEAPON）は観測一意ではなくユーザー採用方針で
SC_INCREASEAGI / SC_STRIPWEAPON を通常変換へ入れ、除外候補はexcluded_candidatesに残す。
残る曖昧6件（112/149/324/438/737/1316）は根拠なく一意化しない。
表示側0196 flag=0の`sc_end`も変換後SCのみを使い、未解決は確認用コメントにする。
解析CLIは`--emulator auriga|rathena`（既定auriga）で同じ生成プロファイルを選べる
（`analyze_session` / `analyze_dialogues` 等）。上流の継続追従は別対応。

生成書式はconfig/auriga/dialogue.jsonのprogress_action、hideonnpc等、unittalk_target、
status_start/status_end/status_review等で変更できる。GUIのタイムラインから元Packetへ移動できる。
指定ログ20261028-012526-0abe69d9では、progress5・表示状態変更6・状態異常4件を追加保持し、
状態異常4件のコード化を確認した。Auriga実環境での実行確認は未実施。
