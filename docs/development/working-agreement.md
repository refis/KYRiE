# 作業合意（GitHub運用）

[資料一覧](../README.md) · [CONTRIBUTING](../../CONTRIBUTING.md)

GitHubへ管理を移したあとの、Issue / PR / docs / テストの役割分担です。  
納期や性能の確約ではなく、観測根拠を壊さないための合意です。

## 役割分担

| 置き場 | 役割 |
|---|---|
| GitHub Issue | これから行う作業の単一チケット（バグ・機能・採取・調査） |
| Pull Request | `main` へ入れる変更のレビュー単位 |
| `docs/` | 仕様・操作・限界の正本 |
| `DEVELOPMENT.md` | 直近の作業メモ・計測・検証範囲の記録（仕様の代替にしない） |
| `docs/releases/` | 版ごとの到達点・検証範囲・残作業 |
| 生ログ / DB / EXE | Git外。Issueには識別情報のみ |

WikiやDiscussionsは使わず、質問はIssue、確定した説明はdocsへ昇格します。

## 観測と推定

- 受信および観測可能な非暗号化送信から根拠を残す。
- 未観測の分岐・AI条件・設定湧き数・タイマー値・サーバー内部状態を発明しない。
- 観測した時間差はサーバー設定時間そのものではない。
- PacketID・可変長は little endian。未知IDのあとで同期のためバイトを飛ばさない。
- 欠損は再送待ち。内容を合成しない。判別できた初期HTTPは PASS。
- MOBスキル間隔は個体単位で計算してからクラス集計する。
- Auriga NPC（タイマー含む）と MOB解析を優先。rAthena表示は低優先・外部profile。

根拠の扱いの詳細は [restoration-plan.md](restoration-plan.md) を参照。

## Issue のラベル目安

- 種別: `bug` / `enhancement` / `documentation` / `capture` / `investigation`
- 領域: `npc` / `mob` / `gui` / `capture-stack` / `storage` / `config-dict`
- 状態: `needs-raw-log` / `needs-auriga-check` / `blocked`
- 優先: `P0`（取得破損・保存破壊） / `P1`（復元誤り） / `P2`（表示・辞書・操作性）

テンプレは `.github/ISSUE_TEMPLATE/` にあります。

## PR とテスト

- 変更した機能グループだけを `python -m tools.run_tests` で実行する（既定）。
- 実行した範囲をPRに書く。選択実行を全件通過と書かない。
- 挙動変更には回帰を追加する。重複した実装詳細だけのテストは増やさない。
- リリースや横断変更のときだけ全discoverや広いグループを検討する。
- Windows実機・Npcap・Auriga実行は合成／GUIテストの代替にならない。必要な場合はIssueで明示する。

## docs と DEVELOPMENT.md

- 操作や意味解析の結果が変わる変更は、同PRで該当 `docs/` を更新する。
- `DEVELOPMENT.md` には「何を測ったか・どのテスト範囲か・次に触る候補」を短く残してよい。
- 仕様として残す内容は docs へ移し、Issue/PRからリンクする。
- 目次更新は [docs/README.md](../README.md) に追記する。

## キャプチャと秘密情報

[SECURITY.md](../../SECURITY.md) に従う。診断へ平文ペイロードを出さない。  
ソーススナップショット手順は [releases/README.md](../releases/README.md)。
