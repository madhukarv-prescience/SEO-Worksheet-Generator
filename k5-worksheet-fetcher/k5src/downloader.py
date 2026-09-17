"""Rate-limited, resumable PDF downloader.

Idempotent: any file already present on disk (non-zero size) is skipped, so
re-running `fetch` after an interruption only pulls what's missing.
"""
import os
import subprocess
import time

from k5src import common


def download_pdfs(urls, dest_dir, user_agent, delay=0.25, timeout=20):
    os.makedirs(dest_dir, exist_ok=True)
    ok, failed, skipped = [], [], []

    for url in sorted(urls):
        fname = common.filename_of(url)
        out_path = os.path.join(dest_dir, fname)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            skipped.append(url)
            continue
        try:
            result = subprocess.run(
                ["curl", "-sL", "-A", user_agent, "--max-time", str(timeout),
                 "-o", out_path, "-w", "%{http_code}", url],
                capture_output=True, text=True, timeout=timeout + 10,
            )
            code = result.stdout.strip()
        except Exception as e:
            code = f"ERR:{e}"

        if code == "200":
            ok.append(url)
        else:
            failed.append((url, code))
            if os.path.exists(out_path):
                os.remove(out_path)
        time.sleep(delay)

    return {"ok": ok, "failed": failed, "skipped": skipped, "total": len(urls)}
