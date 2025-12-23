from __future__ import annotations
from pathlib import Path
import os
from importlib import resources

APPDIR_NAME = "ReportGen"
REL_USER_TEMPLATE = Path("templates") / "報告書_ひな形_v2.docx"

def appdata_dir() -> Path:
    # Roaming AppData（%APPDATA%）
    base = os.environ.get("APPDATA")  # 例: C:\Users\XX\AppData\Roaming
    return Path(base) / APPDIR_NAME if base else Path.home() / f".{APPDIR_NAME}"

def user_template_path() -> Path:
    return appdata_dir() / REL_USER_TEMPLATE

def packaged_template_path(preferred: str | None = None) -> Path:
    """パッケージ同梱テンプレート（preferredがあれば優先）"""
    from importlib.resources import files, as_file

    candidates = []
    if preferred:
        candidates.append(preferred)
    candidates.extend(
        [
            "報告書_ひな形_v2.docx",
            "報告書_ひな形.docx",
        ]
    )
    local_dir = Path(__file__).resolve().parents[1] / "templates"
    local_candidates = [
        local_dir / "bk" / "報告書_ひな形.docx",
        local_dir / "bk" / "報告書_ひな形_v2.docx",
    ]
    seen: set[str] = set()
    for name in candidates:
        if name in seen:
            continue
        seen.add(name)
        try:
            traversable = files("reportgen.templates") / name
            with as_file(traversable) as p:
                candidate_path = Path(p)
                if candidate_path.exists():
                    return candidate_path
        except FileNotFoundError:
            continue
    for lp in local_candidates:
        if lp.exists():
            return lp
    raise FileNotFoundError("同梱テンプレートが見つかりません。")

def ensure_user_template_exists() -> Path:
    """ユーザー領域に無ければ、同梱テンプレを初期展開して返す"""
    upath = user_template_path()
    if not upath.exists():
        try:
            upath.parent.mkdir(parents=True, exist_ok=True)
            src = packaged_template_path()
            upath.write_bytes(Path(src).read_bytes())
        except PermissionError:
            return packaged_template_path()
    return upath

def resolve_template_path(preferred: str | None = None) -> Path:
    """
    優先順：
      1) preferred（GUIで明示パス）
      2) 環境変数 REPORTGEN_TEMPLATE_PATH
      3) ユーザー上書き（存在すれば。新しければ使用）
      4) 同梱テンプレ
    """
    if preferred:
        p = Path(preferred)
        if p.exists():
            return p
    env_path = os.environ.get("REPORTGEN_TEMPLATE_PATH")
    if env_path:
        p = Path(env_path).expanduser()
        if p.exists():
            return p

    packaged = packaged_template_path()
    up = user_template_path()
    if up.exists():
        try:
            if packaged.exists() and packaged.stat().st_mtime > up.stat().st_mtime:
                return packaged
        except FileNotFoundError:
            pass
        return up

    # 初期導入時はユーザー領域に展開して、そちらを既定にする
    return ensure_user_template_exists()
