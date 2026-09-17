"""
Illustrations for worksheet questions.

WHY THIS IS NOT AN IMAGE-GENERATION API CALL
--------------------------------------------
A diffusion model cannot be trusted to place 7 objects when the question
says 7, or to put a tick at 24 on a number line. It produces something
that looks plausible and is arithmetically wrong — the worst possible
failure for a maths worksheet, because it renders "successfully" and only
a human notices.

So the language model's job here is only to EMIT A STRUCTURED SPEC
(kind + parameters). Python then draws it, deterministically and
correctly. No image API key required, nothing to pay for, and the same
spec redraws identically forever.

Photo-real or decorative artwork is the one case where a real image model
genuinely helps; that path is `generate_realistic_image()` and needs an
OpenAI key. It is never used for anything where the maths must be right.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math

import httpx

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from app import config  # noqa: E402
from app.config import DIAGRAM_DIR  # noqa: E402

# Bhanzu brand palette (brand guidelines p.18)
ORANGE = "#f15d22"
DEEP_BLUE = "#212638"
YELLOW = "#fab82b"
FUN_BLUE = "#5e91ff"
GREY = "#45474a"

SUPPORTED_KINDS = ["number_line", "object_group", "ten_frame", "bar_model", "array"]

# Sent to the language model so it knows what it may ask for. Keeping this
# list short and explicit is deliberate — an open-ended "describe any
# picture" invites specs nothing can draw.
DIAGRAM_SPEC_INSTRUCTIONS = f"""When a question needs a picture, set "diagram" to an object.
Only these kinds exist — anything else will be ignored:

  {{"kind": "number_line", "min": 0, "max": 20, "step": 1,
    "points": [{{"value": 7, "label": "start"}}],
    "jumps": [{{"from": 7, "to": 12, "label": "+5"}}]}}

  {{"kind": "object_group", "groups": [4, 3], "shape": "circle"}}
      -> draws 2 groups of countable objects (4 then 3). shape:
         circle | square | triangle | star

  {{"kind": "ten_frame", "filled": 7}}
      -> a standard 10-frame with 7 counters

  {{"kind": "array", "rows": 3, "cols": 4}}
      -> a rectangular array for multiplication

  {{"kind": "bar_model", "parts": [12, 8], "total_label": "?"}}
      -> a part-part-whole bar

Set "diagram" to null when the question needs no picture.

NEVER DRAW THE ANSWER. This is the rule most often broken, so read it
twice. If the question asks for a MISSING PART ("how many more...?",
"how many are in the other group?"), the picture must show ONLY the part
the child is told about. Drawing the missing part as well turns a
reasoning question into a counting exercise and tests nothing.

  WRONG: "You have 5 counters and add some to make 10. How many did you
          add?" drawn as 5 counters AND 5 counters.
  RIGHT: the same question with only the 5 shown, or no picture at all.

Drawing a TOTAL is fine: "3 stars and 2 stars, how many altogether?"
shows 3 and 2, because the answer 5 is not itself drawn."""


def _path_for(spec: dict) -> tuple[str, str]:
    key = hashlib.sha1(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:12]
    return key, str(DIAGRAM_DIR / f"{key}.png")


def _finish(fig, path: str) -> str:
    fig.savefig(path, dpi=150, bbox_inches="tight", pad_inches=0.15,
                 facecolor="white", transparent=False)
    plt.close(fig)
    return path


# ── Number line ────────────────────────────────────────────────────
def _nice_label_step(vmin: float, vmax: float, step: float, width_in: float) -> float:
    """Choose how often to print a tick label so labels cannot collide.

    Estimated from the widest label's character count against available
    width. Computing this instead of asking the model to 'avoid overlap'
    is the whole reason number lines come out legible.
    """
    n_ticks = int(round((vmax - vmin) / step)) + 1
    widest = max(len(f"{vmin:g}"), len(f"{vmax:g}"))
    char_in = 0.075                       # rough width of one digit at this font size
    needed = widest * char_in + 0.12      # plus breathing room
    max_labels = max(2, int(width_in / needed))
    every = math.ceil(n_ticks / max_labels)
    return step * every


def render_number_line(spec: dict, path: str) -> str:
    vmin = float(spec.get("min", 0))
    vmax = float(spec.get("max", 10))
    step = float(spec.get("step", 1)) or 1
    points = spec.get("points") or []
    jumps = spec.get("jumps") or []

    n_ticks = int(round((vmax - vmin) / step)) + 1
    width = min(12.0, max(6.0, n_ticks * 0.42))
    height = 2.4 if jumps else 1.7

    fig, ax = plt.subplots(figsize=(width, height))
    ax.set_xlim(vmin - step * 0.6, vmax + step * 0.6)
    ax.set_ylim(-1.0, 1.6 if jumps else 0.8)
    ax.axis("off")

    ax.annotate("", xy=(vmax + step * 0.5, 0), xytext=(vmin - step * 0.5, 0),
                 arrowprops=dict(arrowstyle="-|>", lw=2.2, color=DEEP_BLUE))

    label_step = _nice_label_step(vmin, vmax, step, width)
    v = vmin
    while v <= vmax + 1e-9:
        is_labelled = abs((v - vmin) % label_step) < 1e-9 or abs(v - vmax) < 1e-9
        ax.plot([v, v], [-0.13, 0.13] if is_labelled else [-0.07, 0.07],
                 color=DEEP_BLUE, lw=2.0 if is_labelled else 1.2)
        if is_labelled:
            ax.text(v, -0.32, f"${v:g}$", ha="center", va="top",
                     fontsize=12, color=DEEP_BLUE)
        v += step

    for p in points:
        try:
            val = float(p.get("value"))
        except (TypeError, ValueError):
            continue
        ax.plot([val], [0], "o", ms=11, color=ORANGE, zorder=5)
        if p.get("label"):
            ax.text(val, 0.30, str(p["label"]), ha="center", va="bottom",
                     fontsize=11, color=ORANGE, fontweight="bold")

    # Jump arrows live in a band ABOVE the labels, with thin stems down to
    # the line. Drawn as arcs directly on the line they tangle with points.
    for i, j in enumerate(jumps):
        try:
            a, b = float(j.get("from")), float(j.get("to"))
        except (TypeError, ValueError):
            continue
        y = 0.75 + (i % 2) * 0.45
        ax.plot([a, a], [0.05, y], lw=1.0, color=FUN_BLUE, alpha=0.6)
        ax.plot([b, b], [0.05, y], lw=1.0, color=FUN_BLUE, alpha=0.6)
        ax.annotate("", xy=(b, y), xytext=(a, y),
                     arrowprops=dict(arrowstyle="-|>", lw=2.0, color=FUN_BLUE))
        if j.get("label"):
            ax.text((a + b) / 2, y + 0.08, str(j["label"]), ha="center",
                     va="bottom", fontsize=11, color=FUN_BLUE, fontweight="bold")

    return _finish(fig, path)


# ── Countable object groups ────────────────────────────────────────
def _draw_shape(ax, kind: str, x: float, y: float, r: float, color: str):
    if kind == "square":
        ax.add_patch(plt.Rectangle((x - r, y - r), 2 * r, 2 * r,
                                     facecolor=color, edgecolor=DEEP_BLUE, lw=1.6))
    elif kind == "triangle":
        ax.add_patch(plt.Polygon([[x, y + r], [x - r, y - r], [x + r, y - r]],
                                   facecolor=color, edgecolor=DEEP_BLUE, lw=1.6))
    elif kind == "star":
        pts = []
        for i in range(10):
            ang = math.pi / 2 + i * math.pi / 5
            rad = r if i % 2 == 0 else r * 0.45
            pts.append([x + rad * math.cos(ang), y + rad * math.sin(ang)])
        ax.add_patch(plt.Polygon(pts, facecolor=color, edgecolor=DEEP_BLUE, lw=1.4))
    else:
        ax.add_patch(plt.Circle((x, y), r, facecolor=color,
                                  edgecolor=DEEP_BLUE, lw=1.6))


def render_object_group(spec: dict, path: str) -> str:
    groups = [int(g) for g in (spec.get("groups") or [3]) if int(g) > 0][:4]
    shape = spec.get("shape", "circle")
    per_row = 5
    colors = [ORANGE, FUN_BLUE, YELLOW, GREY]

    widths = [min(len_g, per_row) for len_g in groups]
    total_w = sum(widths) + (len(groups) - 1) * 1.2
    max_rows = max(math.ceil(g / per_row) for g in groups)

    fig, ax = plt.subplots(figsize=(min(11, max(4, total_w * 0.85)),
                                      max(1.8, max_rows * 1.1 + 0.4)))
    ax.set_aspect("equal")
    ax.axis("off")

    x_cursor = 0.0
    for gi, count in enumerate(groups):
        rows = math.ceil(count / per_row)
        cols = min(count, per_row)
        for idx in range(count):
            r, c = divmod(idx, per_row)
            _draw_shape(ax, shape, x_cursor + c * 1.0,
                         (rows - 1 - r) * 1.0, 0.38, colors[gi % len(colors)])
        x_cursor += cols * 1.0
        if gi < len(groups) - 1:
            ax.text(x_cursor + 0.35, (rows - 1) * 0.5, "and", ha="center",
                     va="center", fontsize=13, color=DEEP_BLUE, style="italic")
            x_cursor += 1.2

    ax.set_xlim(-0.7, x_cursor + 0.2)
    ax.set_ylim(-0.7, max_rows * 1.0 + 0.1)
    return _finish(fig, path)


# ── Ten frame ──────────────────────────────────────────────────────
def render_ten_frame(spec: dict, path: str) -> str:
    filled = max(0, min(10, int(spec.get("filled", 0))))
    fig, ax = plt.subplots(figsize=(4.4, 2.0))
    ax.set_aspect("equal")
    ax.axis("off")
    for i in range(10):
        r, c = divmod(i, 5)
        ax.add_patch(plt.Rectangle((c, 1 - r), 1, 1, facecolor="white",
                                     edgecolor=DEEP_BLUE, lw=2.0))
        if i < filled:
            ax.add_patch(plt.Circle((c + 0.5, 1 - r + 0.5), 0.32,
                                      facecolor=ORANGE, edgecolor=DEEP_BLUE, lw=1.4))
    ax.set_xlim(-0.2, 5.2)
    ax.set_ylim(-0.2, 2.2)
    return _finish(fig, path)


# ── Array ──────────────────────────────────────────────────────────
def render_array(spec: dict, path: str) -> str:
    rows = max(1, min(12, int(spec.get("rows", 3))))
    cols = max(1, min(12, int(spec.get("cols", 4))))
    fig, ax = plt.subplots(figsize=(min(8, cols * 0.55 + 1),
                                      min(6, rows * 0.55 + 1)))
    ax.set_aspect("equal")
    ax.axis("off")
    for r in range(rows):
        for c in range(cols):
            ax.add_patch(plt.Circle((c, rows - 1 - r), 0.34, facecolor=FUN_BLUE,
                                      edgecolor=DEEP_BLUE, lw=1.4))
    ax.set_xlim(-0.7, cols - 0.3)
    ax.set_ylim(-0.7, rows - 0.3)
    return _finish(fig, path)


# ── Bar model ──────────────────────────────────────────────────────
def render_bar_model(spec: dict, path: str) -> str:
    parts = spec.get("parts") or [1, 1]
    labels = [str(p) for p in parts]
    try:
        widths = [max(0.25, float(p)) for p in parts]
    except (TypeError, ValueError):
        widths = [1.0] * len(parts)
    total = sum(widths)

    fig, ax = plt.subplots(figsize=(8, 2.3))
    ax.axis("off")
    x = 0.0
    for i, (w, lab) in enumerate(zip(widths, labels)):
        ax.add_patch(plt.Rectangle((x, 0.55), w, 0.6,
                                     facecolor=[ORANGE, FUN_BLUE, YELLOW, GREY][i % 4],
                                     edgecolor=DEEP_BLUE, lw=2.0, alpha=0.85))
        ax.text(x + w / 2, 0.85, lab, ha="center", va="center",
                 fontsize=14, color="white", fontweight="bold")
        x += w

    ax.add_patch(plt.Rectangle((0, 0.05), total, 0.35, facecolor="white",
                                 edgecolor=DEEP_BLUE, lw=2.0, linestyle="--"))
    ax.text(total / 2, 0.22, str(spec.get("total_label", "?")), ha="center",
             va="center", fontsize=14, color=DEEP_BLUE, fontweight="bold")
    ax.set_xlim(-0.15, total + 0.15)
    ax.set_ylim(-0.05, 1.35)
    return _finish(fig, path)


_RENDERERS = {
    "number_line": render_number_line,
    "object_group": render_object_group,
    "ten_frame": render_ten_frame,
    "array": render_array,
    "bar_model": render_bar_model,
}


# ── OpenAI image generation (decorative / photo-real only) ─────────
IMAGE_STYLE_SUFFIX = (
    " Simple, clean, child-friendly illustration for a printed primary "
    "school worksheet. Flat colours, high contrast, plenty of white space. "
    "No text, numbers, letters or labels anywhere in the image."
)


def generate_realistic_image(prompt: str) -> str | None:
    """Draw a decorative illustration with OpenAI's image model.

    NEVER used where the maths must be right — a diffusion model cannot be
    trusted to place exactly 7 counters or tick 24 on a number line. Those
    go through render_diagram() above, which is deterministic. This exists
    for scene-setting artwork ("children playing in a park") where being
    approximately right is fine.

    Returns the diagram id, or None if no key is set or the call fails —
    a worksheet with no decoration is perfectly serviceable, so this never
    raises into the generation flow.
    """
    if not config.OPENAI_API_KEY:
        return None

    key = hashlib.sha1((prompt + config.OPENAI_IMAGE_MODEL).encode()).hexdigest()[:12]
    path = DIAGRAM_DIR / f"{key}.png"
    if path.exists():           # same prompt, same picture — don't pay twice
        return key

    body = {
        "model": config.OPENAI_IMAGE_MODEL,
        "prompt": prompt + IMAGE_STYLE_SUFFIX,
        "size": "1024x1024",
        "n": 1,
    }
    # gpt-image-1 always returns base64 and REJECTS response_format;
    # dall-e-3 defaults to a URL, so it has to be asked for base64.
    if not config.OPENAI_IMAGE_MODEL.startswith("gpt-image"):
        body["response_format"] = "b64_json"

    try:
        resp = httpx.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
            json=body, timeout=180,
        )
        if resp.status_code != 200:
            return None
        item = resp.json()["data"][0]
        if item.get("b64_json"):
            path.write_bytes(base64.b64decode(item["b64_json"]))
        elif item.get("url"):
            img = httpx.get(item["url"], timeout=60)
            img.raise_for_status()
            path.write_bytes(img.content)
        else:
            return None
        return key
    except Exception:
        return None


def render_diagram(spec: dict | None) -> str | None:
    """Draw a diagram from a model-supplied spec.

    Returns the diagram id (filename stem) or None. Never raises — a
    broken spec means no picture, which is survivable; a 500 on the whole
    generation is not.
    """
    if not isinstance(spec, dict):
        return None
    kind = spec.get("kind")
    fn = _RENDERERS.get(kind)
    if fn is None:
        return None
    key, path = _path_for(spec)
    try:
        fn(spec, path)
        return key
    except Exception:
        plt.close("all")
        return None
