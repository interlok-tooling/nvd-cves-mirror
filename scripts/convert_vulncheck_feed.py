#!/usr/bin/env python3

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Convert VulnCheck NVD++ backup ZIP files into a Dependency Check-compatible mirror feed."
    )
    parser.add_argument("--api-token", help="VulnCheck API token used to fetch the backup index")
    parser.add_argument(
        "--backup-index-url",
        default="https://api.vulncheck.com/v3/backup/nist-nvd2",
        help="VulnCheck backup index URL",
    )
    parser.add_argument(
        "--download-dir",
        help="Directory used to download backup ZIP files when --api-token is supplied",
    )
    parser.add_argument(
        "--input-zip",
        action="append",
        default=[],
        help="Path to a local VulnCheck backup ZIP file; may be supplied multiple times",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where the converted nvd_api_cache output will be written",
    )
    parser.add_argument(
        "--previous-cache-dir",
        help="Path to a previous nvd_api_cache directory used to compute the modified feed incrementally",
    )
    parser.add_argument(
        "--branch-readme-mode",
        choices=["canary", "production"],
        default="canary",
        help="Controls the README text written alongside the generated cache",
    )
    return parser.parse_args()


def fetch_backup_zips(api_token, backup_index_url, download_dir):
    request = urllib.request.Request(
        backup_index_url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_token}",
        },
    )
    with urllib.request.urlopen(request) as response:
        index = json.load(response)

    urls = [entry["url"] for entry in index.get("data", []) if entry.get("url")]
    if not urls:
        raise RuntimeError("Backup index did not contain any download URLs")

    download_path = Path(download_dir)
    download_path.mkdir(parents=True, exist_ok=True)

    zip_paths = []
    for url in urls:
        file_name = Path(urllib.parse.urlparse(url).path).name
        target = download_path / file_name
        with urllib.request.urlopen(url) as response, target.open("wb") as output_handle:
            shutil.copyfileobj(response, output_handle)
        zip_paths.append(target)
    return zip_paths


def parse_timestamp(value):
    if value.endswith("Z"):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_timestamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def format_feed_timestamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "")


def year_from_item(item):
    published = item.get("cve", {}).get("published")
    if published:
        return str(max(2002, parse_timestamp(published).year))
    cve_id = item.get("cve", {}).get("id", "")
    raise RuntimeError(f"Unable to determine year for item {cve_id!r}")


def last_modified_from_item(item):
    value = item.get("cve", {}).get("lastModified")
    if not value:
        raise RuntimeError(f"Missing lastModified for item {item.get('cve', {}).get('id', '<unknown>')}")
    return parse_timestamp(value)


def load_previous_properties(previous_cache_dir):
    if not previous_cache_dir:
        return None
    properties_path = Path(previous_cache_dir) / "cache.properties"
    if not properties_path.exists():
        return None

    properties = {}
    with properties_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            properties[key] = value.replace("\\:", ":")
    return properties


def cache_header(total_results, timestamp):
    return {
        "resultsPerPage": total_results,
        "startIndex": 0,
        "totalResults": total_results,
        "format": "NVD_CVE",
        "version": "2.0",
        "timestamp": timestamp,
    }


def write_feed(raw_items_path, total_results, timestamp, output_path):
    raw_json_path = output_path.with_suffix("")
    header = cache_header(total_results, timestamp)

    sha256 = hashlib.sha256()
    size = 0

    with raw_json_path.open("wb") as raw_handle:
        prefix = json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8")[:-1]
        prefix += b',"vulnerabilities":['
        raw_handle.write(prefix)
        sha256.update(prefix)
        size += len(prefix)

        with raw_items_path.open("rb") as items_handle:
            shutil.copyfileobj(items_handle, raw_handle)

        with raw_items_path.open("rb") as items_handle:
            while True:
                chunk = items_handle.read(1024 * 1024)
                if not chunk:
                    break
                sha256.update(chunk)
                size += len(chunk)

        suffix = b"]}"
        raw_handle.write(suffix)
        sha256.update(suffix)
        size += len(suffix)

    with raw_json_path.open("rb") as raw_handle, gzip.open(output_path, "wb") as gzip_handle:
        shutil.copyfileobj(raw_handle, gzip_handle)

    gz_size = output_path.stat().st_size
    raw_json_path.unlink()
    return size, gz_size, sha256.hexdigest()


def write_meta(meta_path, last_modified, size, gz_size, sha256):
    meta_path.write_text(
        "\n".join(
            [
                f"lastModifiedDate:{last_modified}",
                f"size:{size}",
                f"gzSize:{gz_size}",
                f"sha256:{sha256}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def write_branch_readme(output_dir, mode):
    if mode == "production":
        content = """## Data Source

CVE data in this cache is sourced from [VulnCheck NVD++](https://vulncheck.com/nvd2),
a free community service provided by VulnCheck Inc., which provides reliable access
to NIST National Vulnerability Database (NVD) data.

Original CVE data © NIST National Vulnerability Database (https://nvd.nist.gov).
"""
    else:
        content = """## Data Source

This branch is an experimental VulnCheck-backed canary feed for Dependency Check testing.

CVE data in this cache is sourced from [VulnCheck NVD++](https://vulncheck.com/nvd2),
a free community service provided by VulnCheck Inc., which provides reliable access
to NIST National Vulnerability Database (NVD) data.

Original CVE data © NIST National Vulnerability Database (https://nvd.nist.gov).
"""
    (Path(output_dir) / "README.md").write_text(content, encoding="utf-8")


def convert(zip_paths, output_dir, previous_cache_dir, branch_readme_mode):
    output_root = Path(output_dir)
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    cache_dir = output_root / "nvd_api_cache"
    cache_dir.mkdir()

    previous_properties = load_previous_properties(previous_cache_dir)
    previous_overall = None
    if previous_properties and previous_properties.get("lastModifiedDate"):
        previous_overall = parse_timestamp(previous_properties["lastModifiedDate"])

    work_dir = Path(tempfile.mkdtemp(prefix="vulncheck-convert-"))
    year_items = {}
    year_counts = defaultdict(int)
    year_last_modified = {}
    modified_items_path = work_dir / "modified-items.json"
    modified_handle = modified_items_path.open("w", encoding="utf-8")
    modified_first = True
    modified_count = 0
    modified_last_modified = None
    overall_last_modified = None

    try:
        for zip_path in sorted(Path(path) for path in zip_paths):
            with zipfile.ZipFile(zip_path) as archive:
                entry_names = sorted(
                    entry_name for entry_name in archive.namelist() if entry_name.endswith(".json.gz")
                )
                for entry_name in entry_names:
                    with archive.open(entry_name) as entry_handle:
                        with gzip.open(entry_handle, "rt", encoding="utf-8") as gzip_handle:
                            payload = json.load(gzip_handle)

                    for item in payload.get("vulnerabilities", []):
                        year = year_from_item(item)
                        item_last_modified = last_modified_from_item(item)
                        overall_last_modified = (
                            item_last_modified
                            if overall_last_modified is None or item_last_modified > overall_last_modified
                            else overall_last_modified
                        )
                        year_last_modified[year] = (
                            item_last_modified
                            if year not in year_last_modified or item_last_modified > year_last_modified[year]
                            else year_last_modified[year]
                        )

                        if year not in year_items:
                            year_items[year] = (work_dir / f"{year}.items.json").open("w", encoding="utf-8")
                        year_handle = year_items[year]
                        if year_counts[year] > 0:
                            year_handle.write(",")
                        json.dump(item, year_handle, separators=(",", ":"), ensure_ascii=False)
                        year_counts[year] += 1

                        if previous_overall is None or item_last_modified > previous_overall:
                            if not modified_first:
                                modified_handle.write(",")
                            json.dump(item, modified_handle, separators=(",", ":"), ensure_ascii=False)
                            modified_first = False
                            modified_count += 1
                            modified_last_modified = (
                                item_last_modified
                                if modified_last_modified is None or item_last_modified > modified_last_modified
                                else modified_last_modified
                            )

        for handle in year_items.values():
            handle.close()
        modified_handle.close()

        if overall_last_modified is None:
            raise RuntimeError("No vulnerabilities were found in the supplied backup ZIP files")

        feed_timestamp = format_feed_timestamp(overall_last_modified)
        timestamp = format_timestamp(overall_last_modified)
        property_lines = [
            f"# Generated {datetime.now(timezone.utc).strftime('%a %b %d %H:%M:%S UTC %Y')}",
            "prefix=nvdcve-",
        ]

        for year in sorted(year_counts):
            items_path = work_dir / f"{year}.items.json"
            feed_path = cache_dir / f"nvdcve-{year}.json.gz"
            size, gz_size, sha256 = write_feed(items_path, year_counts[year], feed_timestamp, feed_path)
            meta_timestamp = format_timestamp(year_last_modified[year])
            write_meta(cache_dir / f"nvdcve-{year}.meta", meta_timestamp, size, gz_size, sha256)
            property_lines.append(f"lastModifiedDate.{year}={meta_timestamp.replace(':', '\\:')}")

        modified_feed_path = cache_dir / "nvdcve-modified.json.gz"
        modified_meta_path = cache_dir / "nvdcve-modified.meta"

        if previous_overall is not None and previous_overall == overall_last_modified and previous_cache_dir:
            previous_cache = Path(previous_cache_dir)
            shutil.copy2(previous_cache / "nvdcve-modified.json.gz", modified_feed_path)
            shutil.copy2(previous_cache / "nvdcve-modified.meta", modified_meta_path)
            modified_property_timestamp = previous_properties.get("lastModifiedDate.modified", format_timestamp(overall_last_modified))
        else:
            if modified_count == 0:
                modified_last_modified = overall_last_modified
            size, gz_size, sha256 = write_feed(modified_items_path, modified_count, feed_timestamp, modified_feed_path)
            modified_property_timestamp = format_timestamp(modified_last_modified)
            write_meta(modified_meta_path, modified_property_timestamp, size, gz_size, sha256)

        property_lines.append(f"lastModifiedDate.modified={modified_property_timestamp.replace(':', '\\:')}")
        property_lines.append(f"lastModifiedDate={timestamp.replace(':', '\\:')}")
        (cache_dir / "cache.properties").write_text("\n".join(property_lines) + "\n", encoding="utf-8")
        write_branch_readme(output_root, branch_readme_mode)
    finally:
        for handle in year_items.values():
            try:
                if not handle.closed:
                    handle.close()
            except Exception:
                pass
        if not modified_handle.closed:
            modified_handle.close()
        shutil.rmtree(work_dir, ignore_errors=True)


def main():
    args = parse_args()

    zip_paths = [Path(path) for path in args.input_zip]
    if args.api_token:
        if not args.download_dir:
            raise RuntimeError("--download-dir is required when --api-token is supplied")
        zip_paths.extend(fetch_backup_zips(args.api_token, args.backup_index_url, args.download_dir))

    if not zip_paths:
        raise RuntimeError("No input ZIP files were provided")

    convert(zip_paths, args.output_dir, args.previous_cache_dir, args.branch_readme_mode)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)