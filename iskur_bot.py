"""
===============================================================================
İŞKUR & SBB Resmi Memur İlan Takip, Yetkilendirme ve Sticky Menü Botu
===============================================================================

Bu ana uygulama, İŞKUR e-Şube ve T.C. Cumhurbaşkanlığı SBB Resmi Kamu İlan 
portallarını periyodik olarak tarar. 

Özellikler:
- 🛡️ **Telegram ID Yetkilendirme**: Sadece yetkili kullanıcılar ve Admin erişebilir. Yetkisiz kişilere ID bilgisi verilip erişim engellenir.
- 👨‍dolar **Admin Yönetim Komutları**: `/ekle <id> <isim>`, `/sil <id>`, `/kullanicilar`
- 📌 **Mükerrer İlan Engelleme**: SQLite & JSON veritabanı denetimi ile 0 mükerrer bildirim.
- 📱 **Sticky (Sabit) Menü**: Telegram ekranının altında 7/24 sabit duran özel butonlu kontrol paneli.
- 🧠 **Gemini AI Analizi**: İlan metninden gizli detayları ve satır arası tüyoları çıkartır.
"""

import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime
from typing import Dict, List, Set, Any, Optional
import requests

from iskur_scraper import IskurScraper
from sbb_scraper import SbbScraper
from memurlar_scraper import MemurlarScraper
from kariyer_scraper import KariyerScraper
from gemini_analyzer import GeminiAnalyzer
from db_manager import DBManager

# Logging Yapılandırması
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("IskurBot")

# Türkiye 81 İl Haritası (Plaka Kodu -> İl Adı)
TURKEY_CITIES = {
    "0": "Tüm Türkiye",
    "1": "Adana", "2": "Adıyaman", "3": "Afyonkarahisar", "4": "Ağrı", "5": "Amasya",
    "6": "Ankara", "7": "Antalya", "8": "Artvin", "9": "Aydın", "10": "Balıkesir",
    "11": "Bilecik", "12": "Bingöl", "13": "Bitlis", "14": "Bolu", "15": "Burdur",
    "16": "Bursa", "17": "Çanakkale", "18": "Çankırı", "19": "Çorum", "20": "Denizli",
    "21": "Diyarbakır", "22": "Edirne", "23": "Elazığ", "24": "Erzincan", "25": "Erzurum",
    "26": "Eskişehir", "27": "Gaziantep", "28": "Giresun", "29": "Gümüşhane", "30": "Hakkari",
    "31": "Hatay", "32": "Isparta", "33": "Mersin", "34": "İstanbul", "35": "İzmir",
    "36": "Kars", "37": "Kastamonu", "38": "Kayseri", "39": "Kırklareli", "40": "Kırşehir",
    "41": "Kocaeli", "42": "Konya", "43": "Kütahya", "44": "Malatya", "45": "Manisa",
    "46": "Kahramanmaraş", "47": "Mardin", "48": "Muğla", "49": "Muş", "50": "Nevşehir",
    "51": "Niğde", "52": "Ordu", "53": "Rize", "54": "Sakarya", "55": "Samsun",
    "56": "Siirt", "57": "Sinop", "58": "Sivas", "59": "Tekirdağ", "60": "Tokat",
    "61": "Trabzon", "62": "Tunceli", "63": "Şanlıurfa", "64": "Uşak", "65": "Van",
    "66": "Yozgat", "67": "Zonguldak", "68": "Aksaray", "69": "Bayburt", "70": "Karaman",
    "71": "Kırıkkale", "72": "Batman", "73": "Şırnak", "74": "Bartın", "75": "Ardahan",
    "76": "Iğdır", "77": "Yalova", "78": "Karabük", "79": "Kilis", "80": "Osmaniye", "81": "Düzce"
}

# Coğrafi Bölgelere Göre Şehir Grupları
REGION_CITIES = {
    "marmara": {"title": "🌊 Marmara Bölgesi", "codes": ["34", "59", "22", "39", "41", "54", "16", "17", "10", "11", "77"]},
    "ic_anadolu": {"title": "⛰️ İç Anadolu Bölgesi", "codes": ["6", "26", "42", "38", "58", "71", "68", "70", "40", "51", "50", "66", "18"]},
    "ege": {"title": "🌅 Ege Bölgesi", "codes": ["35", "9", "20", "48", "45", "3", "43", "64"]},
    "akdeniz": {"title": "🌴 Akdeniz Bölgesi", "codes": ["7", "1", "33", "31", "32", "15", "80", "46"]},
    "karadeniz": {"title": "🌲 Karadeniz Bölgesi", "codes": ["55", "61", "52", "53", "28", "67", "78", "74", "14", "81", "37", "57", "5", "19", "60", "8", "29", "69"]},
    "dogu": {"title": "🏔️ Doğu Anadolu", "codes": ["25", "44", "23", "65", "4", "36", "49", "13", "12", "24", "30", "62", "75", "76"]},
    "guneydogu": {"title": "🏜️ Güneydoğu Anadolu", "codes": ["27", "21", "63", "47", "72", "2", "73", "56", "79"]}
}


def escape_html(text: Any) -> str:
    """Metin içindeki &, <, > karakterlerini Telegram HTML için güvenli hale getirir."""
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class IskurJobBot:
    """
    İŞKUR & SBB Kamu Personeli İlan İzleyici, Yetkilendirme ve Sabit Menü Botu.
    """

    CONFIG_FILE = "config_iskur.json"
    SEEN_JOBS_FILE = "seen_jobs.json"
    LAST_UPDATE_FILE = "last_update_id.txt"

    # 🔐 Ortam değişkeni -> config anahtarı eşlemesi.
    # Bu değişkenler tanımlıysa config_iskur.json içindeki değerleri geçersiz kılar.
    ENV_CONFIG_MAP = {
        "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
        "TELEGRAM_CHAT_ID": "telegram_chat_id",
        "ADMIN_CHAT_ID": "admin_chat_id",
        "GEMINI_API_KEY": "gemini_api_key",
    }

    def __init__(self):
        """
        Bot ayarlarını yükler, Scraper, SQLite ve Gemini AI nesnelerini başlatır.
        """
        self.config = self._load_config()
        self.seen_jobs: Set[str] = self._load_seen_jobs()
        self.db = DBManager()
        self._last_update_id: int = self._load_last_update_id()
        
        # Admin ID'sini SQLite veritabanına otomatik yetkili olarak ekle
        admin_id = str(self.config.get("admin_chat_id", ""))
        if admin_id:
            self.db.add_user(admin_id, "Sistem Yöneticisi (Admin)", role="admin")

        # e-Devlet çerezleri varsa al
        cookies = self.config.get("session_cookies", {})
        cookies = {k: v for k, v in cookies.items() if v}
        
        self.scraper = IskurScraper(cookies=cookies if cookies else None)
        self.sbb_scraper = SbbScraper()
        self.memurlar_scraper = MemurlarScraper()
        self.kariyer_scraper = KariyerScraper()
        
        # Gemini AI Yapay Zeka Analiz İstemcisi
        gemini_key = self.config.get("gemini_api_key", "")
        self.gemini = GeminiAnalyzer(api_key=gemini_key)

        self.last_check_time: Optional[datetime] = None
        self.total_notifications_sent: int = 0
        self.is_running: bool = False

    def _load_config(self) -> Dict[str, Any]:
        """
        config_iskur.json dosyasını okur ve ortam değişkeni (environment variable)
        ile verilen gizli değerleri üzerine uygular.

        Ortam değişkenleri sayesinde Telegram token'ı ve Gemini API anahtarı
        repoda/sunucuda düz metin olarak tutulmak zorunda kalmaz:
            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ADMIN_CHAT_ID, GEMINI_API_KEY
        """
        self._env_provided_keys: Set[str] = set()

        if not os.path.exists(self.CONFIG_FILE):
            config: Dict[str, Any] = {
                "telegram_bot_token": "",
                "telegram_chat_id": "",
                "admin_chat_id": "",
                "gemini_api_key": "",
                "enable_sbb_public_portal": True,
                "enable_memurlar_portal": True,
                "enable_kariyer_portal": True,
                "city_code": "",
                "city_name": "Tüm Türkiye",
                "isyeri_turu": "kamu",
                "keyword": "",
                "check_interval_seconds": 180,
                "enable_telegram_notifications": True,
                "session_cookies": {
                    "ASP.NET_SessionId": "",
                    "iskur_cookie": ""
                }
            }
            try:
                with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
            except Exception as err:
                logger.warning(f"Varsayılan config dosyası oluşturulamadı: {err}")
        else:
            try:
                with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception as err:
                logger.error(f"Config dosyası okunamadı: {err}")
                config = {}

        # 🔐 Ortam değişkenleri dosyadaki değerleri geçersiz kılar (güvenli dağıtım için)
        for env_name, config_key in self.ENV_CONFIG_MAP.items():
            env_value = os.environ.get(env_name, "").strip()
            if env_value:
                config[config_key] = env_value
                self._env_provided_keys.add(config_key)

        return config

    def _save_config(self) -> None:
        """
        Gelen konfigürasyon değişikliklerini kaydeder.

        Ortam değişkeninden gelen gizli değerler (token, API anahtarı) diske
        YAZILMAZ; böylece secret'lar dosyada düz metin olarak birikmez.
        """
        try:
            data = dict(self.config)
            for key in getattr(self, "_env_provided_keys", set()):
                data[key] = ""
            with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as err:
            logger.error(f"Config kaydedilirken hata: {err}")

    def _load_seen_jobs(self) -> Set[str]:
        """
        Daha önce görülen ilan numaralarının saklandığı JSON dosyasını okur.
        """
        if not os.path.exists(self.SEEN_JOBS_FILE):
            return set()

        try:
            with open(self.SEEN_JOBS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("seen_ids", []))
        except Exception as err:
            logger.error(f"Görülen ilanlar dosyası okunamadı: {err}")
            return set()

    def _save_seen_jobs(self) -> None:
        """
        Görülen ilan numaralarını kayıt eder.

        ÖNEMLİ (depo şişmesini önler):
        - ID listesi deterministik olarak SIRALANIR. Python `set` sırası her
          çalıştırmada farklı olduğu için sıralanmadığında git'te binlerce
          satırlık sahte fark oluşuyor ve depo gereksiz yere büyüyordu.
        - İçerik (ilan ID kümesi) değişmediyse dosya hiç yazılmaz; böylece
          yeni ilan yokken boşuna commit üretilmez.
        """
        try:
            new_ids = sorted(self.seen_jobs)

            # ID kümesi değişmediyse dosyaya dokunma (gereksiz commit olmasın)
            if os.path.exists(self.SEEN_JOBS_FILE):
                try:
                    with open(self.SEEN_JOBS_FILE, "r", encoding="utf-8") as f:
                        old_ids = json.load(f).get("seen_ids", [])
                    if sorted(old_ids) == new_ids:
                        return
                except Exception:
                    pass  # Bozuk/eksik dosya varsa aşağıda yeniden yazılır

            with open(self.SEEN_JOBS_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {"seen_ids": new_ids, "last_update": datetime.now().isoformat()},
                    f, ensure_ascii=False, indent=2
                )
        except Exception as err:
            logger.error(f"Görülen ilanlar kaydedilirken hata: {err}")

    def _load_last_update_id(self) -> int:
        """
        Telegram getUpdates için son okunan update_id değerini dosyadan yükler.
        """
        if not os.path.exists(self.LAST_UPDATE_FILE):
            return 0
        try:
            with open(self.LAST_UPDATE_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                return int(content) if content else 0
        except Exception as err:
            logger.error(f"Son update_id okunamadı: {err}")
            return 0

    def _save_last_update_id(self, update_id: int) -> None:
        """
        Telegram getUpdates son işlenen update_id değerini dosyaya kaydeder.
        """
        try:
            with open(self.LAST_UPDATE_FILE, "w", encoding="utf-8") as f:
                f.write(str(update_id))
        except Exception as err:
            logger.error(f"Son update_id kaydedilirken hata: {err}")

    def get_sticky_menu_keyboard(self) -> Dict[str, Any]:
        """
        Telegram sohbet ekranının altında sürekli duracak Sabit (Sticky) klavye butonları.
        """
        return {
            "keyboard": [
                [{"text": "🔍 Anlık İlan Tara"}, {"text": "📋 Son İlanlar"}],
                [{"text": "🏙️ İl Filtresi"}, {"text": "🏢 Sektör Filtresi"}],
                [{"text": "⚙️ Mevcut Ayarlar"}, {"text": "👥 Kullanıcılar"}]
            ],
            "resize_keyboard": True,
            "is_persistent": True
        }

    def edit_telegram_message(self, chat_id: str, message_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None) -> None:
        """
        Mevcut Telegram mesajının metnini ve inline butonlarını yerinde (in-place) günceller.
        """
        token = self.config.get("telegram_bot_token", "")
        if not token:
            return
        try:
            url = f"https://api.telegram.org/bot{token}/editMessageText"
            payload = {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            if reply_markup is not None:
                payload["reply_markup"] = reply_markup
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code != 200:
                logger.warning(f"editMessageText HTML hatası ({resp.status_code}): {resp.text}")
                payload["text"] = re.sub(r'<[^>]+>', '', text)
                payload.pop("parse_mode", None)
                requests.post(url, json=payload, timeout=10)
        except Exception as err:
            logger.error(f"editMessageText hatası: {err}")

    def get_city_menu_text(self, region: str = "main") -> str:
        """
        Şehir menüsü açıklama metnini üretir.
        """
        selected = self.config.get("selected_cities", [])
        if not selected:
            sel_str = "🇹🇷 Tüm Türkiye (Kısıtlama Yok)"
        else:
            names = [TURKEY_CITIES.get(c, c) for c in selected]
            if len(names) <= 4:
                sel_str = f"{', '.join(names)} ({len(names)} Şehir Seçili)"
            else:
                sel_str = f"{', '.join(names[:3])} ve {len(names)-3} il daha ({len(names)} Şehir)"

        if region == "main":
            return (
                f"🏙️ <b>İl ve Bölge Filtresi Seçimi</b>\n\n"
                f"📌 <b>Aktif Seçim:</b> {sel_str}\n\n"
                f"Aşağıdaki popüler illere veya bölge butonlarına dokunarak 81 il arasından istediğiniz kadar ili çoklu seçebilirsiniz:"
            )

        reg_title = REGION_CITIES.get(region, {}).get("title", "Bölge Şehirleri")
        return (
            f"<b>{reg_title}</b>\n\n"
            f"📌 <b>Aktif Seçim:</b> {sel_str}\n\n"
            f"Seçmek/Çıkarmak istediğiniz ile dokunun (Yeşil tık ✅ seçili illeri gösterir):"
        )

    def get_city_menu_markup(self, current_region: str = "main") -> Dict[str, Any]:
        """
        81 ili kapsayan interaktif ve çoklu seçimli Inline Keyboard menüsü üretir.
        """
        selected_cities = set(self.config.get("selected_cities", []))

        if current_region == "main":
            pop_cities = [("59", "Tekirdağ"), ("34", "İstanbul"), ("6", "Ankara"), ("35", "İzmir"), ("16", "Bursa"), ("41", "Kocaeli")]
            pop_buttons = []
            for code, name in pop_cities:
                mark = "✅" if code in selected_cities else "📍"
                pop_buttons.append({"text": f"{mark} {name} ({code})", "callback_data": f"city_toggle_{code}_main"})
            
            pop_rows = [pop_buttons[i:i+2] for i in range(0, len(pop_buttons), 2)]

            keyboard = [
                [{"text": "🇹🇷 TÜM TÜRKİYE (Seçimi Sıfırla)", "callback_data": "city_reset_all"}],
                *pop_rows,
                [{"text": "🌊 Marmara", "callback_data": "city_reg_marmara"}, {"text": "⛰️ İç Anadolu", "callback_data": "city_reg_ic_anadolu"}],
                [{"text": "🌅 Ege", "callback_data": "city_reg_ege"}, {"text": "🌴 Akdeniz", "callback_data": "city_reg_akdeniz"}],
                [{"text": "🌲 Karadeniz", "callback_data": "city_reg_karadeniz"}, {"text": "🏔️ Doğu Anadolu", "callback_data": "city_reg_dogu"}],
                [{"text": "🏜️ Güneydoğu Anadolu", "callback_data": "city_reg_guneydogu"}],
                [{"text": f"💾 SEÇİMİ KAYDET ({len(selected_cities)} Şehir Seçili)", "callback_data": "city_apply"}]
            ]
            return {"inline_keyboard": keyboard}

        reg_info = REGION_CITIES.get(current_region, {})
        codes = reg_info.get("codes", [])
        city_buttons = []

        for code in codes:
            name = TURKEY_CITIES.get(code, code)
            mark = "✅" if code in selected_cities else "📍"
            city_buttons.append({"text": f"{mark} {name} ({code})", "callback_data": f"city_toggle_{code}_{current_region}"})

        rows = [city_buttons[i:i+2] for i in range(0, len(city_buttons), 2)]

        keyboard = [
            *rows,
            [{"text": "🔙 Ana Bölge Menüsüne Dön", "callback_data": "city_reg_main"}],
            [{"text": f"💾 SEÇİMİ KAYDET ({len(selected_cities)} Şehir Seçili)", "callback_data": "city_apply"}]
        ]
        return {"inline_keyboard": keyboard}

    def send_telegram_message(self, text: str, target_chat_id: Optional[str] = None, include_keyboard: bool = True, reply_markup: Optional[Dict[str, Any]] = None) -> bool:
        """
        Telegram Bot API üzerinden mesaj gönderir. 
        Kullanıcı belirtilmemişse tüm yetkili kişilere iletir.
        """
        token = self.config.get("telegram_bot_token", "")
        if not token:
            logger.warning("Telegram Bot Token henüz ayarlanmamış.")
            return False

        # Hedef sohbet kimliklerini belirle
        target_ids = []
        if target_chat_id:
            target_ids = [str(target_chat_id)]
        else:
            # Tüm yetkili kullanıcıları ve Admin'i al
            admin_id = str(self.config.get("admin_chat_id", ""))
            users = self.db.get_all_users()
            user_ids = [str(u["telegram_id"]) for u in users]
            if admin_id and admin_id not in user_ids:
                user_ids.append(admin_id)
            target_ids = user_ids if user_ids else [str(self.config.get("telegram_chat_id", ""))]

        # Telegram 3800 karakter sınırlama parçalaması
        chunks = []
        if len(text) > 3800:
            parts = text.split("\n\n")
            current_chunk = ""
            for part in parts:
                if len(current_chunk) + len(part) + 2 > 3800:
                    chunks.append(current_chunk)
                    current_chunk = part
                else:
                    current_chunk += ("\n\n" + part if current_chunk else part)
            if current_chunk:
                chunks.append(current_chunk)
        else:
            chunks = [text]

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        overall_success = True

        for c_id in target_ids:
            if not c_id:
                continue

            for chunk in chunks:
                payload = {
                    "chat_id": c_id,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False
                }
                if reply_markup is not None:
                    payload["reply_markup"] = reply_markup
                elif include_keyboard:
                    payload["reply_markup"] = self.get_sticky_menu_keyboard()

                try:
                    resp = requests.post(url, json=payload, timeout=10)
                    if resp.status_code != 200:
                        # Düz metin fallback: HTML etiketlerini temizleyip kullanıcıya ilet
                        logger.warning(f"Telegram parse_mode hatası ({resp.status_code}): {resp.text}")
                        payload["text"] = re.sub(r'<[^>]+>', '', chunk)
                        payload.pop("parse_mode", None)
                        requests.post(url, json=payload, timeout=10)
                except Exception as err:
                    logger.error(f"Telegram mesaj gönderme hatası ({c_id}): {err}")
                    overall_success = False

        return overall_success

    def check_for_new_jobs(self, is_initial_run: bool = False) -> List[Dict[str, Any]]:
        """
        İŞKUR ve SBB Kamu İlan Portallarını tarar, MÜKERRER OLMAYAN yeni ilanları tespit eder.
        """
        self.last_check_time = datetime.now()
        city_code = self.config.get("city_code", "")
        isyeri_turu = self.config.get("isyeri_turu", "kamu")
        keyword = self.config.get("keyword", "")

        logger.info(f"Çoklu Kaynak İlan Taraması Başlatılıyor... (Saat: {self.last_check_time.strftime('%H:%M:%S')})")
        
        all_jobs: List[Dict[str, Any]] = []
        selected_cities = self.config.get("selected_cities", [])
        city_codes = selected_cities if selected_cities else ([city_code] if city_code else [])

        # 1. İŞKUR İlan Taraması
        iskur_jobs = self.scraper.search_jobs(city_code=city_code, isyeri_turu=isyeri_turu, keyword=keyword, city_codes=city_codes)
        for j in iskur_jobs:
            j["source"] = "İŞKUR e-Şube"
            all_jobs.append(j)

        # 2. SBB Resmi Kamu İlan Portalı Taraması (Kamu veya Tümü seçiliyse)
        if isyeri_turu in ["kamu", "tumu"] and self.config.get("enable_sbb_public_portal", True):
            try:
                sbb_jobs = self.sbb_scraper.fetch_public_jobs()
                all_jobs.extend(sbb_jobs)
            except Exception as err:
                logger.error(f"SBB taraması sırasında hata: {err}")

        # 3. Memurlar.net Resmi Memur & Kamu İlanları Taraması (Kamu veya Tümü seçiliyse)
        if isyeri_turu in ["kamu", "tumu"] and self.config.get("enable_memurlar_portal", False):
            try:
                memurlar_jobs = self.memurlar_scraper.fetch_public_jobs()
                all_jobs.extend(memurlar_jobs)
            except Exception as err:
                logger.error(f"Memurlar.net taraması sırasında hata: {err}")

        # 4. Kariyer.net Özel Sektör ve Kurumsal İlan Taraması (Özel veya Tümü seçiliyse)
        if isyeri_turu in ["ozel", "tumu"] and self.config.get("enable_kariyer_portal", False):
            try:
                selected_city_names = [TURKEY_CITIES.get(c, c) for c in selected_cities] if selected_cities else None
                kariyer_jobs = self.kariyer_scraper.search_jobs(city_names=selected_city_names, keyword=keyword)
                all_jobs.extend(kariyer_jobs)
            except Exception as err:
                logger.error(f"Kariyer.net taraması sırasında hata: {err}")

        if not all_jobs:
            logger.info("Tarama tamamlandı: Yeni ilan bulunamadı.")
            return []

        new_jobs: List[Dict[str, Any]] = []

        for job in all_jobs:
            job_no = job["job_no"]
            # 🚨 KESİN MÜKERRER KONTROLÜ: Hem JSON hem SQLite tablosunda yoksa ekle
            if job_no not in self.seen_jobs and not self.db.is_job_seen(job_no):
                new_jobs.append(job)
                self.seen_jobs.add(job_no)

        self._save_seen_jobs()

        if new_jobs:
            logger.info(f"🎉 Toplam {len(new_jobs)} adet YENİ (Mükerrer Olmayan) ilan tespit edildi!")

            if is_initial_run and len(new_jobs) > 5:
                active_portals = ["İŞKUR e-Şube"]
                if self.config.get("enable_sbb_public_portal", True):
                    active_portals.append("SBB Kamu İlan")
                if self.config.get("enable_memurlar_portal", False):
                    active_portals.append("Memurlar.net")
                if self.config.get("enable_kariyer_portal", False):
                    active_portals.append("Kariyer.net")
                portals_str = ", ".join(active_portals)

                summary_msg = (
                    f"🟢 <b>İlan Takip Botu Aktif!</b>\n\n"
                    f"📍 <b>Kapsam:</b> {self.config.get('city_name', 'Tüm Türkiye')}\n"
                    f"🏢 <b>Sektör Türü:</b> {isyeri_turu.upper()}\n"
                    f"🌐 <b>Aktif Portallar:</b> {portals_str}\n"
                    f"🤖 <b>Gemini AI Analizi:</b> AKTİF ⚡\n"
                    f"🔍 <b>Toplam Mevcut İlan:</b> {len(all_jobs)} adet tespit edildi.\n"
                    f"⚡ Bot 7/24 çalışıyor. Yeni bir ilan düştüğünde Gemini AI analizi ile birlikte buraya gelecek!"
                )
                self.send_telegram_message(summary_msg)
            else:
                # Çok sayıda yeni ilan varsa (ör. kapsam değişikliği sonrası ilk tarama)
                # hepsini tek bir özet mesajda göster. Aksi halde ilk 10 ilan için
                # ayrı ayrı (Gemini AI analizli) bildirim gönderilir.
                if len(new_jobs) > 10:
                    digest = ["🗂️ <b>Toplu Yeni İlan Özeti</b>",
                              f"Toplam <b>{len(new_jobs)}</b> yeni ilan bulundu.\n"]
                    for idx, j in enumerate(new_jobs[:40], start=1):
                        digest.append(
                            f"{idx}. <b>{j.get('title', '')}</b>\n"
                            f"   📍 {j.get('location', '')} | ⏳ {j.get('deadline', '')}\n"
                            f"   🔗 {j.get('detail_url', '')}"
                        )
                    if len(new_jobs) > 40:
                        digest.append(f"\n… ve {len(new_jobs) - 40} ilan daha.")
                    digest.append("\n⬇️ En güncel 10 ilan için ayrıntılı AI analizi aşağıda:")
                    self.send_telegram_message("\n".join(digest))

                for job in new_jobs[:10]:
                    try:
                        self._send_job_notification(job)
                        self.total_notifications_sent += 1
                    except Exception as err:
                        logger.error(f"İlan bildirimi gönderilirken hata ({job.get('job_no')}): {err}", exc_info=True)
        else:
            logger.info("Yeni eklenen ilan bulunmuyor (Tüm ilanlar zaten veritabanında mevcut).")

        return new_jobs

    def _send_job_notification(self, job: Dict[str, Any]) -> None:
        """
        Tekil bir iş/memur ilanı için Gemini AI analizi üreterek Telegram bildirimi gönderir.
        """
        source = job.get("source", "Resmi Portal")
        job_no = job.get("job_no", "")
        title = job.get("title", "")
        location = job.get("location", "")
        deadline = job.get("deadline", "")
        detail_url = job.get("detail_url", "")

        description = ""
        education = "Belirtilmedi"

        if "İŞKUR" in source:
            detail = self.scraper.get_job_detail(job_no)
            if detail:
                education = detail.get("education", "Belirtilmedi")
                description = detail.get("description", "")
        elif "Memurlar" in source:
            detail = self.memurlar_scraper.get_job_detail(job_no)
            if detail:
                description = detail.get("description", title)
            else:
                description = title
        elif "Kariyer" in source:
            description = job.get("description", title)
        else:
            description = title

        # Başlıktaki bitişik tarih/sayıları düzelt (Örn: ALACAK4 Ekim -> ALACAK | 4 Ekim)
        clean_title = re.sub(r'([a-zA-ZÇĞİÖŞÜçğıöşü])(\d{1,2}\s+[a-zA-ZÇĞİÖŞÜçğıöşü]+)', r'\1 | \2', title)

        # SQLite veritabanına kesin kaydet
        full_job_data = {
            "job_no": job_no,
            "title": clean_title,
            "location": location,
            "education": education,
            "deadline": deadline,
            "source": source,
            "description": description,
            "detail_url": detail_url
        }
        self.db.save_job(full_job_data)

        # Gemini AI Yapay Zeka Analizi Üret
        logger.info(f"Gemini AI Analizi Yapılıyor: {clean_title[:30]}...")
        ai_analysis = self.gemini.analyze_job(
            title=clean_title,
            location=location,
            education=education,
            raw_description=description,
            source=source
        )

        # Telegram HTML için dinamik alanları güvenli hale getir
        safe_title = escape_html(clean_title)
        safe_source = escape_html(source)
        safe_location = escape_html(location)
        safe_education = escape_html(education)
        safe_deadline = escape_html(deadline)

        message = (
            f"🚨 <b>YENİ RESMİ MEMUR / İŞ İLANI DÜŞTÜ!</b> 🚨\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📌 <b>İlan ID:</b> <code>{job_no}</code>\n"
            f"🏛️ <b>Kaynak:</b> {safe_source}\n\n"
            f"💼 <b>Pozisyon / İlan:</b>\n<b>{safe_title}</b>\n\n"
            f"📍 <b>Çalışma Yeri:</b> {safe_location}\n"
            f"🎓 <b>Öğrenim Şartı:</b> {safe_education}\n"
            f"⏳ <b>Son Başvuru Tarihi:</b> {safe_deadline}\n"
        )

        if ai_analysis:
            message += f"\n🤖 <b>GEMİNİ AI SATIR ARASI ANALİZİ</b>\n\n{ai_analysis}\n"

        message += (
            f"\n─────────────────────────\n"
            f"💬 <i>Soru sormak için bu mesaja yanıt verin (Reply) veya <code>/soru {job_no} Sorunuz</code> yazın.</i>\n\n"
            f"🔗 <a href='{detail_url}'><b>Resmi İlanı İncele ve Başvur</b></a>"
        )
        self.send_telegram_message(message)

    def _answer_callback_query(self, token: str, callback_query_id: str, text: str = "") -> None:
        """
        Telegram inline buton tıklamalarına bildirim yanıtı gönderir.
        """
        try:
            url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
            requests.post(url, json={"callback_query_id": callback_query_id, "text": text, "show_alert": False}, timeout=5)
        except Exception as err:
            logger.error(f"answerCallbackQuery hatası: {err}")

    def process_telegram_interactive_messages(self) -> None:
        """
        Telegram mesajlarını, komutları, buton etkileşimlerini ve yetkilendirmeyi yönetir.
        """
        token = self.config.get("telegram_bot_token", "")
        admin_id = str(self.config.get("admin_chat_id", ""))
        if not token:
            return

        try:
            offset = (self._last_update_id + 1) if self._last_update_id > 0 else None
            params = {"timeout": 2}
            if offset:
                params["offset"] = offset

            url = f"https://api.telegram.org/bot{token}/getUpdates"
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code != 200:
                return

            updates = resp.json().get("result", [])
            for upd in updates:
                upd_id = upd.get("update_id")
                if not upd_id:
                    continue

                if upd_id > self._last_update_id:
                    self._last_update_id = upd_id
                    self._save_last_update_id(upd_id)

                # 🚨 ATOMİK MÜKERRER MESAJ ENGELLEME KONTROLÜ:
                # Birden fazla bot örneği çalışsa dahi, aynı update_id sadece TEK BİR bot tarafından işlenebilir!
                if not self.db.mark_update_processed(upd_id):
                    logger.info(f"🛡️ Update ID {upd_id} diğer bot örneği tarafından zaten işlendi, atlanıyor.")
                    continue

                # 🔘 1. CALLBACK QUERY (INLINE BUTON TIKLAMALARI)
                cb = upd.get("callback_query")
                if cb:
                    cb_id = cb.get("id")
                    cb_data = cb.get("data", "")
                    sender_id = str(cb.get("from", {}).get("id", ""))
                    sender_name = cb.get("from", {}).get("first_name", "Kullanıcı")

                    if not self.db.is_user_authorized(sender_id, admin_id=admin_id):
                        self._answer_callback_query(token, cb_id, "⛔ Yetkisiz erişim!")
                        continue

                    if cb_data.startswith("city_toggle_"):
                        parts = cb_data.replace("city_toggle_", "").split("_")
                        code = parts[0]
                        reg = parts[1] if len(parts) > 1 else "main"

                        selected = set(self.config.get("selected_cities", []))
                        if code in selected:
                            selected.remove(code)
                        else:
                            selected.add(code)

                        self.config["selected_cities"] = list(selected)
                        self._save_config()

                        c_name = TURKEY_CITIES.get(code, code)
                        status_str = "eklendi" if code in selected else "çıkarıldı"
                        self._answer_callback_query(token, cb_id, f"{c_name} {status_str}.")

                        cb_msg = cb.get("message", {})
                        if cb_msg:
                            m_id = cb_msg.get("message_id")
                            c_id = cb_msg.get("chat", {}).get("id")
                            menu_txt = self.get_city_menu_text(reg)
                            markup = self.get_city_menu_markup(reg)
                            self.edit_telegram_message(str(c_id), m_id, menu_txt, reply_markup=markup)

                    elif cb_data.startswith("city_reg_"):
                        reg = cb_data.replace("city_reg_", "")
                        self._answer_callback_query(token, cb_id)
                        cb_msg = cb.get("message", {})
                        if cb_msg:
                            m_id = cb_msg.get("message_id")
                            c_id = cb_msg.get("chat", {}).get("id")
                            menu_txt = self.get_city_menu_text(reg)
                            markup = self.get_city_menu_markup(reg)
                            self.edit_telegram_message(str(c_id), m_id, menu_txt, reply_markup=markup)

                    elif cb_data == "city_reset_all":
                        self.config["selected_cities"] = []
                        self.config["city_code"] = ""
                        self.config["city_name"] = "Tüm Türkiye"
                        self._save_config()
                        self._answer_callback_query(token, cb_id, "🇹🇷 Tüm Türkiye olarak sıfırlandı!")
                        cb_msg = cb.get("message", {})
                        if cb_msg:
                            m_id = cb_msg.get("message_id")
                            c_id = cb_msg.get("chat", {}).get("id")
                            menu_txt = self.get_city_menu_text("main")
                            markup = self.get_city_menu_markup("main")
                            self.edit_telegram_message(str(c_id), m_id, menu_txt, reply_markup=markup)

                    elif cb_data == "city_apply":
                        selected = self.config.get("selected_cities", [])
                        if not selected:
                            c_str = "Tüm Türkiye"
                            self.config["city_name"] = c_str
                            self.config["city_code"] = ""
                        else:
                            names = [TURKEY_CITIES.get(c, c) for c in selected]
                            if len(names) <= 3:
                                c_str = ", ".join(names)
                            else:
                                c_str = f"{', '.join(names[:3])} ve {len(names)-3} il daha ({len(names)} Şehir)"
                            self.config["city_name"] = c_str
                            self.config["city_code"] = selected[0]
                        self._save_config()
                        self._answer_callback_query(token, cb_id, "✅ Seçim kaydedildi!")
                        self.send_telegram_message(f"✅ İlan arama şehirleri <b>{self.config['city_name']}</b> olarak kaydedildi ve uygulandı!", target_chat_id=sender_id)

                    elif cb_data.startswith("set_sec_"):
                        sec = cb_data.replace("set_sec_", "").strip().lower()
                        if sec in ["kamu", "ozel", "tumu"]:
                            sec_title = {"kamu": "Sadece Kamu İlanları", "ozel": "Özel Sektör İlanları", "tumu": "Kamu + Özel Sektör"}.get(sec, sec.upper())
                            self.config["isyeri_turu"] = sec
                            self._save_config()

                            self._answer_callback_query(token, cb_id, f"✅ Sektör {sec_title} olarak seçildi!")
                            self.send_telegram_message(f"✅ Sektör filtresi <b>{sec_title}</b> olarak değiştirildi!", target_chat_id=sender_id)

                    continue

                msg = upd.get("message")
                if not msg:
                    continue

                sender_id = str(msg.get("from", {}).get("id", ""))
                sender_name = msg.get("from", {}).get("first_name", "Kullanıcı")
                text = msg.get("text", "").strip()

                # 🛡️ YETKİLENDİRME KONTROLÜ
                if not self.db.is_user_authorized(sender_id, admin_id=admin_id):
                    logger.warning(f"Yetkisiz Erişim Denemesi! ID: {sender_id} - İsim: {sender_name}")
                    unauth_msg = (
                        f"⛔ <b>YETKİSİZ ERİŞİM!</b>\n\n"
                        f"Bu sisteme erişim yetkiniz bulunmamaktadır.\n"
                        f"Lütfen sistem yöneticisine Telegram ID'nizi ileterek yetki isteyin.\n\n"
                        f"📌 <b>Sizin Telegram ID'niz:</b> <code>{sender_id}</code>"
                    )
                    self.send_telegram_message(unauth_msg, target_chat_id=sender_id, include_keyboard=False)
                    continue

                # 📌 1. STICKY MENÜ BUTONLARI & KOMUTLAR
                il_cmd_match = re.match(r"^/il(?:@\w+)?\s+(\d+)", text, re.IGNORECASE)
                sektor_cmd_match = re.match(r"^/sektor(?:@\w+)?\s+(\w+)", text, re.IGNORECASE)
                ekle_cmd_match = re.match(r"^/ekle(?:@\w+)?\s+(\d+)\s+(.+)", text, re.IGNORECASE)
                sil_cmd_match = re.match(r"^/sil(?:@\w+)?\s+(\d+)", text, re.IGNORECASE)
                kullanicilar_cmd_match = re.match(r"^/kullanicilar(?:@\w+)?", text, re.IGNORECASE) or ("kullanıcılar" in text.lower() or "kullanicilar" in text.lower())

                if text.startswith("/start") or "Mevcut Ayarlar" in text or "Ayarlar" in text:
                    c_name = self.config.get("city_name", "Tüm Türkiye")
                    sec_map = {"kamu": "🏛️ Sadece Kamu İlanları", "ozel": "🏢 Özel Sektör İlanları", "tumu": "🌐 Kamu + Özel Sektör"}
                    i_turu_str = sec_map.get(self.config.get("isyeri_turu", "kamu").lower(), "🏛️ Kamu")
                    sel_cities = self.config.get("selected_cities", [])
                    city_count_str = f"({len(sel_cities)} İl Seçili)" if sel_cities else "(Tüm Türkiye)"

                    active_portals = ["💼 İŞKUR e-Şube"]
                    if self.config.get("enable_sbb_public_portal", True):
                        active_portals.append("🏛️ SBB Kamu İlan")
                    if self.config.get("enable_memurlar_portal", False):
                        active_portals.append("📰 Memurlar.net")
                    if self.config.get("enable_kariyer_portal", False):
                        active_portals.append("🏢 Kariyer.net")
                    portals_str = ", ".join(active_portals)

                    status_msg = (
                        f"🤖 <b>İŞKUR & SBB Resmi Memur İlan Takip Botu</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"👤 <b>Kullanıcı:</b> {sender_name}\n"
                        f"🆔 <b>Telegram ID:</b> <code>{sender_id}</code>\n"
                        f"📍 <b>İl Filtresi:</b> {c_name} <i>{city_count_str}</i>\n"
                        f"🏢 <b>Sektör:</b> {i_turu_str}\n"
                        f"🌐 <b>Aktif Portallar:</b> {portals_str}\n"
                        f"🧠 <b>Yapay Zeka (Gemini AI):</b> Aktif ⚡\n"
                        f"👑 <b>Sistem Yöneticisi:</b> <code>{admin_id}</code>\n\n"
                        f"👇 <i>Aşağıdaki sabit menü butonlarını kullanarak dilediğiniz işlemi anında gerçekleştirebilirsiniz:</i>"
                    )
                    self.send_telegram_message(status_msg, target_chat_id=sender_id)

                elif "Anlık İlan Tara" in text or "İlan Tara" in text or text.startswith("/tara"):
                    self.send_telegram_message(
                        "🔍 <b>İŞKUR ve SBB Portalları Taranıyor...</b>\n\n"
                        "⏳ <i>Lütfen bekleyin, güncel resmi kamu ilanları sorgulanıyor...</i>",
                        target_chat_id=sender_id
                    )
                    new_j = self.check_for_new_jobs(is_initial_run=False)
                    if not new_j:
                        self.send_telegram_message(
                            "✅ <b>Tarama Tamamlandı</b>\n\n"
                            "ℹ️ Şu an için kriterlerinize uygun yeni eklenen mükerrer olmayan bir ilan bulunamadı.\n"
                            "Tüm portallar güncel ve 7/24 takiptedir!",
                            target_chat_id=sender_id
                        )

                elif "Son İlanlar" in text or text.startswith("/son"):
                    recent = self.db.get_recent_jobs(5)
                    if recent:
                        rec_msg = "📋 <b>Sistemdeki En Son 5 Resmi İlan:</b>\n"
                        rec_msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
                        for idx, r_job in enumerate(recent, 1):
                            src_badge = "🏛️ SBB" if "SBB" in r_job.get("source", "") else "💼 İŞKUR"
                            deadline_str = r_job.get('deadline') or 'Belirtilmedi'
                            rec_msg += (
                                f"<b>{idx}. {r_job['title']}</b>\n"
                                f"   {src_badge} | 📍 {r_job['location']} | ⏳ {deadline_str}\n"
                                f"   🆔 İlan No: <code>{r_job['job_no']}</code>\n\n"
                            )
                        rec_msg += "💡 <i>Bir ilan hakkında soru sormak için: <code>/soru [İlan_No] [Sorunuz]</code> yazabilirsiniz.</i>"
                        self.send_telegram_message(rec_msg, target_chat_id=sender_id)
                    else:
                        self.send_telegram_message("ℹ️ Henüz veritabanında kayıtlı ilan bulunmuyor.", target_chat_id=sender_id)

                elif "İl Filtresi" in text or text == "/il" or text.startswith("/il@"):
                    city_menu = self.get_city_menu_text("main")
                    city_markup = self.get_city_menu_markup("main")
                    self.send_telegram_message(city_menu, target_chat_id=sender_id, reply_markup=city_markup)

                elif il_cmd_match:
                    code = il_cmd_match.group(1).strip()
                    c_name = TURKEY_CITIES.get(code, f"İl Kodu: {code}")
                    if code == "0":
                        self.config["selected_cities"] = []
                        self.config["city_code"] = ""
                        self.config["city_name"] = "Tüm Türkiye"
                    else:
                        selected = set(self.config.get("selected_cities", []))
                        selected.add(code)
                        self.config["selected_cities"] = list(selected)
                        self.config["city_code"] = code
                        names = [TURKEY_CITIES.get(c, c) for c in selected]
                        self.config["city_name"] = ", ".join(names[:3]) + (f" ({len(names)} Şehir)" if len(names) > 3 else "")
                    self._save_config()
                    self.send_telegram_message(f"✅ İlan arama şehri <b>{self.config['city_name']}</b> olarak güncellendi!", target_chat_id=sender_id)

                elif "Sektör Filtresi" in text or text == "/sektor" or text.startswith("/sektor@"):
                    sec_markup = {
                        "inline_keyboard": [
                            [{"text": "🏛️ Sadece Kamu İlanları", "callback_data": "set_sec_kamu"}],
                            [{"text": "🏢 Özel Sektör İlanları", "callback_data": "set_sec_ozel"}],
                            [{"text": "🌐 Kamu + Özel Sektör (Tümü)", "callback_data": "set_sec_tumu"}]
                        ]
                    }
                    sec_menu = (
                        f"🏢 <b>Sektör Filtresi Değiştirme</b>\n\n"
                        f"📌 <b>Mevcut Seçim:</b> {self.config.get('isyeri_turu', 'kamu').upper()}\n\n"
                        f"Aşağıdaki butonlara dokunarak aramak istediğiniz sektör türünü anında seçebilirsiniz:"
                    )
                    self.send_telegram_message(sec_menu, target_chat_id=sender_id, reply_markup=sec_markup)

                elif sektor_cmd_match:
                    sec = sektor_cmd_match.group(1).strip().lower()
                    if sec in ["kamu", "ozel", "tumu"]:
                        self.config["isyeri_turu"] = sec
                        self._save_config()
                        self.send_telegram_message(f"✅ Sektör filtresi <b>{sec.upper()}</b> olarak değiştirildi!", target_chat_id=sender_id)

                # 👑 ADMIN KOMUTLARI (/ekle, /sil, /kullanicilar)
                elif ekle_cmd_match:
                    if sender_id != admin_id:
                        self.send_telegram_message("⛔ <b>Yetkisiz İşlem:</b> Bu komut sadece Sistem Yöneticisi (Admin) tarafından kullanılabilir.", target_chat_id=sender_id)
                    else:
                        target_id = ekle_cmd_match.group(1).strip()
                        target_name = ekle_cmd_match.group(2).strip()
                        if self.db.add_user(target_id, target_name):
                            self.send_telegram_message(
                                f"✅ <b>Kullanıcı Başarıyla Yetkilendirildi!</b>\n\n"
                                f"👤 <b>İsim:</b> {target_name}\n"
                                f"🆔 <b>Telegram ID:</b> <code>{target_id}</code>\n"
                                f"🛡️ <b>Rol:</b> Yetkili Kullanıcı",
                                target_chat_id=sender_id
                            )
                            welcome = (
                                f"🎉 <b>Tebrikler {target_name}!</b>\n\n"
                                f"Sistem Yöneticisi tarafından İŞKUR & SBB Resmi İlan Takip Botuna erişim yetkiniz tanımlandı.\n"
                                f"Artık tüm resmi memur ve kamu iş ilanlarını anlık takip edebilirsiniz!"
                            )
                            self.send_telegram_message(welcome, target_chat_id=target_id)

                elif text.startswith("/ekle"):
                    if sender_id != admin_id:
                        self.send_telegram_message("⛔ <b>Yetkisiz İşlem:</b> Bu komut sadece Sistem Yöneticisi (Admin) tarafından kullanılabilir.", target_chat_id=sender_id)
                    else:
                        self.send_telegram_message(
                            "➕ <b>Yetkili Kullanıcı Ekleme</b>\n\n"
                            "📌 <b>Kullanım:</b> <code>/ekle [ID] [İsim]</code>\n"
                            "💡 <b>Örnek:</b> <code>/ekle 123456789 Ahmet Yılmaz</code>\n\n"
                            "<i>Not: Kullanıcının ID öğrenmesi için bota /start yazması yeterlidir.</i>",
                            target_chat_id=sender_id
                        )

                elif sil_cmd_match:
                    if sender_id != admin_id:
                        self.send_telegram_message("⛔ <b>Yetkisiz İşlem:</b> Bu komut sadece Sistem Yöneticisi (Admin) tarafından kullanılabilir.", target_chat_id=sender_id)
                    else:
                        target_id = sil_cmd_match.group(1).strip()
                        if self.db.remove_user(target_id):
                            self.send_telegram_message(
                                f"🗑️ <b>Yetki Silindi!</b>\n\n"
                                f"🆔 ID: <code>{target_id}</code> başarıyla sistemden kaldırıldı.",
                                target_chat_id=sender_id
                            )

                elif text.startswith("/sil"):
                    if sender_id != admin_id:
                        self.send_telegram_message("⛔ <b>Yetkisiz İşlem:</b> Bu komut sadece Sistem Yöneticisi (Admin) tarafından kullanılabilir.", target_chat_id=sender_id)
                    else:
                        self.send_telegram_message(
                            "🗑️ <b>Kullanıcı Yetkisi Kaldırma</b>\n\n"
                            "📌 <b>Kullanım:</b> <code>/sil [ID]</code>\n"
                            "💡 <b>Örnek:</b> <code>/sil 123456789</code>\n\n"
                            "<i>Mevcut kişileri görmek için <b>👥 Kullanıcılar</b> butonuna dokunabilirsiniz.</i>",
                            target_chat_id=sender_id
                        )

                elif kullanicilar_cmd_match:
                    if sender_id != admin_id:
                        self.send_telegram_message("⛔ <b>Yetkisiz İşlem:</b> Bu komut sadece Sistem Yöneticisi (Admin) tarafından kullanılabilir.", target_chat_id=sender_id)
                    else:
                        users = self.db.get_all_users()
                        u_msg = "👥 <b>Kayıtlı Yetkili Kullanıcılar Listesi:</b>\n"
                        u_msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
                        for idx, u in enumerate(users, 1):
                            role_badge = "👑 Yönetici" if u.get('role') == 'admin' else "👤 Yetkili"
                            u_msg += f"{idx}. <b>{u['name']}</b> ({role_badge})\n   🆔 ID: <code>{u['telegram_id']}</code>\n\n"
                        u_msg += "➕ <i>Yeni kişi eklemek için: <code>/ekle [ID] [İsim]</code></i>\n"
                        u_msg += "🗑️ <i>Yetki silmek için: <code>/sil [ID]</code></i>"
                        self.send_telegram_message(u_msg, target_chat_id=sender_id)

                elif text.strip() in ["/soru", "/sor"]:
                    self.send_telegram_message(
                        "❓ <b>Gemini AI İlan Danışmanı</b>\n\n"
                        "Resmi ilanlar hakkında merak ettiğiniz şartları (KPSS puanı, yaş sınırı, ikametgah, mezuniyet şartı vb.) yapay zekaya sorabilirsiniz.\n\n"
                        "📌 <b>Kullanım Yöntemleri:</b>\n"
                        "1. İlgili ilan bildirimini yanıtlayarak (Reply) doğrudan sorunuzu yazın.\n"
                        "2. Veya: <code>/soru [İlan_No] [Sorunuz]</code>\n\n"
                        "💡 <b>Örnek:</b>\n"
                        "<code>/soru 00009844279 Bu ilana önlisans mezunları başvurabilir mi?</code>",
                        target_chat_id=sender_id
                    )

                # ❓ 2. GEMİNİ İLE SORU-CEVAP
                else:
                    reply_to = msg.get("reply_to_message", {})
                    reply_text = reply_to.get("text", "")
                    job_no = None
                    question = None

                    if reply_text:
                        match = re.search(r"\b(0000\d{7}|SBB_\w+)\b", reply_text, re.IGNORECASE)
                        if match:
                            job_no = match.group(1).strip()
                        question = text
                    elif text.startswith("/soru") or text.startswith("/sor"):
                        parts = text.split(maxsplit=2)
                        if len(parts) >= 3:
                            job_no = parts[1].strip()
                            question = parts[2].strip()

                    if not job_no and question and not text.startswith("/"):
                        recent = self.db.get_recent_jobs(1)
                        if recent:
                            job_no = recent[0]["job_no"]

                    if job_no and question:
                        logger.info(f"Soru yanıtlanıyor -> İlan: {job_no}, Soru: '{question}'")
                        job_data = self.db.get_job(job_no)
                        if not job_data:
                            job_data = {"job_no": job_no, "title": f"İlan {job_no}", "description": reply_text or question}

                        answer = self.gemini.ask_question_about_job(job_data, question)
                        reply_msg = (
                            f"🤖 <b>Gemini AI İlan Yanıtı</b> (İlan: <code>{job_no}</code>)\n\n"
                            f"❓ <b>Soru:</b> {question}\n\n"
                            f"💬 <b>Cevap:</b>\n{answer}"
                        )
                        self.send_telegram_message(reply_msg, target_chat_id=sender_id)

        except Exception as err:
            logger.error(f"Telegram etkileşimli mesajlar işlenirken hata: {err}")

    async def run_loop(self) -> None:
        """
        Ana döngü: Telegram mesajlarını canlı dinler ve belirlenen periyotta İŞKUR & SBB portalını tarar.
        """
        self.is_running = True
        interval = int(self.config.get("check_interval_seconds", 180))
        logger.info(f"Bot çalışıyor! Kontrol Periyodu: {interval} saniye ({interval // 60} dakika).")

        self.check_for_new_jobs(is_initial_run=True)
        last_job_check = asyncio.get_event_loop().time()

        while self.is_running:
            try:
                # ⚡ Telegram mesajlarını ve buton etkileşimlerini anında işle
                self.process_telegram_interactive_messages()

                # 🔎 Periyodik ilan kontrolünü çalıştır
                now = asyncio.get_event_loop().time()
                if now - last_job_check >= interval:
                    self.check_for_new_jobs(is_initial_run=False)
                    last_job_check = now

                await asyncio.sleep(2)
            except asyncio.CancelledError:
                logger.info("Bot durduruluyor...")
                self.is_running = False
                break
            except Exception as err:
                logger.error(f"Döngü sırasında beklenmeyen hata: {err}", exc_info=True)
                await asyncio.sleep(5)


def main():
    bot = IskurJobBot()
    try:
        asyncio.run(bot.run_loop())
    except KeyboardInterrupt:
        print("\n[BİLGİ] Bot kullanıcı tarafından durduruldu.")


if __name__ == "__main__":
    main()
