# SEO Math Worksheets

Fetches free source worksheets and turns them into new, validated,
Bhanzu-branded worksheets — reviewed and approved by a human before
anything goes out. See [ARCHITECTURE.md](ARCHITECTURE.md) for the full
system diagram.

## Two components

| | What it does | Needs a key? |
|---|---|---|
| [`k5-worksheet-fetcher/`](k5-worksheet-fetcher/README.md) | Crawls K5 Learning, downloads new worksheet PDFs, resumable | No |
| [`seo_math_worksheets/`](seo_math_worksheets/README.md) | The hosted tool: library → create → validate → review → export | Yes — see below |

## Quick start

```bash
# 1. Fetch some source worksheets (skip if you already have some)
cd k5-worksheet-fetcher
python3 run.py fetch kindergarten-simple-math

# 2. Run the tool
cd ../seo_math_worksheets
pip3 install -r requirements.txt
cp .env.example .env        # then paste in ONE API key
python3 -m uvicorn app.main:app --port 8020
```

Open **http://127.0.0.1:8020**. The **Setup** tab shows exactly which
provider is active without opening any file.

## This is not the BLC project

BLC Worksheets is a separate project with its own content, guidelines,
and credentials. Nothing here imports from it, shares its `.env`, or
reuses its code — keep it that way.
