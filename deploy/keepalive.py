#!/usr/bin/env python3
"""
===============================================================================
Oracle Cloud Always Free - "Bosta Sayilma" (Idle Reclamation) Korumasi
===============================================================================

Oracle, Always Free sunuculari 7 gun boyunca "bosta" sayarsa geri alabilir.
Bosta sayilma kosullari (7 gun boyunca asagidakilerin HEPSI gecerliyse):
  - CPU kullaniminin 95. yuzdelik degeri %10'un altinda
  - Ag kullaniminin 95. yuzdelik degeri %10'un altinda
  - Bellek kullaniminin 95. yuzdelik degeri %20'nin altinda (ARM/A1 icin)

Bu script, cok hafif ve surekli bir CPU yuku ureterek sunucunun "bosta"
sayilmasini engeller. Varsayilan olarak toplam CPU'nun ~%15'ini kullanir.

Kullanim:
    python3 keepalive.py              # Varsayilan %15 yuk
    python3 keepalive.py --percent 20 # Yuk miktarini ayarla

Not: En temiz cozum Oracle hesabini "Pay As You Go" (kullandikca ode) seviyesine
yukseltmektir. Always Free limitleri icinde kalindigi surece ucret alinmaz ve
bosta sayilma geri alimi UYGULANMAZ.
===============================================================================
"""

import argparse
import os
import time

DEFAULT_PERCENT = 15.0
CYCLE_SECONDS = 1.0


def cpu_count() -> int:
    """Sunucudaki kullanilabilir CPU cekirdek sayisini dondurur."""
    try:
        return os.cpu_count() or 1
    except Exception:
        return 1


def run_keepalive(percent: float) -> None:
    """
    Surekli dongude, her saniyede belirtilen oranda CPU mesguliyeti uretir.

    :param percent: Toplam CPU'nun yuzde kaci mesgul edilecek (0-100).
    """
    cores = cpu_count()
    percent = max(1.0, min(95.0, percent))

    # Tek cekirdek uzerinden hesaplanan mesguliyet suresi
    busy_seconds = CYCLE_SECONDS * (percent / 100.0) * cores
    busy_seconds = min(busy_seconds, CYCLE_SECONDS)
    idle_seconds = CYCLE_SECONDS - busy_seconds

    print(
        f"[keepalive] Baslatildi. Cekirdek: {cores} | "
        f"Hedef yuk: toplam CPU'nun ~%{percent:.0f}'i | "
        f"dongu: {busy_seconds:.2f}s mesgul + {idle_seconds:.2f}s bekleme",
        flush=True,
    )

    while True:
        try:
            end = time.monotonic() + busy_seconds
            while time.monotonic() < end:
                # Hafif ama gercek CPU isi (optimize edilip atilmaz)
                sum(i * i for i in range(1000))
            if idle_seconds > 0:
                time.sleep(idle_seconds)
        except KeyboardInterrupt:
            print("[keepalive] Durduruldu.", flush=True)
            return
        except Exception as err:
            print(f"[keepalive] Hata: {err}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Oracle Cloud Always Free bosta sayilma korumasi"
    )
    parser.add_argument(
        "--percent",
        type=float,
        default=DEFAULT_PERCENT,
        help=f"Mesgul edilecek CPU yuzdesi (varsayilan: {DEFAULT_PERCENT})",
    )
    args = parser.parse_args()
    run_keepalive(args.percent)
