# K5 Worksheet Fetcher

An on-demand tool for downloading free PDF worksheets from k5learning.com,
organized by target (grade/category), incremental across runs, and gated by
your explicit approval before anything downloads.

Currently configured targets (see `config/targets.py`):

- **kindergarten-simple-math** — Kindergarten > Simple Math (~350 PDFs)
- **full-math-worksheets** — full Math Worksheets site, grades 1-6 (likely a
  few thousand PDFs — run `scan` to see the real count before deciding)

## Requirements

Python 3 (stdlib only) + `curl` on PATH. No `pip install` needed.

## Usage

Run everything from this project's root directory.

```bash
# Safe, read-only: crawl a target and update its manifest. No downloads.
python3 run.py scan kindergarten-simple-math

# Show new-vs-already-downloaded counts for a target (no downloads).
python3 run.py plan kindergarten-simple-math

# Actually download what's missing (only run this once you're happy with `plan`).
python3 run.py fetch kindergarten-simple-math

# Zip up whatever's been downloaded for a target.
python3 run.py package kindergarten-simple-math

# Or do all four steps in one go, with an approval prompt before any download:
python3 run.py run kindergarten-simple-math
```

Use `all` instead of a target name to run a command across every configured
target. Add `--yes` to `run` to skip the interactive approval prompt (for
non-interactive use — you're still choosing to run it, so this is on you).

## How the approval gate works

`run` always does `scan` → `plan` → **stops and asks you** → `fetch` →
`package`. Nothing is downloaded until you type `y` at the prompt. If you
just want to see what's new without any risk of a download, use `scan` +
`plan` directly — those two commands never touch the filesystem beyond the
manifest.

## Incremental re-runs

Each target's manifest (`data/manifests/<target>.json`) records every PDF URL
seen on the last `scan`. `fetch` skips any file already present on disk
(non-zero size), so re-running the pipeline later only pulls new/missing
worksheets — it won't re-download the same 350 files every time.

## Project layout

```
k5-worksheet-fetcher/
├── run.py                 # CLI entrypoint — scan / plan / fetch / package / run
├── config/
│   └── targets.py         # target definitions (add new sections here, no code changes)
├── src/
│   ├── common.py          # curl-based fetch + link extraction
│   ├── crawler.py         # generic BFS subtree crawler → set of PDF URLs
│   ├── state.py           # per-target manifest load/save
│   ├── downloader.py      # rate-limited, resumable PDF download
│   └── packager.py        # zip a target's output folder
├── data/
│   ├── manifests/         # target_name.json — known PDF URLs + last scan time
│   └── output/            # downloaded PDFs, one subfolder per target, + zips
└── logs/
```

## Adding a new target

Add an entry to `TARGETS` in `config/targets.py` — no other code changes are
needed. See the comments in that file for `boundary_mode` (`prefix` vs
`sibling_exclude`) — it controls how the crawler decides which links belong
to the target's own subtree versus a different category on the site.

## Politeness / rate limiting

Requests are sequential (not parallel) with a configurable delay between
them (`config/targets.py` → `CRAWL`), matching what was validated manually
against k5learning.com's `robots.txt` (which allows crawling these paths).
Don't lower the delays without a reason to.
