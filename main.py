"""
Zebra Yazıcı Otonom Yönetim Telegram Botu
-----------------------------------------
Bu uygulama, ağ üzerindeki Zebra etiket yazıcılarını Telegram üzerinden otonom
olarak yönetmeyi, durum takibi yapmayı, ZPL formatında test/ayar etiketleri göndermeyi
ve Windows işletim sistemine otomatik yazıcı sürücüsü/portu eklemeyi sağlar.
"""

import asyncio
import json
import os
import socket
import subprocess
import logging
import sys
from typing import Dict, Any, Tuple

# Windows konsol çıktıları için UTF-8 yapılandırması
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Uygulama genelinde kullanılacak loglama yapılandırması
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Yazıcı konfigürasyonlarının saklandığı veritabanı (JSON dosyası)
PRINTERS_FILE = "printers.json"

# Telegram Bot Token Bilgisi (ortam degiskeninden okunur; repoda deger tutulmaz)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")


def load_printers() -> Dict[str, Any]:
    """
    Kaydedilmiş yazıcı verilerini JSON dosyasından güvenli bir şekilde yükler.
    """
    if os.path.exists(PRINTERS_FILE):
        try:
            with open(PRINTERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as err:
            logger.error(f"Yazıcı JSON dosyası okunurken hata oluştu: {err}")
            return {}
    return {}


def save_printers(printers: Dict[str, Any]) -> bool:
    """
    Güncellenmiş yazıcı verilerini JSON dosyasına kalıcı olarak kaydeder.
    """
    try:
        with open(PRINTERS_FILE, "w", encoding="utf-8") as f:
            json.dump(printers, f, ensure_ascii=False, indent=4)
        return True
    except IOError as err:
        logger.error(f"Yazıcı JSON dosyasına yazılırken hata oluştu: {err}")
        return False


def send_zpl_to_printer(ip: str, zpl_command: str) -> bool:
    """
    Belirtilen IP adresine TCP 9100 portu üzerinden raw ZPL/SGD komutunu iletir.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(3)
            s.connect((ip, 9100))
            s.sendall(zpl_command.encode("utf-8"))
        logger.info(f"ZPL komutu başarıyla gönderildi ({ip})")
        return True
    except Exception as err:
        logger.error(f"ZPL komutu gönderilirken hata ({ip}): {err}")
        return False


def check_printer_status(ip: str) -> Tuple[bool, str]:
    """
    Yazıcıya Host Status (~HS) sorgusu göndererek çevrimiçi durumunu ve yanıtını kontrol eder.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(3)
            s.connect((ip, 9100))
            s.sendall(b"~HS\r\n")
            response = s.recv(1024)

        if response:
            return True, "Yazıcı aktif ve çevrimiçi."
        else:
            return True, "Yazıcı bağlantısı kuruldu ancak yanıt boş döndü."
    except socket.timeout:
        return False, "Zaman aşımı: Yazıcıya 3 saniye içinde ulaşılamadı."
    except ConnectionRefusedError:
        return False, "Bağlantı reddedildi: 9100 portu kapalı veya yazıcı çevrimdışı."
    except Exception as err:
        return False, f"Bağlantı hatası: {err}"


def add_windows_printer(printer_name: str, ip_address: str, driver_name: str) -> bool:
    """
    Windows PowerShell komutlarını kullanarak otonom yazıcı portu ve yazıcı tanımı oluşturur.
    """
    port_name = f"IP_{ip_address}"
    try:
        subprocess.run(
            [
                "powershell",
                "-Command",
                f'Add-PrinterPort -Name "{port_name}" -PrinterHostAddress "{ip_address}"',
            ],
            check=True,
            capture_output=True,
            text=True
        )

        subprocess.run(
            [
                "powershell",
                "-Command",
                f'Add-Printer -Name "{printer_name}" -DriverName "{driver_name}" -PortName "{port_name}"',
            ],
            check=True,
            capture_output=True,
            text=True
        )
        logger.info(f"Windows yazıcısı başarıyla eklendi: {printer_name}")
        return True
    except subprocess.CalledProcessError as err:
        logger.error(f"Windows Yazıcı Ekleme PowerShell Hatası: {err.stderr}")
        return False
    except Exception as err:
        logger.error(f"Windows Yazıcı Ekleme Beklenmeyen Hata: {err}")
        return False


async def scan_ip(ip: str, port: int = 9100, timeout: float = 0.5) -> Dict[str, str] | None:
    """
    Belirtilen IP ve portu kontrol eder, TCP bağlantısı kurulursa cihaz bilgisini döndürür.
    """
    try:
        conn = asyncio.open_connection(ip, port)
        reader, writer = await asyncio.wait_for(conn, timeout=timeout)
        
        # Soket kapatılıyor
        writer.close()
        await writer.wait_closed()

        name = "Sanal_Zebra" if ip == "127.0.0.1" else f"Zebra_{ip.replace('.', '_')}"
        return {"ip": ip, "name": name, "status": "Aktif"}
    except Exception:
        return None


async def discover_network_printers() -> list[Dict[str, str]]:
    """
    Yerel ağ alt ağını (Subnet) ve 127.0.0.1'i eşzamansız olarak tarar, 9100 portu açık yazıcıları döner.
    """
    discovered: list[Dict[str, str]] = []

    # 1. Localhost kontrolü (Sanal Yazıcı / Mock Server Testi)
    local_mock = await scan_ip("127.0.0.1", 9100, timeout=0.3)
    if local_mock:
        discovered.append(local_mock)

    # 2. Yerel Ağ IP Taraması
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "192.168.1.1"

    ip_parts = local_ip.split(".")
    if len(ip_parts) == 4:
        subnet_prefix = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}."

        # 1-254 arası tüm IP adresleri paralel taranıyor
        tasks = [scan_ip(f"{subnet_prefix}{i}", 9100, timeout=0.5) for i in range(1, 255)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, dict) and res:
                if not any(d["ip"] == res["ip"] for d in discovered):
                    discovered.append(res)

    return discovered


async def background_printer_monitor(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Arka planda periyodik olarak çalışan görev (Job Queue).
    """
    chat_id = context.job.data
    printers = load_printers()

    if not printers:
        return

    for name, info in printers.items():
        ip = info if isinstance(info, str) else info.get("ip")
        if not ip:
            continue

        is_online, _ = check_printer_status(ip)

        if not is_online:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🚨 *KRİTİK UYARI!*\n*{name}* yazıcısına (IP: `{ip}`)"
                    " ulaşılamıyor! Yazıcı çevrimdışı veya ağ bağlantısı kopmuş"
                    " olabilir."
                ),
                parse_mode="Markdown",
            )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /start Komut İşleyicisi.
    """
    chat_id = update.effective_chat.id

    if context.job_queue is not None:
        current_jobs = context.job_queue.get_jobs_by_name(str(chat_id))
        if not current_jobs:
            context.job_queue.run_repeating(
                background_printer_monitor,
                interval=1800,
                first=10,
                data=chat_id,
                name=str(chat_id),
            )

    keyboard = [
        [InlineKeyboardButton("🖨️ Yazıcıları Listele / Yönet", callback_data="list_printers")],
        [InlineKeyboardButton("🔍 Ağdaki Yazıcıları Otomatik Tara", callback_data="auto_discover")],
        [InlineKeyboardButton("➕ Manuel Yazıcı Ekle (Ağ + Windows)", callback_data="add_printer_info")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🤖 *Zebra Yazıcı Otonom Yönetim Paneline* Hoş Geldiniz!\n"
        "(Arka plan izleme sistemi aktif.)\n"
        "Ne yapmak istiyorsunuz?",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Inline Buton Tıklama Etkileşimlerini İşleyen Merkezi Callback Fonksiyonu.
    """
    query = update.callback_query
    await query.answer()
    data = query.data

    printers = load_printers()

    if data == "list_printers":
        if not printers:
            await query.edit_message_text(
                "Kayıtlı yazıcı bulunamadı. Lütfen önce yazıcı ekleyin.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Ana Menü", callback_data="main_menu")]]
                ),
            )
            return

        keyboard = []
        for name, info in printers.items():
            ip = info if isinstance(info, str) else info.get("ip")
            keyboard.append(
                [InlineKeyboardButton(f"🖨️ {name} ({ip})", callback_data=f"sel_{name}")]
            )
        keyboard.append(
            [InlineKeyboardButton("🔙 Ana Menü", callback_data="main_menu")]
        )

        await query.edit_message_text(
            "Ayar yapmak veya yönetmek istediğiniz yazıcıyı seçin:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data == "auto_discover":
        await query.edit_message_text("⏳ *Yerel ağ taranıyor...*\n\nPort 9100 üzerinde aktif olan Zebra yazıcılar tespit ediliyor. Lütfen 2-3 saniye bekleyin...", parse_mode="Markdown")
        discovered = await discover_network_printers()

        if not discovered:
            await query.edit_message_text(
                "❌ *Ağda aktif Zebra yazıcı bulunamadı.*\n\n"
                "• Yazıcının açık ve ağa bağlı olduğundan emin olun.\n"
                "• Test ortamındaysanız 'mock_zebra_printer.py' sunucusunun çalıştığını kontrol edin.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Ana Menü", callback_data="main_menu")]]
                ),
            )
            return

        keyboard = []
        for p in discovered:
            ip = p["ip"]
            name = p["name"]
            keyboard.append(
                [InlineKeyboardButton(f"➕ Ekle: {name} ({ip})", callback_data=f"autoadd_{ip}")]
            )
        keyboard.append(
            [InlineKeyboardButton("🔙 Ana Menü", callback_data="main_menu")]
        )

        await query.edit_message_text(
            f"🎉 *Ağda {len(discovered)} adet aktif Zebra yazıcı tespit edildi!*\n\n"
            "Sisteme otomatik eklemek istediğiniz yazıcıya tıklayın:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data.startswith("autoadd_"):
        target_ip = data.replace("autoadd_", "")
        name = "Sanal_Zebra" if target_ip == "127.0.0.1" else f"Zebra_{target_ip.replace('.', '_')}"
        driver = "ZDesigner ZD421-200 dpi ZPL"

        printers[name] = {"ip": target_ip, "driver": driver}
        save_printers(printers)

        await query.edit_message_text(
            f"✅ *{name}* yazıcısı başarıyla otomatik tespit edildi ve kayda alındı!\n\n"
            f"• IP: `{target_ip}`\n"
            f"• Sürücü: `{driver}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🖨️ Yazıcı Yönetimi", callback_data=f"sel_{name}")],
                    [InlineKeyboardButton("🔙 Ana Menü", callback_data="main_menu")]
                ]
            ),
        )

    elif data == "add_printer_info":
        context.user_data["state"] = "waiting_for_add"
        await query.edit_message_text(
            "Lütfen yazıcıyı şu formatta gönderin:\n\n"
            "`YazıcıAdı IPAdresi SürücüAdı`\n\n"
            "*Örnek:*\n"
            "`Depo_5 192.168.1.50 ZDesigner ZD421-200 dpi ZPL`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Ana Menü", callback_data="main_menu")]]
            ),
        )

    elif data == "main_menu":
        context.user_data.clear()
        keyboard = [
            [InlineKeyboardButton("🖨️ Yazıcıları Listele / Yönet", callback_data="list_printers")],
            [InlineKeyboardButton("🔍 Ağdaki Yazıcıları Otomatik Tara", callback_data="auto_discover")],
            [InlineKeyboardButton("➕ Manuel Yazıcı Ekle (Ağ + Windows)", callback_data="add_printer_info")],
        ]
        await query.edit_message_text(
            "Ana Menü:", reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("sel_"):
        printer_name = data.replace("sel_", "")
        context.user_data["selected_printer"] = printer_name

        keyboard = [
            [InlineKeyboardButton("🔍 Anlık Durum Sorgula", callback_data="check_status")],
            [InlineKeyboardButton("🧪 Test Etiketi Gönder", callback_data="send_test_label")],
            [InlineKeyboardButton("📱 QR Kod / Barkod Bastır", callback_data="print_code")],
            [InlineKeyboardButton("📏 Boyut Ayarla (mm/cm)", callback_data="set_size")],
            [InlineKeyboardButton("🌑 Koyuluk Ayarla (0-30)", callback_data="set_darkness")],
            [InlineKeyboardButton("⚡ Yazdırma Hızı Ayarla", callback_data="set_speed")],
            [InlineKeyboardButton("🔄 Otomatik Kalibrasyon", callback_data="calibrate")],
            [InlineKeyboardButton("📄 Yapılandırma Etiketi Bastır", callback_data="print_config")],
            [InlineKeyboardButton("🖥️ Windows'a Otomatik Ekle", callback_data="win_add")],
            [InlineKeyboardButton("🗑️ Yazıcıyı Sil", callback_data=f"del_{printer_name}")],
            [InlineKeyboardButton("🔙 Yazıcı Listesi", callback_data="list_printers")],
        ]
        await query.edit_message_text(
            f"Seçilen Yazıcı: *{printer_name}*\nNe yapmak istiyorsunuz?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data == "check_status":
        printer_name = context.user_data.get("selected_printer")
        if not printer_name:
            await query.edit_message_text("❌ Lütfen önce listeden bir yazıcı seçin.")
            return

        p_info = printers.get(printer_name)
        ip = p_info if isinstance(p_info, str) else (p_info.get("ip") if p_info else None)

        if not ip:
            await query.edit_message_text(f"❌ '{printer_name}' için geçerli bir IP adresi bulunamadı.")
            return

        await query.edit_message_text("⏳ Yazıcı durumu sorgulanıyor...")
        is_online, msg = check_printer_status(ip)

        status_text = (
            f"🟢 *{printer_name} Çevrimiçi*\nIP: `{ip}`\nDurum: {msg}"
            if is_online
            else f"🔴 *{printer_name} Çevrimdışı!*\nIP: `{ip}`\nHata: {msg}"
        )

        await query.edit_message_text(
            status_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Geri", callback_data=f"sel_{printer_name}")]]
            ),
        )

    elif data == "send_test_label":
        printer_name = context.user_data.get("selected_printer")
        if not printer_name:
            await query.edit_message_text("❌ Lütfen önce bir yazıcı seçin.")
            return

        p_info = printers.get(printer_name)
        ip = p_info if isinstance(p_info, str) else (p_info.get("ip") if p_info else None)

        if not ip:
            await query.edit_message_text("❌ Yazıcı IP bilgisi bulunamadı.")
            return

        test_zpl = (
            "^XA\n^FO50,50^A0N,35,35^FDTELEGRAM BOT TEST^FS\n"
            f"^FO50,100^A0N,25,25^FDYazici: {printer_name}^FS\n"
            "^FO50,140^BY2^BCN,60,Y,N,N^FD12345678^FS\n^XZ"
        )

        success = send_zpl_to_printer(ip, test_zpl)
        if success:
            msg = f"✅ *{printer_name}* yazıcısına test etiketi başarıyla gönderildi!"
        else:
            msg = f"❌ *{printer_name}* yazıcısına ulaşılamadı (IP: `{ip}`)."

        await query.edit_message_text(
            msg,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Geri", callback_data=f"sel_{printer_name}")]]
            ),
        )

    elif data == "print_code":
        selected = context.user_data.get("selected_printer", "")
        context.user_data["state"] = "waiting_for_barcode"
        await query.edit_message_text(
            "📱 *Barkod / QR Kod Basımı*\n\n"
            "Lütfen etiket üzerine yazdırılacak metin, seri numarası veya linki girin:\n"
            "Örnek: `URUN-123456` veya `https://ornek.com`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Geri", callback_data=f"sel_{selected}")]]
            ),
        )

    elif data == "set_size":
        selected = context.user_data.get("selected_printer", "")
        context.user_data["state"] = "waiting_for_size"
        await query.edit_message_text(
            "📏 *Etiket Ölçüsü Ayarlama*\n\n"
            "Lütfen yeni etiket ölçülerini **Milimetre (mm)** cinsinden `Genişlik,Yükseklik` şeklinde yazın.\n\n"
            "*Örnek:* `100,50` (10 cm genişlik, 5 cm yükseklik etiketi için)\n\n"
            "ℹ️ *Not:* Standart 203 DPI Zebra yazıcılarda 1 mm = 8 nokta (dots) olarak otomatik hesaplanır.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Geri", callback_data=f"sel_{selected}")]]
            ),
        )

    elif data == "set_darkness":
        selected = context.user_data.get("selected_printer", "")
        context.user_data["state"] = "waiting_for_darkness"
        await query.edit_message_text(
            "🌑 *Koyuluk Ayarlama*\n\n"
            "Lütfen koyuluk seviyesini **0 ile 30** arasında bir sayı olarak girin.\n"
            "Örnek: `20`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Geri", callback_data=f"sel_{selected}")]]
            ),
        )

    elif data == "set_speed":
        selected = context.user_data.get("selected_printer", "")
        context.user_data["state"] = "waiting_for_speed"
        await query.edit_message_text(
            "⚡ *Yazdırma Hızı Ayarlama*\n\n"
            "Lütfen yazdırılma hızını (inch/saniye) **2 ile 6** arasında bir sayı olarak girin.\n"
            "• `2`: Çok Yüksek Kalite / Yavaş\n"
            "• `4`: Standart Dengeli Hız\n"
            "• `6`: Yüksek Hız\n\n"
            "Örnek: `4`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Geri", callback_data=f"sel_{selected}")]]
            ),
        )

    elif data == "calibrate":
        printer_name = context.user_data.get("selected_printer")
        if not printer_name:
            await query.edit_message_text("❌ Yazıcı seçilmedi.")
            return

        p_info = printers.get(printer_name)
        ip = p_info if isinstance(p_info, str) else (p_info.get("ip") if p_info else None)

        if not ip:
            await query.edit_message_text("❌ IP bulunamadı.")
            return

        await query.edit_message_text("⏳ Medya kalibrasyonu başlatılıyor...")
        # Zebra ~JC (Medya Uzunluk ve Gap Sensör Kalibrasyon Komutu)
        success = send_zpl_to_printer(ip, "~JC\r\n")

        if success:
            msg = f"🔄 *{printer_name}* kalibrasyon komutu (~JC) başarıyla iletildi!"
        else:
            msg = f"❌ *{printer_name}* yazıcısına ulaşılamadı (IP: `{ip}`)."

        await query.edit_message_text(
            msg,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Geri", callback_data=f"sel_{printer_name}")]]
            ),
        )

    elif data == "print_config":
        printer_name = context.user_data.get("selected_printer")
        if not printer_name:
            await query.edit_message_text("❌ Yazıcı seçilmedi.")
            return

        p_info = printers.get(printer_name)
        ip = p_info if isinstance(p_info, str) else (p_info.get("ip") if p_info else None)

        if not ip:
            await query.edit_message_text("❌ IP bulunamadı.")
            return

        await query.edit_message_text("⏳ Yapılandırma etiketi komutu gönderiliyor...")
        # Zebra ~WC (Yazıcı Yapılandırma Bilgisi Bastırma Komutu)
        success = send_zpl_to_printer(ip, "~WC\r\n")

        if success:
            msg = f"📄 *{printer_name}* yapılandırma etiketi yazdırma komutu (~WC) iletildi!"
        else:
            msg = f"❌ *{printer_name}* yazıcısına ulaşılamadı (IP: `{ip}`)."

        await query.edit_message_text(
            msg,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Geri", callback_data=f"sel_{printer_name}")]]
            ),
        )

    elif data == "win_add":
        printer_name = context.user_data.get("selected_printer")
        if not printer_name:
            await query.edit_message_text("❌ Yazıcı seçilmedi.")
            return

        printer_info = printers.get(printer_name)

        if not printer_info or isinstance(printer_info, str) or "driver" not in printer_info:
            await query.edit_message_text(
                "❌ Bu yazıcı için sürücü adı tanımlanmamış.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Geri", callback_data=f"sel_{printer_name}")]]
                ),
            )
            return

        ip = printer_info["ip"]
        driver = printer_info["driver"]

        await query.edit_message_text("⏳ Yazıcı Windows'a ekleniyor...")
        success = add_windows_printer(printer_name, ip, driver)

        if success:
            msg = f"✅ *{printer_name}* başarıyla Windows'a ve porta eklendi!"
        else:
            msg = "❌ Windows'a eklenirken hata oluştu (Sürücü adı veya PowerShell yetkilerini kontrol edin)."

        await query.edit_message_text(
            msg,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Geri", callback_data=f"sel_{printer_name}")]]
            ),
        )

    elif data.startswith("del_"):
        printer_name = data.replace("del_", "")
        if printer_name in printers:
            del printers[printer_name]
            save_printers(printers)
        await query.edit_message_text(
            f"🗑️ *{printer_name}* listeden silindi.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🖨️ Yazıcı Listesi", callback_data="list_printers")]]
            ),
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Kullanıcının gönderdiği metin mesajlarını duruma (state) göre işleyen fonksiyon.
    """
    state = context.user_data.get("state")
    text = update.message.text.strip()
    printers = load_printers()

    if state == "waiting_for_add":
        try:
            parts = text.split(" ", 2)
            if len(parts) < 3:
                await update.message.reply_text(
                    "⚠️ Hatalı format! Örnek:\n"
                    "`Depo_1 192.168.1.50 ZDesigner ZD421-200 dpi ZPL`",
                    parse_mode="Markdown",
                )
                return

            name, ip, driver = parts[0], parts[1], parts[2]
            printers[name] = {"ip": ip, "driver": driver}
            save_printers(printers)
            context.user_data.clear()

            await update.message.reply_text(
                f"✅ *Yazıcı Kaydedildi!*\nAd: `{name}`\nIP: `{ip}`\nSürücü: `{driver}`",
                parse_mode="Markdown",
            )
        except Exception as err:
            logger.error(f"Yazıcı ekleme sırasında hata: {err}")
            await update.message.reply_text(f"Bir hata oluştu: {err}")

    elif state == "waiting_for_size":
        printer_name = context.user_data.get("selected_printer")
        if not printer_name:
            await update.message.reply_text("❌ Seçili yazıcı bulunamadı.")
            return

        p_info = printers.get(printer_name)
        ip = p_info if isinstance(p_info, str) else (p_info.get("ip") if p_info else None)

        if not ip:
            await update.message.reply_text("❌ Yazıcı IP bilgisi bulunamadı.")
            return

        try:
            parts = [p.strip() for p in text.split(",")]
            w_mm, h_mm = float(parts[0]), float(parts[1])

            # Standart 203 DPI Zebra yazıcılar için 1 mm = 8 dot
            # Eğer sürücü adında 300 dpi kelimesi geçiyorsa 1 mm = 12 dot
            driver_str = str(p_info.get("driver", "") if isinstance(p_info, dict) else "").lower()
            dots_per_mm = 12.0 if "300" in driver_str else 8.0

            w_dots = int(w_mm * dots_per_mm)
            h_dots = int(h_mm * dots_per_mm)

            zpl = f"^XA^PW{w_dots}^LL{h_dots}^XZ"
            success = send_zpl_to_printer(ip, zpl)

            if success:
                await update.message.reply_text(
                    f"✅ *{printer_name}* boyut ayarı gönderildi!\n\n"
                    f"• Girilen Ölçü: `{w_mm} mm x {h_mm} mm` ({w_mm/10} cm x {h_mm/10} cm)\n"
                    f"• ZPL Nokta (Dots): `{w_dots} x {h_dots}`",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(f"❌ Yazıcıya ulaşılamadı (IP: `{ip}`).", parse_mode="Markdown")
        except Exception:
            await update.message.reply_text("⚠️ Hatalı değer! Örnek format: `100,50` (mm cinsinden)", parse_mode="Markdown")

        context.user_data.clear()

    elif state == "waiting_for_darkness":
        printer_name = context.user_data.get("selected_printer")
        if not printer_name:
            await update.message.reply_text("❌ Seçili yazıcı bulunamadı.")
            return

        p_info = printers.get(printer_name)
        ip = p_info if isinstance(p_info, str) else (p_info.get("ip") if p_info else None)

        if not ip:
            await update.message.reply_text("❌ Yazıcı IP bilgisi bulunamadı.")
            return

        try:
            darkness = int(text)
            zpl = f"! 0 200 200 210 1\nDARKNESS {darkness}\nPRINT\n"
            success = send_zpl_to_printer(ip, zpl)

            if success:
                await update.message.reply_text(
                    f"✅ *{printer_name}* koyuluk seviyesi {darkness} yapıldı.",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(f"❌ Yazıcıya ulaşılamadı (IP: `{ip}`).", parse_mode="Markdown")
        except Exception:
            await update.message.reply_text("⚠️ Geçersiz sayı! 0-30 arası bir değer girin.")

        context.user_data.clear()

    elif state == "waiting_for_barcode":
        printer_name = context.user_data.get("selected_printer")
        if not printer_name:
            await update.message.reply_text("❌ Seçili yazıcı bulunamadı.")
            return

        p_info = printers.get(printer_name)
        ip = p_info if isinstance(p_info, str) else (p_info.get("ip") if p_info else None)

        if not ip:
            await update.message.reply_text("❌ Yazıcı IP bilgisi bulunamadı.")
            return

        try:
            barcode_zpl = (
                "^XA\n"
                "^FO50,40^A0N,30,30^FDOtonom Barkod Basimi^FS\n"
                f"^FO50,90^BY2^BCN,70,Y,N,N^FD{text}^FS\n"
                f"^FO50,200^BQN,2,4^FDQA,{text}^FS\n"
                "^XZ"
            )
            success = send_zpl_to_printer(ip, barcode_zpl)

            if success:
                await update.message.reply_text(
                    f"✅ *{printer_name}* yazıcısına `{text}` içerikli Barkod & QR Kod basıldı!",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(f"❌ Yazıcıya ulaşılamadı (IP: `{ip}`).", parse_mode="Markdown")
        except Exception as err:
            await update.message.reply_text(f"⚠️ Barkod oluşturulurken hata: {err}")

        context.user_data.clear()

    elif state == "waiting_for_speed":
        printer_name = context.user_data.get("selected_printer")
        if not printer_name:
            await update.message.reply_text("❌ Seçili yazıcı bulunamadı.")
            return

        p_info = printers.get(printer_name)
        ip = p_info if isinstance(p_info, str) else (p_info.get("ip") if p_info else None)

        if not ip:
            await update.message.reply_text("❌ Yazıcı IP bilgisi bulunamadı.")
            return

        try:
            speed = int(text)
            if not (2 <= speed <= 6):
                await update.message.reply_text("⚠️ Lütfen 2 ile 6 arasında bir hız değeri girin.")
                return

            speed_zpl = f"^XA^PR{speed}^XZ"
            success = send_zpl_to_printer(ip, speed_zpl)

            if success:
                await update.message.reply_text(
                    f"✅ *{printer_name}* yazdırma hızı `{speed} ips` olarak ayarlandı.",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(f"❌ Yazıcıya ulaşılamadı (IP: `{ip}`).", parse_mode="Markdown")
        except Exception:
            await update.message.reply_text("⚠️ Geçersiz sayı! 2-6 arasında bir değer girin.")

        context.user_data.clear()


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Bot çalışırken oluşan beklenmeyen istisnaları yakalar ve loglar.
    """
    logger.error("Bot çalışmasında hata oluştu:", exc_info=context.error)


def main() -> None:
    """
    Telegram Bot Uygulamasının Ana Çalıştırma Fonksiyonu.
    """
    logger.info("Zebra Otonom Yönetim Botu başlatılıyor...")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    print("==================================================")
    print("Otonom Zebra Botu aktif ve calisiyor...")
    print("==================================================")
    app.run_polling()


if __name__ == "__main__":
    main()
