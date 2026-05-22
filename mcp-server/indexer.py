"""
PC内のファイルをベクトル化してFAISSインデックスに保存する。

機能:
  - 初回インデックス作成
  - チャンク単位の差分更新（変更チャンクのみ再ベクトル化）
  - watchdog による自動監視（バックグラウンド常駐）
"""
import os
import sys
import json
import hashlib
import time
import faiss
import threading
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

from llama_index.core import (
    VectorStoreIndex,
    StorageContext,
    load_index_from_storage,
    Settings as LlamaSettings,
)
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import Document, TextNode
from llama_index.embeddings.bedrock import BedrockEmbedding
from llama_index.vector_stores.faiss import FaissVectorStore
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

load_dotenv()

# ============================================================
# 設定
# ============================================================
TARGET_DIRS = [d.strip() for d in os.getenv("TARGET_DIRS", "").split(",") if d.strip()]
INDEX_DIR   = Path(os.getenv("INDEX_DIR", "./data/index"))
META_FILE   = Path(os.getenv("META_FILE", "./data/index_meta.json"))
REGION      = os.getenv("AWS_DEFAULT_REGION", "ap-northeast-1")
EMBED_MODEL = os.getenv("EMBED_MODEL", "amazon.titan-embed-text-v2:0")

EXCLUDE_PATTERNS = [
    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.bmp", "*.webp", "*.ico", "*.svg",
    "*.mp3", "*.mp4", "*.wav", "*.mov", "*.avi", "*.flac", "*.aac",
    "*.zip", "*.tar", "*.gz", "*.7z", "*.rar",
    "*.exe", "*.dll", "*.so", "*.dylib", "*.bin",
    "*.ttf", "*.otf", "*.woff", "*.woff2",
    "*.pdf", "*.xls", "*.xlsx", "*.ppt", "*.pptx",
    "*.pyc", "*.pyo", "__pycache__",
    ".git", ".svn", ".hg",
    "node_modules", "venv", ".venv", "env",
    "dist", "build", ".next", "out", "target",
    ".vscode", ".idea", "*.suo",
    ".DS_Store", "Thumbs.db", "desktop.ini",
    ".env", ".env.local", ".env.production",
    "package-lock.json", "yarn.lock", "poetry.lock",
    "data",
]

IGNORE_PATH_FRAGMENTS = [
    "\\data\\", "/data/",
    "\\.git\\", "/.git/",
    "\\__pycache__\\", "/__pycache__/",
]

# ============================================================
# ログ出力（MCPのstdioを汚染しないようにstderrに出力）
# ============================================================
def log(msg: str):
    print(msg, file=sys.stderr, flush=True)

# ============================================================
# Bedrock Embedding の初期化
# ============================================================
def init_embedding() -> BedrockEmbedding:
    embed_model = BedrockEmbedding(
        model_name=EMBED_MODEL,
        region_name=REGION,
    )
    LlamaSettings.embed_model = embed_model
    LlamaSettings.node_parser = SentenceSplitter(
        chunk_size=256,
        chunk_overlap=32,
    )
    return embed_model

# ============================================================
# メタデータ管理
# meta[path] = {
#   "chunks": {"0": "hash0", "1": "hash1", ...},
#   "node_ids": {"0": "node_id0", "1": "node_id1", ...},
#   "last_indexed": "2026-..."
# }
# ============================================================
def load_meta() -> dict:
    if META_FILE.exists():
        with open(META_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_meta(meta: dict):
    META_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

def chunk_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()

# ============================================================
# インデックスの読み込み or 新規作成
# ============================================================
def load_or_create_index(embed_model: BedrockEmbedding) -> VectorStoreIndex:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    faiss_file = INDEX_DIR / "faiss.index"
    
    if (INDEX_DIR / "docstore.json").exists() and faiss_file.exists():
        log("[Indexer] 既存FAISSインデックスを読み込み中...")
        # FAISSインデックスを読み込み
        faiss_index = faiss.read_index(str(faiss_file))
        vector_store = FaissVectorStore(faiss_index=faiss_index)
        storage = StorageContext.from_defaults(
            vector_store=vector_store,
            persist_dir=str(INDEX_DIR)
        )
        return load_index_from_storage(storage)
    else:
        log("[Indexer] 新規FAISSインデックスを作成中...")
        # 1024次元（Titan Embed v2の次元数）
        faiss_index = faiss.IndexFlatL2(1024)
        vector_store = FaissVectorStore(faiss_index=faiss_index)
        storage = StorageContext.from_defaults(vector_store=vector_store)
        return VectorStoreIndex([], storage_context=storage, embed_model=embed_model)

# ============================================================
# メインクラス
# ============================================================
class FileIndexer:

    def __init__(self):
        embed_model  = init_embedding()
        self.index   = load_or_create_index(embed_model)
        self.meta    = load_meta()

    def update(self):
        log(f"[Indexer] 差分スキャン開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        current_files: set[str] = set()
        for target_dir in TARGET_DIRS:
            if not Path(target_dir).exists():
                log(f"[Indexer] ディレクトリが見つかりません: {target_dir}")
                continue
            for path in Path(target_dir).rglob("*"):
                if path.is_file() and not self._is_excluded(path):
                    current_files.add(str(path))

        to_remove = [p for p in self.meta if p not in current_files]
        to_process = list(current_files)

        log(f"[Indexer] 処理対象: {len(to_process)} 件, 削除: {len(to_remove)} 件")

        if to_remove:
            self._remove_from_index(to_remove)
            for p in to_remove:
                self.meta.pop(p, None)

        if to_process:
            self._update_files_by_chunks(to_process)

        save_meta(self.meta)
        log(f"[Indexer] 差分更新完了 (合計 {len(current_files)} ファイル管理中)")

    def _update_files_by_chunks(self, file_paths: list[str]):
        changed = False

        for path in file_paths:
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                # 空ファイルをスキップ
                if not content.strip():
                    log(f"[Indexer] {Path(path).name}: 空ファイル（スキップ）")
                    continue

                # チャンク分割
                # Documentでは、1つのファイル全体を1ドキュメントとして扱う
                doc = Document(text=content, id_=path)
                
                # チャンク分割してノードを作成
                nodes = LlamaSettings.node_parser.get_nodes_from_documents([doc])

                # チャンクが生成されない場合もスキップ
                if not nodes:
                    log(f"[Indexer] {Path(path).name}: チャンクなし（スキップ）")
                    continue

                # 新しいチャンクハッシュを計算
                new_hashes = {str(i): chunk_hash(node.text) for i, node in enumerate(nodes)}

                # 既存のメタデータから古いハッシュとnode_idsを取得
                old_meta   = self.meta.get(path, {})
                old_hashes = old_meta.get("chunks", {})
                old_ids    = old_meta.get("node_ids", {})

                # 変更チャンクを特定
                changed_indices = [
                    i for i, node in enumerate(nodes)
                    if new_hashes[str(i)] != old_hashes.get(str(i))
                ]

                # チャンク数も変わっていない＆変更なし → スキップ
                if not changed_indices and len(nodes) == len(old_hashes):
                    log(f"[Indexer] {Path(path).name}: 変更なし（スキップ）")
                    continue

                log(f"[Indexer] {Path(path).name}: {len(changed_indices)}/{len(nodes)} チャンク変更")

                # 変更チャンクの古いノードをインデックスから削除
                for i in changed_indices:
                    old_node_id = old_ids.get(str(i))
                    if old_node_id:
                        try:
                            self.index.delete_nodes([old_node_id])
                        except Exception:
                            pass

                # 変更チャンクのみ再ベクトル化して追加
                new_ids = dict(old_ids)  # 既存IDを引き継ぐ
                for i in changed_indices:
                    node = nodes[i]
                    node_id = f"{path}_chunk_{i}_{new_hashes[str(i)][:8]}"
                    log(f"[Indexer]   ベクトル化中: {Path(path).name} チャンク{i}")
                    embedding = LlamaSettings.embed_model.get_text_embedding(node.text)
                    new_node = TextNode(
                        text=node.text,
                        id_=node_id,
                        embedding=embedding,
                        metadata={
                            "file_path": path,
                            "file_name": Path(path).name,
                            "chunk_index": i,
                        },
                        ref_doc_id=path,
                    )
                    self.index.insert_nodes([new_node])
                    new_ids[str(i)] = node_id

                # メタデータ更新
                self.meta[path] = {
                    "chunks":       new_hashes,
                    "node_ids":     new_ids,
                    "last_indexed": datetime.now().isoformat(),
                }
                changed = True

            except Exception as e:
                log(f"[Indexer] エラー ({path}): {e}")

        if changed:
            self.index.storage_context.persist(persist_dir=str(INDEX_DIR))
            # FAISSインデックスを保存
            faiss.write_index(
                self.index.vector_store.client,
                str(INDEX_DIR / "faiss.index")
            )
            log("[Indexer] インデックスを保存しました")

    def _remove_from_index(self, paths: list[str]):
        log("[Indexer] 削除されたファイルをインデックスから除外中...")
        removed = 0
        for path in paths:
            old_ids = self.meta.get(path, {}).get("node_ids", {})
            if old_ids:
                try:
                    self.index.delete_nodes(list(old_ids.values()))
                    removed += 1
                except Exception as e:
                    log(f"[Indexer] 削除エラー ({path}): {e}")
        if removed:
            self.index.storage_context.persist(persist_dir=str(INDEX_DIR))
            # FAISSインデックスを保存
            faiss.write_index(
                self.index.vector_store.client,
                str(INDEX_DIR / "faiss.index")
            )
        log(f"[Indexer] {removed} 件を除外しました")

    def _is_excluded(self, path: Path) -> bool:
        name = path.name
        for pattern in EXCLUDE_PATTERNS:
            if pattern.startswith("*."):
                if name.endswith(pattern[1:]):
                    return True
            else:
                if pattern in path.parts:
                    return True
        return False


# ============================================================
# watchdog ハンドラー
# ============================================================
class IndexUpdateHandler(FileSystemEventHandler):

    def __init__(self, indexer: FileIndexer):
        self.indexer = indexer
        self._debounce_timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def _should_ignore(self, path: str) -> bool:
        return any(fragment in path for fragment in IGNORE_PATH_FRAGMENTS)

    def _schedule_update(self):
        with self._lock:
            if self._debounce_timer:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(3.0, self.indexer.update)
            self._debounce_timer.start()

    def on_created(self, event):
        if not event.is_directory and not self._should_ignore(event.src_path):
            log(f"[Watcher] 追加を検知: {event.src_path}")
            self._schedule_update()

    def on_modified(self, event):
        if not event.is_directory and not self._should_ignore(event.src_path):
            log(f"[Watcher] 変更を検知: {event.src_path}")
            self._schedule_update()

    def on_deleted(self, event):
        if not event.is_directory and not self._should_ignore(event.src_path):
            log(f"[Watcher] 削除を検知: {event.src_path}")
            self._schedule_update()

    def on_moved(self, event):
        if not event.is_directory and not self._should_ignore(event.src_path):
            log(f"[Watcher] 移動を検知: {event.src_path} -> {event.dest_path}")
            self._schedule_update()


# ============================================================
# watchdog の起動
# ============================================================
def start_watcher(indexer: FileIndexer) -> Observer:
    handler  = IndexUpdateHandler(indexer)
    observer = Observer()
    for target_dir in TARGET_DIRS:
        if Path(target_dir).exists():
            observer.schedule(handler, path=target_dir, recursive=True)
            log(f"[Watcher] 監視開始: {target_dir}")
    observer.start()
    return observer


# ============================================================
# CLI エントリーポイント
# ============================================================
if __name__ == "__main__":
    watch_mode = "--watch" in sys.argv

    indexer = FileIndexer()
    indexer.update()

    if watch_mode:
        observer = start_watcher(indexer)
        log("[Watcher] 常駐監視モード（Ctrl+C で終了）")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
            observer.join()
            log("[Watcher] 監視を終了しました")