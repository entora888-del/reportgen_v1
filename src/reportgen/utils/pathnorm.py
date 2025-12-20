import os, re

def is_windows_runtime() -> bool:
    """ネイティブWindows実行か（WSLではFalse）"""
    return os.name == "nt" and "WSL_DISTRO_NAME" not in os.environ

def normalize_input_path(s: str) -> str:
    """
    貼り付け/テキストDnDで受けたパス文字列を実行環境に合わせて正規化。
      - Windows: そのまま（C:\... / \\wsl$\... / file:///C:/...）
      - WSL: C:\... → /mnt/c/..., file:///C:/... → /mnt/c/...
    """
    s = s.strip().strip('"').strip("'")

    # file:///C:/path → C:\path（Windows） or /mnt/c/path（WSL）
    if s.lower().startswith("file:///"):
        s = s[8:].lstrip("/")            # "C:/Users/..."
        s = s.replace("/", "\\")         # "C:\Users\..."
    # \\wsl$ は今回はそのまま返す（Windows側での利用を想定）
    if s.startswith("\\\\wsl$"):
        return s

    # WSL実行時は Windowsパス → /mnt/<drive>/... に変換
    if not is_windows_runtime():
        m = re.match(r"^([A-Za-z]):[\\/](.*)$", s)
        if m:
            drive = m.group(1).lower()
            rest = m.group(2).replace("\\", "/")
            return f"/mnt/{drive}/{rest}"

    return s
