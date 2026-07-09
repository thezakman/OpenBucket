"""OpenBucket - dump the contents of public/exposed cloud storage buckets.

Supports Amazon S3 (and S3-compatible XML APIs) and Oracle Cloud
Object Storage (native JSON API), transparently handling each backend's
pagination.
"""

from .core import (
    BucketError,
    detect_bucket_type,
    download_file,
    download_keys,
    format_size,
    is_allowed,
    is_downloaded,
    list_bucket,
    list_oracle_keys,
    list_s3_keys,
    load_listing_cache,
    local_path_for,
    save_listing_cache,
)

__version__ = "3.0.0"
__author__ = "TheZakMan"

__all__ = [
    "__version__",
    "__author__",
    "BucketError",
    "detect_bucket_type",
    "download_file",
    "download_keys",
    "format_size",
    "is_allowed",
    "is_downloaded",
    "list_bucket",
    "list_oracle_keys",
    "list_s3_keys",
    "load_listing_cache",
    "local_path_for",
    "save_listing_cache",
]
