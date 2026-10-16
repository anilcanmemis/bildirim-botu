# 🚀 7/24 Ücretsiz Sunucu Kurulum Kılavuzu

Bu kılavuz, İŞKUR & SBB İlan Takip Botunu **kendi ücretsiz sunucunuzda** (VM)
7/24 kesintisiz çalıştırmanız için gereken tüm adımları içerir.

---

## ❓ Neden GitHub Actions artık çalışmıyor?

**Sorun:** GitHub Actions, **private (özel)** depolar için ayda sadece
**2.000 dakika** ücretsiz çalışma süresi verir.

Bot, 7/24 kesintisiz çalışmak için her seferinde ~350 dakika (5 saat 50 dakika)
boyunca dönüyordu ve günde 4 kez tetikleniyordu:

```
350 dakika × 4 çalıştırma = ~1.400 dakika / GÜN
1.400 × 30 gün             = ~42.000 dakika / AY  (limit: 2.000)
```

Yani ücretsiz kota **yaklaşık 1,5 günde** tükeniyor. Nitekim:

| Tarih | Durum |
|---|---|
| 9 – 13 Ekim | Bot kesintisiz çalıştı ✅ |
| 13 Ekim 22:24 UTC | Kota tükendi, son başarılı çalıştırma |
| 14 Ekim'den itibaren | Cron tetikleniyor ama **iş hiç başlamıyor** ❌ |

GitHub'ın verdiği hata mesajı aynen şuydu:

> *"The job was not started because recent account payments have failed or your
> spending limit needs to be increased."*

**Çözüm:** Botu, ücretsiz ve kalıcı bir sunucuya (VM) taşıyoruz. Böylece
dakika kotası diye bir sınır kalmıyor.

---

## 🏗️ Yeni Mimari

```
┌──────────────────────────────────────────────────────────────┐
│  ÜCRETSİZ VM (Oracle Cloud Always Free)                      │
│                                                              │
│   systemd: iskur-bot.service                                 │
│     └─ python check_now.py --forever                         │
│          ├─ Her 2 sn  : Telegram mesaj/buton kontrolü        │
│          ├─ Her 3 dk  : İŞKUR + SBB ilan taraması            │
│          └─ Her 10 dk : (opsiyonel) git yedekleme            │
│                                                              │
│   Durum dosyaları yerel diskte kalıcı:                       │
│     jobs.db · seen_jobs.json · last_update_id.txt            │
└──────────────────────────────────────────────────────────────┘
```

**Kazanımlar:**
- ✅ Dakika kotası yok → gerçek 7/24 kesintisiz
- ✅ Çökerse systemd 10 saniye içinde otomatik yeniden başlatır
- ✅ Sunucu yeniden başlasa bile bot otomatik ayağa kalkar
- ✅ Tamamen ücretsiz (kredi kartı sadece kimlik doğrulama için, ücret alınmaz)

---

## 📋 Ön Hazırlık: GitHub Erişim Anahtarı

Depo **private** olduğu için sunucudan klonlayabilmek adına bir erişim
anahtarı (token) oluşturun:

1. https://github.com/settings/tokens adresine gidin
2. **Generate new token (classic)** → *Read-only* yeterli
3. Yetkiler: **`repo`** kutusunu işaretleyin
4. **Generate token** → çıkan `ghp_...` değerini bir yere kaydedin

> 💡 Alternatif: `Fine-grained token` → Repository access: *iskur-is-ilan-takip*
> → Permissions: **Contents = Read-only**

---

## ☁️ Adım 1 — Oracle Cloud Ücretsiz Hesap

1. https://www.oracle.com/cloud/free/ adresine gidin → **Start for free**
2. E-posta, telefon ve **kredi kartı** bilgilerinizi girin
   - Kart **sadece kimlik doğrulama** için kullanılır (~1$ provizyon çekilip iade edilir)
   - Always Free limitleri içinde kaldığınız sürece **hiçbir ücret ödemezsiniz**
3. **Home Region** seçin — ⚠️ *Bu seçim sonradan değiştirilemez*
   - Türkiye'ye en yakın seçenekler: **Germany Central (Frankfurt)**,
     **Netherlands (Amsterdam)**, **Switzerland (Zurich)**

---

## 🖥️ Adım 2 — Sunucu (VM) Oluşturma

Oracle konsolunda: **Menu ☰ → Compute → Instances → Create instance**

| Alan | Değer |
|---|---|
| **Name** | `iskur-bot` |
| **Image** | Canonical **Ubuntu 24.04** |
| **Shape** | Ampere → **VM.Standard.A1.Flex** |
| **OCPU / Memory** | **1 OCPU / 6 GB** (Always Free limiti: 2 OCPU / 12 GB) |
| **Primary VNIC** | ✅ Assign a public IPv4 address |
| **SSH keys** | *Generate a key pair for me* → **private key'i indirin** |

> ⚠️ **"Out of host capacity" hatası alırsanız:** Bu, ücretsiz ARM kapasitesinin
> o an dolu olduğu anlamına gelir. Farklı bir *Availability Domain* seçin veya
> birkaç saat sonra tekrar deneyin.
>
> 💡 **Alternatif (kapasite sorunu yaşarsanız):** Shape olarak
> **VM.Standard.E2.1.Micro** (AMD, 1 GB RAM) seçin. Bu da Always Free'dir ve
> botumuz için fazlasıyla yeterlidir.

**Create** butonuna basın ve sunucunun **Public IP** adresini not edin.

---

## 🔌 Adım 3 — Sunucuya Bağlanma

İndirdiğiniz private key dosyasının izinlerini ayarlayıp bağlanın.

**Windows (PowerShell):**
```powershell
icacls "C:\yol\ssh-key-2026-10-16.key" /inheritance:r /grant:r "$($env:USERNAME):(R)"
ssh -i "C:\yol\ssh-key-2026-10-16.key" ubuntu@<PUBLIC_IP>
```

**Linux / macOS:**
```bash
chmod 600 ~/Downloads/ssh-key-2026-10-16.key
ssh -i ~/Downloads/ssh-key-2026-10-16.key ubuntu@<PUBLIC_IP>
```

> Oracle'ın varsayılan güvenlik listesi 22 (SSH) portuna izin verir,
> ek bir ayar yapmanıza gerek yoktur.

---

## 🤖 Adım 4 — Botu Kurma (Tek Komut)

Sunucuya bağlandıktan sonra:

```bash
# 1) Projeyi klonla (<TOKEN> yerine Adım 0'daki ghp_... değerini yazın)
git clone https://<TOKEN>@github.com/anilcanmemis/iskur-is-ilan-takip.git
cd iskur-is-ilan-takip

# 2) Kurulumu başlat
sudo bash deploy/setup.sh
```

**Oracle Cloud kullanıyorsanız** (bosta sayılma koruması ile birlikte):
```bash
sudo KEEPALIVE=true bash deploy/setup.sh
```

Bu komut otomatik olarak şunları yapar:

1. Python 3, venv ve git paketlerini kurar
2. Projeyi `/opt/epic-davinci` klasörüne kopyalar
3. Sanal ortam oluşturup bağımlılıkları yükler
4. `iskur-bot.service` systemd servisini kurar ve **başlatır**
5. Servisi **boot'ta otomatik başlayacak** şekilde etkinleştirir

Kurulum ~2 dakika sürer. Sonunda şunu görmelisiniz:

```
======================================================================
  BASARILI: iskur-bot servisi calisiyor ve 7/24 aktif.
======================================================================
```

---

## 🔐 Adım 5 — Gizli Anahtarları Taşıma (Önerilir)

Token ve API anahtarı şu an `config_iskur.json` içinde düz metin olarak duruyor.
Daha güvenli olması için ortam değişkeni dosyasına taşıyın:

```bash
sudo nano /etc/iskur-bot.env
```

Doldurulacak alanlar:

```ini
TELEGRAM_BOT_TOKEN=<botfather_tokeniniz>
TELEGRAM_CHAT_ID=<bildirim_gidecek_chat_id>
ADMIN_CHAT_ID=<admin_telegram_id>
GEMINI_API_KEY=<gemini_api_anahtariniz>
```

Kaydedip servisi yeniden başlatın:

```bash
sudo systemctl restart iskur-bot
```

> Bu dosyadaki değerler `config_iskur.json` içindekilerin **yerine geçer**.
> Boş bırakılan satırlar yok sayılır. Dosya izinleri otomatik olarak `600`'dür.
>
> ⚠️ `config_iskur.json` içindeki token'ı sildiğinizde bot artık sadece
> bu dosyayı kullanır — token'ı **hiçbir zaman** git'e commit etmeyin.

---

## 📊 Kontrol ve Yönetim Komutları

| Ne yapmak istiyorum | Komut |
|---|---|
| Canlı log izle | `journalctl -u iskur-bot -f` |
| Son 50 satır log | `journalctl -u iskur-bot -n 50 --no-pager` |
| Servis durumu | `systemctl status iskur-bot` |
| Yeniden başlat | `sudo systemctl restart iskur-bot` |
| Durdur / Başlat | `sudo systemctl stop iskur-bot` / `start` |
| Otomatik başlatmayı kapat | `sudo systemctl disable iskur-bot` |

### Kurulumun doğru çalıştığını test etme

```bash
# Tek seferlik kontrol (test modu)
cd /opt/epic-davinci
.venv/bin/python check_now.py --once
```

Telegram'da bota `/start` yazın — sabit menü anında yanıt vermelidir.

---

## 🔄 Güncelleme

Kodda değişiklik yaptıysanız:

```bash
cd /opt/epic-davinci
git pull
sudo bash deploy/setup.sh
```

---

## 🛡️ Oracle Cloud "Bosta Sayılma" Koruması

Oracle, Always Free sunucuları **7 gün boyunca boşta** sayarsa geri alabilir.
Boşta sayılma koşulu (7 gün boyunca hepsinin geçerli olması):

- CPU kullanımının 95. yüzdelik değeri **%10'un altında**
- Ağ kullanımının 95. yüzdelik değeri **%10'un altında**
- Bellek kullanımının 95. yüzdelik değeri **%20'nin altında**

**İki çözüm var:**

**1) (En temiz) Pay As You Go'ya yükseltin**
Oracle hesabınızı *Upgrade to Pay As You Go* ile yükseltin. Always Free
limitleri içinde kaldığınız sürece **ücret ödemezsiniz** ve bosta sayılma
geri alımı **uygulanmaz**. Kart bilgisi zaten kayıtlı olduğu için ek işlem gerekmez.

**2) Koruma scriptini kurun**
```bash
sudo KEEPALIVE=true bash deploy/setup.sh
```
Bu, toplam CPU'nun ~%15'ini sürekli meşgul ederek sunucunun boşta sayılmasını
engeller. Durumunu kontrol etmek için:
```bash
systemctl status iskur-keepalive
```

---

## 🐳 Alternatif: Docker / Konteyner Platformu

Sunucu yönetmek istemiyorsanız `deploy/Dockerfile` hazırdır:

```bash
docker build -f deploy/Dockerfile -t iskur-bot .
docker run -d --name iskur-bot --restart always \
  -v iskur_state:/data \
  -e TELEGRAM_BOT_TOKEN="..." \
  -e GEMINI_API_KEY="..." \
  iskur-bot
```

> ⚠️ **Dikkat:** Render, Railway, Glitch gibi platformların ücretsiz planları
> belli süre sonra uyutulur (sleep) — bu, Telegram botu için **uygun değildir**.
> Koyeb'in "nano" ücretsiz planı veya bir VM kullanın.

---

## 🆘 Sorun Giderme

### Bot Telegram'a cevap vermiyor
```bash
journalctl -u iskur-bot -n 100 --no-pager
```
- `Telegram bot token hatalı` → `/etc/iskur-bot.env` içindeki token'ı kontrol edin
- `sqlite3.OperationalError` → dosya izinleri bozuk:
  `sudo chown -R ubuntu:ubuntu /opt/epic-davinci`

### Servis sürekli yeniden başlıyor
```bash
systemctl status iskur-bot --no-pager -l
```
Genelde eksik bağımlılık veya yazma izni sorunudur. Şunu çalıştırın:
```bash
cd /opt/epic-davinci && .venv/bin/pip install -r requirements.txt
```

### Aynı ilanlar tekrar bildiriliyor
Durum dosyaları silinmiş olabilir. Şunları kontrol edin:
```bash
ls -la /opt/epic-davinci/jobs.db /opt/epic-davinci/seen_jobs.json
```

### "Out of host capacity" (Oracle VM oluştururken)
Farklı bir *Availability Domain* deneyin, `E2.1.Micro` (AMD) shape'ini seçin
veya birkaç saat sonra tekrar deneyin.

---

## 📁 İlgili Dosyalar

| Dosya | Açıklama |
|---|---|
| `deploy/setup.sh` | Tek komutla sunucu kurulumu |
| `deploy/iskur-bot.service` | systemd servis tanımı (7/24) |
| `deploy/iskur-keepalive.service` | Oracle bosta sayılma koruması |
| `deploy/keepalive.py` | Hafif CPU yükü üreteci |
| `deploy/Dockerfile` | Konteyner imajı |
| `deploy/.env.example` | Ortam değişkenleri şablonu |
