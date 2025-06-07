#!/usr/bin/env python3
"""
OrgPhotos – robust OneDrive photo sorting (version 2.1.6, fixed URLs)
===================================================================

This version:
  • Delegates the "pyramid of certainty" to sorting_logic.py (pick_date, validate_date).
  • Uses the original /me/drive/… URLs with the correct trailing at sign (:/ and :/children).
  • All 404/400/… responses are handled via requests.raise_for_status() as in the original version.
  • Debug output shows what's in SOURCE_DIR and TARGET_DIR.
"""

import os
import sys
import time
import logging
import requests
import datetime as dt
from typing import Optional

# ---------------------------------------------------------------------------
# Add the script directory to sys.path so Python can find sorting_logic.py
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# ---------------------------------------------------------------------------
# Import external sorting logic (pyramid of certainty)
# ---------------------------------------------------------------------------
from sorting_logic import pick_date, validate_date

# ---------------------------------------------------------------------------
# Debug: verify what run.sh passed via ENV
# ---------------------------------------------------------------------------
LOG_LEVEL = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("OrgPhotos")
log.info(f"DEBUG SOURCE_DIR = {os.getenv('SOURCE_DIR')}")
log.info(f"DEBUG TARGET_DIR = {os.getenv('TARGET_DIR')}")

# ---------------------------------------------------------------------------
# Environment variables (exported from run.sh / Home Assistant GUI)
# ---------------------------------------------------------------------------
CLIENT_ID     = os.getenv("ONEDRIVE_CLIENT_ID")
TENANT_ID     = os.getenv("ONEDRIVE_TENANT_ID", "common")
REFRESH_FP    = os.getenv("ONEDRIVE_REFRESH_FILE")
SOURCE_DIR    = os.getenv("SOURCE_DIR", "Inbox")
TARGET_DIR    = os.getenv("TARGET_DIR", "OrgPhotos")
DEBOUNCE_SECS = int(os.getenv("DEBOUNCE_SECS", "20"))
UNSORTED      = f"{TARGET_DIR}/Unsorted"

# Ensure we have ONEDRIVE_CLIENT_ID and the refresh token file
if not (CLIENT_ID and REFRESH_FP and os.path.exists(REFRESH_FP)):
    sys.exit("[ERROR] Missing ONEDRIVE_CLIENT_ID or REFRESH_TOKEN file (ONEDRIVE_REFRESH_FILE)")

log.info(f"Log level set to {log.getEffectiveLevel()}")

# ---------------------------------------------------------------------------
# Global variable for HEADERS (access token stored there after refresh)
# ---------------------------------------------------------------------------
HEADERS: dict[str, str] = {}
TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
ACCESS_TOKEN: str = ""

def refresh_access_token() -> None:
    """
    Read the refresh token from file and exchange it for an access token.
    Uses scope 'https://graph.microsoft.com/Files.ReadWrite.All offline_access',
    exactly like the original version 2.10.
    """
    global ACCESS_TOKEN, HEADERS
    try:
        rt = open(REFRESH_FP).read().strip()
    except IOError:
        log.error("Refresh token file missing: %s", REFRESH_FP)
        sys.exit(1)

    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": rt,
            "scope": "https://graph.microsoft.com/Files.ReadWrite.All offline_access",
        },
        timeout=30,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError:
        log.error("Token refresh failed: %s", response.text)
        sys.exit(1)

    tok = response.json()
    ACCESS_TOKEN = tok.get("access_token", "")
    HEADERS = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

    # If Graph returned a new refresh_token, save it back
    if tok.get("refresh_token"):
        try:
            with open(REFRESH_FP, "w") as f:
                f.write(tok["refresh_token"])
                log.debug("Refresh token file updated.")
        except Exception as e:
            log.warning("Cannot update refresh token file: %s", e)

def ensure_token():
    """
    If we don't have an ACCESS_TOKEN (HEADERS is empty), call refresh_access_token().
    """
    if not ACCESS_TOKEN:
        refresh_access_token()

# ---------------------------------------------------------------------------
# Wrapper for calling the Graph API (requests + raise_for_status())
# ---------------------------------------------------------------------------
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

def graph_request(method: str, endpoint: str, params=None, json_body=None):
    """
    1) ensure_token() keeps HEADERS with a valid Bearer token.
    2) Build URL = f"{GRAPH_BASE}/{endpoint}".
    3) If status == 401 → refresh token and retry once.
    4) response.raise_for_status() raises HTTPError for any error ≥400.
    5) On success returns response.json().
    """
    ensure_token()
    url = f"{GRAPH_BASE}/{endpoint}"
    response = requests.request(method, url, headers=HEADERS, params=params, json=json_body, timeout=30)

    if response.status_code == 401:
        log.info("Access token expired, refreshing and retrying.")
        refresh_access_token()
        response = requests.request(method, url, headers=HEADERS, params=params, json=json_body, timeout=30)

    try:
        response.raise_for_status()
    except requests.HTTPError:
        log.error(f"Graph API error: {response.status_code} – {response.text}")
        raise

    return response.json()

# ---------------------------------------------------------------------------
# Return folder ID in personal OneDrive – URL fixed with trailing ':/'
# ---------------------------------------------------------------------------
def get_folder_id(path: str) -> Optional[str]:
    """
    GET /me/drive/root:/{path}:/ → returns its ID if the folder exists.
    If it does not exist, response.raise_for_status() throws HTTPError(404).
    """
    endpoint = f"me/drive/root:/{path}:/"
    data = graph_request("GET", endpoint)
    return data.get("id") if data else None

# ---------------------------------------------------------------------------
# Ensure the folder exists or create it (recursively by segments).
# ---------------------------------------------------------------------------
def ensure_folder(path: str) -> str:
    """
    1) Try ID = get_folder_id(path). If it exists, return it.
    2) If get_folder_id() raises 404, split path = parent + name,
       recursively create parent (or use 'root' if parent == ''),
       then POST /me/drive/items/{parent_id}/children {name: seg, folder: {}}.
    3) Return the ID of the newly created (or existing) folder.
    """
    try:
        folder_id = get_folder_id(path)
        if folder_id:
            return folder_id
    except requests.HTTPError as e:
        # Reraise the exception if it's not a 404
        if "404" not in str(e):
            raise

    # Folder does not exist, create it
    parent, name = os.path.split(path)
    parent_id = ensure_folder(parent) if parent else 'root'
    create_endpoint = f"me/drive/items/{parent_id}/children"
    body = {"name": name, "folder": {}}
    result = graph_request("POST", create_endpoint, json_body=body)
    new_id = result.get("id") if result else None
    if not new_id:
        log.error("Cannot create folder: %s", path)
        sys.exit(1)
    return new_id

# ---------------------------------------------------------------------------
# Return a list of items (files + folders) in folder `path`
# ---------------------------------------------------------------------------
def list_children(path: str) -> list[dict]:
    """
    1) If path != "", endpoint = "me/drive/root:/{path}:/children"
       otherwise = "me/drive/root/children"
    2) Append ?$select=… to filter columns.
    3) If the folder does not exist, response.raise_for_status() throws 404 → script exits.
    4) Otherwise return data['value'].
    """
    if path:
        endpoint = f"me/drive/root:/{path}:/children"
    else:
        endpoint = "me/drive/root/children"
    fields = [
        "id","name","fileSystemInfo","createdDateTime","lastModifiedDateTime",
        "photo","video","parentReference","folder"
    ]
    data = graph_request("GET", f"{endpoint}?$select={','.join(fields)}")
    return data.get("value", []) if data else []

# ---------------------------------------------------------------------------
# Move a file (item_id) into folder dest_folder_id
# ---------------------------------------------------------------------------
def move_item(item_id: str, dest_folder_id: str, new_name: str):
    """
    PATCH /me/drive/items/{item_id} with {parentReference: {id: dest_folder_id}, name: new_name, conflictBehavior: replace}.
    If an HTTPError occurs, log it and continue.
    """
    endpoint = f"me/drive/items/{item_id}"
    body = {
        "parentReference": {"id": dest_folder_id},
        "name": new_name,
        "@microsoft.graph.conflictBehavior": "replace"
    }
    try:
        graph_request("PATCH", endpoint, json_body=body)
    except requests.HTTPError:
        log.error("Error moving item %s to %s", item_id, dest_folder_id)

# ---------------------------------------------------------------------------
# Single pass through SOURCE_DIR
# ---------------------------------------------------------------------------
def sort_once():
    moved = 0
    unsorted_count = 0

    entries = list_children(SOURCE_DIR)
    for entry in entries:
        # Skip if it's a folder
        if entry.get("folder") is not None:
            continue

        name = entry.get("name", "")
        item_id = entry.get("id")
        parent_ref = entry.get("parentReference", {}).get("path", "")

        # 1) Pyramid of certainty (in sorting_logic.py)
        when, method = pick_date(entry)

        # 2) Validate the date
        if not validate_date(when):
            dest_id = ensure_folder(UNSORTED)
            move_item(item_id, dest_id, name)
            log.warning("Unsorted: %s (method: %s)", name, method)
            unsorted_count += 1
            continue

        # 3) Valid date → subfolder YYYY/YYYY_MM
        when_utc = when.astimezone(dt.timezone.utc)
        year = when_utc.year
        month = when_utc.month
        dest_subpath = f"{TARGET_DIR}/{year}/{year:04d}_{month:02d}"

        # If the file is already in the correct subfolder, do nothing
        if parent_ref.endswith(dest_subpath):
            continue

        dest_id = ensure_folder(dest_subpath)
        move_item(item_id, dest_id, name)
        log.info(
            "Moved: %-30s → %-25s (method: %s, date: %s)",
            name, dest_subpath, method, when_utc.isoformat()
        )
        moved += 1

    log.info("Completed run: moved=%d, unsorted=%d", moved, unsorted_count)

# ---------------------------------------------------------------------------
# Main loop (every DEBOUNCE_SECS)
# ---------------------------------------------------------------------------
def main_loop():
    log.info("Starting main sorting loop.")
    try:
        while True:
            sort_once()
            log.info("Sleeping %d seconds …", DEBOUNCE_SECS)
            time.sleep(DEBOUNCE_SECS)
    except (KeyboardInterrupt, SystemExit):
        log.info("Received shutdown signal – exiting.")
        sys.exit(0)
    except Exception as e:
        log.exception("Unexpected error in main_loop: %s", e)
        sys.exit(1)

if __name__ == "__main__":
    main_loop()
