"""Core logic for OpenBucket: bucket detection, listing and downloading.

This module is intentionally free of any presentation/UI code so it can be
reused as a library. All progress reporting happens through optional
callbacks (``on_page`` / ``on_result``).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import random
import time
import urllib.parse
import xml.etree.ElementTree as ElementTree
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional, Tuple

import requests

# Name of the metadata directory dropped inside the output folder.
CACHE_DIRNAME = ".openbucket"

# A small pool of User-Agents rotated per request to look less robotic.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
    "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:54.0) Gecko/20100101 Firefox/54.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/11.1 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 10_3_1 like Mac OS X) AppleWebKit/603.1.30 (KHTML, like Gecko) Version/10.0 Mobile/14E304 Safari/602.1",
    "Mozilla/5.0 (Linux; Android 7.0; Nexus 5X Build/NBD90W) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/62.0.3202.84 Mobile Safari/537.36",
]


class BucketError(Exception):
    """Raised when a bucket cannot be listed (network error, bad status, etc.)."""


def _random_headers() -> Dict[str, str]:
    return {"User-Agent": random.choice(USER_AGENTS)}


def get_namespace(element: ElementTree.Element) -> str:
    m = re.match(r"\{.*\}", element.tag)
    return m.group(0) if m else ""


def format_size(size_bytes: int) -> str:
    """Human-readable byte size (bytes/KB/MB/GB/TB)."""
    size = float(size_bytes)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "bytes":
                return f"{int(size)} bytes"
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"


def _extension(key: str) -> str:
    return key.rsplit(".", 1)[-1].lower() if "." in key else ""


def is_blacklisted(key: str, blacklist: Optional[List[str]]) -> bool:
    if not blacklist:
        return False
    return _extension(key) in blacklist


def is_allowed(
    key: str,
    blacklist: Optional[List[str]] = None,
    whitelist: Optional[List[str]] = None,
) -> bool:
    """Return True if ``key`` should be kept given the (optional) filters.

    ``whitelist`` (if given) keeps only those extensions; ``blacklist`` drops
    the listed extensions. Blacklist wins over whitelist on conflicts.
    """
    ext = _extension(key)
    if whitelist and ext not in whitelist:
        return False
    if blacklist and ext in blacklist:
        return False
    return True


def create_directory_structure(path: str) -> bool:
    if not path or os.path.isdir(path):
        return True
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except OSError:
        return False


def local_path_for(out_folder: str, key: str) -> str:
    """Where a given object key is written on disk (keeping literal ``//``)."""
    return os.path.join(out_folder, key.replace("//", "/double_slash/"))


def is_downloaded(out_folder: str, key: str) -> bool:
    """True if the object already exists locally as a non-empty file."""
    try:
        return os.path.getsize(local_path_for(out_folder, key)) > 0
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# Listing cache
# --------------------------------------------------------------------------- #

def _cache_paths(out_folder: str, url: str) -> Tuple[str, str, str]:
    # Key files by a short hash of the URL so a full listing and prefixed
    # listings can coexist without clobbering each other.
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    cache_dir = os.path.join(out_folder, CACHE_DIRNAME)
    return cache_dir, os.path.join(cache_dir, f"listing-{h}.json"), os.path.join(cache_dir, f"keys-{h}.txt")


def save_listing_cache(
    out_folder: str,
    url: str,
    backend: str,
    download_base: str,
    keys: List[str],
    listed_at: float,
) -> bool:
    """Persist the full (unfiltered) object listing next to the downloads."""
    cache_dir, meta_path, keys_path = _cache_paths(out_folder, url)
    if not create_directory_structure(cache_dir):
        return False
    try:
        with open(keys_path, "w", encoding="utf-8") as f:
            f.write("\n".join(keys))
        meta = {
            "url": url,
            "backend": backend,
            "download_base": download_base,
            "count": len(keys),
            "listed_at": listed_at,
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f)
    except OSError:
        return False
    return True


def load_listing_cache(
    out_folder: str,
    url: str,
    ttl_seconds: Optional[float] = None,
    now: Optional[float] = None,
) -> Optional[Dict[str, object]]:
    """Load a cached listing for ``url`` if present, matching and (optionally) fresh.

    Returns ``{backend, download_base, keys, listed_at, count}`` or ``None``.
    """
    _, meta_path, keys_path = _cache_paths(out_folder, url)
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return None

    if meta.get("url") != url:
        return None
    if ttl_seconds is not None and now is not None:
        if now - float(meta.get("listed_at", 0)) > ttl_seconds:
            return None

    try:
        with open(keys_path, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None

    keys = [k for k in content.split("\n") if k]
    return {
        "backend": meta.get("backend"),
        "download_base": meta.get("download_base"),
        "keys": keys,
        "listed_at": meta.get("listed_at"),
        "count": meta.get("count"),
    }


# --------------------------------------------------------------------------- #
# Backend detection & listing
# --------------------------------------------------------------------------- #

def detect_bucket_type(url: str) -> str:
    """Return ``"oracle"`` for Oracle Object Storage URLs, else ``"s3"``."""
    parsed = urllib.parse.urlparse(url)
    if "oraclecloud.com" in parsed.netloc or re.search(r"/n/[^/]+/b/[^/]+/o/?", parsed.path):
        return "oracle"
    return "s3"


def list_oracle_keys(
    url: str,
    blacklist: Optional[List[str]] = None,
    timeout: int = 30,
    on_page: Optional[Callable[[int, int], None]] = None,
    whitelist: Optional[List[str]] = None,
) -> Tuple[str, List[str]]:
    """List every object in an Oracle bucket, following ``nextStartWith`` paging.

    Returns ``(download_base, keys)`` where ``download_base`` is the ``.../o/``
    endpoint used to build each object's download URL.
    """
    parsed = urllib.parse.urlparse(url)
    download_base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if not download_base.endswith("/"):
        download_base += "/"
    base_params = dict(urllib.parse.parse_qsl(parsed.query))

    keys: List[str] = []
    start: Optional[str] = None
    page = 0
    while True:
        params = dict(base_params)
        if start:
            params["start"] = start
        try:
            r = requests.get(download_base, headers=_random_headers(), params=params, timeout=timeout)
        except requests.RequestException as e:
            raise BucketError(f"Error listing objects: {e}") from e

        if r.status_code != 200:
            raise BucketError(f"Listing failed (HTTP {r.status_code})")

        try:
            data = r.json()
        except ValueError as e:
            raise BucketError("Oracle response is not valid JSON") from e

        for obj in data.get("objects", []):
            name = obj.get("name")
            if name and not name.endswith("/") and is_allowed(name, blacklist, whitelist):
                keys.append(name)

        page += 1
        if on_page:
            on_page(page, len(keys))

        start = data.get("nextStartWith")
        if not start:
            break

    return download_base, keys


def list_s3_keys(
    url: str,
    blacklist: Optional[List[str]] = None,
    timeout: int = 30,
    on_page: Optional[Callable[[int, int], None]] = None,
    whitelist: Optional[List[str]] = None,
) -> Tuple[str, List[str]]:
    """List every object in an S3-compatible bucket, following the XML marker paging.

    Returns ``(download_base, keys)``.
    """
    parsed = urllib.parse.urlparse(url)
    download_base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    base_params = dict(urllib.parse.parse_qsl(parsed.query))

    keys: List[str] = []
    marker: Optional[str] = None
    page = 0
    while True:
        params = dict(base_params)
        if marker:
            params["marker"] = marker
        try:
            r = requests.get(download_base, headers=_random_headers(), params=params, timeout=timeout)
        except requests.RequestException as e:
            raise BucketError(f"Error listing objects: {e}") from e

        if r.status_code != 200:
            raise BucketError(f"Listing failed (HTTP {r.status_code})")

        try:
            root = ElementTree.fromstring(r.content)
        except ElementTree.ParseError as e:
            raise BucketError("Bucket response is not valid XML") from e

        ns = get_namespace(root)
        contents = root.findall(f"{ns}Contents")
        last_key: Optional[str] = None
        for content in contents:
            key_el = content.find(f"{ns}Key")
            if key_el is not None and key_el.text:
                last_key = key_el.text
                if not key_el.text.endswith("/") and is_allowed(key_el.text, blacklist, whitelist):
                    keys.append(key_el.text)

        page += 1
        if on_page:
            on_page(page, len(keys))

        # Determine next marker for pagination.
        truncated_el = root.find(f"{ns}IsTruncated")
        is_truncated = truncated_el is not None and (truncated_el.text or "").lower() == "true"
        next_marker_el = root.find(f"{ns}NextMarker")
        if next_marker_el is not None and next_marker_el.text:
            marker = next_marker_el.text
        elif is_truncated and last_key:
            marker = last_key
        else:
            break

    return download_base, keys


def list_bucket(
    url: str,
    blacklist: Optional[List[str]] = None,
    timeout: int = 30,
    on_page: Optional[Callable[[int, int], None]] = None,
    whitelist: Optional[List[str]] = None,
) -> Tuple[str, str, List[str]]:
    """Detect the backend and list its keys.

    Returns ``(backend, download_base, keys)``.
    """
    backend = detect_bucket_type(url)
    if backend == "oracle":
        base, keys = list_oracle_keys(url, blacklist, timeout, on_page, whitelist)
    else:
        base, keys = list_s3_keys(url, blacklist, timeout, on_page, whitelist)
    return backend, base, keys


# --------------------------------------------------------------------------- #
# Downloading
# --------------------------------------------------------------------------- #

def download_file(
    bucket_url: str,
    key: str,
    out_folder: str,
    blacklist: Optional[List[str]] = None,
    timeout: int = 30,
    retry_count: int = 3,
    overwrite: bool = False,
) -> Dict[str, object]:
    """Download a single object. Returns a result dict with a ``status`` field.

    Writes to a ``.part`` file and renames it into place only on success, so an
    interrupted download never leaves a truncated file that ``is_downloaded``
    would mistake for complete.
    """
    if key.endswith("/") or is_blacklisted(key, blacklist):
        return {"status": "skipped", "file": key, "reason": "directory or blacklisted"}

    try:
        file_path = local_path_for(out_folder, key)

        if not overwrite:
            try:
                if os.path.getsize(file_path) > 0:
                    return {"status": "skipped", "file": key, "reason": "exists"}
            except OSError:
                pass

        directory = os.path.dirname(file_path)
        if not create_directory_structure(directory):
            return {"status": "failed", "file": key, "reason": "could not create directory"}

        # Preserve slashes in the object name but escape spaces/special chars.
        safe_key = urllib.parse.quote(key, safe="/")
        file_url = bucket_url.rstrip("/") + "/" + safe_key
        part_path = file_path + ".part"

        last_reason = "unknown error"
        for attempt in range(retry_count):
            try:
                r = requests.get(file_url, headers=_random_headers(), timeout=timeout, stream=True)
                if r.status_code == 200:
                    with open(part_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    os.replace(part_path, file_path)
                    return {"status": "success", "file": key, "size": os.path.getsize(file_path)}
                last_reason = f"HTTP {r.status_code}"
            except requests.RequestException as e:
                last_reason = str(e)
            if attempt < retry_count - 1:
                time.sleep(1)

        # Clean up a partial file left by the failed attempts.
        try:
            os.remove(part_path)
        except OSError:
            pass
        return {"status": "failed", "file": key, "reason": last_reason}

    except Exception as e:  # pragma: no cover - defensive
        return {"status": "failed", "file": key, "reason": str(e)}


def download_keys(
    files_to_download: List[str],
    bucket_url: str,
    out_folder: str,
    blacklist: Optional[List[str]] = None,
    max_workers: int = 10,
    timeout: int = 30,
    on_result: Optional[Callable[[Dict[str, object]], None]] = None,
    overwrite: bool = False,
) -> Dict[str, int]:
    """Download a list of keys in parallel.

    ``on_result`` is invoked with each file's result dict as it completes,
    which the CLI uses to drive its progress bar. On ``KeyboardInterrupt`` the
    pending (not-yet-started) downloads are cancelled so we don't hang waiting
    on a huge queue, and the interrupt is re-raised.
    """
    results = {"downloaded": 0, "failed": 0, "skipped": 0, "total_size": 0}
    if not files_to_download:
        return results

    executor = ThreadPoolExecutor(max_workers=max_workers)
    futures = {
        executor.submit(download_file, bucket_url, key, out_folder, blacklist, timeout, overwrite=overwrite): key
        for key in files_to_download
    }
    try:
        for future in as_completed(futures):
            result = future.result()
            status = result["status"]
            if status == "success":
                results["downloaded"] += 1
                results["total_size"] += int(result.get("size", 0))
            elif status == "skipped":
                results["skipped"] += 1
            else:
                results["failed"] += 1
            if on_result:
                on_result(result)
    except KeyboardInterrupt:
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)

    return results
