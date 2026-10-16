# =============================================================================
#  Epic Davinci - ISKUR & SBB Ilan Takip Botu (Docker imaji)
#  Koyeb / Fly.io / Railway / kendi sunucunuz gibi konteyner platformlari icin
# =============================================================================
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Istanbul

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

# Kod /app icinde durur
COPY . /app

RUN pip install --no-cache-dir -r /app/requirements.txt

# Calisma klasoru /data: bot durum dosyalarini (jobs.db, seen_jobs.json,
# last_update_id.txt) buraya yazar. Kalici olmasi icin bu klasore volume baglayin:
#     docker run -v iskur_state:/data ...
# Bot goreli yollari kullandigi icin CWD'nin /data olmasi yeterlidir.
WORKDIR /data

CMD ["python", "/app/check_now.py", "--forever"]
