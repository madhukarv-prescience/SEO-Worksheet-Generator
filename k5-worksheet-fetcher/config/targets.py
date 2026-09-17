"""
Target definitions for the K5 Learning worksheet fetcher.

Each entry in TARGETS describes one section of k5learning.com to crawl
independently. Add/remove/edit targets here — no code changes needed.

boundary_mode explained:
- "prefix": only follow links whose path starts with the root (or one of the
  sub_roots). Safe default for sites that nest cleanly, e.g. the grade-based
  Math Worksheets site (/free-math-worksheets/first-grade-1/addition/...).
- "sibling_exclude": some K5 sections (e.g. the kindergarten hub) cross-link
  to short, top-level-looking paths that are actually part of the *current*
  category's content (like /numbers or /counting under numbers-counting),
  not separate categories. This mode follows those, and only excludes a link
  if it matches a *known sibling category slug* from `sibling_slugs`.
"""
import os

TARGETS = {
    "kindergarten-simple-math": {
        "hub_path": "/free-preschool-kindergarten-worksheets",
        "root_path": "/free-preschool-kindergarten-worksheets/simple-math",
        "boundary_mode": "sibling_exclude",
        "sibling_slugs": [
            "numbers-counting", "reading-comprehension", "letters-alphabet",
            "phonics", "vocabulary", "writing", "shapes", "simple-math",
            "science", "colors", "social-emotional", "activities-concepts",
        ],
        "pdf_pattern": r"/worksheets/.*\.pdf$",
        "output_subdir": "kindergarten_simple_math",
        "description": "Kindergarten > Simple Math (addition, subtraction, patterns, "
                        "measurement, money, graphing, comparisons, sorting, ~350 PDFs)",
    },

    "numbers-counting": {
        "hub_path": "/free-preschool-kindergarten-worksheets",
        "root_path": "/free-preschool-kindergarten-worksheets/numbers-counting",
        "boundary_mode": "sibling_exclude",
        "sibling_slugs": [
            "numbers-counting", "reading-comprehension", "letters-alphabet",
            "phonics", "vocabulary", "writing", "shapes", "simple-math",
            "science", "colors", "social-emotional", "activities-concepts",
        ],
        "pdf_pattern": r"/worksheets/.*\.pdf$",
        "output_subdir": "kindergarten_numbers_counting",
        "description": "Kindergarten > Numbers & Counting (numbers 1-10, counting, "
                        "tens/ones, tracing numbers, ordinal numbers, more/less, "
                        "odd/even, ~373 PDFs)",
    },

    "full-math-worksheets": {
        "hub_path": "/free-math-worksheets",
        "sub_roots": [
            "/free-math-worksheets/first-grade-1",
            "/free-math-worksheets/second-grade-2",
            "/free-math-worksheets/third-grade-3",
            "/free-math-worksheets/fourth-grade-4",
            "/free-math-worksheets/fifth-grade-5",
            "/free-math-worksheets/sixth-grade-6",
            # Deliberately NOT crawling /free-math-worksheets/topics or
            # /math-drills — those re-list the same worksheets under a
            # different navigation path. Crawling them too would just mean
            # more page fetches for zero new PDFs (the URL set dedupes
            # anyway), so we skip them to keep the crawl faster.
        ],
        "boundary_mode": "prefix",
        "pdf_pattern": r"/worksheets/.*\.pdf$",
        "output_subdir": "full_math_worksheets",
        "description": "Full K5 Math Worksheets site, grades 1-6 (likely several "
                        "thousand PDFs — scan first to see the real count)",
    },
}

CRAWL = {
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "rate_limit_seconds": 0.3,       # delay between page fetches while crawling
    "download_delay_seconds": 0.25,  # delay between PDF downloads
    "max_pages_per_target": 3000,    # safety cap so a crawl can't run away forever
    "retries": 2,
    "timeout_seconds": 20,
}

# Anchored to THIS project's own folder, not the current working directory.
# Without this, running `python3 run.py list` from the repo root (instead of
# from k5-worksheet-fetcher/) would silently look in the wrong place and
# report "never scanned / not fetched" even when hundreds of PDFs exist —
# a nasty, non-erroring failure mode. Absolute paths remove that trap
# entirely, and are safe for the sources/ adapter too: pathlib's `/`
# operator returns the right-hand operand when it is already absolute.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OUTPUT = {
    "base_dir": os.path.join(_PROJECT_ROOT, "data", "output"),
    "manifest_dir": os.path.join(_PROJECT_ROOT, "data", "manifests"),
}
