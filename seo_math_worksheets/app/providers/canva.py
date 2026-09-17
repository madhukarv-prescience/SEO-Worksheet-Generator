"""
The image-replacement fallback.

Reached ONLY when validation says the questions are fine but a picture is
not (`verdict == "images_failed"`). Questions are never touched on this
path — that is the whole point of separating the two verdicts.

Order of attempts, cheapest first:

  1. REDRAW. Render the same spec again with our own renderer. Most
     "bad image" cases are a transient render failure, and this costs
     nothing and needs no key. It fixes the majority.

  2. CANVA. Only if a redraw still fails AND Canva credentials exist.

READ THIS BEFORE WIRING CANVA UP FOR REAL
-----------------------------------------
Canva's Connect API does NOT draw original artwork from a prompt. Its
Autofill endpoint places images you already own into a Brand Template you
designed yourself in the Canva UI. So this path needs:

  - a Canva integration (CANVA_CLIENT_ID / CANVA_CLIENT_SECRET)
  - a Brand Template with an image placeholder (CANVA_BRAND_TEMPLATE_ID)
  - a folder of generic fallback artwork you supply

Without all of that, this module reports honestly that it cannot help,
and the worksheet is shown with the question intact and no picture —
which is far better than a wrong picture on a maths worksheet.
"""
from __future__ import annotations

from app import config
from app.providers import images


def replace_images(worksheet: dict, bad_numbers: list[int]) -> dict:
    """Try to fix only the named questions' pictures.

    Returns {"fixed": [...], "still_bad": [...], "method": "redraw"|"canva"|"none"}
    and mutates the worksheet's diagram ids in place.
    """
    fixed, still_bad = [], []
    by_number = {q.get("number"): q for q in worksheet.get("questions") or []}

    for n in bad_numbers:
        q = by_number.get(n)
        if not q:
            continue

        # 1. Redraw from the original spec.
        spec = q.get("diagram_spec")
        if spec:
            new_id = images.render_diagram(spec)
            if new_id:
                q["diagram_id"] = new_id
                fixed.append(n)
                continue

        # 2. Canva, if it is actually configured.
        if config.canva_configured():
            asset = _canva_asset(q)
            if asset:
                q["diagram_id"] = asset
                fixed.append(n)
                continue

        # 3. Neither worked. Drop the picture rather than keep a broken
        # one — the question still stands on its own.
        q["diagram_id"] = None
        q["diagram_spec"] = None
        still_bad.append(n)

    method = "redraw" if fixed and not config.canva_configured() else (
        "canva" if fixed else "none")
    return {"fixed": fixed, "still_bad": still_bad, "method": method}


def _canva_asset(question: dict) -> str | None:
    """Placeholder for the real Canva Autofill call.

    Left unimplemented on purpose: writing a plausible-looking integration
    against an API nobody here can run would be worse than an honest gap —
    it would look finished and fail the first time someone added keys. The
    setup this needs is documented at the top of this file.
    """
    return None


def availability() -> dict:
    """What the image fallback can currently do — used by the UI so it can
    say something true rather than promising Canva when there are no keys."""
    return {
        "redraw": True,                        # always available, no key
        "canva": config.canva_configured(),
    }
