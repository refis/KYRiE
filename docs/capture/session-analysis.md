# 保存ログを一度再生してまとめて解析する

[資料一覧へ](../README.md) · [プロジェクトREADME](../../README.md)

```powershell
python -m tools.analyze_session logs/20261027-193248-fcdc039c/capture.jsonl --definitions logs/20261027-193248-fcdc039c/PacketLength.used.txt --output logs/20261027-193248-fcdc039c/session-analysis.json
python -m tools.analyze_session logs/SESSION/capture.jsonl --definitions logs/SESSION/PacketLength.used.txt --output logs/SESSION/session-rathena.json --emulator rathena
```

GUIと同じ順序でWorld、MOB配置、ショップ、戦闘、スキル、プレイヤー、会話を更新する。
生ログの再生は1回。全分野で共通のパケット番号を使い、既存の分野別解析コマンドも利用できる。

`--emulator auriga|rathena`（既定`auriga`）で生成プロファイル根（`config/<emulator>/`）を切り替える。
`analyze_dialogues` / `merge_dialogues` / `analyze_entities` / `analyze_skills` /
`compare_dialogue_timing` も同じフラグを持つ。観測意味の抽出は共通で、本文候補・配置候補の
書式だけが変わる。受信表示JSONのCLI切替は対象外（GUIの表示形式を使う）。

レポートにはNPC/MOB個体、プレイヤー・キャラクタ情報、会話と会話外演出、
ショップ、戦闘・スキル、MOB配置観測と未確定の配置候補、統合会話とAuriga本文候補を含む。
手動採用していないNPCタイマーやMOB配置設定は生成しない。
会話外演出は時刻・対象・根拠付きで保持するが、反復比較の基準点は利用者がGUIで選択する。

`emulator`は適用した生成プロファイル名。source_sha256は元ログ、definitions_sha256は後方優先を適用した長さ定義の正規化SHA256、
dialogue_profileは会話生成書式のパスとSHA256。ログ・生成書式の解析中の変更は検出して拒否する。
生ログは128MiBまで、出力JSONは64MiBまで。元ログ・指定定義・config以下への上書きは禁止し、
出力は一時ファイルへ書込後に置換する。元のキャプチャログは変更しない。

replayには停止接続・残った未完ストリーム・TCP診断を保持する。
transport_quality=not_verifiedは、実際の欠損やレイアウト互換性を確定していないという意味。
停止ゼロを取得完全とみなさない。各分野の問題・容量到達フラグも確認する。

## 品質サマリー

qualityは既存の各分野の根拠を変更せず、次をまとめる。

- 取得停止・未完ストリーム・session_end欠落・TCP診断なし・途中取得境界・SYN待ち。
- World／キャラクタ／会話／ショップ／戦闘／スキルの解析問題。
- 容量到達、保留名の退避、演出の保存上限による欠落。
- 個別会話の問題とタイムライン品質フラグ、反復演出の不一致。
- 統合除外、統合入力上限、コード生成エラー。

findingsにはsection・code・countを置き、元の根拠は対応する分野のJSONへ残す。
同じ原因が複数の項目へ現れる場合があるため、countを合算して障害件数とは扱わない。
未帰属のスキル・攻撃通知数も別欄へ保持し、原因をNPC/MOBの欠損と断定しない。
異なる演出の観測や途中取得も確認対象になるため、review_requiredはソフトウェア故障を意味しない。

findingsがあればstatus=review_required、なければno_reported_issues。
どちらもcapture_completeness=not_verifiedを維持する。
このサマリーで元の会話や生成結果を自動削除・書換えしない。
CLIにも状態と項目数を表示する。各分野の問題一覧は保存上限があるため、issue_countと
保存されたissuesの配列長が一致しない場合は全件が掲載されているとは見なさない。

dialogue_reviewは統合から除外された会話の確認用一覧。
会話ID、取得世代、NPC・マップ、状態、除外理由・品質フラグ、先頭／末尾Packet番号、出典を保持する。
元の会話本文を補完したり、除外を自動解除したりしない。
skill_cast_reviewは既存の詠唱開始と後続通知の対応候補、未観測状態と根拠Packetを保持する。
新たな対応付けや詠唱成功・実詠唱時間の判定は行わない。
GUIの「会話・コード → 統合除外の確認」でも同じ一覧を表示し、
行を選んで「選択項目の会話・先頭根拠を開く」、またはダブルクリックで移動できる。
開始未観測は開始条件不明、取消しは観測された操作、中断は観測範囲の限界として区別して確認する。

measurementsのpacket_countは全送受信パケット件数、replay_secondsは再生と意味解析、
total_secondsは入力ハッシュ・再生・集計・会話生成を含む。JSON整形・出力I/Oとプロセス起動時間は含まない。
処理時間は実行PCや同時負荷で変わる。GUI描画性能・長時間取得性能を示す数値ではない。

合成ログで個別解析と会話・個体・プレイヤー・スキル・統合コードの一致、
入力変更の拒否、保存失敗時の既存レポート保持と元ログ保護を検証した。
実ログでも複数分野の一致を確認。Auriga本体での候補実行検証は別途必要。


## 20261029追加ログの確認結果

対象: 20261029-215033-0a6328fa。入力発言・選択肢・会話タイムアウトの検証用。
PacketLength.used.txtを使い、15,472パケット（SEND880／RECV14,592）、27接続を再生した。
フレーミングエラー・未完ストリームは0、会話20件・統合10群、生成エラー0。
元ログのSHA-256を解析前後に照合し、生データ・定義を変更していない。

確認結果:

- 本人の入力発言2件をSEND→RECVへ一意に照合。末尾NULなし形式への修正を含む。
- 会話1/2/3は3選択肢を全て観測して1群へ統合。4と14は選択値255による中断側で、未完として除外。
- 会話17/19/13/18の統合はwhile1個・continue1個・switch1個。別の反復メニュー群もwhile/continueを生成。
- 会話6はmenu待ち、18はnext待ちでtimeout_suspected。6→正常会話5、18→正常会話17の前方一致により
  timeout_close_removed_prefix_matchで統合し、元の終了根拠を保持する。経過秒によるタイムアウト確定はしない。
- 数値／文字inputのタイムアウトや、本人発言の同文多重候補を実データで確認したとは扱わない。

修正後の会話解析issuesは0。ただし09FF出現名のCP932解読警告6件、タイムラインの
重複要求注意2件と観測開始不足1件、中断会話の除外2件が残る。
quality=review_required、capture_completeness=not_verifiedを維持する。生成成功はAuriga動作確認ではない。

当該ログフォルダへ次を保存した。

- session-analysis-initial-review.json: 修正前の解析結果。
- session-analysis-verified-review.json: 修正後の総合解析と全根拠。
- player-speech-audit-verified.json: 本人入力のSEND関連候補。
- validation-summary.json: Packet数・入力照合・統合群・未応答終了正規化・残注意の確認結果。
- merged-dialogues-reviewed.txt: 統合会話本文10群。未観測項目を補完しない編集用候補。

本人宛て頭上通知は旧ログ20261028-012526-0abe69d9の0x08B3で3件確認した。
実バイトによる発言形式回帰を追加し、発言・選択保存・GUI・タイムアウト・whileの関連22項目を選択して確認。
全件テスト、Auriga読込／実行試験は行っていない。


### 出現名警告の追加点検

同ログの6件は、09FFの名前領域23バイトの末尾にCP932先行バイトだけが残っていた。
不完全名の参考診断を追加した再解析はsession-analysis-name-diagnostics-review.json、
対象6件の根拠はspawn-name-diagnostics.jsonへ保存した。
正式名を推定せず、元ログと全10群の生成会話を変更していない。quality=review_requiredを維持する。
詳細は[不完全な出現名](../observations/entity-observations.md#末尾のcp932文字が途切れた出現名)を参照。


### 未応答終了タイムラインの追加点検（2026-10-30）

会話6(menu待ち)・18(next待ち)の重複要求注意は、サーバーcloseが未応答要求を置き換える際の分類不足だった。
元要求の未完了waitを保持し、品質フラグとGUI区間をunanswered_terminationへ修正した。
反復候補には含めず、正常側統合と統合本文10群は不変であることを確認した。
再解析はsession-analysis-unanswered-wait-review.json、2件の根拠はunanswered-wait-validation.json。
品質は引き続きreview_required。問題なしへ変更したのではなく、元要求と終了の関係を明示した。
関連16項目を選択して確認。全件テスト・Auriga実行は行っていない。


### 会話開始未観測のOnTouch候補（2026-10-30）

会話10はクリックなしでclass45 NPC付近からwarpした観測。NPC候補1体・歩行先・MAP移動が対応し、
配置付き出力はwarp型で統合ON/OFF一致。歩行到着や接触範囲の確定ではない。
OnTouch候補の画面説明を追加したが、start_unobservedと反復集計除外は維持する。
touch-warp-review.jsonとtouch-warp-reviewed.txtを当該フォルダへ保存。対象16項目を選択して確認。
これで名前警告・未応答終了・クリック開始なしの各注意の意味を点検できたが、通信完全性やAuriga実行は未確認。


## 所持品一覧の構造診断

`python -m tools.audit_inventory LOG --output REPORT` で0B09/0B0A/0B38/0B39の受信一覧だけを集計する。
標準はLOGと同じフォルダのPacketLength.used.txt。--definitionsでのみ変更できる。
生ログ・定義のSHA-256を開始時と終了時に照合し、書換えがあれば停止する。
元ログ・定義・configへの出力を拒否する。レポート保存は既存の一時ファイル置換を用いる。
Index/ID/数量、鑑定状態の確認状況、元レコードhex、パケット番号・接続・時刻を記録する。
所持品以外のinventory typeと不正レコードは別集計。PlayerStoreや生成コードは更新しない。
未確認0B38のフラグ位置を推定しない。件数・抽出上限・省略数を必ず確認する。
確認済み／未確認の表は[所持品観測の検証境界](../observations/player-observations.md#一覧ストライドと鑑定フラグの検証境界48)。


### 会話解析CLIの入力保護（2026-10-30）

`tools.analyze_dialogues`も共通の原子保存へ統一。出力先が元ログ・長さ定義・configなら解析前に拒否する。
生ログは128MiB、行は2Mi文字までとし、解析前後のSHA-256が異なる場合は結果を返さない。
CLIでは長さ定義も前後照合し、保存失敗時は既存レポートを保持する。
source_sha256は元ログ、definitions_file_sha256は元定義ファイル、definitions_sha256は既存の正規化定義ハッシュ。
元の会話・統合・タイムラインと数値命令の生成方式は変更しない。
