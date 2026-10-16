"""
===============================================================================
İŞKUR & SBB İlan Kontrol ve Telegram Canlı İntibak Scripti (check_now.py)
===============================================================================

Bu script, hem kendi sunucuda (systemd/Docker) hem de GitHub Actions ortamında
7/24 KESİNTİSİZ çalışacak şekilde tasarlanmıştır.

Çalışma Mantığı:
- Her 3 dakikada bir İŞKUR, SBB, Memurlar.net ve Kariyer.net portallarını tarar.
- Telegram mesajlarını ve buton tıklamalarını 2 saniyede bir işleyerek anlık yanıt verir.
- Durum dosyaları (seen_jobs.json, jobs.db, last_update_id.txt) yerel diskte kalıcıdır.
  `ISKUR_GIT_BACKUP=true` verilirse ayrıca her 10 dakikada bir git'e yedeklenir.

Çalıştırma Modları:
- `--forever`  : SINIRSIZ döngü. Kendi sunucuda (systemd Restart=always) 7/24 çalışır.
                 Varsayılan ve önerilen mod budur.
- `--duration <saniye>` : Belirtilen süre kadar çalışıp temiz kapanır.
                 GitHub Actions'ın 6 saatlik limiti için 21000 sn (~5s50dk) kullanılır.
- `--once`     : Tek geçiş yapıp anında sonlanır (test/debug için).
"""

import os
import subprocess
import sys
import time
import logging
import signal
from typing import Optional
from iskur_bot import IskurJobBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("CheckNow")

# GitHub Actions ortamında çalışıp çalışmadığını tespit eder
IS_CI = os.environ.get("GITHUB_ACTIONS") == "true"

# Durum dosyalarının git'e yedeklenip yedeklenmeyeceği.
# GitHub Actions'ta her zaman açık; kendi sunucuda ISKUR_GIT_BACKUP=true ile isteğe bağlı açılır.
GIT_BACKUP_ENABLED = IS_CI or os.environ.get("ISKUR_GIT_BACKUP", "").lower() == "true"

# Durum dosyaları yerel diskte kalıcı olduğu için sunucuda varsayılan olarak yedek gerekmez.
DEFAULT_GIT_PUSH_INTERVAL = 600 if GIT_BACKUP_ENABLED else 0


def _handle_shutdown_signal(signum, frame):
    """SIGTERM / SIGINT sinyali alındığında temiz kapanış sağlar."""
    logger.info(f"🛑 Kapanma sinyali alındı ({signum}). Bot anında durduruluyor...")
    sys.exit(0)


try:
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    signal.signal(signal.SIGINT, _handle_shutdown_signal)
except Exception:
    pass


def _git_push_state():
    """
    Tarama durumunu (seen_jobs.json, last_update_id.txt) git'e push eder.
    Bu sayede GitHub Actions instance'ı yeniden başladığında kaldığı yerden devam eder.
    Kendi sunucuda yalnızca ISKUR_GIT_BACKUP=true ise çalışır; aksi halde sessizce atlanır.

    NOT: jobs.db bilinçli olarak push EDİLMEZ; içinde yetkili kullanıcı
    (Telegram ID) tablosu bulunduğu için depoda tutulmaz.
    """
    if not GIT_BACKUP_ENABLED:
        return

    def _run(cmd):
        return subprocess.run(cmd, check=False, capture_output=True, text=True)

    try:
        _run(["git", "config", "--global", "user.name", "GitHub Actions Bot"])
        _run(["git", "config", "--global", "user.email", "actions@github.com"])
        _run(["git", "add", "seen_jobs.json", "last_update_id.txt"])

        result = _run(["git", "commit", "-m", "chore: durum kaydi [skip ci]"])
        combined = (result.stdout or "") + (result.stderr or "")
        if "nothing to commit" in combined or "no changes added" in combined:
            logger.debug("Git: Kaydedilecek değişiklik yok, push atlandı.")
            return

        # HEAD detached olsa dahi çalışsın diye hedef dal açıkça belirtilir.
        # (actions/checkout bazı olay tiplerinde detached HEAD bırakır ve
        #  çıplak `git push` bu durumda hata verir.)
        branch = os.environ.get("GITHUB_REF_NAME", "main") or "main"
        push = _run(["git", "push", "origin", f"HEAD:{branch}"])

        if push.returncode == 0:
            logger.info(f"✅ Durum git'e kaydedildi ve push edildi (dal: {branch}).")
            return

        # Push reddedildiyse (ör. bu sırada depoya yeni bir kod commit'i
        # gönderildiyse "non-fast-forward" olur) uzak dalı rebase ile alıp
        # bir kez daha denenir. Böylece kod güncellemesi durum kaydını kilitlemez.
        detail = (push.stderr or push.stdout or "").strip().replace("\n", " ")[:300]
        logger.warning(f"⚠️ İlk push başarısız (kod {push.returncode}): {detail}")

        _run(["git", "pull", "--rebase", "--autostash", "origin", branch])
        retry = _run(["git", "push", "origin", f"HEAD:{branch}"])
        if retry.returncode == 0:
            logger.info(f"✅ Durum git'e kaydedildi (rebase sonrası, dal: {branch}).")
        else:
            detail2 = (retry.stderr or retry.stdout or "").strip().replace("\n", " ")[:300]
            logger.warning(f"⚠️ Git push tekrar başarısız (kod {retry.returncode}): {detail2}")
    except Exception as err:
        logger.warning(f"Git push sırasında hata (görmezden gelinebilir): {err}")


def run_checker(
    duration_seconds: Optional[int] = 21000,
    job_check_interval: int = 180,
    git_push_interval: Optional[int] = None,
    single_pass: bool = False
):
    """
    Telegram canlı etkileşim ve periyodik ilan tarama ana döngüsü.

    :param duration_seconds: Toplam çalışma süresi (saniye).
                             None verilirse SINIRSIZ çalışır (7/24 sunucu modu).
                             Varsayılan: 21000 (~5s50dk - GitHub Actions için).
    :param job_check_interval: İlan taramaları arası bekleme süresi (saniye). Varsayılan: 180 (3dk).
    :param git_push_interval: Git push araları (saniye). None ise otomatik belirlenir.
    :param single_pass: True ise tek geçiş yapıp anında sonlanır (--once modu).
    """
    if git_push_interval is None:
        git_push_interval = DEFAULT_GIT_PUSH_INTERVAL

    bot = IskurJobBot()

    if single_pass:
        logger.info("🔬 Tek seferlik kontrol başlatılıyor (--once)...")
        bot.process_telegram_interactive_messages()
        new_jobs = bot.check_for_new_jobs(is_initial_run=False)
        logger.info(f"✅ Tek seferlik kontrol tamamlandı. {len(new_jobs)} adet yeni ilan bildirildi.")
        return

    if duration_seconds is None:
        logger.info("🚀 7/24 KESİNTİSİZ Mod Başlatıldı! (Sınırsız çalışma süresi)")
    else:
        saat_dk = f"{duration_seconds // 3600} saat {(duration_seconds % 3600) // 60} dakika"
        logger.info(f"🚀 Sürekli Döngü Modu Başlatıldı! Toplam çalışma süresi: {saat_dk}")
    logger.info(f"   ↳ İlan taraması: her {job_check_interval // 60} dakikada bir")
    if git_push_interval:
        logger.info(f"   ↳ Git yedekleme (durum kaydı): her {git_push_interval // 60} dakikada bir")
    else:
        logger.info("   ↳ Git yedekleme: kapalı (durum dosyaları yerel diskte kalıcı)")

    start_time = time.time()
    last_job_check: float = 0.0
    last_git_push: float = 0.0

    while duration_seconds is None or (time.time() - start_time) < duration_seconds:
        try:
            # ⚡ 1. Telegram mesajlarını ve buton etkileşimlerini anında işle
            bot.process_telegram_interactive_messages()

            now = time.time()

            # 🔎 2. Her 3 dakikada bir ilan taraması yap
            if now - last_job_check >= job_check_interval:
                gecen_sure = int(now - start_time)
                logger.info(
                    f"🔎 Periyodik İlan Taraması ({gecen_sure // 60}. dakika) "
                    f"(Saat: {time.strftime('%H:%M:%S')})..."
                )
                bot.check_for_new_jobs(is_initial_run=False)
                last_job_check = time.time()

            # 💾 3. Git yedekleme açıksa her 10 dakikada bir durumu kaydet
            if git_push_interval and (now - last_git_push) >= git_push_interval:
                logger.info("💾 Periyodik durum kaydı (git push) yapılıyor...")
                _git_push_state()
                last_git_push = time.time()

            time.sleep(2)

        except KeyboardInterrupt:
            logger.info("⌨️ Kullanıcı tarafından durduruldu.")
            break
        except Exception as err:
            logger.error(f"Döngü sırasında beklenmeyen hata: {err}")
            time.sleep(5)

    if duration_seconds is None:
        logger.info("🛑 Sınırsız döngü durduruldu. Temiz kapanış yapılıyor.")
    else:
        kalan = int(duration_seconds - (time.time() - start_time))
        logger.info(f"✅ {saat_dk} süre tamamlandı (kalan: {max(0, kalan)}sn). Temiz kapanış yapılıyor.")

    # Kapanmadan önce son durumu kaydet
    if GIT_BACKUP_ENABLED:
        logger.info("💾 Kapanış öncesi son git push yapılıyor...")
        _git_push_state()


if __name__ == "__main__":
    args = sys.argv[1:]
    is_once = "--once" in args

    # --forever: 7/24 kesintisiz mod (kendi sunucu / systemd / Docker için)
    if "--forever" in args:
        duration = None
    elif "--duration" in args:
        try:
            duration = int(args[args.index("--duration") + 1])
        except (IndexError, ValueError):
            logger.error("--duration parametresi için geçerli bir saniye değeri verilmedi.")
            sys.exit(2)
    else:
        duration = 21000  # Varsayılan: GitHub Actions 6 saat limiti için ~5s50dk

    try:
        run_checker(
            duration_seconds=duration,
            job_check_interval=180,      # 3 dakikada bir ilan taraması
            git_push_interval=None,      # Otomatik: CI'da 600sn, sunucuda kapalı
            single_pass=is_once
        )
    except Exception as err:
        logger.error(f"Kontrol sırasında beklenmeyen hata: {err}", exc_info=True)
        sys.exit(1)
