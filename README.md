# PhilSys National ID — Queuing System (Python edition)

A 4-panel office queuing display (kiosk), a self-service "take a number" screen
for citizens, and a staff console to call the next number — all backed
directly by a Google Sheet and a Google Drive folder (AVP videos), via a
**Python (Flask) backend using a Google Service Account**.

This replaces the old Node.js + Google Apps Script "bridge" version: no more
pasting code into Apps Script, no more redeploying a Web App every time you
change something. One Python app, one place to deploy, one set of credentials.

```
Citizen tablet (index.html) ─┐
Kiosk TV (kiosk.html)      ──┼─► Flask app (app.py) ─► Google Sheets API + Drive API
Staff console (admin.html) ──┘        (service account)
```

## What auto-detect / auto-fill means here

Every time the app starts, `google_client.ensure_headers()` checks four tabs
in your Sheet: `Requirements`, `MobileRegistrationSchedule`,
`RegistrationLog`, and `QueueState`. For each one it will:

- **create the tab** if it doesn't exist yet
- **write the header row** if it's missing, blank, or doesn't match

So you can hand it a blank spreadsheet and it will build the tabs and headers
itself on first boot — you only need to fill in the actual data rows
(requirements list, mobile registration dates). Column **order** in each tab
also doesn't matter when reading data back — the app matches columns by
header name, not position.

---

## 1. Google Cloud: create a Service Account

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and
   create a new project (or reuse one).
2. **APIs & Services → Library** — enable:
   - **Google Sheets API**
   - **Google Drive API**
3. **APIs & Services → Credentials → Create Credentials → Service account.**
   Give it any name (e.g. `nid-queuing-bot`). No roles/permissions needed at
   the project level — access is granted by sharing the Sheet/Drive folder
   directly with it (next step).
4. Open the new service account → **Keys → Add Key → Create new key → JSON**.
   This downloads a `.json` file — **keep it private**, never commit it to
   git.
5. Open that JSON file and copy the `client_email` value
   (looks like `nid-queuing-bot@your-project.iam.gserviceaccount.com`).

## 2. Set up the Google Sheet

1. Create a Google Sheet (any name, e.g. "NID Queuing").
2. Click **Share**, paste in the service account's `client_email` from step
   1.5, give it **Editor** access, and share.
3. From the Sheet's URL — `https://docs.google.com/spreadsheets/d/THIS_PART/edit`
   — copy the ID. You'll set this as `GOOGLE_SHEET_ID`.
4. You don't need to create any tabs by hand — the app does that on first
   boot (see "auto-detect / auto-fill" above). But you do still need to type
   in your actual **data rows** once the tabs exist:

   **`Requirements`**

   | Category  | Requirement                                  | Order |
   |-----------|-----------------------------------------------|-------|
   | Primary   | PSA Birth Certificate (original + photocopy)   | 1     |
   | Secondary | Valid government-issued ID                     | 2     |
   | Other     | Barangay Certificate of Residency               | 3     |

   `Category` must be `Primary`, `Secondary`, or `Other`. The first `Primary`
   row and first `Secondary` row are the two blinking chips; every row shows
   in the scrolling list below.

   **`MobileRegistrationSchedule`**

   | Date       | Day      | Venue                        | TimeStart | TimeEnd | Slots | Notes |
   |------------|----------|-------------------------------|-----------|---------|-------|-------|
   | 2026-07-20 | Monday   | Barangay San Isidro Covered Court | 8:00 AM | 4:00 PM | 200 | |

   Use `YYYY-MM-DD` text or real date cells.

   **`RegistrationLog`** and **`QueueState`** — leave these empty; the app
   writes to them automatically (ticket log and the day's queue counters).

## 3. Share the Drive folder

1. Create/choose a Drive folder containing your AVP `.mp4` videos.
2. Share it with the same service account `client_email`, with **Editor**
   (Content manager) access — needed so staff can upload, rename, and
   delete videos from `/admin`, not just view them.
3. From the folder's URL — `https://drive.google.com/drive/folders/THIS_PART`
   — copy the ID. You'll set this as `DRIVE_FOLDER_ID`.
4. The kiosk lists and rotates through every video file it finds in that
   folder automatically — upload a new one from `/admin` (or drop it into
   Drive by hand) any time, no redeploy needed.

> **Video playback note:** Drive's embedded player can't tell the kiosk page
> exactly when a clip ends (cross-origin iframe), so the kiosk rotates on a
> fixed 90-second timer instead (`VIDEO_ROTATE_MS` in `public/js/kiosk.js`).
> For frame-accurate playback, host MP4s as static files instead of via Drive.

## Staff console: managing AVP videos

The third panel on `/admin` manages the videos the kiosk rotates through —
upload a new one, rename it, or delete it, no more dropping files into Drive
by hand.

Uploads go **directly from the browser to Google Drive**, not through this
server. Routing a whole video through a free-tier Render instance first
(browser → Render → Drive) was the main reason uploads used to feel slow —
Render's free plan has limited CPU/bandwidth and the file effectively had to
travel the network twice. Now only a small JSON handshake touches Render;
the video bytes go straight to Drive's own infrastructure, using Drive's
[resumable upload protocol](https://developers.google.com/drive/api/guides/manage-uploads#resumable),
which supports cross-origin (CORS) PUT requests from a browser for exactly
this purpose.

| Method | Route                                | Purpose                                          |
|--------|----------------------------------------|-----------------------------------------------------|
| GET    | `/api/admin/videos?key=...`            | list videos (size, upload date)                     |
| POST   | `/api/admin/videos/init`               | open a Drive resumable-upload session, return its URL |
| POST   | `/api/admin/videos/confirm`            | tell the server the upload finished (refreshes cache) |
| POST   | `/api/admin/videos/<id>/rename`        | rename a video                                       |
| POST   | `/api/admin/videos/<id>/delete`        | delete a video from Drive                            |

The upload flow from `/admin`:

1. Browser calls `/api/admin/videos/init` with the passcode + filename/type/size.
2. The server asks Drive to open a resumable session (one small server-to-Drive
   request) and hands the session URL back.
3. The browser `PUT`s the file straight to that Drive URL — this is the part
   that's actually slow for large videos, and it's now bottlenecked only by
   your own upload bandwidth and Drive, not by Render.
4. The browser calls `/api/admin/videos/confirm`, which clears the
   `/api/data` cache so the kiosk and citizen tablet pick up the new video on
   their next poll instead of waiting out the cache TTL.

This is why the service account needs "Editor" (Content manager) access to
the Drive folder, not just Viewer — double-check that in Drive's Share
dialog if uploads start failing after you update from an older version of
this app.

## Staff console: managing Requirements & the mobile schedule

`/admin` now has two extra panels below the queue call controls, both gated
behind the same passcode:

- **Requirements list** — add or delete rows in the `Requirements` tab
  (Category, text, Order) without opening the Sheet.
- **Mobile registration schedule** — add or delete rows in the
  `MobileRegistrationSchedule` tab (Date, Day, Venue, TimeStart, TimeEnd,
  Slots, Notes).

Both panels talk to new JSON endpoints that read/write the Sheet directly:

| Method | Route                                   | Purpose                        |
|--------|------------------------------------------|---------------------------------|
| GET    | `/api/admin/requirements?key=...`         | list requirements (with row #) |
| POST   | `/api/admin/requirements`                 | add a requirement               |
| POST   | `/api/admin/requirements/<row>/delete`    | delete a requirement            |
| GET    | `/api/admin/schedule?key=...`             | list schedule rows (with row #) |
| POST   | `/api/admin/schedule`                     | add a schedule row              |
| POST   | `/api/admin/schedule/<row>/delete`        | delete a schedule row           |

Every row is returned with its live sheet row number (`row`), and deletes
target that exact row via the Sheets API's `deleteDimension` request, which
needs each tab's numeric `sheetId` (not its name). That numeric id is warmed
into an in-memory cache at startup (inside `ensure_headers()`) and reused for
every delete, so deleting a row never costs an extra metadata round-trip —
only a fresh lookup if a tab was created by hand after boot. Any add/delete
also invalidates the `/api/data` cache so the kiosk and citizen tablet pick
up the change on their next poll.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: GOOGLE_SHEET_ID, DRIVE_FOLDER_ID, ADMIN_KEY,
# and GOOGLE_SERVICE_ACCOUNT_FILE=path/to/your-downloaded-key.json
export $(grep -v '^#' .env | xargs)   # load .env into your shell

python app.py
```

Visit `http://localhost:3000/`, `/kiosk`, and `/admin`. Watch the terminal on
first run — you should see:

```
[headers] auto-filled header row for 'Requirements': [...]
[headers] auto-filled header row for 'MobileRegistrationSchedule': [...]
[headers] auto-filled header row for 'RegistrationLog': [...]
[headers] auto-filled header row for 'QueueState': [...]
[startup] Sheet headers verified/auto-filled OK.
```

## Push this repo to GitHub

```bash
git init
git add .
git commit -m "Initial commit: NID queuing system (Python/Flask)"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

Your service account JSON key is **not** in this repo (it's git-ignored) —
that's intentional, it goes into Render as an environment variable instead.

## Deploy to Render

1. On [Render](https://render.com): **New → Web Service**, connect this
   GitHub repo.
2. Render should auto-detect `render.yaml` (Python runtime, build/start
   commands). If it asks manually instead:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn app:app --bind 0.0.0.0:$PORT`
3. Under **Environment**, add:
   - `GOOGLE_SHEET_ID` — the Spreadsheet ID from step 2.3 above (the long
     string in the Sheet's URL between `/d/` and `/edit`)
   - `DRIVE_FOLDER_ID` — the Drive folder ID from step 3.3 above (the long
     string at the end of the folder's URL)
   - `ADMIN_KEY` — your staff passcode, used by `/admin` and every
     `/api/admin/*` route
   - `GOOGLE_SERVICE_ACCOUNT_JSON` — open your downloaded JSON key file,
     copy its **entire contents**, and paste it in as the value (Render's
     environment variable editor accepts multi-line values fine)
4. Deploy. Render gives you a URL like
   `https://nid-queuing-system.onrender.com`.
   - Office TV → that URL + `/kiosk`
   - Citizen tablet → the bare URL (`/`)
   - Staff device → `/admin`
5. Sanity-check the deploy:
   - Open `/healthz` — should return `{"ok": true}`.
   - Open `/admin`, enter the passcode, confirm both the queue counters and
     the new Requirements/Schedule panels load without errors.
   - Add a test requirement or schedule row from `/admin`, then reload `/`
     or `/kiosk` and confirm it shows up (allow a few seconds for the
     `/api/data` cache to expire).
   - Delete the test row you just added.

> Free Render web services spin down after inactivity and take ~30–60s to
> wake back up. For an always-on office display, use a paid instance type or
> a keep-alive ping.

## Daily reset

Ticket sequences (`R-001`, `V-001`, …) and today's "now serving" numbers live
in the `QueueState` tab (one data row, auto-managed). Every time anyone
requests a ticket, calls next/prev, or the kiosk polls, the app checks
today's date in Asia/Manila time — if it's a new day, both sequences reset to
`000` automatically. Staff can also force a reset any time from `/admin`.

## Branding

The logo (`public/assets/logo.png`) is the PhilSys National ID mark used
as-is in the header of every screen; the favicons are cropped from it.

## Project structure

```
app.py              Flask app: routes + static file serving
google_client.py     All Sheets/Drive access, header auto-detect/fill, queue logic
requirements.txt     Python dependencies
render.yaml          Render Blueprint (Python web service)
.env.example         Local dev environment variable template
public/              Frontend: kiosk.html, index.html, admin.html, css/, js/, assets/
```
