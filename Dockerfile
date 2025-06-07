ARG BUILD_FROM
FROM ${BUILD_FROM}

# ---- systémové balíčky ----
RUN apk add --no-cache \
      python3 \
      py3-pip \
  && python3 -m venv /opt/venv

# Přidat virtuální prostředí do PATH
ENV PATH="/opt/venv/bin:$PATH"

# ---- Python závislosti ----
RUN pip install --no-cache-dir \
      piexif \
      openpyxl \
      watchdog \
      dateparser \
      msal \
      requests

# ---- aplikační soubory ----
COPY OrgPhotos.py       /addon/
COPY sorting_logic.py   /addon/
COPY run.sh             /etc/services.d/orgphotos/run

# Udělit práva ke spuštění
RUN chmod 755 /etc/services.d/orgphotos/run /addon/OrgPhotos.py




