# SEO Math Worksheets

A tool that takes free source worksheets, turns them into brand-new
worksheets with different questions and pictures, checks them
automatically for mistakes, and lets a person approve them before
anything is used. This file will walk you through running it, even if
you've never touched code before.

**If you get stuck at any point, that's normal — jump to
[If something goes wrong](#if-something-goes-wrong) near the bottom.**

---

## What this actually does (no jargon)

1. **Fetch** — a small program downloads free worksheet PDFs from a
   website called K5 Learning and saves them on your computer.
2. **Generate** — you open a page in your web browser, pick one of
   those worksheets, choose a grade and a few settings, and click a
   button. An AI writes a brand-new worksheet with the same *kind* of
   questions but different numbers, names, and pictures.
3. **Check** — before you ever see it, the tool automatically checks
   the new worksheet for mistakes: wrong answers, missing questions,
   pictures that don't match the question, and so on.
4. **Review** — you look at what was made, fix anything by hand if you
   want, and click Approve.
5. **Download** — you get a finished, branded PDF.

Nothing goes out the door without a person clicking Approve. The AI
never publishes anything by itself.

---

## Part 1 — Get the code onto your computer

You only need to do this once.

### 1.1 Check you have Python

Open your computer's **Terminal** app (Mac: press `Cmd + Space`, type
`Terminal`, press Enter. Windows: search for "PowerShell").

Paste this in and press Enter:

```bash
python3 --version
```

- If you see something like `Python 3.11.4` — good, skip to 1.2.
- If you see an error, install Python first from
  **[python.org/downloads](https://www.python.org/downloads/)** (just
  click the big download button, then open the installer), then try
  the command again.

### 1.2 Download this repository

Still in Terminal, go to a folder where you want this project to live
(for example your Desktop) and run:

```bash
cd ~/Desktop
git clone https://github.com/madhukarv-prescience/SEO-Worksheet-Generator.git
cd SEO-Worksheet-Generator
```

If you get `command not found: git`, install Git from
**[git-scm.com/downloads](https://git-scm.com/downloads)** and try again.

You now have a folder called `SEO-Worksheet-Generator` with everything
in it.

---

## Part 2 — Get the worksheets running

Everything below happens inside the `seo_math_worksheets` folder.

### 2.1 Install what the tool needs

```bash
cd seo_math_worksheets
pip3 install -r requirements.txt
```

This downloads some free helper libraries. It takes a minute or two —
you'll see a lot of text scroll past, that's normal.

> **If you see "externally-managed-environment"**, your computer is
> protecting its built-in Python. Run these three lines instead, then
> continue as normal:
> ```bash
> python3 -m venv .venv
> source .venv/bin/activate
> pip3 install -r requirements.txt
> ```
> If you did this, remember: every time you come back to work on this
> later, run `source .venv/bin/activate` first, in this same folder.

### 2.2 Get a free key so the AI can write questions

The tool needs to talk to an AI service to write new questions. The
easiest, free option is **Groq**:

1. Go to **[console.groq.com/keys](https://console.groq.com/keys)**
2. Sign up (free, no credit card)
3. Click **Create API Key**, give it any name, copy the key it shows you
   (starts with `gsk_...`) — you can only see it once, so copy it now

### 2.3 Put the key into the tool

Back in Terminal, still inside `seo_math_worksheets`:

```bash
cp .env.example .env
open -e .env
```

A text file opens. Find the line that says:

```
GROQ_API_KEY=
```

Click right after the `=` and paste your key, so it reads:

```
GROQ_API_KEY=gsk_your_actual_key_here
```

**No spaces, no quote marks.** Save the file (`Cmd+S`) and close it.

### 2.4 Start the tool

```bash
python3 -m uvicorn app.main:app --port 8020
```

You'll see some lines ending in something like
`Uvicorn running on http://127.0.0.1:8020`. That means it's working.
**Leave this Terminal window open** — closing it stops the tool.

### 2.5 Open it

In your web browser, go to:

```
http://127.0.0.1:8020
```

You should see the app, with **bhanzu | SEO Math Worksheets** at the
top. Click the **Setup** tab in the top-right — it should show
**Groq — in use now**. If it does, you're fully set up.

---

## Part 3 — Using it, step by step

The three big steps run left to right along the bar under the header:
**① Library → ② Create → ③ Review & approve.**

### ① Library

This is where worksheets come from. You have three choices, all on the
same screen:

- **From our collections** — worksheets already downloaded from K5
  Learning. Either type a number and click **Add** (grabs that many),
  or click **Browse 📂** to open the folder and see every worksheet
  inside by name — tick the ones you actually want (click a name's
  **View** button to open the PDF first if you're not sure), then
  **Add selected**.
- **From Google Drive** — paste a link to a single PDF file
  (must be shared as "Anyone with the link").
- **From your computer** — click **Choose file** and pick a PDF.

Some worksheets you'll see have a little **⚠ warning** under them —
that means the worksheet is a colouring activity, not a maths question,
so it probably won't turn into a good new worksheet. Best to pick ones
without the warning.

Click **Next: create worksheets →** when you've added something.

### ② Create

Pick:
- **Source worksheet** — which one to build from (or tick the box to
  use every worksheet in the library at once)
- **Grade** — Kindergarten through Grade 10
- **How should they be built?** — change the setting/context, write
  more questions of the same type, or both
- **How many versions** — how many different new worksheets to make
- **Closing message** — a friendly note at the end. Type a topic and
  click **Suggest** and the AI writes one for you

Click **Create worksheets**. This takes a little while — you'll see a
progress bar if you asked for several at once.

### ③ Review & approve

Every worksheet made shows up here with a coloured note explaining
whether it passed the automatic check:

| What you see | What it means |
|---|---|
| **Checked — looks right** | Passed every check. Ready to approve. |
| **Pictures need redrawing** | The questions were fine, only a picture wasn't — it's already been fixed automatically. |
| **Needs another pass** | Something is genuinely wrong (says exactly what) — best to reject or ask for a change. |
| **Could not finish checking** | The check itself couldn't run (unusual) — look at it carefully yourself before approving. |

For each worksheet you can:
- **Approve** / **Reject**
- **Edit** — change any question's wording or answer by hand
- **Ask for a change** — type what you want changed in plain English
  ("make question 3 easier", "use animals instead of fruit")
- **Preview** — see the actual finished page and download the PDF

Approved worksheets collect in the **Approved** tab at the top, where
you can download them any time.

---

## Every time you come back to work on this

You don't need to redo Part 1 or 2. Just:

```bash
cd SEO-Worksheet-Generator/seo_math_worksheets
python3 -m uvicorn app.main:app --port 8020
```

(add `source .venv/bin/activate` before that line if you set up a venv
earlier) then open `http://127.0.0.1:8020` again.

**Or just double-click `start.command`** in the `seo_math_worksheets`
folder — it does all of the above by itself, including first-time setup.

---

## Getting your team using it, without teaching them any of this

**The design:** every teammate runs their own completely independent
copy of the tool — nobody depends on anybody else's laptop, WiFi, or
uptime. Each person can pick a different K5 category (one takes
Kindergarten Simple Math, another takes Grade 1, and so on) and work
through Library → Create → Review entirely on their own machine. The
one place work comes back together is a **shared Google Drive folder** —
every approved worksheet gets sent there with one click, organised
automatically into a subfolder per category, so different people's work
never collides.

### Step 1 — each person gets their own copy running

Every teammate follows **Parts 1 and 2 of this guide** from the top —
clone the repo, install, get their own free Groq key (or you hand out a
shared OpenAI key — either works identically), then either run the
usual command or just double-click `start.command`.

**If a teammate has Claude Code**, they don't need to read any of that
themselves — see "Running this with Claude Code" below.

### Step 2 — set up the shared Drive folder (done ONCE, by you)

This is a one-time setup for whoever owns the shared folder — not
something every teammate repeats.

1. Go to **[console.cloud.google.com](https://console.cloud.google.com)**
   and create a new project (or use an existing one) — name it anything,
   e.g. `seo-worksheets`
2. In the search bar, find **"Google Drive API"** and click **Enable**
3. In the left menu, go to **IAM & Admin → Service Accounts** →
   **Create Service Account**. Name it anything (e.g. `worksheet-uploader`),
   click through the remaining steps with the defaults, then **Create**
4. Click on the service account you just made → **Keys** tab →
   **Add Key → Create new key → JSON**. A file downloads automatically
5. Rename that downloaded file to exactly `service_account.json` and
   move it into the `seo_math_worksheets` folder (next to `.env`) —
   it's already excluded from GitHub, so it's safe to leave there
6. Open that JSON file in a text editor, find the line that says
   `"client_email"`, and copy the email address next to it (looks like
   `something@your-project.iam.gserviceaccount.com`)
7. In Google Drive, create (or pick) the folder you want everyone's
   approved worksheets to land in. Right-click it → **Share** → paste
   in that email address → set it to **Editor** → Share
8. Copy that folder's **link** (Share → Copy link)
9. Open the tool, go to the **Setup** tab, find **"Shared Drive
   folder"**, paste the link into the box, click **Save**. It takes
   effect immediately — no restart needed, and the pill should change
   to **connected** (as long as `service_account.json` from step 4 is
   already sitting in the `seo_math_worksheets` folder).

Once it's set up on your machine, share `service_account.json` and the
`GOOGLE_DRIVE_FOLDER_ID` value with any teammate who also wants to send
straight to Drive from their own copy — everyone points at the same
folder using the same credentials.

### Step 3 — using it day to day

On the **Approved** tab, every worksheet gets a **Send to Drive**
button, and there's a **Send all approved to Drive →** button at the
top for sending everything at once. That's it — approved worksheets
show up in the shared Drive folder, sorted into a subfolder named after
whichever K5 category they came from.

### If you'd rather have one single shared instance instead

If everyone happens to be on the same office WiFi and you'd prefer one
running copy that everyone opens in their browser (same library, same
approvals, nothing to install for anyone), that's also possible — run
`python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8020` and share
`http://<your machine's IP>:8020` (find it with `ipconfig getifaddr en0`).
The trade-off: it depends on your machine staying on and connected, and
only works for people on the same network. The Drive-folder design above
avoids both of those limits, which is why it's the default recommendation.

---

## Running this with Claude Code — step by step

If a teammate has Claude Code, they can skip almost everything above.
Here's the exact sequence.

**Step 1 — open Claude Code anywhere** (an empty folder is fine — it'll
create its own).

**Step 2 — paste this in:**

> Clone https://github.com/madhukarv-prescience/SEO-Worksheet-Generator.git,
> install `seo_math_worksheets`'s dependencies, help me get a free Groq
> API key from console.groq.com/keys and put it in
> `seo_math_worksheets/.env`, then start the tool and open it in my
> browser.

Claude Code will clone the repo, install everything, walk them through
getting a key, start the server, and open `http://127.0.0.1:8020` — the
same sequence used to build this whole project in the first place.

**Step 3 — if the team is using a shared Drive folder** (see below),
paste this too:

> Paste this Drive folder link into the Setup tab's "Shared Drive
> folder" box and save it: `<the link Madhukar gave you>`

If the credential file (`service_account.json`) hasn't been shared with
them separately, tell Claude Code that too — it'll explain where to put
it.

**Step 4 — from here on, just describe what you want in plain English.**
Some real examples:
- *"Fetch some Grade 2 worksheets"*
- *"Show me what's in the Kindergarten Simple Math folder before I add any"*
- *"Generate 3 versions of this worksheet at Grade 3, core difficulty"*
- *"Send my approved worksheets to the shared Drive folder"*
- *"Why did this worksheet fail validation?"*

Claude Code reads this same README and the code itself, so it always
knows the current state of the tool — no separate instructions to keep
in sync.

---

## Everything you can customize

A complete list, so nothing is left undocumented.

### From inside the app (no file editing, takes effect immediately)

| Setting | Where |
|---|---|
| Which AI provider is active | Setup tab (auto-detected from whichever key is in `.env`) |
| Shared Drive folder | Setup tab — paste a link, click Save |
| Canva connection | Setup tab — "Connect Canva" (only relevant if pursuing Canva — see its own section) |
| Grade (Kindergarten–10), difficulty, build mode | Create screen, per generation |
| What should vary (context/numbers/representation/etc.) | Create screen, tick any combination |
| How many versions | Create screen |
| Questions per worksheet | Create screen (blank = grade's default) |
| Closing message + what it should invite the child to do | Create screen — type a topic and pick a goal, or write your own |
| Worksheet template (visual style) | Library → upload a PDF/DOCX, tag with a grade; pick it on Create |
| Use every source at once vs. one at a time | Create screen checkbox |

### From `.env` (requires editing the file + restarting)

| Variable | What it controls | Default |
|---|---|---|
| `GROQ_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | Question-writing provider (first one present wins) | none |
| `LLM_PROVIDER` | Force a specific provider instead of auto-detect | `auto` |
| `GROQ_MODEL` / `ANTHROPIC_MODEL` / `OPENAI_MODEL` | Which model per provider | see `.env.example` |
| `GROQ_MAX_TOKENS` | Response length budget for Groq | `5200` |
| `OPENAI_IMAGE_MODEL` | Model for decorative/photo-real images | `gpt-image-1` |
| `CANVA_CLIENT_ID` / `_SECRET` / `_BRAND_TEMPLATE_ID` | Canva integration identity (needs Canva Enterprise — see its section) | none |
| `CANVA_REDIRECT_URI` | Where Canva sends the browser back after approval | `http://127.0.0.1:8020/api/canva/callback` |
| `APP_SECRET_KEY` | Encrypts the Canva connection's tokens at rest | auto-generated if blank |
| `GOOGLE_DRIVE_FOLDER_ID` | Fallback shared folder if nothing's saved in the Setup tab | none |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Path to the Drive credential file | `service_account.json` in the same folder |
| `SEO_STUDIO_DATA` | Where uploads/exports/the database live | `data/` in the same folder |

### For a developer changing behaviour in code

| What | Where | Default |
|---|---|---|
| How many sources a single bulk run can touch | `app/jobs.py` → `MAX_SOURCES_PER_RUN` | 25 |
| Pause between sources in a bulk run (rate-limit pacing) | `app/generate.py` → `BULK_PAUSE_SECONDS` | 4 seconds |
| The instructional design framework itself (grade skills, difficulty mix, variation dimensions) | `app/framework.py` | — |
| What counts as "no real question" for the activity-sheet warning | `app/ingest.py` → `looks_like_questions()` | — |
| The validation gate's checks | `app/validate.py` | — |

---

## If something goes wrong

| What you see | What to do |
|---|---|
| `command not found: python3` | Install Python from python.org/downloads |
| `command not found: git` | Install Git from git-scm.com/downloads |
| `externally-managed-environment` | Use the `.venv` steps in section 2.1 |
| The **Setup** tab shows nothing "in use now" | Your key in `.env` isn't saved correctly — redo section 2.3, check for stray spaces |
| A worksheet says "the daily allowance is used up" | The free Groq plan has a small daily limit. Wait — it says exactly how long — or come back tomorrow |
| A worksheet keeps saying "needs another pass" | This is the checker working correctly — read the specific reason it gives and either fix it by hand or reject it |
| The page looks broken/unstyled | Hard-refresh your browser (`Cmd+Shift+R`) |
| Nothing happens when you visit `127.0.0.1:8020` | Check the Terminal window is still open and didn't show an error |

Still stuck? The person who owns this project is
**Madhukar V** (`madhukar.v@expinfi.com`).

---

## For anyone continuing the code itself

See **[ARCHITECTURE.md](ARCHITECTURE.md)** for how the system fits
together, and **[seo_math_worksheets/README.md](seo_math_worksheets/README.md)**
for the technical detail: the validation gate, the instructional design
framework behind question generation, and the current status of the
optional OpenAI/Canva integrations.

## This is not the BLC project

BLC Worksheets is a separate project with its own content, guidelines,
and credentials. Nothing here imports from it, shares its `.env`, or
reuses its code — keep it that way.
