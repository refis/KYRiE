# GitHub ラベル（手動作成）

[作業合意](working-agreement.md) · [CONTRIBUTING](../../CONTRIBUTING.md)

Issueテンプレが参照する追加ラベルです。リポジトリの token 権限によっては CI エージェントから作成できないため、メンテナが一度だけ作成してください。

```powershell
gh label create capture --repo refis/KYRiE --description "Raw packet capture or re-observation" --color 0E8A16 --force
gh label create investigation --repo refis/KYRiE --description "Observation review without code change yet" --color 5319E7 --force
gh label create npc --repo refis/KYRiE --description "NPC restoration / dialogue / shop" --color 1D76DB --force
gh label create mob --repo refis/KYRiE --description "MOB performance / skills / spawns" --color B60205 --force
gh label create gui --repo refis/KYRiE --description "GUI workspace behaviour" --color FBCA04 --force
gh label create capture-stack --repo refis/KYRiE --description "Framing TCP IPC receive path" --color D93F0B --force
gh label create storage --repo refis/KYRiE --description "SQLite session log projects" --color 006B75 --force
gh label create config-dict --repo refis/KYRiE --description "External JSON dictionaries and profiles" --color C5DEF5 --force
gh label create needs-raw-log --repo refis/KYRiE --description "Blocked on raw capture evidence" --color E4E669 --force
gh label create needs-auriga-check --repo refis/KYRiE --description "Needs Auriga load or runtime check" --color F9D0C4 --force
gh label create blocked --repo refis/KYRiE --description "Waiting on external dependency" --color 000000 --force
gh label create P0 --repo refis/KYRiE --description "Capture corruption or data loss risk" --color B60205 --force
gh label create P1 --repo refis/KYRiE --description "Incorrect reconstruction or missing evidence" --color D93F0B --force
gh label create P2 --repo refis/KYRiE --description "Display dictionary or UX" --color 0E8A16 --force
```

既存の `bug` / `enhancement` / `documentation` 等はそのまま使います。
