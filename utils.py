"""
utils.py
汎用ユーティリティ（ログTee・プログレスバー）
"""

import os
import sys


def setup_stdout_tee(log_file_path: str) -> None:
    """
    print の出力をコンソールとログファイルの両方に流す。
    ログ量が多いときでも、あとから内容を追えるようにするための簡易Tee。
    """
    if getattr(sys.stdout, "_is_xpost_tee", False):
        return

    os.makedirs(os.path.dirname(log_file_path) or ".", exist_ok=True)
    log_f = open(log_file_path, "a", encoding="utf-8")
    original_stdout = sys.stdout

    class TeeStdout:
        def __init__(self, orig, log_file):
            self._orig = orig
            self._log = log_file
            self._is_xpost_tee = True

        def write(self, s):
            self._orig.write(s)
            self._log.write(s)

        def flush(self):
            self._orig.flush()
            self._log.flush()

    sys.stdout = TeeStdout(original_stdout, log_f)


def _make_bar(done: int, total: int, width: int = 28) -> str:
    ratio = done / total if total > 0 else 0
    filled = int(width * ratio)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {done}/{total} ({ratio * 100:.0f}%)"
