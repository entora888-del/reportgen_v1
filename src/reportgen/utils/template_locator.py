from __future__ import annotations
from pathlib import Path
import os
from importlib import resources

APPDIR_NAME = "ReportGen"
REL_USER_TEMPLATE = Path("templates") / "報告書_ひな形.docx"

def appdata_dir() -> Path:
    # Roaming AppData（%APPDATA%）
    base = os.environ.get("APPDATA")  # 例: C:\Users\XX\AppData\Roaming
    return Path(base) / APPDIR_NAME if base else Path.home() / f".{APPDIR_NAME}"

def user_template_path() -> Path:
    return appdata_dir() / REL_USER_TEMPLATE

def packaged_template_path() -> Path:
    # パッケージ同梱: reportgen/templates/報告書_ひな形.docx
    # Python 3.9+ 推奨API: files() / as_file()
    from importlib.resources import files, as_file
    traversable = files("reportgen.templates") / "報告書_ひな形.docx"
    # 実ファイルパスが必要な場面に備えて Path を返す
    with as_file(traversable) as p:
        return Path(p)

def ensure_user_template_exists() -> Path:
    """ユーザー領域に無ければ、同梱テンプレを初期展開して返す"""
    upath = user_template_path()
    if not upath.exists():
        upath.parent.mkdir(parents=True, exist_ok=True)
        src = packaged_template_path()
        upath.write_bytes(Path(src).read_bytes())
    return upath

def resolve_template_path(preferred: str | None = None) -> Path:
    """
    優先順：
      1) preferred（GUIで明示パス）
      2) ユーザー上書き（無ければ初期展開）
      3) 同梱テンプレ
    """
    if preferred:
        p = Path(preferred)
        if p.exists():
            return p
    up = user_template_path()
    if up.exists():
        return up
    # 初期導入時はユーザー領域に展開して、そちらを既定にする
    return ensure_user_template_exists()
