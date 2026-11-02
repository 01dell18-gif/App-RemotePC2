"""
FYJ Channel Remote - Universal Smart Launcher
Menjalankan FYJ Remote secara cerdas di perangkat mana pun:
- Jika belum ada Master Server di LAN: Berjalan sebagai Master Server Gateway & membuka dashboard web.
- Jika sudah ada Master Server di LAN: Otomatis menghubungkan agen klien ke Master & membuka dashboard.
- Mendukung argumen '--master' atau '--agent' jika ingin memaksakan mode tertentu.
"""

import os
import sys
import time
import json
import socket
import webbrowser
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def check_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        res = s.connect_ex((host, port))
        s.close()
        return res == 0
    except Exception:
        return False

def discover_lan_master(timeout_sec: float = 1.5) -> dict:
    """Mendengarkan siaran beacon UDP dari Master Server di jaringan LAN."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout_sec)
    
    # Broadcast discovery query
    try:
        sock.bind(("", 0))
        sock.sendto(json.dumps({"type": "DISCOVER_MASTER"}).encode("utf-8"), ("255.255.255.255", 8889))
    except Exception:
        pass

    start = time.time()
    while time.time() - start < timeout_sec:
        try:
            data, addr = sock.recvfrom(2048)
            msg = json.loads(data.decode("utf-8", errors="ignore"))
            if msg.get("type") in ("FYJ_BEACON", "MASTER_REPLY"):
                server_ip = msg.get("server_ip") or addr[0]
                http_port = msg.get("http_port", 8080)
                ws_port = msg.get("ws_port", 8081)
                
                # Pastikan bukan beacon dari IP lokal sendiri
                if server_ip not in ("127.0.0.1", "localhost"):
                    sock.close()
                    return {
                        "server_ip": server_ip,
                        "http_url": f"http://{server_ip}:{http_port}",
                        "ws_url": f"ws://{server_ip}:{ws_port}"
                    }
        except socket.timeout:
            break
        except Exception:
            break
    sock.close()
    return {}

def run_as_master():
    print("=" * 70)
    print("   👑 FYJ CHANNEL REMOTE - MODE: MASTER SERVER CONTROLLER")
    print("=" * 70)
    print(" [*] Memulai Gateway Server...")
    
    server_script = os.path.join(BASE_DIR, "server", "server.py")
    
    # Buka browser setelah server mulai
    def _open_ui():
        time.sleep(1.2)
        webbrowser.open("http://localhost:8080")
    
    import threading
    threading.Thread(target=_open_ui, daemon=True).start()

    # Jalankan server.py secara langsung di thread utama
    try:
        subprocess.run([sys.executable, "-u", server_script], cwd=BASE_DIR)
    except KeyboardInterrupt:
        print("\n[!] Master Server dihentikan.")

def run_as_agent(master_info: dict):
    print("=" * 70)
    print("   💻 FYJ CHANNEL REMOTE - MODE: CLIENT AGENT")
    print("=" * 70)
    print(f" [+] Ditemukan Master Server di LAN: {master_info['http_url']}")
    print(f" [*] Menghubungkan ke WebSocket Hub: {master_info['ws_url']}")
    
    agent_script = os.path.join(BASE_DIR, "agent", "fyj_agent.py")
    
    # Buka dashboard di browser
    try:
        webbrowser.open(master_info["http_url"])
    except Exception:
        pass
    
    try:
        subprocess.run([
            sys.executable, "-u", agent_script,
            "--server", master_info["ws_url"],
            "--channel", "LAB-UTAMA"
        ], cwd=os.path.dirname(agent_script))
    except KeyboardInterrupt:
        print("\n[!] Client Agent dihentikan.")

def main():
    force_master = "--master" in sys.argv
    force_agent = "--agent" in sys.argv

    if force_master:
        run_as_master()
        return

    if force_agent:
        master_info = discover_lan_master(timeout_sec=2.0)
        if master_info:
            run_as_agent(master_info)
        else:
            print("[!] Tidak ditemukan Master Server di LAN. Menjalankan agen dengan server localhost...")
            run_as_agent({"http_url": "http://localhost:8080", "ws_url": "ws://127.0.0.1:8081"})
        return

    # 1. Cek apakah Master Server lokal sudah berjalan
    if check_port_open("127.0.0.1", 8080) and check_port_open("127.0.0.1", 8081):
        print("[+] Master Server sudah aktif di komputer ini.")
        print("[*] Membuka Web Dashboard di browser...")
        webbrowser.open("http://localhost:8080")
        return

    # 2. Cari apakah ada Master Server aktif di jaringan LAN
    print("[*] Memindai jaringan LAN untuk Master Server...")
    master_info = discover_lan_master(timeout_sec=1.5)

    if master_info:
        run_as_agent(master_info)
    else:
        run_as_master()

if __name__ == "__main__":
    main()

