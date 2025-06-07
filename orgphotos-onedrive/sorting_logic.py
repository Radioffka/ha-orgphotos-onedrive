# sorting_logic.py

import re
import datetime as dt
from typing import Optional, Tuple

# --------------------------------------------------
# Constants for time zones and valid date range
# --------------------------------------------------
UTC = dt.timezone.utc
INVALID_LOWER = dt.datetime(1990, 1, 1, tzinfo=UTC)
# Upper boundary is set dynamically to current time + 1 day

# --------------------------------------------------
# Patterns for extracting a date from the filename
# --------------------------------------------------
FILENAME_PATTERNS = [
    "%Y:%m:%d %H:%M:%S",       # exif‐style "2023:05:12 14:30:00"
    "%Y-%m-%d %H.%M.%S",       # Windows screenshot "2023-05-12 14.30.00"
    "%Y%m%d_%H%M%S",           # e.g. "20230512_143000"
    "%Y-%m-%d_%H-%M-%S",       # e.g. "2023-05-12_14-30-00"
    "%Y%m%d%H%M%S",            # e.g. "20230512143000"
    "%Y-%m-%d %H:%M:%S",       # ISO-like "2023-05-12 14:30:00"
    "%Y%m%d",                  # date only "20230512"
    "%Y-%m-%d",                # date only "2023-05-12"
]

# --------------------------------------------------
# Generic regex patterns if none of the above match
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
# Helper functions for converting and validating dates
# --------------------------------------------------
def iso_to_dt(raw_str: str) -> dt.datetime:
    """
    Convert an ISO 8601 string (e.g. "2023-05-12T14:30:00Z") to a UTC datetime object.
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
    Try to derive a date from the filename using predefined formats
    or regex patterns. Returns a datetime in UTC or None.
    """
    # First try all FILENAME_PATTERNS
    for pattern in FILENAME_PATTERNS:
        try:
            candidate = dt.datetime.strptime(name, pattern)
            return candidate.replace(tzinfo=UTC)
        except Exception:
            continue

    # If no pattern matches, try GENERIC_PATTERNS
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
    Check whether the datetime object is in the range [INVALID_LOWER, current time + 1 day].
    Returns True if dt_obj is not None and within the range, otherwise False.
    """
    if dt_obj is None:
        return False
    invalid_upper = dt.datetime.now(UTC) + dt.timedelta(days=1)
    return INVALID_LOWER <= dt_obj <= invalid_upper

# --------------------------------------------------
# Main function: pick_date using the pyramid of certainty
# --------------------------------------------------
def pick_date(entry: dict) -> Tuple[Optional[dt.datetime], str]:
    """
    Determine the most reliable capture date based on the so-called pyramid of certainty.
    Input: entry – dictionary with file metadata from OneDrive (Graph API response).
    Output: (datetime in UTC or None, method as a string).
    Method is one of: 'exif-photo', 'exif-video', 'upload-created',
                      'folder', 'filename', 'fs_modified', 'fs_created', 'unknown'.
    """
    # 1) EXIF date for photos
    photo_meta = entry.get("photo", {})
    if photo_meta.get("takenDateTime"):
        return iso_to_dt(photo_meta["takenDateTime"]), "exif-photo"

    # 2) EXIF date for videos
    video_meta = entry.get("video", {})
    if video_meta.get("takenDateTime"):
        return iso_to_dt(video_meta["takenDateTime"]), "exif-video"

    # 3) If it's a video (by extension), use createdDateTime as the upload timestamp
    name_lower = entry.get("name", "").lower()
    if name_lower.endswith((".mp4", ".mov", ".mkv", ".avi")):
        created = entry.get("createdDateTime")
        if created:
            return iso_to_dt(created), "upload-created"

    # 4) Date from parent folder name (YYYY-MM or YYYY_MM_DD)
    parent_path = entry.get("parentReference", {}).get("path", "")
    folder_match = re.search(r"/(\d{4})[-_](\d{2})(?:[-_](\d{2}))?$", parent_path)
    if folder_match:
        year, month, day = folder_match.groups()
        day = day or "1"
        try:
            return dt.datetime(int(year), int(month), int(day), tzinfo=UTC), "folder"
        except Exception:
            pass

    # 5) Date from filename
    dt_from_name = date_from_name(entry.get("name", ""))
    if dt_from_name:
        return dt_from_name, "filename"

    # 6) File timestamps: take the oldest of lastModified and fileSystemInfo.created
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

    # 7) Fallback: general upload timestamp (createdDateTime)
    created = entry.get("createdDateTime")
    if created:
        return iso_to_dt(created), "upload-created"

    # 8) No source – unknown date
    return None, "unknown"

# --------------------------------------------------
# Optional helper function: build the target path based on the date
# --------------------------------------------------
def determine_target_path(entry: dict) -> Tuple[str, str]:
    """
    Combined function that returns the appropriate relative target path in the
    structure YEAR/YEAR_MONTH or 'Unsorted', and also returns the method.
    If the date is invalid (or None), returns ('Unsorted', method).
    Otherwise returns ('YYYY/YYYY_MM', method).
    """
    when, method = pick_date(entry)
    if not validate_date(when):
        return "Unsorted", method

    when_utc = when.astimezone(UTC)
    year = when_utc.year
    month = when_utc.month
    target_subdir = f"{year}/{year:04d}_{month:02d}"
    return target_subdir, method
