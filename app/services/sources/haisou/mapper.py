from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.services.adapters.pan115 import normalize_115_share_link
from app.services.link.downloads import is_valid_download_link
from app.services.types import SearchResult


def map_haisou_items(
    items: list[dict[str, Any]] | list[Any],
    *,
    source_name: str = "海搜 Haisou",
    source_type: str = "site_plugin",
    platforms: list[str] | None = None,
) -> list[SearchResult]:
    allowed = {str(item).strip().lower() for item in (platforms or ["115"]) if str(item).strip()}
    results: list[SearchResult] = []
    seen: set[str] = set()
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        platform = str(raw.get("platform") or "").strip().lower()
        if allowed and platform and platform not in allowed:
            continue
        if platform and platform != "115":
            continue
        url = build_haisou_share_url(raw)
        if not url or not is_valid_download_link(url) or url in seen:
            continue
        seen.add(url)
        title = str(raw.get("title") or "").strip() or source_name
        context_parts = [
            title,
            str(raw.get("platformName") or platform or ""),
            f"size={raw.get('sizeBytes')}" if raw.get("sizeBytes") is not None else "",
            f"files={raw.get('fileCount')}" if raw.get("fileCount") is not None else "",
            f"hsid={raw.get('hsid')}" if raw.get("hsid") else "",
            *_haisou_file_contexts(raw),
        ]
        context = "\n".join(part for part in context_parts if part)
        results.append(
            SearchResult(
                title=title[:120],
                url=url,
                source=f"{source_type}:{source_name}",
                message_id=str(raw.get("hsid") or raw.get("shareCode") or "") or None,
                context=context,
            )
        )
    return results


def _haisou_file_contexts(item: dict[str, Any], limit: int = 30) -> list[str]:
    """Collect searchable filenames/paths from Haisou payload variants."""
    values: list[str] = []
    seen: set[str] = set()
    file_keys = {
        "file",
        "filename",
        "fileName",
        "file_name",
        "filePath",
        "file_path",
        "name",
        "path",
        "title",
    }
    container_keys = {"files", "fileList", "file_list", "items", "children", "paths"}

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        values.append(text[:240])

    def walk(value: Any, *, key: str = "", depth: int = 0) -> None:
        if len(values) >= limit or depth > 4:
            return
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                if len(values) >= limit:
                    break
                if child_key in file_keys and not isinstance(child_value, (dict, list, tuple)):
                    add(child_value)
                elif child_key in container_keys or isinstance(child_value, (dict, list, tuple)):
                    walk(child_value, key=str(child_key), depth=depth + 1)
            return
        if isinstance(value, (list, tuple)):
            for child in value:
                if len(values) >= limit:
                    break
                walk(child, key=key, depth=depth + 1)
            return
        if key in file_keys or key in container_keys:
            add(value)

    walk(item)
    inferred = _infer_episode_context(values)
    if inferred:
        values.insert(0, inferred)
    return values


VIDEO_FILE_RE = re.compile(r"(?i)\.(?:mkv|mp4|ts|m2ts|avi|mov|wmv|flv|webm|rmvb|iso)$")
EPISODE_FILE_RE = re.compile(
    r"(?i)(?:^|[\s._\-\[\(])(?:s(?P<season>\d{1,2})[\s._-]*)?(?:e|ep)?(?P<episode>\d{1,3})(?:[\s._\-\]\)]|$)"
)


def _infer_episode_context(values: list[str]) -> str:
    episodes = _episode_numbers_from_files(values)
    if not episodes:
        return ""
    highest = max(episodes)
    if highest < 2:
        return ""
    # Only synthesize a pack range when the file list looks continuous enough.
    expected = set(range(1, highest + 1))
    if len(episodes & expected) < min(highest, max(2, int(highest * 0.6))):
        return ""
    return f"S01E01-E{highest:02d}"


def _episode_numbers_from_files(values: list[str]) -> set[int]:
    episodes: set[int] = set()
    for value in values:
        name = str(value or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
        if not name or not VIDEO_FILE_RE.search(name):
            continue
        stem = VIDEO_FILE_RE.sub("", name)
        for match in EPISODE_FILE_RE.finditer(stem):
            number = _safe_episode_number(match.group("episode"))
            if number:
                episodes.add(number)
    return episodes


def _safe_episode_number(value: Any) -> int:
    try:
        number = int(str(value or "").lstrip("0") or "0")
    except ValueError:
        return 0
    return number if 0 < number <= 200 else 0


def build_haisou_share_url(item: dict[str, Any]) -> str:
    share_url = str(item.get("shareUrl") or item.get("share_url") or "").strip()
    share_code = str(item.get("shareCode") or item.get("share_code") or "").strip()
    share_pwd = str(item.get("sharePwd") or item.get("share_pwd") or item.get("pwd") or "").strip()
    platform = str(item.get("platform") or "").strip().lower()

    if not share_url and platform == "115" and share_code:
        share_url = f"https://115.com/s/{share_code}"
    if not share_url:
        return ""

    if platform == "115" or "115.com" in share_url or "115cdn.com" in share_url:
        return _with_115_password(share_url, share_pwd)
    return share_url


def _with_115_password(link: str, password: str | None) -> str:
    base = normalize_115_share_link(link) or str(link or "").strip()
    if not base:
        return ""
    if not password:
        return base
    parsed = urlparse(base)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    keys = {key.lower() for key, _ in query_items}
    if {"password", "pwd", "receive_code"} & keys:
        return base
    query_items.append(("password", str(password).strip()))
    return urlunparse(parsed._replace(query=urlencode(query_items)))
