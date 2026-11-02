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
        """Menggabungkan active online agents dengan registered offline devices tanpa duplikasi."""
        ch = self.get_or_create_channel(channel_id)
        active_ids = set()
        active_macs = set()
        active_ips = set()
        result = []

        # 1. Masukkan semua active online agents
        for a_id, a in ch["agents"].items():
            info = dict(a["info"])
            info["status"] = "online"
            result.append(info)
            active_ids.add(a_id)
            if info.get("mac") and info["mac"] != "00:00:00:00:00:00":
                active_macs.add(info["mac"].upper())
            if info.get("ip") and info["ip"] not in ("127.0.0.1", "unknown"):
                active_ips.add(info["ip"])

        # 2. Masukkan saved devices dari devices_db yang berada di channel ini tapi sedang offline
        for dev_id, dev_data in devices_db.items():
            dev_channel = dev_data.get("channel", "LAB-UTAMA")
            if dev_channel == channel_id:
                dev_mac = (dev_data.get("mac") or "").upper()
                dev_ip = dev_data.get("ip") or ""
                # Hindari duplikasi jika versi online-nya sudah terdeteksi
                if dev_id not in active_ids and dev_mac not in active_macs and dev_ip not in active_ips:
                    result.append({
                        "id": dev_id,
                        "name": dev_data.get("name", "Komputer"),
                        "hostname": dev_data.get("hostname", ""),
                        "ip": dev_ip or "127.0.0.1",
                        "mac": dev_mac or "00:00:00:00:00:00",
                        "notes": dev_data.get("notes", ""),
                        "status": "offline",
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
    global local_agent_proc
    if local_agent_proc is not None and local_agent_proc.poll() is None:
        return
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
            print("[+] Local Agent background service otomatis aktif untuk PC ini!")
        except Exception as e:
            print(f"[!] Gagal memulai local agent otomatis: {e}")

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
            if ping_res.get("is_local"):
                ensure_local_agent_running()

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

            if ping_res.get("is_local"):
                ensure_local_agent_running()

            # Perbarui status di devices_db
            if agent_id in devices_db:
                devices_db[agent_id]["status"] = "online" if ping_res.get("alive") else "offline"
                save_devices_db(devices_db)

            # Beritahu semua master
            dev_info = {
                "id": agent_id,
                "name": devices_db.get(agent_id, {}).get("name", "Komputer"),
                "hostname": devices_db.get(agent_id, {}).get("hostname", ""),
                "ip": ip or "127.0.0.1",
                "mac": mac or "00:00:00:00:00:00",
                "notes": devices_db.get(agent_id, {}).get("notes", ""),
                "status": "online" if ping_res.get("alive") else "offline",
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
                "connected": ping_res.get("alive", False),
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
            if not agent_id:
                agent_id = f"dev_{int(time.time()*1000)%1000000}"
            
            channel_name = payload.get("channel", "LAB-UTAMA")
            if agent_id not in devices_db:
                devices_db[agent_id] = {"channel": channel_name}
            
            for k in ["name", "hostname", "ip", "mac", "notes", "channel"]:
                if k in payload:
                    devices_db[agent_id][k] = payload[k]
            save_devices_db(devices_db)

            dev_ip = payload.get("ip") or devices_db[agent_id].get("ip", "")
            dev_mac = payload.get("mac") or devices_db[agent_id].get("mac", "")
            
            # Cek koneksi secara otomatis seketika data disimpan
            if dev_mac:
                send_wake_on_lan(dev_mac)
            ping_res = check_host_ping(dev_ip)
            if ping_res.get("is_local"):
                ensure_local_agent_running()

            is_alive = ping_res.get("alive", False)

            # Update active agent jika online
            matched = False
            for ch in channel_mgr.channels.values():
                if agent_id in ch["agents"]:
                    ag = ch["agents"][agent_id]["info"]
                    for k in ["name", "hostname", "ip", "mac", "notes"]:
                        if k in payload:
                            ag[k] = payload[k]
                    ag["status"] = "online"
                    matched = True
                    if main_event_loop and not main_event_loop.is_closed():
                        asyncio.run_coroutine_threadsafe(
                            notify_masters(ag["channel"], {"type": "agent_updated", "agent": ag}),
                            main_event_loop
                        )

            if not matched:
                auto_status = "online" if is_alive else "offline"
                offline_info = {
                    "id": agent_id,
                    "name": devices_db[agent_id].get("name", "Komputer"),
                    "hostname": devices_db[agent_id].get("hostname", ""),
                    "ip": devices_db[agent_id].get("ip", "127.0.0.1"),
                    "mac": devices_db[agent_id].get("mac", "00:00:00:00:00:00"),
                    "notes": devices_db[agent_id].get("notes", ""),
                    "status": auto_status,
                    "channel": channel_name,
                    "cpu": 0, "ram": 0, "is_locked": False
                }
                if main_event_loop and not main_event_loop.is_closed():
                    asyncio.run_coroutine_threadsafe(
                        notify_masters(channel_name, {"type": "agent_updated", "agent": offline_info}),
                        main_event_loop
                    )

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True,
                "agent_id": agent_id,
                "device": devices_db[agent_id],
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
                    agent_id = data.get("agent_id") or f"dev_{int(time.time()*1000)%1000000}"
                    if agent_id not in devices_db:
                        devices_db[agent_id] = {"channel": channel_id}
                    
                    fields = ["name", "hostname", "ip", "mac", "notes", "channel"]
                    for f in fields:
                        if f in data:
                            devices_db[agent_id][f] = data[f]
                    save_devices_db(devices_db)

                    # Update active agent jika online
                    matched = False
                    for target_ch in channel_mgr.channels.values():
                        if agent_id in target_ch["agents"]:
                            ag = target_ch["agents"][agent_id]["info"]
                            for f in fields:
                                if f in data:
                                    ag[f] = data[f]
                            matched = True
                            await notify_masters(ag["channel"], {"type": "agent_updated", "agent": ag})

                    if not matched:
                        offline_info = {
                            "id": agent_id,
                            "name": devices_db[agent_id].get("name", "Komputer"),
                            "hostname": devices_db[agent_id].get("hostname", ""),
                            "ip": devices_db[agent_id].get("ip", "127.0.0.1"),
                            "mac": devices_db[agent_id].get("mac", "00:00:00:00:00:00"),
                            "notes": devices_db[agent_id].get("notes", ""),
                            "status": "offline",
                            "channel": channel_id,
                            "cpu": 0, "ram": 0, "is_locked": False
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
                    if ping_res.get("is_local"):
                        ensure_local_agent_running()

                    new_status = "online" if ping_res.get("alive") else "offline"
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
        agent_id = params.get("id", [f"pc_{int(time.time()*1000)%100000}"])[0]
        agent_name = params.get("name", ["Komputer Klien"])[0]
        detected_ip = websocket.remote_address[0] if websocket.remote_address else "127.0.0.1"

        agent_info = {
            "id": agent_id,
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

        if agent_id in devices_db:
            saved = devices_db[agent_id]
            for f in ["name", "hostname", "ip", "mac", "notes"]:
                if f in saved and saved[f]:
                    agent_info[f] = saved[f]

        ch["agents"][agent_id] = {"ws": websocket, "info": agent_info}
        print(f"[+] Agent '{agent_info['name']}' ({agent_id}) bergabung ke Channel: {channel_id}")

        await notify_masters(channel_id, {
            "type": "agent_joined",
            "agent": agent_info
        })

        try:
            async for raw_msg in websocket:
                data = json.loads(raw_msg)
                msg_type = data.get("type")

                if msg_type == "agent_hello":
                    reported_info = data.get("info", {})
                    for k in ["hostname", "mac", "os", "resolution"]:
                        if k in reported_info:
                            agent_info[k] = reported_info[k]

                    if "ip" in reported_info and agent_info.get("ip") in ["127.0.0.1", "unknown"]:
                        agent_info["ip"] = reported_info["ip"]

                    mac_key = agent_info.get("mac")
                    matched_db_id = None
                    if mac_key:
                        for db_id, db_entry in devices_db.items():
                            if db_entry.get("mac") == mac_key or db_entry.get("hostname") == agent_info.get("hostname"):
                                matched_db_id = db_id
                                for f in ["name", "hostname", "ip", "notes"]:
                                    if f in db_entry and db_entry[f]:
                                        agent_info[f] = db_entry[f]
                                break

                    target_store_id = matched_db_id or agent_id
                    devices_db[target_store_id] = {
                        "name": agent_info["name"],
                        "hostname": agent_info.get("hostname", agent_info["name"]),
                        "ip": agent_info["ip"],
                        "mac": agent_info.get("mac", "00:00:00:00:00:00"),
                        "notes": agent_info.get("notes", ""),
                        "channel": channel_id
                    }
                    save_devices_db(devices_db)

                    agent_info["last_seen"] = time.time()
                    await notify_masters(channel_id, {
                        "type": "agent_updated",
                        "agent": agent_info
                    })

                elif msg_type == "screen_frame":
                    agent_info["last_seen"] = time.time()
                    frame_data = {
                        "type": "screen_frame",
                        "agent_id": agent_id,
                        "frame": data.get("frame"),
                        "mode": data.get("mode", "thumbnail"),
                        "timestamp": data.get("timestamp", time.time())
                    }
                    await notify_masters(channel_id, frame_data)

                elif msg_type == "agent_stats":
                    agent_info["cpu"] = data.get("cpu", 0)
                    agent_info["ram"] = data.get("ram", 0)
                    agent_info["active_window"] = data.get("active_window", "")
                    agent_info["is_locked"] = data.get("is_locked", False)
                    agent_info["last_seen"] = time.time()
                    await notify_masters(channel_id, {
                        "type": "agent_stats",
                        "agent_id": agent_id,
                        "stats": {
                            "cpu": agent_info["cpu"],
                            "ram": agent_info["ram"],
                            "active_window": agent_info["active_window"],
                            "is_locked": agent_info["is_locked"]
                        }
                    })

                elif msg_type == "script_result":
                    # Meneruskan hasil eksekusi terminal skrip ke master
                    await notify_masters(channel_id, {
                        "type": "script_result",
                        "agent_id": agent_id,
                        "agent_name": agent_info["name"],
                        "script_name": data.get("script_name", ""),
                        "success": data.get("success", True),
                        "output": data.get("output", "")
                    })

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            if agent_id in ch["agents"]:
                del ch["agents"][agent_id]
            print(f"[-] Agent '{agent_info['name']}' ({agent_id}) keluar dari Channel: {channel_id}")
            agent_info["status"] = "offline"
            await notify_masters(channel_id, {
                "type": "agent_updated",
                "agent": agent_info
            })

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

    # Otomatis aktifkan Local Client Agent di PC ini sehingga langsung online
    ensure_local_agent_running()

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
