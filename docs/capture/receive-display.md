# 受信パケットの整形表示

[資料一覧へ](../README.md) · [プロジェクトREADME](../../README.md)

## インスタンスMAPのwarp表示

Aurigaのdisplay.jsonはinstance_map_reference・instance_warp・instance_entry_warpで名前参照と表示を変更できる。
`@`を含むMAPへの移動は、直前のプレイヤーMAPもインスタンスならgetmdmapnameを使用する。
通常MAPからの入場・移動元不明の場合はmdenterの可能性を示すコメントとして出力する。
元のMAP名・座標は解析フィールドに保持する。3項目がない旧書式は従来の表示を維持し、rAthenaへ自動適用しない。
生成候補の同じ規則はconfig/auriga/dialogue.jsonのinstance_*書式で変更する。

Auriga表示を93 IDへ拡充した。NPC/MOBの初回観測・移動、所持品、Zeny差分と
GUI基本データの仕様は[基本データガイド](../observations/player-observations.md)を参照。
表示ルールの任意キーdecoderにactor/playerを指定すると、固定の意味デコーダーが
供給するフィールドをtemplate/variantsで使用できる。任意コードは実行しない。

## 使い方

1. 通常どおり PacketLength.txt と対象プロセスを指定してキャプチャする。
2. 表の「Decoded packet text」と中央の整形ログに解析結果が表示される。
3. 行を選択すると、下部で整形文・解析フィールド・元のHEXを確認できる。
4. 既定の `config/auriga/display.json` の `template` を編集して保存する。
5. 「設定 → 表示 → 再読込」を押すと、新しい書式で取得済み履歴も再表示する。
6. 主画面の「観測ログを保存…」で、現在のPacketIDフィルターと表示設定を反映した
   整形ログをUTF-8で保存する。原本のSQLiteにはrawバイトが保存される。

表示JSONのパスはBrowseで変更可能。初期パスは実行時の作業ディレクトリではなく
プロジェクト内を基準に解決する。再読込に失敗した場合は正常な前設定を維持し、
ステータスバーに理由を出す。初回の読込が失敗した場合も受信・HEX・保存は継続できる。
旧 `config/receive_display.json` は互換用として保持する。rAthena用は低優先度の
`config/rathena/display.json` に分離した。受信ログ表示はAurigaと同数のPacketIDを持ち、
フィールド定義は共有する。`getmdmapname` / `mdenter` などAuriga向けインスタンス書式は入れず、
未照合の会話ウィンドウ命令（messize等）は実行形ではなく確認用コメントにする。
`entity_metadata` は受信ログ表示ではfalseのまま。コード生成用の `dialogue.json` /
`entity_metadata.json` / `status_ids.json` 等は `config/rathena/` に分離し、エミュレータ切替で
切り替える（send_displayは共有）。復元の主目的と実装順は
[復元開発計画](../development/restoration-plan.md)を参照。

「設定 → 表示」の「表示未定義のパケットも観測ログに表示する」は、長さ定義は既知だが
表示定義のないパケットのログを表示・非表示にする。「観測時刻を表示する」は外部定義のtimestamp書式を付加する。
受信用プロファイルはSENDに適用しない。送信は独立したsend_display.jsonで整形し、
同じ一覧・整形ログ・HEX・SQLiteへ表示／保存する。Display JSONのRECV/SENDで
編集する方向を切り替えられる。

## 構造オーバーレイとフィールド索引タグ（#35）

未知PacketIDや長さ拡張されたパケット向けに、版付きJSONで長さと表示フィールドを
明示上書きできる。例: `config/packet_overlay.example.json`。
「設定 → 取得 → 構造オーバーレイ」でパスを指定し、観測開始時にPacketLengthへ、
表示の再読込時にdisplayへマージする。未指定時は従来どおり。失敗時は従来の
方向fail-closedを維持し、未知ID後の境界再同期やバイト飛ばしは行わない。

各フィールドに任意の `index` タグを付けられる（表示注釈のみ。ワイヤ値・SQLite raw・
集計キーは数値／生値のまま）。未設定は従来どおり。設定時はパケット詳細で
`値（注釈）` 形式（例: `1010（鉄）`）。一致なしは `未登録`／`未観測` を明示し埋めない。

| index | 解決元 |
|---|---|
| actor_id | WorldStore（同一取得・接続・MAP世代の名称） |
| item_id | client_names item_identified |
| quest_id | client_names quests |
| map_name | client_names maps |
| class_id | player_classes（職業クラス可否のみ） |
| skill_id | skill_names |
| status_icon | reference_names status_icon |
| visual_effect | reference_names visual_effect |

### 同一行の actor コメント

`// {actor_comment}` を使うテンプレートは、名称が取れた NPC について
`名称(actor_id), x, y` 形式へ展開する（WorldStore の同一接続・MAP世代）。
名称未取得時は従来どおり ActorID のみ。実行引数側の `{actor_id}` はそのまま数値／保護置換（`self`）を使う。

### showevent（0446）のログ抑制

NPC Entity に `showevent_flag`（既定 `-1`）と `showevent_kind` を保持する。
観測ログへ出すのは **flag/kind が変化したときだけ**。名称が取れた NPC は
`名称(actor_id), x, y` をコメントに付ける。`state=9999` は NPC 判定用ラベルで、
出現（spawn）が無い Actor は配置 Entity を作らず観測ログのみ（`showeventflag=9999 NPC判定`）。
解析・会話復元の `event_marker` 保持は従来どおり全件行う。

### update_status（00B0／00B1／0ACB）

HP/SP/重量など多発する `@update_status` 行は観測ログから抑制する。
Zeny（type 20）と Base/Job Exp（type 1/2）は表示を残す。PlayerStore の数値更新は継続する。

セッション開始時は適用後の長さを `PacketLength.used.txt` に残し、オーバーレイ利用時は
`PacketOverlay.used.json` と `session_start.overlay_sha256` も残す。

### パケット詳細での編集（#35 P1）

「パケット詳細」で行を選び「構造オーバーレイを編集…」を開く。
フィールド追加・offset/type/length・index（actor_id / item_id 等）・パケット長を編集し、
長さ確認（定義長と観測raw・フィールド被覆）のあとオーバーレイJSONへ保存する。
保存後は設定のオーバーレイパスを更新し、表示を再解析する。
既存のdisplay規則があれば初期値として読み、同一IDはオーバーレイ内で置換する。

### 同一ID差分と確定エクスポート（#35 P2）

同じPacketIDの行を2件選び「同一ID差分」でrawバイト差分を表示する。
オーバーレイまたはdisplayのフィールド範囲があれば差分箇所をフィールド名で注釈する。
長さが違っても境界再同期はせず、欠けた側は `--` と示す。

「オーバーレイ確定をエクスポート…」は設定中のオーバーレイから
`PacketLength.overlay-export.txt` と `display.overlay-export.json` を書き出す。
プロジェクト本体の PacketLength.txt / display.json は上書きしない。

## 文面を変える例

会話パケット00B4の既定値は `"template": "mes {text:q};"`。
これを `"template": "NPC {actor_id}: {text}"` にすると、日本語本文が
`NPC 42: こんにちは` の形式で表示される。Pythonを編集する必要はない。

- `{text}` は文字列をそのまま表示する。
- `{text:q}` は二重引用符を含む文字列にし、改行・引用符・バックスラッシュを
  エスケープする。スクリプト風表示にはこちらを使う。
- `{color:#08x}` は16進表示。対応する書式は空指定、q、d、x、X、#x、#06x、
  #08x、06X、04X、,d、+d。文字列への数値書式は読込時にエラーになる。
- 実際の改行を含むテンプレートはJSON内で `\n` を使用する。
- リテラルの波括弧は `{{` と `}}` にする。
- コード実行・式評価・属性アクセス・関数呼び出しはできない。

## JSON契約 version 1

トップレベルの必須項目はversion、fallback、error、timestamp、packets。
encodingは既定cp932。defaultsは接続ごとの状態の初期値。

各packetsエントリーはids（16進文字列の配列）、name、templateを持つ。
fieldsは任意。各フィールドはパケット先頭からのoffsetとtypeで指定する。
offset=0がPacketID、可変長のoffset=2が総パケット長であり、本文先頭からの
オフセットではない。

- 整数: u8/u16/u32/u64、i8/i16/i32/i64。すべてLittle Endian。
- string: length指定時は固定バイト数、未指定時は末尾まで。最初のNULまでを
  encodingで厳密に復号する。フィールドごとにencodingを上書きできる。
- bytes: 同じlength指定でHEX文字列を得る。
- 整数にはmask、scale、addを指定でき、`(value & mask) * scale + add` の順。
- min_lengthで当該バージョンの最小長を追加指定できる。
- variantsはwhen（値の一致条件）とtemplateの配列。条件がすべて一致した最初の
  書式を使う。一致しなければ通常のtemplateを使う。
- rememberはdefaultsに宣言したctx_変数名とフィールド名の対応。正常解析後に
  更新する。カットインとマップ名の保持に使い、接続ごとに分離する。
- 組込変数: packet_id、length、direction、source、connection、time、name、error。

不明なキー、重複JSONキー、重複表示ID、存在しないプレースホルダー、未対応型は
設定エラーになる。表示IDの重複をエラーにする規則は、PacketLength.txtの
「後方定義優先」とは独立している。

設定最大2MiB、テンプレート最大16384文字、1定義のフィールドと条件分岐は各256個。
状態を保持する接続は最大4096個で、それを超えると古い状態を破棄する。
画面上のパケット一覧ページ化（最大1000件）と観測本文の末尾5000行／約26万文字上限は既存
（[GUI作業空間](../guide/gui-workspace.md)）。
`events`／`display_results` は既定5万件超で DB 保存確認済みの先頭だけメモリ退避し、
根拠移動は SQLite 行読込（#77）。未保存パケットは退避しない。更なる計測・上限調整は O2。

## MARiAからの調査範囲と互換性

参照元: https://github.com/refis/MARiA/blob/master/maria.py
2026-10-26に取得したReadPacket実装を調査。参照用コピーは.reference/MARiAに置き、
アプリからimportしない。既存のキャプチャや再同期処理を取り込んでいない。
機能差分の正本は[開発計画・MARiAとの差分](../development/development-roadmap.md#mariaとの差分)
（2026-11-01再確認）。ここは受信表示プロファイル視点の要約。

初期プロファイルは66ルール・73IDを持ち、会話、メニュー、入力、カットイン、
クエスト、アナウンス、音楽・効果音、マップ移動、演出、HP、戦闘・スキル、
経験値、状態効果、ダイアログ位置などを表示する。ID一覧・フィールド位置の
正本はJSON。040Cなど、同梱長さ定義にはない別バージョンの表示定義も含む。
実際のキャプチャ可否・分割は常に対象バージョンのPacketLength.txtが決定する。
長さが合うことだけではフィールド互換性は証明できないため、実ゲームのバージョン
に合うデータでの確認は必要。

MARiAの全文字列・状態推論・pickle保存との完全互換移植ではない。観測・候補生成まで
進んだ領域と、意図的に移植しない領域を分ける。

対応済み／部分対応（表示・状態・候補。MARiA同等の自動推論ではない）:

- NPC/MOBの出現・移動一覧と接続／マップ世代分離（GUIエンティティ）
- 外部名称辞書（スキル・状態／効果シンボル・品名・MAP・クエスト等）とプロジェクト版照合
- 所持品・装備・鑑定状態の観測と会話中の授受候補（ランダムオプションの命令再現はしない）
- 通常ショップの繰り返し商品台帳と shop／callshop 候補
- barter（0x0B0E／実機0x0B56）の常コメント候補（`//- barter` / `// callbarter`。実行命令化はしない）
- キャラクター一覧・ログイン基本データの観測
- OnTouch／根拠付きの warp 候補（近傍同時発生だけでは原因確定しない）
- MOB個体別スキル間隔・cast review・性能比較（AI条件・設定湧きの自動復元はしない）
- 生ログのオフライン再解析・複数ログ・作業プロジェクト（pickle互換なし）
- display_only だった個別通知の観測保持・命令非生成（[未対応通知](../npc/unsupported-notifications.md)）

意図的ギャップ・未採用（詳細は[未対応通知](../npc/unsupported-notifications.md)）:

- BGMのNPC割当・musiceffect命令化
- キャッシュ shop。0x0B79／exchange は取得検証保留（#70。未採取のままレイアウトを広げない）
- setcell・hateffect 等の実行命令化（観測コメントのみの種別を含む）
- showevent は単独ではコメントのみ。setquest／delquest 直後の関連付け時のみ `OnQuestInfo:` へ実行命令化（[クエスト資源観測](../npc/dialogue-resource-observations.md)）
- 新規に見つかった表示定義のみ PacketID の構造化要否（勝手に命令化しない）
- EXE暗号化前取得、未知ID後の境界再同期
- stateiconimginfo の画像名辞書化（#69。取り込み不要）

対応しないIDもrawは保存し、表示未定義として残す。名前が不明な戦闘・演出は
推測した名前を埋めずactor IDを表示する。メニューは選択肢数によらずmenu形式に
統一する。操作キャラクターの名前・パーティ名・ギルド名が本文に含まれる場合は
`getstrcharinfo`（rAthenaは`strcharinfo`）へ置換し、本人ActorIDの注釈は`self`と表記する。
生の観測値・根拠JSONは保持したまま、観測ログとコード候補の表示／生成時だけ置換する。
パーティ／ギルドは観測済みのときだけ対象にし、未取得値は補完しない。

参照元の0972はtypeの位置と文字列開始位置が重なっているため、type=8、本文=9に
分離した。009Aの色プレフィックス判定と02C1の不自然なビットシフトは複製せず、
前者は本文を表示、後者はwire値を明示する。ゲームバージョンで異なる場合は
プロファイルのフィールド位置や文面を変更する。NULのない文字列末尾を落としたり、
不正なcp932バイトを黙って捨てたりしない。

表示解析の範囲外・文字コードエラーは当該行のdecode_errorにし、次の完全パケット
の表示を継続する。これはフレーマーの未知ID停止とは別であり、ストリームを
再同期したりPacketLength.txtを変更したりする動作ではない。

接続の表示識別子には初期SYN番号を含め、同じ4タプルの再接続で表示状態が混ざる
ことを防ぐ。キャプチャ再開始時にも状態を初期化し、履歴の再表示時も区切りを守る。
既存TCP接続への取得開始オプションを使った場合はSYNの代わりにASSUMEDと開始位置を
表示する。これは最初の受信本文をパケット境界と仮定したことを示し、検証済みの
境界を意味しない。未知IDで停止したら、取得を続けたままゲームを再接続する。

## 残課題（表示・負荷）

初期提案のうち、生ログ再解析・接続世代ごとの状態・通常ショップスキーマ・
エンティティ一覧のモデル化は実装済み。次に残る表示まわりの課題:

1. メモリ履歴退避は既定5万件超で、DB確認済み先頭のみ退避し根拠移動はDB読込（#77）。更なる計測・調整は O2。
2. SQLiteのスループット計測。保存は WAL＋1件commitを維持し、遅延バッチ化より先に採用済み（roadmap O1）。
3. キャッシュ shop の版別スキーマ。0x0B79／exchange は該当 NPC 確認後の実機ログでのみ再確認（#70）。
4. 新たな display_only 候補が出たときだけの構造化要否判断（勝手に命令化しない）。


## スキルユニット表示の辞書（2026-10-30）

標準Auriga/receive書式の09CAにdecoder=skill_unitを追加した。
unit_symbol/unit_name/unit_skill_ids/unit_known、unit_mapping_basis/unit_catalog_sha256を使用できる。
元のunit_id・actor_idに加え、unit_actor_idとsource_actor_idを表示する。
書式からこのdecoderを使わない場合は従来の数値フィールドのみの書式も利用できる。
辞書はDisplayProfile読込時に固定され、履歴保存・表示の途中では再読込しない。
詳細は[MOBスキルの説明](../mob/mob-skills.md)の設置スキルユニット名称を参照。


## 状態アイコン・視覚効果の参照シンボル（2026-10-30）

標準Auriga/receive書式で、状態0196/043F/0983と効果019B/01F3/0284/0B0Dに参照シンボルを併記する。
状態はstatus_icon（EFST_*）、効果はvisual_effect（EF_*）で、同じ数値でも別の名前空間を参照する。
元のeffect_id、ActorID、値・時間・フラグは変更しない。sc_start/sc_endの命令IDや引数変換は既存処理のまま。

config/reference_names.jsonに状態アイコン1,325種・視覚効果121種のID対応を保持する。
既知の同値重複3件は記録し、異なる定義値の競合は生成時に拒否する。
EFSTファイル末尾の既知のunknown-stateガードは完全一致する形だけを除外し、Lua関数を実行しない。
その他の実行文・関数・不正な定数は取り込まない。

書式のdecoder=visual_effect_name/status_icon_nameでreference_symbols/reference_description/
reference_namespace/reference_known/reference_catalog_sha256を利用できる。辞書はDisplayProfile読込時に固定され、
表示中に原Luaや辞書を1件ずつ再読込しない。未登録IDは元の数値と未登録／説明未登録表示を維持する。
受信長は各対応形式に厳密一致する必要があり、未対応の構造を類推して読むことはない。
旧プロファイルでdecoderを指定しなければ従来の数値表示を利用できる。

### 日本語説明と版・出典（#24）

`catalogs` は ID→シンボルのみ。任意の `descriptions` は名前空間ごとの ID→説明文字列で、
シンボル表とは分離する。未設定・未登録は `説明未登録`。改行・NUL・空文字・未知IDへの説明は拒否する。
`description_sources` に取り込み元パス・SHA-256・field（現状 `descript_title`）・encoding を残す。
提供 `stateiconinfo.lua` から状態アイコン日本語タイトル792件を取り込み済み。
stateiconimginfo の画像名は辞書化しない（#69）。
説明の有無で effect_id・SC変換・観測集計・script_id_conversion は変えない。
視覚エフェクトの日本語は確認済み出典が無い間は空のままとする。

開発用の再生成:

```powershell
python -m tools.build_reference_names
python -m tools.build_reference_names --status-info ".reference/data/luafiles514/lua files/stateicon/stateiconinfo.lua"
```

既定入力は提供されたskilleffectinfo/effectid.luaとstateicon/efstids.lua。
--effects/--status/--status-info/--outputで指定可能。入力・.referenceへの上書きを拒否し、出典SHA-256を記録する。
`--status-info` は StateIconList／StateIconInfoList の `descriptive` 文字列、または `descript` 配列の先頭日本語タイトルだけを読む（`COLOR_*` 色定数の裸識別子は無視、関数・実行文は拒否）。
インデックス代入形式 `StateIconList[EFST_IDs.…]=…` も取り込み、空の `StateIconList={}` 初期化はスキップする。
EFST→SCの新規対応追加は別作業。プロジェクト再解析で同じ表示を得るには、この辞書の版も維持する。

対象8テストを確認。既存2ログでは合計3,213通知・表示エラー0。
状態2,566件中2,255件、視覚効果647件中51件でシンボルを解決し、残るIDは未登録で保持した。
全効果の名称が揃った結果ではない。logs/reference-name-display-review.jsonに出典ハッシュと結果を保存した。


### MARiAによる不足状態名の補完（2026-10-30 / v0.0.5保存後）

提供LuaにないEFST7件（821/822/823/824/982/993/994）をMARiA const.EFSTから表示用に補完。
重複1,034件はID・シンボル一致、競合0件。現行は状態1,325種・視覚効果121種。
Luaを優先し、不足IDのみ追加する。重複IDまたは同名シンボルのID不一致は生成を拒否する。
MARiAはPython ASTの定数辞書だけを読み、コードを実行しない。補完元はカタログのsourcesと
supplemental_statuses（basis=maria_only）に残す。現在クライアントの仕様確認済みとは同一視しない。
再生成の--mariaは既定.reference/MARiA/const.py。従来の--effects/--status/--outputも使用できる。
既存2ログでは状態名の解決が105通知増え、2,566通知中2,360件を解決、206件は未登録。
視覚効果は647件中51件を維持。全3,213通知の表示エラー0、元ログと定義ハッシュは不変。
関連11項目が通過。logs/reference-name-maria-supplement-review.jsonに補完元と結果を保存した。
辞書更新により過去プロジェクトのハッシュが異なる場合は、保存版の辞書を使用するか、生ログから新規に開く。
