"""
FYJ Channel Remote - Central Gateway & Web Master Server
Mengelola komunikasi real-time antara Web Master (Browser Pengendali) dan Target Agent (PC Klien).
Mendukung Web Master Dashboard (Port 8080) dan WebSocket Relay Engine (Port 8081).
Mendukung Registrasi, Edit & Hapus Perangkat (Host Name, IP Address, MAC Address, Catatan).
Mendukung Manajemen Skrip Otomasi (PowerShell, CMD) & Eksekusi Terarah (Selected / All PCs).
"""

import os
import sys
import json
import time
import socket
import asyncio
import threading
import subprocess
import http.server
import urllib.parse
from typing import Dict, Set

try:
    import websockets
except ImportError:
    print("[ERROR] websockets module tidak ditemukan. Jalankan: pip install websockets")
    sys.exit(1)

# Konfigurasi Port
HTTP_PORT = 8080
WS_PORT = 8081
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "web"))
DB_FILE = os.path.join(BASE_DIR, "devices_db.json")
SCRIPTS_FILE = os.path.join(BASE_DIR, "scripts_db.json")

# Database Perangkat Persisten
def load_devices_db() -> dict:
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Gagal membaca {DB_FILE}: {e}")
    return {}

def save_devices_db(db: dict):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[!] Gagal menyimpan {DB_FILE}: {e}")

devices_db = load_devices_db()

# Database Skrip Otomasi Persisten
def load_scripts_db() -> list:
    if os.path.exists(SCRIPTS_FILE):
        try:
            with open(SCRIPTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Gagal membaca {SCRIPTS_FILE}: {e}")
    return []

def save_scripts_db(scripts: list):
    try:
        with open(SCRIPTS_FILE, "w", encoding="utf-8") as f:
            json.dump(scripts, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[!] Gagal menyimpan {SCRIPTS_FILE}: {e}")

scripts_db = load_scripts_db()

# Struktur Data In-Memory
class ChannelManager:
    def __init__(self):
        self.channels: Dict[str, dict] = {
            "LAB-UTAMA": {"masters": set(), "agents": {}},
            "LAB-DKV-1": {"masters": set(), "agents": {}},
            "RUANG-KELAS-A": {"masters": set(), "agents": {}},
        }
        self.lock = asyncio.Lock()

    def get_or_create_channel(self, channel_id: str):
        if channel_id not in self.channels:
            self.channels[channel_id] = {"masters": set(), "agents": {}}
        return self.channels[channel_id]

    def get_channel_devices(self, channel_id: str):
        """
        Menampilkan daftar perangkat SESUAI DENGAN DATA YANG DI-INPUT DI 'Data Perangkat & Jaringan' (devices_db).
        Setiap perangkat yang terdaftar strictly dikoneksikan ke datanya sendiri (IP & MAC).
        """
        ch = self.get_or_create_channel(channel_id)
        result = []

        # devices_db adalah sumber kebenaran tunggal (Source of Truth)
        for dev_id, dev_data in devices_db.items():
            dev_channel = dev_data.get("channel", "LAB-UTAMA")
            if dev_channel != channel_id:
                continue

            dev_mac = (dev_data.get("mac") or "").upper()
            dev_ip = dev_data.get("ip") or ""
            dev_name = dev_data.get("name", "Komputer")
            dev_host = dev_data.get("hostname", "")

            # Cek apakah ada agent WebSocket aktif yang strictly cocok dengan device ini
            active_agent = None
            if dev_id in ch["agents"]:
                active_agent = ch["agents"][dev_id]
            else:
                for a_id, a in ch["agents"].items():
                    a_info = a["info"]
                    if a_info.get("id") == dev_id:
                        active_agent = a
                        break

            if active_agent:
                info = dict(active_agent["info"])
                info["id"] = dev_id
                info["name"] = dev_name
                info["hostname"] = dev_host or info.get("hostname", "")
                info["ip"] = dev_ip or info.get("ip", "127.0.0.1")
                info["mac"] = dev_mac or info.get("mac", "00:00:00:00:00:00")
                info["notes"] = dev_data.get("notes", "")
                info["status"] = "online"
                info["channel"] = channel_id
                result.append(info)
            else:
                saved_status = dev_data.get("status", "offline")
                result.append({
                    "id": dev_id,
                    "name": dev_name,
                    "hostname": dev_host,
                    "ip": dev_ip or "127.0.0.1",
                    "mac": dev_mac or "00:00:00:00:00:00",
                    "notes": dev_data.get("notes", ""),
                    "status": saved_status,
                    "channel": channel_id,
                    "resolution": "1920x1080",
                    "mode": "thumbnail",
                    "is_locked": False,
                    "cpu": 0,
                    "ram": 0,
                    "active_window": "",
                    "connected_at": 0,
                    "last_seen": 0,
                    "os": "Windows"
                })
        return result

    def get_all_channels_summary(self):
        summary = {}
        for ch_id, ch_data in self.channels.items():
            devices = self.get_channel_devices(ch_id)
            online_count = sum(1 for d in devices if d.get("status") == "online")
            summary[ch_id] = {
                "agent_count": online_count,
                "total_devices": len(devices),
                "master_count": len(ch_data["masters"]),
                "agents": devices
            }
        return summary

channel_mgr = ChannelManager()
main_event_loop = None

def normalize_mac(mac: str) -> str:
    if not mac:
        return ""
    return mac.replace(":", "").replace("-", "").strip().upper()

def find_matching_device_id(agent_ip: str, agent_mac: str, agent_hostname: str) -> Optional[str]:
    """
    Kecocokan ketat (Strict Identity Match) antara connecting agent dengan entri di devices_db.
    Hanya mengembalikan device_id jika:
    1. MAC address sama persis (setelah dinormalisasi)
    2. ATAU IP address sama persis (dan bukan loopback 127.0.0.1)
    3. ATAU Hostname sama persis DAN IP address sama
    Jika tidak cocok dengan perangkat manapun di devices_db, return None.
    Mencegah perangkat lain atau PC lokal membajak data kartu perangkat lab!
    """
    clean_agent_mac = normalize_mac(agent_mac)
    agent_ip = (agent_ip or "").strip()
    agent_host = (agent_hostname or "").strip().lower()

    for dev_id, dev in devices_db.items():
        dev_mac = normalize_mac(dev.get("mac", ""))
        dev_ip = (dev.get("ip") or "").strip()
        dev_host = (dev.get("hostname") or "").strip().lower()

        # 1. Kecocokan MAC address (prioritas utama dan paling akurat)
        if clean_agent_mac and clean_agent_mac != "000000000000" and dev_mac and dev_mac != "000000000000":
            if clean_agent_mac == dev_mac:
                return dev_id

        # 2. Kecocokan IP address (bukan loopback)
        if agent_ip and dev_ip and not agent_ip.startswith("127.") and not dev_ip.startswith("127."):
            if agent_ip == dev_ip:
                return dev_id

        # 3. Kecocokan Hostname (hanya jika IP sama)
        if dev_host and agent_host and dev_host == agent_host:
            if agent_ip and dev_ip and agent_ip == dev_ip:
                return dev_id

    return None

def get_local_ips():
    ips = []
    # 1. Cari IP rute LAN utama yang terhubung ke jaringan aktif
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        main_lan_ip = s.getsockname()[0]
        s.close()
        if main_lan_ip and not main_lan_ip.startswith("127."):
            ips.append(main_lan_ip)
    except Exception:
        pass

    # 2. Tambahkan localhost loopback
    if "127.0.0.1" not in ips:
        ips.append("127.0.0.1")

    # 3. Cari IP interface jaringan lainnya (hindari duplikat)
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127.") and ip not in ips:
                # Prioritaskan IP non-VirtualBox di depan VirtualBox
                if not ip.startswith("192.168.56."):
                    ips.insert(1 if len(ips) > 1 else 0, ip)
                else:
                    ips.append(ip)
    except Exception:
        pass
    return ips

# --- PING & NETWORK REACHABILITY CHECKER ---
def check_host_ping(ip: str, timeout_ms: int = 1000) -> dict:
    if not ip or ip.strip() == "":
        return {"alive": False, "latency_ms": 0, "status": "IP Kosong", "is_local": False}
    
    ip = ip.strip()
    local_ips = get_local_ips()
    if ip in local_ips or ip in ("127.0.0.1", "localhost"):
        return {"alive": True, "latency_ms": 1, "status": "Online (Host Lokal)", "is_local": True}

    try:
        if sys.platform == "win32":
            cmd = ["ping", "-n", "1", "-w", str(timeout_ms), ip]
        else:
            cmd = ["ping", "-c", "1", "-W", "1", ip]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        stdout_upper = res.stdout.upper()

        # Pastikan tidak ada pesan host unreachable atau timeout
        has_error = (
            "DESTINATION HOST UNREACHABLE" in stdout_upper or
            "UNREACHABLE" in stdout_upper or
            "REQUEST TIMED OUT" in stdout_upper or
            "RTO" in stdout_upper or
            "100% LOSS" in stdout_upper or
            "100% HILANG" in stdout_upper
        )

        has_reply = (
            "TTL=" in stdout_upper or
            "REPLY FROM" in stdout_upper or
            "BALASAN DARI" in stdout_upper
        )

        alive = (res.returncode == 0) and has_reply and (not has_error)
        latency = 1

        if alive:
            for part in res.stdout.split():
                clean_p = part.lower().replace("ms", "").replace("<", "=")
                if "time=" in clean_p or "waktu=" in clean_p:
                    try:
                        num = clean_p.split("=")[-1].strip()
                        latency = max(1, int(num))
                    except Exception:
                        pass
            return {"alive": True, "latency_ms": latency, "status": f"Terhubung ({latency} ms)", "is_local": False}
    except Exception as e:
        print(f"[!] Error saat ping {ip}: {e}")

    return {"alive": False, "latency_ms": 0, "status": "Tidak Merespons (Offline)", "is_local": False}

def send_wake_on_lan(mac: str) -> bool:
    try:
        clean_mac = (mac or "").replace(":", "").replace("-", "").strip()
        if len(clean_mac) == 12:
            data = bytes.fromhex("FFFFFFFFFFFF" + clean_mac * 16)
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(data, ("255.255.255.255", 9))
            s.close()
            return True
    except Exception:
        pass
    return False

local_agent_proc = None

def ensure_local_agent_running():
    """
    HANYA menjalankan local agent jika komputer server ini terdaftar secara eksplisit
    di devices_db (berdasarkan IP LAN lokal atau MAC address fisik komputer ini).
    Jika TIDAK terdaftar di devices_db, komputer server HANYA bertindak sebagai Web Master Controller
    dan TIDAK AKAN menyiarkan layar master ke dashboard!
    """
    global local_agent_proc
    if local_agent_proc is not None and local_agent_proc.poll() is None:
        return

    # Cek apakah IP LAN lokal komputer ini terdaftar di devices_db
    local_ips = get_local_ips()
    is_registered = False
    for dev in devices_db.values():
        dev_ip = (dev.get("ip") or "").strip()
        if dev_ip in local_ips and not dev_ip.startswith("127."):
            is_registered = True
            break

    if not is_registered:
        return  # Jangan aktifkan local agent jika tidak terdaftar di Data Perangkat!

    agent_path = os.path.abspath(os.path.join(BASE_DIR, "..", "agent", "fyj_agent.py"))
    if os.path.exists(agent_path):
        try:
            kwargs = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            local_agent_proc = subprocess.Popen(
                [sys.executable, "-u", agent_path, "--channel", "LAB-UTAMA"],
                cwd=os.path.dirname(agent_path),
                **kwargs
            )
            print("[+] Local Agent background service aktif untuk PC lokal ini.")
        except Exception as e:
            print(f"[!] Gagal memulai local agent: {e}")

# --- HTTP Server untuk Web Master UI & REST API ---
class FYJHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            data = {
                "app": "FYJ Channel Remote",
                "version": "1.3.0",
                "status": "online",
                "ws_port": WS_PORT,
                "local_ips": get_local_ips(),
                "channels": channel_mgr.get_all_channels_summary(),
                "saved_devices": devices_db,
                "scripts_count": len(scripts_db)
            }
            self.wfile.write(json.dumps(data, indent=2).encode("utf-8"))
            return

        elif parsed.path == "/api/channels":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(channel_mgr.get_all_channels_summary(), indent=2).encode("utf-8"))
            return

        elif parsed.path == "/api/devices":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(devices_db, indent=2).encode("utf-8"))
            return

        elif parsed.path == "/api/scripts":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(scripts_db, indent=2).encode("utf-8"))
            return

        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("content-length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        if parsed.path == "/api/channels":
            ch_name = payload.get("channel_name", "").strip().upper()
            if ch_name:
                channel_mgr.get_or_create_channel(ch_name)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "channel": ch_name}).encode("utf-8"))
                return

        elif parsed.path == "/api/devices/check":
            ip = payload.get("ip", "").strip()
            mac = payload.get("mac", "").strip()
            if mac:
                send_wake_on_lan(mac)
            ping_res = check_host_ping(ip)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "ping": ping_res}).encode("utf-8"))
            return

        elif parsed.path == "/api/devices/connect":
            agent_id = payload.get("agent_id")
            channel_name = payload.get("channel", "LAB-UTAMA")
            ip = payload.get("ip", "").strip()
            mac = payload.get("mac", "").strip()

            if not ip and agent_id in devices_db:
                ip = devices_db[agent_id].get("ip", "")
            if not mac and agent_id in devices_db:
                mac = devices_db[agent_id].get("mac", "")

            if mac:
                send_wake_on_lan(mac)
            ping_res = check_host_ping(ip)
            is_alive = ping_res.get("alive", False)

            # Perbarui status di devices_db
            if agent_id in devices_db:
                devices_db[agent_id]["status"] = "online" if is_alive else "offline"
                save_devices_db(devices_db)

            # Beritahu semua master
            dev_info = {
                "id": agent_id,
                "name": devices_db.get(agent_id, {}).get("name", "Komputer"),
                "hostname": devices_db.get(agent_id, {}).get("hostname", ""),
                "ip": ip or "127.0.0.1",
                "mac": mac or "00:00:00:00:00:00",
                "notes": devices_db.get(agent_id, {}).get("notes", ""),
                "status": "online" if is_alive else "offline",
                "channel": channel_name,
                "cpu": 0, "ram": 0, "is_locked": False
            }
            if main_event_loop and not main_event_loop.is_closed():
                asyncio.run_coroutine_threadsafe(
                    notify_masters(channel_name, {"type": "agent_updated", "agent": dev_info}),
                    main_event_loop
                )

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True,
                "connected": is_alive,
                "ping": ping_res,
                "device": dev_info
            }).encode("utf-8"))
            return

        elif parsed.path == "/api/devices/disconnect":
            agent_id = payload.get("agent_id")
            channel_name = payload.get("channel", "LAB-UTAMA")

            # Jika agent aktif terhubung via WebSocket, putuskan
            ch = channel_mgr.get_or_create_channel(channel_name)
            if agent_id in ch["agents"]:
                ag_ws = ch["agents"][agent_id]["ws"]
                if main_event_loop and not main_event_loop.is_closed():
                    asyncio.run_coroutine_threadsafe(ag_ws.close(), main_event_loop)
                del ch["agents"][agent_id]

            if agent_id in devices_db:
                devices_db[agent_id]["status"] = "offline"
                save_devices_db(devices_db)

            dev_info = {
                "id": agent_id,
                "name": devices_db.get(agent_id, {}).get("name", "Komputer"),
                "hostname": devices_db.get(agent_id, {}).get("hostname", ""),
                "ip": devices_db.get(agent_id, {}).get("ip", "127.0.0.1"),
                "mac": devices_db.get(agent_id, {}).get("mac", "00:00:00:00:00:00"),
                "notes": devices_db.get(agent_id, {}).get("notes", ""),
                "status": "offline",
                "channel": channel_name,
                "cpu": 0, "ram": 0, "is_locked": False
            }
            if main_event_loop and not main_event_loop.is_closed():
                asyncio.run_coroutine_threadsafe(
                    notify_masters(channel_name, {"type": "agent_updated", "agent": dev_info}),
                    main_event_loop
                )

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "status": "offline", "device": dev_info}).encode("utf-8"))
            return

        elif parsed.path == "/api/devices/update":
            agent_id = payload.get("agent_id")
            old_agent_id = payload.get("old_agent_id") or agent_id
            name = payload.get("name", "Komputer").strip()
            hostname = payload.get("hostname", "").strip()
            ip = payload.get("ip", "").strip()
            mac = payload.get("mac", "").strip().upper()
            notes = payload.get("notes", "").strip()
            channel_name = payload.get("channel", "LAB-UTAMA").strip().upper()

            clean_mac = normalize_mac(mac)
            if clean_mac and clean_mac != "000000000000":
                canonical_id = f"pc_{clean_mac}"
            elif ip and not ip.startswith("127."):
                canonical_id = f"pc_{ip.replace('.', '_')}"
            elif hostname:
                canonical_id = f"pc_{hostname.replace(' ', '_')}"
            else:
                canonical_id = agent_id or f"dev_{int(time.time()*1000)%1000000}"

            # Hapus entry lama dari devices_db jika ID berubah
            if old_agent_id and old_agent_id != canonical_id and old_agent_id in devices_db:
                del devices_db[old_agent_id]
                if main_event_loop and not main_event_loop.is_closed():
                    asyncio.run_coroutine_threadsafe(
                        notify_masters(channel_name, {"type": "device_deleted", "agent_id": old_agent_id}),
                        main_event_loop
                    )

            if mac:
                send_wake_on_lan(mac)
            ping_res = check_host_ping(ip)
            is_alive = ping_res.get("alive", False)

            devices_db[canonical_id] = {
                "name": name,
                "hostname": hostname,
                "ip": ip,
                "mac": mac,
                "notes": notes,
                "channel": channel_name,
                "status": "online" if is_alive else "offline"
            }
            save_devices_db(devices_db)

            # Update active agent jika ada yang cocok
            matched = False
            for ch in channel_mgr.channels.values():
                if canonical_id in ch["agents"]:
                    ag = ch["agents"][canonical_id]["info"]
                    ag["name"] = name
                    ag["hostname"] = hostname
                    ag["ip"] = ip
                    ag["mac"] = mac
                    ag["notes"] = notes
                    ag["status"] = "online"
                    matched = True
                    if main_event_loop and not main_event_loop.is_closed():
                        asyncio.run_coroutine_threadsafe(
                            notify_masters(ag["channel"], {"type": "agent_updated", "agent": ag}),
                            main_event_loop
                        )

            dev_info = {
                "id": canonical_id,
                "name": name,
                "hostname": hostname,
                "ip": ip or "127.0.0.1",
                "mac": mac or "00:00:00:00:00:00",
                "notes": notes,
                "status": "online" if is_alive else "offline",
                "channel": channel_name,
                "resolution": "1920x1080",
                "mode": "thumbnail",
                "is_locked": False,
                "cpu": 0, "ram": 0
            }

            if not matched and main_event_loop and not main_event_loop.is_closed():
                asyncio.run_coroutine_threadsafe(
                    notify_masters(channel_name, {"type": "agent_updated", "agent": dev_info}),
                    main_event_loop
                )

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True,
                "agent_id": canonical_id,
                "old_agent_id": old_agent_id,
                "device": dev_info,
                "ping": ping_res,
                "auto_connected": is_alive
            }).encode("utf-8"))
            return

        elif parsed.path == "/api/devices/delete":
            agent_id = payload.get("agent_id")
            channel_name = payload.get("channel", "LAB-UTAMA")
            if agent_id:
                if agent_id in devices_db:
                    del devices_db[agent_id]
                    save_devices_db(devices_db)
                
                # Cari juga jika disimpan dengan format MAC
                for db_k, db_v in list(devices_db.items()):
                    if db_k == agent_id or db_v.get("mac") == agent_id:
                        del devices_db[db_k]
                        save_devices_db(devices_db)

                if main_event_loop and not main_event_loop.is_closed():
                    asyncio.run_coroutine_threadsafe(
                        notify_masters(channel_name, {"type": "device_deleted", "agent_id": agent_id}),
                        main_event_loop
                    )

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "deleted_id": agent_id}).encode("utf-8"))
                return

        elif parsed.path == "/api/scripts":
            # Tambah atau Update Skrip
            s_id = payload.get("id") or f"script_{int(time.time()*1000)%1000000}"
            script_entry = {
                "id": s_id,
                "name": payload.get("name", "Script Baru"),
                "description": payload.get("description", ""),
                "platform": payload.get("platform", "Windows"),
                "language": payload.get("language", "PowerShell"),
                "type": payload.get("type", "Custom"),
                "code": payload.get("code", "")
            }
            
            # Cek apakah update atau tambah baru
            idx = next((i for i, s in enumerate(scripts_db) if s["id"] == s_id), -1)
            if idx >= 0:
                scripts_db[idx] = script_entry
            else:
                scripts_db.append(script_entry)
            save_scripts_db(scripts_db)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "script": script_entry}).encode("utf-8"))
            return

        elif parsed.path == "/api/scripts/delete":
            s_id = payload.get("id")
            scripts_db[:] = [s for s in scripts_db if s["id"] != s_id]
            save_scripts_db(scripts_db)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "deleted_id": s_id}).encode("utf-8"))
            return

        self.send_response(400)
        self.end_headers()

    def log_message(self, format, *args):
        try:
            msg_str = " ".join(str(a) for a in args)
            if "GET /api/" in msg_str or "favicon.ico" in msg_str:
                return
        except Exception:
            pass
        super().log_message(format, *args)

def start_http_server():
    server_address = ("0.0.0.0", HTTP_PORT)
    httpd = http.server.ThreadingHTTPServer(server_address, FYJHTTPRequestHandler)
    print(f"[*] HTTP Server Web Master aktif di port {HTTP_PORT}")
    httpd.serve_forever()

# --- WebSocket Relay Hub ---
async def notify_masters(channel_id: str, message: dict):
    ch = channel_mgr.channels.get(channel_id)
    if not ch:
        return
    dead = set()
    payload = json.dumps(message)
    for m in list(ch["masters"]):
        try:
            await m.send(payload)
        except Exception:
            dead.add(m)
    ch["masters"].difference_update(dead)

async def ws_handler(websocket):
    path = websocket.request.path if hasattr(websocket, "request") else websocket.path
    parsed = urllib.parse.urlparse(path)
    params = urllib.parse.parse_qs(parsed.query)

    role = params.get("role", [""])[0]
    channel_id = params.get("channel", ["LAB-UTAMA"])[0].strip().upper()

    ch = channel_mgr.get_or_create_channel(channel_id)

    if role == "master":
        ch["masters"].add(websocket)
        print(f"[+] Master terhubung ke Channel: {channel_id}")
        
        devices_list = channel_mgr.get_channel_devices(channel_id)
        await websocket.send(json.dumps({
            "type": "channel_state",
            "channel": channel_id,
            "agents": devices_list
        }))

        try:
            async for raw_msg in websocket:
                data = json.loads(raw_msg)
                msg_type = data.get("type")

                if msg_type == "switch_channel":
                    new_ch_id = data.get("channel", "").strip().upper()
                    if new_ch_id and new_ch_id != channel_id:
                        ch["masters"].discard(websocket)
                        channel_id = new_ch_id
                        ch = channel_mgr.get_or_create_channel(channel_id)
                        ch["masters"].add(websocket)
                        devices_list = channel_mgr.get_channel_devices(channel_id)
                        await websocket.send(json.dumps({
                            "type": "channel_state",
                            "channel": channel_id,
                            "agents": devices_list
                        }))

                elif msg_type == "update_device":
                    agent_id = data.get("agent_id")
                    old_agent_id = data.get("old_agent_id") or agent_id
                    name = data.get("name", "Komputer").strip()
                    hostname = data.get("hostname", "").strip()
                    ip = data.get("ip", "").strip()
                    mac = data.get("mac", "").strip().upper()
                    notes = data.get("notes", "").strip()

                    clean_mac = normalize_mac(mac)
                    if clean_mac and clean_mac != "000000000000":
                        canonical_id = f"pc_{clean_mac}"
                    elif ip and not ip.startswith("127."):
                        canonical_id = f"pc_{ip.replace('.', '_')}"
                    elif hostname:
                        canonical_id = f"pc_{hostname.replace(' ', '_')}"
                    else:
                        canonical_id = agent_id or f"dev_{int(time.time()*1000)%1000000}"

                    if old_agent_id and old_agent_id != canonical_id and old_agent_id in devices_db:
                        del devices_db[old_agent_id]
                        await notify_masters(channel_id, {"type": "device_deleted", "agent_id": old_agent_id})

                    if mac:
                        send_wake_on_lan(mac)
                    ping_res = check_host_ping(ip)
                    is_alive = ping_res.get("alive", False)

                    devices_db[canonical_id] = {
                        "name": name,
                        "hostname": hostname,
                        "ip": ip,
                        "mac": mac,
                        "notes": notes,
                        "channel": channel_id,
                        "status": "online" if is_alive else "offline"
                    }
                    save_devices_db(devices_db)

                    # Update active agent jika online
                    matched = False
                    for target_ch in channel_mgr.channels.values():
                        if canonical_id in target_ch["agents"]:
                            ag = target_ch["agents"][canonical_id]["info"]
                            ag["name"] = name
                            ag["hostname"] = hostname
                            ag["ip"] = ip
                            ag["mac"] = mac
                            ag["notes"] = notes
                            ag["status"] = "online"
                            matched = True
                            await notify_masters(ag["channel"], {"type": "agent_updated", "agent": ag})

                    if not matched:
                        offline_info = {
                            "id": canonical_id,
                            "name": name,
                            "hostname": hostname,
                            "ip": ip or "127.0.0.1",
                            "mac": mac or "00:00:00:00:00:00",
                            "notes": notes,
                            "status": "online" if is_alive else "offline",
                            "channel": channel_id,
                            "resolution": "1920x1080",
                            "mode": "thumbnail",
                            "is_locked": False,
                            "cpu": 0, "ram": 0
                        }
                        await notify_masters(channel_id, {"type": "agent_updated", "agent": offline_info})

                elif msg_type == "delete_device":
                    agent_id = data.get("agent_id")
                    if agent_id:
                        if agent_id in devices_db:
                            del devices_db[agent_id]
                            save_devices_db(devices_db)
                        for db_k in list(devices_db.keys()):
                            if db_k == agent_id:
                                del devices_db[db_k]
                                save_devices_db(devices_db)
                        await notify_masters(channel_id, {"type": "device_deleted", "agent_id": agent_id})

                elif msg_type == "connect_device":
                    agent_id = data.get("agent_id")
                    target_ip = data.get("ip")
                    target_mac = data.get("mac")
                    if not target_ip and agent_id in devices_db:
                        target_ip = devices_db[agent_id].get("ip", "")
                    if not target_mac and agent_id in devices_db:
                        target_mac = devices_db[agent_id].get("mac", "")
                    
                    if target_mac:
                        send_wake_on_lan(target_mac)
                    ping_res = check_host_ping(target_ip)
                    is_alive = ping_res.get("alive", False)

                    new_status = "online" if is_alive else "offline"
                    if agent_id in devices_db:
                        devices_db[agent_id]["status"] = new_status
                        save_devices_db(devices_db)

                    dev_info = {
                        "id": agent_id,
                        "name": devices_db.get(agent_id, {}).get("name", "Komputer"),
                        "hostname": devices_db.get(agent_id, {}).get("hostname", ""),
                        "ip": target_ip or "127.0.0.1",
                        "mac": target_mac or "00:00:00:00:00:00",
                        "notes": devices_db.get(agent_id, {}).get("notes", ""),
                        "status": new_status,
                        "channel": channel_id,
                        "cpu": 0, "ram": 0, "is_locked": False
                    }
                    await notify_masters(channel_id, {"type": "agent_updated", "agent": dev_info})

                elif msg_type == "disconnect_device":
                    agent_id = data.get("agent_id")
                    if agent_id in ch["agents"]:
                        try:
                            await ch["agents"][agent_id]["ws"].close()
                        except Exception:
                            pass
                        del ch["agents"][agent_id]
                    if agent_id in devices_db:
                        devices_db[agent_id]["status"] = "offline"
                        save_devices_db(devices_db)
                    dev_info = {
                        "id": agent_id,
                        "name": devices_db.get(agent_id, {}).get("name", "Komputer"),
                        "hostname": devices_db.get(agent_id, {}).get("hostname", ""),
                        "ip": devices_db.get(agent_id, {}).get("ip", "127.0.0.1"),
                        "mac": devices_db.get(agent_id, {}).get("mac", "00:00:00:00:00:00"),
                        "notes": devices_db.get(agent_id, {}).get("notes", ""),
                        "status": "offline",
                        "channel": channel_id,
                        "cpu": 0, "ram": 0, "is_locked": False
                    }
                    await notify_masters(channel_id, {"type": "agent_updated", "agent": dev_info})

                elif msg_type == "execute_script":
                    targets = data.get("targets") or data.get("target_id") or "all"
                    script_data = data.get("script", {})
                    cmd_payload = json.dumps({
                        "type": "remote_command",
                        "command": "execute_script",
                        "params": {
                            "code": script_data.get("code", ""),
                            "language": script_data.get("language", "PowerShell"),
                            "script_name": script_data.get("name", "Custom Script")
                        }
                    })
                    if targets == "all":
                        for a in list(ch["agents"].values()):
                            try:
                                await a["ws"].send(cmd_payload)
                            except Exception:
                                pass
                    elif isinstance(targets, list):
                        for t_id in targets:
                            if t_id in ch["agents"]:
                                try:
                                    await ch["agents"][t_id]["ws"].send(cmd_payload)
                                except Exception:
                                    pass
                    elif isinstance(targets, str):
                        for t_id in targets.split(","):
                            t_id = t_id.strip()
                            if t_id in ch["agents"]:
                                try:
                                    await ch["agents"][t_id]["ws"].send(cmd_payload)
                                except Exception:
                                    pass

                elif msg_type == "remote_input":
                    target_id = data.get("target_id")
                    if target_id in ch["agents"]:
                        await ch["agents"][target_id]["ws"].send(raw_msg)

                elif msg_type == "remote_command":
                    targets = data.get("targets") or data.get("target_id")
                    if targets == "all":
                        for a in list(ch["agents"].values()):
                            try:
                                await a["ws"].send(raw_msg)
                            except Exception:
                                pass
                    elif isinstance(targets, list):
                        for t_id in targets:
                            if t_id in ch["agents"]:
                                try:
                                    await ch["agents"][t_id]["ws"].send(cmd_payload)
                                except Exception:
                                    pass
                    elif targets in ch["agents"]:
                        await ch["agents"][targets]["ws"].send(raw_msg)

                elif msg_type == "set_agent_mode":
                    target_id = data.get("target_id")
                    mode = data.get("mode", "thumbnail")
                    if target_id in ch["agents"]:
                        ch["agents"][target_id]["info"]["mode"] = mode
                        await ch["agents"][target_id]["ws"].send(json.dumps({
                            "type": "set_mode",
                            "mode": mode
                        }))

                elif msg_type == "broadcast_demo_frame":
                    for a in list(ch["agents"].values()):
                        try:
                            await a["ws"].send(raw_msg)
                        except Exception:
                            pass

                elif msg_type == "stop_broadcast_demo":
                    for a in list(ch["agents"].values()):
                        try:
                            await a["ws"].send(raw_msg)
                        except Exception:
                            pass

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            ch["masters"].discard(websocket)
            print(f"[-] Master terputus dari Channel: {channel_id}")

    elif role == "agent":
        raw_agent_id = params.get("id", [""])[0]
        agent_name = params.get("name", ["Komputer Klien"])[0]
        detected_ip = websocket.remote_address[0] if websocket.remote_address else "127.0.0.1"

        agent_info = {
            "id": raw_agent_id or f"pc_{int(time.time()*1000)%100000}",
            "name": agent_name,
            "hostname": agent_name,
            "channel": channel_id,
            "ip": detected_ip,
            "mac": "00:00:00:00:00:00",
            "notes": "",
            "resolution": "1920x1080",
            "mode": "thumbnail",
            "status": "online",
            "is_locked": False,
            "cpu": 0,
            "ram": 0,
            "active_window": "",
            "connected_at": time.time(),
            "last_seen": time.time()
        }

        active_dev_id = None

        try:
            async for raw_msg in websocket:
                data = json.loads(raw_msg)
                msg_type = data.get("type")

                if msg_type == "agent_hello":
                    reported_info = data.get("info", {})
                    reported_hostname = reported_info.get("hostname", "")
                    reported_ip = reported_info.get("ip", detected_ip)
                    reported_mac = reported_info.get("mac", "")

                    for k in ["os", "resolution", "mode"]:
                        if k in reported_info:
                            agent_info[k] = reported_info[k]

                    # Pencocokan ketat dengan perangkat di Data Perangkat & Jaringan
                    matched_id = find_matching_device_id(reported_ip, reported_mac, reported_hostname)
                    if matched_id:
                        active_dev_id = matched_id
                        saved_dev = devices_db[matched_id]
                        agent_info["id"] = matched_id
                        agent_info["name"] = saved_dev.get("name", agent_name)
                        agent_info["hostname"] = saved_dev.get("hostname", reported_hostname)
                        agent_info["ip"] = saved_dev.get("ip", reported_ip)
                        agent_info["mac"] = saved_dev.get("mac", reported_mac)
                        agent_info["notes"] = saved_dev.get("notes", "")
                        agent_info["status"] = "online"
                        agent_info["last_seen"] = time.time()

                        devices_db[matched_id]["status"] = "online"
                        save_devices_db(devices_db)

                        ch["agents"][matched_id] = {"ws": websocket, "info": agent_info}
                        print(f"[+] Agent TERVERIFIKASI cocok dengan: '{agent_info['name']}' ({matched_id}) IP: {agent_info['ip']}")
                        await notify_masters(channel_id, {
                            "type": "agent_updated",
                            "agent": agent_info
                        })
                    else:
                        print(f"[!] PERINGATAN: Agent dari IP {reported_ip} (Host: {reported_hostname}, MAC: {reported_mac}) TIDAK TERDAFTAR di Data Perangkat & Jaringan. Siaran layar ditolak.")

                elif msg_type == "screen_frame":
                    if not active_dev_id:
                        continue  # Hanya siarkan jika agent terdaftar dan cocok secara ketat
                    agent_info["last_seen"] = time.time()
                    frame_data = {
                        "type": "screen_frame",
                        "agent_id": active_dev_id,
                        "frame": data.get("frame"),
                        "mode": data.get("mode", "thumbnail"),
                        "timestamp": data.get("timestamp", time.time())
                    }
                    await notify_masters(channel_id, frame_data)

                elif msg_type == "agent_stats":
                    if not active_dev_id:
                        continue
                    agent_info["cpu"] = data.get("cpu", 0)
                    agent_info["ram"] = data.get("ram", 0)
                    agent_info["active_window"] = data.get("active_window", "")
                    agent_info["is_locked"] = data.get("is_locked", False)
                    agent_info["last_seen"] = time.time()
                    await notify_masters(channel_id, {
                        "type": "agent_stats",
                        "agent_id": active_dev_id,
                        "stats": {
                            "cpu": agent_info["cpu"],
                            "ram": agent_info["ram"],
                            "active_window": agent_info["active_window"],
                            "is_locked": agent_info["is_locked"]
                        }
                    })

                elif msg_type == "script_result":
                    if not active_dev_id:
                        continue
                    await notify_masters(channel_id, {
                        "type": "script_result",
                        "agent_id": active_dev_id,
                        "agent_name": agent_info["name"],
                        "script_name": data.get("script_name", ""),
                        "success": data.get("success", True),
                        "output": data.get("output", "")
                    })

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            if active_dev_id:
                if active_dev_id in ch["agents"]:
                    del ch["agents"][active_dev_id]
                if active_dev_id in devices_db:
                    devices_db[active_dev_id]["status"] = "offline"
                    save_devices_db(devices_db)
                agent_info["status"] = "offline"
                await notify_masters(channel_id, {
                    "type": "agent_updated",
                    "agent": agent_info
                })
                print(f"[-] Agent '{agent_info['name']}' ({active_dev_id}) terputus dari Channel: {channel_id}")

    else:
        await websocket.close(1008, "Role parameter missing (role=master or role=agent)")

def start_udp_beacon_service():
    """Layanan beacon UDP untuk memudahkan agen klien di LAN mendeteksi server master secara otomatis."""
    def _beacon_loop():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            sock.bind(("", 8889))
        except Exception:
            pass
        sock.settimeout(2.0)

        while True:
            try:
                ips = get_local_ips()
                primary_ip = next((ip for ip in ips if ip != "127.0.0.1"), "127.0.0.1")
                beacon_data = json.dumps({
                    "type": "FYJ_BEACON",
                    "server_ip": primary_ip,
                    "http_port": HTTP_PORT,
                    "ws_port": WS_PORT,
                    "channel": "LAB-UTAMA"
                }).encode("utf-8")

                sock.sendto(beacon_data, ("255.255.255.255", 8889))

                try:
                    data, addr = sock.recvfrom(1024)
                    req = json.loads(data.decode("utf-8", errors="ignore"))
                    if req.get("type") == "DISCOVER_MASTER":
                        reply = json.dumps({
                            "type": "MASTER_REPLY",
                            "server_ip": primary_ip,
                            "http_port": HTTP_PORT,
                            "ws_port": WS_PORT,
                            "channel": "LAB-UTAMA"
                        }).encode("utf-8")
                        sock.sendto(reply, addr)
                except socket.timeout:
                    pass
            except Exception:
                time.sleep(2)
            time.sleep(2.0)

    threading.Thread(target=_beacon_loop, daemon=True).start()

async def main():
    global main_event_loop
    main_event_loop = asyncio.get_running_loop()

    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()

    # Aktifkan UDP Beacon Service untuk auto-discovery klien LAN
    start_udp_beacon_service()

    ips = get_local_ips()
    print("=" * 65)
    print("      🚀 FYJ CHANNEL REMOTE - GATEWAY & WEB MASTER SERVER")
    print("=" * 65)
    print(f" [*] Web Master Dashboard: http://localhost:{HTTP_PORT}")
    for ip in ips:
        if ip != "127.0.0.1":
            print(f" [*] Akses Jaringan LAN : http://{ip}:{HTTP_PORT}")
    print(f" [*] WebSocket Relay Hub : ws://0.0.0.0:{WS_PORT}")
    print("=" * 65)
    print("Tekan Ctrl+C untuk menghentikan server.\n")

    async with websockets.serve(ws_handler, "0.0.0.0", WS_PORT, max_size=25 * 1024 * 1024):
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Server dimatikan.")
    finally:
        if local_agent_proc is not None:
            try:
                local_agent_proc.terminate()
            except Exception:
                pass
