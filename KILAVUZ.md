# 🧭 Epic Davinci - Sistem Mimari ve Kullanım Kılavuzu

Bu repository, iki ana otonom alt sistemi barındıran modüler bir yazılım altyapısıdır:
1. **Zebra Yazıcı Otonom Yönetim Sistemi**: Telegram üzerinden termal etiket yazıcılarını yönetme ve etiket bastırma.
2. **İŞKUR & SBB Resmi Memur İlan Takip, Yetkilendirme ve Gemini AI Botu**: Türkiye geneli İŞKUR ve T.C. Cumhurbaşkanlığı SBB Resmi Kamu İlan Portalı (`kamuilan.sbb.gov.tr`) ilanlarını periyodik tarayarak Gemini AI analizi ile Telegram'dan bildirme, yetkisiz erişimleri engelleme ve 7/24 sabit menü sunma.

---

## 🗺️ Proje Dosya Yapısı (Neyin Nerede Olduğu)

```
epic-davinci/
├── iskur_scraper.py          # İŞKUR Web Scraper ve Oturum Yönetim Modülü
├── sbb_scraper.py            # T.C. Cumhurbaşkanlığı SBB Resmi Kamu İlan Portalı Scraper Modülü
├── memurlar_scraper.py       # Memurlar.net Resmi Memur, Akademik ve Kamu İlanları Scraper Modülü
├── kariyer_scraper.py        # Kariyer.net Özel Sektör ve Kurumsal İlan Scraper Modülü
├── gemini_analyzer.py        # Gemini 2.5 Flash AI İlan Analiz ve Satır Arası İpucu Modülü
├── db_manager.py             # SQLite (jobs.db) İlan & Yetkili Kullanıcı Veritabanı Modülü
├── iskur_bot.py              # İŞKUR, SBB, Memurlar.net & Kariyer.net Çoklu Kaynak Botu
├── check_now.py              # 7/24 Canlı İlan Kontrolçüsü (--forever / --once modları)
├── config_iskur.json         # Bot Yapılandırma, Admin ID, Gemini Key ve Filtre Ayarları
├── seen_jobs.json            # Bildirilmiş İlan Numaralarının Saklandığı Veritabanı
├── last_update_id.txt        # Telegram getUpdates Mesaj Offset Takip Dosyası
├── jobs.db                   # SQLite İlan ve Yetkili Kullanıcı Veritabanı
├── deploy/                   # 🆕 7/24 Ücretsiz Sunucu Kurulum Paketi
│   ├── KURULUM.md            # Adım adım VM kurulum kılavuzu (Oracle Cloud vb.)
│   ├── setup.sh              # Tek komutla sunucu kurulumu
│   ├── iskur-bot.service     # systemd servis tanımı (Restart=always)
│   ├── iskur-keepalive.service  # Oracle "bosta sayılma" koruması servisi
│   ├── keepalive.py          # Hafif CPU yükü üreteci
│   ├── Dockerfile            # Konteyner imajı
│   └── .env.example          # Ortam değişkenleri şablonu
├── .github/workflows/
│   └── iskur_checker.yml     # (Devre dışı) Manuel yedek çalıştırma workflow'u
├── main.py                   # Zebra Yazıcı Telegram Botu Ana Uygulaması
├── mock_zebra_printer.py     # Sanal Zebra Yazıcı Sunucusu (Test Amaçlı)
├── printers.json             # Kayıtlı Yazıcılar Veritabanı
├── requirements.txt          # Proje Python Bağımlılıkları (requests, bs4)
└── KILAVUZ.md                # Mimari Rehber ve Kullanım Dokümantasyonu
```

---

## 🛡️ Yetkilendirme ve Admin Yönetimi

- **Admin ID**: Ortam değişkeni / GitHub Secrets üzerinden tanımlanır (`ADMIN_CHAT_ID`)
- **Yetkisiz Kullanıcı Koruması**: Yetki verilmeyen üçüncü şahıslar Telegram'dan `/start` bastığında yetkisiz erişim uyarısı alır ve Telegram ID'si gösterilir.
- **Admin Komutları** (Doğrudan veya Telegram otomatik tamamlamadaki `@bot_adi` takısıyla çalışır):
  - `/ekle [ID] [İsim]` (Örn: `/ekle 123456789 Ahmet Yılmaz`): Yeni yetkili kullanıcı ekler.
  - `/sil [ID]` (Örn: `/sil 123456789`): Kullanıcının yetkisini kaldırır.
  - `/kullanicilar`: Kayıtlı yetkili kullanıcıları roller ve ID'leri ile detaylı listeler.
  - `/soru [İlan_No] [Sorunuz]`: Belirli bir ilan için Gemini AI yapay zeka analizi ve soru-cevap danışmanlığı sağlar.

---

## 📱 Telegram Sabit (Sticky) Menü Butonları

Telegram sohbet ekranının altında 7/24 sabit duran özel kontrol paneli:
1. 🔍 **Anlık İlan Tara**: İŞKUR ve SBB portallarını anında tarar.
2. 📋 **Son İlanlar**: Veritabanındaki en son 5 ilanı listeler.
3. 🏙️ **İl Filtresi**: Şehir arama kapsamını değiştirir (`/il 0`, `/il 59`, `/il 34` vb.).
4. 🏢 **Sektör Filtresi**: Kamu, Özel veya Tümü seçeneklerini süzebilir.
5. ⚙️ **Mevcut Ayarlar**: Aktif filtreleri ve Admin durumunu gösterir.
6. 👥 **Kullanıcılar**: Admin yetkili kullanıcı listesini gösterir.

---

## 🌐 Entegre İstihdam ve Kamu Portalları (Modüler Yapı)

Şu an aktif portallar (Kullanıcı tercihi doğrultusunda):
1. **💼 İŞKUR e-Şube (`esube.iskur.gov.tr`) [AKTİF]**:
   - Türkiye İş Kurumu resmi kamu ve özel sektör iş ilanları. Sayısal ilan numaraları (`00009844279`) ile taranır.
2. **🏛️ T.C. Cumhurbaşkanlığı SBB Kamu Portalı (`kamuilan.sbb.gov.tr`) [AKTİF]**:
   - Strateji ve Bütçe Başkanlığı resmi kamu personel, uzman yardımcısı, askeri ve akademik alım ilanları. Deterministik MD5 Hash (`SBB_a1b2c3d4e5f6`) ile izlenir.

Modüler Olarak Hazırda Bekleyen Portallar (`config_iskur.json` üzerinden istenildiği zaman aktif edilebilir):
3. **📰 Memurlar.net Kamu & Memur İlanları (`ilan.memurlar.net`) [PASİF]**:
   - Tüm bakanlıklar, üniversiteler, belediyeler, KPSS-A, KPSS-B ve sözleşmeli personel alımları (`enable_memurlar_portal`).
4. **🏢 Kariyer.net Özel Sektör & Kurumsal (`kariyer.net`) [PASİF]**:
   - Türkiye'nin özel sektör ve kurumsal kariyer portalı (`enable_kariyer_portal`).

---

## 📌 %100 Mükerrer İlan Koruması (SBB & İŞKUR)

- **İŞKUR İlanları**: İŞKUR web sitesindeki sabit sayısal ilan numaraları (`00009844279` vb.) ile denetlenir.
- **SBB Kamu İlanları**: SBB portalında (`kamuilan.sbb.gov.tr`) `kod=` URL parametresi her sayfa yenilemesinde dinamik/rastgele üretildiği için, ilan başlığından türetilen deterministik **MD5 Hash ID** (`SBB_a1b2c3d4e5f6`) kullanılır.
- Hem `seen_jobs.json` hem de `jobs.db` SQLite veritabanında çift katmanlı denetim yapılarak **%100 mükerrer bildirim engellenir**.
- **Atomik Telegram Update Kilidi (`telegram_updates`)**: Bulut sunucularda veya çakışan süreçlerde aynı Telegram buton tıklaması (`update_id`) birden fazla bot örneği tarafından yakalansa dahi SQLite atomik kilit mekanizması sayesinde mükerrer yanıtlar %100 engellenir ve sadece TEK BİR yanıt gönderilir.

---

## 🏙️ Türkiye'nin 81 İli ve Çoklu Şehir Seçimi Özelliği

- **81 İl Desteği**: Türkiye'nin tüm 81 ili plaka kodları (01-81) ve coğrafi bölgeleri ile sisteme entegre edilmiştir.
- **7 Coğrafi Bölge Sekmesi**: Marmara, İç Anadolu, Ege, Akdeniz, Karadeniz, Doğu Anadolu ve Güneydoğu Anadolu sekmeleri ile illere kolay erişim.
- **Çoklu Şehir Filtreleme (Multi-Select)**: Kullanıcılar istedikleri sayıda ili (örneğin Tekirdağ + İstanbul + Kocaeli) aynı anda seçip kaydedebilir.
- **Canlı Tık ✅ Göstergesi**: Seçilen şehirler yerinde güncellenen butonlarda yeşil tık ✅ ile gösterilir.
- **Tüm Türkiye Seçeneği**: İstenildiği an tek dokunuşla tüm iller kısıtlamasız aranabilir.

---

## ⚡ 7/24 Kesintisiz Çalışma Mimarisi (Kendi Sunucu / systemd)

> ⚠️ **Önemli Değişiklik:** Sistem, GitHub Actions'tan **kendi ücretsiz sunucuya
> (VM)** taşınmıştır. Nedeni: GitHub Actions private depolar için ayda yalnızca
> **2.000 dakika** ücretsiz süre verir; 7/24 çalışma ise **~42.000 dakika/ay**
> gerektirdiği için kota ~1,5 günde tükeniyordu.
> Detaylı kurulum: **[`deploy/KURULUM.md`](deploy/KURULUM.md)**

- **Sınırsız Döngü Modeli (`--forever`)**: `check_now.py --forever` komutu,
  hiçbir süre sınırı olmadan kesintisiz çalışır. 6 saatlik job limiti yoktur.
- **Anlık Telegram Yanıtı**: Bot döngü içerisinde her 2 saniyede bir Telegram
  mesaj ve buton etkileşimlerini kontrol eder; butonlara ve komutlara anında tepki verir.
- **Periyodik İlan Taraması**: Her 3 dakikada bir İŞKUR ve SBB portalları
  taranarak yeni düşen ilanlar Gemini AI analizli olarak Telegram'a gönderilir.
- **Kalıcı Yerel Durum**: `seen_jobs.json`, `jobs.db` ve `last_update_id.txt`
  sunucu diskinde kalıcıdır. `ISKUR_GIT_BACKUP=true` verilirse ayrıca her
  10 dakikada bir GitHub'a yedeklenir.
- **Otomatik Kurtarma (systemd `Restart=always`)**: Bot herhangi bir nedenle
  çökerse systemd tarafından **10 saniye içinde** yeniden başlatılır.
- **Açılışta Otomatik Başlama**: `systemctl enable` sayesinde sunucu yeniden
  başlasa dahi bot kendiliğinden ayağa kalkar. Gerçek 7/24 kesintisizlik.
- **Gizli Anahtar Güvenliği**: Token ve API anahtarı `/etc/iskur-bot.env`
  dosyasından ortam değişkeni olarak okunabilir; repoda düz metin durması gerekmez.

### Yedek Çalışma Yolu (GitHub Actions - Devre Dışı)

`.github/workflows/iskur_checker.yml` dosyası yalnızca **manuel** çalıştırma
için bırakılmıştır (`Actions → Run workflow`). Otomatik `schedule` ve `push`
tetikleyicileri kaldırılmıştır.

