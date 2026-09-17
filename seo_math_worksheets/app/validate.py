"""
The validation gate.

Generation produces a worksheet. This decides whether it is fit to show a
reviewer — and, when only the pictures are wrong, sends those (and ONLY
those) down the Canva replacement path while every question stays exactly
as written.

Two layers, deliberately in this order:

1. STRUCTURAL checks. No API call, no cost, never wrong. Missing answers,
   empty questions, numbers outside the grade's range, blank or missing
   diagrams. Most real failures are caught here.

2. SENSE check. One API call that asks: does each question actually make
   sense, and is the stated answer correct? This is the check a human
   would otherwise have to do line by line.

The verdict is one of:
    passed          -> straight to preview
    images_failed   -> questions are fine, pictures are not. Canva path.
    failed          -> the questions themselves are wrong. Needs regenerating.
    unverified      -> the sense check could not run (quota, network).
                        NEVER silently treated as a pass.
"""
from __future__ import annotations

import json
import re

from app.config import DIAGRAM_DIR
from app.framework import GRADE_TEMPLATES
from app.providers import llm

SENSE_SYSTEM = """You are checking a children's maths worksheet before a teacher sees it.

Each question may come with a picture. "picture_shown" tells you what the
child can see — treat it as part of the question. A question that reads
incompletely on its own is FINE if the picture supplies the missing
information.

For EACH question, decide:
  - Does it make sense, question and picture together? (unambiguous,
    answerable, complete)
  - Is the given answer actually correct? Do the arithmetic yourself.
  - Is it appropriate for the stated grade?

Be strict about correctness and relaxed about style. A question that is
merely plain is fine. A question whose answer is wrong is not.

Return STRICT JSON:
{
  "questions": [
    {"number": 1, "ok": true, "issue": ""},
    {"number": 2, "ok": false, "issue": "answer says 14, should be 13"}
  ]
}
Every question you were given must appear exactly once."""


def _describe_diagram(spec) -> str:
    """Plain-words version of a diagram spec, for the sense checker."""
    if not isinstance(spec, dict):
        return "none — the question must stand on its own words"
    k = spec.get("kind")
    if k == "object_group":
        groups = spec.get("groups") or []
        return (f"a picture showing {' and '.join(str(g) for g in groups)} "
                f"{spec.get('shape', 'object')}s, drawn as separate groups")
    if k == "ten_frame":
        return f"a ten-frame with {spec.get('filled')} counters filled in"
    if k == "array":
        return f"an array of {spec.get('rows')} rows by {spec.get('cols')} columns"
    if k == "bar_model":
        return (f"a bar model with parts {spec.get('parts')} and total "
                f"labelled {spec.get('total_label')!r}")
    if k == "number_line":
        bits = [f"a number line from {spec.get('min')} to {spec.get('max')}"]
        if spec.get("points"):
            bits.append(f"marked at {[p.get('value') for p in spec['points']]}")
        if spec.get("jumps"):
            bits.append(f"with jumps {[(j.get('from'), j.get('to')) for j in spec['jumps']]}")
        return ", ".join(bits)
    return f"a {k} diagram"


def _is_reflect(q: dict) -> bool:
    return (q.get("section") or "").strip().lower() == "reflect"


def _numbers_in(text: str) -> list[float]:
    return [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", text or "")]


def structural_check(worksheet: dict, grade: int) -> tuple[list[str], list[int]]:
    """Returns (question-level problems, question numbers whose image failed).

    Deliberately separates the two: an image problem is recoverable by
    redrawing, a question problem is not.
    """
    problems: list[str] = []
    bad_images: list[int] = []
    lo, hi = GRADE_TEMPLATES.get(grade, GRADE_TEMPLATES[3])["number_range"]

    questions = worksheet.get("questions") or []
    if not questions:
        return ["The worksheet came back with no questions."], []

    seen_text = set()
    for q in questions:
        n = q.get("number")
        text = (q.get("text") or "").strip()

        if not text:
            problems.append(f"Q{n}: no question text.")
            continue
        # The Reflect item is a closing prompt ("which question made you
        # think hardest?"), not something with a right answer. Demanding
        # one failed every otherwise-perfect worksheet.
        if not _is_reflect(q) and not (q.get("answer") or "").strip():
            problems.append(f"Q{n}: no answer given.")

        # A stem with no numbers at all is a blank template, not a
        # question — e.g. "___ + ___ = ___". Real case: a source PDF whose
        # extracted text was mostly blanks, which the model copied.
        if not _is_reflect(q) and not _numbers_in(text) and "___" in text:
            problems.append(f"Q{n}: is a blank template, not a question.")
            continue

        # Duplicate stems are the commonest way a "10 question" worksheet
        # is really 4 questions repeated.
        key = re.sub(r"\W+", " ", text.lower()).strip()
        if key in seen_text:
            problems.append(f"Q{n}: repeats an earlier question almost word for word.")
        seen_text.add(key)

        out_of_range = [v for v in _numbers_in(text) if v < lo or v > hi]
        if out_of_range:
            problems.append(
                f"Q{n}: uses {out_of_range[0]:g}, outside the "
                f"{GRADE_TEMPLATES.get(grade, GRADE_TEMPLATES[3])['label']} range "
                f"({lo:g}–{hi:g}).")

        if _picture_gives_answer(q):
            bad_images.append(n)
            continue

        if q.get("diagram_spec") and not q.get("diagram_id"):
            bad_images.append(n)
        elif q.get("diagram_id"):
            path = DIAGRAM_DIR / f"{q['diagram_id']}.png"
            if not path.exists() or _is_blank(path):
                bad_images.append(n)

    return problems, bad_images


# Phrasings that mean "tell me the part I haven't shown you".
# `\w+` gaps allow the object name to sit in the middle.
_PART_QUESTION_PATTERNS = [
    r"how many (?:\w+\s+){0,3}more",
    r"how many (?:\w+\s+){0,3}did you add",
    r"how many (?:\w+\s+){0,3}(?:are |were )?(?:in the other|left|remain)",
    r"how many (?:\w+\s+){0,3}must",
    r"how many (?:\w+\s+){0,3}should",
    r"missing",
    r"belongs in",
    r"what number goes",
]


def _picture_gives_answer(q: dict) -> bool:
    """Catch a picture that hands the child the answer.

    Real example this was written for: "you have 5 circles and add some
    more to make 10 — how many did you add?" drawn as five circles AND
    five more. The child counts instead of reasoning, and the question
    stops testing anything.

    The rule: for a MISSING-PART question, the unknown quantity must not
    appear as a drawn group. Totals are fine — "3 and 2, how many
    altogether?" shows 3 and 2, and 5 is not drawn.
    """
    spec = q.get("diagram_spec")
    if not isinstance(spec, dict):
        return False

    answers = _numbers_in(q.get("answer") or "")
    if len(answers) != 1:
        return False
    answer = answers[0]

    # Only applies when the question asks for a PART, not a total.
    # These have to be regexes: real questions name the object in the
    # middle ("how many CIRCLES did you add"), so plain substring
    # matching on "how many did you add" silently never fires.
    text = (q.get("text") or "").lower()
    if not any(re.search(pat, text) for pat in _PART_QUESTION_PATTERNS):
        return False

    kind = spec.get("kind")
    if kind == "object_group":
        return any(float(g) == answer for g in (spec.get("groups") or [])
                    if isinstance(g, (int, float)))
    if kind == "bar_model":
        return any(float(pt) == answer for pt in (spec.get("parts") or [])
                    if isinstance(pt, (int, float)))
    if kind == "ten_frame":
        return float(spec.get("filled", -1)) == answer
    return False


def _is_blank(path) -> bool:
    """A picture that saved successfully but is empty is the worst failure
    mode — it looks like it worked. Catch it by pixel content, not by
    whether the file exists."""
    try:
        from PIL import Image

        im = Image.open(path).convert("L")
        hist = im.histogram()
        near_white = sum(hist[250:])
        return near_white / max(1, sum(hist)) > 0.995
    except Exception:
        return True


def sense_check(worksheet: dict, grade: int) -> tuple[list[str], bool]:
    """Returns (problems, ran_successfully)."""
    questions = [q for q in (worksheet.get("questions") or []) if not _is_reflect(q)]
    if not questions:
        return [], True
    # The picture is part of the question. Without telling the checker one
    # exists, it flags every diagram-based question as "lacks context" —
    # which is most warm-up questions on a primary worksheet.
    payload = [{"number": q.get("number"), "question": q.get("text"),
                 "answer": q.get("answer"),
                 "picture_shown": _describe_diagram(q.get("diagram_spec"))}
                for q in questions]
    label = GRADE_TEMPLATES.get(grade, GRADE_TEMPLATES[3])["label"]
    try:
        result = llm.complete_json(
            SENSE_SYSTEM,
            f"GRADE: {label}\n\nQUESTIONS:\n{json.dumps(payload, indent=2)}")
    except Exception:
        return [], False

    problems = []
    for row in result.get("questions") or []:
        if not row.get("ok", True):
            issue = (row.get("issue") or "does not make sense").strip()
            problems.append(f"Q{row.get('number')}: {issue}")
    return problems, True


def validate(worksheet: dict, grade: int, run_sense_check: bool = True) -> dict:
    """The gate. Returns a verdict dict stored alongside the worksheet."""
    problems, bad_images = structural_check(worksheet, grade)

    sense_ran = True
    if run_sense_check and not problems:
        # Only worth paying for the sense check once the structure is sound;
        # a structurally broken worksheet is going back regardless.
        sense_problems, sense_ran = sense_check(worksheet, grade)
        problems.extend(sense_problems)

    if problems:
        verdict = "failed"
    elif bad_images:
        verdict = "images_failed"
    elif not sense_ran:
        # Could not confirm. Not a pass — say so rather than implying one.
        verdict = "unverified"
    else:
        verdict = "passed"

    return {
        "verdict": verdict,
        "problems": problems,
        "bad_images": bad_images,
        "sense_check_ran": sense_ran,
    }


# Plain-English wording for the review screen. No verdict codes reach the UI.
VERDICT_TEXT = {
    "passed": "Checked — looks right",
    "images_failed": "Pictures need redrawing",
    "failed": "Needs another pass",
    "unverified": "Could not finish checking",
}
