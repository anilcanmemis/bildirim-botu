"""
===============================================================================
SBB Kamu İlan Portalı Scraper Modülü (sbb_scraper.py)
===============================================================================

Bu modül, T.C. Cumhurbaşkanlığı Strateji ve Bütçe Başkanlığı (SBB) Resmi Kamu 
Personel Alım Portalı (`kamuilan.sbb.gov.tr`) üzerindeki tüm memur, sözleşmeli 
personel, uzman yardımcısı, hakim/savcı, askeri ve akademik alım ilanlarını 
otomatik olarak tarar ve ayrıştırır.
"""

import hashlib
import logging
import re
import urllib.parse
from typing import List, Dict, Any, Optional
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SbbScraper")


class SbbScraper:
    """
    SBB Resmi Kamu İlan Portalı web kazıma sınıfı.
    """

    BASE_URL = "https://kamuilan.sbb.gov.tr/"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://kamuilan.sbb.gov.tr/"
        })

    def fetch_public_jobs(self) -> List[Dict[str, Any]]:
        """
        SBB portalındaki en güncel resmi kamu memur alım ilanlarını çeker.
        
        :return: İlan sözlükleri içeren liste.
        """
        job_list: List[Dict[str, Any]] = []

        try:
            logger.info("SBB Resmi Kamu İlan Portalı taranıyor (kamuilan.sbb.gov.tr)...")
            response = self.session.get(self.BASE_URL, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            job_links = soup.find_all("a", href=re.compile(r"ilanDetay\.aspx\?kod=", re.I))

            logger.info(f"SBB sayfasında {len(job_links)} adet resmi kamu ilanı linki tespit edildi.")

            for a in job_links:
                title = a.text.strip()
                href = a.get("href", "")
                
                # Link oluşturma
                if not href.startswith("http"):
                    detail_url = f"{self.BASE_URL}{href}"
                else:
                    detail_url = href

                # SBB portalında 'kod=' parametresi her sayfa yenilemede dinamik üretildiği için
                # mükerrerliği engellemek amacıyla ilan başlığından sabit MD5 hash ID türetilir.
                clean_title_key = re.sub(r'\s+', ' ', title.strip().upper())
                title_hash = hashlib.md5(clean_title_key.encode('utf-8')).hexdigest()[:12]
                job_no = f"SBB_{title_hash}"

                if len(title) > 8 and not any(j["job_no"] == job_no for j in job_list):
                    job_item = {
                        "job_no": job_no,
                        "title": title,
                        "location": "TÜRKİYE GENELİ / KAMU KURUMU",
                        "deadline": "İlan Detayında Belirtildi",
                        "detail_url": detail_url,
                        "source": "SBB Kamu İlan Portalı (Resmi)",
                        "raw_summary": title
                    }
                    job_list.append(job_item)

            logger.info(f"SBB portalından {len(job_list)} adet benzersiz kamu ilanı ayrıştırıldı.")
            return job_list

        except Exception as err:
            logger.error(f"SBB portalı taranırken hata oluştu: {err}", exc_info=True)
            return job_list
