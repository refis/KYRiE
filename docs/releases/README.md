# リリース / ソーススナップショット

[資料一覧](../README.md) · [v0.0.7](v0.0.7.md) · [v0.0.6](v0.0.6.md) · [v0.0.5](v0.0.5.md) · [v0.0.4](v0.0.4.md)

KYRiEの「版」は、現状 **private なソーススナップショット** です。EXE配布や公開リリースとは別です。

## タグを打つ前（必須の版同期）

次を **同じコミット** で揃える。`version.py` だけ進めて直下READMEを旧版のまま残さない。

1. `version.py` の `__version__` と `SNAPSHOT_DATE` を更新する。
2. **プロジェクト直下の `README.md`**
   - 先頭見出しを `# KYRiE vX.Y.Z (Windows)` にし、本文の版表記・「vX.Y.Zでできること」も同じ版へ更新する。
   - `docs/releases/vX.Y.Z.md` へのリンクを追加し、直前版リンクを残す。
3. `docs/releases/vX.Y.Z.md` に到達点・検証範囲・保存物・残作業を書く。
4. [docs/README.md](../README.md) のスナップショット節へ `vX.Y.Z` リンクを追加する。
5. 変更に応じたテストを実行する。横断・リリース時は広め／全discoverを検討し、**実際に走らせた範囲**を記録する。
6. 作業ツリーに生ログ・DB・EXE・生成NPCコードが混入していないことを確認する。

`python -m tools.run_tests release` は、直下README・`docs/releases/vX.Y.Z.md`・docs索引が
`version.py` と一致することを検証する。不一致のまま `build_snapshot` も拒否する。

## スナップショット作成

```powershell
python -m tools.build_snapshot --output-dir dist
```

- 既存ZIPは上書きしない。別の出力先を使う。
- ZIP内 `SNAPSHOT.json` にファイルごとのサイズとSHA-256、ZIP横に全体のSHA-256を残す。
- リポジトリ直下の `SNAPSHOT.json` を版マニフェストとして置く場合は、**作成したZIP内の同名ファイルをコピー**して更新する（手編集しない）。版・日付は `version.py` と一致させる。
- `logs/`、DB、クライアントEXE、`.reference`、生成コード、キャッシュ、`config/user_settings.json`は含めない。
- ZIP内の `ignorepacket.json` だけ空の既定値へ戻す（作業側の設定は変えない）。
- `config/user_settings.json`はローカル専用のためZIPへ入れない（作業側のファイルも変更しない）。

検証の目安:

```powershell
python -m tools.run_tests release
```

## GitHub上の扱い

- ソースZIPを公開Releaseの常用にしない（中身に参照辞書が含まれ得るため、公開条件は別途確認）。
- 版の説明は `docs/releases/` を正本とし、必要なら private Release の説明欄からリンクする。
- 公開時のライセンスは未確定（[NOTICE](../../NOTICE)）。
