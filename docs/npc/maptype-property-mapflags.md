# MapTypeProperty と mapflag 候補

[資料一覧](../README.md) · [未対応通知（map_property）](unsupported-notifications.md) · [クライアント資料計画](../development/client-data-utilization-plan.md)

検討日: 2026-11-02。入力は利用者提供の `MapTypeProperty.txt`（原資料はリポジトリ外）。

## 結論

**MAPごとの取得（例: `https://rotool.gungho.jp/map/<map>`）が難しい場合でも、観測できた map 名と 01D6／099B の type（kind）が揃い、かつその type が MapTypeProperty の `MAPTYPE n` に存在するなら、構造を合わせて mapflag **コメント行**の候補生成は可能。**  
ただし次はできない／しない。

| できる | できない／しない |
|--------|------------------|
| type 0–27 の ADD_PROPERTY → 保守的な mapflag コメント候補 | ファイル単体からの **map名→type 割り当て**（行が無い） |
| 観測 `(map, kind)` とカタログ照合 | kind がカタログ外（実ログの 50／112 等）への発明 |
| 出典 SHA 付きの type カタログ | 実行用 mapflag／`@mapproperty` 命令の自動採用 |
| カタログ外 type／099B flags の**手動確認メモ** | 099B flags を mapInfoTable と断定すること |

クライアントの ADD_PROPERTY とエミュレータ mapflag は対応が近いが同一ではない。候補は review only。

## PACKET_ZC_MAPPROPERTY（0x02E7）

利用者提供の `PACKET_ZC_MAPPROPERTY.txt` は可変長 `0x02E7` の構造定義。

- `type@4` — `MAPTYPE_*`（例: VILLAGE=0 … UNUSED=0x1D、LAST=0x1E）
- `mapInfoTable@6` — `MAPPROPERTY_*` 各1バイト（サンプル長33＝表27）。多くは 0/1だが `SHOW_HP_BAR` は非ブール値あり
- 現行JP採取ログは主に `01D6`／`099B`。`02E7` が来た場合のみ表を構造化保持する

シンボルカタログ: `config/zc_mapproperty_symbols.json`。

```text
python -m tools.build_zc_mapproperty_symbols --input path/to/PACKET_ZC_MAPPROPERTY.txt
```

## 解析ログ（手動確認メモ）

`map_property` 観測ごとに `manual_review` を付与する。

- **カタログ外 type**: `map` 名と `type`（および packet enum にあれば symbol）をメモし、`OUT_OF_MAPTYPE_CATALOG` と明示
- **flags（099B）**: hex・立っている bit・`MAPPROPERTY_*` の bit 位置**推測**をメモ。`layout_confirmed=false`（02E7 表との同一視はしない）

```text
python -m tools.analyze_map_property_review logs/SESSION/capture.jsonl \
  --definitions PacketLength.txt \
  --output logs/SESSION/map-property-review.json
```

`summary.out_of_catalog` と `summary.flag_memos` を人手確認用に使う。

## 資料の役割分担

1. **MapTypeProperty.txt** — `MAPTYPE n { ADD_PROPERTY… }`。type テンプレート。unset は FALSE。
2. **01D6／099B** — 入場時に type（と 099B では flags）を観測。`map_property` として構造化済み・実行命令なし。
3. **rotool 等の MAPページ** — map 名ごとの type／付帯情報の外部参照。取得できない場合の代替にはならないが、観測 type の人間確認には使える。
4. **mapnametable.txt** — 表示名のみ。type は持たない。
5. **mapinfotable.scp** — 古い type 行の要約表であり、map 名バインドではない。

## 実ログとの照合（20261102-171318-9aba07f0）

workspace 定義で再生した 01D6／099B の type 例:

| map | kind | MapTypeProperty |
|-----|------|-----------------|
| prontera.gat / lasagna.gat | 0 | Town（一致） |
| icas_in.gat / dali02.gat / airport.gat | 1 | Indoor（一致） |
| icecastle.gat | 112 | **カタログ外** → 候補生成しない |
| paramk_.gat / hal_opera.gat | 50 | **カタログ外** → 候補生成しない |

提供ファイルは MAPTYPE 0–27。現行サーバの拡張 type は別版 MapTypeProperty か、観測コメントのみ。

## 保守的な対応（コメント候補）

実装は `reconstruction/maptype_property.py` の `PROPERTY_MAPFLAG_HINTS`。

| ADD_PROPERTY | 値 | 候補 mapflag | 信頼度 |
|--------------|----|--------------|--------|
| TELEPORT | FALSE（unset含む） | noteleport | medium |
| NOTREMEMBER | FALSE | nomemo | medium |
| DISCONNECT_NOTREMEMBER | TRUE | nosave SavePoint | medium |
| CALLMONSTER | FALSE | nobranch | medium |
| PK | TRUE | pvp | medium |
| SIEGE | TRUE | gvg | low（castle/TE要確認） |
| DENYSKILL | TRUE | noskill | medium |
| DENY_BUTTERFLY | TRUE | noreturn | low |
| DISABLE_LOCKON | TRUE | nolockon | medium |
| USE_SIMPLE_EFFECT | TRUE | forcemineffect | medium |
| BATTLEFIELD | TRUE | battleground | medium |

BLOCK_ITEM／BLOCK_SKILL は件数メモに留め、`restricted` ゾーン番号や item_noequip 行は自動発明しない。

## 使い方

```text
python -m tools.build_maptype_property_catalog --input path/to/MapTypeProperty.txt
python -m tools.suggest_mapflag_comments --map icas_in.gat --type 1
python -m tools.suggest_mapflag_comments --map paramk_.gat --type 50
```

出力例（Indoor / type 1）:

```text
// mapflag candidates from MapTypeProperty MAPTYPE 1 (Indoor); source_sha256=…; review only — not server truth
// icas_in	mapflag	nobranch  // CALLMONSTER=FALSE (explicit) confidence=medium
// icas_in	mapflag	nomemo  // NOTREMEMBER=FALSE (explicit) confidence=medium
// icas_in	mapflag	noteleport  // TELEPORT=FALSE (explicit) confidence=medium
```

生成カタログ: `config/maptype_property_catalog.json`（原 TXT はコミットしない）。  
`map_property` 観測の実行命令非生成は維持（[未対応通知](unsupported-notifications.md)）。

## 推奨運用

1. キャプチャで map 入場と 01D6／099B を残す（map 名は player map context）。
2. kind がカタログ内なら `suggest_mapflag_comments` でコメント候補を出す。
3. カタログ外 kind は拡張 MapTypeProperty の入手か、観測メモのみ。rotool をスクレイプして type を埋めない。
4. 候補を本番 mapflag へ落とす前に、サーバ挙動・既存 flag セットを人手確認する。
