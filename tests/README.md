# テストの実行と整理方針

通常の変更は、変更した機能・メソッドに対応するテストだけを実行します。
関連機能への影響がある場合に対象を追加し、失敗や未解決の懸念がなければ繰り返し拡大しません。
一度通過した回帰テストは残し、実行対象を絞ります。文書だけの変更はリンクや記述の確認に留めます。

## 機能別の選択

```powershell
python -m tools.run_tests --list
python -m tools.run_tests shop
python -m tools.run_tests dialogue npc
python -m tools.run_tests shop --dry-run
```

機能の区分:

- `release`: ソースZIPの同梱範囲・ハッシュ・再現性・上書き保護
- `commands`: 所持品・装備・精錬・倉庫・姿勢・床アイテム・waitingroom命令

- `capture`: TCP取得、送受信、プロセス追跡、長さ定義・抽出
- `ipc` / `pipe`: IPC単体 / Named Pipe連携
- `dialogue`: 会話、close、統合・タイムアウト、書式、インスタンス
- `presentation`: 会話内アクション、状態異常ID変換、announce、演出、BGM、viewpoint等の観測
- `npc`: 配置・全件出力、class 45・139接触／warp、初期状態、group/title、ActorID
- `shop`: 商品一覧、shop/callshop、拡張barter（0x0B56）、全件出力
- `player`: 現在情報、クエスト、個体状態
- `mob`: 攻撃・性能、スキル、配置・DB候補
- `display`: 表示変換・ignorepacket
- `events`: 時間経過、観測窓、反復比較、手動タイマー候補
- `storage`: ログ、観測保存、品質、作業プロジェクト、GUIユーザー設定プロファイル
- `cli-emulator`: 解析CLIの `--emulator` 指定
- `gui-capture` / `gui-display` / `gui-restoration` / `gui-timing`: GUI責務別
- `offline`: 再解析・参照ファイル連携
- `selection`: テスト実行対象の選択機構

グループは最低限の目安で、自動の依存解析ではありません。例えばcallshopのGUI保存を
変える場合は`shop gui-restoration`、全件NPC出力だけなら`tests.unit.test_npc_bundle`を指定します。
AurigaRendererの共有処理など複数機能へ波及する変更は、該当する会話・演出・NPC等を追加します。
同じケースを複数の指定に含めても実行は1回です。対象未指定や未知の機能名では実行しません。

さらに細かくモジュール・クラス・メソッドを直接指定できます。

```powershell
python -m tools.run_tests tests.unit.test_npc_bundle
python -m unittest tests.unit.test_npc_bundle.NpcBundleTests.test_ambiguous_shop_binding_is_review_only_in_json_and_text -q
```

新しいテストモジュールは`tools/run_tests.py`の対応グループへ追加します。
既存のunit/integration配置とunittestの直接実行は維持しています。

## 全件・階層別の確認

全件実行はリリース前、共通基盤・依存関係の大幅な変更など、広範囲の確認が必要な場合に限定します。
実施時はその理由を記録します。通常の編集ごとには実施しません。

```powershell
python -m unittest discover -s tests -t . -q
```

単体だけ、または連携だけを広く確認する必要がある場合:

```powershell
python -m unittest discover -s tests/unit -t . -q
python -m unittest discover -s tests/integration -t . -q
```

結果には実行した対象と件数を記載し、選択実行の成功を全件成功とは表現しません。

GUIテストはoffscreenで動作し、メモリDBと一時ログディレクトリを使用します。
Windows実機でのNpcap動作確認を代替するものではありません。

`support/` はパケット・会話生成の共通ヘルパーとGUI準備処理です。
テストモジュール同士をimportせず、必要なヘルパーをここから明示的にimportします。
GUIテストはキャプチャ操作、表示、NPC/MOB復元、時間・イベント処理の責務ごとに分割しています。

## 2026-10-27の整理

209件から204件へ削減。移動前後のテストメソッド名を照合し、意図した5件以外に
欠落・重複がないことを確認しました。詳細は `.reference/test-cleanup-audit.json` に保存しています。

削除・統合した確認:

- 表示定義の件数固定チェック: 実際の表示変換、Auriga/rAthena切替で検証。
- GUIタブの配置・親子関係のみの確認: 操作シナリオを残し、内部配置の固定を解除。
- 初期設定だけの確認: 双方向取得・生ログ記録・Pipeの既定値を開始停止テストへ統合。
- 手動投入した旧セッション封筒の確認: 実際の再開始前後のコールバックを使う検証を維持。
- 無関係な表示インスタンスによる状態不変の確認: GUIの再読込と状態維持の検証を維持し、
  decoder許可リストの検証は表示定義の不正値テストへ統合。

一度通過したことだけを理由に回帰テストは削除しません。
未知IDでの停止、TCP再接続・欠損、接続や観測世代の分離、入力後の継続、
矛盾会話のブロック化、menu/switchの生成、証拠情報と出力上限の検証を残します。
今後は同じ振る舞いの重複を増やさず、関連するケースを既存テストやsubTestへ追加します。

整理後の検証結果: 単体173件、連携31件、全体204件が通過。
既存の実行方法でも全204件を検出します。
実ログ `20261026-223425-131e9688` と `20261027-064450-e05d0fb7` を再解析し、
15ステップ・18ステップの会話から生成するコードが保存済み結果と一致することも確認しました。
統合結果は1グループ、識別情報不足による除外1件、コード生成エラー0件です。

直近スナップショットの検証範囲は[v0.0.6記録](../docs/releases/v0.0.6.md)を参照。
版を進めるときは直下READMEも同コミットで更新する（[手順](../docs/releases/README.md)）。
