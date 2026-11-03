# 未対応通知の対象と構造化保持

[資料一覧へ](../README.md) · [プロジェクトREADME](../../README.md)

表示JSON（`config/*/display.json`）にあるが、会話モデル／命令生成へ未接続、
または観測のみで実行命令へ出さない通知の一覧と保持方針。
起因NPC・OnTimer値・サーバー内部状態・未観測フィールドは推測しない。

状態の意味:

| 状態 | 意味 |
|------|------|
| `observed` | `presentation_observations` 等へ構造化保持済み |
| `not_adopted` | 観測はあるが実行命令／タイマー採用は意図的に出さない（コメントまたは拒否） |
| `display_only` | 表示定義のみ。decode／構造化保持なし |

保持先の既定は `presentation_observations`（会話並行・外部候補は既存と同じ付帯列）。
新規の並行ストアは作らない。命令生成や OnTimer 推定は別Issue。

## イベントアイコン（0446）

| 項目 | 内容 |
|------|------|
| PacketID | `0446`（14バイト固定） |
| 表示名 | NPC event marker / `@showevent {state}, {kind}` |
| フィールド | actor_id@2 u32, x@6 u16, y@8 u16, state@10 u16, kind@12 u16 |
| 状態 | `observed` + （単独時）`not_adopted` / （クエスト関連時）OnQuestInfo |
| 観測 kind | `event_marker` |
| 生成 | 会話本文の単独はコメントのみ（`event_marker`）。会話中（close2判定中含む）の `setquest`／`delquest` 直後に続いた場合は該当NPCの `OnQuestInfo:` へ `showevent {state}, {kind}, "{name}"; // {quest_id}: {x}, {y}` を追加 |
| タイマー | 手動採用時は `showevent {state}, {kind}; // {x}, {y}`（対象NPC自身・会話外）。rAthena書式は確認コメント可（[event-timer-candidates](event-timer-candidates.md)） |
| 外部候補 | 会話中の別既知NPCへ届いた場合は `external_presentations` へ保持。既定はコメント（`external_event_marker`）。明示採用時は `showevent {state}, {kind}, {target}; // {x}, {y}`（Auriga）。クエスト関連付け済みなら OnQuestInfo 側へ移し、外部コメントは出さない |

合成パケットで decode・保持・コメント出力・タイマー拒否を確認。実機／Auriga実行確認は不要（本Issue範囲）。

## 帽子エフェクト（0A3B）

| 項目 | 内容 |
|------|------|
| PacketID | `0A3B`（PacketLength `-1`。既知レイアウトは全長11バイト） |
| 表示名 | Hat effect / `@hat_effect`・`@hat_effect_end` |
| フィールド | length@2 u16(=11), actor_id@4 u32, enabled@8 u8, effect_id@9 u16 |
| 状態 | `observed` + `not_adopted` |
| 観測 kind | `hat_effect` |
| 生成 | コメントのみ（`hat_effect` / `external_hat_effect`）。hateffect 等の実行命令は出さない |
| タイマー | 手動採用時は**全行コメント**のみ（[event-timer-candidates](event-timer-candidates.md)） |
| 外部候補 | 会話中の別既知NPCへ届いた場合は `external_presentations` へ保持。呼出し元は未確定 |

表示定義のフィールド配置に合わせた合成パケットで decode・保持・コメント出力を確認。
未知の追加バイトや length≠11 は構造化せずエラーとする。実機／Auriga実行確認は不要（#18範囲）。

## 実績通知（0A24）

| 項目 | 内容 |
|------|------|
| PacketID | `0A24`（PacketLength 66） |
| 表示名 | Achievement / `achievement {id}` |
| フィールド | achievement_id@16 u32（表示定義どおり。他バイトは未解釈） |
| 状態 | `observed` + `not_adopted` |
| 観測 kind | `achievement` |
| 生成 | 出さない。プレイヤー向け通知であり NPC の achievement 命令／タイマーへ変換しない |
| 対象 | ActorID なし。会話中でも active NPC へ割り当てない（music と同様） |

合成パケットで decode・保持・命令非生成を確認。残バイトの意味は推測しない。

## 色付きユニット発言（02C1）

| 項目 | 内容 |
|------|------|
| PacketID | `02C1`（PacketLength `-1`） |
| 表示名 | Colored unit speech / `@talk …, color: …` |
| フィールド | length@2 u16、actor_id@4 u32、color@8 u32、text@12（NUL終端） |
| 状態 | `observed` + `not_adopted` |
| 観測 kind | `colored_speech` |
| 生成 | コメントのみ（`colored_speech` / `external_colored_speech`）。`unittalk` 実行命令は出さない |
| タイマー | 手動採用時は**全行コメント**のみ（[event-timer-candidates](event-timer-candidates.md)） |
| 外部候補 | 会話中の別既知NPCへ届いた場合は `external_presentations` へ保持。呼出し元は未確定 |

表示定義の wire 色値を明示し、008D `unittalk` と混同しない。合成パケットで decode・保持・コメント出力を確認。
20261102-173136-edcd6b68で実機 RECV×1（MOB actor 732、会話外、color wire `0x000000FF`、
map `pay_d03_i.gat`）。presentation_observations に保持し、会話 auriga 本文へ unittalk は出さない。

## アイテムプレビュー（0AB9／0B13）

| 項目 | 内容 |
|------|------|
| PacketID | `0AB9`（47バイト）／`0B13`（48バイト） |
| 表示名 | Item preview / `itempreview {index}` |
| フィールド | index@2 u16（表示定義どおり生値-2。他バイトは未解釈） |
| 状態 | `observed` + `not_adopted` |
| 観測 kind | `item_preview` |
| 生成 | 出さない。所持Indexの観測メモであり `getitem`／`itempreview` 実行命令へ変換しない |
| 対象 | ActorID なし。会話中でも active NPC へ割り当てない（achievement と同様） |

合成パケットで decode・保持・命令非生成を確認。残バイトの意味は推測しない。

## マップ属性（01D6／099B）

| 項目 | 内容 |
|------|------|
| PacketID | `01D6`（4バイト）／`099B`（8バイト）／`02E7`（`-1`、サンプル33バイト） |
| 表示名 | Map property / `@mapproperty` |
| フィールド | kind@2 u16。`099B` は flags@4 u32。`02E7` は type@4＋mapInfoTable@6 |
| 状態 | `observed` + `not_adopted` |
| 観測 kind | `map_property` |
| 生成 | 出さない。マップ属性の観測であり NPC 本文命令へ変換しない |
| 対象 | ActorID なし。会話中でも active NPC へ割り当てない |

kind がクライアント `MapTypeProperty.txt` の `MAPTYPE n` に載る場合に限り、
mapflag **コメント候補**を別ツールで出せる（実行 mapflag の自動採用はしない）。
カタログ外 type と 099B flags は `manual_review` メモとして解析ログへ残し、人手確認用とする。
詳細は[MapTypeProperty と mapflag](maptype-property-mapflags.md)。

## 入場時状態（08FF／0984）

| 項目 | 内容 |
|------|------|
| PacketID | `08FF`（24バイト）／`0984`（28バイト） |
| 表示名 | Status effect on enter / `@effect_enter` |
| フィールド | actor_id@2、effect_id@6、remaining_ms@8、付加値。`0984` は tick@12 を追加 |
| 状態 | `observed` + `not_adopted` |
| 観測 kind | `status_enter` |
| 生成 | コメントのみ。既存 status（0196／043F／0983）と混同せず `sc_start` 等は出さない |
| タイマー | 採用対象外（入場時状態を OnTimer へ落とさない） |
| 外部候補 | 会話中の別既知NPCへ届いた場合は `external_presentations` へ保持 |

## 傭兵表示（029B）

| 項目 | 内容 |
|------|------|
| PacketID | `029B`（80バイト） |
| 表示名 | Mercenary / `@makemerc` |
| フィールド | actor_id@2、name@22（24バイト）、duration@64（他バイトは未解釈） |
| 状態 | `observed` + `not_adopted` |
| 観測 kind | `mercenary` |
| 生成 | コメントのみ。`makemerc` 等の実行命令は出さない |
| 対象 | NPC 復元の主経路外。外部候補保持可。タイマー採用対象外 |

## 表示定義にあるが構造化未接続（display_only）

表示テンプレートがあるが、現状 `decode_dialogue` へ未配線だった ID は上記へ個別配線済み。
新たな display_only 候補が出たときだけ、この表へ追加する。

## 観測済みだが実行命令未採用（not_adopted の例）

詳細は各専用ドキュメント。ここは対照用の要約。

| kind / ID | 保持 | 生成・タイマー |
|-----------|------|----------------|
| `music`（07FE/0B8C） | 対象なしで構造化 | 本文・タイマーへ musiceffect しない（[event-trials](event-trials.md)） |
| `mapcell`（0192） | 構造化 | setcellは出さない。タイマーは選択窓関連のコメント採用可 |
| `effect_value`（0284） | 構造化・コメント | 実行命令なし。タイマーはコメント採用可（[event-timer-candidates](event-timer-candidates.md)） |
| `event_marker`（0446） | 構造化・コメント／OnQuestInfo | 会話単独はコメント。タイマー・外部明示採用は showevent 実行命令可（座標注記） |
| `hat_effect`（0A3B） | 構造化・コメント | 実行命令なし。タイマーはコメント採用可 |
| `colored_speech`（02C1） | 構造化・コメント | 実行 unittalk なし。タイマーはコメント採用可 |
| `item_preview`（0AB9／0B13） | 構造化 | getitem／itempreview 実行命令・タイマーへ出さない |
| `map_property`（01D6／099B） | 構造化 | mapproperty 実行命令・タイマーへ出さない |
| `status_enter`（08FF／0984） | 構造化・コメント | sc_start 等なし。タイマー採用対象外 |
| `mercenary`（029B） | 構造化・コメント | makemerc 実行命令・タイマーへ出さない |
| `external_*` | 外部候補 | 既定はコメント。emotion／effect／解除／overhead／unittalk／event_marker は明示採用可。sound等は不可 |
| `progressbar` 観測コメント／viewpoint 未対応値 | 構造化 | 09D1／窓内02F0 progressbar はタイマーコメント採用可（秒数≠OnTimer）。viewpoint対応範囲はタイマー実行命令、未対応値はコメント採用 |

## 変更時の確認

```text
python -m tools.run_tests presentation
python -m tools.run_tests tests.unit.test_map_property_observations tests.unit.test_status_enter_observations tests.unit.test_mercenary_observations
```

全件 discover は本Issueの既定範囲外。実機・Npcap・Auriga確認は不要。
