# OrgPhotos OneDrive Add-on

**Verze 2.10 (2025-05-26)**

„OrgPhotos“ je Home Assistant add-on, který **robustně třídí** soubory ve vaší OneDrive složce podle data (rok/měsíc), přímo v cloudu, pomocí Microsoft Graph API.

---

## Klíčové vlastnosti

- **Pyramida jistoty** pro výběr data:
  1. EXIF metadata (`photo.takenDateTime`, `video.takenDateTime`)
  2. Datum v rodičovské složce (např. `2022-09`)
  3. Datum v názvu souboru (generické regexy + common patterns)
  4. Nejstarší z `fileSystemInfo.lastModifiedDateTime` a `fileSystemInfo.createdDateTime`
  5. OneDrive `createdDateTime` (upload time)
- **Timezone-aware** práce s časem (vše v UTC), bez varování Pythonu
- **Přepis duplicit** pomocí `@microsoft.graph.conflictBehavior = replace`
- **Automatické obnovení** přístupového tokenu při vypršení (HTTP 401)
- **Nekonečná smyčka** s pauzou `DEBOUNCE_SECS` (nastavitelnou v GUI)
- **Neplatné nebo budoucí datum** posílá do složky `UNSORTED`
- Podrobný **log** každé operace (metoda, datum, cílová cesta)

---

## Požadavky

1. **Home Assistant** s podporou add-onů  
2. **OneDrive-Sync** add-on nebo jiná cesta k získání `refresh_token`  
3. Zápisový přístup k souboru s `refresh_token` (typicky `/data/refresh_token`)

---

## Instalace add-onu

1. Vytvoř si repozitář s tímto add-onem v Supervisor → Add-on Store → Přidat zdroj.  
2. V Supervisor → Add-on → OrgPhotos OneDrive klikni **Install**.

---

## Konfigurace (`config.json`)

```yaml
options:
  source_dir: "Inbox"            # zdrojová složka v OneDrive
  target_dir: "OrgPhotos"        # kořen pro třídění (vytvoří podsložky)
  debounce_secs: 20              # interval mezi průchody (s)
  onedrive_client_id: "<GUID>"   # Azure AD aplikace
  onedrive_tenant_id: "common"   # Tenant ID nebo 'common'

Spuštění (run.sh)

Add-on automaticky načte konfiguraci přes bashio a nastaví environment proměnné:

export SOURCE_DIR=$(bashio::config 'source_dir')
export TARGET_DIR=$(bashio::config 'target_dir')
export DEBOUNCE_SECS=$(bashio::config 'debounce_secs')
export ONEDRIVE_CLIENT_ID=$(bashio::config 'onedrive_client_id')
export ONEDRIVE_TENANT_ID=$(bashio::config 'onedrive_tenant_id')
exec python3 -u /addon/OrgPhotos.py

Logování

    INFO: spuštění (run start), přesunuté soubory, přepsané duplicitní soubory, pauza (Sleeping X seconds)

    WARNING: soubory se špatným/absurdním datem (přesun do Unsorted)

    ERROR: nečekané chyby (token refresh, HTTP chyby mimo 404)

Složka Unsorted

Pokud validate_date() vyhodnotí čas jako neplatný (před rokem 1990 nebo v budoucnosti), soubor se přesune do:

<TARGET_DIR>/Unsorted/

Umožňuje ruční kontrolu nesprávně pojmenovaných či poškozených souborů.
Údržba

    Pro další formáty názvů (lokální Windows screenshoty, nestandardní prefixy) uprav FILENAME_PATTERNS nebo GENERIC_PATTERNS v OrgPhotos.py.

    Sledování běhu add-onu a případné restartování v Supervisoru.