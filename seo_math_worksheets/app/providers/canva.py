"""
The image-replacement fallback, and the Canva Connect OAuth flow it needs.

Reached ONLY when validation says the questions are fine but a picture is
not (`verdict == "images_failed"`). Questions are never touched on this
path — that is the whole point of separating the two verdicts.

Order of attempts, cheapest first:

  1. REDRAW. Render the same spec again with our own renderer. Most
     "bad image" cases are a transient render failure, and this costs
     nothing and needs no key. It fixes the majority.
  2. CANVA. Only if a redraw still fails AND a live Canva connection
     exists (see below — this is not just a key being present).

═══════════════════════════════════════════════════════════════════════
READ THIS BEFORE ASSUMING THIS "JUST NEEDS AN API KEY"
═══════════════════════════════════════════════════════════════════════

1. CANVA'S AUTOFILL API REQUIRES A CANVA ENTERPRISE PLAN.
   Direct from Canva's own docs: "To use the Brand Template and Autofill
   APIs, your integration must act on behalf of a user that's a member
   of a Canva Enterprise organization." If the team's Canva plan is
   Free/Pro/Teams, this entire module is a dead end no matter what
   credentials exist — there is no workaround, this is a plan-tier gate
   enforced by Canva, not something fixable in code.

2. THIS IS OAUTH 2.0 AUTHORIZATION CODE + PKCE, NOT A STATIC API KEY.
   A real person must click "Allow" in a browser once. There is no
   server-to-server "client_credentials" shortcut for this API — an
   earlier version of this file assumed one and was wrong. Concretely:
     - CANVA_CLIENT_ID / CANVA_CLIENT_SECRET identify the INTEGRATION,
       not a user. They alone cannot call the Autofill API.
     - A connection is established by visiting GET /api/canva/connect
       (see app/main.py), which redirects to Canva, where a real team
       member logs in and approves it. Canva then redirects back to
       CANVA_REDIRECT_URI with a one-time code, which is exchanged for
       an access token + refresh token — stored (encrypted) in the
       `canva_connection` table, not in .env.
     - That connection can expire or be revoked from Canva's side at
       any time. `canva_configured()` checking three .env values only
       tells you the INTEGRATION exists; `is_connected()` in this file
       is what tells you whether autofill can actually be called.

3. CANVA CANNOT DRAW ORIGINAL ARTWORK. Autofill places an image you
   already own into a Brand Template you designed yourself in the Canva
   UI. It is not a prompt-to-image generator.

Without a completed connection, this module reports honestly that it
cannot help, and the worksheet is shown with the question intact and no
picture — far better than a wrong picture on a maths worksheet.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone

import httpx

from app import config
from app.db import get_conn, new_id, now
from app.providers import images

CANVA_AUTHORIZE_URL = "https://www.canva.com/api/oauth/authorize"
CANVA_TOKEN_URL = "https://api.canva.com/rest/v1/oauth/token"
CANVA_API_BASE = "https://api.canva.com/rest/v1"

# Minimum scopes for exactly what this module does: read/write brand
# templates' data fields, upload assets, and export designs. Canva's own
# security guidelines say to request the minimum needed — resist adding
# more here without a reason.
CANVA_SCOPES = "asset:write brandtemplate:content:read design:content:write design:content:read"


# ── Encryption at rest for the refresh/access tokens ────────────────
def _fernet():
    from cryptography.fernet import Fernet

    key = config.APP_SECRET_KEY
    if not key:
        # No key configured: derive a stable one from the Canva client
        # secret so at least restarts within the same .env don't break —
        # but this is a fallback, not the recommended path. See the note
        # on APP_SECRET_KEY in config.py.
        seed = (config.CANVA_CLIENT_SECRET or "seo-math-worksheets-dev").encode()
        key = base64.urlsafe_b64encode(hashlib.sha256(seed).digest())
    return Fernet(key if isinstance(key, bytes) else key.encode())


def _encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


# ── PKCE ─────────────────────────────────────────────────────────────
def _pkce_pair() -> tuple[str, str]:
    """Returns (code_verifier, code_challenge) per RFC 7636 (S256)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def start_authorization() -> str:
    """Begin the OAuth dance. Returns the URL to send the browser to.

    Call this from a route a real person clicks — never automatically,
    and never from a background job. Canva's security guidelines require
    the integration to be tied to a web app with registered redirect
    URIs; this assumes app/main.py serves CANVA_REDIRECT_URI.
    """
    if not (config.CANVA_CLIENT_ID and config.CANVA_CLIENT_SECRET):
        raise RuntimeError(
            "CANVA_CLIENT_ID / CANVA_CLIENT_SECRET are not set in .env. "
            "Create an integration at https://www.canva.com/developers/ first."
        )

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)
    with get_conn() as c:
        c.execute(
            "INSERT INTO oauth_state (state, code_verifier, created_at) VALUES (?,?,?)",
            (state, verifier, now()),
        )

    params = {
        "response_type": "code",
        "client_id": config.CANVA_CLIENT_ID,
        "redirect_uri": config.CANVA_REDIRECT_URI,
        "scope": CANVA_SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    from urllib.parse import urlencode
    return f"{CANVA_AUTHORIZE_URL}?{urlencode(params)}"


def complete_authorization(code: str, state: str) -> dict:
    """Handle Canva's redirect back after approval. Exchanges the
    one-time code for tokens and stores them (encrypted)."""
    with get_conn() as c:
        row = c.execute(
            "SELECT code_verifier FROM oauth_state WHERE state=?", (state,)
        ).fetchone()
        if row is None:
            raise RuntimeError(
                "This connection attempt has expired or was already used. "
                "Start again from the Setup tab."
            )
        c.execute("DELETE FROM oauth_state WHERE state=?", (state,))
        verifier = row["code_verifier"]

    resp = httpx.post(
        CANVA_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": config.CANVA_REDIRECT_URI,
            "client_id": config.CANVA_CLIENT_ID,
            "client_secret": config.CANVA_CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Canva rejected the connection (HTTP {resp.status_code}): "
            f"{resp.text[:300]}"
        )

    body = resp.json()
    expires_at = (datetime.now(timezone.utc)
                   + timedelta(seconds=int(body.get("expires_in", 3600)))).isoformat()

    with get_conn() as c:
        c.execute(
            """INSERT INTO canva_connection
                 (id, access_token, refresh_token, expires_at, connected_by, connected_at)
               VALUES ('default', ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 access_token=excluded.access_token,
                 refresh_token=excluded.refresh_token,
                 expires_at=excluded.expires_at,
                 connected_at=excluded.connected_at""",
            (_encrypt(body["access_token"]), _encrypt(body["refresh_token"]),
             expires_at, None, now()),
        )
    return {"connected": True, "expires_at": expires_at}


def is_connected() -> bool:
    with get_conn() as c:
        return c.execute(
            "SELECT 1 FROM canva_connection WHERE id='default'"
        ).fetchone() is not None


def disconnect() -> None:
    with get_conn() as c:
        c.execute("DELETE FROM canva_connection WHERE id='default'")


def connection_status() -> dict:
    with get_conn() as c:
        row = c.execute(
            "SELECT expires_at, connected_at FROM canva_connection WHERE id='default'"
        ).fetchone()
    if not row:
        return {"connected": False}
    expired = datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc)
    return {"connected": True, "connected_at": row["connected_at"],
             "access_token_expired": expired}  # a refresh_token can still renew it


def _access_token() -> str:
    """Returns a usable access token, refreshing it first if expired.

    Raises RuntimeError with a message safe to show a reviewer if there
    is no connection at all — this is the "please connect Canva" path,
    distinct from "Canva rejected the request".
    """
    with get_conn() as c:
        row = c.execute(
            "SELECT access_token, refresh_token, expires_at FROM canva_connection "
            "WHERE id='default'"
        ).fetchone()
    if not row:
        raise RuntimeError(
            "Canva isn't connected yet. Go to Setup and click 'Connect Canva'."
        )

    if datetime.fromisoformat(row["expires_at"]) > datetime.now(timezone.utc) + timedelta(minutes=1):
        return _decrypt(row["access_token"])

    # Expired — refresh. This does NOT need the person to click anything
    # again; the refresh token is good until Canva revokes it.
    resp = httpx.post(
        CANVA_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": _decrypt(row["refresh_token"]),
            "client_id": config.CANVA_CLIENT_ID,
            "client_secret": config.CANVA_CLIENT_SECRET,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            "Canva's connection has expired and could not be renewed. "
            "Go to Setup and reconnect."
        )
    body = resp.json()
    expires_at = (datetime.now(timezone.utc)
                   + timedelta(seconds=int(body.get("expires_in", 3600)))).isoformat()
    with get_conn() as c:
        c.execute(
            "UPDATE canva_connection SET access_token=?, refresh_token=?, expires_at=? "
            "WHERE id='default'",
            (_encrypt(body["access_token"]),
             _encrypt(body.get("refresh_token") or _decrypt(row["refresh_token"])),
             expires_at),
        )
    return body["access_token"]


# ── The actual autofill call — async jobs, must be polled ───────────
def _poll(url: str, headers: dict, timeout_s: int = 45) -> dict:
    """Canva's asset-upload, autofill, and export endpoints are all
    fire-and-poll: the POST returns a job id in 'in_progress' state, and
    the real result only appears once GET on the job returns 'success'.
    Treating the POST's response as the answer (as an earlier version of
    this file did) silently uses an empty/incomplete result."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = httpx.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        job = resp.json()["job"]
        if job["status"] == "success":
            return job
        if job["status"] == "failed":
            raise RuntimeError(f"Canva job failed: {job.get('error', 'unknown error')}")
        time.sleep(1.5)
    raise RuntimeError("Canva didn't finish in time.")


def _canva_asset(field_values: dict, image_path: str, out_path: str) -> str | None:
    """Runs the real Autofill flow: upload -> autofill -> export.

    field_values: text fields to autofill, e.g. {"title": "..."}. Field
      names must match the placeholders on the Canva Brand Template
      (check with GET /brand-templates/{id}/dataset if unsure).
    image_path: a local image to place into the template's image field.
    """
    if not config.canva_configured():
        return None
    if not is_connected():
        return None

    token = _access_token()
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Upload the image asset.
    with open(image_path, "rb") as f:
        # NOTE: the exact JSON shape of Asset-Upload-Metadata was not
        # confirmed against Canva's OpenAPI spec while writing this (the
        # documentation excerpt available described it only as "Base64
        # encoded filename", not the surrounding key). Verify this header
        # against https://www.canva.dev/docs/connect/api-reference/ once
        # a real connection exists to test against — if uploads fail with
        # a 400 mentioning this header, this is the line to fix.
        meta = base64.b64encode(b"worksheet-image.png").decode()
        upload = httpx.post(
            f"{CANVA_API_BASE}/asset-uploads",
            headers={**headers, "Content-Type": "application/octet-stream",
                      "Asset-Upload-Metadata": f'{{"name_base64":"{meta}"}}'},
            content=f.read(), timeout=60,
        )
    upload.raise_for_status()
    job = _poll(f"{CANVA_API_BASE}/asset-uploads/{upload.json()['job']['id']}", headers)
    asset_id = job["asset"]["id"]

    # 2. Autofill the brand template.
    autofill = httpx.post(
        f"{CANVA_API_BASE}/autofills",
        headers=headers,
        json={
            "brand_template_id": config.CANVA_BRAND_TEMPLATE_ID,
            "data": {
                **{k: {"type": "text", "text": v} for k, v in field_values.items()},
                "image": {"type": "image", "asset_id": asset_id},
            },
        },
        timeout=30,
    )
    autofill.raise_for_status()
    job = _poll(f"{CANVA_API_BASE}/autofills/{autofill.json()['job']['id']}", headers)
    design_id = job["result"]["design"]["id"]

    # 3. Export the finished design as a PNG.
    export = httpx.post(
        f"{CANVA_API_BASE}/exports",
        headers=headers,
        json={"design_id": design_id, "format": {"type": "png"}},
        timeout=30,
    )
    export.raise_for_status()
    job = _poll(f"{CANVA_API_BASE}/exports/{export.json()['job']['id']}", headers)
    export_url = job["urls"][0]

    img = httpx.get(export_url, timeout=60)
    img.raise_for_status()
    from pathlib import Path
    Path(out_path).write_bytes(img.content)
    return Path(out_path).stem


# ── The fallback entry point used by generate.py ────────────────────
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

        # 1. Redraw from the original spec — free, no connection needed.
        spec = q.get("diagram_spec")
        if spec:
            new_id_ = images.render_diagram(spec)
            if new_id_:
                q["diagram_id"] = new_id_
                fixed.append(n)
                continue

        # 2. Canva, only if a live connection exists (not just keys).
        if config.canva_configured() and is_connected():
            try:
                from app.config import DIAGRAM_DIR
                out_path = str(DIAGRAM_DIR / f"canva_{new_id()}.png")
                asset = _canva_asset({"title": worksheet.get("title", "")},
                                       image_path=out_path, out_path=out_path)
                if asset:
                    q["diagram_id"] = asset
                    fixed.append(n)
                    continue
            except Exception:
                pass  # fall through to "drop the picture"

        # 3. Neither worked. Drop the picture rather than keep a broken
        # one — the question still stands on its own.
        q["diagram_id"] = None
        q["diagram_spec"] = None
        still_bad.append(n)

    method = "redraw" if fixed and not (config.canva_configured() and is_connected()) else (
        "canva" if fixed else "none")
    return {"fixed": fixed, "still_bad": still_bad, "method": method}


def availability() -> dict:
    """What the image fallback can currently do — used by the UI so it can
    say something true rather than promising Canva when it isn't connected."""
    return {
        "redraw": True,                                  # always available, no key
        "canva_keys_set": config.canva_configured(),
        "canva_connected": is_connected(),
    }
