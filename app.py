"""
NID Queuing System — Python (Flask) backend.

Talks directly to Google Sheets + Google Drive using a Service Account.
Serves the same static frontend (public/) and the same JSON API shape as
the original Node/Apps-Script version, so nothing in public/js needs to
change.
"""

import os
import time
import traceback

from flask import Flask, jsonify, request, send_from_directory

import google_client as gc

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_BYTES", 512 * 1024 * 1024))  # 512MB default — video bytes stream through this server on their way to Drive (see /api/admin/videos/upload)

ADMIN_KEY = os.environ.get("ADMIN_KEY", "")
PUBLIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public")

# Auto-detect and fill in any missing/incorrect sheet tabs and header rows
# the moment the app boots (works under `python app.py` and under gunicorn).
try:
    gc.ensure_headers()
    print("[startup] Sheet headers verified/auto-filled OK.")
except Exception as exc:  # noqa: BLE001
    print(f"[startup] WARNING: could not verify/auto-fill sheet headers: {exc}")

# -------- tiny in-memory cache so the kiosk polling loop doesn't hammer Sheets --------
_cache = {"data": None, "ts": 0.0}
CACHE_SECONDS = 4


def _invalidate_cache():
    _cache["data"] = None
    _cache["ts"] = 0.0


def _build_data():
    return {
        "ok": True,
        "requirements": gc.read_requirements(),
        "schedule": gc.read_schedule(),
        "videos": gc.list_videos(),
        "queue": gc.get_state_public(),
    }


# -------------------------------- API routes --------------------------------

@app.get("/api/data")
def api_data():
    now = time.time()
    if _cache["data"] is not None and now - _cache["ts"] < CACHE_SECONDS:
        return jsonify(_cache["data"])
    try:
        data = _build_data()
        _cache["data"], _cache["ts"] = data, now
        return jsonify(data)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.get("/api/queue")
def api_queue():
    try:
        return jsonify({"ok": True, "queue": gc.get_state_public()})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/ticket")
def api_ticket():
    body = request.get_json(silent=True) or {}
    line = str(body.get("line") or "").lower()
    if line not in ("registration", "verification"):
        return jsonify({"ok": False, "error": "line must be registration or verification"}), 400
    try:
        result, state = gc.issue_ticket(line, body.get("name", ""))
        _invalidate_cache()
        return jsonify({"ok": True, **result, "queue": gc.state_to_public(state)})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/admin/<action>")
def api_admin(action):
    if action not in ("next", "prev", "reset", "verify"):
        return jsonify({"ok": False, "error": "Unknown admin action"}), 404

    body = request.get_json(silent=True) or {}
    key = body.get("key")
    if not key or (ADMIN_KEY and key != ADMIN_KEY):
        return jsonify({"ok": False, "error": "Invalid passcode"}), 401

    if action == "verify":
        return jsonify({"ok": True})

    try:
        if action == "reset":
            state = gc.reset_state()
        else:
            line = str(body.get("line") or "").lower()
            line = "verification" if line.startswith("ver") else "registration"
            delta = 1 if action == "next" else -1
            state = gc.advance_serving(line, delta)
        _invalidate_cache()
        return jsonify({"ok": True, "queue": gc.state_to_public(state)})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 502


def _valid_admin_key(supplied):
    return bool(supplied) and (not ADMIN_KEY or supplied == ADMIN_KEY)


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


# -------------------------------- Admin: Requirements CRUD --------------------------------

@app.get("/api/admin/requirements")
def api_admin_requirements_list():
    if not _valid_admin_key(request.args.get("key")):
        return jsonify({"ok": False, "error": "Invalid passcode"}), 401
    try:
        return jsonify({"ok": True, "items": gc.list_requirements_admin()})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/admin/requirements")
def api_admin_requirements_add():
    body = request.get_json(silent=True) or {}
    if not _valid_admin_key(body.get("key")):
        return jsonify({"ok": False, "error": "Invalid passcode"}), 401
    text = str(body.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "Requirement text is required"}), 400
    category = str(body.get("category") or "").strip()
    try:
        order = float(body.get("order") or 0)
    except (TypeError, ValueError):
        order = 0
    try:
        gc.add_requirement(category, text, order)
        _invalidate_cache()
        return jsonify({"ok": True, "items": gc.list_requirements_admin()})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/admin/requirements/<int:row>/delete")
def api_admin_requirements_delete(row):
    body = request.get_json(silent=True) or {}
    if not _valid_admin_key(body.get("key")):
        return jsonify({"ok": False, "error": "Invalid passcode"}), 401
    try:
        gc.delete_requirement(row)
        _invalidate_cache()
        return jsonify({"ok": True, "items": gc.list_requirements_admin()})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 502


# -------------------------------- Admin: Mobile Registration Schedule CRUD --------------------------------

@app.get("/api/admin/schedule")
def api_admin_schedule_list():
    if not _valid_admin_key(request.args.get("key")):
        return jsonify({"ok": False, "error": "Invalid passcode"}), 401
    try:
        return jsonify({"ok": True, "items": gc.list_schedule_admin()})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/admin/schedule")
def api_admin_schedule_add():
    body = request.get_json(silent=True) or {}
    if not _valid_admin_key(body.get("key")):
        return jsonify({"ok": False, "error": "Invalid passcode"}), 401
    date = str(body.get("date") or "").strip()
    venue = str(body.get("venue") or "").strip()
    if not (date and venue):
        return jsonify({"ok": False, "error": "Date and venue are required"}), 400
    try:
        gc.add_schedule(
            date,
            str(body.get("day") or "").strip(),
            venue,
            str(body.get("timeStart") or "").strip(),
            str(body.get("timeEnd") or "").strip(),
            str(body.get("slots") or "").strip(),
            str(body.get("notes") or "").strip(),
        )
        _invalidate_cache()
        return jsonify({"ok": True, "items": gc.list_schedule_admin()})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/admin/schedule/<int:row>/delete")
def api_admin_schedule_delete(row):
    body = request.get_json(silent=True) or {}
    if not _valid_admin_key(body.get("key")):
        return jsonify({"ok": False, "error": "Invalid passcode"}), 401
    try:
        gc.delete_schedule(row)
        _invalidate_cache()
        return jsonify({"ok": True, "items": gc.list_schedule_admin()})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 502


# -------------------------------- Admin: AVP videos (Drive) CRUD --------------------------------

@app.get("/api/admin/videos")
def api_admin_videos_list():
    if not _valid_admin_key(request.args.get("key")):
        return jsonify({"ok": False, "error": "Invalid passcode"}), 401
    try:
        return jsonify({"ok": True, "items": gc.list_videos_admin()})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.put("/api/admin/videos/upload")
def api_admin_videos_upload():
    # The video's raw bytes are the request body (a plain PUT, not
    # multipart) — key/filename/mimetype/size travel as query params since
    # there's no JSON body to carry them. This server streams the body
    # straight through to Drive as it arrives (see
    # google_client.upload_video_stream for why it can't go direct-to-Drive
    # from the browser instead).
    if not _valid_admin_key(request.args.get("key")):
        return jsonify({"ok": False, "error": "Invalid passcode"}), 401
    filename = str(request.args.get("filename") or "").strip()
    if not filename:
        return jsonify({"ok": False, "error": "filename is required"}), 400
    try:
        gc.upload_video_stream(
            request.stream,
            filename,
            request.args.get("mimetype"),
            request.args.get("size"),
        )
        _invalidate_cache()
        return jsonify({"ok": True, "items": gc.list_videos_admin()})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        print(f"[upload] route error: {exc!r}", flush=True)
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/admin/videos/<file_id>/rename")
def api_admin_videos_rename(file_id):
    body = request.get_json(silent=True) or {}
    if not _valid_admin_key(body.get("key")):
        return jsonify({"ok": False, "error": "Invalid passcode"}), 401
    name = str(body.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Name cannot be empty"}), 400
    try:
        gc.rename_video(file_id, name)
        _invalidate_cache()
        return jsonify({"ok": True, "items": gc.list_videos_admin()})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/admin/videos/<file_id>/delete")
def api_admin_videos_delete(file_id):
    body = request.get_json(silent=True) or {}
    if not _valid_admin_key(body.get("key")):
        return jsonify({"ok": False, "error": "Invalid passcode"}), 401
    try:
        gc.delete_video(file_id)
        _invalidate_cache()
        return jsonify({"ok": True, "items": gc.list_videos_admin()})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.errorhandler(413)
def too_large(_exc):
    return jsonify({"ok": False, "error": "Request body too large."}), 413


# -------------------------------- Pages / static --------------------------------

@app.get("/")
def page_index():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.get("/kiosk")
def page_kiosk():
    return send_from_directory(PUBLIC_DIR, "kiosk.html")


@app.get("/admin")
def page_admin():
    return send_from_directory(PUBLIC_DIR, "admin.html")


@app.get("/<path:filepath>")
def static_files(filepath):
    return send_from_directory(PUBLIC_DIR, filepath)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
