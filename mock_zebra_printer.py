"""
Zebra Yazıcı Simülatörü (Mock Zebra Printer Server)
---------------------------------------------------
Bu modül, fiziksel bir Zebra yazıcının TCP 9100 (RAW Port) davranışını taklit eder.
Ağda gerçek bir Zebra yazıcı bulunmadığı durumlarda Telegram Botunun sorunsuz
test edilebilmesi için bir sanal yazıcı soketi oluşturur.
"""

import socket
import sys

# Windows konsol çıktıları için UTF-8 yapılandırması
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

HOST = "127.0.0.1"
PORT = 9100


def start_mock_printer(host: str = HOST, port: int = PORT) -> None:
    """
    Sanal Zebra yazıcı TCP sunucusunu başlatır.
    """
    print("==================================================")
    print("SANAL ZEBRA YAZICI SIMULATORU BASLATILIYOR...")
    print(f"Adres: {host}:{port}")
    print("Bot uzerinden IP olarak '127.0.0.1' girerek test edebilirsiniz.")
    print("==================================================\n")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            server_socket.bind((host, port))
            server_socket.listen()
            print("Sanal yazici baglantilari dinliyor...\n")
        except Exception as err:
            print(f"Soket baslatilirken hata olustu: {err}")
            sys.exit(1)

        while True:
            try:
                client_socket, client_address = server_socket.accept()
                print(f"Yeni baglanti kabul edildi: {client_address[0]}:{client_address[1]}")

                with client_socket:
                    client_socket.settimeout(5.0)
                    data = client_socket.recv(4096)

                    if not data:
                        continue

                    data_str = data.decode("utf-8", errors="ignore")

                    if "~HS" in data_str:
                        print("[DURUM SORGUSU] '~HS' (Host Status) komutu alindi.")
                        mock_hs_response = b"\x02020,0,0,0931,000,0,0,0,000,0,0,0\x03"
                        client_socket.sendall(mock_hs_response)
                        print("[YANIT] Sanal cevrimici durum yaniti bot'a iletildi.\n")
                    else:
                        print("[YAZDIRMA EMIRI] Gelen ZPL Verisi:")
                        print("-" * 40)
                        print(data_str.strip())
                        print("-" * 40)
                        print("[BASARILI] Etiket islendi ve simule edildi.\n")

            except socket.timeout:
                print("Zaman asimi uyarisi.")
            except KeyboardInterrupt:
                print("\nSanal yazici durduruluyor.")
                break
            except Exception as e:
                print(f"Baglanti islenirken hata: {e}")


if __name__ == "__main__":
    start_mock_printer()
