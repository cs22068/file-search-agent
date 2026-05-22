"""
FastMCPでファイル検索機能をMCPツールとして公開する。
Claude for Desktopから自然言語でPC内のファイルを検索できる。

起動方法:
  python server.py
"""
import hashlib
import threading
from pathlib import Path
from fastmcp import FastMCP
from searcher import FileSearcher              # 検索エンジン
from indexer import FileIndexer, start_watcher # インデクサーとファイル監視

# ============================================================
# MCPサーバーの初期化
# ============================================================
# FastMCPのインスタンスを作成し、ツールを定義
mcp = FastMCP("FileSearchAgent")

indexer  = FileIndexer()
threading.Thread(target=indexer.update, daemon=True).start() # 起動時のupdateをバックグラウンドで実行（タイムアウト防止）

# 検索エンジンの起動
searcher = FileSearcher()
observer = start_watcher(indexer)

# ============================================================
# MCPツールの定義
# ============================================================

def search_in_custom_dirs(query: str, target_dirs: str) -> str:
    base_dir = Path(__file__).parent
    dir_hash = hashlib.md5(target_dirs.encode("utf-8")).hexdigest()[:12]
    custom_index_dir = str(base_dir / "data" / "custom" / dir_hash / "index")
    custom_meta_file = str(base_dir / "data" / "custom" / dir_hash / "index_meta.json")
    
    dirs = [d.strip() for d in target_dirs.split(",") if d.strip()]
    temp_indexer = FileIndexer(
        target_dirs=dirs,
        index_dir=custom_index_dir,
        meta_file=custom_meta_file,
    )
    temp_indexer.update()
    temp_searcher = FileSearcher(index_dir=custom_index_dir)
    return temp_searcher.search(query)


@mcp.tool()
def search_files(query: str, target_dirs: str = "") -> str:
    """
    【エクスプローラーについて】PC内のファイルを自然言語で検索します。

    このツールは「エクスプローラーについて」という言葉が含まれる質問にのみ使用してください。

    【重要】ユーザーの入力に " で囲まれたパスがある場合、
    その " の中身を必ずtarget_dirsに設定してください。
    queryにはパスを含めないでください。

    例:
    - 「エクスプローラーについて "C:/Users/論文" の中を検索して」
      → query="検索したい内容", target_dirs="C:/Users/論文"
    - 「エクスプローラーについて "C:/Users/A,C:/Users/B" を検索して」
      → query="検索したい内容", target_dirs="C:/Users/A,C:/Users/B"
    - 「エクスプローラーについて IAMロールの定義を探して」（"なし）
      → query="IAMロールの定義", target_dirs=""（省略）

    Args:
        query: 検索したい内容の自然言語クエリ（パスは含めない）
        target_dirs: " で囲まれたディレクトリパス（カンマ区切りで複数指定可能）
                     省略時は環境変数TARGET_DIRSのパスを使用
    Returns:
        検索結果と参照ファイルのパス
    """
    # target_dirsが指定されている場合は一時的にインデックスを作成
    if target_dirs:
        return search_in_custom_dirs(query, target_dirs)
    else:
        return searcher.search(query)

# ============================================================
# 追加のMCPツールやエンドポイントをここに定義可能
# ============================================================

@mcp.tool()
def reindex_files(target_dir: str = "") -> str:
    """
    ファイルのインデックスを手動で更新します。
    通常は自動更新されますが、強制的に更新したいときに使います。

    Args:
        target_dir: インデックス化するディレクトリのパス（省略可）
    Returns:
        更新結果のメッセージ
    """
    indexer.update()
    return "インデックスを更新しました"


@mcp.tool()
def index_status() -> str:
    """
    現在のインデックス状態を確認します。
    何件のファイルがインデックス化されているかを確認できます。

    Returns:
        インデックス済みファイル数と最終更新日時
    """
    meta = indexer.meta
    if not meta:
        return "インデックスが存在しません。先に reindex_files を実行してください。"

    count = len(meta)
    latest = max(v["last_indexed"] for v in meta.values())
    return f"インデックス済みファイル数: {count} 件\n最終更新: {latest}"


# ============================================================
# エントリーポイント
# ============================================================
if __name__ == "__main__":
    try:
        mcp.run()
    finally:
        observer.stop()
        observer.join()