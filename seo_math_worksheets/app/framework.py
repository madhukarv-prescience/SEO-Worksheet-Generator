"""
The instructional design framework that governs how a source question is
regenerated.

This is the answer to "on what basis will it change?". Without it, an LLM
asked to "change the question" just swaps apples for oranges and calls it
a day — which produces variants that look different but teach exactly the
same thing at exactly the same difficulty. That is worthless for SEO (the
pages are near-duplicates) and worthless pedagogically.

Six dimensions, each independently controllable. The generator sends the
active settings to the model as explicit constraints, and stores them on
the worksheet so a reviewer can see WHY a question came out the way it
did.

Sources these are drawn from (standard, well-established instructional
design literature — nothing exotic):
  - Bloom's revised taxonomy / Webb's Depth of Knowledge  -> cognitive demand
  - Bruner's CPA (Concrete-Pictorial-Abstract)            -> representation
  - Sweller's Cognitive Load Theory                       -> load budget
  - Marton's Variation Theory                             -> what to vary
  - Polya's four phases                                   -> problem structure
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ── 1. Cognitive demand ────────────────────────────────────────────
# Webb's Depth of Knowledge, trimmed to what actually occurs in K-6
# worksheets. DOK4 (extended investigation over days) never appears on a
# worksheet, so it is deliberately absent.
DOK_LEVELS = {
    1: {
        "name": "Recall & reproduce",
        "verbs": ["count", "name", "identify", "recognise", "copy", "match"],
        "description": "One step, no decision. The child either knows it or doesn't.",
    },
    2: {
        "name": "Apply a skill or concept",
        "verbs": ["compare", "classify", "estimate", "order", "complete the pattern",
                   "solve using a known method"],
        "description": "Requires choosing or executing a procedure. One real decision point.",
    },
    3: {
        "name": "Strategic thinking",
        "verbs": ["explain why", "find another way", "decide which method",
                   "spot the mistake", "work backwards"],
        "description": "Multi-step, more than one valid route, child must justify or choose.",
    },
}


# ── 2. Representation (Bruner's CPA) ───────────────────────────────
REPRESENTATIONS = {
    "concrete": "Countable discrete objects shown individually. The child can point at each one.",
    "pictorial": "A structured visual — array, ten-frame, number line, bar model, tally.",
    "abstract": "Symbols and numerals only. No supporting picture.",
}

# Which mix suits which grade. Younger bands lean concrete; the jump to
# abstract is gradual and is the single biggest driver of perceived
# difficulty in early primary.
GRADE_REPRESENTATION_MIX = {
    0: {"concrete": 0.75, "pictorial": 0.25, "abstract": 0.0},
    1: {"concrete": 0.6, "pictorial": 0.4, "abstract": 0.0},
    2: {"concrete": 0.4, "pictorial": 0.45, "abstract": 0.15},
    3: {"concrete": 0.2, "pictorial": 0.5, "abstract": 0.3},
    4: {"concrete": 0.1, "pictorial": 0.45, "abstract": 0.45},
    5: {"concrete": 0.0, "pictorial": 0.4, "abstract": 0.6},
    6: {"concrete": 0.0, "pictorial": 0.3, "abstract": 0.7},
    7: {"concrete": 0.0, "pictorial": 0.25, "abstract": 0.75},
    8: {"concrete": 0.0, "pictorial": 0.2, "abstract": 0.8},
    9: {"concrete": 0.0, "pictorial": 0.15, "abstract": 0.85},
    10: {"concrete": 0.0, "pictorial": 0.15, "abstract": 0.85},
}


# ── 3. Cognitive load budget (Sweller) ─────────────────────────────
# "Element interactivity" = how many things the child must hold in working
# memory simultaneously. This is the honest measure of difficulty — far
# more predictive than how big the numbers are.
LOAD_BUDGET = {
    "light":    {"max_elements": 2, "max_steps": 1, "scaffold": "always"},
    "moderate": {"max_elements": 4, "max_steps": 2, "scaffold": "partial"},
    "heavy":    {"max_elements": 6, "max_steps": 3, "scaffold": "none"},
}

# Extraneous load is load that teaches nothing. These are non-negotiable
# rules applied to every generated worksheet.
EXTRANEOUS_LOAD_RULES = [
    "One question per visual. Never make the child work out which picture belongs to which question.",
    "No decorative imagery that isn't part of the question.",
    "Keep the question text and its picture adjacent — never split across a page break.",
    "Use the same word for the same thing throughout (not 'add' in Q1 and 'total' in Q2 for the same operation).",
    "No more than one unfamiliar context per worksheet.",
]


# ── 4. Variation theory (Marton) ───────────────────────────────────
# The core insight: a child perceives what is essential about a concept
# only when that aspect VARIES while everything else stays INVARIANT.
# So across a set of questions we deliberately vary exactly one dimension
# at a time. Varying everything at once (the naive "make it different"
# approach) teaches nothing.
VARIATION_DIMENSIONS = {
    "surface_context": "Objects, names, setting. Vary freely — this is what makes a worksheet feel new.",
    "number_magnitude": "Size of the numbers involved. Vary to shift difficulty within the same skill.",
    "missing_position": "Where the unknown sits: a+b=? vs a+?=c vs ?+b=c. Same skill, very different demand.",
    "representation": "Concrete / pictorial / abstract for the same underlying question.",
    "step_count": "One-step vs multi-step versions of the same relationship.",
    "distractor_similarity": "How close the wrong options are to the right one (for selection formats).",
}


# ── 5. Difficulty levers ───────────────────────────────────────────
# Concrete, controllable knobs the UI exposes. Each maps to something the
# model is told explicitly, so 'hard' means something specific and
# repeatable rather than whatever the model feels like that day.
DIFFICULTY_LEVELS = {
    "foundation": {
        "label": "Foundation",
        "dok_mix": {1: 0.7, 2: 0.3, 3: 0.0},
        "load": "light",
        "missing_position": "result_only",     # a + b = ?
        "scaffold": "worked example at the top, visual support on every question",
        "description": "For a child meeting this skill for the first time, or revisiting after a gap.",
    },
    "core": {
        "label": "Core",
        "dok_mix": {1: 0.3, 2: 0.6, 3: 0.1},
        "load": "moderate",
        "missing_position": "mixed",
        "scaffold": "visual support on roughly half the questions",
        "description": "Grade-expected practice. This is the default.",
    },
    "stretch": {
        "label": "Stretch",
        "dok_mix": {1: 0.1, 2: 0.5, 3: 0.4},
        "load": "heavy",
        "missing_position": "any",
        "scaffold": "no visual support; at least one 'explain' or 'find the mistake' question",
        "description": "For a child who has the skill and needs depth, not more repetition.",
    },
}


# ── 6. Worksheet composition (Polya-informed arc) ──────────────────
# A worksheet is not a flat list. This arc is applied to every generated
# sheet so it has a shape a teacher recognises.
COMPOSITION_ARC = [
    {"section": "Warm up",   "share": 0.20, "dok": 1,
     "purpose": "Rebuild confidence and activate the prior skill. Should feel easy."},
    {"section": "Practice",  "share": 0.55, "dok": 2,
     "purpose": "The core of the sheet. Systematic variation along ONE dimension."},
    {"section": "Stretch",   "share": 0.20, "dok": 3,
     "purpose": "Apply it somewhere unfamiliar, or explain the reasoning."},
    {"section": "Reflect",   "share": 0.05, "dok": 1,
     "purpose": "A closing note. This is where the teacher's own message lands."},
]


# ── Grade templates ────────────────────────────────────────────────
# What 'Grade N' actually means when selected in the UI.
GRADE_TEMPLATES = {
    0: {"label": "Kindergarten", "question_count": 8, "number_range": (0, 10),
         "reading_level": "One or two words, or no words at all. The picture is the question.",
         "typical_skills": ["counting to 10", "more and fewer", "matching numerals to groups",
                             "sorting by one attribute", "recognising 2D shapes"]},
    1: {"label": "Grade 1", "question_count": 10, "number_range": (0, 20),
         "reading_level": "Three to five words per instruction. Picture carries the meaning.",
         "typical_skills": ["counting to 20", "addition within 10", "comparing groups",
                             "2D shape names", "simple patterns"]},
    2: {"label": "Grade 2", "question_count": 12, "number_range": (0, 100),
         "reading_level": "One short sentence per question.",
         "typical_skills": ["place value to 100", "addition/subtraction within 20",
                             "skip counting", "simple measurement", "halves and quarters"]},
    3: {"label": "Grade 3", "question_count": 14, "number_range": (0, 1000),
         "reading_level": "One or two sentences. Some questions purely in words.",
         "typical_skills": ["multiplication tables", "division as sharing",
                             "unit fractions", "perimeter", "time"]},
    4: {"label": "Grade 4", "question_count": 16, "number_range": (0, 10000),
         "reading_level": "Short word problems expected.",
         "typical_skills": ["multi-digit multiplication", "equivalent fractions",
                             "decimals to hundredths", "area", "factors"]},
    5: {"label": "Grade 5", "question_count": 18, "number_range": (0, 100000),
         "reading_level": "Multi-sentence word problems.",
         "typical_skills": ["fraction arithmetic", "decimal operations", "volume",
                             "coordinate plane", "order of operations"]},
    6: {"label": "Grade 6", "question_count": 20, "number_range": (0, 1000000),
         "reading_level": "Full word problems; some multi-part.",
         "typical_skills": ["ratio and rate", "percentages", "negative numbers",
                             "algebraic expressions", "statistical measures"]},
    7: {"label": "Grade 7", "question_count": 20, "number_range": (-10000, 1000000),
         "reading_level": "Multi-step word problems; some require setting up an equation.",
         "typical_skills": ["proportional relationships", "operations with rationals",
                             "linear expressions", "scale drawings", "probability of simple events",
                             "area and circumference of circles"]},
    8: {"label": "Grade 8", "question_count": 20, "number_range": (-100000, 1000000),
         "reading_level": "Multi-step problems, formal notation expected.",
         "typical_skills": ["linear equations in one variable", "systems of equations",
                             "functions", "exponents and scientific notation",
                             "Pythagorean theorem", "transformations", "scatter plots"]},
    9: {"label": "Grade 9", "question_count": 18, "number_range": (-1000000, 1000000),
         "reading_level": "Formal mathematical language; multi-part questions.",
         "typical_skills": ["quadratic expressions and factorising", "linear and quadratic graphs",
                             "sequences", "surds and indices", "coordinate geometry",
                             "similar and congruent triangles", "statistics and spread"]},
    10: {"label": "Grade 10", "question_count": 18, "number_range": (-1000000, 1000000),
          "reading_level": "Formal notation, proof-style reasoning, multi-part questions.",
          "typical_skills": ["quadratic equations and the discriminant", "simultaneous equations",
                              "trigonometric ratios", "circle theorems", "polynomials",
                              "probability with two events", "arithmetic and geometric progressions"]},
}


@dataclass
class GenerationSpec:
    """Everything that governs one generated variant. Stored alongside the
    worksheet so a reviewer can see exactly what was asked for."""
    grade: int = 3
    difficulty: str = "core"
    question_count: int | None = None      # None -> grade default
    vary_dimensions: list[str] = field(default_factory=lambda: ["surface_context"])
    closing_message: str = ""              # the teacher's own note for the Reflect section
    extra_instructions: str = ""           # freeform prompt from the UI
    seed_index: int = 0                    # which variant of N this is
    modes: list[str] = field(default_factory=lambda: ["reframe"])  # see generate.MODES

    def resolved_question_count(self) -> int:
        if self.question_count:
            return self.question_count
        return GRADE_TEMPLATES[self.grade]["question_count"]

    def to_prompt_constraints(self) -> str:
        """Render this spec as explicit constraints for the language model.

        Deliberately verbose and specific: vague instructions ("make it
        harder") produce vague results. Every number here is something the
        model can actually comply with and a reviewer can actually check.
        """
        g = GRADE_TEMPLATES[self.grade]
        d = DIFFICULTY_LEVELS[self.difficulty]
        load = LOAD_BUDGET[d["load"]]
        rep = GRADE_REPRESENTATION_MIX[self.grade]
        n = self.resolved_question_count()

        dok_text = ", ".join(
            f"{int(share * 100)}% at DOK{level} ({DOK_LEVELS[level]['name']})"
            for level, share in d["dok_mix"].items() if share > 0
        )
        rep_text = ", ".join(
            f"{int(share * 100)}% {name}" for name, share in rep.items() if share > 0
        )
        vary_text = "\n".join(
            f"  - {dim}: {VARIATION_DIMENSIONS[dim]}"
            for dim in self.vary_dimensions if dim in VARIATION_DIMENSIONS
        )
        arc_text = "\n".join(
            f"  - {s['section']}: {int(s['share'] * n) or 1} question(s) — {s['purpose']}"
            for s in COMPOSITION_ARC
        )
        rules_text = "\n".join(f"  - {r}" for r in EXTRANEOUS_LOAD_RULES)

        return f"""GRADE: {g['label']}
Number range: {g['number_range'][0]}–{g['number_range'][1]}
Reading level: {g['reading_level']}
Typical skills at this grade: {', '.join(g['typical_skills'])}

DIFFICULTY: {d['label']} — {d['description']}
Cognitive demand mix: {dok_text}
Working-memory budget: at most {load['max_elements']} elements held at once,
  at most {load['max_steps']} step(s) per question.
Scaffolding: {d['scaffold']}
Position of the unknown: {d['missing_position']}

REPRESENTATION MIX: {rep_text}
  concrete  = {REPRESENTATIONS['concrete']}
  pictorial = {REPRESENTATIONS['pictorial']}
  abstract  = {REPRESENTATIONS['abstract']}

VARY THESE DIMENSIONS (and hold everything else constant — this is
deliberate: a child perceives what is essential only when one thing varies
against a stable background):
{vary_text}

WORKSHEET SHAPE ({n} questions total):
{arc_text}

NON-NEGOTIABLE RULES:
{rules_text}

CLOSING MESSAGE for the Reflect section (use the teacher's own words,
lightly polished — do not replace their meaning):
  "{self.closing_message or '(none supplied — write a short warm sign-off)'}"

ADDITIONAL INSTRUCTIONS FROM THE AUTHOR:
  {self.extra_instructions or '(none)'}

This is variant #{self.seed_index + 1}. It must be materially different
from the other variants in this batch — different contexts, different
numbers — while testing the identical skill at the identical difficulty.
"""


def framework_summary() -> dict:
    """Machine-readable summary, served to the UI so the front end never
    hardcodes its own copy of these lists."""
    return {
        "grades": {k: {"label": v["label"], "question_count": v["question_count"],
                        "skills": v["typical_skills"]}
                    for k, v in GRADE_TEMPLATES.items()},
        "difficulties": {k: {"label": v["label"], "description": v["description"]}
                          for k, v in DIFFICULTY_LEVELS.items()},
        "variation_dimensions": VARIATION_DIMENSIONS,
    }
