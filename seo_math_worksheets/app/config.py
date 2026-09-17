"""
Configuration for Bhanzu SEO Math Worksheets.

Everything comes from `seo_math_worksheets/.env`. Nothing is hardcoded and nothing
is shared with the BLC Worksheets project — separate project, separate
keys, separate everything.

PROVIDER SELECTION IS AUTOMATIC. Paste in whichever key you happen to
have and the app uses it. No key at all still runs the whole app in
sample mode, so the interface can be demoed and reviewed before anyone
spends a cent.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

APP_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=APP_ROOT / ".env")

DATA_DIR = Path(os.getenv("SEO_STUDIO_DATA", APP_ROOT / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
EXPORT_DIR = DATA_DIR / "exports"
DIAGRAM_DIR = DATA_DIR / "diagrams"
for _d in (DATA_DIR, UPLOAD_DIR, EXPORT_DIR, DIAGRAM_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Tests override this so they never touch the live database.
DB_PATH = Path(os.getenv("SEO_STUDIO_DB", DATA_DIR / "studio.db"))

# Where the already-fetched K5 worksheets live. Reused as-is — that
# fetcher works and there is no reason to rebuild it.
K5_OUTPUT_DIR = APP_ROOT.parent / "k5-worksheet-fetcher" / "data" / "output"

# ── Text generation keys ───────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
# Must be set explicitly — see the note in providers/llm.py::_groq.
# 8000 was exactly the free tier's PER-MINUTE token budget, so every
# request reserved the entire minute and the next was always rejected.
# 5200 fits a worksheet (measured ~5175 completion tokens) with headroom.
GROQ_MAX_TOKENS = int(os.getenv("GROQ_MAX_TOKENS", "5200"))
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# ── Image keys (optional — see IMAGE STRATEGY in README) ───────────
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
CANVA_CLIENT_ID = os.getenv("CANVA_CLIENT_ID", "")
CANVA_CLIENT_SECRET = os.getenv("CANVA_CLIENT_SECRET", "")
CANVA_BRAND_TEMPLATE_ID = os.getenv("CANVA_BRAND_TEMPLATE_ID", "")
# Where Canva redirects back to after someone approves the connection.
# Must be registered EXACTLY (including scheme and trailing slash rules)
# in the integration's settings in the Canva Developer Portal.
CANVA_REDIRECT_URI = os.getenv("CANVA_REDIRECT_URI", "http://127.0.0.1:8020/api/canva/callback")

# Encrypts the Canva refresh token at rest in the database (it is a live
# credential, not a static key — see providers/canva.py). Generate one
# with: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# If unset, a key is generated at startup and printed once — fine for a
# single local run, but it means tokens stored before a restart without
# this set become unreadable after restart. Set it explicitly for any
# shared/deployed instance.
APP_SECRET_KEY = os.getenv("APP_SECRET_KEY", "")

# Explicit override; "auto" means pick whichever key exists.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "auto").lower()


def active_text_provider() -> str:
    """Which provider will actually be used for question writing.

    Returns one of: groq | anthropic | openai | sample
    'sample' means no key is configured — the app still works end to end,
    it just produces clearly-labelled placeholder content.
    """
    if LLM_PROVIDER != "auto":
        return LLM_PROVIDER
    if GROQ_API_KEY:
        return "groq"
    if ANTHROPIC_API_KEY:
        return "anthropic"
    if OPENAI_API_KEY:
        return "openai"
    return "sample"


def active_image_strategy() -> str:
    """Which route illustrations take.

    'drawn'  — Python renders the diagram from a structured spec. Always
               available, costs nothing, and is geometrically correct.
               This is the default and the recommended path for maths.
    'openai' — photo-real / decorative generation. Needs OPENAI_API_KEY.
    """
    return "openai" if OPENAI_API_KEY else "drawn"


def canva_configured() -> bool:
    return bool(CANVA_CLIENT_ID and CANVA_CLIENT_SECRET and CANVA_BRAND_TEMPLATE_ID)


def setup_complete() -> bool:
    """True when the app can write real questions."""
    return active_text_provider() != "sample"


def key_status() -> dict:
    """What's configured, for a settings screen — never the key values
    themselves, only whether one is present and which one is active."""
    active = active_text_provider()
    return {
        "text_providers": {
            "groq": {"configured": bool(GROQ_API_KEY), "active": active == "groq",
                       "model": GROQ_MODEL},
            "anthropic": {"configured": bool(ANTHROPIC_API_KEY), "active": active == "anthropic",
                           "model": ANTHROPIC_MODEL},
            "openai": {"configured": bool(OPENAI_API_KEY), "active": active == "openai",
                        "model": OPENAI_MODEL},
        },
        "active_provider": active,
        "image_strategy": active_image_strategy(),
        "openai_images_configured": bool(OPENAI_API_KEY),
        "canva": {
            "configured": canva_configured(),
            "client_id_set": bool(CANVA_CLIENT_ID),
            "client_secret_set": bool(CANVA_CLIENT_SECRET),
            "brand_template_set": bool(CANVA_BRAND_TEMPLATE_ID),
        },
    }
