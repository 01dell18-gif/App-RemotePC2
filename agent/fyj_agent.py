"""
FYJ Channel Remote - Target Client Agent
Berjalan di komputer target (klien/siswa) untuk streaming layar, input injection,
serta menangani perintah kontrol jarak jauh (Lock Screen, Power Control, Message, dll).
Terinspirasi dari arsitektur modular Veyon (ddengine, interception, screenlock, textmessage).
"""

import os
import sys
import io
import time
import json
import base64
import socket
import platform
import asyncio
import threading
import webbrowser
import subprocess
from typing import Optional

# Third-party libraries
try:
    import websockets
    from PIL import Image, ImageDraw, ImageFont
    import psutil
except ImportError as e:
    print(f"[ERROR] Dependensi belum lengkap: {e}")
    print("Jalankan: pip install -r requirements.txt")
    sys.exit(1)

# Platform-specific Windows imports
IS_WINDOWS = platform.system() == "Windows"
if IS_WINDOWS:
    import ctypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    try:
        import win32gui
        import win32process
    except ImportError:
        win32gui = None
else:
    user32 = None
    win32gui = None

# Konfigurasi Default
DEFAULT_SERVER_WS = "ws://127.0.0.1:8081"
DEFAULT_CHANNEL = "LAB-UTAMA"
DEFAULT_AGENT_NAME = socket.gethostname()

def attach_to_default_desktop():
    """Memastikan thread terhubung langsung ke Desktop fisik interaktif pengguna ('Default' di WinSta0)."""
    if user32:
        try:
            # 0x01FF = DESKTOP_ALL_ACCESS
            hdesk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
            if hdesk:
                user32.SetThreadDesktop(hdesk)
        except Exception:
            pass

# --- INPUT INJECTION ENGINE (Windows User32 API) ---
class WindowsInputInjector:
    # Mouse flags
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_MIDDLEDOWN = 0x0020
    MOUSEEVENTF_MIDDLEUP = 0x0040
    MOUSEEVENTF_WHEEL = 0x0800
    MOUSEEVENTF_ABSOLUTE = 0x8000

    # Key flags
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004

    # Virtual Key Map
    VK_MAP = {
        "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "shift": 0x10,
        "control": 0x11, "alt": 0x12, "pause": 0x13, "capslock": 0x14,
        "escape": 0x1B, "space": 0x20, "pageup": 0x21, "pagedown": 0x22,
        "end": 0x23, "home": 0x24, "arrowleft": 0x25, "arrowup": 0x26,
        "arrowright": 0x27, "arrowdown": 0x28, "insert": 0x2D, "delete": 0x2E,
        "meta": 0x5B, "os": 0x5B, "win": 0x5B, "contextmenu": 0x5D,
        "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
        "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
        "f11": 0x7A, "f12": 0x7B
    }

    def __init__(self):
        attach_to_default_desktop()
        self.screen_w = user32.GetSystemMetrics(0) if user32 else 1920
        self.screen_h = user32.GetSystemMetrics(1) if user32 else 1080

    def update_resolution(self):
        attach_to_default_desktop()
        if user32:
            self.screen_w = user32.GetSystemMetrics(0)
            self.screen_h = user32.GetSystemMetrics(1)

    def move_mouse(self, norm_x: float, norm_y: float):
        if not user32:
            return
        attach_to_default_desktop()
        x = int(norm_x * self.screen_w)
        y = int(norm_y * self.screen_h)
        user32.SetCursorPos(x, y)

    def mouse_event(self, button: str, action: str, norm_x: Optional[float] = None, norm_y: Optional[float] = None):
        if not user32:
            return
        attach_to_default_desktop()
        if norm_x is not None and norm_y is not None:
            self.move_mouse(norm_x, norm_y)

        flag = 0
        if button == "left":
            flag = self.MOUSEEVENTF_LEFTDOWN if action in ("down", "click") else self.MOUSEEVENTF_LEFTUP
        elif button == "right":
            flag = self.MOUSEEVENTF_RIGHTDOWN if action in ("down", "click") else self.MOUSEEVENTF_RIGHTUP
        elif button == "middle":
            flag = self.MOUSEEVENTF_MIDDLEDOWN if action in ("down", "click") else self.MOUSEEVENTF_MIDDLEUP

        if flag:
            user32.mouse_event(flag, 0, 0, 0, 0)
            if action == "click":
                up_flag = self.MOUSEEVENTF_LEFTUP if button == "left" else (self.MOUSEEVENTF_RIGHTUP if button == "right" else self.MOUSEEVENTF_MIDDLEUP)
                user32.mouse_event(up_flag, 0, 0, 0, 0)
            elif action == "dblclick":
                up_flag = self.MOUSEEVENTF_LEFTUP if button == "left" else self.MOUSEEVENTF_RIGHTUP
                user32.mouse_event(up_flag, 0, 0, 0, 0)
                user32.mouse_event(flag, 0, 0, 0, 0)
                user32.mouse_event(up_flag, 0, 0, 0, 0)

    def wheel_scroll(self, delta: float):
        if not user32:
            return
        attach_to_default_desktop()
        amount = int(delta * 120)
        user32.mouse_event(self.MOUSEEVENTF_WHEEL, 0, 0, amount, 0)

    def key_event(self, key_str: str, action: str):
        if not user32:
            return
        attach_to_default_desktop()
        k = key_str.lower()
        flags = 0
        if action == "up":
            flags |= self.KEYEVENTF_KEYUP

        if k in self.VK_MAP:
            vk = self.VK_MAP[k]
            user32.keybd_event(vk, 0, flags, 0)
        elif len(key_str) == 1:
            char_code = ord(key_str)
            if 'a' <= k <= 'z':
                vk = ord(k.upper())
                user32.keybd_event(vk, 0, flags, 0)
            elif '0' <= k <= '9':
                vk = ord(k)
                user32.keybd_event(vk, 0, flags, 0)
            else:
                if action == "down":
                    user32.keybd_event(0, char_code, self.KEYEVENTF_UNICODE, 0)
                    user32.keybd_event(0, char_code, self.KEYEVENTF_UNICODE | self.KEYEVENTF_KEYUP, 0)

    def execute_special_shortcut(self, shortcut_name: str):
        if not user32:
            return
        attach_to_default_desktop()
        if shortcut_name == "win":
            user32.keybd_event(0x5B, 0, 0, 0)
            user32.keybd_event(0x5B, 0, self.KEYEVENTF_KEYUP, 0)
        elif shortcut_name == "win_d":
            user32.keybd_event(0x5B, 0, 0, 0)
            user32.keybd_event(ord('D'), 0, 0, 0)
            user32.keybd_event(ord('D'), 0, self.KEYEVENTF_KEYUP, 0)
            user32.keybd_event(0x5B, 0, self.KEYEVENTF_KEYUP, 0)
        elif shortcut_name == "alt_tab":
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x09, 0, 0, 0)
            user32.keybd_event(0x09, 0, self.KEYEVENTF_KEYUP, 0)
            user32.keybd_event(0x12, 0, self.KEYEVENTF_KEYUP, 0)
        elif shortcut_name == "ctrl_shift_esc":
            user32.keybd_event(0x11, 0, 0, 0)
            user32.keybd_event(0x10, 0, 0, 0)
            user32.keybd_event(0x1B, 0, 0, 0)
            user32.keybd_event(0x1B, 0, self.KEYEVENTF_KEYUP, 0)
            user32.keybd_event(0x10, 0, self.KEYEVENTF_KEYUP, 0)
            user32.keybd_event(0x11, 0, self.KEYEVENTF_KEYUP, 0)

injector = WindowsInputInjector()

# --- LOCK SCREEN OVERLAY ENGINE (Veyon screenlock.dll ekuivalen) ---
class ScreenLockManager:
    def __init__(self):
        self.is_locked = False
        self.lock_window = None
        self.lock_thread = None
        self.message = "Layar Dikunci oleh Pengawas Lab"

    def show_lock(self, message: str = ""):
        if message:
            self.message = message
        if self.is_locked:
            return
        self.is_locked = True
        self.lock_thread = threading.Thread(target=self._run_lock_ui, daemon=True)
        self.lock_thread.start()

    def hide_lock(self):
        self.is_locked = False
        if self.lock_window:
            try:
                self.lock_window.after(0, self.lock_window.destroy)
            except Exception:
                pass
            self.lock_window = None

    def _run_lock_ui(self):
        try:
            import tkinter as tk
            root = tk.Tk()
            self.lock_window = root
            root.title("FYJ Channel Remote - Screen Lock")
            root.attributes("-fullscreen", True)
            root.attributes("-topmost", True)
            root.configure(bg="#0B0F19")
            root.overrideredirect(True)

            # Halangi tombol Alt+F4 atau penutupan manual
            root.protocol("WM_DELETE_WINDOW", lambda: None)

            # Konten UI Layar Kunci
            frame = tk.Frame(root, bg="#0B0F19")
            frame.place(relx=0.5, rely=0.5, anchor="center")

            icon_lbl = tk.Label(frame, text="🔒", font=("Segoe UI Emoji", 84), fg="#38BDF8", bg="#0B0F19")
            icon_lbl.pack(pady=10)

            title_lbl = tk.Label(frame, text="FYJ CHANNEL REMOTE", font=("Arial", 28, "bold"), fg="#FFFFFF", bg="#0B0F19")
            title_lbl.pack(pady=5)

            status_lbl = tk.Label(frame, text="SESI DIKUNCI OLEH PENGAWAS", font=("Arial", 14), fg="#EF4444", bg="#0B0F19")
            status_lbl.pack(pady=5)

            msg_lbl = tk.Label(frame, text=self.message, font=("Arial", 16), fg="#94A3B8", bg="#0B0F19", wraplength=700)
            msg_lbl.pack(pady=20)

            info_lbl = tk.Label(frame, text="Perhatikan instruksi pengajar di depan kelas.", font=("Arial", 11, "italic"), fg="#64748B", bg="#0B0F19")
            info_lbl.pack(pady=10)

            root.mainloop()
        except Exception as e:
            print(f"[!] Error menampilkan lock screen UI: {e}")

lock_mgr = ScreenLockManager()

# --- POP-UP ANNOUNCEMENT ENGINE (Veyon textmessage.dll ekuivalen) ---
def show_popup_announcement(title: str, message: str):
    def _popup():
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            messagebox.showinfo(title or "Pemberitahuan Pengawas", message, parent=root)
            root.destroy()
        except Exception:
            pass
    threading.Thread(target=_popup, daemon=True).start()

# --- SCREEN CAPTURE ENGINE ---
def capture_desktop_frame(quality: int = 50, scale_factor: float = 0.5) -> bytes:
    """Mengambil tangkapan layar desktop fisik asli dengan kompresi JPEG memory buffer."""
    attach_to_default_desktop()
    img = None

    # 1. Coba ImageGrab (Desktop fisik asli pengguna)
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
    except Exception:
        img = None

    # 2. Coba mss jika ImageGrab gagal
    if img is None:
        try:
            import mss
            with mss.mss() as sct:
                monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                shot = sct.grab(monitor)
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        except Exception:
            img = None

    if img is None:
        # Fallback terakhir jika dalam lingkungan tanpa monitor
        w, h = 1280, 720
        img = Image.new("RGB", (w, h), color=(15, 23, 42))
        draw = ImageDraw.Draw(img)
        t_str = time.strftime("%Y-%m-%d %H:%M:%S")
        cpu_val = psutil.cpu_percent() if psutil else 0
        ram_val = psutil.virtual_memory().percent if psutil else 0
        draw.rectangle([(20, 20), (w - 20, h - 20)], outline=(56, 189, 248), width=3)
        draw.text((60, 60), "FYJ CHANNEL REMOTE - TARGET DESKTOP", fill=(255, 255, 255))
        draw.text((60, 100), f"Host: {socket.gethostname()} | Platform: {platform.system()}", fill=(148, 163, 184))
        draw.text((60, 140), f"Time: {t_str} | Status: Live Stream", fill=(52, 211, 153))
        draw.text((60, 180), f"CPU: {cpu_val}% | RAM: {ram_val}%", fill=(251, 191, 36))
        offset = int(time.time() * 50) % 400
        draw.line([(60 + offset, 250), (60 + offset, 500)], fill=(56, 189, 248), width=2)

    # Scaling ukuran gambar
    if scale_factor < 1.0:
        new_w = max(320, int(img.width * scale_factor))
        new_h = max(180, int(img.height * scale_factor))
        img = img.resize((new_w, new_h), Image.Resampling.BILINEAR)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()

import uuid

def get_mac_address() -> str:
    """Mendapatkan alamat MAC fisik kartu jaringan aktif."""
    try:
        if psutil:
            for iface, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == psutil.AF_LINK or (hasattr(addr, "family") and str(addr.family) == "AddressFamily.AF_LINK"):
                        raw = addr.address.replace("-", ":").upper()
                        if len(raw.split(":")) == 6 and raw != "00:00:00:00:00:00" and not raw.startswith("0A:00:27"):
                            return raw
        mac = uuid.getnode()
        return ":".join(f"{(mac >> 8 * i) & 0xff:02X}" for i in reversed(range(6)))
    except Exception:
        return "00:00:00:00:00:00"

def get_local_ip() -> str:
    """Mendapatkan alamat IP jaringan lokal utama."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def get_active_window_title() -> str:
    if win32gui:
        try:
            hwnd = win32gui.GetForegroundWindow()
            return win32gui.GetWindowText(hwnd) or ""
        except Exception:
            pass
    return ""

def discover_master_server(timeout=1.2) -> Optional[str]:
    """Mencari Server Master FYJ di LAN melalui UDP broadcast probe."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(timeout)
        probe = json.dumps({"type": "DISCOVER_MASTER"}).encode("utf-8")
        sock.sendto(probe, ("255.255.255.255", 8889))
        start = time.time()
        while time.time() - start < timeout:
            try:
                data, addr = sock.recvfrom(2048)
                msg = json.loads(data.decode("utf-8", errors="ignore"))
                if msg.get("type") in ("FYJ_BEACON", "MASTER_REPLY"):
                    srv_ip = msg.get("server_ip") or addr[0]
                    ws_p = msg.get("ws_port", 8081)
                    sock.close()
                    return f"ws://{srv_ip}:{ws_p}"
            except socket.timeout:
                break
        sock.close()
    except Exception:
        pass
    return None

# --- AGENT CLIENT LOGIC ---
class FYJClientAgent:
    def __init__(self, server_url: str, channel: str, agent_name: str):
        self.server_url = server_url.rstrip("/")
        self.channel = channel
        self.agent_name = agent_name
        self.mac = get_mac_address()
        self.local_ip = get_local_ip()
        clean_mac = self.mac.replace(":", "").replace("-", "")
        self.agent_id = f"pc_{clean_mac}" if clean_mac and clean_mac != "000000000000" else f"pc_{socket.gethostname()}"
        self.mode = "thumbnail" # 'thumbnail' atau 'active'
        self.running = True
        self.ws = None
        self.loop = None

    async def connect_and_run(self):
        # Jika server diarahkan ke localhost tapi server lokal tidak ada, cari Master di LAN
        if "127.0.0.1" in self.server_url or "localhost" in self.server_url:
            is_local_alive = False
            try:
                test_s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                test_s.settimeout(0.3)
                test_s.connect(("127.0.0.1", 8081))
                test_s.close()
                is_local_alive = True
            except Exception:
                is_local_alive = False

            if not is_local_alive:
                print("[*] Mencari Server Master FYJ di jaringan LAN...")
                discovered = discover_master_server()
                if discovered:
                    self.server_url = discovered
                    print(f"[+] Ditemukan Server Master di LAN: {self.server_url}")

        ws_url = f"{self.server_url}?role=agent&channel={self.channel}&id={self.agent_id}&name={self.agent_name}"
        print(f"[*] Menghubungkan ke Server FYJ: {ws_url}")
        print(f"[*] Info Perangkat: Host={socket.gethostname()} | IP={self.local_ip} | MAC={self.mac}")
        
        while self.running:
            try:
                async with websockets.connect(ws_url, max_size=25 * 1024 * 1024) as ws:
                    self.ws = ws
                    self.loop = asyncio.get_running_loop()
                    print(f"[+] Terhubung dengan sukses ke Channel: {self.channel}")

                    # Kirim pesan awal registrasi agent
                    injector.update_resolution()
                    await ws.send(json.dumps({
                        "type": "agent_hello",
                        "info": {
                            "hostname": socket.gethostname(),
                            "ip": self.local_ip,
                            "mac": self.mac,
                            "os": f"{platform.system()} {platform.release()}",
                            "resolution": f"{injector.screen_w}x{injector.screen_h}",
                            "mode": self.mode
                        }
                    }))

                    # Jalankan concurrent loop: stream layar & terima perintah
                    await asyncio.gather(
                        self._screen_streaming_loop(),
                        self._command_receiver_loop(),
                        self._stats_reporter_loop()
                    )

            except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError, OSError) as e:
                print(f"[!] Sambungan terputus ({e}). Mencoba menghubungkan kembali dalam 3 detik...")
                await asyncio.sleep(3)
            except Exception as e:
                print(f"[!] Error tak terduga: {e}. Retry dalam 3 detik...")
                await asyncio.sleep(3)

    async def _screen_streaming_loop(self):
        """Loop pengiriman frame layar yang beradaptasi dengan mode kontrol."""
        while self.running and self.ws:
            try:
                if self.mode == "active":
                    # Mode kontrol langsung: 20-25 FPS, resolusi tinggi
                    frame_bytes = capture_desktop_frame(quality=65, scale_factor=0.85)
                    delay = 0.045
                else:
                    # Mode grid thumbnail: 1 FPS, resolusi rendah, hemat bandwidth
                    frame_bytes = capture_desktop_frame(quality=45, scale_factor=0.35)
                    delay = 1.2

                b64_frame = base64.b64encode(frame_bytes).decode("ascii")
                msg = {
                    "type": "screen_frame",
                    "mode": self.mode,
                    "frame": b64_frame,
                    "timestamp": time.time()
                }
                await self.ws.send(json.dumps(msg))
                await asyncio.sleep(delay)
            except Exception:
                break

    async def _stats_reporter_loop(self):
        """Kirim statistik CPU, RAM, & status jendela aktif setiap 3 detik."""
        while self.running and self.ws:
            try:
                cpu = psutil.cpu_percent() if psutil else 0
                ram = psutil.virtual_memory().percent if psutil else 0
                active_win = get_active_window_title()

                msg = {
                    "type": "agent_stats",
                    "cpu": cpu,
                    "ram": ram,
                    "active_window": active_win,
                    "is_locked": lock_mgr.is_locked
                }
                await self.ws.send(json.dumps(msg))
                await asyncio.sleep(3)
            except Exception:
                break

    async def _command_receiver_loop(self):
        """Menerima dan mengeksekusi instruksi dari Web Master."""
        while self.running and self.ws:
            try:
                raw_msg = await self.ws.recv()
                data = json.loads(raw_msg)
                msg_type = data.get("type")

                if msg_type == "set_mode":
                    self.mode = data.get("mode", "thumbnail")
                    print(f"[*] Mode streaming berubah ke: {self.mode}")

                elif msg_type == "remote_input":
                    inp_type = data.get("input_type")
                    if inp_type == "mouse_move":
                        injector.move_mouse(data.get("x", 0.5), data.get("y", 0.5))
                    elif inp_type == "mouse_event":
                        injector.mouse_event(data.get("button", "left"), data.get("action", "click"), data.get("x"), data.get("y"))
                    elif inp_type == "wheel":
                        injector.wheel_scroll(data.get("delta", 0))
                    elif inp_type == "key_event":
                        injector.key_event(data.get("key", ""), data.get("action", "down"))
                    elif inp_type == "shortcut":
                        injector.execute_special_shortcut(data.get("name", ""))

                elif msg_type == "remote_command":
                    cmd = data.get("command")
                    params = data.get("params", {})

                    if cmd == "lock":
                        msg_text = params.get("message", "Layar Dikunci oleh Pengawas Lab")
                        lock_mgr.show_lock(msg_text)
                    elif cmd == "unlock":
                        lock_mgr.hide_lock()
                    elif cmd == "message":
                        show_popup_announcement(params.get("title", "Pesan dari Guru"), params.get("message", ""))
                    elif cmd == "open_url":
                        url = params.get("url", "")
                        if url:
                            if not url.startswith("http"):
                                url = "https://" + url
                            webbrowser.open(url)
                    elif cmd == "power":
                        action = params.get("action")
                        self._handle_power_action(action)
                    elif cmd == "execute_script":
                        script_code = params.get("code", "")
                        script_lang = params.get("language", "PowerShell")
                        script_name = params.get("script_name", "Custom Script")
                        self._handle_script_execution(script_code, script_lang, script_name)

            except Exception:
                break

    def _handle_script_execution(self, code: str, language: str, name: str):
        def _run():
            print(f"[*] Menjalankan skrip: '{name}' ({language})")
            output = ""
            success = True
            try:
                if "powershell" in language.lower():
                    res = subprocess.run(
                        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", code],
                        capture_output=True, text=True, timeout=30
                    )
                    output = res.stdout + ("\n" + res.stderr if res.stderr else "")
                    success = (res.returncode == 0)
                else:
                    res = subprocess.run(
                        ["cmd.exe", "/c", code],
                        capture_output=True, text=True, timeout=30
                    )
                    output = res.stdout + ("\n" + res.stderr if res.stderr else "")
                    success = (res.returncode == 0)
            except Exception as e:
                output = str(e)
                success = False

            print(f"[*] Output skrip '{name}':\n{output.strip()}")
            if self.ws:
                try:
                    payload = json.dumps({
                        "type": "script_result",
                        "agent_id": self.agent_id,
                        "script_name": name,
                        "success": success,
                        "output": output.strip()
                    })
                    if self.loop and self.loop.is_running():
                        asyncio.run_coroutine_threadsafe(self.ws.send(payload), self.loop)
                except Exception:
                    pass

        threading.Thread(target=_run, daemon=True).start()

    def _handle_power_action(self, action: str):
        print(f"[*] Perintah daya diterima: {action}")
        if action == "shutdown":
            if IS_WINDOWS:
                os.system("shutdown /s /t 5 /c \"Dimatikan oleh Pengawas FYJ Remote\"")
            else:
                os.system("shutdown -h now")
        elif action == "restart":
            if IS_WINDOWS:
                os.system("shutdown /r /t 5 /c \"Restart oleh Pengawas FYJ Remote\"")
            else:
                os.system("reboot")
        elif action == "lock_workstation":
            if user32:
                user32.LockWorkStation()
        elif action == "logoff":
            if IS_WINDOWS:
                os.system("shutdown /l")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="FYJ Channel Remote - Target Client Agent")
    parser.add_argument("--server", default=DEFAULT_SERVER_WS, help=f"WebSocket Server URL (default: {DEFAULT_SERVER_WS})")
    parser.add_argument("--channel", default=DEFAULT_CHANNEL, help=f"Channel/Room Name (default: {DEFAULT_CHANNEL})")
    parser.add_argument("--name", default=DEFAULT_AGENT_NAME, help=f"Nama PC Client (default: {DEFAULT_AGENT_NAME})")
    args = parser.parse_args()

    agent = FYJClientAgent(args.server, args.channel, args.name)
    try:
        asyncio.run(agent.connect_and_run())
    except KeyboardInterrupt:
        print("\n[!] Agent dihentikan oleh pengguna.")

if __name__ == "__main__":
    main()

