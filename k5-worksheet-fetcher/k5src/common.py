"""Shared HTTP fetch and link-extraction helpers, built on curl (no pip deps)."""
import re
import subprocess
import time
from urllib.parse import urljoin, urlparse

HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)


def fetch(url, user_agent, timeout=20, retries=2, delay=0.3):
    """GET a URL via curl. Returns (html, status_code_str). Empty html on failure."""
    status = "unknown"
    for attempt in range(retries):
        try:
            out = subprocess.run(
                ["curl", "-sL", "-A", user_agent, "-w", "\n__STATUS__%{http_code}",
                 "--max-time", str(timeout), url],
                capture_output=True, text=True, timeout=timeout + 10,
            )
            text = out.stdout
            if "__STATUS__" in text:
                html, status = text.rsplit("__STATUS__", 1)
                status = status.strip()
            else:
                html, status = text, "unknown"
            if status == "200":
                time.sleep(delay)
                return html, status
        except Exception as e:
            status = f"ERROR:{e}"
        time.sleep(0.5)
    time.sleep(delay)
    return "", status


def extract_links(html, base_url):
    """Return absolute URLs for every href in html, skipping anchors/js/mailto."""
    out = []
    for h in HREF_RE.findall(html):
        h = h.strip()
        if not h or h.startswith("#") or h.startswith("javascript:") or h.startswith("mailto:"):
            continue
        out.append(urljoin(base_url, h))
    return out


def path_of(url):
    return urlparse(url).path.rstrip("/")


def filename_of(url):
    return url.rstrip("/").split("/")[-1]
