"""
Google Sheets + Drive access layer for the NID Queuing System.

Auth: a single Service Account (no OAuth/login flow, no Apps Script bridge).
The service account must be:
  - given "Editor" access to the Google Sheet (share the sheet with its
    client_email, found inside your service account JSON key)
  - given at least "Viewer" access to the Drive folder holding the AVP videos

Header auto-detect / auto-fill:
  ensure_headers() runs once at startup. For each required tab it will:
    - create the tab if it doesn't exist yet
    - write/repair the header row if it's missing, blank, or doesn't match
  So you never have to manually type header rows into a fresh sheet again.
"""

import os
import json
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

TIMEZONE = ZoneInfo("Asia/Manila")

SHEET_REQUIREMENTS = "Requirements"
SHEET_SCHEDULE = "MobileRegistrationSchedule"
SHEET_LOG = "RegistrationLog"
SHEET_STATE = "QueueState"

# The single source of truth for what every tab's header row should look like.
# ensure_headers() uses this to auto-detect and auto-fill each tab.
HEADERS = {
    SHEET_REQUIREMENTS: ["Category", "Requirement", "Order"],
    SHEET_SCHEDULE: ["Date", "Day", "Venue", "TimeStart", "TimeEnd", "Slots", "Notes"],
    SHEET_LOG: ["Timestamp", "Line", "Number", "Name"],
    SHEET_STATE: ["Date", "RegTicket", "RegServing", "VerTicket", "VerServing"],
}

SPREADSHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID", "")

_lock = threading.Lock()
_sheets_service = None
_drive_service = None
_creds = None

# tab title -> numeric sheetId (grid id), needed for row-delete batchUpdate
# requests. Populated at startup by ensure_headers() and lazily refreshed by
# _get_sheet_numeric_id() if a tab is missing from it (e.g. hand-created
# after boot).
_sheet_id_cache = {}


def _load_credentials():
    global _creds
    if _creds:
        return _creds
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw:
        info = json.loads(raw)
        _creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        return _creds
    file_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "service-account.json")
    if os.path.exists(file_path):
        _creds = service_account.Credentials.from_service_account_file(file_path, scopes=SCOPES)
        return _creds
    raise RuntimeError(
        "No Google credentials found. Set GOOGLE_SERVICE_ACCOUNT_JSON (paste the full "
        "service account key JSON as one env var) or GOOGLE_SERVICE_ACCOUNT_FILE "
        "(path to a key file, for local dev only)."
    )


def _sheets():
    global _sheets_service
    if _sheets_service is None:
        _sheets_service = build("sheets", "v4", credentials=_load_credentials(), cache_discovery=False)
    return _sheets_service


def _drive():
    global _drive_service
    if _drive_service is None:
        _drive_service = build("drive", "v3", credentials=_load_credentials(), cache_discovery=False)
    return _drive_service


def _require_sheet_id():
    if not SPREADSHEET_ID:
        raise RuntimeError("GOOGLE_SHEET_ID is not set.")


# --------------------------- Header auto-detect / auto-fill ---------------------------

def ensure_headers():
    """Create any missing tab and repair any missing/incorrect header row."""
    _require_sheet_id()
    meta = _sheets().spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    existing_titles = [s["properties"]["title"] for s in meta.get("sheets", [])]

    # warm the sheetId cache while we already have the metadata in hand
    for s in meta.get("sheets", []):
        props = s["properties"]
        _sheet_id_cache[props["title"]] = props["sheetId"]

    add_requests = [
        {"addSheet": {"properties": {"title": name}}}
        for name in HEADERS
        if name not in existing_titles
    ]
    if add_requests:
        resp = _sheets().spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID, body={"requests": add_requests}
        ).execute()
        for reply in resp.get("replies", []):
            props = reply.get("addSheet", {}).get("properties", {})
            if props:
                _sheet_id_cache[props["title"]] = props["sheetId"]

    for name, header in HEADERS.items():
        result = (
            _sheets()
            .spreadsheets()
            .values()
            .get(spreadsheetId=SPREADSHEET_ID, range=f"{name}!1:1")
            .execute()
        )
        current_row = [str(c).strip() for c in result.get("values", [[]])[0]] if result.get("values") else []
        if current_row != header:
            _sheets().spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{name}!A1",
                valueInputOption="RAW",
                body={"values": [header]},
            ).execute()
            print(f"[headers] auto-filled header row for '{name}': {header}")


def _get_sheet_numeric_id(tab_name):
    """Returns the numeric sheetId (grid id) for a tab, using the cache
    warmed by ensure_headers(). Falls back to a fresh metadata fetch if the
    tab isn't cached yet (e.g. created by hand after boot)."""
    if tab_name in _sheet_id_cache:
        return _sheet_id_cache[tab_name]
    meta = _sheets().spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    for s in meta.get("sheets", []):
        props = s["properties"]
        _sheet_id_cache[props["title"]] = props["sheetId"]
    if tab_name not in _sheet_id_cache:
        raise RuntimeError(f"Sheet tab '{tab_name}' was not found in the spreadsheet.")
    return _sheet_id_cache[tab_name]


# --------------------------- Generic sheet reading ---------------------------

def _sheet_to_objects(name, with_row=False):
    """Reads a tab and maps rows to dicts keyed by whatever is in the header
    row (auto-detected), so column order in the sheet doesn't matter.

    If with_row=True, each dict also gets a "_row" key holding the row's
    1-indexed position in the actual sheet (row 1 is the header, so the
    first data row is "_row": 2) — this is what row-delete calls need."""
    result = (
        _sheets()
        .spreadsheets()
        .values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{name}!A1:Z")
        .execute()
    )
    values = result.get("values", [])
    if len(values) < 2:
        return []
    headers = [str(h).strip() for h in values[0]]
    rows = []
    for sheet_row, row in enumerate(values[1:], start=2):
        obj = {headers[i]: (row[i] if i < len(row) else "") for i in range(len(headers))}
        if with_row:
            obj["_row"] = sheet_row
        rows.append(obj)
    return rows


def _add_row(tab_name, values_dict):
    """Appends one row to a tab, mapping values_dict onto that tab's known
    header order (HEADERS[tab_name]) so column position is always correct
    regardless of dict key order."""
    header = HEADERS[tab_name]
    row = [str(values_dict.get(h, "") if values_dict.get(h) is not None else "") for h in header]
    _sheets().spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{tab_name}!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()


def _delete_row(tab_name, row_number):
    """Deletes one row from a tab. row_number is 1-indexed as it appears in
    the actual sheet (header is row 1, so the first data row is 2) — the
    same numbering _sheet_to_objects(..., with_row=True) hands back."""
    if row_number < 2:
        raise ValueError("Refusing to delete the header row.")
    sheet_id = _get_sheet_numeric_id(tab_name)
    _sheets().spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={
            "requests": [
                {
                    "deleteDimension": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "ROWS",
                            "startIndex": row_number - 1,  # 0-indexed, inclusive
                            "endIndex": row_number,  # 0-indexed, exclusive
                        }
                    }
                }
            ]
        },
    ).execute()


def read_requirements():
    rows = _sheet_to_objects(SHEET_REQUIREMENTS)
    out = []
    for r in rows:
        text = str(r.get("Requirement", "")).strip()
        if not text:
            continue
        try:
            order = float(r.get("Order", 0) or 0)
        except (TypeError, ValueError):
            order = 0
        out.append(
            {
                "category": str(r.get("Category", "")).strip(),
                "text": text,
                "order": order,
            }
        )
    out.sort(key=lambda r: r["order"])
    return out


def read_schedule():
    rows = _sheet_to_objects(SHEET_SCHEDULE)
    out = []
    for r in rows:
        date = str(r.get("Date", "")).strip()
        venue = str(r.get("Venue", "")).strip()
        if not (date or venue):
            continue
        out.append(
            {
                "date": date,
                "day": str(r.get("Day", "")).strip(),
                "venue": venue,
                "timeStart": str(r.get("TimeStart", "")).strip(),
                "timeEnd": str(r.get("TimeEnd", "")).strip(),
                "slots": str(r.get("Slots", "")).strip(),
                "notes": str(r.get("Notes", "")).strip(),
            }
        )
    out.sort(key=lambda r: r["date"])
    return out


# --------------------------- Admin CRUD: Requirements ---------------------------

def list_requirements_admin():
    """Same shape as read_requirements() but includes each row's sheet row
    number (as "row") and is not order-filtered/blank-filtered, so staff can
    see and delete exactly what's in the sheet."""
    rows = _sheet_to_objects(SHEET_REQUIREMENTS, with_row=True)
    out = []
    for r in rows:
        category = str(r.get("Category", "")).strip()
        text = str(r.get("Requirement", "")).strip()
        if not (category or text):
            continue
        try:
            order = float(r.get("Order", 0) or 0)
        except (TypeError, ValueError):
            order = 0
        out.append({"row": r["_row"], "category": category, "text": text, "order": order})
    out.sort(key=lambda r: r["order"])
    return out


def add_requirement(category, text, order):
    with _lock:
        _add_row(SHEET_REQUIREMENTS, {"Category": category, "Requirement": text, "Order": order})


def delete_requirement(row):
    with _lock:
        _delete_row(SHEET_REQUIREMENTS, row)


# --------------------------- Admin CRUD: Mobile Registration Schedule ---------------------------

def list_schedule_admin():
    rows = _sheet_to_objects(SHEET_SCHEDULE, with_row=True)
    out = []
    for r in rows:
        date = str(r.get("Date", "")).strip()
        venue = str(r.get("Venue", "")).strip()
        if not (date or venue):
            continue
        out.append(
            {
                "row": r["_row"],
                "date": date,
                "day": str(r.get("Day", "")).strip(),
                "venue": venue,
                "timeStart": str(r.get("TimeStart", "")).strip(),
                "timeEnd": str(r.get("TimeEnd", "")).strip(),
                "slots": str(r.get("Slots", "")).strip(),
                "notes": str(r.get("Notes", "")).strip(),
            }
        )
    out.sort(key=lambda r: r["date"])
    return out


def add_schedule(date, day, venue, time_start, time_end, slots, notes):
    with _lock:
        _add_row(
            SHEET_SCHEDULE,
            {
                "Date": date,
                "Day": day,
                "Venue": venue,
                "TimeStart": time_start,
                "TimeEnd": time_end,
                "Slots": slots,
                "Notes": notes,
            },
        )


def delete_schedule(row):
    with _lock:
        _delete_row(SHEET_SCHEDULE, row)


def _append_log(line, number, name):
    timestamp = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
    _sheets().spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_LOG}!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [[timestamp, line, number, name or ""]]},
    ).execute()


# --------------------------- Drive videos ---------------------------

def list_videos():
    if not DRIVE_FOLDER_ID:
        return []
    query = f"'{DRIVE_FOLDER_ID}' in parents and mimeType contains 'video' and trashed = false"
    resp = (
        _drive()
        .files()
        .list(q=query, fields="files(id,name,mimeType)", pageSize=100, supportsAllDrives=True,
              includeItemsFromAllDrives=True)
        .execute()
    )
    return [
        {
            "id": f["id"],
            "name": f["name"],
            "embedUrl": f"https://drive.google.com/file/d/{f['id']}/preview",
        }
        for f in resp.get("files", [])
    ]


# --------------------------- Queue state (lives in the QueueState tab) ---------------------------

def _today_str():
    return datetime.now(TIMEZONE).strftime("%Y-%m-%d")


def _read_state_row():
    result = (
        _sheets()
        .spreadsheets()
        .values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_STATE}!A2:E2")
        .execute()
    )
    values = result.get("values", [])
    row = values[0] if values else []

    def cell(i, default="0"):
        return row[i] if len(row) > i and str(row[i]).strip() != "" else default

    return {
        "date": cell(0, ""),
        "reg_ticket": int(cell(1)),
        "reg_serving": int(cell(2)),
        "ver_ticket": int(cell(3)),
        "ver_serving": int(cell(4)),
    }


def _write_state_row(state):
    _sheets().spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_STATE}!A2",
        valueInputOption="RAW",
        body={
            "values": [
                [
                    state["date"],
                    state["reg_ticket"],
                    state["reg_serving"],
                    state["ver_ticket"],
                    state["ver_serving"],
                ]
            ]
        },
    ).execute()


def _fresh_state():
    return {"date": _today_str(), "reg_ticket": 0, "reg_serving": 0, "ver_ticket": 0, "ver_serving": 0}


def _state_or_reset():
    state = _read_state_row()
    if state["date"] != _today_str():
        state = _fresh_state()
    return state


def get_state():
    with _lock:
        raw = _read_state_row()
        if raw["date"] != _today_str():
            state = _fresh_state()
            _write_state_row(state)
            return state
        return raw


def reset_state():
    with _lock:
        state = _fresh_state()
        _write_state_row(state)
        return state


def issue_ticket(line, name):
    with _lock:
        state = _state_or_reset()
        key = "ver_ticket" if line == "verification" else "reg_ticket"
        state[key] += 1
        prefix = "V" if line == "verification" else "R"
        number = f"{prefix}-{state[key]:03d}"
        _write_state_row(state)
        _append_log(line, number, name)
        return {"line": line, "ticket": state[key], "number": number}, state


def advance_serving(line, delta):
    with _lock:
        state = _state_or_reset()
        ticket_key = "ver_ticket" if line == "verification" else "reg_ticket"
        serving_key = "ver_serving" if line == "verification" else "reg_serving"
        ticket_max = state[ticket_key]
        nxt = state[serving_key] + delta
        nxt = max(0, min(nxt, ticket_max))
        state[serving_key] = nxt
        _write_state_row(state)
        return state


def state_to_public(state):
    return {
        "date": state["date"],
        "registration": {"ticket": state["reg_ticket"], "serving": state["reg_serving"]},
        "verification": {"ticket": state["ver_ticket"], "serving": state["ver_serving"]},
    }


def get_state_public():
    return state_to_public(get_state())
