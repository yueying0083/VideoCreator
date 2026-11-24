from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from app.config import DATA_DIR


def ensure_project_dirs(project_id: str) -> dict[str, Path]:
    base = DATA_DIR / "projects" / project_id
    dirs = {
        "base": base,
        "assets": base / "assets",
        "frames": base / "frames",
        "takes": base / "takes",
        "audio": base / "audio",
        "exports": base / "exports",
    }
    for p in dirs.values():
        p.mkdir(parents=True, exist_ok=True)
    return dirs


def allocate_rel_path(project_id: str, category: str, ext: str, prefix: str = "") -> tuple[str, Path]:
    dirs = ensure_project_dirs(project_id)
    folder = dirs[category]
    clean_ext = ext.lstrip(".")
    name = f"{prefix}_{uuid.uuid4().hex[:8]}.{clean_ext}" if prefix else f"{uuid.uuid4().hex[:10]}.{clean_ext}"
    abs_path = folder / name
    rel_path = abs_path.relative_to(DATA_DIR).as_posix()
    return rel_path, abs_path


def resolve_abs_path(rel_path: str | None) -> Path | None:
    if not rel_path:
        return None
    candidate = (DATA_DIR / rel_path).resolve()
    data_root = DATA_DIR.resolve()
    if data_root not in candidate.parents and candidate != data_root:
        raise ValueError("Invalid media path")
    return candidate


def to_media_url(rel_path: str | None) -> str | None:
    if not rel_path:
        return None
    clean = rel_path.replace("\\", "/").lstrip("/")
    return f"/media/{clean}"


def delete_project_files(project_id: str) -> None:
    base = DATA_DIR / "projects" / project_id
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
