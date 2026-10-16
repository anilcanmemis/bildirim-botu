#!/usr/bin/env bash
# =============================================================================
#  Epic Davinci - ISKUR & SBB Ilan Takip Botu
#  Tek komutla 7/24 kesintisiz sunucu (VM) kurulumu
# =============================================================================
#
#  Desteklenen sistemler: Ubuntu 22.04 / 24.04, Debian 12+ (Oracle Cloud,
#  Google Cloud, Hetzner, DigitalOcean vb. tum Linux sunucularda calisir)
#
#  Kullanim (sunucuda, repo klasorunun icinden):
#      sudo bash deploy/setup.sh
#
#  Opsiyonel ortam degiskenleri:
#      APP_DIR=/opt/epic-davinci   Kurulacak klasor
#      RUN_USER=ubuntu             Servisin calisacagi kullanici
#      KEEPALIVE=true              Oracle "bosta sayilma" korumasini da kur
#      KEEPALIVE_PERCENT=15        Koruma icin mesgul edilecek CPU yuzdesi
#
# =============================================================================

set -euo pipefail

SERVICE_NAME="iskur-bot"
KEEPALIVE_SERVICE="iskur-keepalive"
APP_DIR="${APP_DIR:-/opt/epic-davinci}"
ENV_FILE="/etc/${SERVICE_NAME}.env"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
KEEPALIVE="${KEEPALIVE:-false}"
KEEPALIVE_PERCENT="${KEEPALIVE_PERCENT:-15}"

# --- 0. Root kontrolu --------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
    echo "HATA: Bu script root yetkisi gerektirir. 'sudo bash deploy/setup.sh' seklinde calistirin." >&2
    exit 1
fi

# --- 1. Servisin calisacagi kullaniciyi belirle -------------------------------
if [ -z "${RUN_USER:-}" ]; then
    if [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
        RUN_USER="$SUDO_USER"
    elif id -u ubuntu >/dev/null 2>&1; then
        RUN_USER="ubuntu"
    else
        RUN_USER="root"
    fi
fi
echo ">>> Servis kullanicisi : ${RUN_USER}"
echo ">>> Kurulum klasoru   : ${APP_DIR}"

# --- 2. Sistem paketlerini kur ------------------------------------------------
echo ">>> Sistem paketleri kuruluyor (python3-venv, git)..."
export DEBIAN_FRONTEND=noninteractive
if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y -qq python3 python3-venv python3-pip git ca-certificates tzdata
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y python3 python3-pip git ca-certificates
else
    echo "UYARI: Bilinmeyen paket yoneticisi. Python 3 ve venv'in kurulu oldugundan emin olun."
fi

# --- 3. Proje dosyalarini APP_DIR'e kopyala -----------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

mkdir -p "${APP_DIR}"

if [ "${SRC_DIR}" != "${APP_DIR}" ]; then
    echo ">>> Proje dosyalari kopyalaniyor: ${SRC_DIR} -> ${APP_DIR}"
    # .git, .venv ve onbellek dosyalari haric her seyi kopyala
    ( cd "${SRC_DIR}" && tar --exclude='./.git' --exclude='./.venv' \
        --exclude='./__pycache__' --exclude='./deploy' -cf - . ) \
        | ( cd "${APP_DIR}" && tar -xf - )
    # deploy klasoru de kopyalansin (yeniden kurulum/guncelleme icin)
    mkdir -p "${APP_DIR}/deploy"
    cp -f "${SCRIPT_DIR}"/* "${APP_DIR}/deploy/" 2>/dev/null || true
else
    echo ">>> Proje zaten ${APP_DIR} icinde, kopyalama atlandi."
fi

# --- 4. Python sanal ortami ve bagimliliklar ----------------------------------
echo ">>> Python sanal ortami hazirlaniyor..."
if [ ! -d "${APP_DIR}/.venv" ]; then
    python3 -m venv "${APP_DIR}/.venv"
fi
"${APP_DIR}/.venv/bin/pip" install --quiet --upgrade pip
"${APP_DIR}/.venv/bin/pip" install --quiet -r "${APP_DIR}/requirements.txt"
echo ">>> Bagimliliklar kuruldu."

# --- 5. Gizli anahtar dosyasi (opsiyonel ama onerilir) ------------------------
if [ ! -f "${ENV_FILE}" ]; then
    echo ">>> ${ENV_FILE} olusturuluyor (gizli anahtarlar icin)..."
    cat > "${ENV_FILE}" <<'EOF'
# Epic Davinci - ISKUR Bot gizli anahtarlari
# Bu dosyayi doldurursaniz config_iskur.json icindeki degerlerin yerine gecer.
# Bos birakilan satirlar yok sayilir ve config_iskur.json kullanilir.
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ADMIN_CHAT_ID=
GEMINI_API_KEY=

# Durum dosyalarini GitHub'a da yedeklemek isterseniz true yapin (git yetkisi gerekir)
ISKUR_GIT_BACKUP=false
EOF
    chmod 600 "${ENV_FILE}"
fi
chmod 600 "${ENV_FILE}" || true

# --- 6. systemd servisini kur -------------------------------------------------
echo ">>> systemd servisi kuruluyor..."
sed -e "s|__APP_DIR__|${APP_DIR}|g" \
    -e "s|__RUN_USER__|${RUN_USER}|g" \
    "${SCRIPT_DIR}/${SERVICE_NAME}.service" > "${UNIT_PATH}"

chown -R "${RUN_USER}:${RUN_USER}" "${APP_DIR}"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}" >/dev/null 2>&1
systemctl restart "${SERVICE_NAME}"

# --- 6b. (Opsiyonel) Oracle "bosta sayilma" korumasi --------------------------
if [ "${KEEPALIVE}" = "true" ]; then
    echo ">>> Bosta sayilma (idle reclamation) korumasi kuruluyor..."
    sed -e "s|__APP_DIR__|${APP_DIR}|g" \
        -e "s|__RUN_USER__|${RUN_USER}|g" \
        -e "s|__KEEPALIVE_PERCENT__|${KEEPALIVE_PERCENT}|g" \
        "${SCRIPT_DIR}/${KEEPALIVE_SERVICE}.service" > "/etc/systemd/system/${KEEPALIVE_SERVICE}.service"
    systemctl daemon-reload
    systemctl enable "${KEEPALIVE_SERVICE}" >/dev/null 2>&1
    systemctl restart "${KEEPALIVE_SERVICE}"
    echo ">>> Koruma aktif: toplam CPU'nun ~%${KEEPALIVE_PERCENT}'i surekli mesgul edilecek."
fi

# --- 7. Durum kontrolu --------------------------------------------------------
sleep 6
echo
echo "======================================================================"
if systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo "  BASARILI: ${SERVICE_NAME} servisi calisiyor ve 7/24 aktif."
else
    echo "  UYARI: Servis aktif gorunmuyor. Loglari kontrol edin:"
    echo "     journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
fi
echo "======================================================================"
echo
echo "  Canli log takibi : journalctl -u ${SERVICE_NAME} -f"
echo "  Durum            : systemctl status ${SERVICE_NAME}"
echo "  Durdur           : sudo systemctl stop ${SERVICE_NAME}"
echo "  Yeniden baslat   : sudo systemctl restart ${SERVICE_NAME}"
echo "  Guncelleme       : cd ${APP_DIR} && git pull && sudo bash deploy/setup.sh"
echo
echo "  Servis, sunucu her acildiginda OTOMATIK olarak baslar."
echo "  Cokerse systemd tarafindan 10 saniye icinde yeniden baslatilir."
if [ "${KEEPALIVE}" = "true" ]; then
    echo "  Bosta sayilma korumasi (${KEEPALIVE_SERVICE}) da aktif."
fi
echo
