"""
Getting source PDFs into the library — the three routes from the spec:

  1. Already-fetched K5 worksheets (727 of them sit on disk today)
  2. A Google Drive link (folder or single file)
  3. A PDF uploaded straight from the reviewer's machine

All three land in the same `sources` table, so everything downstream is
identical regardless of where a PDF came from. That is the whole point of
doing it this way — adding a fourth route later touches only this file.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import httpx
import pymupdf

from app.config import K5_OUTPUT_DIR, UPLOAD_DIR
from app.db import get_conn, log_activity, new_id, now


def _extract_text(path: Path) -> tuple[str, int]:
    try:
        doc = pymupdf.open(path)
        text = "\n\n".join(p.get_text() for p in doc)
        n = len(doc)
        doc.close()
        return text, n
    except Exception:
        return "", 0


def _store(filename: str, src_path: Path, origin: str, detail: str) -> dict:
    """Copy a PDF into the library and index it."""
    sid = new_id()
    stored = UPLOAD_DIR / f"{sid}.pdf"
    shutil.copyfile(src_path, stored)
    text, pages = _extract_text(stored)

    with get_conn() as c:
        c.execute(
            """INSERT INTO sources
                 (id, filename, stored_path, origin, origin_detail,
                  page_count, extracted_text, added_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (sid, filename, str(stored), origin, detail, pages, text, now()),
        )
    return {"id": sid, "filename": filename, "origin": origin, "page_count": pages}


# ── Route 1: the existing K5 library ───────────────────────────────
def list_k5_available() -> list[dict]:
    """What's already been fetched and is sitting on disk, uningested."""
    out = []
    if not K5_OUTPUT_DIR.is_dir():
        return out
    with get_conn() as c:
        known = {r["filename"] for r in
                  c.execute("SELECT filename FROM sources WHERE origin='k5'")}
    for category in sorted(K5_OUTPUT_DIR.iterdir()):
        if not category.is_dir():
            continue
        pdfs = sorted(category.glob("*.pdf"))
        out.append({
            "category": category.name,
            "total": len(pdfs),
            "already_added": sum(1 for p in pdfs if p.name in known),
            "sample": [p.name for p in pdfs[:4]],
        })
    return out


_BROWSE_CACHE_DIR = UPLOAD_DIR.parent / "browse_cache"
_BROWSE_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _browse_cache_path(category: str) -> Path:
    # category is always one of our own configured folder names, never
    # user input reaching a filesystem path — safe to use directly.
    return _BROWSE_CACHE_DIR / f"{category}.json"


def browse_k5_collection(category: str) -> list[dict]:
    """Every PDF inside one fetched category, for the folder-browser view —
    like opening a Finder folder and seeing what's inside before deciding
    what to bring in, rather than "add the first N alphabetically".

    Extracting text from every PDF to run the quality heuristic is slow
    for a large folder (373 files took long enough to feel like the UI
    had hung on first use) — so results are cached to disk, keyed by each
    file's modification time, and only re-extracted when a file is new or
    has actually changed. Re-opening the same folder afterwards is
    instant.
    """
    folder = K5_OUTPUT_DIR / category
    if not folder.is_dir():
        raise ValueError(f"No such collection: {category}")

    with get_conn() as c:
        known = {r["filename"] for r in
                  c.execute("SELECT filename FROM sources WHERE origin='k5'")}

    cache_path = _browse_cache_path(category)
    cache = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
        except (json.JSONDecodeError, OSError):
            cache = {}

    out = []
    changed = False
    for pdf in sorted(folder.glob("*.pdf")):
        mtime = pdf.stat().st_mtime
        cached = cache.get(pdf.name)
        if cached and cached.get("mtime") == mtime:
            likely = cached["likely_has_questions"]
        else:
            text = ""
            try:
                text, _ = _extract_text(pdf)
            except Exception:
                pass
            likely = looks_like_questions(text)
            cache[pdf.name] = {"mtime": mtime, "likely_has_questions": likely}
            changed = True

        out.append({
            "filename": pdf.name,
            "already_added": pdf.name in known,
            "likely_has_questions": likely,
            # A readable title guess from the filename, since these PDFs
            # don't have a title anywhere else visible before opening them.
            "title_guess": pdf.stem.replace("-", " ").replace("_", " ").title(),
        })

    if changed:
        cache_path.write_text(json.dumps(cache))
    return out


def import_from_k5(category: str, limit: int = 10) -> list[dict]:
    folder = K5_OUTPUT_DIR / category
    if not folder.is_dir():
        raise ValueError(f"No such collection: {category}")

    with get_conn() as c:
        known = {r["filename"] for r in
                  c.execute("SELECT filename FROM sources WHERE origin='k5'")}

    added = []
    for pdf in sorted(folder.glob("*.pdf")):
        if len(added) >= limit:
            break
        if pdf.name in known:
            continue
        added.append(_store(pdf.name, pdf, "k5", f"K5 · {category}"))

    log_activity("Worksheets added to library",
                  f"{len(added)} from {category.replace('_', ' ')}")
    return added


def import_k5_selected(category: str, filenames: list[str]) -> list[dict]:
    """Import exactly the files a person picked in the folder-browser,
    rather than the first N in alphabetical order."""
    folder = K5_OUTPUT_DIR / category
    if not folder.is_dir():
        raise ValueError(f"No such collection: {category}")

    with get_conn() as c:
        known = {r["filename"] for r in
                  c.execute("SELECT filename FROM sources WHERE origin='k5'")}

    added = []
    for name in filenames:
        # Reject anything that isn't a plain filename already known to be
        # in this folder — never build a path from unchecked user input.
        pdf = folder / name
        if name in known or "/" in name or not pdf.is_file() or pdf.suffix != ".pdf":
            continue
        added.append(_store(name, pdf, "k5", f"K5 · {category}"))

    log_activity("Worksheets added to library",
                  f"{len(added)} hand-picked from {category.replace('_', ' ')}")
    return added


def preview_k5_file(category: str, filename: str) -> Path:
    """Path to a fetched-but-not-yet-imported PDF, for the browser's View
    button. Filename is validated against the real folder contents so this
    can never be used to read an arbitrary path on disk."""
    folder = K5_OUTPUT_DIR / category
    path = folder / filename
    if "/" in filename or not path.is_file() or path.suffix != ".pdf" or not folder.is_dir():
        raise ValueError("That file isn't in this collection.")
    return path


def remove_from_k5(category: str, count: int, cascade: bool = False) -> dict:
    """Take N worksheets from a collection back out of the library.

    Removes the most recently added first, so repeatedly pressing Add
    then Remove returns you to where you started rather than eating into
    an older selection.
    """
    with get_conn() as c:
        rows = c.execute(
            """SELECT s.id, s.stored_path,
                       (SELECT COUNT(*) FROM batches b WHERE b.source_id = s.id) AS used
                  FROM sources s
                 WHERE s.origin='k5' AND s.origin_detail=?
                 ORDER BY used ASC, s.added_at DESC""",
            (f"K5 \u00b7 {category}",),
        ).fetchall()

    # Untouched ones go first, so a plain "remove 10" never destroys
    # generated work while unused sources are still sitting there.
    unused = [r for r in rows if not r["used"]]
    used = [r for r in rows if r["used"]]

    take = unused[:count]
    kept_back = 0
    if len(take) < count:
        shortfall = count - len(take)
        if cascade:
            take += used[:shortfall]
        else:
            kept_back = min(shortfall, len(used))

    with get_conn() as c:
        for r in take:
            _purge_source(c, r["id"])
    for r in take:
        Path(r["stored_path"]).unlink(missing_ok=True)

    if take:
        log_activity("Worksheets removed from library",
                      f"{len(take)} from {category.replace('_', ' ')}")
    return {"removed": len(take), "kept_back": kept_back}


# ── Route 2: Google Drive link ─────────────────────────────────────
_DRIVE_FILE = re.compile(r"/file/d/([A-Za-z0-9_-]{20,})")
_DRIVE_ID_PARAM = re.compile(r"[?&]id=([A-Za-z0-9_-]{20,})")
_DRIVE_FOLDER = re.compile(r"/folders/([A-Za-z0-9_-]{20,})")


def import_from_drive(link: str) -> list[dict]:
    """Pull a PDF from a Google Drive share link.

    Only works for files shared as "anyone with the link". A folder link
    cannot be listed without Drive API credentials, so that case returns a
    clear explanation rather than a silent empty result.
    """
    link = link.strip()
    if _DRIVE_FOLDER.search(link):
        raise ValueError(
            "That's a folder link. Folder listing needs a Google Drive "
            "connection, which isn't set up yet — for now, open the folder "
            "and paste the link of an individual PDF, or upload the file "
            "directly."
        )

    m = _DRIVE_FILE.search(link) or _DRIVE_ID_PARAM.search(link)
    if not m:
        raise ValueError("That doesn't look like a Google Drive file link.")
    file_id = m.group(1)

    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=60)
        resp.raise_for_status()
    except Exception:
        raise ValueError(
            "Couldn't download that file. Check it's shared as "
            "'Anyone with the link'."
        )

    if not resp.content.startswith(b"%PDF"):
        raise ValueError(
            "That link didn't return a PDF. If the file is large, Drive "
            "shows a virus-scan warning page instead — download it and "
            "upload the file directly."
        )

    tmp = UPLOAD_DIR / f"_drive_{file_id}.pdf"
    tmp.write_bytes(resp.content)
    try:
        rec = _store(f"drive-{file_id}.pdf", tmp, "drive", link)
    finally:
        tmp.unlink(missing_ok=True)

    log_activity("Worksheet added from Drive", rec["filename"])
    return [rec]


# ── Route 3: direct upload ─────────────────────────────────────────
def import_uploaded(filename: str, content: bytes) -> dict:
    if not content.startswith(b"%PDF"):
        raise ValueError("That file isn't a PDF.")
    tmp = UPLOAD_DIR / f"_up_{new_id()}.pdf"
    tmp.write_bytes(content)
    try:
        rec = _store(filename, tmp, "upload", "Uploaded")
    finally:
        tmp.unlink(missing_ok=True)
    log_activity("Worksheet uploaded", filename)
    return rec


# ── Templates ──────────────────────────────────────────────────────
# A template is the LOOK of a worksheet, not its content: the layout a
# finished sheet should follow. Kept separate from sources for that
# reason — a source supplies questions, a template supplies form.
TEMPLATE_DIR = UPLOAD_DIR.parent / "templates"
TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_TEMPLATE_TYPES = {".pdf": "pdf", ".docx": "docx"}


def import_template(filename: str, content: bytes, grade: int | None) -> dict:
    ext = Path(filename).suffix.lower()
    kind = ALLOWED_TEMPLATE_TYPES.get(ext)
    if kind is None:
        raise ValueError("Templates must be a PDF or a Word (.docx) file.")

    tid = new_id()
    stored = TEMPLATE_DIR / f"{tid}{ext}"
    stored.write_bytes(content)

    with get_conn() as c:
        c.execute(
            """INSERT INTO templates (id, name, grade, stored_path, file_kind, added_at)
               VALUES (?,?,?,?,?,?)""",
            (tid, filename, grade, str(stored), kind, now()),
        )
    log_activity("Template added", filename)
    return {"id": tid, "name": filename, "grade": grade, "file_kind": kind}


def list_templates() -> list[dict]:
    with get_conn() as c:
        rows = c.execute(
            "SELECT id, name, grade, file_kind, added_at FROM templates "
            "ORDER BY added_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_template(template_id: str) -> dict | None:
    with get_conn() as c:
        row = c.execute("SELECT * FROM templates WHERE id=?", (template_id,)).fetchone()
    return dict(row) if row else None


def delete_template(template_id: str) -> None:
    t = get_template(template_id)
    if t:
        Path(t["stored_path"]).unlink(missing_ok=True)
    with get_conn() as c:
        c.execute("DELETE FROM templates WHERE id=?", (template_id,))


# ── Integrity repair ───────────────────────────────────────────────
def repair_missing_files() -> dict:
    """Restore sources whose PDF vanished but whose row survived.

    This state was created by an earlier bug: Remove unlinked the file
    BEFORE the database delete, so when the delete hit a foreign-key
    constraint the file was already gone and the row stayed. The row then
    looks fine in the library but every View or generate against it fails
    with "no longer in the library".

    A K5 source can be restored outright — the original is still in the
    fetcher's output folder. Anything uploaded or pulled from Drive cannot
    be, so it is reported rather than silently left broken.
    """
    restored, unrecoverable = [], []
    with get_conn() as c:
        rows = c.execute(
            "SELECT id, filename, stored_path, origin, origin_detail FROM sources"
        ).fetchall()

    for r in rows:
        if Path(r["stored_path"]).exists():
            continue
        original = None
        if r["origin"] == "k5" and r["origin_detail"]:
            category = r["origin_detail"].split("\u00b7")[-1].strip()
            candidate = K5_OUTPUT_DIR / category / r["filename"]
            if candidate.exists():
                original = candidate
        if original:
            shutil.copyfile(original, r["stored_path"])
            restored.append(r["filename"])
        else:
            unrecoverable.append({"id": r["id"], "filename": r["filename"]})

    if restored:
        log_activity("Library repaired", f"{len(restored)} file(s) restored")
    return {"restored": restored, "unrecoverable": unrecoverable}


# ── Source quality ──────────────────────────────────────────────────
def looks_like_questions(text: str) -> bool:
    """Rough check for whether a source has an actual question to mine.

    Real case this exists for: K5's "color by number" sheets extract to
    just a colour key and an instruction line ("Color the picture using
    the number key") — no question, no answer, nothing to regenerate.
    Fed through the pipeline anyway, the model faithfully produces a
    degenerate "How many?" for every question, which the validator then
    (correctly) rejects. Every one of those attempts still costs real
    API quota for a result that was never going to work.

    NOTE: length and "contains a '?'" were tried first and both gave
    false positives — plenty of legitimate K5 worksheets use imperative
    phrasing ("Subtract.", "Circle the heavier object.") with no question
    mark, and are as short as 160 characters. Neither signal separates a
    real worksheet from a coloring activity. What actually distinguishes
    a colour-by-number sheet is its content: a repeated colour key
    ("1 – Blue", "2 – Red", ...) and an instruction to colour a picture.
    Detect that shape directly instead of guessing from a proxy.

    This is advisory, not a hard block — a false negative here should
    still be generatable, just without the warning badge.
    """
    t = (text or "")
    tl = t.lower()

    color_key_lines = len(re.findall(r"\b\d+\s*[-–]\s*[a-z]+\b", tl))
    if color_key_lines >= 3:
        return False
    if re.search(r"colou?r[\s-]*by[\s-]*number", tl):
        return False
    # Broader family of the same activity: "colour the number/box", not
    # just "colour the picture" — same root cause (nothing to ask about).
    if any(phrase in tl for phrase in (
        "using the number key", "colour the picture", "color the picture",
        "color the number", "colour the number", "color the big number",
        "colour the big number",
    )):
        return False

    return True


# ── Library listing ────────────────────────────────────────────────
ORIGIN_LABEL = {"k5": "Fetched", "drive": "From Drive", "upload": "Uploaded"}


def list_sources() -> list[dict]:
    with get_conn() as c:
        rows = c.execute(
            """SELECT id, filename, origin, origin_detail, page_count,
                      extracted_text, added_at
                 FROM sources ORDER BY added_at DESC"""
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["likely_has_questions"] = looks_like_questions(d.pop("extracted_text"))
        d["origin_label"] = ORIGIN_LABEL.get(r["origin"], "Added")
        out.append(d)
    return out


def get_source(source_id: str) -> dict | None:
    with get_conn() as c:
        row = c.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    return dict(row) if row else None


def source_usage(source_id: str) -> dict:
    """How much generated work hangs off this source."""
    with get_conn() as c:
        batches = c.execute("SELECT COUNT(*) n FROM batches WHERE source_id=?",
                             (source_id,)).fetchone()["n"]
        sheets = c.execute(
            """SELECT COUNT(*) n FROM worksheets
                WHERE batch_id IN (SELECT id FROM batches WHERE source_id=?)""",
            (source_id,)).fetchone()["n"]
        approved = c.execute(
            """SELECT COUNT(*) n FROM worksheets
                WHERE review_status='approved'
                  AND batch_id IN (SELECT id FROM batches WHERE source_id=?)""",
            (source_id,)).fetchone()["n"]
    return {"batches": batches, "worksheets": sheets, "approved": approved}


class SourceInUse(ValueError):
    """Raised instead of letting a raw FOREIGN KEY error reach the screen."""

    def __init__(self, message: str, usage: dict):
        super().__init__(message)
        self.usage = usage


def _purge_source(c, source_id: str) -> None:
    """Delete a source and everything generated from it, in FK-safe order."""
    c.execute(
        """DELETE FROM revisions WHERE worksheet_id IN (
               SELECT w.id FROM worksheets w
                 JOIN batches b ON b.id = w.batch_id
                WHERE b.source_id = ?)""", (source_id,))
    c.execute(
        """DELETE FROM worksheets WHERE batch_id IN (
               SELECT id FROM batches WHERE source_id = ?)""", (source_id,))
    c.execute("DELETE FROM batches WHERE source_id=?", (source_id,))
    c.execute("DELETE FROM sources WHERE id=?", (source_id,))


def delete_source(source_id: str, cascade: bool = False) -> dict:
    """Remove one source from the library.

    A source that has been used to generate worksheets is referenced by
    `batches.source_id`, so deleting it outright trips the foreign key and
    SQLite raises "FOREIGN KEY constraint failed" — a database message no
    reviewer should ever see. Instead: say what depends on it, and only
    remove that work when explicitly told to.
    """
    src = get_source(source_id)
    if not src:
        return {"removed": False}

    usage = source_usage(source_id)
    if usage["batches"] and not cascade:
        raise SourceInUse(
            f"{src['filename']} has {usage['worksheets']} worksheet(s) made "
            f"from it"
            + (f", {usage['approved']} of them approved" if usage["approved"] else "")
            + ". Removing it removes those too.",
            usage)

    with get_conn() as c:
        _purge_source(c, source_id)
    Path(src["stored_path"]).unlink(missing_ok=True)
    log_activity("Worksheet removed from library", src["filename"])
    return {"removed": True, **usage}
