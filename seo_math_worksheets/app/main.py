"""
Bhanzu SEO Math Worksheets — HTTP layer.

Run it:
    cd seo_math_worksheets && python3 -m uvicorn app.main:app --port 8020 --reload

Nothing backend-shaped is allowed to reach the browser: no provider
names, no API-key prompts, no record ids in user-facing text. The people
who use this hand its output to clients.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi import Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config, generate, ingest, jobs
from app.providers import canva
from app.validate import VERDICT_TEXT
from app.db import get_conn, init_db, log_activity, worksheet_to_dict
from app.export import worksheet_html
from app.framework import DIFFICULTY_LEVELS, GRADE_TEMPLATES, framework_summary
from app.generate import CLOSING_GOALS
from app.providers.llm import ProviderError

APP_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = APP_DIR / "static"

app = FastAPI(title="Bhanzu SEO Math Worksheets")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/exports", StaticFiles(directory=config.EXPORT_DIR), name="exports")
app.mount("/diagrams", StaticFiles(directory=config.DIAGRAM_DIR), name="diagrams")


@app.on_event("startup")
def _startup():
    init_db()
    # Self-heal any source whose file went missing (see
    # ingest.repair_missing_files for how that used to happen).
    report = ingest.repair_missing_files()
    if report["restored"]:
        print(f"[library] restored {len(report['restored'])} missing file(s): "
              f"{', '.join(report['restored'])}", flush=True)
    if report["unrecoverable"]:
        print(f"[library] {len(report['unrecoverable'])} source(s) cannot be "
              f"restored: {[u['filename'] for u in report['unrecoverable']]}", flush=True)


@app.exception_handler(Exception)
async def _unhandled(request, exc):
    """Never show a bare 'Internal Server Error' — it tells the user
    nothing and hides the cause during debugging."""
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/", response_class=HTMLResponse)
def index():
    """Served with cache-busting. Without this, edits to app.js silently
    do nothing in the browser and it looks like the fix didn't work."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for asset in ("styles.css", "app.js"):
        mtime = int((STATIC_DIR / asset).stat().st_mtime)
        html = html.replace(f"/static/{asset}", f"/static/{asset}?v={mtime}")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


# ── Setup / framework ──────────────────────────────────────────────
@app.get("/api/status")
def api_status():
    return {
        "ready": config.setup_complete(),
        "image_mode": config.active_image_strategy(),
        "grades": {k: v["label"] for k, v in GRADE_TEMPLATES.items()},
        "difficulties": {k: {"label": v["label"], "description": v["description"]}
                          for k, v in DIFFICULTY_LEVELS.items()},
        "framework": framework_summary(),
        "modes": {k: {"label": v["label"], "blurb": v["blurb"]}
                   for k, v in generate.MODES.items()},
        "verdicts": VERDICT_TEXT,
        "closing_goals": {k: v[0] for k, v in CLOSING_GOALS.items()},
        "max_sources_per_run": jobs.MAX_SOURCES_PER_RUN,
        "image_fallback": canva.availability(),
    }


# ── Library ────────────────────────────────────────────────────────
@app.get("/api/sources")
def api_sources():
    return {"sources": ingest.list_sources(), "collections": ingest.list_k5_available()}


@app.post("/api/sources/from-collection")
def api_from_collection(category: str = Form(...), limit: int = Form(10)):
    try:
        return {"added": ingest.import_from_k5(category, limit)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/sources/remove-from-collection")
def api_remove_from_collection(category: str = Form(...), count: int = Form(10),
                                cascade: bool = Form(False)):
    return ingest.remove_from_k5(category, max(1, count), cascade=cascade)


@app.get("/api/sources/{source_id}/file")
def api_source_file(source_id: str):
    """Serve the original PDF so it can be viewed before generating from it."""
    src = ingest.get_source(source_id)
    if not src or not Path(src["stored_path"]).exists():
        raise HTTPException(404, "That worksheet is no longer in the library.")
    return FileResponse(
        src["stored_path"], media_type="application/pdf",
        # inline, not attachment — this is "have a look", not "download".
        headers={"Content-Disposition": f'inline; filename="{src["filename"]}"'},
    )


@app.post("/api/sources/from-drive")
def api_from_drive(link: str = Form(...)):
    try:
        return {"added": ingest.import_from_drive(link)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/sources/upload")
async def api_upload(file: UploadFile = File(...)):
    try:
        return {"added": [ingest.import_uploaded(file.filename, await file.read())]}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/sources/{source_id}")
def api_delete_source(source_id: str, cascade: bool = False):
    try:
        return {"ok": True, **ingest.delete_source(source_id, cascade=cascade)}
    except ingest.SourceInUse as e:
        # 409, not 500 — this is a decision for the reviewer, not a fault.
        raise HTTPException(409, str(e))


@app.get("/api/sources/{source_id}/usage")
def api_source_usage(source_id: str):
    return ingest.source_usage(source_id)


# ── Templates (the LOOK a worksheet should follow) ─────────────────
@app.get("/api/templates")
def api_templates():
    return {"templates": ingest.list_templates()}


@app.post("/api/templates")
async def api_add_template(file: UploadFile = File(...), grade: str = Form("")):
    try:
        return {"added": ingest.import_template(
            file.filename, await file.read(),
            int(grade) if grade not in ("", "any") else None)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/templates/{template_id}/file")
def api_template_file(template_id: str):
    t = ingest.get_template(template_id)
    if not t or not Path(t["stored_path"]).exists():
        raise HTTPException(404, "That template is no longer here.")
    media = ("application/pdf" if t["file_kind"] == "pdf"
              else "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    return FileResponse(t["stored_path"], media_type=media,
                         headers={"Content-Disposition": f'inline; filename="{t["name"]}"'})


@app.delete("/api/templates/{template_id}")
def api_delete_template(template_id: str):
    ingest.delete_template(template_id)
    return {"ok": True}


@app.post("/api/closing-message")
def api_closing_message(topic: str = Form(...), grade: int = Form(3),
                         goal: str = Form("practise")):
    if not topic.strip():
        raise HTTPException(400, "Type a topic first.")
    try:
        return {"closing_message": generate.suggest_closing_message(
            topic.strip(), grade, goal)}
    except ProviderError as e:
        raise HTTPException(502, str(e))


# ── Generation ─────────────────────────────────────────────────────
@app.post("/api/generate")
def api_generate(
    source_id: str = Form(...),
    grade: int = Form(3),
    difficulty: str = Form("core"),
    variant_count: int = Form(2),
    question_count: int = Form(0),
    vary_dimensions: str = Form("surface_context"),
    closing_message: str = Form(""),
    extra_instructions: str = Form(""),
    mode: str = Form("reframe"),
    template_id: str = Form(""),
):
    source = ingest.get_source(source_id)
    if not source:
        raise HTTPException(404, "That worksheet isn't in the library any more.")
    if grade not in GRADE_TEMPLATES:
        raise HTTPException(400, "Pick a grade between 1 and 6.")
    if difficulty not in DIFFICULTY_LEVELS:
        raise HTTPException(400, "Unknown difficulty level.")
    modes = [m for m in mode.split(",") if m in generate.MODES]
    if not modes:
        raise HTTPException(400, "Pick how the worksheets should be built.")
    template = ingest.get_template(template_id) if template_id else None
    variant_count = max(1, min(10, variant_count))

    try:
        batch_id = generate.generate_batch(
            source=source, grade=grade, difficulty=difficulty,
            variant_count=variant_count,
            question_count=question_count or None,
            vary_dimensions=[d for d in vary_dimensions.split(",") if d],
            closing_message=closing_message,
            extra_instructions=extra_instructions,
            modes=modes,
            template=template,
        )
    except ProviderError as e:
        raise HTTPException(502, str(e))
    return {"batch_id": batch_id, **api_batch(batch_id)}


@app.post("/api/generate-all")
def api_generate_all(
    background: BackgroundTasks,
    grade: int = Form(3),
    difficulty: str = Form("core"),
    variant_count: int = Form(3),
    question_count: int = Form(0),
    vary_dimensions: str = Form("surface_context"),
    closing_message: str = Form(""),
    extra_instructions: str = Form(""),
    mode: str = Form("reframe"),
    template_id: str = Form(""),
    include_flagged: bool = Form(False),
):
    """Run the same settings across every source in the library.

    Returns immediately with a job id; the work happens on a worker thread
    and each source's batch is saved as it finishes, so Review fills in as
    the run progresses rather than all at the end.
    """
    busy = jobs.running_job()
    if busy:
        raise HTTPException(
            409,
            f"A run is already going — {busy['done']} of {busy['total']} done. "
            "Wait for it to finish before starting another.")

    sources = ingest.list_sources()
    if not sources:
        raise HTTPException(400, "Add some worksheets to the library first.")

    # Sources with no real question in them (e.g. K5 "colour by number"
    # activity sheets) reliably fail validation — every attempt is quota
    # spent on a result that was never going to work. Skip them by
    # default; the reviewer can opt back in.
    skipped_low_quality = 0
    if not include_flagged:
        n_before = len(sources)
        sources = [s for s in sources if s.get("likely_has_questions", True)]
        skipped_low_quality = n_before - len(sources)
    if not sources:
        raise HTTPException(
            400,
            "Every source in the library looks like an activity sheet with "
            "no question to build from (e.g. colour-by-number). Tick "
            "'include activity sheets anyway' to try them, or add a source "
            "with real questions.")

    if grade not in GRADE_TEMPLATES:
        raise HTTPException(400, "Pick a grade.")
    if difficulty not in DIFFICULTY_LEVELS:
        raise HTTPException(400, "Unknown difficulty level.")

    modes = [m for m in mode.split(",") if m in generate.MODES]
    if not modes:
        raise HTTPException(400, "Pick how the worksheets should be built.")

    capped = sources[: jobs.MAX_SOURCES_PER_RUN]
    template = ingest.get_template(template_id) if template_id else None
    job_id = jobs.create(len(capped), f"{GRADE_TEMPLATES[grade]['label']} · "
                                        f"{len(capped)} worksheet(s)")

    def run():
        for i, src in enumerate(capped):
            # Breathe between sources. Firing back-to-back exhausts the
            # per-minute token allowance and the later sources come back
            # empty — which reads as "generation is broken" when it is
            # really just impatience.
            if i:
                time.sleep(generate.BULK_PAUSE_SECONDS)
            full = ingest.get_source(src["id"])
            if not full:
                jobs.step(job_id, None, 0, f"{src['filename']}: no longer in the library")
                continue
            jobs.update(job_id, current=src["filename"])
            try:
                batch_id = generate.generate_batch(
                    source=full, grade=grade, difficulty=difficulty,
                    variant_count=max(1, min(10, variant_count)),
                    question_count=question_count or None,
                    vary_dimensions=[d for d in vary_dimensions.split(",") if d],
                    closing_message=closing_message,
                    extra_instructions=extra_instructions,
                    modes=modes, template=template,
                )
                with get_conn() as c:
                    made = c.execute("SELECT COUNT(*) n FROM worksheets WHERE batch_id=?",
                                      (batch_id,)).fetchone()["n"]
                jobs.step(job_id, batch_id, made,
                           None if made else f"{src['filename']}: nothing usable came back")
            except Exception as e:
                jobs.step(job_id, None, 0, f"{src['filename']}: {e}")
        jobs.finish(job_id)
        jobs.prune()

    background.add_task(run)
    return {"job_id": job_id, "total": len(capped),
             "skipped": max(0, len(sources) - len(capped)),
             "skipped_low_quality": skipped_low_quality}


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "That run has finished and been cleared.")
    return job


@app.get("/api/batches/{batch_id}")
def api_batch(batch_id: str):
    with get_conn() as c:
        b = c.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        if b is None:
            raise HTTPException(404, "That set of worksheets no longer exists.")
        rows = c.execute(
            "SELECT * FROM worksheets WHERE batch_id=? ORDER BY variant_index",
            (batch_id,)).fetchall()
    batch = dict(b)
    batch["vary_dimensions"] = json.loads(batch["vary_dimensions"])
    return {"batch": batch, "worksheets": [worksheet_to_dict(r) for r in rows]}


@app.get("/api/batches")
def api_batches():
    with get_conn() as c:
        rows = c.execute(
            """SELECT b.*, s.filename AS source_filename,
                       (SELECT COUNT(*) FROM worksheets w WHERE w.batch_id=b.id) AS made,
                       (SELECT COUNT(*) FROM worksheets w WHERE w.batch_id=b.id
                          AND w.review_status='approved') AS approved
                  FROM batches b JOIN sources s ON s.id=b.source_id
                 ORDER BY b.created_at DESC LIMIT 40"""
        ).fetchall()
    return {"batches": [dict(r) for r in rows]}


# ── Review ─────────────────────────────────────────────────────────
@app.post("/api/worksheets/{worksheet_id}/review")
def api_review(worksheet_id: str, status: str = Form(...)):
    if status not in ("approved", "rejected", "draft"):
        raise HTTPException(400, "Unknown review state.")
    with get_conn() as c:
        c.execute("UPDATE worksheets SET review_status=? WHERE id=?",
                   (status, worksheet_id))
    return {"ok": True, "review_status": status}


@app.post("/api/worksheets/{worksheet_id}/revise")
def api_revise(worksheet_id: str, instruction: str = Form(...),
                scope: str = Form("both")):
    if scope not in ("images", "questions", "both"):
        raise HTTPException(400, "Unknown change type.")
    if not instruction.strip():
        raise HTTPException(400, "Describe the change you'd like.")
    try:
        return {"ok": True, "worksheet": generate.regenerate(
            worksheet_id, instruction.strip(), scope)}
    except ProviderError as e:
        raise HTTPException(502, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.put("/api/worksheets/{worksheet_id}/questions")
async def api_edit_questions(worksheet_id: str, request: Request):
    """Accept a reviewer's hand edits.

    Only the fields a person can actually see and change are taken —
    diagram ids and specs are carried over from the stored copy, so an
    edit can't accidentally drop a picture or point at one that doesn't
    exist.
    """
    body = await request.json()
    edits = {int(k): v for k, v in (body.get("questions") or {}).items()}
    if not edits:
        raise HTTPException(400, "Nothing to save.")

    with get_conn() as c:
        row = c.execute("SELECT * FROM worksheets WHERE id=?", (worksheet_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "That worksheet no longer exists.")
        ws = worksheet_to_dict(row)

    for q in ws["questions"]:
        edit = edits.get(q["number"])
        if not edit:
            continue
        if "text" in edit:
            q["text"] = str(edit["text"]).strip()
        if "answer" in edit:
            q["answer"] = str(edit["answer"]).strip()

    with get_conn() as c:
        c.execute("""UPDATE worksheets
                        SET questions=?, review_status='draft', export_path=NULL
                      WHERE id=?""",
                   (json.dumps(ws["questions"]), worksheet_id))
    log_activity("Questions edited by hand", ws["title"])
    return {"ok": True, "questions": ws["questions"]}


@app.get("/api/worksheets/{worksheet_id}/revisions")
def api_revisions(worksheet_id: str):
    with get_conn() as c:
        rows = c.execute(
            "SELECT instruction, scope, created_at FROM revisions "
            "WHERE worksheet_id=? ORDER BY created_at", (worksheet_id,)).fetchall()
    return {"revisions": [dict(r) for r in rows]}


# ── Export ─────────────────────────────────────────────────────────
@app.post("/api/worksheets/{worksheet_id}/export")
def api_export(worksheet_id: str):
    with get_conn() as c:
        row = c.execute("SELECT * FROM worksheets WHERE id=?", (worksheet_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "That worksheet no longer exists.")
        ws = worksheet_to_dict(row)
        batch = dict(c.execute("SELECT * FROM batches WHERE id=?",
                                 (ws["batch_id"],)).fetchone())

    html_path = worksheet_html.render_export(
        ws,
        GRADE_TEMPLATES[batch["grade"]]["label"],
        DIFFICULTY_LEVELS[batch["difficulty"]]["label"],
    )
    pdf_path = worksheet_html.render_pdf(html_path)

    with get_conn() as c:
        c.execute("UPDATE worksheets SET export_path=? WHERE id=?",
                   (str(html_path), worksheet_id))

    return {
        "view_url": f"/exports/{html_path.name}",
        "pdf_url": f"/api/worksheets/{worksheet_id}/pdf" if pdf_path else None,
        "download_name": _download_name(ws, batch),
    }


def _download_name(ws: dict, batch: dict) -> str:
    """The finished PDF carries the SOURCE worksheet's own filename.

    Several variants come from one source, so anything after the first
    gets a suffix — otherwise they would all overwrite each other in the
    reviewer's downloads folder.
    """
    with get_conn() as c:
        row = c.execute("SELECT filename FROM sources WHERE id=?",
                         (batch["source_id"],)).fetchone()
    stem = Path(row["filename"]).stem if row else ws["title"]
    n = ws.get("variant_index", 0)
    return f"{stem}.pdf" if n == 0 else f"{stem}-{n + 1}.pdf"


@app.get("/api/worksheets/{worksheet_id}/pdf")
def api_pdf(worksheet_id: str):
    pdf = config.EXPORT_DIR / f"{worksheet_id}.pdf"
    if not pdf.exists():
        raise HTTPException(404, "Preview this worksheet first.")
    with get_conn() as c:
        row = c.execute("SELECT * FROM worksheets WHERE id=?", (worksheet_id,)).fetchone()
        batch = dict(c.execute("SELECT * FROM batches WHERE id=?",
                                 (row["batch_id"],)).fetchone())
    return FileResponse(pdf, media_type="application/pdf",
                         filename=_download_name(dict(row), batch))


# ── Repository: everything ever brought in ─────────────────────────
@app.get("/api/repository")
def api_repository():
    """The standing record of source PDFs — what came in, from where, and
    whether anything has been built from it yet."""
    with get_conn() as c:
        rows = c.execute(
            """SELECT s.id, s.filename, s.origin, s.origin_detail,
                       s.page_count, s.added_at, s.extracted_text,
                       (SELECT COUNT(*) FROM batches b WHERE b.source_id = s.id) AS runs,
                       (SELECT COUNT(*) FROM worksheets w
                          JOIN batches b2 ON b2.id = w.batch_id
                         WHERE b2.source_id = s.id) AS made,
                       (SELECT COUNT(*) FROM worksheets w
                          JOIN batches b3 ON b3.id = w.batch_id
                         WHERE b3.source_id = s.id
                           AND w.review_status = 'approved') AS approved
                  FROM sources s ORDER BY s.added_at DESC"""
        ).fetchall()

    items = []
    for r in rows:
        d = dict(r)
        d["likely_has_questions"] = ingest.looks_like_questions(d.pop("extracted_text"))
        d["origin_label"] = ingest.ORIGIN_LABEL.get(r["origin"], "Added")
        items.append(d)
    return {
        "items": items,
        "totals": {
            "sources": len(items),
            "used": sum(1 for i in items if i["runs"]),
            "made": sum(i["made"] for i in items),
            "approved": sum(i["approved"] for i in items),
            "by_origin": {
                label: sum(1 for i in items if i["origin_label"] == label)
                for label in sorted({i["origin_label"] for i in items})
            },
        },
    }


# ── Approved: the finished shelf ───────────────────────────────────
@app.get("/api/approved")
def api_approved():
    with get_conn() as c:
        rows = c.execute(
            """SELECT w.id, w.title, w.skill, w.variant_index, w.created_at,
                       w.export_path, b.grade, b.difficulty, s.filename AS source_filename
                  FROM worksheets w
                  JOIN batches b ON b.id = w.batch_id
                  JOIN sources s ON s.id = b.source_id
                 WHERE w.review_status = 'approved'
                 ORDER BY w.created_at DESC"""
        ).fetchall()
    return {"items": [dict(r) for r in rows], "total": len(rows)}


# ── Setup / API key status ──────────────────────────────────────────
@app.get("/api/setup")
def api_setup():
    """What's configured, for a settings screen. Never returns key values —
    only whether one is present, which provider is active, and what each
    piece of the pipeline does. Read-only: keys are pasted into .env and
    picked up on restart, never typed into the app itself."""
    status = config.key_status()
    return {
        **status,
        "canva_stub_note": (
            "Canva's Autofill call itself (app/providers/canva.py::_canva_asset) "
            "is intentionally unimplemented until real credentials exist to "
            "test against — everything around it (when to call it, what to do "
            "if it fails) is already wired up."
        ),
    }


# ── Activity ───────────────────────────────────────────────────────
@app.get("/api/activity")
def api_activity():
    with get_conn() as c:
        rows = c.execute(
            "SELECT action, detail, created_at FROM activity "
            "ORDER BY created_at DESC LIMIT 25").fetchall()
    return {"activity": [dict(r) for r in rows]}
