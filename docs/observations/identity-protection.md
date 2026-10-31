# 操作キャラクター情報の保護置換

[資料一覧へ](../README.md) · [プロジェクトREADME](../../README.md)

観測ログとAuriga/rAthenaコード候補から、操作キャラクターの個人識別情報を外へ出しにくくする。
意味解析やSQLite・根拠JSONの生値は変更しない。表示と生成のときだけ置換する。

## 対象

- 本文系: `mes` / `menu` / `announce` / `showmessage` / `unittalk` など、文字列本文に
  観測済みのキャラクター名・パーティ名・ギルド名が含まれる場合
- 注釈系: 表示テンプレートの `{actor_id}` などが本人ActorIDと一致する場合は `self`

Aurigaでは `getstrcharinfo(0/1/2)`、rAthenaでは `strcharinfo(0/1/2)` を用いる。
書式は `config/*/identity_protection.json`。

## 例

```text
mes "ようこそ、"+getstrcharinfo(0)+"さん";
@emotion 1;	// self
```

複数の識別子が重なる場合は長い一致を優先する（例: パーティ名「太郎党」とキャラ名「太郎」）。

## 取得との関係

- キャラクター名: キャラクター一覧とマップログインから既存どおり取得
- パーティ名 / ギルド名: 状態欄として保持し、値が観測できたときだけ置換する
  （専用パケットの恒常デコードは未実装。未取得なら置換しない）
- 本人ActorID: マップログイン／account通知の既存値

NPCのActorIDやNPC名コメントは本人情報ではないため置換しない。

## 検証

観測値そのものはステップ・`DisplayResult.fields` に残し、生成行だけが置換後になることを
単体テストで確認する。
