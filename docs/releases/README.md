# リリース / ソーススナップショット

[資料一覧](../README.md) · [v0.0.5](v0.0.5.md) · [v0.0.4](v0.0.4.md)

KYRiEの「版」は、現状 **private なソーススナップショット** です。EXE配布や公開リリースとは別です。

## タグを打つ前

1. `version.py` の `__version__` と `SNAPSHOT_DATE` を更新する。
2. `docs/releases/vX.Y.Z.md` に到達点・検証範囲・保存物・残作業を書く。
3. [docs/README.md](../README.md) のスナップショット節へリンクする。
4. 変更に応じたテストを実行する。横断・リリース時は広め／全discoverを検討し、**実際に走らせた範囲**を記録する。
5. 作業ツリーに生ログ・DB・EXE・生成NPCコードが混入していないことを確認する。

## スナップショット作成

```powershell
python -m tools.build_snapshot --output-dir dist
```

- 既存ZIPは上書きしない。別の出力先を使う。
- ZIP内 `SNAPSHOT.json` にファイルごとのサイズとSHA-256、ZIP横に全体のSHA-256を残す。
- `logs/`、DB、クライアントEXE、`.reference`、生成コード、キャッシュは含めない。
- ZIP内の `ignorepacket.json` だけ空の既定値へ戻す（作業側の設定は変えない）。

検証の目安:

```powershell
python -m tools.run_tests release
```

## GitHub上の扱い

- ソースZIPを公開Releaseの常用にしない（中身に参照辞書が含まれ得るため、公開条件は別途確認）。
- 版の説明は `docs/releases/` を正本とし、必要なら private Release の説明欄からリンクする。
- 公開時のライセンスは未確定（[NOTICE](../../NOTICE)）。
