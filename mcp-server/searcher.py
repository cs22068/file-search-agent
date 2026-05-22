"""
FAISSインデックスに対してクエリを投げ、
boto3でBedrockを直接呼び出して自然言語で回答を生成する。
LlamaIndexのBedrockConverseを使わないことでJP推論プロファイルに対応。
"""
import os
import sys
import boto3
import faiss
from pathlib import Path
from dotenv import load_dotenv

from llama_index.core import (
    StorageContext,
    load_index_from_storage,
    Settings as LlamaSettings,
)
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.llms import CustomLLM, CompletionResponse, LLMMetadata
from llama_index.core.llms.callbacks import llm_completion_callback
from llama_index.embeddings.bedrock import BedrockEmbedding
from llama_index.vector_stores.faiss import FaissVectorStore

load_dotenv() # .envファイルから環境変数を読み込む

# ============================================================
# 設定
# ============================================================
INDEX_DIR   = Path(os.getenv("INDEX_DIR", "./data/index"))
REGION      = os.getenv("AWS_DEFAULT_REGION", "ap-northeast-1")
EMBED_MODEL = os.getenv("EMBED_MODEL", "amazon.titan-embed-text-v2:0")
LLM_MODEL   = os.getenv("LLM_MODEL", "jp.anthropic.claude-sonnet-4-6")

# ============================================================
# ログ出力（MCPのstdioを汚染しないようにstderrに出力）
# ============================================================
def log(msg: str):
    print(msg, file=sys.stderr, flush=True)

# ============================================================
# boto3でBedrockを直接呼び出すカスタムLLM
# LlamaIndexのBedrockConverseはJP推論プロファイル非対応のため自作
# ============================================================
class BedrockDirectLLM(CustomLLM):

    model_id: str = LLM_MODEL
    region: str = REGION
    max_tokens: int = 2048

    # LLMの仕様に合わせて、モデルのコンテキストウィンドウや出力トークン数をメタデータとして提供
    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(
            context_window=200000,
            num_output=self.max_tokens,
            model_name=self.model_id,
        )

    # LLMの仕様に合わせて、boto3でBedrockを呼び出す
    # @llm_completion_callbackデコーダーを使うことで、ログ管理やエラー処理が自動で行われる
    @llm_completion_callback()
    def complete(self, prompt: str, **kwargs) -> CompletionResponse:
        client = boto3.client(
            "bedrock-runtime",
            region_name=self.region,
        )
        response = client.converse(
            modelId=self.model_id,
            messages=[
                {"role": "user", "content": [{"text": prompt}]}
            ],
            inferenceConfig={
                "maxTokens": self.max_tokens,
                "temperature": 0.1,
            },
        )
        text = response["output"]["message"]["content"][0]["text"]
        return CompletionResponse(text=text)

    # 今回はストリーミング非対応のため、completeのみ実装し、stream_completeは未実装のまま
    @llm_completion_callback()
    def stream_complete(self, prompt: str, **kwargs):
        raise NotImplementedError("streaming is not supported")


# ============================================================
# 初期化
# ============================================================
def init_models():
    LlamaSettings.embed_model = BedrockEmbedding(
        model_name=EMBED_MODEL,
        region_name=REGION,
    )
    LlamaSettings.llm = BedrockDirectLLM(
        model_id=LLM_MODEL,
        region=REGION,
    )
    LlamaSettings.node_parser = SentenceSplitter(
        chunk_size=256,
        chunk_overlap=32,
    )

def _load_query_engine():
    if not (INDEX_DIR / "docstore.json").exists():
        return None

    faiss_file = INDEX_DIR / "faiss.index"
    faiss_index = faiss.read_index(str(faiss_file))
    vector_store = FaissVectorStore(faiss_index=faiss_index)
    storage = StorageContext.from_defaults(
        vector_store=vector_store,
        persist_dir=str(INDEX_DIR)
    )
    index = load_index_from_storage(storage)
    return index.as_query_engine(
        similarity_top_k=5,
        response_mode="compact",
    )

# ============================================================
# メインクラス
# ============================================================
class FileSearcher:

    def __init__(self):
        init_models()
        self._query_engine = None

        if (INDEX_DIR / "docstore.json").exists():
            log("[Searcher] インデックスを読み込み中...")
            self._query_engine = _load_query_engine()
            log("[Searcher] 準備完了")
        else:
            log("[Searcher] インデックスなし。バックグラウンドで作成中...")

    def _ensure_query_engine(self) -> bool:
        """クエリエンジンが使えるか確認。なければ再ロードを試みる"""
        if self._query_engine is not None:
            return True
        if (INDEX_DIR / "docstore.json").exists():
            log("[Searcher] インデックスが完成しました。読み込み中...")
            self._query_engine = _load_query_engine()
            log("[Searcher] 準備完了")
            return True
        return False

    def search(self, query: str) -> str:
        if not self._ensure_query_engine():
            return "インデックスを作成中です。しばらく待ってから再度お試しください。"

        log(f"[Searcher] クエリ: {query}")
        response = self._query_engine.query(query)

        sources = self._extract_sources(response)
        answer = str(response)

        if sources:
            answer += "\n\n参照ファイル:\n" + "\n".join(f"  - {s}" for s in sources)

        return answer

    def _extract_sources(self, response) -> list[str]:
        sources = []
        seen = set()
        for node in response.source_nodes:
            path = node.metadata.get("file_path") or node.node.ref_doc_id or ""
            if path and path not in seen:
                seen.add(path)
                sources.append(path)
        return sources


# ============================================================
# CLI エントリーポイント
# python searcher.py "IAMロールはどこで定義されている？"
# ============================================================
if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "このプロジェクトの構成を教えて"

    searcher = FileSearcher()
    result = searcher.search(query)
    print("\n===== 回答 =====")
    print(result)