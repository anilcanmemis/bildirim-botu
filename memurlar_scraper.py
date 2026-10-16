"""
===============================================================================
Memurlar.net Kamu & Memur İlanları Scraper Modülü (memurlar_scraper.py)
===============================================================================

Bu modül, Türkiye'nin en köklü ve kapsamlı kamu personel alım platformu olan 
Memurlar.net (`ilan.memurlar.net`) üzerindeki KPSS-A, KPSS-B, sözleşmeli personel, 
işçi, akademik kadro, askeri ve belediye alım ilanlarını otomatik olarak 
tarar, ayrıştırır ve detaylarını çıkarır.
"""

import logging
import re
from typing import List, Dict, Any, Optional
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MemurlarScraper")


class MemurlarScraper:
    """
    Memurlar.net Resmi Kamu ve Memur İlanları web kazıma sınıfı.
    """

    BASE_URL = "https://ilan.memurlar.net"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://ilan.memurlar.net/"
        })

    def fetch_public_jobs(self) -> List[Dict[str, Any]]:
        """
        Memurlar.net portalındaki en güncel kamu ve memur alım ilanlarını çeker.
        
        :return: İlan sözlükleri içeren liste.
        """
        job_list: List[Dict[str, Any]] = []

        try:
            logger.info("Memurlar.net Kamu İlan Portalı taranıyor (ilan.memurlar.net)...")
            response = self.session.get(self.BASE_URL, timeout=15)
            response.raise_for_status()
            
            # Memurlar.net Türkçe karakter kodlaması windows-1254 veya iso-8859-9'dur
            response.encoding = "windows-1254"

            soup = BeautifulSoup(response.text, "html.parser")
            job_links = soup.find_all("a", href=re.compile(r"/ilan/(\d+)/", re.I))

            seen_ids = set()

            for a in job_links:
                href = a.get("href", "")
                m = re.search(r"/ilan/(\d+)/", href)
                if not m:
                    continue

                ad_id = m.group(1)
                if ad_id in seen_ids:
                    continue
                seen_ids.add(ad_id)

                # İlan başlığını temizle
                raw_title = a.get_text(separator=" ", strip=True)
                # Çift satır ve gereksiz boşlukları temizle
                clean_title = re.sub(r'\s+', ' ', raw_title).strip()

                if len(clean_title) < 6:
                    continue

                # Tam URL oluştur
                if href.startswith("//"):
                    detail_url = f"https:{href}"
                elif href.startswith("/"):
                    detail_url = f"{self.BASE_URL}{href}"
                elif not href.startswith("http"):
                    detail_url = f"{self.BASE_URL}/{href}"
                else:
                    detail_url = href

                job_no = f"MEMURLAR_{ad_id}"

                job_item = {
                    "job_no": job_no,
                    "title": clean_title,
                    "location": "KAMU KURUMLARI / TÜRKİYE GENELİ",
                    "education": "İlan Detayında Belirtildi",
                    "deadline": "İlan Metninde Belirtildi",
                    "detail_url": detail_url,
                    "source": "Memurlar.net Kamu",
                    "description": clean_title
                }
                job_list.append(job_item)

            logger.info(f"Memurlar.net portalından {len(job_list)} adet güncel kamu ilanı ayrıştırıldı.")
            return job_list

        except Exception as err:
            logger.error(f"Memurlar.net portalı taranırken hata oluştu: {err}", exc_info=True)
            return job_list

    def get_job_detail(self, job_no: str) -> Optional[Dict[str, Any]]:
        """
        Belirtilen ilanın detay sayfasına giderek ilan metnini çeker.
        """
        try:
            ad_id = job_no.replace("MEMURLAR_", "")
            detail_url = f"{self.BASE_URL}/ilan/{ad_id}/"
            resp = self.session.get(detail_url, timeout=12)
            if resp.status_code != 200:
                return None

            resp.encoding = "windows-1254"
            soup = BeautifulSoup(resp.text, "html.parser")
            
            article = soup.find("article") or soup.find("div", class_="content") or soup.find("div", id="content")
            if article:
                text_content = article.get_text(separator="\n", strip=True)
                return {"description": text_content[:3000]}
        except Exception as err:
            logger.error(f"Memurlar.net ilan detayı çekilirken hata ({job_no}): {err}")
        return None
