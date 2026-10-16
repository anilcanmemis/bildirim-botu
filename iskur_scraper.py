"""
===============================================================================
İŞKUR Açık İş İlanı Scraper ve Oturum Yönetim Modülü (iskur_scraper.py)
===============================================================================

Bu modül, Türkiye İş Kurumu (İŞKUR) e-Şube platformundaki (esube.iskur.gov.tr) 
açık iş ilanlarını ASP.NET WebForms mimarisine uygun şekilde taramak, ilan 
detaylarını ayrıştırmak ve e-Devlet oturum çerezlerini canlı tutmak için 
geliştirilmiştir.

Mimarisi:
- ASP.NET WebForms dinamik durum parametrelerini (__VIEWSTATE, __EVENTVALIDATION,
  __VIEWSTATEGENERATOR) otomatik yakalar ve istek başlıklarında gönderir.
- e-Devlet girişi sonrası alınan oturum çerezlerini (ASP.NET_SessionId, iskur_cookie)
  destekler ve periyodik keep-alive (ping) ile oturumun zaman aşımına uğramasını engeller.
- İl (örneğin Tekirdağ=59), İşyeri Türü (Kamu/Özel) ve Anahtar Kelime filtreleri sunar.
"""

import logging
import re
from typing import List, Dict, Any, Optional
import requests
from bs4 import BeautifulSoup

# Log yapılandırması - Türkçe ve anlaşılır log mesajları için
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("IskurScraper")


class IskurScraper:
    """
    İŞKUR e-Şube web kazıma ve oturum yönetimi sınıfı.
    
    Özellikler:
    1. Otomatik ASP.NET ViewState ve EventValidation takibi.
    2. İl, ilçe, çalışma türü ve arama terimine göre ilan arama.
    3. e-Devlet oturum çerezlerini yükleyerek yetkili istek atabilme.
    4. Periyodik canlı tutma (Keep-Alive) ile oturum süresini uzatma.
    """

    BASE_URL = "https://esube.iskur.gov.tr/Istihdam/AcikIsIlanAra.aspx"
    DETAIL_URL = "https://esube.iskur.gov.tr/Istihdam/AcikIsIlanDetay.aspx"

    # Şehir Kod Haritası (Sık kullanılan iller ve genel kodlar)
    CITY_CODES = {
        "TÜMÜ": "",
        "TEKİRDAĞ": "59",
        "İSTANBUL (ANADOLU)": "34",
        "İSTANBUL (AVRUPA)": "34",
        "ANKARA": "6",
        "İZMİR": "35",
        "BURSA": "16",
        "KOCAELİ": "41"
    }

    def __init__(self, cookies: Optional[Dict[str, str]] = None):
        """
        Scraper oturumunu ve HTTP istemcisini başlatır.
        
        :param cookies: (İsteğe bağlı) e-Devlet oturum çerezleri dict formatında.
        """
        self.session = requests.Session()
        # Gerçek bir tarayıcı süsü vermek için gelişmiş HTTP başlıkları (Header Spoofing)
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        })
        
        # Kullanıcı e-Devlet çerezlerini verdiyse oturuma ekle
        if cookies:
            self.session.cookies.update(cookies)
            logger.info("e-Devlet oturum çerezleri HTTP istemcisine başarıyla aktarıldı.")

        self._viewstate: str = ""
        self._eventvalidation: str = ""
        self._viewstategenerator: str = ""

    def initialize_session(self) -> bool:
        """
        İŞKUR arama sayfasını ilk defa çağırarak ASP.NET ViewState ve çerezleri alır.
        
        :return: Oturum başarıyla başlatıldıysa True, aksi halde False.
        """
        try:
            logger.info("İŞKUR ana arama sayfasına bağlantı kuruluyor...")
            response = self.session.get(self.BASE_URL, timeout=15)
            response.raise_for_status()

            # HTML içeriğini ayrıştır ve ASP.NET gizli alanlarını yakala
            soup = BeautifulSoup(response.text, "html.parser")
            
            vs_input = soup.find("input", {"id": "__VIEWSTATE"})
            ev_input = soup.find("input", {"id": "__EVENTVALIDATION"})
            vsg_input = soup.find("input", {"id": "__VIEWSTATEGENERATOR"})

            self._viewstate = vs_input.get("value", "") if vs_input else ""
            self._eventvalidation = ev_input.get("value", "") if ev_input else ""
            self._viewstategenerator = vsg_input.get("value", "") if vsg_input else ""

            logger.info(f"Oturum başlatıldı. ViewState Uzunluğu: {len(self._viewstate)} karakter.")
            return True

        except Exception as err:
            logger.error(f"İŞKUR oturumu başlatılırken hata oluştu: {err}", exc_info=True)
            return False

    def search_jobs(
        self,
        city_code: str = "",
        city_codes: Optional[List[str]] = None,
        isyeri_turu: str = "kamu",
        keyword: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Belirtilen kriterlere göre İŞKUR ilanlarında arama gerçekleştirir.
        Çoklu il seçimi desteklenmektedir.
        
        :param city_code: İl plaka kodu (örneğin Tekirdağ için '59', hepsi için '').
        :param city_codes: Çoklu il seçimi listesi (örneğin ['59', '34']).
        :param isyeri_turu: 'kamu' (Kamu İlanları), 'ozel' (Özel Sektör) veya 'tumu'.
        :param keyword: Aranan pozisyon, meslek veya kelime.
        :return: Ayrıştırılmış ilan listesi (dict nesneleri içeren liste).
        """
        # Çoklu şehir listesi verildiyse her şehir için arama yapıp birleştir
        if city_codes and len(city_codes) > 1:
            all_results: List[Dict[str, Any]] = []
            seen_no = set()
            for code in city_codes:
                if code == "0":
                    continue
                res = self.search_jobs(city_code=code, isyeri_turu=isyeri_turu, keyword=keyword)
                for item in res:
                    j_no = item.get("job_no")
                    if j_no and j_no not in seen_no:
                        seen_no.add(j_no)
                        all_results.append(item)
            return all_results

        # Tekil il kodu belirleme
        # NOT: İŞKUR formunda ctlIl='' değeri "--Tüm İller--" anlamına gelir.
        target_code = city_code
        if city_codes and len(city_codes) == 1:
            target_code = "" if city_codes[0] == "0" else city_codes[0]

        # ÖNEMLİ: İŞKUR formunda yalnızca iki radyo seçeneği vardır:
        #   ozelSektorRadio (Özel Sektör) ve kamuRadio (Kamu).
        # "Tümü" diye bir radyo YOKTUR. Bu yüzden "tumu" seçildiğinde iki ayrı
        # arama yapılır ve sonuçlar ilan numarasına göre tekilleştirilerek birleştirilir.
        if isyeri_turu.lower() in ("tumu", "tümü", "all"):
            merged: List[Dict[str, Any]] = []
            seen_no = set()
            for tur in ("kamu", "ozel"):
                for item in self._search_single(target_code, tur, keyword):
                    j_no = item.get("job_no")
                    if j_no and j_no not in seen_no:
                        seen_no.add(j_no)
                        merged.append(item)
            logger.info(f"'Tümü' kapsamı için kamu + özel sektör birleştirildi: {len(merged)} ilan.")
            return merged

        return self._search_single(target_code, isyeri_turu, keyword)

    def _search_single(self, target_code: str, isyeri_turu: str, keyword: str) -> List[Dict[str, Any]]:
        """
        Tek bir işyeri türü (kamu veya özel) için arama yapar.
        search_jobs() tarafından çağrılır.
        """
        # Eğer ViewState henüz çekilmediyse oturumu başlat
        if not self._viewstate:
            if not self.initialize_session():
                return []

        # İşyeri Türü Radio Buton seçimi
        radio_value = "kamuRadio"
        if isyeri_turu.lower() in ("ozel", "özel"):
            radio_value = "ozelSektorRadio"

        # ASP.NET Postback veri paketi (Form verisi)
        payload = {
            "__EVENTTARGET": "ctl04$ctlAcikIsPageCommand$CommandItem_Search",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": self._viewstate,
            "__VIEWSTATEGENERATOR": self._viewstategenerator,
            "__EVENTVALIDATION": self._eventvalidation,
            "ctl04$ctlArananMetin2": keyword,
            "ctl04$IsyeriTuruRadios": radio_value,
            "ctl04$ctlIl": str(target_code),
            "ctl04$ctlIlce": "",
            "ctl04$ctlMeslek$ctlMeslek_TextBox": "",
            "ctl04$ctlCalismaPeryodu": "",
            "ctl04$ctlIlanTarihi": "",
        }

        try:
            logger.info(f"Arama yapılıyor -> Şehir Kodu: '{target_code}', Tür: '{isyeri_turu}', Kelime: '{keyword}'")
            response = self.session.post(self.BASE_URL, data=payload, timeout=20)
            response.raise_for_status()

            # Sonraki aramalar için güncel ViewState bilgisini kaydet
            soup = BeautifulSoup(response.text, "html.parser")
            vs_input = soup.find("input", {"id": "__VIEWSTATE"})
            if vs_input and vs_input.get("value"):
                self._viewstate = vs_input.get("value")
            ev_input = soup.find("input", {"id": "__EVENTVALIDATION"})
            if ev_input and ev_input.get("value"):
                self._eventvalidation = ev_input.get("value")

            # İlan tablosunu ayrıştır
            return self._parse_job_grid(soup)

        except Exception as err:
            logger.error(f"İlan araması gerçekleştirilirken hata oluştu: {err}", exc_info=True)
            return []

    def _parse_job_grid(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        Arama sonucu dönen HTML tablosunu (Grid) okuyarak ilan bilgilerini yapılandırır.
        
        :param soup: BeautifulSoup HTML nesnesi.
        :return: İlan sözlük listesi.
        """
        job_list: List[Dict[str, Any]] = []

        # İlan tablosu 'ctl04_ctlGridAcikIslerListeDetail' ID'si ile oluşur
        grid_table = soup.find("table", {"id": re.compile(r"GridAcikIslerListeDetail", re.I)})
        if not grid_table:
            logger.info("Arama sonucunda tablo bulunamadı (Uygun kayıt olmayabilir).")
            return job_list

        rows = grid_table.find_all("tr")
        logger.info(f"İlan tablosunda toplam {len(rows)} satır bulundu.")

        for row in rows:
            cells = row.find_all("td")
            if not cells or len(cells) < 3:
                continue

            row_text = row.text

            # 11 haneli İlan Numarasını Regex ile çek (örneğin 00009850708)
            job_no_match = re.search(r"\b0000\d{7}\b", row_text)
            if not job_no_match:
                continue
            job_no = job_no_match.group(0)

            # Pozisyon Unvanı (Hücre 0)
            cell0_text = cells[0].text.strip()
            # Unvanın ilk satırı başlık olarak alınır
            title = cell0_text.split("\n")[0].strip() if cell0_text else "Belirtilmemiş Pozisyon"

            # Çalışma Yeri / Şehir - İlçe (Hücre 1)
            cell1_text = cells[1].text.strip() if len(cells) > 1 else ""
            location_match = re.search(r"\(Çalışma Yeri:\s*([^\)]+)\)", cell1_text, re.IGNORECASE)
            location = location_match.group(1).strip() if location_match else cell1_text

            # Son Başvuru Tarihi ve Kalan Gün (Hücre 2)
            cell2_text = cells[2].text.strip() if len(cells) > 2 else ""
            date_match = re.search(r"(\d{1,2}\.\d{1,2}\.\d{4})", cell2_text)
            deadline = date_match.group(1) if date_match else "Belirtilmedi"

            # Doğrudan İlan Detay Linki
            detail_url = f"{self.DETAIL_URL}?uiID={job_no}"

            job_item = {
                "job_no": job_no,
                "title": title,
                "location": location,
                "deadline": deadline,
                "detail_url": detail_url,
                "raw_summary": f"{title} - {location}"
            }

            job_list.append(job_item)

        logger.info(f"Toplam {len(job_list)} adet geçerli iş ilanı ayrıştırıldı.")
        return job_list

    def get_job_detail(self, job_no: str) -> Optional[Dict[str, Any]]:
        """
        Belirli bir ilan numarasına ait detaylı açıklamayı ve nitelikleri çeker.
        
        :param job_no: İlan Numarası (örneğin '00009850708').
        :return: İlan detay verisi veya Hata durumunda None.
        """
        try:
            url = f"{self.DETAIL_URL}?uiID={job_no}"
            response = self.session.get(url, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # 1. Genel Hususlar ve Özel Şartlar / İlan Açıklaması
            desc_text = ""
            container = soup.find(lambda e: e.name in ['td', 'div', 'span'] and 'Genel Hususlar ve Özel Şartlar' in e.text)
            if container:
                full = container.text.strip()
                parts = full.split('Genel Hususlar ve Özel Şartlar')
                if len(parts) > 1:
                    raw_desc = parts[1].strip()
                    lines = [line.strip() for line in raw_desc.split('\n') if line.strip()]
                    desc_text = "\n".join(lines[:8])

            # 2. Öğrenim Durumu (Asgari - Azami)
            asgari = soup.find('span', {'id': re.compile('ctlOgrenimAsgari', re.I)})
            azami = soup.find('span', {'id': re.compile('ctlOgrenimAzami', re.I)})
            education = ""
            if asgari or azami:
                ed_asg = asgari.text.strip() if asgari else ""
                ed_azm = azami.text.strip() if azami else ""
                education = f"{ed_asg} - {ed_azm}".strip(" -")

            return {
                "job_no": job_no,
                "detail_url": url,
                "description": desc_text if desc_text else "Açıklama belirtilmemiş.",
                "education": education if education else "Belirtilmedi"
            }

        except Exception as err:
            logger.error(f"İlan detay çekilirken hata oluştu ({job_no}): {err}")
            return None

    def ping_session(self) -> bool:
        """
        e-Devlet veya normal ASP.NET oturumunu canlı tutmak için hafif bir HTTP isteği gönderir.
        ASP.NET varsayılan oturum süresi 20 dakikadır. Her 5 dakikada bir çağrılarak
        oturumun düşmesi engellenir.
        
        :return: Oturum canlıysa True, aksi halde False.
        """
        try:
            logger.info("Oturum canlı tutma (Keep-Alive Ping) isteği gönderiliyor...")
            response = self.session.get(self.BASE_URL, timeout=10)
            return response.status_code == 200
        except Exception as err:
            logger.warning(f"Oturum ping isteği başarısız oldu: {err}")
            return False
