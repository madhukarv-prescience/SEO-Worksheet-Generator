#!/usr/bin/env python3
"""
K5 Learning worksheet fetcher — on-demand CLI.

Usage:
    python3 run.py scan    [target|all]     # crawl only, updates the manifest, no downloads
    python3 run.py plan    [target|all]     # show new-vs-already-have counts (no downloads)
    python3 run.py fetch   [target|all]     # download what's missing (rate-limited, resumable)
    python3 run.py package [target|all]     # zip a target's downloaded output
    python3 run.py run     [target|all]     # scan -> plan -> ASK YOU TO APPROVE -> fetch -> package

Targets are defined in config/targets.py. Nothing is downloaded without
either passing through the `run` command's approval prompt, or you
explicitly calling `fetch` yourself.
"""
import argparse
import os
import sys
import time

from config.targets import TARGETS, CRAWL, OUTPUT
from k5src import crawler, state, downloader, packager


def resolve_targets(name):
    if name == "all":
        return list(TARGETS.keys())
    if name not in TARGETS:
        print(f"Unknown target '{name}'. Available: {', '.join(TARGETS)}")
        sys.exit(1)
    return [name]


def cmd_scan(args):
    for name in resolve_targets(args.target):
        cfg = TARGETS[name]
        print(f"\n=== SCAN: {name} ===")
        print(f"  {cfg.get('description', '')}")

        def progress(n, pages, pdfs, queue, _name=name):
            if pages % 10 == 0:
                print(f"  ...{pages} pages crawled, {pdfs} pdfs found, {queue} queued")

        pdfs, pages, failures = crawler.crawl_target(name, cfg, CRAWL, progress=progress)
        state.save_manifest(OUTPUT["manifest_dir"], name, pdfs,
                             timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"))
        print(f"  Done: {pages} pages crawled, {len(pdfs)} unique PDFs, "
              f"{len(failures)} fetch failures")
        if failures:
            fail_path = os.path.join(OUTPUT["manifest_dir"], f"{name}_scan_failures.txt")
            with open(fail_path, "w") as f:
                f.write("\n".join(failures))
            print(f"  Failures logged to {fail_path}")


def cmd_plan(args):
    any_missing_manifest = False
    for name in resolve_targets(args.target):
        cfg = TARGETS[name]
        manifest = state.load_manifest(OUTPUT["manifest_dir"], name)
        urls = set(manifest["urls"])
        dest_dir = os.path.join(OUTPUT["base_dir"], cfg["output_subdir"])
        existing_files = set(os.listdir(dest_dir)) if os.path.isdir(dest_dir) else set()
        missing = [u for u in urls if u.rstrip("/").split("/")[-1] not in existing_files]

        print(f"\n=== PLAN: {name} ===")
        if not urls:
            print("  No manifest yet — run `scan` first.")
            any_missing_manifest = True
            continue
        print(f"  Manifest: {len(urls)} known PDFs (last scan: {manifest['last_scan']})")
        print(f"  Already on disk: {len(urls) - len(missing)}")
        print(f"  Would download: {len(missing)}")
    return not any_missing_manifest


def cmd_fetch(args):
    for name in resolve_targets(args.target):
        cfg = TARGETS[name]
        manifest = state.load_manifest(OUTPUT["manifest_dir"], name)
        urls = set(manifest["urls"])
        if not urls:
            print(f"No manifest for '{name}' — run `scan` first.")
            continue
        dest_dir = os.path.join(OUTPUT["base_dir"], cfg["output_subdir"])
        print(f"\n=== FETCH: {name} -> {dest_dir} ===")
        result = downloader.download_pdfs(
            urls, dest_dir, CRAWL["user_agent"],
            delay=CRAWL.get("download_delay_seconds", 0.25),
        )
        print(f"  OK: {len(result['ok'])}, already-had: {len(result['skipped'])}, "
              f"failed: {len(result['failed'])}")
        if result["failed"]:
            fail_path = os.path.join(OUTPUT["manifest_dir"], f"{name}_download_failures.txt")
            with open(fail_path, "w") as f:
                for u, code in result["failed"]:
                    f.write(f"{code}\t{u}\n")
            print(f"  Failures logged to {fail_path}")


def cmd_package(args):
    for name in resolve_targets(args.target):
        cfg = TARGETS[name]
        dest_dir = os.path.join(OUTPUT["base_dir"], cfg["output_subdir"])
        if not os.path.isdir(dest_dir) or not os.listdir(dest_dir):
            print(f"Nothing downloaded yet for '{name}' — run `fetch` first.")
            continue
        zip_path = os.path.join(OUTPUT["base_dir"], f"{cfg['output_subdir']}.zip")
        packager.zip_dir(dest_dir, zip_path)
        size_mb = os.path.getsize(zip_path) / (1024 * 1024)
        print(f"Zipped {name} -> {zip_path} ({size_mb:.1f} MB)")


def cmd_run(args):
    """scan -> plan -> approval prompt -> fetch -> package. This is the one
    command that can actually download files, and it always stops for your
    go-ahead first unless --yes is passed explicitly."""
    cmd_scan(args)
    ok = cmd_plan(args)
    if not ok:
        return
    if not args.yes:
        resp = input("\nProceed with download for the above target(s)? [y/N] ").strip().lower()
        if resp != "y":
            print("Aborted — no files downloaded.")
            return
    cmd_fetch(args)
    cmd_package(args)


def cmd_list(args):
    """Show every configured target and whether it's been fetched yet."""
    print(f"{len(TARGETS)} configured target(s):\n")
    for name, cfg in TARGETS.items():
        dest_dir = os.path.join(OUTPUT["base_dir"], cfg["output_subdir"])
        n_local = len([f for f in os.listdir(dest_dir) if f.endswith(".pdf")]) \
            if os.path.isdir(dest_dir) else 0
        manifest = state.load_manifest(OUTPUT["manifest_dir"], name)
        n_known = len(manifest["urls"])
        status = f"{n_local} PDFs on disk" if n_local else "not fetched yet"
        if n_known:
            status += f", {n_known} known from last scan ({manifest['last_scan']})"
        else:
            status += ", never scanned"
        print(f"  {name}")
        print(f"      {cfg.get('description', '')}")
        print(f"      -> {status}\n")


def main():
    parser = argparse.ArgumentParser(description="K5 Learning worksheet fetcher")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="Show configured targets and their fetch status")
    p_list.set_defaults(func=cmd_list)

    for cmd_name, fn in [("scan", cmd_scan), ("plan", cmd_plan),
                          ("fetch", cmd_fetch), ("package", cmd_package)]:
        p = sub.add_parser(cmd_name)
        p.add_argument("target", nargs="?", default="all",
                        help=f"One of: {', '.join(TARGETS)}, or 'all'")
        p.set_defaults(func=fn)

    p = sub.add_parser("run", help="scan -> plan -> approval prompt -> fetch -> package")
    p.add_argument("target", nargs="?", default="all")
    p.add_argument("--yes", action="store_true",
                    help="Skip the interactive approval prompt (non-interactive use)")
    p.set_defaults(func=cmd_run)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
