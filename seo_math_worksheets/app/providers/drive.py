"""
Pushes approved worksheets to one shared Google Drive folder — the
meeting point for a team where everyone runs their own independent copy
of the tool (see ARCHITECTURE.md, "Team deployment"). No shared server,
no shared database: everyone's local Approved PDFs land in the same
Drive folder, organised into a subfolder per source category, so
several people working on different K5 categories at once don't collide.

WHY A SERVICE ACCOUNT, NOT OAUTH (UNLIKE CANVA)
────────────────────────────────────────────────
Canva's Autofill API needs a live human logging in via a browser, because
it acts ON BEHALF OF a specific Canva user. This is a different shape of
problem: we just need to drop files into ONE folder that already belongs
to someone (the project owner). A Google Cloud "service account" is
built for exactly this — it's its own robot identity with its own email
address (something like `xyz@project.iam.gserviceaccount.com`). Share a
Drive folder with that email, the way you'd share it with any colleague,
and the backend can upload into it forever with no login flow, no
browser redirect, and nothing to click "Allow" on repeatedly.

ONE-TIME SETUP (done ONCE by whoever owns the shared Drive folder — not
by every teammate, and not something this code can do on its own behalf,
the same way it can't create a Canva account for you):
  1. console.cloud.google.com -> create a project (or reuse one)
  2. Enable the "Google Drive API" for that project
  3. Create a Service Account, then create a JSON key for it and
     download the file
  4. Save that file as `service_account.json` inside this folder
     (it's already in .gitignore — never commit it)
  5. Open the JSON file, copy the "client_email" value
  6. In Google Drive, right-click the shared folder -> Share -> paste
     that email in, give it Editor access
  7. Copy the folder's ID from its URL (the part after /folders/) into
     GOOGLE_DRIVE_FOLDER_ID in .env

Without this configured, sending to Drive is simply unavailable — the UI
says so plainly rather than pretending the button works.
"""
from __future__ import annotations

from pathlib import Path

from app import config


def configured() -> bool:
    return bool(config.GOOGLE_SERVICE_ACCOUNT_FILE
                and Path(config.GOOGLE_SERVICE_ACCOUNT_FILE).is_file()
                and config.GOOGLE_DRIVE_FOLDER_ID)


def _service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        config.GOOGLE_SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# Subfolder ids are looked up once per run and reused — creating a
# folder is a write, and calling it once per upload would mean a batch
# of 20 approvals makes 20 redundant "does this folder exist" round trips.
_subfolder_cache: dict[str, str] = {}


def _subfolder_id(service, name: str) -> str:
    if name in _subfolder_cache:
        return _subfolder_cache[name]

    safe_name = name.replace("'", "\\'")
    query = (
        f"'{config.GOOGLE_DRIVE_FOLDER_ID}' in parents "
        f"and name = '{safe_name}' "
        "and mimeType = 'application/vnd.google-apps.folder' "
        "and trashed = false"
    )
    results = service.files().list(q=query, fields="files(id)", pageSize=1).execute()
    files = results.get("files", [])
    if files:
        folder_id = files[0]["id"]
    else:
        created = service.files().create(
            body={
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [config.GOOGLE_DRIVE_FOLDER_ID],
            },
            fields="id",
        ).execute()
        folder_id = created["id"]

    _subfolder_cache[name] = folder_id
    return folder_id


def upload_worksheet(pdf_path: str, filename: str, category: str) -> dict:
    """Uploads one approved worksheet PDF into <shared folder>/<category>/.

    `category` is the source's origin_detail turned into a folder name —
    e.g. "Kindergarten Simple Math" — so worksheets from different K5
    categories (which different teammates might each be working through)
    land in clearly separated subfolders of the one shared folder instead
    of one flat pile of hundreds of files.

    Raises RuntimeError with a message safe to show a reviewer if Drive
    isn't configured or the upload fails — callers decide whether that
    should block anything or just be reported.
    """
    if not configured():
        raise RuntimeError(
            "A shared Drive folder isn't set up yet. See the 'Shared Drive "
            "folder' section in the project README to configure one."
        )

    from googleapiclient.http import MediaFileUpload

    service = _service()
    folder_id = _subfolder_id(service, category)

    media = MediaFileUpload(pdf_path, mimetype="application/pdf", resumable=False)
    file = service.files().create(
        body={"name": filename, "parents": [folder_id]},
        media_body=media,
        fields="id, webViewLink",
    ).execute()
    return {"file_id": file["id"], "view_link": file.get("webViewLink")}
