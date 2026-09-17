"""Generic BFS crawler: walks a target's subtree(s) and collects PDF worksheet links.

Does NOT download anything — scan is a read-only, safe operation you can run
as often as you like.
"""
import re
from collections import deque

from k5src import common

BASE = "https://www.k5learning.com"


def crawl_target(target_name, target_cfg, crawl_cfg, progress=None):
    """
    Returns (pdf_urls: set[str], pages_crawled: int, failures: list[str]).
    """
    hub_path = target_cfg["hub_path"].rstrip("/")
    pdf_pattern = target_cfg.get("pdf_pattern", r"/worksheets/.*\.pdf$")
    boundary_mode = target_cfg.get("boundary_mode", "prefix")
    sibling_slugs = set(target_cfg.get("sibling_slugs", []))
    roots = target_cfg.get("sub_roots") or [target_cfg.get("root_path")]
    roots = [r.rstrip("/") for r in roots if r]

    ua = crawl_cfg["user_agent"]
    delay = crawl_cfg.get("rate_limit_seconds", 0.3)
    timeout = crawl_cfg.get("timeout_seconds", 20)
    retries = crawl_cfg.get("retries", 2)
    max_pages = crawl_cfg.get("max_pages_per_target", 3000)

    all_pdfs = set()
    failures = []
    pages_crawled = 0
    visited = set(roots)
    queue = deque(roots)

    while queue and pages_crawled < max_pages:
        p = queue.popleft()
        url = BASE + p
        html, status = common.fetch(url, ua, timeout=timeout, retries=retries, delay=delay)
        pages_crawled += 1
        if not html:
            failures.append(f"{status}\t{url}")
            continue

        links = common.extract_links(html, url)

        for l in links:
            if re.search(pdf_pattern, l, re.IGNORECASE):
                all_pdfs.add(l)

        for l in links:
            lp = common.path_of(l)
            if lp != hub_path and not lp.startswith(hub_path + "/"):
                continue  # outside this site section entirely

            if boundary_mode == "prefix":
                if not any(lp == r or lp.startswith(r + "/") for r in roots):
                    continue
            elif boundary_mode == "sibling_exclude":
                rest = lp[len(hub_path) + 1:] if lp.startswith(hub_path + "/") else ""
                segs = [s for s in rest.split("/") if s]
                if len(segs) == 1 and segs[0] in sibling_slugs and lp not in roots:
                    continue  # a different top-level category, skip

            if lp in visited:
                continue
            visited.add(lp)
            queue.append(lp)

        if progress:
            progress(target_name, pages_crawled, len(all_pdfs), len(queue))

    return all_pdfs, pages_crawled, failures
