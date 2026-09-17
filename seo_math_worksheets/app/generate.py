"""
Turning one source worksheet into N new ones.

The flow, per variant:
    source text
      -> mine the underlying pattern (what skill, what question shapes)
      -> rewrite against the instructional design framework constraints
      -> draw any diagrams the model asked for
      -> store

The framework (app/framework.py) is what makes this principled. Without
it the model swaps nouns and produces near-duplicates, which is both
pedagogically pointless and actively harmful for SEO.
"""
from __future__ import annotations

import json

from app.db import get_conn, log_activity, new_id, now
from app.framework import GenerationSpec
from app import validate as validator
from app.providers import canva, images, llm

# Seconds to wait between sources in a bulk run. Tuned for Groq's free
# tier; raise it if runs keep reporting "the question writer is busy".
BULK_PAUSE_SECONDS = 4

SYSTEM_PROMPT = f"""You write original maths worksheets for Bhanzu, a global maths education company.

You are given the text of ONE existing worksheet as structural reference,
plus a precise design specification. Your job is NOT to copy or lightly
reword it. Your job is to:

1. MINE THE PATTERN. Work out what skill the source worksheet actually
   trains and what question shapes it uses. Keep that.

2. DISCARD ALL SURFACE CONTENT. Every object, name, number, and scenario
   from the source must go. If the source counted apples, do not count
   any fruit.

3. WRITE A NEW WORKSHEET that trains the identical skill, obeying every
   constraint in the specification you are given.

HARD REQUIREMENTS:
- Globally neutral content. No region-specific currency, festivals,
  idioms, or names that only read naturally in one country. Use names and
  settings that a child in any country would follow.
- Every question must be solvable and the answer you give must be
  correct. Check your arithmetic.
- Match the requested grade's reading level exactly. A Grade 1 question
  with a two-sentence stem is a failure.
- Follow the requested section arc and difficulty mix.

{images.DIAGRAM_SPEC_INSTRUCTIONS}

Return STRICT JSON, no markdown fencing, exactly this shape:
{{
  "title": "short worksheet title",
  "skill": "the skill being trained, in plain words",
  "questions": [
    {{"number": 1,
      "section": "Warm up" | "Practice" | "Stretch" | "Reflect",
      "text": "the question as the child reads it",
      "answer": "the correct answer",
      "dok": 1,
      "representation": "concrete" | "pictorial" | "abstract",
      "diagram": null}}
  ],
  "closing_note": "the closing message for the Reflect section"
}}"""


# Two ways to use a source worksheet. They answer different needs, so
# they get genuinely different instructions rather than a tweaked
# sentence — the model behaves very differently depending on which.
MODES = {
    "reframe": {
        "label": "Change the context",
        "blurb": "Same questions, brand-new setting — different objects, "
                  "names, numbers and scenarios.",
        "instruction": """MODE: REFRAME.
Keep the source worksheet's question-by-question structure. For each
question in the source, write ONE replacement that tests the identical
thing at the identical difficulty, but with entirely new surface content:
new objects, new names, new numbers, new scenario.

The result should feel like the same worksheet rewritten for a different
classroom — same shape, same length, nothing recognisable from the
original.""",
    },
    "expand": {
        "label": "More questions of these types",
        "blurb": "Find the question types in the source, then write many "
                  "more of each — for building a larger bank.",
        "instruction": """MODE: EXPAND.
First identify the DISTINCT QUESTION TYPES present in the source
worksheet (there are usually between two and five). Then write a much
larger set of questions covering those same types.

Spread the questions across the types you found, giving each type several
different variants — vary the numbers, the objects, and where the unknown
sits, so that no two feel like the same question twice. Group questions of
the same type together and order the groups from most familiar to least.

The result should be a practice bank built out of the source's question
types, not a copy of the source.""",
    },
}


def _build_user_prompt(source_text: str, spec: GenerationSpec) -> str:
    excerpt = (source_text or "").strip()
    if len(excerpt) > 6000:
        excerpt = excerpt[:6000] + "\n…(truncated)"
    picked = [m for m in (getattr(spec, "modes", None) or ["reframe"]) if m in MODES]
    if not picked:
        picked = ["reframe"]
    if len(picked) == 1:
        mode_block = MODES[picked[0]]["instruction"]
    else:
        # Both asked for: reframe everything, then keep going past the
        # source's length with more of the same types. Spelling out the
        # combination beats concatenating two instructions that each say
        # "do this" and leave the model to guess the priority.
        mode_block = """MODE: REFRAME + EXPAND (both).
Work in two passes.

PASS 1 — REFRAME: for each question in the source, write one replacement
that tests the identical thing at the identical difficulty, with entirely
new objects, names, numbers and scenario.

PASS 2 — EXPAND: identify the distinct question types in the source, then
keep going and write further questions of those same types, varying the
numbers, the objects and where the unknown sits.

Put the reframed questions first, in the source's order, then the extra
ones grouped by type. The total must match the requested question count."""
    return f"""{mode_block}

DESIGN SPECIFICATION
====================
{spec.to_prompt_constraints()}

SOURCE WORKSHEET (structural reference only — take the PATTERN, discard
every object, name, number and scenario):
====================
{excerpt or '(no text could be read from this PDF — invent an appropriate worksheet for the grade and difficulty above)'}
"""


def _normalise_questions(raw: list, spec: GenerationSpec) -> list[dict]:
    """Defend against the model's formatting drift before anything is
    stored. Storing malformed questions means every consumer downstream
    has to defend against it instead."""
    out = []
    for i, q in enumerate(raw or []):
        if not isinstance(q, dict):
            continue
        text = str(q.get("text") or "").strip()
        if not text:
            continue
        diagram_id = images.render_diagram(q.get("diagram"))
        out.append({
            "number": i + 1,
            "section": q.get("section") or "Practice",
            "text": text,
            "answer": str(q.get("answer", "")).strip(),
            "dok": int(q.get("dok") or 2) if str(q.get("dok", "")).isdigit() else 2,
            "representation": q.get("representation") or "abstract",
            "diagram_id": diagram_id,
            "diagram_spec": q.get("diagram") if diagram_id else None,
        })
    return out


def generate_batch(source: dict, grade: int, difficulty: str, variant_count: int,
                    question_count: int | None, vary_dimensions: list[str],
                    closing_message: str, extra_instructions: str,
                    modes: list[str] | None = None,
                    template: dict | None = None) -> str:
    """Create a batch and generate every variant in it. Returns batch id."""
    batch_id = new_id()
    with get_conn() as c:
        c.execute(
            """INSERT INTO batches
                 (id, source_id, grade, difficulty, variant_count, question_count,
                  vary_dimensions, closing_message, extra_instructions,
                  status, error, created_at, mode, template_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (batch_id, source["id"], grade, difficulty, variant_count,
             question_count, json.dumps(vary_dimensions), closing_message,
             extra_instructions, "generating", None, now(),
             ",".join(modes or ["reframe"]),
             (template or {}).get("id")),
        )

    made, failures = 0, []
    for idx in range(variant_count):
        spec = GenerationSpec(
            grade=grade,
            difficulty=difficulty,
            question_count=question_count,
            vary_dimensions=vary_dimensions or ["surface_context"],
            closing_message=closing_message,
            extra_instructions=extra_instructions,
            seed_index=idx,
            modes=modes or ["reframe"],
        )
        try:
            result = llm.complete_json(
                SYSTEM_PROMPT, _build_user_prompt(source.get("extracted_text", ""), spec))
        except llm.ProviderError as e:
            failures.append(str(e))
            continue

        questions = _normalise_questions(result.get("questions"), spec)
        if not questions:
            failures.append("A variant came back with no usable questions.")
            continue

        # ── the validation gate ──────────────────────────────────
        draft = {"questions": questions}
        verdict = validator.validate(draft, grade)

        # Questions are fine but a picture isn't: fix ONLY the pictures.
        if verdict["verdict"] == "images_failed":
            repair = canva.replace_images(draft, verdict["bad_images"])
            questions = draft["questions"]
            verdict["image_repair"] = repair
            if not repair["still_bad"]:
                verdict["verdict"] = "passed"
                verdict["problems"] = []

        with get_conn() as c:
            c.execute(
                """INSERT INTO worksheets
                     (id, batch_id, variant_index, title, skill, questions,
                      closing_note, review_status, export_path, created_at,
                      validation)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (new_id(), batch_id, idx,
                 str(result.get("title") or f"Worksheet {idx + 1}"),
                 str(result.get("skill") or ""),
                 json.dumps(questions),
                 str(result.get("closing_note") or closing_message or ""),
                 "draft", None, now(), json.dumps(verdict)),
            )
        made += 1

    status = "ready" if made else "failed"
    with get_conn() as c:
        c.execute("UPDATE batches SET status=?, error=? WHERE id=?",
                   (status, "; ".join(failures[:3]) if failures else None, batch_id))

    log_activity("Worksheets written",
                  f"{made} of {variant_count} from {source['filename']}")
    return batch_id


def regenerate(worksheet_id: str, instruction: str, scope: str = "both") -> dict:
    """Apply a reviewer's plain-English change request.

    scope='images' is the cheap path from the spec: keep every question
    exactly as it is and only redraw pictures. Nothing is sent to the
    language model for the question text at all, so the questions
    genuinely cannot drift.
    """
    with get_conn() as c:
        row = c.execute("SELECT * FROM worksheets WHERE id=?", (worksheet_id,)).fetchone()
        if row is None:
            raise ValueError("That worksheet no longer exists.")
        ws = dict(row)
        batch = dict(c.execute("SELECT * FROM batches WHERE id=?",
                                 (ws["batch_id"],)).fetchone())

    questions = json.loads(ws["questions"])

    if scope == "images":
        for q in questions:
            if q.get("diagram_spec"):
                q["diagram_id"] = images.render_diagram(q["diagram_spec"])
        updated = {"title": ws["title"], "skill": ws["skill"],
                    "questions": questions, "closing_note": ws["closing_note"]}
    else:
        spec = GenerationSpec(
            grade=batch["grade"],
            difficulty=batch["difficulty"],
            question_count=batch["question_count"],
            vary_dimensions=json.loads(batch["vary_dimensions"]),
            closing_message=batch["closing_message"] or "",
            extra_instructions=(batch["extra_instructions"] or ""),
            seed_index=ws["variant_index"],
            modes=(batch["mode"] or "reframe").split(","),
        )
        current = json.dumps({"title": ws["title"], "skill": ws["skill"],
                                "questions": [{k: q[k] for k in
                                               ("number", "section", "text", "answer")}
                                              for q in questions]}, indent=2)
        user = f"""{spec.to_prompt_constraints()}

THE WORKSHEET AS IT STANDS:
{current}

THE REVIEWER HAS ASKED FOR THIS CHANGE:
"{instruction}"

Apply exactly that change. Leave everything the reviewer did not mention
alone — same skill, same difficulty, same section arc. Return the full
worksheet in the same JSON shape."""
        result = llm.complete_json(SYSTEM_PROMPT, user)
        questions = _normalise_questions(result.get("questions"), spec)
        if not questions:
            raise ValueError("That change didn't produce a usable worksheet. Try rewording it.")
        updated = {"title": result.get("title") or ws["title"],
                    "skill": result.get("skill") or ws["skill"],
                    "questions": questions,
                    "closing_note": result.get("closing_note") or ws["closing_note"]}

    verdict = validator.validate({"questions": updated["questions"]}, batch["grade"])
    if verdict["verdict"] == "images_failed":
        repair = canva.replace_images(updated, verdict["bad_images"])
        verdict["image_repair"] = repair
        if not repair["still_bad"]:
            verdict["verdict"] = "passed"

    with get_conn() as c:
        c.execute("""UPDATE worksheets
                        SET title=?, skill=?, questions=?, closing_note=?,
                            review_status='draft', export_path=NULL,
                            validation=?
                      WHERE id=?""",
                   (updated["title"], updated["skill"],
                    json.dumps(updated["questions"]), updated["closing_note"],
                    json.dumps(verdict), worksheet_id))
        c.execute("""INSERT INTO revisions (id, worksheet_id, instruction, scope, created_at)
                      VALUES (?,?,?,?,?)""",
                   (new_id(), worksheet_id, instruction, scope, now()))

    log_activity("Changes applied",
                  "Pictures redrawn" if scope == "images" else "Questions rewritten")
    return updated


CLOSING_SYSTEM = """You write the short sign-off that sits at the end of a
children's maths worksheet, in a highlighted box titled "Before you go".

It has one job: make the child want to come back to the next session.

Rules:
- Two sentences at most. One is often better.
- Warm and specific, never generic praise ("Well done!" alone is wasted space).
- Name what they just practised, and point forward to what it unlocks next.
- Match the reading level of the grade you are given.
- Globally neutral: no region-specific references, festivals, or idioms.
- No exclamation-mark pile-ups, no emoji.

Return STRICT JSON: {"closing_message": "..."}"""


# What the sign-off should point the child towards. The worksheet is a
# marketing surface as well as a teaching one, so the invitation is part
# of the design rather than an afterthought bolted on at the end.
CLOSING_GOALS = {
    "practise": ("Practise more",
                  "invite them to try another worksheet on the same skill"),
    "next_topic": ("The next concept",
                    "point ahead to the topic this skill unlocks, by name"),
    "article": ("Read more",
                 "suggest reading a short Bhanzu article about where this maths "
                 "shows up in the real world"),
    "demo": ("Join a Bhanzu class",
              "warmly invite them to a free Bhanzu demo class to go further — "
              "one short sentence, never pushy, never a hard sell"),
}


def suggest_closing_message(topic: str, grade: int, goal: str = "practise") -> str:
    """Write a closing note from a topic, so the author doesn't have to."""
    from app.framework import GRADE_TEMPLATES

    g = GRADE_TEMPLATES.get(grade, GRADE_TEMPLATES[3])
    _, goal_text = CLOSING_GOALS.get(goal, CLOSING_GOALS["practise"])
    result = llm.complete_json(
        CLOSING_SYSTEM,
        f"GRADE: {g['label']}\nReading level: {g['reading_level']}\n"
        f"TOPIC THEY JUST PRACTISED: {topic}\n"
        f"WHAT IT SHOULD INVITE THEM TO DO: {goal_text}\n\n"
        "Write the closing message.",
    )
    return str(result.get("closing_message") or "").strip()
