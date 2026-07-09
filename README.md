<h1 align="center">OpenBucket</h1>

<p align="center">
  <em>Dump every object from a public / exposed / misconfigured cloud storage bucket.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.8%2B-blue.svg" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/version-3.0.0-brightgreen.svg" alt="Version 3.0.0">
  <img src="https://img.shields.io/github/license/thezakman/OpenBucket.svg" alt="License">
  <img src="https://img.shields.io/badge/backends-S3%20%7C%20Oracle-orange.svg" alt="Backends: S3 | Oracle">
  <img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs welcome">
</p>

<p align="center">
  <img src="assets/demo.gif" alt="OpenBucket demo" width="100%">
</p>

OpenBucket lists and downloads the full contents of an open bucket, in parallel,
with a live progress UI. It speaks both **Amazon S3** (and any S3-compatible XML
API) and **Oracle Cloud Object Storage** (native JSON API), auto-detecting the
backend from the URL and handling each one's pagination for you.

## Features

- 🪣 **Two backends, auto-detected** — Amazon S3 / S3-compatible (XML) and Oracle
  Cloud Object Storage (JSON), each with full pagination.
- ⚡ **Parallel downloads** with a live `rich` progress bar (count, size, speed, ETA).
- 🗂️ **Listing cache** — list a 500k-object bucket once, reuse it on the next run.
- ⏯️ **Resume** — already-downloaded files are skipped; atomic writes mean an
  interrupted run never leaves a corrupt file behind.
- 🔎 **Extension filters** — skip some (`--blacklist`) or keep only some (`--whitelist`).
- 🎯 **Server-side prefix** (`--prefix`) to narrow huge buckets without listing everything.
- 🧵 Configurable threads, timeout, retries, and rotating User-Agents.

## Installation

```bash
git clone https://github.com/thezakman/OpenBucket.git
cd OpenBucket
pip install .
```

This installs the `openbucket` command. For development use `pip install -e .`.
You can also run it without installing:

```bash
pip install -r requirements.txt
python -m openbucket <bucket_url>
```

## Usage

```
usage: openbucket [-h] [--blacklist BLACKLIST] [--whitelist WHITELIST]
                  [--prefix PREFIX] [--threads THREADS] [--output OUTPUT]
                  [--timeout TIMEOUT] [--list-only] [--overwrite] [--refresh]
                  [--no-cache] [--cache-ttl HOURS] [--quiet] [--version]
                  bucket_url

positional arguments:
  bucket_url            URL of the bucket (listing endpoint)

options:
  --blacklist BLACKLIST Comma-separated extensions to skip (e.g. jpg,png,mp4)
  --whitelist, -w       Download ONLY these extensions (e.g. pdf,csv)
  --prefix, -p          List only objects under this prefix (server-side)
  --threads, -t         Download threads (default: 10)
  --output, -o          Output folder
  --timeout             Request timeout in seconds
  --list-only, -l       List objects only, without downloading
  --overwrite           Re-download files that already exist (default: skip/resume)
  --refresh             Ignore the cache and re-list the bucket from scratch
  --no-cache            Don't read or write the listing cache
  --cache-ttl HOURS     Listing-cache lifetime in hours (0 = never expires; default: 24)
  --quiet, -q           Do not print the banner
  --version             Show the version and exit
```

### Examples

```bash
# Amazon S3 (or S3-compatible)
openbucket https://mybucket.s3.amazonaws.com/

# Oracle Cloud Object Storage — use the /o/ listing endpoint
openbucket https://objectstorage.<region>.oraclecloud.com/n/<namespace>/b/<bucket>/o/

# Just list, don't download
openbucket <bucket_url> --list-only

# Filter by extension, custom folder, more threads
openbucket <bucket_url> --blacklist jpg,png,gif -o ./loot -t 20
openbucket <bucket_url> --whitelist pdf,csv          # only PDFs and CSVs

# Narrow a huge bucket server-side, then resume later
openbucket <bucket_url> --prefix backups/2024/
```

### Caching & resuming

Listing a huge bucket is expensive — the sample bucket in the demo has 500k+
objects, which is dozens of paginated requests. OpenBucket makes re-runs cheap:

- **Listing cache** — the full object list is saved under `<output>/.openbucket/`
  and reused on the next run (up to `--cache-ttl` hours). Because the cache stores
  the *unfiltered* list, you can change `--blacklist`/`--whitelist` between runs
  and it re-filters instantly, with no new listing requests. Pass `--refresh` to
  force a fresh listing.
- **Resume** — files already present on disk are skipped, so an interrupted run
  just picks up where it left off. Downloads are written atomically (`.part` →
  rename), so a half-finished file is never mistaken for a complete one. Pass
  `--overwrite` to re-download everything.

`Ctrl+C` cancels cleanly, even mid-download of a very large bucket.

> **Note:** extension filtering is client-side — neither S3 nor Oracle can filter
> a listing by file extension, only by prefix. Use `--prefix` to cut down the
> listing at the source; the cache handles the rest.

## Use as a library

The core logic is UI-free and importable:

```python
from openbucket import list_bucket, download_keys

backend, base, keys = list_bucket("https://.../o/")
download_keys(keys, base, out_folder="./dump")
```

## Authorized use only

OpenBucket is for security research, authorized penetration tests, bug-bounty
scope, and recovering your own data. Only point it at buckets you own or are
explicitly permitted to access.

## Contributing

Issues are welcome and pull requests are appreciated.

### Contributors
  * [TheZakMan](https://tzm.ink/)

## License

[MIT](LICENSE)
