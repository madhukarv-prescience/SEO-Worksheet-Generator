"""
One interface, several providers, automatic selection.

`complete_json(system, user)` returns a parsed dict. Every caller uses
that and stays ignorant of which company answered — which is the point:
when a key changes, nothing above this file changes.

Providers are imported lazily so the app starts with none of their SDKs
installed.
"""
from __future__ import annotations

import json
import re
import time

from app import config


class ProviderError(RuntimeError):
    """Raised with a message that is safe to show a non-technical user."""


def _extract_json(text: str) -> dict:
    """Pull a JSON object out of a model response.

    Models wrap JSON in prose or ```json fences more often than their
    documentation admits, so this tolerates both rather than failing on
    an otherwise-perfect response.
    """
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise ProviderError(
            "The question writer returned something we couldn't read. "
            "Try generating again."
        )


# ── Groq ───────────────────────────────────────────────────────────
# Groq reports its per-minute token budget on every response. Reading it
# and pacing against it is the difference between a bulk run that works
# and one where every request after the first is rejected.
_RATE = {"remaining": None, "reset_seconds": 0.0, "limit": None}


def rate_state() -> dict:
    return dict(_RATE)


def _parse_reset(value: str | None) -> float:
    """Groq sends durations like '915ms', '2.5s', '1m30s'."""
    if not value:
        return 0.0
    total, num, i = 0.0, "", 0
    while i < len(value):
        ch = value[i]
        if ch.isdigit() or ch == ".":
            num += ch
        elif value.startswith("ms", i):
            total += float(num or 0) / 1000.0; num = ""; i += 1
        elif ch == "m":
            total += float(num or 0) * 60; num = ""
        elif ch == "s":
            total += float(num or 0); num = ""
        i += 1
    return total + float(num or 0)


def _note_rate_headers(resp) -> None:
    h = resp.headers
    if "x-ratelimit-limit-tokens" in h:
        try:
            _RATE["limit"] = int(h["x-ratelimit-limit-tokens"])
            _RATE["remaining"] = int(h.get("x-ratelimit-remaining-tokens", 0))
            _RATE["reset_seconds"] = _parse_reset(h.get("x-ratelimit-reset-tokens"))
        except ValueError:
            pass


def _wait_for_budget(needed: int) -> None:
    """Pause until there is room for a request of this size.

    Without this, a bulk run fires the next request while the minute's
    budget is still spent, gets a 429, burns a retry, and reports "the
    question writer is busy" — which reads as a fault and is really just
    impatience.
    """
    remaining = _RATE.get("remaining")
    if remaining is None or remaining >= needed:
        return
    wait = min(_RATE.get("reset_seconds") or 0, 65) + 1
    time.sleep(wait)
    _RATE["remaining"] = _RATE.get("limit")


def _groq(system: str, user: str, max_retries: int = 3) -> str:
    import httpx

    # Rough: ~4 characters per token, plus the reply we are asking for.
    needed = (len(system) + len(user)) // 4 + config.GROQ_MAX_TOKENS

    for attempt in range(max_retries):
        _wait_for_budget(needed)
        resp = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
            json={
                "model": config.GROQ_MODEL,
                "messages": [{"role": "system", "content": system},
                              {"role": "user", "content": user}],
                "response_format": {"type": "json_object"},
                "temperature": 0.8,
                # REQUIRED. Without an explicit budget Groq's default is
                # far too small for this model — it spends ~5k tokens
                # (much of it on a hidden reasoning field) and the JSON
                # truncates, which comes back as a 400
                # "json_validate_failed" with an EMPTY failed_generation.
                # That error looks like a bad prompt and is not.
                "max_tokens": config.GROQ_MAX_TOKENS,
            },
            timeout=180,
        )
        # Groq returns 413 when a request exceeds the per-minute token
        # allowance — it is a rate limit wearing a different number, and
        # retrying after a pause works. Treated as a hard failure it looks
        # like "your prompt is too big", which it usually isn't.
        _note_rate_headers(resp)

        if resp.status_code in (429, 413):
            # Groq tells us how long to wait; obey it rather than guessing.
            hint = re.search(r"try again in ([\d.]+)s", resp.text)
            wait = float(hint.group(1)) + 1 if hint else 5 * (attempt + 1)
            if "tokens per day" in resp.text.lower() or "TPD" in resp.text:
                # Tell them WHEN, and roughly how much is left — "resets
                # tomorrow" is wrong (it is a rolling window) and gives
                # them nothing to plan around.
                when = re.search(r"try again in ([\dhms]+(?:\.\d+s)?)", resp.text)
                used = re.search(r"Limit (\d+), Used (\d+)", resp.text)
                detail = f" ({used.group(2)} of {used.group(1)} used today)" if used else ""
                raise ProviderError(
                    "The daily question-writing allowance is used up"
                    + detail
                    + (f". Try again in {when.group(1)}." if when else ".")
                )
            if attempt == max_retries - 1:
                raise ProviderError("The question writer is busy. Try again in a minute.")
            time.sleep(min(wait, 30))
            continue
        if resp.status_code == 400 and "json_validate_failed" in resp.text:
            # The answer was cut off mid-JSON. Worth one more go before
            # giving up — a shorter answer often completes.
            if attempt < max_retries - 1:
                continue
            raise ProviderError(
                "The worksheet came back incomplete. Try again, or ask for "
                "fewer questions.")
        if resp.status_code != 200:
            raise ProviderError(f"Question writing failed ({resp.status_code}).")
        return resp.json()["choices"][0]["message"]["content"]
    raise ProviderError("The question writer is busy. Try again in a minute.")


# ── Anthropic ──────────────────────────────────────────────────────
def _anthropic(system: str, user: str) -> str:
    import httpx

    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": config.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": config.ANTHROPIC_MODEL,
            "max_tokens": 8000,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=180,
    )
    if resp.status_code != 200:
        raise ProviderError(f"Question writing failed ({resp.status_code}).")
    return resp.json()["content"][0]["text"]


# ── OpenAI ─────────────────────────────────────────────────────────
def _openai(system: str, user: str) -> str:
    import httpx

    resp = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
        json={
            "model": config.OPENAI_MODEL,
            "messages": [{"role": "system", "content": system},
                          {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
        },
        timeout=180,
    )
    if resp.status_code != 200:
        raise ProviderError(f"Question writing failed ({resp.status_code}).")
    return resp.json()["choices"][0]["message"]["content"]


# ── Sample mode ────────────────────────────────────────────────────
def _sample(system: str, user: str) -> str:
    """No key configured. Produces a structurally valid worksheet so the
    whole interface — generation, review, regeneration, export — can be
    exercised and demoed before anyone pays for anything.

    Content is obviously placeholder by design. It must never be mistaken
    for real generated output.
    """
    # Match ONLY the closing-message request's own marker. Matching on the
    # phrase "closing message" also hit the worksheet prompt (which has a
    # "CLOSING MESSAGE for the Reflect section" block), so every generation
    # came back as a closing note with zero questions.
    m = re.search(r"TOPIC THEY JUST PRACTISED: (.+)", user)
    if m:
        topic = m.group(1).strip()
        return json.dumps({"closing_message":
            f"Great work on {topic or 'today'} — next time we build on it. "
            "(Sample text: finish setup to write these for real.)"})

    # \d only, and the label is "Kindergarten" not "Grade 0" — so both
    # Grade 10 (read as 1) and Kindergarten (unmatched) were wrong.
    grade_label = "Grade 3"
    m = re.search(r"GRADE: (Kindergarten|Grade \d+)", user)
    if m:
        grade_label = m.group(1)
    grade = 0 if grade_label == "Kindergarten" else int(grade_label.split()[-1])
    count = 6
    m = re.search(r"WORKSHEET SHAPE \((\d+) questions", user)
    if m:
        count = min(int(m.group(1)), 8)

    sections = ["Warm up"] + ["Practice"] * (count - 3) + ["Stretch", "Reflect"]
    questions = []
    for i in range(count):
        questions.append({
            "number": i + 1,
            "section": sections[i] if i < len(sections) else "Practice",
            "text": f"Sample question {i + 1} for {grade_label}. "
                     "This is placeholder text, not a real question.",
            "answer": "—",
            "dok": 1 if i == 0 else 2,
            "representation": "abstract",
            "diagram": None,
        })
    return json.dumps({
        "title": f"Sample Worksheet — {grade_label}",
        "skill": "Sample content",
        "questions": questions,
        "closing_note": "This is sample content shown before setup is finished.",
    })


_PROVIDERS = {
    "groq": _groq,
    "anthropic": _anthropic,
    "openai": _openai,
    "sample": _sample,
}


def complete_json(system: str, user: str) -> dict:
    provider = config.active_text_provider()
    fn = _PROVIDERS.get(provider)
    if fn is None:
        raise ProviderError(f"Unknown provider setting: {provider}")
    return _extract_json(fn(system, user))


def is_sample_mode() -> bool:
    return config.active_text_provider() == "sample"
