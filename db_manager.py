"""
===============================================================================
İŞKUR & SBB SQLite Veritabanı ve Kullanıcı Yönetim Modülü (db_manager.py)
===============================================================================

Bu modül, çekilen tüm iş ve memur ilanlarını ve yetkili Telegram kullanıcılarını 
SQLite veritabanında (jobs.db) saklar. Mükerrer bildirim engelleme ve admin/kullanıcı 
yetkilendirme yönetimini sağlar.
"""

import sqlite3
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = logging.getLogger("DBManager")


class DBManager:
    """
    SQLite Veritabanı ve Kullanıcı Yetkilendirme Yöneticisi Sınıfı.
    """

    DB_FILE = "jobs.db"

    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """
        İlanlar ve Yetkili Kullanıcılar tablolarını oluşturur.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # İlanlar Tablosu
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS jobs (
                        job_no TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        location TEXT,
                        education TEXT,
                        deadline TEXT,
                        source TEXT,
                        description TEXT,
                        detail_url TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC)")

                # Yetkili Kullanıcılar Tablosu
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        telegram_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        role TEXT DEFAULT 'user',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Telegram Güncellemeleri / Atomik Mükerrer Mesaj Engelleme Tablosu
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS telegram_updates (
                        update_id INTEGER PRIMARY KEY,
                        processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
            logger.info("SQLite veritabanı (jobs.db - jobs, users & telegram_updates) başarıyla hazırlandı.")
        except Exception as err:
            logger.error(f"Veritabanı oluşturulurken hata: {err}")

    # =========================================================================
    # 📌 İLAN YÖNETİMİ & MÜKERRER KONTROLÜ
    # =========================================================================

    def is_job_seen(self, job_no: str) -> bool:
        """
        İlanın veritabanında daha önce kaydedilip bildirilmediğini kontrol eder.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM jobs WHERE job_no = ?", (job_no,))
                return cursor.fetchone() is not None
        except Exception as err:
            logger.error(f"İlan mükerrer kontrolü hatası ({job_no}): {err}")
            return False

    def save_job(self, job: Dict[str, Any]) -> bool:
        """
        İlanı SQLite veritabanına ekler veya günceller.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO jobs 
                    (job_no, title, location, education, deadline, source, description, detail_url, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    str(job.get("job_no", "")),
                    str(job.get("title", "")),
                    str(job.get("location", "")),
                    str(job.get("education", "Belirtilmedi")),
                    str(job.get("deadline", "")),
                    str(job.get("source", "")),
                    str(job.get("description", "")),
                    str(job.get("detail_url", "")),
                    datetime.now().isoformat()
                ))
                conn.commit()
            return True
        except Exception as err:
            logger.error(f"İlan SQLite'a kaydedilirken hata ({job.get('job_no')}): {err}")
            return False

    def get_job(self, job_no: str) -> Optional[Dict[str, Any]]:
        """
        İlan Numarasına göre ilanın tüm detaylarını getirir.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM jobs WHERE job_no = ? OR job_no LIKE ?", (job_no, f"%{job_no}%"))
                row = cursor.fetchone()
                if row:
                    return dict(row)
        except Exception as err:
            logger.error(f"İlan SQLite'tan çekilirken hata ({job_no}): {err}")
        return None

    def get_recent_jobs(self, limit: int = 5) -> List[Dict[str, Any]]:
        """
        En son eklenen ilanları listeler.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as err:
            logger.error(f"Son ilanlar çekilirken hata: {err}")
            return []

    # =========================================================================
    # 👥 KULLANICI & YETKİLENDİRME YÖNETİMİ
    # =========================================================================

    def add_user(self, telegram_id: str, name: str, role: str = "user") -> bool:
        """
        Sisteme yeni bir yetkili Telegram kullanıcısı ekler.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO users (telegram_id, name, role, created_at)
                    VALUES (?, ?, ?, ?)
                """, (str(telegram_id), name, role, datetime.now().isoformat()))
                conn.commit()
            logger.info(f"Kullanıcı eklendi: {name} (ID: {telegram_id}, Rol: {role})")
            return True
        except Exception as err:
            logger.error(f"Kullanıcı eklenirken hata ({telegram_id}): {err}")
            return False

    def remove_user(self, telegram_id: str) -> bool:
        """
        Sistemden yetkili kullanıcıyı siler.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM users WHERE telegram_id = ?", (str(telegram_id),))
                conn.commit()
            logger.info(f"Kullanıcı yetkisi kaldırıldı: ID {telegram_id}")
            return True
        except Exception as err:
            logger.error(f"Kullanıcı silinirken hata ({telegram_id}): {err}")
            return False

    def is_user_authorized(self, telegram_id: str, admin_id: str = "") -> bool:
        """
        Kullanıcının sisteme erişim yetkisi olup olmadığını denetler.
        """
        str_id = str(telegram_id)
        if admin_id and str_id == str(admin_id):
            return True

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM users WHERE telegram_id = ?", (str_id,))
                return cursor.fetchone() is not None
        except Exception as err:
            logger.error(f"Yetki kontrolü hatası ({telegram_id}): {err}")
            return False

    def get_all_users(self) -> List[Dict[str, Any]]:
        """
        Tüm kayıtlı yetkili kullanıcıları döndürür.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users ORDER BY created_at ASC")
                return [dict(row) for row in cursor.fetchall()]
        except Exception as err:
            logger.error(f"Kullanıcılar çekilirken hata: {err}")
            return []

    # =========================================================================
    # ⚡ TELEGRAM GÜNCELLEME ATOMİK MÜKERRER KİLİT YÖNETİMİ
    # =========================================================================

    def mark_update_processed(self, update_id: int) -> bool:
        """
        Telegram update_id değerini veritabanına kaydeder.
        Eğer bu update_id daha önce işlenmişse False döndürür (mükerrer yanıt engellenir).
        İlk defa işleniyorsa True döndürür.
        """
        if not update_id:
            return True
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO telegram_updates (update_id, processed_at) VALUES (?, ?)",
                    (int(update_id), datetime.now().isoformat())
                )
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            logger.info(f"🛡️ Mükerrer Telegram update_id engellendi (Diğer bot örneği yanıtladı): {update_id}")
            return False
        except Exception as err:
            logger.error(f"update_id veritabanına işlenirken hata ({update_id}): {err}")
            return True
