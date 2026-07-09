"""Command-line interface for OpenBucket, powered by ``rich``."""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.parse

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from rich.text import Text

from . import __version__
from .core import (
    BucketError,
    create_directory_structure,
    download_keys,
    format_size,
    is_allowed,
    is_downloaded,
    list_bucket,
    load_listing_cache,
    save_listing_cache,
)

console = Console()

# Kept as a list of lines to sidestep quote-escaping in the ASCII art (it mixes
# `"`, `"""` and `'`). No `[`/`]` appear in the art, so rich markup is safe.
_ART_LINES = [
    ' dP"Yb  88""Yb 888888 88b 88 88""Yb 88   88  dP""b8 88  dP 888888 888888',
    'dP //Yb 88__dP 88__   88Yb88 88__dP 88   88 dP   `" 88odP  88__     88',
    'Yb// dP 88"""  88""   88 Y88 88""Yb Y8   8P Yb      88"Yb  88""     88',
    " YbodP  88     888888 88  Y8 88oodP `YbodP'  YboodP 88  Yb 888888   88",
]
BANNER = "[cyan]" + "\n".join(_ART_LINES) + "[/cyan]"


def print_banner() -> None:
    subtitle = Text.assemble(
        ("Hey, look! it's a ", "dim"),
        ("bucket", "bold green"),
        ("  —  let's download it!", "dim"),
    )
    console.print(
        Panel(
            BANNER,
            title=f"[bold green]OpenBucket[/] [dim]v{__version__}[/]",
            subtitle=subtitle,
            border_style="yellow",
            padding=(0, 2),
            expand=False,
        )
    )


def _default_output(bucket_url: str) -> str:
    parsed = urllib.parse.urlparse(bucket_url)
    bucket_name = parsed.netloc
    bucket_path = parsed.path.strip("/")
    if bucket_path:
        return os.path.join(os.getcwd(), bucket_name, bucket_path)
    return os.path.join(os.getcwd(), bucket_name)


def _apply_prefix(url: str, prefix: str) -> str:
    """Merge a ``prefix`` into the listing URL's query (server-side narrowing)."""
    if not prefix:
        return url
    parsed = urllib.parse.urlparse(url)
    query = dict(urllib.parse.parse_qsl(parsed.query))
    query["prefix"] = prefix
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def _humanize_age(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def _list_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        TextColumn("[green]{task.fields[found]}[/] objects"),
        console=console,
        transient=True,
    )


def _download_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=None),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TextColumn("[green]{task.fields[size]}"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    )


def _print_summary(results, duration: float) -> None:
    """Compact one-line-plus-rule summary that uses the terminal width well."""
    ok = results["failed"] == 0
    style = "green" if ok else "red"
    icon = "✓" if ok else "✗"
    console.print()
    console.rule(f"[bold {style}]{icon} Done[/] [dim]· {duration:.1f}s[/]", style=style, align="left")

    segments = [
        f"[bold green]{results['downloaded']}[/] downloaded "
        f"[dim]([/][green]{format_size(results['total_size'])}[/][dim])[/]"
    ]
    if results.get("already"):
        segments.append(f"[cyan]{results['already']}[/] already present")
    if results["skipped"]:
        segments.append(f"[yellow]{results['skipped']}[/] skipped")
    if results["failed"]:
        segments.append(f"[red]{results['failed']}[/] failed")
    console.print("  " + "   [dim]·[/]   ".join(segments))


def parse_arguments(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="openbucket",
        description="Dump the contents of a public/exposed cloud storage bucket "
        "(Amazon S3 or Oracle Cloud Object Storage).",
    )
    parser.add_argument("bucket_url", help="URL of the bucket (listing endpoint)")
    parser.add_argument(
        "--blacklist",
        default="",
        help="Comma-separated extensions to skip (e.g. jpg,png,mp4)",
    )
    parser.add_argument(
        "--whitelist",
        "-w",
        default="",
        help="Download ONLY these extensions, comma-separated (e.g. pdf,csv)",
    )
    parser.add_argument(
        "--prefix",
        "-p",
        default="",
        help="List only objects under this prefix (server-side, fewer pages)",
    )
    parser.add_argument("--threads", "-t", type=int, default=10, help="Download threads (default: 10)")
    parser.add_argument("--output", "-o", default="", help="Output folder")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout in seconds")
    parser.add_argument("--list-only", "-l", action="store_true", help="List objects only, without downloading")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-download files that already exist (default: skip/resume)",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore the cache and re-list the bucket from scratch",
    )
    parser.add_argument("--no-cache", action="store_true", help="Don't read or write the listing cache")
    parser.add_argument(
        "--cache-ttl",
        type=float,
        default=24.0,
        help="Listing-cache lifetime in hours (0 = never expires; default: 24)",
    )
    parser.add_argument("--quiet", "-q", action="store_true", help="Don't print the banner")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    bucket_url = _apply_prefix(args.bucket_url, args.prefix)
    out_folder = args.output or _default_output(args.bucket_url)
    blacklist = [e.strip().lstrip(".").lower() for e in args.blacklist.split(",") if e.strip()]
    whitelist = [e.strip().lstrip(".").lower() for e in args.whitelist.split(",") if e.strip()]

    info = Table.grid(padding=(0, 1))
    info.add_column(style="bold blue")
    info.add_column()
    info.add_row("Bucket:", args.bucket_url)
    if args.prefix:
        info.add_row("Prefix:", args.prefix)
    if not args.list_only:
        info.add_row("Output:", out_folder)
    if whitelist:
        info.add_row("Only:", ", ".join(whitelist))
    if blacklist:
        info.add_row("Skipping:", ", ".join(blacklist))
    console.print(info)

    # The storage APIs can only narrow a listing by prefix, never by extension,
    # so extension filters are applied client-side after the full listing.
    if (blacklist or whitelist) and not args.prefix:
        console.print(
            "[dim]Note: extension filters are applied after listing (the API can't "
            "filter by extension). Use --prefix to narrow at the source.[/]"
        )
    console.print()

    start = time.time()

    # -- Listing (cache-aware) --------------------------------------------- #
    ttl_seconds = None if args.cache_ttl <= 0 else args.cache_ttl * 3600
    cache = None
    if not args.refresh and not args.no_cache:
        cache = load_listing_cache(out_folder, bucket_url, ttl_seconds, start)

    if cache:
        backend = cache["backend"]
        download_base = cache["download_base"]
        all_keys = cache["keys"]
        age = _humanize_age(start - float(cache["listed_at"] or start))
        console.print(
            f"[green][+][/] Cached listing · [bold]{backend.upper()}[/] · "
            f"[bold green]{len(all_keys)}[/] objects (listed {age} ago). "
            f"[dim]Use --refresh to update.[/]"
        )
    else:
        try:
            with _list_progress() as progress:
                task = progress.add_task("Listing objects...", total=None, found=0)

                def on_page(page: int, count: int) -> None:
                    progress.update(task, found=count, description=f"Listing objects (page {page})...")

                # List everything unfiltered so the cache is filter-independent.
                backend, download_base, all_keys = list_bucket(
                    bucket_url, None, args.timeout, on_page, None
                )
        except BucketError as e:
            console.print(f"[bold red][!][/] {e}")
            return 1

        if not all_keys:
            console.print("[yellow][!][/] No objects found in the bucket.")
            return 1

        console.print(
            f"[green][+][/] Backend [bold]{backend.upper()}[/] · "
            f"[bold green]{len(all_keys)}[/] objects found."
        )
        if not args.no_cache:
            save_listing_cache(out_folder, bucket_url, backend, download_base, all_keys, start)

    # -- Filter by extension ----------------------------------------------- #
    if blacklist or whitelist:
        keys = [k for k in all_keys if is_allowed(k, blacklist, whitelist)]
        console.print(f"[green][+][/] After extension filter: [bold]{len(keys)}[/] objects.")
    else:
        keys = all_keys

    if not keys:
        console.print("[yellow][!][/] Nothing left after filtering.")
        return 0

    if args.list_only:
        for key in keys:
            console.print(f"  [dim]{download_base.rstrip('/')}/[/]{key}")
        return 0

    # -- Downloading ------------------------------------------------------- #
    if not create_directory_structure(out_folder):
        console.print(f"[bold red][!][/] Could not create output folder: {out_folder}")
        return 1

    already = 0
    if args.overwrite:
        to_download = keys
    else:
        with console.status("[blue]Checking already-downloaded files...", spinner="dots"):
            to_download = [k for k in keys if not is_downloaded(out_folder, k)]
        already = len(keys) - len(to_download)
        if already:
            console.print(
                f"[green][+][/] [bold]{already}[/] already downloaded (skipping) · "
                f"[bold]{len(to_download)}[/] remaining."
            )

    if not to_download:
        console.print("[green][✓][/] Everything already downloaded. Nothing to do.")
        return 0

    failures = []
    state = {"bytes": 0}
    with _download_progress() as progress:
        task = progress.add_task("Downloading", total=len(to_download), size="0 bytes")

        def on_result(result) -> None:
            if result["status"] == "success":
                state["bytes"] += int(result.get("size", 0))
            elif result["status"] == "failed":
                failures.append(result)
            progress.update(task, advance=1, size=format_size(state["bytes"]))

        results = download_keys(
            to_download, download_base, out_folder, blacklist,
            args.threads, args.timeout, on_result, args.overwrite,
        )
    results["already"] = already

    duration = time.time() - start

    for f in failures[:20]:
        console.print(f"[red][!][/] Failed: {f['file']} [dim]({f['reason']})[/]")
    if len(failures) > 20:
        console.print(f"[red][!][/] ... and {len(failures) - 20} more failures.")

    _print_summary(results, duration)
    return 0 if results["failed"] == 0 else 2


def main(argv=None) -> int:
    args = parse_arguments(argv)
    if not args.quiet:
        print_banner()
    try:
        return run(args)
    except KeyboardInterrupt:
        console.print("\n[yellow][!][/] Interrupted by user.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
