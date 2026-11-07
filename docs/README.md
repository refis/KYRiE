# ドキュメント案内

操作・観測対象・開発目的から資料を探すための目次です。[プロジェクトREADME](../README.md)に導入手順があります。

観測値と未確認のサーバー処理・設定値は区別します。各資料の制約・未対応事項も確認してください。
検証件数や実ログ結果は記載時点の記録です。最新の作業記録は[DEVELOPMENT.md](../DEVELOPMENT.md)を参照してください。
Issue/PRはGitHub、確定仕様はdocsを正本とします。

文書の読者分割・GUI操作性の**方針検討**（EXE化・EXE配布はしない）は
[文書分割・GUI UX](development/packaging-docs-gui-ux.md) を参照（実装済み機能一覧ではない）。

## 利用者向け（まずここ）

日常の起動・観測・再解析・採取だけを探す場合:

1. [プロジェクトREADME](../README.md) — 導入・限界・NOTICE
2. [GUIの構成と操作](guide/gui-workspace.md)
3. [保存ログの再解析](guide/offline-replay.md) / [作業プロジェクト](guide/offline-project.md) / [複数ログ](guide/multiple-log-replay.md)
4. [生パケット採取リスト](capture/raw-packet-collection-checklist.md)
5. [観測ログの表示除外](guide/ignorepacket.md)

残作業の正本は[開発計画・次の着手単位](development/development-roadmap.md#次の着手単位)。

## 仕様契約（操作と開発の共有正本）

意味解析・生成境界・未対応の定義。手順書ではなく契約として読む:

### キャプチャ・解析

- [取得失敗・長さ定義の調査](capture/capture-analysis.md)
- [送信パケットの取得](capture/send-capture.md)
- [受信パケットの表示書式](capture/receive-display.md)
- [一括セッション解析](capture/session-analysis.md)

### NPC復元

- [会話復元の対応範囲](npc/dialogue-restoration.md)
- [会話経路の統合・矛盾](npc/dialogue-merging.md)
- [反復メニューのwhile化](npc/dialogue-menu-loops.md)
- [close・close2と応答](npc/dialogue-closing.md)
- [会話中の所持品・Zeny変化](npc/dialogue-resource-observations.md)
- [所持品・装備・倉庫・待機室の命令](npc/item-and-ui-commands.md)
- [会話の時間経過・反復比較](npc/dialogue-timing.md)
- [演出の基準点比較](npc/event-trials.md)
- [手動確認したタイマー候補](npc/event-timer-candidates.md)
- [未対応通知の対象と構造化保持](npc/unsupported-notifications.md)
- [MapTypeProperty と mapflag コメント候補](npc/maptype-property-mapflags.md)
- [配置付きNPCファイル出力](npc/npc-file-export.md)
- [全NPCの一括出力](npc/npc-bundle-export.md)
- [通常ショップの観測](npc/shop-observations.md)
- [shop・callshop候補の出力](npc/shop-export.md)

### MOB解析

- [性能・攻撃間隔の観測](mob/mob-performance.md)
- [使用スキル・詠唱の観測](mob/mob-skills.md)
- [スキルDB候補の出力](mob/mob-skill-export.md)
- [配置・再観測と配置候補](mob/mob-spawn-observations.md)

### 基本データ・個体観測

- [現在マップ・座標・所持品・Zeny](observations/player-observations.md)
- [ログインとキャラクター台帳](observations/login-character-data.md)
- [NPC・MOB個体の観測](observations/entity-observations.md)
- [プレイヤー現在マップによる配置補完](observations/entity-map-context.md)
- [グループ・称号とOnInit](observations/entity-group-title.md)
- [操作キャラクター情報の保護置換](observations/identity-protection.md)

## 開発向け

方針・計画・運用。日常操作の手順は「利用者向け」を正とする。

- [作業合意（GitHub運用）](development/working-agreement.md)
- [GitHubラベル作成](development/github-labels.md)
- [復元の基本方針・根拠の扱い](development/restoration-plan.md)
- [MARiAとの差分・今後の計画](development/development-roadmap.md)
- [文書分割・GUI UX の検討（EXE化なし）](development/packaging-docs-gui-ux.md)
- [保存後の経過メモ](development/progress-notes.md)
- [提供TXT/Luaの調査と活用計画](development/client-data-utilization-plan.md)
- [貢献・作業の進め方](../CONTRIBUTING.md)
- [セキュリティと取り扱い](../SECURITY.md)
- [テストの実行・整理方針](../tests/README.md)
- [ネイティブ取得・IPC設計](../hook/DESIGN.md)

## スナップショット

- [手順・タグ前チェック](releases/README.md)
- [v0.0.11](releases/v0.0.11.md) · [v0.0.10](releases/v0.0.10.md) · [v0.0.9](releases/v0.0.9.md) · [v0.0.8](releases/v0.0.8.md) · [v0.0.7](releases/v0.0.7.md) · [v0.0.6](releases/v0.0.6.md) · [v0.0.5](releases/v0.0.5.md) · [v0.0.4](releases/v0.0.4.md)

資料追加時は該当分類へ配置し、この目次へリンクを追加します。詳細仕様は各資料、全体方針は開発方針、作業履歴はDEVELOPMENT.mdへ記録します。
