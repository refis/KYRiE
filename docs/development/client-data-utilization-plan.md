# クライアント参照データの活用計画

[資料一覧](../README.md) · [開発計画](development-roadmap.md)

調査日: 2026-10-30。対象は利用者提供の `.reference/data`。
初回調査後、利用者指定に従い名称差122件をLua優先で反映し、続いて限定静的インポータを実装した。
新規588件を追加済みで、現行辞書は1,913件。元の参照データは変更していない。
全ファイルの相対パス・サイズ・SHA-256と予備照合は
`logs/client-data-reference-inventory.json` に保存した。

## ローカル原資料の利用許可（2026-11-02）

辞書・カタログ拡充が必要なときは、利用者マシン上の次を**読取専用の根拠**として用いてよい。

- `C:\project\KYRiE\.reference`（および作業コピーの `.reference/`）
- `C:\project\KYRiE\client`（および作業コピーの `client/`）

制約（既存方針と同じ）:

- 原資料そのもの（EXE／DLL／Lua／LUB／抽出バイナリ／私有ログ等）を Git・ソースZIP・PR へ持ち出さない。
  `.gitignore` の `.reference/` と `client/*` 除外を維持する。
- 成果物は `config/*.json` 等の生成辞書と、SHA-256／出典パスを記した docs・レポートのみ。
- Lua／Python／EXE は実行せず、限定静的パーサだけ使う。未確認 ID の発明・EFST→SC の新規変換・サーバー条件の推定はしない。
- 原資料ディレクトリへの書込み・上書き出力を拒否する（既存インポータ契約）。

エージェント環境に `.reference/data` が無い場合は拡充を保留し、手元に原資料がある実行での再生成を待つ。

## 1. 調査結果

全3,109ファイル、174,068,656 byte。Lua 1,534、LUB 1,534、TXT 38、SCP 1、EXE 1、BAT 1。
直下は40ファイル（TXT 36件等）。`luafiles514` は3,063件、`test` は6件。
`.lub` のLuaバイナリヘッダーを確認できたのは1,517件。拡張子だけで形式を決めない。
特に直下のiteminfo.luaとiteminfo.lubは同じテキスト内容であり、二重に取り込まない。

`test/decompile_errors.txt` にeffecttool/1@jitter.lubのbad header失敗記録がある。
Lua 10ファイルにDECOMPILER ERRORの印があり、印のないファイルも完全な逆変換とは保証されない。
関数ファイルには崩れた構造もあるため、Luaや同梱EXE/BATを実行せず、必要な定数・リテラルを読む。
複数位置にあるdatainfo/effecttoolの同名資料は、相対パスと内容ハッシュを区別して優先元を指定する。

### スキル名の予備照合

- 調査開始時のconfig/skill_names.json: 1,325件。更新後は1,913件。3件のみという旧記載は誤り。
- skillinfoz/skillid.lua: 完全な限定テーブル解析で1,977シンボル、数値IDは1,976種類。
- skillinfoz/skillinfolist.lua: 名称を持つ1,751レコードをIDへ照合した。
- 更新前の追加候補588件・名称差122件を反映済み。Luaにない既存名162件を保持。
- 別名シンボルSCRIPT_000とITEM_SAVAGE_STEAKが同じID 11000を共有する。

初回の大文字限定による予備抽出は1,750名称・既存のみ163件だった。
正式な限定解析でAll_EVENT_20TH_ANNIVERSARYも認識し、1,751名称・既存のみ162件へ訂正した。
初回調査JSONは予備結果のまま保管し、正式インポートの結果は別レポートへ記録する。
現行の「ウインドウォーク」→提供資料の「ウィンドウォーク」等の表記差、傭兵等の区別がある。
Lua未収録の162件を欠落として削除せず、MOB専用スキル等の既存情報を保持する。

## 2. 優先して使うデータ

### A. skillinfoz: スキル名称・補助説明（最優先）

skillid.luaのSKIDとskillinfolist.luaのSkillNameを結合する。
数値ID・シンボル・日本語名を別項目で管理し、MOB使用スキル、詠唱、観測ログ、
mon_skill_dbの「モンスター名＠スキル名」へ共通の名前解決を適用する。
利用者確定規則: 有効なLua名称と既存名が異なる場合はLua名称を採用する。
既存名との差分は記録し、名称差ごとの再承認は求めない。Luaにない既存名は保持する。
空値・解析不良・未解決IDは上書き根拠にしない。Lua内の同一ID競合は単なる既存名との差とは分けて報告する。

skilldescript.luaは詳細画面の参考説明に利用できる。
skillinfolistのMaxLv/SpAmount/AttackRange等、skilldelaylistの固定・変動詠唱やディレイは、
クライアント設定として別欄で参照する。観測レベルやMOBのAI・使用確率・実際の間隔を上書きしない。
skilltreeview.lua/jobinheritlist.luaは職業スキルの整理用で低優先度。
skillinfo_f.luaは参照処理の読み取りに限り、その関数を実行・移植しない。

### B. スキルユニット名称: 独立したID対応が必要

スキルユニット出現表示は、数値にシンボル・参照スキル名を併記する方式へ更新済み。
skillinfozはスキル名を得られるが、設置ユニットのunit_idとの直接対応表は今回の調査では確認できない。
スキルID、設置ユニット種別ID、実行時ActorIDを混同しない。
例: セイフティウォールはSKID 12に対し、MARiA UNITID/Auriga UNT_SAFETYWALLは126（0x7E）。

まずローカルMARiA const.UNITIDと参照Auriga skill.h/skill_get_unit_idの対応を、出典・版付きで整理する。
ユニット種別→シンボルを基礎にし、スキルとの対応が確認できたものだけ日本語名を付ける。
待機／発動形態、共通トラップ、一対多・多対一の対応を許容し、シンボル名の似方だけでは結合しない。
未解決はunit_idの数値と未確認表示を維持。新しいユニットIDの対応には追加の根拠が必要となる。

### C. 状態・演出・外見の辞書（次優先）

- stateicon/efstids.lua、stateiconinfo.lua、stateiconimginfo.lua: 状態アイコンID・シンボル・説明・画像名。
  観測値の説明を補い、既存config/auriga/status_ids.jsonの変換根拠と照合する。
  EFSTとAuriga SCは別ID体系で、EFST番号をそのままsc_start/sc_endへ渡さない。
  日本語説明は `reference_names.descriptions` へ分離して取り込み可能（#24）。
  提供 stateiconinfo の `descript` 先頭タイトル792件を取り込み済み。画像名対応は別作業。
- skilleffectinfo/effectid.lua、skilleffectinfolist.lua、actorstate.lua: エフェクトID・音・モーションの参照。
  スキルと演出の候補関係を表示できるが、一つの演出から使用スキルや発生元を確定しない。
- datainfo/jobidentity.lua、npcidentity.lua、jobname.lua、pcjobname.lua: 職業／NPC／MOBのclassシンボル・リソース名。
  観測NPC名をリソース名で置き換えず、class844外見変更等の既存分類規則を維持する。
- accessoryid/accname、spriterobeid/spriterobename、weapontable、titletable: 頭装備・肩・武器・称号の表示補助。
  外見番号とアイテムIDは同一視しない。setnpcdisplayの引数対応は別途検証する。
- emotion/cashemotion、hateffectinfo、damageskin: エモーション・装備演出等の説明候補。
  数値・配信先・発生元は観測を優先する。

## 3. アイテム・MAP・クエスト等

### アイテム資料

利用者指定により、名称はidnum2itemdisplaynametableの識別済名称だけを使用する。
num2itemdisplaynametableの未鑑定名称は取り込み・表示対象外。鑑定状態は別の観測値として扱う。
idnum2itemdesctable/num2itemdesctableは説明、idnum2itemresnametable/num2itemresnametableはリソース名。
iteminfo.luaは名称・スロット・ClassNum・EffectID等を持つが、空の名称も多く、
TXTの有効名称を空文字で上書きしない。レコードIDと表示名の照合を先に行う。

cardprefixnametable/cardpostfixnametableはカード接頭・接尾語、num2cardillustnametableは画像、
carditemnametable/bookitemnametableは種別集合として整理する。
itemslotcounttable、itemslottable、itemparamtableはスロット数・装備箇所等の補助候補で、
ビット値の意味と現クライアント版を確認してから表示する。
equipmentproperties.lua、itemmoveinfov5、buyingstoreitemlist、metalprocessitemlist/tableは
装備性質・取引制約・買取・加工の参考資料。サーバー側可否の確定や交換shopの自動生成には使わない。

GUIの所持品、NPCアイテム授受、通常shopの名称確認に優先利用する。
床アイテム履歴・MOBドロップ台帳は作らない。
leveluseskillspamount.txtはskillinfozの消費SPとの相違確認に限り、MOB使用条件にはしない。

### MAP・クエスト・ナビゲーション

mapnametable.txtとnavigation/navi_map_jp.luaはMAP識別子に併記する表示名に使う。
内部キー・生成コードのMAP名は生値を保持。rsw/gat拡張子、大小文字、インスタンス接頭辞は
表示名検索のための投影に限定し、実マップIDを同一化しない。
resnametableのリソース共有は同じゲーム内MAP／NPCである証拠にしない。

questid2display.txt、datainfo/questinfo_f等はクエスト名・説明の補助に使う。
setquest/delquestは引き続き観測ID、checkquestの状態は観測根拠を使用し、説明から進行条件を復元しない。

navigationのNPC/MOB/リンク・距離・スクロール・ワープ選択情報は、外部参考として分離する。
Navi_Mobには複合値に見える数値があり、各列をclass IDや湧き数と決め打ちしない。
ナビIDを実行時ActorIDと同一視せず、NPC配置・現在MAP・MOB性能の観測値を置き換えない。

mp3nametableはMAP既定BGMの参考。受信BGM変更やmusiceffectの観測を新規に作らない。
viewpointtableはカメラの距離・角度等であり、0x0144マーカーのviewpoint命令とは別物。
mappostableはワールド地図上の領域で、ゲーム内セル座標として使わない。

### 低優先度・参考用途に留める資料

fogparametertable、mapobjlighttable、indoorrswtable、exceptionminimapnametable、
notnavigate_maptable、mapinfotable.scp、etcinfo、mapskydata、mapeffectinfoは背景・表示設定。
特にeffecttool（lua files側だけで1,378 Lua）はクライアント側MAP演出の参考であり、
時刻や座標からNPC OnTimer、サーバーイベント条件、スクリプト命令を補完しない。

msgstringtable/msgstring_jpはシステム文言、guildtipはヘルプ、ba_frostjoke/dc_screamは発言素材、
mannerは発言制限資料であり、NPC会話本文へ流用しない。
UI文言の照合・通知種別の区別に必要なものだけ後で取り込む。

残るLua群（admin、adventureguide、agit、chatwndinfo、dressroom、enchant、equipmentproperties、
itemreform、offsetitempos、optioninfo、ridingspreditinfo、seekparty、selectpackage、service_japan、
spreditinfo、stylingshop、transparentitem、worldviewdata等）とhotkey/wndinfo/signboardlistは
クライアントUI・見た目・案内・サービス用資料として分類する。今回の復元目的に直結する静的辞書だけを選別し、
関数やサービス設定を解析処理へ読み込まない。test内のEXE/BATは取り込み対象外。
全ファイルの所在は調査JSONのmanifestで追跡できる。

## 4. 共通取り込み方式

1. 原資料は読み取り専用。採用ファイル・内容ハッシュ・エンコーディング・抽出方式・版を記録する。
2. インポータは許可した定数代入・テーブル・文字列リテラルだけを静的解析する。
   最初にdry-runで追加／変更／競合／未解決／不正行を出し、既存辞書を直接変更しない。
3. Lua文字列はバイト列として字句解析し、Luaエスケープを戻した後にCP932等へ厳密変換する。
   CP932のソ・表等の末尾0x5Cとエスケープが衝突するため、先にUnicodeへ変換した正規表現置換は使わない。
   実際にリジェクトソード等で余分なバックスラッシュが生じた。文字コード混在・不明値は警告して保留する。
4. 数値IDの名前空間を分ける。SKID／unit種別／class／ActorID／EFST／SC／effect／item／外見番号を分離する。
   出典間の競合を自動的な後勝ちにせず、ファイルごとの採用規則と手動上書きを明示する。
5. 正規化結果だけをUTF-8 JSONへ生成する。既存skill_namesのversion=1/skills形式は維持し、
   シンボル・説明・出典等の補助カタログは分離して既存利用箇所の互換性を保つ。
6. 生パケット・観測名・IDを変えず、辞書の表示名を追加投影する。元の不完全名を推測で埋めない。
7. 生成・保存開始時の辞書と出典を固定し、更新前後を混ぜない。解析JSON／プロジェクト／MOB候補へ
   採用カタログの識別情報を残す。GUIで174MBの原資料を毎回読み込まず、明示的なインポートでのみ更新する。
8. 失敗時は既存辞書を保持し、差分を確認できる形で保存する。現行ローダーのサイズ・ID・文字数制限を維持する。

## 5. 実装順と完了条件

### 第1段階: スキル名インポートの土台と更新（実装済み）

対象をskillid/skillinfolistの2ファイルに限定した静的インポータを実装済み。
バイト文字列・コメント・入れ子テーブル・定数参照を解析し、関数・関数呼出し・追加実行文は拒否する。
Lua優先・既存名保持・別名報告・不正／未解決時の適用拒否を実装した。
GUI等は従来の辞書APIを使う。MOB候補名・固定保存等を含む対象13テストを確認した。

### 第2段階: スキルユニット・状態・エフェクトの名前解決

UNITIDとAuriga側対応を別カタログへ整理し、確認できるunit_idだけ日本語名を付ける。
状態・effectは数値とシンボルの併記から始め、既存sc_start変換や未知ID停止を変えない。

### 第3段階: アイテム・MAP・クエストの表示補助

名前の有効件数と競合を点検して辞書を生成し、所持品／shop／MAP基本データ／クエストタイムラインへ併記する。
NPC/MOBの観測・同一性判定とコードの数値引数は維持する。

### 第4段階: 説明・コスト・外見・演出資料

詳細画面や任意の参照欄へ追加する。詠唱時間・コスト・範囲はクライアント資料との比較に限定。
MAP演出やナビゲーションの詳しい利用は、必要になった項目を個別に検証してから進める。

変更ごとに対象テストのみ実施する。初回はLuaのCP932/0x5C/引用符/数値エスケープ、別名・重複、
不正構文・未解決SKID・空値、旧辞書保持、MOB名称と固定保存を重点にする。
辞書更新でPacketID・フレーミング・観測件数・会話の数値引数が変化しないことを既存ログで確認する。
スキルの名称変更によるコメント／候補nameの変更は、意味イベントの変化と分けて扱う。
全件テスト、実機試験、固定v0.0.4の再作成を今回の計画策定だけで実施しない。


### Lua優先の初回反映（2026-10-30）

調査時の入力ファイルと辞書のSHA-256が一致することを再確認し、既存名称差122件だけを更新した。
現行辞書のID集合と件数1,325は維持し、新規IDは追加していない。
出典と優先規則を辞書name_resolutionへ記録し、変更前後の名称・辞書ハッシュを
logs/skill-name-lua-priority-update.jsonへ保存した。
関連3テストで辞書API、MOB候補へのLua名称反映、スキルID・元観測の不変を確認。
予備照合の588/122/163は変更前の調査値として保持する。


## 6. スキル名インポータの使い方

確認のみ（既定動作、辞書を書き換えない）:

```powershell
python -m tools.import_skill_names --report logs/skill-name-import-preview.json
```

検証後の辞書へ反映:

```powershell
python -m tools.import_skill_names --apply --report logs/skill-name-import-plan.json
```

既定入力は.reference/data/luafiles514/lua files/skillinfoz配下のskillid.luaとskillinfolist.lua。
--skillid/--info/--dictionaryで入力を指定可能。--encodingはcp932（既定）またはutf-8。
ソースは各2MiB、辞書は1MiB、トークン数・入れ子にも上限がある。
Luaバイナリを直接読まず、限定文法以外は不正・未対応として停止する。
重複キー、未解決SKID、空の名称、同一IDの名称競合は既存名との通常差分とは区別して適用を拒否する。

レポートのstage=validated_import_planは検証された更新計画を意味し、適用完了記録ではない。
--apply成功時はCLIがApplied SHA256を表示する。入力ハッシュと生成予定ハッシュを再確認し、
同じディレクトリの一時ファイルから辞書を置き換える。失敗時は元辞書を維持し、一時ファイルを削除する。
.reference配下は原資料として出力禁止。レポートは入力ファイルとconfig配下にも上書きできない。
書式・辞書のロードは次回起動時の通常処理で行い、GUIに原Luaを自動実行・再読込する機構は追加しない。

今回の適用計画: logs/skill-name-import-applied-plan.json。
適用後の確認: logs/skill-name-import-after-update.json（1,913→1,913、追加0、変更0、問題0）。
再実行しても辞書内容は同じになる。現在の辞書SHA-256は
51cced23d431efe54001a50316fee81c119508228f903f5d77a0b07682f2a1e5。
機能テストは `python -m tools.run_tests catalog` で選択実行できる。


### スキルユニット名称の初回反映（2026-10-30）

第2段階のうちユニット種別の名称解決を実装済み。173種類、定義の矛盾2種類、未解決対応6件。
範囲・時間等のDB列は解釈せず、確認できたSKIDとユニット番号の対応だけ利用する。
現在の辞書はconfig/skill_units.json。再生成は開発用CLIで行う。

```powershell
python -m tools.build_skill_unit_catalog --auriga-root C:/project/Auriga
```

MARiAのconst.pyはASTの定数辞書のみ、Aurigaの列挙値は数値リテラルと連番のみを解析する。
参照Python/C/Luaコードは実行しない。--maria/--skillid/--outputで対象を指定できる。
原資料・入力ファイルへの上書きを拒否し、入力ハッシュ再確認と一時ファイルからの置換を行う。
辞書には全採用資料のSHA-256を記録。スキル名の更新をユニット候補名にも反映する場合は再生成する。
状態・effect辞書の拡充と、プロジェクトの辞書版保持は引き続き残作業。


### 状態・視覚効果の初回反映（2026-10-30）

第2段階の状態アイコン1,318種・視覚効果121種について、数値に参照シンボルを併記する辞書を追加。
config/reference_names.jsonの2名前空間を分離し、EFST→SCの新しい変換やスキル使用推定は行わない。
詳細と再生成手順は[受信表示書式](../capture/receive-display.md)を参照。
同値重複3件を記録。提供ファイル中の既知ガード以外の関数・実行文は受け付けない。
既存2ログ3,213通知はエラー0、未登録も数値を維持。日本語説明・未登録効果の辞書拡充は残る。
名称辞書の参照・ハッシュを新規GUIプロジェクトに保持し、実行時の同梱辞書と照合する対応を追加済み。
辞書本体の同梱・任意パスからの実行は行わず、異版は停止する。旧形式は版未記録と明示して読み込む。
詳細は[作業プロジェクト](../guide/offline-project.md)を参照。次はアイテム・MAP・クエストの表示補助へ進める。


### 品名・MAP・クエスト名の初回反映（2026-10-30）

識別済品名15,880件、MAP名4,906件、クエストID8,030件を表示用カタログへ取り込んだ。
MAPの空名8件は未登録として記録し、異なる名称を持つクエストID5件は候補を併記する。
未鑑定名称は利用者指定で除外。config/client_names.jsonは約1.2MBで、既存の設定2MiB制限を維持する。
再生成は `python -m tools.build_client_names`。--data/--outputで指定可能。

GUIの所持品・基本MAP情報・クエストタイムラインへ併記し、観測モデルの名称やコードのIDを上書きしない。
所持品の鑑定は、確認済み一覧のbit0、取得時の専用値、鑑定結果から保持する。
確認済み／未確認のストライドと鑑定フラグは
[所持品観測の検証境界](../observations/player-observations.md#一覧ストライドと鑑定フラグの検証境界48)へ集約。
確認済み形式の根拠はローカルAuriga clif.cの0B09/0B0Aと
[rAthenaのNORMALITEM_INFO/EQUIPITEM_INFO](https://github.com/rathena/rathena/blob/master/src/map/packets_struct.hpp)。
未鑑定名称なし・他フラグの併存・成功／失敗通知・数量保持・GUI・元IDとコード不変等を関連13項目で確認。
既存2ログの最終所持品265/336枠はすべて名称解決、Player解析問題0件。
鑑定状態は旧ログ106枠確認／159枠不明、新ログ156枠確認／180枠不明（未確認一覧形式を推測しない）。
ログと定義のハッシュは不変。logs/client-name-identification-review.jsonへ記録した。
通常shopへの品名併記は実装済み。商品ID・価格・復元コードは変更しない。
0B39は参照実装と実ログ末尾を照合し、68byteレコードoffset67のbit0に対応済み。
0B38は PacketLength 未登録・実ログ0件で利用廃止の可能性。長さ／フラグを推測追加せず、採取優先外。
参照: https://github.com/rathena/rathena/blob/master/src/map/packets_struct.hpp （EQUIPITEM_INFO）。

会話タイムラインのアイテム授受（getitem/getitem2/delitem）にも資料品名を反映済み。ID・数量、未登録ID、装備属性、観測モデルと生成コードの維持を関連3項目で確認。

### MAP・クエスト・ナビゲーション資料の完了範囲（2026-10-30 / v0.0.5）

MAP・クエストの表示名に加え、独立した資料検索ウィンドウを実装。MAPはTXT優先、未登録時にナビ名で補助。
MAP名候補とTXT名を並記し、クエストIDの複数名称も保持する。内部識別子や観測状態は変更しない。
ナビMAP4,449、NPC11,897、MOB14,483、リンク7,852、スクロール1（NULL）、選択ワープ289件。
数値列は意味を推定せず原列のまま表示する。距離・関数資料による経路探索はこの段階の対象外。
生成: `python -m tools.build_navigation`。原資料は静的限定パーサで読む。出典とSHA-256を保持し、変更検知・検証後に置換。
生成先config/navigation.jsonのみ4MiB上限とし、他設定は2MiBを維持。プロジェクトにも辞書版を固定する。
両カタログの再生成一致、MAP名称差0件、関連15項目の通過を確認。詳細はv0.0.5記録を参照。
この範囲を完了としてソーススナップショットを作成する。資料からサーバー条件を推定する段階へは進めない。


### 保存後の不足状態名補完（2026-10-30）

MARiA EFSTと提供Luaの重複1,034件を照合し、競合0件を確認。不足7件だけを出典付きで補完し、
現行状態アイコン名は1,325種。実ログ105通知で新規解決、表示エラー0。視覚効果121種は変更なし。
参照表示のみで、SC変換・スキル推定・状態効果の意味づけは追加しない。
原資料の関数やPythonは実行しない。保存済みv0.0.5 ZIPにはこの補完を反映しない。
