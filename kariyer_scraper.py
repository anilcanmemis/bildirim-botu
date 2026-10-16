"""
===============================================================================
Kariyer.net Özel Sektör ve Kurumsal İlan Scraper Modülü (kariyer_scraper.py)
===============================================================================

Bu modül, Türkiye'nin lider insan kaynakları ve istihdam platformu olan 
Kariyer.net (`kariyer.net`) üzerindeki kurumsal özel sektör iş ilanlarını 
şehir ve anahtar kelime bazlı olarak otomatik olarak tarar ve ayrıştırır.
"""

import logging
import re
import unicodedata
from typing import List, Dict, Any, Optional
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("KariyerScraper")


def city_to_slug(city_name: str) -> str:
    """
    Türkçe şehir adını Kariyer.net URL formatına (slug) dönüştürür.
    Örn: 'Tekirdağ' -> 'tekirdag', 'İstanbul' -> 'istanbul'
    """
    if not city_name or city_name.strip() in ["Tüm Türkiye", "0", ""]:
        return ""
    
    name = city_name.strip()
    # Türkçe özel harf dönüşümleri
    tr_map = {
        'ı': 'i', 'I': 'i', 'İ': 'i', 'i': 'i',
        'ş': 's', 'Ş': 's',
        'ğ': 'g', 'Ğ': 'g',
        'ü': 'u', 'Ü': 'u',
        'ö': 'o', 'Ö': 'o',
        'ç': 'c', 'Ç': 'c'
    }
    for k, v in tr_map.items():
        name = name.replace(k, v)
    
    slug = re.sub(r'[^a-zA-Z0-9]+', '-', name.lower()).strip('-')
    return slug


class KariyerScraper:
    """
    Kariyer.net Özel Sektör ve Kurumsal İlan Kazıma Sınıfı.
    """

    BASE_URL = "https://www.kariyer.net"

    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*"
        }

    def search_jobs(self, city_names: Optional[List[str]] = None, keyword: str = "") -> List[Dict[str, Any]]:
        """
        Kariyer.net üzerinden güncel iş ilanlarını tarar.
        
        :param city_names: Aranacak şehir adları listesi (Örn: ['Tekirdağ', 'İstanbul']).
        :param keyword: Aranacak pozisyon anahtar kelimesi.
        :return: İlan sözlükleri listesi.
        """
        job_list: List[Dict[str, Any]] = []
        seen_ids = set()

        # Taranacak URL listesini oluştur
        target_urls = []
        if city_names:
            for c_name in city_names:
                slug = city_to_slug(c_name)
                if slug:
                    target_urls.append((f"{self.BASE_URL}/is-ilanlari/{slug}", c_name))
        
        # Eğer şehir listesi boşsa veya "Tüm Türkiye" ise genel sayfayı tara
        if not target_urls:
            target_urls.append((f"{self.BASE_URL}/is-ilanlari", "Türkiye Geneli"))

        logger.info(f"Kariyer.net taranıyor ({len(target_urls)} farklı lokasyon/sayfa)...")

        for target_url, loc_name in target_urls:
            try:
                resp = requests.get(target_url, headers=self.headers, timeout=12)
                if resp.status_code != 200:
                    logger.warning(f"Kariyer.net yanıt kodu {resp.status_code}: {target_url}")
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                links = soup.find_all("a", href=re.compile(r"/is-ilani/.*-(\d+)$"))

                for a in links:
                    href = a.get("href", "")
                    m = re.search(r"-(\d+)$", href)
                    if not m:
                        continue

                    ad_id = m.group(1)
                    if ad_id in seen_ids:
                        continue
                    seen_ids.add(ad_id)

                    # Kart içerisindeki metinleri ayrıştır
                    items = [s.strip() for s in a.stripped_strings if s.strip() not in ["Sponsorlu İlan", "Yeni İlan", "update", "İş Yerinde", "Hibrit", "Uzaktan"] and not s.strip().startswith("Ort.")]
                    # Tek harfli veya çok kısa sembolleri baştan temizle
                    while items and len(items[0]) <= 2:
                        items.pop(0)

                    if len(items) < 2:
                        continue

                    pos_title = items[0]
                    company_name = items[1] if len(items) > 1 else "Kurumsal Firma"
                    job_location = items[2] if len(items) > 2 else loc_name

                    full_title = f"{pos_title} ({company_name})"
                    detail_url = f"{self.BASE_URL}{href}" if href.startswith("/") else href
                    job_no = f"KARIYER_{ad_id}"

                    job_item = {
                        "job_no": job_no,
                        "title": full_title,
                        "location": job_location,
                        "education": "İlan Detayında Belirtildi",
                        "deadline": "Kariyer.net Aktif İlan",
                        "detail_url": detail_url,
                        "source": "Kariyer.net Özel Sektör",
                        "description": f"Pozisyon: {pos_title}\nFirma: {company_name}\nLokasyon: {job_location}"
                    }
                    job_list.append(job_item)

            except Exception as err:
                logger.error(f"Kariyer.net sayfası taranırken hata ({target_url}): {err}")

        logger.info(f"Kariyer.net üzerinden toplam {len(job_list)} adet güncel iş ilanı ayrıştırıldı.")
        return job_list
