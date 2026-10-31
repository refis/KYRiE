# 貢献・作業の進め方

KYRiEは private な開発リポジトリです。作業の入り口は **GitHub Issue**、変更の入り口は **Pull Request → `main`** です。  
仕様と操作の正本は `docs/`、直近の作業メモは `DEVELOPMENT.md` です。

詳細な境界・優先順位は [作業合意](docs/development/working-agreement.md) を読んでください。

## 始める前

1. [README](README.md) で導入と限界を確認する。
2. [docs/README.md](docs/README.md) で対象資料を探す。
3. 生ログ・DB・クライアントEXE・`.reference`・`config/user_settings.json` は Git に入れない（`.gitignore` / [SECURITY.md](SECURITY.md)）。

## Issue

- バグ・機能・採取・調査は Issue を先に作る（テンプレあり）。
- 1 Issue = 1意図。完了条件と「推測しない範囲」を書く。
- 生パケット本文やアカウント情報は貼らない。必要な識別情報は件数・ハッシュ・版名に留める。

## ブランチと PR

- 既定ブランチは `main`。機能ブランチから PR する。
- 1 PR = 1意図。ドキュメントのみの変更も可。
- PR本文はテンプレに従い、**実際に実行した** `python -m tools.run_tests …` を書く。
- 選択実行の通過を全スイート通過と書かない。
- 挙動が変わる変更は回帰テストを同PRに含める。仕様・操作が変わる場合は `docs/` も同PRで更新する。

## テスト

```powershell
python -m tools.run_tests --list
python -m tools.run_tests <groups...>
```

- 既定は変更した機能グループだけを実行する。
- 依存・失敗・未解決の懸念があるときだけ対象を広げる。
- リリースや横断変更では広め／全discoverを検討する。
- 詳細は [tests/README.md](tests/README.md)。

## コード上の守るべき点（要約）

- 受動受信キャプチャと既存 SQLite 列を壊さない。
- PacketID／可変長は little endian。長さはヘッダ込み。未知IDのあとで境界を推測しない。
- 欠損は再送待ち。パケット内容を合成しない。初期HTTPは PASS。
- 未観測のサーバー条件・タイマー・AI・湧き数を発明しない。
- Auriga NPC復元と MOB解析を優先。rAthena表示は低優先で外部profile分離。
- 診断に平文ペイロードを出さない。

エージェント向けの同趣旨ルールは `.cursor/rules/project.mdc` にもあります。

## リリース

ソーススナップショット手順は [docs/releases/README.md](docs/releases/README.md) を参照。  
公開配布用ライセンス方針は未確定です。現状のソースZIPは公開リリースではありません（[NOTICE](NOTICE)）。
