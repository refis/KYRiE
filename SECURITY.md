# セキュリティと取り扱い

KYRiEはゲーム通信の観測・保存を扱います。リポジトリやIssueに載せてよいものと、外に置くものを分けてください。

## リポジトリに入れないもの

- 生キャプチャ（`logs/`、`*.jsonl`、再解析用生バイト）
- パケットDB（`*.sqlite3` と `-wal`/`-shm`）
- クライアントEXE・抽出バイナリ・`.reference` 原資料
- 生成したNPCコードや作業用エクスポート（ルートの生成物）
- ローカルGUI設定（`config/user_settings.json`）
- アカウント、パスワード、個人を特定しうる会話全文のサンプルをIssue/PRに貼ること

`.gitignore` とソーススナップショットの除外方針が正です。ローカルの `client/` は [client/README.md](client/README.md) を参照。

## Issue / PR で共有してよい識別情報

- パケット件数、接続数、品質警告の種類と件数
- 定義ファイル名、定義ハッシュ、アプリ版（`version.py`）
- 再現に必要な PacketID（数値）と、ペイロードを含まない構造説明
- 外部保管物の **SHA-256** とおおよその保管場所（秘密の絶対パスは避ける）

診断ログにも平文ペイロードを出さないでください。

観測ログとコード候補では、操作キャラクターの名前・パーティ名・ギルド名を
`getstrcharinfo` 等へ置換し、本人ActorID注釈は `self` と表記します。
詳細は [docs/observations/identity-protection.md](docs/observations/identity-protection.md)。

## 脆弱性や取り扱い上の懸念

private リポジトリ向けの作業です。取得経路・IPC・保存周りで危険な挙動を見つけた場合は、公開Issueに詳細ペイロードを載せず、メンテナ（リポジトリ所有者）へ直接連絡してください。

## スナップショット

`python -m tools.build_snapshot` の成果物は private データ無しのソース保存用です。公開配布や第三者への再配布を意味しません。公開時のライセンスと参照資料の扱いは別途決定します（[NOTICE](NOTICE)）。
