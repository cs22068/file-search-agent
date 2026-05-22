# File Search Agent 開発ドキュメント

## 1. プロジェクト概要

### 背景・動機
Deploy-Agent（FastMCP × AWS Bedrock × LlamaIndex）の開発記事を参考に、同じ技術スタックを応用して個人用ファイル検索ツールを開発する。

「あのファイルどこだっけ」という状況を解消するため、ファイル名ではなく**内容・文脈で検索できる仕組み**を構築する。

### やりたいこと
自分のPC内のファイル（論文・入試資料・コード・メモなど）を自然言語で検索できるツールを作る。

---

## 2. 要件定義

### 機能要件
- 自然言語でPC内のファイルを検索できる
- ファイル名ではなく**内容・文脈**で検索できる
- 検索結果に参照ファイルのパスを表示する
- ファイルの追加・変更・削除を自動検知してインデックスを更新する
- Claude for Desktopのチャットから検索できる

### 非機能要件
- ベクトルインデックスはローカルに保存（クラウド不要）
- 月のランニングコストは数百円以内
- GPUは不要（Bedrockのサーバー側で処理）
- ノートPCで動作する

### 対象ファイル
- コードファイル（.py, .ts, .js など）
- テキスト・Markdown（.txt, .md）
- 設定ファイル（.json, .yaml など）
- ※PDFは大容量のため今回は除外

### 除外ファイル
- 画像・動画・音声
- 圧縮ファイル・バイナリ
- 依存関係フォルダ（node_modules, venv など）
- Gitの内部ファイル
- 機密情報（.env）

---

## 3. システム設計

### アーキテクチャ

```
あなたのPC
┌─────────────────────────────────────────┐
│                                         │
│  Claude for Desktop                     │
│       ↕ MCP Protocol                   │
│  MCP Server (FastMCP) [server.py]       │
│       ↕                                 │
│  検索エンジン [searcher.py]              │
│       ↕                                 │
│  インデクサー [indexer.py]               │
│       ↕                                 │
│  FAISSインデックス（ローカル保存）        │
│                                         │
└─────────────────────────────────────────┘
         ↕ AWS SDK (boto3)
┌─────────────────────────────────────────┐
│  AWS Bedrock (ap-northeast-1)           │
│  ・Titan Embed Text v2（ベクトル化）     │
│  ・Claude Sonnet 4.6 JP推論プロファイル  │
│    （回答生成）                          │
└─────────────────────────────────────────┘
```

### 技術スタック

| 役割 | 技術 |
|------|------|
| UIフレームワーク | FastMCP |
| RAGフレームワーク | LlamaIndex |
| Embedding | Amazon Titan Embed Text v2 |
| LLM | Claude Sonnet 4.6（JP推論プロファイル） |
| ベクトルDB | FAISS（ローカル保存） |
| ファイル監視 | watchdog |
| インフラ管理 | AWS CDK（TypeScript） |
| 言語 | Python 3.13 |

### データフロー

**インデックス化（初回・差分更新）**
```
PC内ファイル
→ ハッシュ値で差分検出
→ SimpleDirectoryReader でテキスト抽出
→ Titan Embed Text v2 でベクトル化（Bedrock API）
→ FAISS インデックスにローカル保存
→ メタデータ（ハッシュ・更新日時）を JSON で管理
```

**検索時**
```
ユーザーのクエリ（自然言語）
→ Titan Embed Text v2 でベクトル化
→ FAISS で類似チャンク上位5件を取得
→ Claude Sonnet 4.6 が自然言語で回答生成
→ 参照ファイルパスと合わせて返答
```

### プロジェクト構成

```
file-search-agent/
├── cdk/                        # AWS CDK（インフラ管理）
│   ├── bin/
│   │   └── cdk.ts              # CDKエントリーポイント
│   ├── lib/
│   │   └── file-search-stack.ts # IAMリソース定義
│   └── package.json
├── mcp-server/                 # アプリケーション本体
│   ├── server.py               # Phase 4: FastMCP MCPサーバー
│   ├── indexer.py              # Phase 2: インデクサー
│   ├── searcher.py             # Phase 3: 検索エンジン
│   ├── requirements.txt
│   ├── .env                    # 認証情報・設定
│   └── data/
│       ├── index/              # FAISSインデックス（自動生成）
│       └── index_meta.json     # 差分更新用メタデータ
└── venv/                       # Python仮想環境
```

---

## 4. 環境構築

### 前提条件
- Python 3.13
- Node.js（CDK用）
- AWS CLI
- AWS CDK CLI（`npm install -g aws-cdk`）

### Python環境のセットアップ

```powershell
# 仮想環境の作成
cd file-search-agent
python -m venv venv
.\venv\Scripts\Activate.ps1

# ライブラリのインストール
pip install -r mcp-server/requirements.txt
```

### requirements.txt

```
llama-index
llama-index-embeddings-bedrock
llama-index-llms-bedrock
llama-index-llms-bedrock-converse
boto3
faiss-cpu
watchdog
python-dotenv
fastmcp
```

### AWS認証設定

```powershell
aws configure
# AWS Access Key ID: （natorihirofumi_cli のキー）
# AWS Secret Access Key: （シークレットキー）
# Default region name: ap-northeast-1
# Default output format: json
```

### .env の設定

```env
AWS_ACCESS_KEY_ID=（natorihirofumi_cli のアクセスキー）
AWS_SECRET_ACCESS_KEY=（シークレットキー）
AWS_DEFAULT_REGION=ap-northeast-1

TARGET_DIRS=C:/Users/nh200/Cloude_Application_Development/file-search-agent/cdk,C:/Users/nh200/Cloude_Application_Development/file-search-agent/mcp-server
INDEX_DIR=./data/index
META_FILE=./data/index_meta.json
WATCH_ENABLED=true
EMBED_MODEL=amazon.titan-embed-text-v2:0
LLM_MODEL=jp.anthropic.claude-sonnet-4-6
```

---

## 5. AWSインフラ構築（Phase 1） ✅

### CDKでIAMリソースをデプロイ

```powershell
cd cdk
npm install
cdk bootstrap   # 初回のみ
cdk deploy
```

### 作成されるリソース

| リソース | 説明 |
|---------|------|
| IAM User: `file-search-bedrock-user` | Bedrock呼び出し用ユーザー |
| IAM Policy: `FileSearchBedrockPolicy` | Bedrock権限ポリシー |
| IAM Access Key | .envに設定するキー |

> **注意**: 現在は開発中のため`natorihirofumi_cli`（AdministratorAccess）のキーを使用。完成後に`file-search-bedrock-user`のキーに切り替える予定。

### 許可しているBedrockリソース

```
# Embedding
arn:aws:bedrock:ap-northeast-1::foundation-model/amazon.titan-embed-text-v2:0

# LLM（JP推論プロファイル）
arn:aws:bedrock:ap-northeast-1:716287580111:inference-profile/jp.anthropic.claude-sonnet-4-6
```

---

## 6. インデクサー実装（Phase 2） ✅

### 主要機能

**差分更新**
- ファイルのMD5ハッシュ値を`index_meta.json`で管理
- 前回インデックス化以降に変更・追加されたファイルのみ再処理
- 削除されたファイルはインデックスから除外

**watchdog自動監視**
- ファイルの追加・変更・削除・移動を検知
- デバウンス処理（3秒）で連続イベントをまとめて1回の更新に

**ノイズ除外**
- 画像・動画・音声・バイナリを除外
- node_modules・venv・.gitなどを除外
- .env・data/フォルダ自身も除外（無限ループ防止）

**注意点**
- printは全てstderrに出力する（MCPのstdio通信を汚染しないため）
- 絵文字はWindowsのcp932エンコーディングでクラッシュするため使用禁止

### 実行方法

```powershell
cd mcp-server

# 差分更新を1回実行
python indexer.py

# 差分更新後、watchdogで常駐監視
python indexer.py --watch
```

---

## 7. 検索エンジン実装（Phase 3） ✅

### 主要機能
- FAISSインデックスからクエリに類似する上位5件のチャンクを取得
- Claude Sonnet 4.6が自然言語で回答を生成
- 参照したファイルのパスも合わせて返す

### LlamaIndexとboto3の使い分け

LlamaIndexの`BedrockConverse`クラスはJP推論プロファイル（`jp.`プレフィックス）に対応していないため、`CustomLLM`を継承してboto3で直接Converse APIを呼び出すカスタムLLMを実装。

### 実行方法

```powershell
python searcher.py "IAMロールはどこで定義されている？"
python searcher.py "watchdogはどんな処理をしている？"
```

---

## 8. MCPサーバー実装（Phase 4） ✅

### 公開しているMCPツール

| ツール名 | 説明 |
|---------|------|
| `search_files` | 自然言語でPC内ファイルを検索 |
| `reindex_files` | インデックスを手動更新 |
| `index_status` | インデックス状態を確認 |

### 起動時の動作
1. インデックス読み込み
2. 差分更新を1回実行（新しいファイルを即反映）
3. watchdogがバックグラウンドで常時監視開始
4. ファイル変更を検知したら自動でインデックス更新

---

## 9. Claude for Desktop連携（Phase 5） ✅

### 設定ファイルの場所

```
C:\Users\nh200\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json
```

### 設定内容

```json
{
  "mcpServers": {
    "file-search-agent": {
      "command": "C:\\Users\\nh200\\Cloude_Application_Development\\file-search-agent\\venv\\Scripts\\python.exe",
      "args": [
        "C:\\Users\\nh200\\Cloude_Application_Development\\file-search-agent\\mcp-server\\server.py"
      ],
      "env": {
        "AWS_ACCESS_KEY_ID": "...",
        "AWS_SECRET_ACCESS_KEY": "...",
        "AWS_DEFAULT_REGION": "ap-northeast-1",
        "TARGET_DIRS": "...",
        "INDEX_DIR": "...",
        "META_FILE": "...",
        "EMBED_MODEL": "amazon.titan-embed-text-v2:0",
        "LLM_MODEL": "jp.anthropic.claude-sonnet-4-6"
      }
    }
  }
}
```

### 確認方法
Claude for Desktop → Chat → + → コネクタ → `file-search-agent`がONになっていればOK

---

## 10. トラブルシューティング

### Pythonバージョン問題
Inkscapeのpython.exeがPATHに入っていて優先されていた。
→ Windowsの設定アプリからInkscapeのパスを削除して解決。

### OpenAI APIキーエラー
LlamaIndexのデフォルトEmbeddingがOpenAIになっていた。
→ `VectorStoreIndex([], embed_model=embed_model)`のように明示的にembed_modelを渡すことで解決。

### watchdog無限ループ
`data/index_meta.json`の変更をwatchdogが検知→更新→また検知のループ。
→ `IGNORE_PATH_FRAGMENTS`で`\data\`パスのイベントを無視することで解決。

### Bedrockモデルアクセス問題
東京リージョン（ap-northeast-1）のon-demand呼び出し対応モデルはLEGACYのみ。
新しいモデルは推論プロファイル経由が必要だが、`aws-marketplace:Subscribe`権限が必要。
→ AdministratorAccessを持つ`natorihirofumi_cli`のキーを使うことで解決。

### LlamaIndexのJP推論プロファイル非対応
`BedrockConverse`クラスが`jp.`プレフィックスのモデルIDを認識しない。
→ `CustomLLM`を継承してboto3で直接Converse APIを呼び出すカスタムLLMを実装して解決。

### MCPのstdio通信エラー（JSON parse error）
indexer.pyのprintがstdoutに出力され、MCPのJSON通信と混ざってクラッシュ。
→ 全printを`file=sys.stderr`に変更して解決。

### UnicodeEncodeError（絵文字クラッシュ）
`✅`や`⚠`などの絵文字がWindowsのcp932エンコーディングで出力できずクラッシュ。
→ 絵文字を全て削除して解決。

---

## 11. コスト見積もり

| 処理 | モデル | 料金目安 |
|------|--------|---------|
| 初回インデックス化 | Titan Embed Text v2 | 数円（1回のみ） |
| 差分インデックス化 | Titan Embed Text v2 | 追加ファイル分のみ |
| 検索1回 | Claude Sonnet 4.6 | 数円 |
| 月間合計 | - | 数百円以内 |

---

## 12. 今後の予定

- [ ] `file-search-bedrock-user`への権限追加と切り替え
- [ ] 対象ディレクトリの拡張（OneDrive・Documents など）
- [ ] PDFサポートの追加検討


プロジェクト管理のアシスト
引継ぎ　issueとpullリクエスト参照可能
バージョン管理系