"""
FastMCPでファイル検索機能をMCPツールとして公開する。
Claude for Desktopから自然言語でPC内のファイルを検索できる。

起動方法:
  python server.py
"""
import os
import hashlib
import threading
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
 
    # パスをMD5ハッシュ化してフォルダ名にする
    # 例: "C:/Users/論文,C:/Users/研究" → "a3f9c2b1d4e5"
    dir_hash = hashlib.md5(target_dirs.encode("utf-8")).hexdigest()[:12]
    custom_index_dir = f"./data/custom/{dir_hash}/index"
    custom_meta_file = f"./data/custom/{dir_hash}/index_meta.json"
 
    # 現在の環境変数を退避
    original_target_dirs = os.getenv("TARGET_DIRS", "")
    original_index_dir   = os.getenv("INDEX_DIR",   "./data/index")
    original_meta_file   = os.getenv("META_FILE",   "./data/index_meta.json")
 
    # カスタムパス用の環境変数に切り替え
    os.environ["TARGET_DIRS"] = target_dirs
    os.environ["INDEX_DIR"]   = custom_index_dir
    os.environ["META_FILE"]   = custom_meta_file
 
    try:
        # FileIndexer・FileSearcherは起動時に環境変数を読み込むため
        # 環境変数切り替え後にインスタンスを作成する
        temp_indexer = FileIndexer()
        temp_indexer.update()  # 初回は全件作成、2回目以降は差分更新
 
        temp_searcher = FileSearcher()
        return temp_searcher.search(query)
 
    finally:
        # 必ず元の環境変数に戻す
        os.environ["TARGET_DIRS"] = original_target_dirs
        os.environ["INDEX_DIR"]   = original_index_dir
        os.environ["META_FILE"]   = original_meta_file


@mcp.tool()
def search_files(query: str, target_dirs: str = "") -> str:
    """
    【エクスプローラーについて】PC内のファイルを自然言語で検索します。
    
    このツールは「エクスプローラーについて」という言葉が含まれる質問にのみ使用してください。
    例:
    - 「エクスプローラーについて、機械学習のファイルはどこ？」
    - 「エクスプローラーについて、IAMロールの定義を探して」
    - 「エクスプローラーについて、C:/Documents の中からPythonコードを検索」
    
    それ以外の一般的な質問（コード生成、説明、知識など）には使用しないでください。
    
    Args:
        query: 検索したい内容の自然言語クエリ
        target_dirs: 検索対象のディレクトリパス（カンマ区切りで複数指定可能）
                     例: "C:/Users/name/Documents,C:/Users/name/Projects"
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