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
| 状態 | `observed` + `not_adopted` |
| 観測 kind | `event_marker` |
| 生成 | コメントのみ（`event_marker` / `external_event_marker`）。実行 `showevent` は出さない |
| タイマー | 手動採用時は**全行コメント**のみ。実行 showevent は出さない（[event-timer-candidates](event-timer-candidates.md)） |
| 外部候補 | 会話中の別既知NPCへ届いた場合は `external_presentations` へ保持。呼出し元は未確定 |

合成パケットで decode・保持・コメント出力・タイマー拒否を確認。実機／Auriga実行確認は不要（本Issue範囲）。

## 表示定義にあるが構造化未接続（display_only）

表示テンプレートがあるが、現状 `decode_dialogue` へ未配線。一覧のみ。勝手に命令化しない。

| PacketID | 表示名 | 主なフィールド（表示定義） | 構造化が必要になったときの方針 |
|----------|--------|---------------------------|--------------------------------|
| `0A3B` | Hat effect | actor_id@4, enabled@8, effect_id@9 | actor 付きなら `presentation_observations`。実行命令は未確認ならコメント |
| `0A24` | Achievement | achievement_id@16 | プレイヤー通知として保持候補。NPC命令へは出さない |
| `0AB9` / `0B13` | Item preview | index@2 | 表示のみ／編集用メモ。getitem へ自動変換しない |
| `02C1` | Colored unit speech | 表示テンプレート参照 | unittalk と混同しない。要フィールド照合後に観測 kind を新設 |
| `01D6` / `099B` | Map property | kind 等 | マップ属性観測。NPC 本文命令へは出さない |
| `029B` | Mercenary | actor_id, name, duration | 傭兵表示。NPC 復元の主経路外 |
| `08FF` / `0984` | Status on enter | 表示の `@effect_enter` | 既存 status（0196/043F/0983）と別。混同・自動補完しない |

## 観測済みだが実行命令未採用（not_adopted の例）

詳細は各専用ドキュメント。ここは対照用の要約。

| kind / ID | 保持 | 生成・タイマー |
|-----------|------|----------------|
| `music`（07FE/0B8C） | 対象なしで構造化 | 本文・タイマーへ musiceffect しない（[event-trials](event-trials.md)） |
| `mapcell`（0192） | 構造化 | setcell／タイマーへ出さない |
| `effect_value`（0284） | 構造化・コメント | 実行命令なし。タイマーはコメント採用可（[event-timer-candidates](event-timer-candidates.md)） |
| `external_*` | 外部候補 | 既定はコメント。emotion／effect／解除／overhead／unittalk は明示採用可（#16）。sound等は不可 |
| `progressbar` 観測コメント／viewpoint 未対応値 | 構造化 | 対応範囲外はコメントまたは非タイマー |

## 変更時の確認

```text
python -m tools.run_tests presentation
python -m tools.run_tests tests.unit.test_event_marker_observations
```

全件 discover は本Issueの既定範囲外。実機・Npcap・Auriga確認は不要。
