# KYRiE v0.0.5 (Windows)

v0.0.5はMAP・クエスト・ナビゲーション資料の表示・検索までを含むソース保存版です。現在の作業ツリーには保存後の開発も含みます。過去のv0.0.4 ZIPは保持します。開発履歴は[開発記録](DEVELOPMENT.md)に記載します。

Auriga形式のNPCコード復元と、MOB性能・使用スキルの観測解析を目的とする開発スナップショットです。
MARiAを参考に、受信・観測可能な非暗号化送信パケットから編集用コードと根拠を生成します。
完成した元スクリプトやサーバー設定を保証するものではありません。

- [v0.0.5の変更点・検証・残作業](docs/releases/v0.0.5.md)
- [保存済みv0.0.4の記録](docs/releases/v0.0.4.md)
- [目的別ドキュメント一覧](docs/README.md)
- [GUI操作](docs/guide/gui-workspace.md) / [開発計画](docs/development/development-roadmap.md)

## 導入

1. WindowsでNpcapを導入します。実際の取得にはアダプターと権限の確認が必要です。
2. Python 3.13 x64を推奨します。今回の検証環境はCPython 3.13.0 x64です。
3. プロジェクト直下で仮想環境を作成し、検証時の依存版を導入します。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe main.py
```

`requirements.txt`は許容範囲、`requirements-lock.txt`は今回使用した版の記録です。
新規環境での依存取得・起動確認はスナップショットの手動確認事項です。

4. 対象クライアント版に合う`PacketLength.txt`を選びます。同梱定義は全クライアント共通ではありません。
   既定はプロジェクト直下の`PacketLength.txt`です。抽出定義を使う場合は設定画面から明示的に選択してください。
5. 対象EXE/PIDを選び、「観測開始」の準備完了後にゲームへログイン／再接続します。
   Interface未指定では使用可能なNpcapアダプターを対象とします。

[取得の診断](docs/capture/capture-analysis.md) / [非暗号化SEND](docs/capture/send-capture.md)

## v0.0.5でできること

- プロセス選択、複数接続追跡、TCP再構成、送受信共通PacketEvent、観測ログと生パケット保存。
- マップ・XY・所持品・Zeny、NPC/MOBの初回と差分、サーバー別ActorID順の一覧・出力。
- NPCの配置・会話統合、選択肢、反復menuのwhile化、入力応答、close/close2、shop/callshop。
- HIDDEN/CLOAKED初期状態、group/title・waitingroom・職業外見のOnInit、接触NPCとインスタンス名の投影。
- 観測条件に応じた所持品・装備・精錬・姿勢・倉庫等の命令候補。未知の引数は確認用コメント。
- MOBの性能・使用スキル・再観測の整理、手動確認した配置／スキルDB候補。
- 演出・会話開始・マップ到着を基準とした比較、根拠保存・再開。タイマー候補は既存の手動採用と全時刻入力で作成。
- 生ログの単独／複数再解析、作業プロジェクト保存、観測ログだけを対象とするignorepacket。

[全NPC一括出力](docs/npc/npc-bundle-export.md) / [イベント比較](docs/npc/event-trials.md) /
[MOB解析](docs/mob/mob-performance.md) / [保存ログの再解析](docs/guide/offline-replay.md)

## 外部設定

- `config/auriga/display.json`: 受信文章、差分表示。送信は`config/send_display.json`。
- `config/auriga/dialogue.json`: Aurigaコード書式。
- `config/auriga/entity_metadata.json`: group/title・waitingroom・外見初期化。
- `config/player_classes.json`: 職業外見class一覧。変更後は再起動・再解析。
- `config/auriga/status_ids.json`: 状態異常ID変換。未確認の引数は自動補完しません。
- `config/auriga/script_commands.json`: 命令候補の条件。床アイテムの総寿命は60000ms。
- `config/ignorepacket.json`: 観測ログ非表示。パケット保存・意味解析・コード生成は継続します。

表示書式はGUIから再読込できます。低優先のrAthena書式は`config/rathena/`に分離しています。
[表示JSON](docs/capture/receive-display.md) / [非表示設定](docs/guide/ignorepacket.md)

## パケット分割と観測の限界

PacketIDは先頭2バイトLE。固定長は定義値を使用し、可変長はID直後2バイトLEの総長（IDとLengthを含む）です。
重複IDは後方定義を優先します。未知IDや矛盾する再送で影響ストリームを停止し、バイト飛ばしや再同期はしません。
欠損は再送を待ち、未解消のギャップは30秒で停止します。SYN観測を基本とし、途中取得は境界を仮定する機能です。
HTTPとして判別した通信はPASSします。Npcapの欠落、高負荷、IPv4断片化には実機確認・追加開発が残ります。

起因・隠れた変数・未観測分岐・AI条件・設定湧き数・タイマー値は推測しません。
観測した時間差はサーバー設定時間ではなく、生成コードはAurigaで読込・動作確認する必要があります。
C++ x86による暗号化前取得は未実装です。任意の外部producer用Named Pipe受信はありますが、ゲームからの取得機能ではありません。
[ネイティブ／IPC設計](hook/DESIGN.md)

## 保存データとスナップショット

再解析には「設定 → 記録」で生バイト記録を有効にします。生ログ・DBにはゲーム内情報が含まれ得るため、
ソースと別に管理してください。パケットDBはWAL＋FULL同期・1件commitを使用し、単体コピーはアプリ終了後に行います。
使用中の-wal／-shmは個別削除しないでください。[保存方式](docs/capture/capture-analysis.md)に詳細があります。
スナップショットZIPにはlogs、DB、クライアントEXE、参照リポジトリ、生成コードを含めません。
ローカルのignorepacket設定はZIP内で空の既定値へ戻します。作業側の設定・データは変更しません。

```powershell
python -m tools.build_snapshot --output-dir dist
```

既存ZIPは上書きしません。更新版を作る場合は別の出力先を指定します。
ZIP内の`SNAPSHOT.json`にファイル一覧とSHA-256、ZIP横に全体のSHA-256を保存します。
このソース保存はEXE配布や公開リリースとは別です。公開時のライセンス・同梱データの扱いは別途確認します。

## 検証

通常は変更対象だけを実行します。

```powershell
python -m tools.run_tests --list
python -m tools.run_tests npc events
```

全件テストが必要な場合の手動実行（v0.0.5では対象テストのみ実行）:

```powershell
python -m unittest discover -s tests -t . -q
```

[テスト方針](tests/README.md)と[v0.0.5の検証記録](docs/releases/v0.0.5.md)を参照してください。
合成・GUIテストの通過はWindowsゲーム実機／Auriga本体での動作確認を代替しません。
旧v0.2/v0.3の開発経緯は[DEVELOPMENT.md](DEVELOPMENT.md)に保存しています。

MAP・クエスト・ナビゲーション資料は「作業 → MAP・クエスト・ナビ資料…」で検索します。
ナビID・数値列は観測ActorIDやサーバー設定と同一視せず、復元コードを自動補完しません。
