"""Run Context and Metadata Management.

Provides unique run_id generation (UTC timestamp + git commit hash),
run-specific directory orchestration (runs/<run_id>/), metadata tracking,
and backward-compatible context propagation.
"""

import os
import sys
import json
import time
import subprocess
from datetime import datetime, timezone
from typing import Optional, Dict, Any

_CURRENT_RUN_ID: Optional[str] = None
_RUN_START_TIME: Optional[float] = None


def get_git_commit_hash(short: bool = True) -> str:
    """Retrieves current git commit hash, falling back to reading .git/HEAD or 'nogit'."""
    # 1. Try git CLI
    try:
        cmd = ["git", "rev-parse", "--short" if short else "HEAD"]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=2)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass

    # 2. Try direct filesystem lookup in .git
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        git_dir = os.path.join(base_dir, ".git")
        head_file = os.path.join(git_dir, "HEAD")
        if os.path.isfile(head_file):
            with open(head_file, "r", encoding="utf-8") as f:
                head_content = f.read().strip()
            if head_content.startswith("ref:"):
                ref_path = os.path.join(git_dir, head_content[5:].strip().replace("/", os.sep))
                if os.path.isfile(ref_path):
                    with open(ref_path, "r", encoding="utf-8") as f:
                        commit = f.read().strip()
                        return commit[:7] if short else commit
            else:
                return head_content[:7] if short else head_content
    except Exception:
        pass

    return "nogit"


def generate_run_id(prefix: Optional[str] = None, is_test: bool = False) -> str:
    """Generates a run_id in the format: YYYYMMDD-HHMMSS_<commit_hash> (or prefixed for test)."""
    env_run_id = os.getenv("MC_RUN_ID")
    if env_run_id and env_run_id.strip():
        return env_run_id.strip()

    now_utc = datetime.now(timezone.utc)
    ts = now_utc.strftime("%Y%m%d-%H%M%S")
    commit = get_git_commit_hash(short=True)

    if prefix:
        return f"{prefix}_{ts}_{commit}"
    if is_test:
        return f"test_{ts}_{commit}"
    return f"{ts}_{commit}"


def set_current_run_id(run_id: str) -> str:
    """Explicitly sets the active process run_id."""
    global _CURRENT_RUN_ID, _RUN_START_TIME
    _CURRENT_RUN_ID = run_id
    if _RUN_START_TIME is None:
        _RUN_START_TIME = time.time()
    return _CURRENT_RUN_ID


def get_current_run_id() -> str:
    """Returns the active run_id, generating a default one if not already set."""
    global _CURRENT_RUN_ID, _RUN_START_TIME
    if _CURRENT_RUN_ID is None:
        _CURRENT_RUN_ID = generate_run_id()
        _RUN_START_TIME = time.time()
    return _CURRENT_RUN_ID


def reset_current_run_id() -> None:
    """Resets the active run_id (useful in unit tests)."""
    global _CURRENT_RUN_ID, _RUN_START_TIME
    _CURRENT_RUN_ID = None
    _RUN_START_TIME = None


def get_run_directory(run_id: Optional[str] = None, base_dir: Optional[str] = None) -> str:
    """Returns absolute path to runs/<run_id>/, ensuring directory exists."""
    active_id = run_id or get_current_run_id()
    if base_dir is None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    else:
        root = base_dir

    run_dir = os.path.join(root, "runs", active_id)
    os.makedirs(run_dir, exist_ok=True)
    return run_dir


def write_run_metadata(
    run_id: Optional[str] = None,
    extra_meta: Optional[Dict[str, Any]] = None,
    base_dir: Optional[str] = None
) -> str:
    """Writes run_meta.json inside runs/<run_id>/."""
    global _RUN_START_TIME
    active_id = run_id or get_current_run_id()
    run_dir = get_run_directory(active_id, base_dir=base_dir)
    meta_path = os.path.join(run_dir, "run_meta.json")

    commit = get_git_commit_hash(short=False)
    short_commit = commit[:7] if commit != "nogit" else "nogit"
    duration = round(time.time() - (_RUN_START_TIME or time.time()), 2)
    is_test = active_id.startswith("test_") or bool(extra_meta and extra_meta.get("is_test"))

    meta = {
        "run_id": active_id,
        "commit_hash": commit,
        "short_commit": short_commit,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "mc_version": os.getenv("MC_VERSION") or os.getenv("MINECRAFT_VERSION") or "1.20.4",
        "model_name": os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
        "log_level": os.getenv("LOG_LEVEL", "INFO"),
        "duration_seconds": duration,
        "is_test": is_test,
        "summary": "Completed"
    }

    if extra_meta:
        meta.update(extra_meta)

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    return meta_path
