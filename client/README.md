# ローカルのクライアント調査資料

クライアントEXEと抽出した長さ定義・抽出レポートを置く作業用フォルダです。
ソースZIP・GitHubには含めません（`.gitignore`で制御）。作業フォルダから削除もしません。

対象例: `*.exe`、`PacketLength.extracted*`、`client_packet.txt`、抽出バイナリ。
このフォルダに置く `README.md` だけがソース管理対象です。
辞書拡充の根拠として読取専用利用してよいが、ファイル本体の持ち出しは禁止。
詳細は[クライアント資料計画](../docs/development/client-data-utilization-plan.md)。

`PacketLength.extracted.txt`があると取得定義の既定で優先されます。
新しいクライアントへ変更する際は、版・EXEハッシュ・抽出レポート・差分を確認し、
GUIで選択された定義を確認してください。未知IDから自動で書き換える機能はありません。
