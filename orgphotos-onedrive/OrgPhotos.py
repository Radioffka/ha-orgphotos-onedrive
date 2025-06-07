#!/usr/bin/env python3
"""
OrgPhotos – robustní třídění OneDrive fotek (verze 2.10, opravené URL)
====================================================================

Tato verze:
  • Deleguje “pyramidu jistoty” do sorting_logic.py (pick_date, validate_date).
  • Používá původní /me/drive/… URL se správným trailingem zavináče (:/ i :/children).
  • Všechny 404/400/… jsou ošetřeny metodou requests.raise_for_status() tak, 
    jak to dělala původní verze.
  • Debug-výpisy, aby bylo jasné, co je ve SOURCE_DIR/TARGET_DIR.
"""

import os
import sys
import time
import logging
import requests
import datetime as dt
from typing import Optional

# ---------------------------------------------------------------------------
# Přidání složky se skripty do sys.path (aby Python našel sorting_logic.py)
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# ---------------------------------------------------------------------------
# Import externí logiky třídění (pyramida jistoty)
# ---------------------------------------------------------------------------
from sorting_logic import pick_date, validate_date

# ---------------------------------------------------------------------------
# Debug: ověříme, co nám run.sh do ENV předal
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
# ENV proměnné (exportované z run.sh / Home Assistant GUI)
# ---------------------------------------------------------------------------
CLIENT_ID     = os.getenv("ONEDRIVE_CLIENT_ID")
TENANT_ID     = os.getenv("ONEDRIVE_TENANT_ID", "common")
REFRESH_FP    = os.getenv("ONEDRIVE_REFRESH_FILE")
SOURCE_DIR    = os.getenv("SOURCE_DIR", "Inbox")
TARGET_DIR    = os.getenv("TARGET_DIR", "OrgPhotos")
DEBOUNCE_SECS = int(os.getenv("DEBOUNCE_SECS", "20"))
UNSORTED      = f"{TARGET_DIR}/Unsorted"

# Ověř, že máme ONEDRIVE_CLIENT_ID a soubor s refresh tokenem
if not (CLIENT_ID and REFRESH_FP and os.path.exists(REFRESH_FP)):
    sys.exit("[ERROR] Missing ONEDRIVE_CLIENT_ID or REFRESH_TOKEN file (ONEDRIVE_REFRESH_FILE)")

log.info(f"Log level set to {log.getEffectiveLevel()}")

# ---------------------------------------------------------------------------
# Globální proměnná pro HEADERS (access token se tam uloží po refreshi)
# ---------------------------------------------------------------------------
HEADERS: dict[str, str] = {}
TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
ACCESS_TOKEN: str = ""

def refresh_access_token() -> None:
    """
    Načte refresh token ze souboru a vymění jej za access token.
    Používá scope 'https://graph.microsoft.com/Files.ReadWrite.All offline_access',
    přesně jako originální verze 2.10.
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

    # Pokud Graph vrátil i nový refresh_token, uložíme jej zpět
    if tok.get("refresh_token"):
        try:
            with open(REFRESH_FP, "w") as f:
                f.write(tok["refresh_token"])
                log.debug("Refresh token file updated.")
        except Exception as e:
            log.warning("Cannot update refresh token file: %s", e)

def ensure_token():
    """
    Pokud nemáme ACCESS_TOKEN (HEADERS je prázdné), zavoláme refresh_access_token().
    """
    if not ACCESS_TOKEN:
        refresh_access_token()

# ---------------------------------------------------------------------------
# Wrapper pro volání Graph API (requests + raise_for_status())
# ---------------------------------------------------------------------------
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

def graph_request(method: str, endpoint: str, params=None, json_body=None):
    """
    1) ensure_token() – udržuje HEADERS s platným Bearer tokenem.
    2) Sestaví URL = f"{GRAPH_BASE}/{endpoint}".
    3) Pokud status == 401 → refresh token a retry jednou.
    4) response.raise_for_status() – vyhodí HTTPError pro jakoukoliv chybu ≥400.
    5) V případě úspěchu vrátí response.json().
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
# Vrátí ID složky v osobním OneDrive – opravené URL s koncovým ':/'
# ---------------------------------------------------------------------------
def get_folder_id(path: str) -> Optional[str]:
    """
    GET /me/drive/root:/{path}:/ → pokud složka existuje, vrátí jej jí ID.
    Pokud neexistuje, response.raise_for_status() vyhodí HTTPError(404).
    """
    endpoint = f"me/drive/root:/{path}:/"
    data = graph_request("GET", endpoint)
    return data.get("id") if data else None

# ---------------------------------------------------------------------------
# Zajistí existenci složky, nebo ji vytvoří (rekurzivně po segmentech).
# ---------------------------------------------------------------------------
def ensure_folder(path: str) -> str:
    """
    1) Zkusíme ID = get_folder_id(path). Pokud existuje, vrátí ho.
    2) Pokud get_folder_id() vyhodí 404, rozdělíme path = parent + name,
       rekurzivně vytvoříme parent (nebo vezmeme 'root', pokud parent == ''),
       a pak POST /me/drive/items/{parent_id}/children {name: seg, folder: {}}.
    3) Vrátíme ID nově vytvořené (nebo již existující) složky.
    """
    try:
        folder_id = get_folder_id(path)
        if folder_id:
            return folder_id
    except requests.HTTPError as e:
        # Pokud to není 404, přepošleme výjimku dál
        if "404" not in str(e):
            raise

    # Složka neexistuje, vytvoříme ji
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
# Vrátí seznam položek (files + folders) ve složce `path`
# ---------------------------------------------------------------------------
def list_children(path: str) -> list[dict]:
    """
    1) Pokud path != "", endpoint = “me/drive/root:/{path}:/children”
       jinak           = “me/drive/root/children”
    2) Přidáme ?$select=… pro vyfiltrování sloupců.
    3) Pokud složka neexistuje, response.raise_for_status() vyhodí 404 → skript skončí.
    4) V opačném případě vrátí data['value'].
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
# Přesune soubor (item_id) do složky dest_folder_id
# ---------------------------------------------------------------------------
def move_item(item_id: str, dest_folder_id: str, new_name: str):
    """
    PATCH /me/drive/items/{item_id} se {parentReference: {id: dest_folder_id}, name: new_name, conflictBehavior: replace}.
    Pokud dojde k HTTPError, zaloguje a pokračuje.
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
# Jednorázový průchod složkou SOURCE_DIR
# ---------------------------------------------------------------------------
def sort_once():
    moved = 0
    unsorted_count = 0

    entries = list_children(SOURCE_DIR)
    for entry in entries:
        # Pokud je to složka, přeskočíme
        if entry.get("folder") is not None:
            continue

        name = entry.get("name", "")
        item_id = entry.get("id")
        parent_ref = entry.get("parentReference", {}).get("path", "")

        # 1) Pyramida jistoty (externě v sorting_logic.py)
        when, method = pick_date(entry)

        # 2) Validace data
        if not validate_date(when):
            dest_id = ensure_folder(UNSORTED)
            move_item(item_id, dest_id, name)
            log.warning("Unsorted: %s (method: %s)", name, method)
            unsorted_count += 1
            continue

        # 3) Platné datum → podsložka YYYY/YYYY_MM
        when_utc = when.astimezone(dt.timezone.utc)
        year = when_utc.year
        month = when_utc.month
        dest_subpath = f"{TARGET_DIR}/{year}/{year:04d}_{month:02d}"

        # Pokud už je soubor ve správné podsložce, nic neděláme
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
# Hlavní smyčka (každých DEBOUNCE_SECS)
# ---------------------------------------------------------------------------
def main_loop():
    log.info("Spouštím hlavní smyčku třídění.")
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
