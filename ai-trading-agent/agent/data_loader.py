"""Data loader — transparent layer for local disk or GitHub API reads."""

import json
import logging
import os
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# GitHub settings (only used in cloud mode)
_GITHUB_REPO = os.getenv("GITHUB_REPO", "")  # e.g. "user/repo"
_GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
_GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")


def _is_cloud() -> bool:
    return os.getenv("DEPLOYMENT_MODE", "local") == "cloud"


def _load_from_github(path: Path) -> dict | list | None:
    """Load a JSON file from GitHub API (raw content)."""
    if not _GITHUB_REPO:
        logger.warning("GITHUB_REPO not set — cannot load from GitHub")
        return None

    # Convert local path to repo-relative path
    # Expects paths like data/findings/2025-01-15.json
    rel_path = str(path)
    # Strip leading parts to get repo-relative path
    for prefix in ("ai-trading-agent/", "./"):
        if rel_path.startswith(prefix):
            rel_path = rel_path[len(prefix):]

    url = f"https://api.github.com/repos/{_GITHUB_REPO}/contents/{rel_path}"
    headers = {"Accept": "application/vnd.github.raw+json"}
    if _GITHUB_TOKEN:
        headers["Authorization"] = f"token {_GITHUB_TOKEN}"

    params = {"ref": _GITHUB_BRANCH}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 404:
            return None
        else:
            logger.warning("GitHub API %d for %s", resp.status_code, rel_path)
            return None
    except Exception as e:
        logger.warning("GitHub API error for %s: %s", rel_path, e)
        return None


def load_json_file(path: Path) -> dict | list | None:
    """Load a JSON file — from local disk or GitHub API depending on mode."""
    if _is_cloud():
        return _load_from_github(path)

    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def list_json_files(directory: Path, pattern: str = "*.json") -> list[Path]:
    """List JSON files in a directory — local only (cloud uses different listing)."""
    if _is_cloud():
        return _list_github_files(directory, pattern)
    return sorted(directory.glob(pattern), reverse=True)


def _list_github_files(directory: Path, pattern: str = "*.json") -> list[Path]:
    """List files in a GitHub repo directory."""
    if not _GITHUB_REPO:
        return []

    rel_path = str(directory)
    for prefix in ("ai-trading-agent/", "./"):
        if rel_path.startswith(prefix):
            rel_path = rel_path[len(prefix):]

    url = f"https://api.github.com/repos/{_GITHUB_REPO}/contents/{rel_path}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    if _GITHUB_TOKEN:
        headers["Authorization"] = f"token {_GITHUB_TOKEN}"

    params = {"ref": _GITHUB_BRANCH}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code != 200:
            return []
        files = resp.json()
        if not isinstance(files, list):
            return []
        # Filter by extension and sort descending
        suffix = pattern.replace("*", "")
        matching = [Path(f["path"]) for f in files if f["name"].endswith(suffix)]
        return sorted(matching, reverse=True)
    except Exception as e:
        logger.warning("GitHub API listing error: %s", e)
        return []
