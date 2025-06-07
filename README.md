# OrgPhotos OneDrive Add-on

**Version 2.1.7 (2025-05-26)**

*OrgPhotos* is a Home Assistant add-on that robustly sorts files in your OneDrive folder by date (year/month), directly in the cloud, using the Microsoft Graph API.

## Key Features

- **Pyramid of certainty for date selection**  
  1. EXIF metadata (`photo.takenDateTime`, `video.takenDateTime`)  
  2. Parent folder date (e.g. `2022-09`)  
  3. Date in file name (generic regexes + common patterns)  
  4. Earliest of `fileSystemInfo.lastModifiedDateTime` and `fileSystemInfo.createdDateTime`  
  5. OneDrive `createdDateTime` (upload time)  
- **Timezone-aware handling** (all in UTC), without Python warnings  
- **Duplicate handling** with `@microsoft.graph.conflictBehavior = replace`  
- **Automatic token refresh** on expiration (HTTP 401)  
- **Infinite loop** with adjustable `DEBOUNCE_SECS` pause (configurable via GUI)  
- **Invalid or future dates** are sent to the `UNSORTED` folder  
- **Detailed logging** of every operation (method, date, destination path)  

## Requirements

- Home Assistant with add-on support  
- OneDrive-Sync add-on or other mechanism to obtain a `refresh_token`  
- Write access to the `refresh_token` file (typically `/data/refresh_token`)  

## Installation

1. In Home Assistant, go to **Supervisor → Add-on Store → Add Repository**.  
2. Enter the repository URL and save.  
3. In **Supervisor → Add-on → OrgPhotos OneDrive**, click **Install**.  

## Configuration (`config.json`)

```yaml
options:
  source_dir: "Inbox"            # OneDrive folder to watch
  target_dir: "OrgPhotos"        # Root folder for sorting (creates subfolders)
  debounce_secs: 20              # Interval between scans (seconds)
  onedrive_client_id: "<GUID>"   # Azure AD application (client) ID
  onedrive_tenant_id: "common"   # Tenant ID or 'common'
```

Execution (run.sh)

The add-on automatically reads the configuration via bashio and sets environment variables:

export SOURCE_DIR=$(bashio::config 'source_dir')
export TARGET_DIR=$(bashio::config 'target_dir')
export DEBOUNCE_SECS=$(bashio::config 'debounce_secs')
export ONEDRIVE_CLIENT_ID=$(bashio::config 'onedrive_client_id')
export ONEDRIVE_TENANT_ID=$(bashio::config 'onedrive_tenant_id')
exec python3 -u /addon/OrgPhotos.py

Logging

    INFO: startup (run start), moved files, replaced duplicates, pause (Sleeping X seconds)

    WARNING: files with invalid or absurd dates (moved to Unsorted)

    ERROR: unexpected errors (token refresh failures, HTTP errors other than 404)

Unsorted Folder

When validate_date() determines a date is invalid (before 1990 or in the future), files are moved to:

<TARGET_DIR>/Unsorted/

This allows manual review of incorrectly named or corrupted files.
Maintenance

    To support additional filename formats (Windows screenshots, unconventional prefixes), adjust FILENAME_PATTERNS or GENERIC_PATTERNS in `sorting_logic.py`.

    Monitor the add-on in Supervisor and restart if necessary.
