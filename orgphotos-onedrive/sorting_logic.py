# sorting_logic.py

import re
import datetime as dt
from typing import Optional, Tuple

# --------------------------------------------------
# Konstanty pro časové zóny a platné rozmezí dat
# --------------------------------------------------
UTC = dt.timezone.utc
INVALID_LOWER = dt.datetime(1990, 1, 1, tzinfo=UTC)
# Horní hranici nastavíme dynamicky na aktuální čas + 1 den

# --------------------------------------------------
# Vzory pro extrakci data z názvu souboru
# --------------------------------------------------
FILENAME_PATTERNS = [
    "%Y:%m:%d %H:%M:%S",       # exif‐style "2023:05:12 14:30:00"
    "%Y-%m-%d %H.%M.%S",       # Windows screenshot "2023-05-12 14.30.00"
    "%Y%m%d_%H%M%S",           # např. "20230512_143000"
    "%Y-%m-%d_%H-%M-%S",       # např. "2023-05-12_14-30-00"
    "%Y%m%d%H%M%S",            # např. "20230512143000"
    "%Y-%m-%d %H:%M:%S",       # ISO‐like "2023-05-12 14:30:00"
    "%Y%m%d",                  # pouze datum "20230512"
    "%Y-%m-%d",                # pouze datum "2023-05-12"
]

# --------------------------------------------------
# Generické regexové vzory, pokud žádný z výše nepadne
# --------------------------------------------------
GENERIC_PATTERNS = [
    # yyyyMMdd_HHmmss
    (r"(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})[_\-](?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})"),
    # yyyy-MM-dd_HH-mm-ss
    (r"(?P<year>\d{4})\-(?P<month>\d{2})\-(?P<day>\d{2})[_](?P<hour>\d{2})[_](?P<minute>\d{2})[_](?P<second>\d{2})"),
    # yyyyMMdd
    (r"(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})"),
    # yyyy-MM-dd
    (r"(?P<year>\d{4})\-(?P<month>\d{2})\-(?P<day>\d{2})"),
]

# --------------------------------------------------
# Pomocné funkce pro převod a validaci dat
# --------------------------------------------------
def iso_to_dt(raw_str: str) -> dt.datetime:
    """
    Převede ISO 8601 řetězec (např. "2023-05-12T14:30:00Z") na datetime objekt v UTC.
    """
    try:
        parsed = dt.datetime.fromisoformat(raw_str.replace("Z", "+00:00"))
        return parsed.astimezone(UTC)
    except Exception:
        base = raw_str.split(".")[0]
        parsed = dt.datetime.fromisoformat(base.replace("Z", "+00:00"))
        return parsed.astimezone(UTC)

def date_from_name(name: str) -> Optional[dt.datetime]:
    """
    Pokusí se podle jména souboru vysledovat datum podle předefinovaných formátů
    nebo podle regexů. Vrací datetime (UTC) nebo None.
    """
    # Nejprve zkusit všechny FILENAME_PATTERNS
    for pattern in FILENAME_PATTERNS:
        try:
            candidate = dt.datetime.strptime(name, pattern)
            return candidate.replace(tzinfo=UTC)
        except Exception:
            continue

    # Pokud žádný pattern nevyhovuje, zkusit GENERIC_PATTERNS
    for regex in GENERIC_PATTERNS:
        match = re.search(regex, name)
        if match:
            groups = match.groupdict()
            year = int(groups.get("year", 0))
            month = int(groups.get("month", 1))
            day = int(groups.get("day", 1))
            hour = int(groups.get("hour", 0))
            minute = int(groups.get("minute", 0))
            second = int(groups.get("second", 0))
            try:
                return dt.datetime(year, month, day, hour, minute, second, tzinfo=UTC)
            except Exception:
                return None
    return None

def validate_date(dt_obj: Optional[dt.datetime]) -> bool:
    """
    Zkontroluje, zda daný datetime objekt je v rozmezí [INVALID_LOWER, aktuální čas + 1 den].
    Vrací True, pokud dt_obj není None a spadá do rozmezí, jinak False.
    """
    if dt_obj is None:
        return False
    invalid_upper = dt.datetime.now(UTC) + dt.timedelta(days=1)
    return INVALID_LOWER <= dt_obj <= invalid_upper

# --------------------------------------------------
# Hlavní funkce: pyramida jistoty pick_date
# --------------------------------------------------
def pick_date(entry: dict) -> Tuple[Optional[dt.datetime], str]:
    """
    Určí nejjistější datum pořízení podle tzv. pyramidy jistoty.
    Vstup: entry – slovník s metadaty souboru z OneDrive (Graph API response).
    Výstup: (datetime v UTC nebo None, metoda jako řetězec).
    Metoda je jeden z: 'exif-photo', 'exif-video', 'upload-created',
                      'folder', 'filename', 'fs_modified', 'fs_created', 'unknown'.
    """
    # 1) EXIF datum pro fotky
    photo_meta = entry.get("photo", {})
    if photo_meta.get("takenDateTime"):
        return iso_to_dt(photo_meta["takenDateTime"]), "exif-photo"

    # 2) EXIF datum pro videa
    video_meta = entry.get("video", {})
    if video_meta.get("takenDateTime"):
        return iso_to_dt(video_meta["takenDateTime"]), "exif-video"

    # 3) Pokud je to video (podle přípony), použít createdDateTime jako upload timestamp
    name_lower = entry.get("name", "").lower()
    if name_lower.endswith((".mp4", ".mov", ".mkv", ".avi")):
        created = entry.get("createdDateTime")
        if created:
            return iso_to_dt(created), "upload-created"

    # 4) Datum z názvu rodičovské složky (YYYY-MM nebo YYYY_MM_DD)
    parent_path = entry.get("parentReference", {}).get("path", "")
    folder_match = re.search(r"/(\d{4})[-_](\d{2})(?:[-_](\d{2}))?$", parent_path)
    if folder_match:
        year, month, day = folder_match.groups()
        day = day or "1"
        try:
            return dt.datetime(int(year), int(month), int(day), tzinfo=UTC), "folder"
        except Exception:
            pass

    # 5) Datum z názvu souboru
    dt_from_name = date_from_name(entry.get("name", ""))
    if dt_from_name:
        return dt_from_name, "filename"

    # 6) Souborové časy: vezměme nejstarší z lastModified a fileSystemInfo.created
    fs_info = entry.get("fileSystemInfo", {})
    candidates: list[Tuple[dt.datetime, str]] = []
    for key, tag in [("lastModifiedDateTime", "fs_modified"), ("createdDateTime", "fs_created")]:
        ts = fs_info.get(key)
        if ts:
            try:
                dt_obj = iso_to_dt(ts)
                candidates.append((dt_obj, tag))
            except Exception:
                pass
    if candidates:
        oldest, method = min(candidates, key=lambda x: x[0])
        return oldest, method

    # 7) Fallback: upload timestamp (createdDateTime) obecně
    created = entry.get("createdDateTime")
    if created:
        return iso_to_dt(created), "upload-created"

    # 8) Žádný zdroj – neznámé datum
    return None, "unknown"

# --------------------------------------------------
# Volitelná pomocná funkce: sestaví cílovou cestu na základě data
# --------------------------------------------------
def determine_target_path(entry: dict) -> Tuple[str, str]:
    """
    Kombinovaná funkce, která vrátí vhodnou relativní cílovou cestu (ve struktuře
    YEAR/YEAR_MONTH) nebo 'Unsorted', a současně vrátí metodu (string).
    Pokud datum není platné (nebo je None), vrátí ('Unsorted', method).
    Jinak vrátí ('YYYY/YYYY_MM', method).
    """
    when, method = pick_date(entry)
    if not validate_date(when):
        return "Unsorted", method

    when_utc = when.astimezone(UTC)
    year = when_utc.year
    month = when_utc.month
    target_subdir = f"{year}/{year:04d}_{month:02d}"
    return target_subdir, method
