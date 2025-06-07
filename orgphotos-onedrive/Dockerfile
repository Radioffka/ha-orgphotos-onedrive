ARG BUILD_FROM
FROM ${BUILD_FROM}

# ---- system packages ----
RUN apk add --no-cache \
      python3 \
      py3-pip \
  && python3 -m venv /opt/venv

# Add the virtual environment to PATH
ENV PATH="/opt/venv/bin:$PATH"

# ---- Python dependencies ----
RUN pip install --no-cache-dir \
      piexif \
      msal \
      requests

# ---- application files ----
COPY OrgPhotos.py       /addon/
COPY sorting_logic.py   /addon/
COPY run.sh             /etc/services.d/orgphotos/run

# Make files executable
RUN chmod 755 /etc/services.d/orgphotos/run /addon/OrgPhotos.py




