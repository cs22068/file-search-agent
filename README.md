# File Search Agent 開発

## 1. プロジェクト概要

### 背景・動機
Deploy-Agent（FastMCP × AWS Bedrock × LlamaIndex）の開発記事を参考に、同じ技術スタックを応用して個人用ファイル検索ツールを開発する。

特にエクスプローラーについて「あのファイルどこだっけ」という状況を解消するため、ファイル名だけではなく**内容・文脈で検索できる仕組み**を構築する。

参考記事：[[Deploy-Agent開発 Vol.1] FastMCP × AWS Bedrockで「コードとドキュメントを読んで勝手にデプロイ計画を立てるAI」を作ってみた](https://qiita.com/kz-ow/items/ec9d115421e5a3da9076)

### やりたいこと
自分のPC内のファイルを自然言語で検索できるツールを作る。

**注意：**
PDFなどの大容量ファイルはインデックス化に時間がかかるため、現在は比較的容量が小さいテキストベースのファイルを対象としている。対象ファイルの詳細は要件定義を参照。

## 2. 要件定義

### 機能要件
- 自然言語でPC内のファイルを検索可能
- ファイル名だけでなく、**内容・文脈**で検索可能
- ファイルの追加・変更・削除を自動検知してインデックスを更新する
- Claude for Desktopのチャットから検索できる

### 非機能要件
- ベクトルとインデックスはローカルに保存
- GPU不要でノートPCで動作する

### 対象ファイル
- コードファイル（.py, .ts, .js など）
- テキスト・Markdown（.txt, .md）
- 設定ファイル（.json, .yaml など）
- （※PDFなどは大容量のため今回は除外）

### 除外ファイル
- 画像・動画・音声
- 圧縮ファイル・バイナリ
- 依存関係フォルダ（node_modules, venv など）
- Gitの内部ファイル
- 非公開情報（.env）

---

## 3. システム設計

### アーキテクチャ

---

### 技術スタック

| 技術 | 役割 |
|------|------|
| AWS CDK（TypeScript） | インフラ管理（IAMリソース定義） |
| Python 3.13.5 | 開発言語 |
| FastMCP | UIフレームワーク（MCPサーバー） |
| LlamaIndex | RAGフレームワーク（ベクトル検索・インデックス管理） |
| FAISS | ベクトルデータベース（ローカル保存） |
| Amazon Bedrock - Titan Embed Text v2 | Embeddingモデル（テキストのベクトル化） |
| Amazon Bedrock - Claude Sonnet 4.6（JP推論プロファイル経由） | LLM（自然言語での回答生成） |


### プロジェクト構成

```
file-search-agent/
├── cdk/                         # AWS CDK（インフラ管理）
│   ├── bin/
│   │   └── cdk.ts               # CDKエントリーポイント
│   ├── lib/
│   │   └── file-search-stack.ts # IAMリソース定義
│   └── package.json
├── mcp-server/                  # アプリケーション本体
│   ├── server.py                # MCPサーバー
│   ├── indexer.py               # インデクサー
│   ├── searcher.py              # 検索エンジン
│   ├── requirements.txt
│   ├── .env                     # 認証情報・設定
│   └── data/
│       ├── index/               # FAISSインデックス（自動生成）
│       └── index_meta.json      # 差分更新用メタデータ
└── venv/                        # Python仮想環境
```
---

## 4. 環境構築

#### Node.jsのインストール
```
sudo apt update
sudo apt install -y curl unzip
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
```
#### 確認
```
node -v
  v22.14.0
```

#### AWS CLIv2のインストール
```
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
```
#### 確認
```
aws --version
  aws-cli/2.24.20 Python/3.12.9 Windows/11 exe/AMD64
```

#### AWS CDKのインストール
```
sudo npm install -g aws-cdk
```
#### 確認
```
cdk --version
  2.1122.0 (build c8f270c)
```

### Python環境のセットアップ

```powershell
# 仮想環境の作成
python -m venv venv
.\venv\Scripts\Activate

# ライブラリのインストール
pip install -r requirements.txt
```

### AWS認証設定

```
aws configure

# AWS Access Key ID: <アクセスキー>
# AWS Secret Access Key: <シークレットキー>
# Default region name: <リージョン名>
# Default output format: json
```
---

## 5. AWSインフラ構築

### CDKでIAMリソースをデプロイ

```
cd cdk
npm install
cdk deploy
```

### 作成されるリソース

| リソース | 説明 |
|---------|------|
| IAM User: `file-search-bedrock-user` | Bedrock呼び出し用ユーザー |
| IAM Policy: `FileSearchBedrockPolicy` | Bedrock権限ポリシー |
| IAM Access Key | .envに設定するキー |

### 許可しているBedrockリソース

```
# Embeddingモデル
arn:aws:bedrock:ap-northeast-1::foundation-model/amazon.titan-embed-text-v2:0

# LLM（JP推論プロファイル）
arn:aws:bedrock:ap-northeast-1:716287580111:inference-profile/jp.anthropic.claude-sonnet-4-6

# ルーティング先のモデル
'arn:aws:bedrock:ap-northeast-1::foundation-model/anthropic.claude-sonnet-4-6',
'arn:aws:bedrock:ap-northeast-3::foundation-model/anthropic.claude-sonnet-4-6',
```

### デプロイ後の.env の設定

```env
AWS_ACCESS_KEY_ID=<`file-search-bedrock-user`のアクセスキー>
AWS_SECRET_ACCESS_KEY=<`file-search-bedrock-user`のシークレットキー>
AWS_DEFAULT_REGION=<リージョン名>

TARGET_DIRS=<デフォルトで指定するパス>
INDEX_DIR=./data/index
META_FILE=./data/index_meta.json
WATCH_ENABLED=true
EMBED_MODEL=amazon.titan-embed-text-v2:0
LLM_MODEL=jp.anthropic.claude-sonnet-4-6
```
---

## 6. インデクサー: indexer.py

### 主要機能

**差分更新**
- ファイルのMD5ハッシュ値を `index_meta.json` で管理
- 前回インデックス化以降に変更・追加されたファイルのみ再処理
- 削除されたファイルはインデックスから除外

**watchdogによる自動監視**
- ファイルの追加・変更・削除・移動をリアルタイム監視

### 実行方法

```
cd mcp-server

# 差分更新を1回実行
python indexer.py

# 差分更新後、watchdogでリアルタイム監視
python indexer.py --watch
```
---

## 7. 検索エンジン: search.py

### 主要機能
- FAISSインデックスからクエリに類似する上位5件のチャンクを取得
- Amazon Bedrockが自然言語で回答を生成
- 参照したファイルのパスも合わせて返す

### 実行方法

```
python searcher.py "IAMロールはどこで定義されている？"
python searcher.py "watchdogはどんな処理をしている？"
```
---

## 8. MCPサーバー

### 主要機能

| ツール名 | 説明 |
|---------|------|
| `search_files` | （メイン）自然言語でPC内ファイルを検索（デフォルトのパスまたは指定パス） |
| `reindex_files` | （仮）インデックスを手動更新 |
| `index_status` | （仮）インデックス状態を確認 |

### search_filesの使い方

**1. デフォルトディレクトリから検索**
```
エクスプローラーについて IAMロールの定義を探して
```

**2. 特定のディレクトリを指定して検索**
```
エクスプローラーについて "C:/Users/Documents" の中からPythonコードを検索
```

**3. 複数ディレクトリを指定**
```
エクスプローラーについて "C:/Projects,C:/Documents" から機械学習のファイルを探して
```

**重要な注意点：**
- 必ず「エクスプローラーについて」というキーワードを付けてください
- ダブルクォート `"パス"` で囲むと、そのディレクトリ専用のインデックスが作成されます
- パスを指定しない場合は、.envの `TARGET_DIRS` が使用されます
---

## 9. Claude for Desktop連携

### 設定ファイルの場所

Claude for Desktopを開く → ハンバーガーボタン → ファイル → 設定 → 開発者 → 設定を編集

エクスプローラーが開くので、`claude_desktop_config.json` を開く

### 以下の内容を張り付け

```json
{
  "mcpServers": {
    "file-search-agent": {
      "command": "C:\\Users\\~\\file-search-agent\\venv\\Scripts\\python.exe",
      "args": [
        "C:\\Users\\~\\file-search-agent\\mcp-server\\server.py"
      ],
      "env": {
        "AWS_ACCESS_KEY_ID": "<`file-search-bedrock-user`のアクセスキー>",
        "AWS_SECRET_ACCESS_KEY": "<`file-search-bedrock-user`のシークレットキー>",
        "AWS_DEFAULT_REGION": "<リージョン名>",
        "TARGET_DIRS": "<デフォルトで指定するパス>",
        "INDEX_DIR": "./data/index",
        "META_FILE": "./data/index_meta.json",
        "EMBED_MODEL": "amazon.titan-embed-text-v2:0",
        "LLM_MODEL": "jp.anthropic.claude-sonnet-4-6"
      }
    }
  }
}
```

### 確認方法
Claude for Desktop → Chat → + → コネクタ → `file-search-agent` がONになっていればOK

### 起動時の動作
1. インデックス読み込み
2. 差分更新を1回実行（バックグラウンドで実行、タイムアウト防止）
3. watchdogがバックグラウンドで常時監視開始
4. ファイル変更を検知したら自動でインデックス更新（デバウンス3秒）
---

## 10. 使用例

### Claude for Desktopでの検索例

**例1: デフォルトディレクトリから検索**
```
エクスプローラーについて watchdogの処理を教えて
```
→ .envの`TARGET_DIRS`で指定されたディレクトリから検索

**例2: 特定のプロジェクトフォルダを検索**
```
エクスプローラーについて "C:/Users/~" の構成を教えて
```
→ 指定したディレクトリ専用の一時インデックスを作成して検索

**例3: 複数のフォルダを横断検索**
```
エクスプローラーについて "C:/Projects/A,C:/Projects/B" からReactコンポーネントを探して
```
→ 複数ディレクトリをカンマ区切りで指定

### インデックス管理

**インデックス状態の確認**
```
index_statusを実行して
```
→ インデックス済みファイル数と最終更新日時を表示

**手動でインデックス更新**
```
reindex_filesを実行して
```
→ 通常は自動更新されるが、強制的に更新したい場合に使用

---

## 11. 今後の予定

- [ ] 対象ディレクトリの拡張（OneDrive・Documents など）
- [ ] PDFサポートの追加検討
- [ ] チャンク分割サイズの最適化（現在256文字）
- [ ] 検索結果の上位件数を可変にする機能（現在5件固定）