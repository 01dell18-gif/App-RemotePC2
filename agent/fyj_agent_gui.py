"""
FYJ Channel Remote - Client Agent GUI Launcher
Antarmuka grafis ramah pengguna untuk menghubungkan PC siswa/klien ke Channel Remote.
Mendukung pengaturan Host Name, IP Address, dan MAC Address.
"""

import sys
import os
import socket
import threading
import asyncio
import tkinter as tk
from tkinter import ttk, messagebox

# Import core agent logic
from fyj_agent import FYJClientAgent, DEFAULT_SERVER_WS, DEFAULT_CHANNEL, DEFAULT_AGENT_NAME, get_mac_address, get_local_ip

class FYJAgentApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FYJ Channel Remote - Klien")
        self.geometry("480x560")
        self.resizable(False, False)
        self.configure(bg="#0F172A")

        self.agent_instance = None
        self.agent_thread = None
        self.is_connected = False

        self._build_ui()

    def _build_ui(self):
        # Header Banner
        header = tk.Frame(self, bg="#1E293B", pady=15)
        header.pack(fill="x")

        title = tk.Label(header, text="FYJ CHANNEL REMOTE", font=("Segoe UI", 16, "bold"), fg="#38BDF8", bg="#1E293B")
        title.pack()

        subtitle = tk.Label(header, text="Koneksi Klien & Lab Automation", font=("Segoe UI", 9), fg="#94A3B8", bg="#1E293B")
        subtitle.pack()

        # Body Form
        body = tk.Frame(self, bg="#0F172A", padx=30, pady=16)
        body.pack(fill="both", expand=True)

        # Server Address
        tk.Label(body, text="Alamat Server WebSocket:", font=("Segoe UI", 9, "bold"), fg="#F8FAFC", bg="#0F172A").pack(anchor="w", pady=(0, 2))
        self.server_entry = tk.Entry(body, font=("Consolas", 10), bg="#1E293B", fg="#38BDF8", insertbackground="white", relief="flat")
        self.server_entry.insert(0, DEFAULT_SERVER_WS)
        self.server_entry.pack(fill="x", ipady=5, pady=(0, 10))

        # Channel Name
        tk.Label(body, text="Nama Channel / Ruangan:", font=("Segoe UI", 9, "bold"), fg="#F8FAFC", bg="#0F172A").pack(anchor="w", pady=(0, 2))
        self.channel_entry = tk.Entry(body, font=("Segoe UI", 10), bg="#1E293B", fg="#34D399", insertbackground="white", relief="flat")
        self.channel_entry.insert(0, DEFAULT_CHANNEL)
        self.channel_entry.pack(fill="x", ipady=5, pady=(0, 10))

        # Client Host Name / PC Name
        tk.Label(body, text="Nama Komputer (Host Name):", font=("Segoe UI", 9, "bold"), fg="#F8FAFC", bg="#0F172A").pack(anchor="w", pady=(0, 2))
        self.name_entry = tk.Entry(body, font=("Segoe UI", 10), bg="#1E293B", fg="#FBBF24", insertbackground="white", relief="flat")
        self.name_entry.insert(0, DEFAULT_AGENT_NAME)
        self.name_entry.pack(fill="x", ipady=5, pady=(0, 10))

        # Network Info Row (IP & MAC)
        net_frame = tk.Frame(body, bg="#0F172A")
        net_frame.pack(fill="x", pady=(0, 12))

        # IP Address
        ip_frame = tk.Frame(net_frame, bg="#0F172A")
        ip_frame.pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Label(ip_frame, text="Alamat IP (IPv4):", font=("Segoe UI", 9, "bold"), fg="#94A3B8", bg="#0F172A").pack(anchor="w", pady=(0, 2))
        self.ip_entry = tk.Entry(ip_frame, font=("Consolas", 9), bg="#1E293B", fg="#F8FAFC", insertbackground="white", relief="flat")
        self.ip_entry.insert(0, get_local_ip())
        self.ip_entry.pack(fill="x", ipady=5)

        # MAC Address
        mac_frame = tk.Frame(net_frame, bg="#0F172A")
        mac_frame.pack(side="right", fill="x", expand=True, padx=(6, 0))
        tk.Label(mac_frame, text="MAC Address:", font=("Segoe UI", 9, "bold"), fg="#94A3B8", bg="#0F172A").pack(anchor="w", pady=(0, 2))
        self.mac_entry = tk.Entry(mac_frame, font=("Consolas", 9), bg="#1E293B", fg="#A78BFA", insertbackground="white", relief="flat")
        self.mac_entry.insert(0, get_mac_address())
        self.mac_entry.pack(fill="x", ipady=5)

        # Status Bar Box
        self.status_box = tk.Frame(body, bg="#1E293B", padx=15, pady=8)
        self.status_box.pack(fill="x", pady=(0, 16))

        self.status_led = tk.Label(self.status_box, text="●", font=("Segoe UI", 16), fg="#EF4444", bg="#1E293B")
        self.status_led.pack(side="left", padx=(0, 10))

        self.status_text = tk.Label(self.status_box, text="Status: Terputus", font=("Segoe UI", 10, "bold"), fg="#94A3B8", bg="#1E293B")
        self.status_text.pack(side="left")

        # Connect / Disconnect Button
        self.btn_toggle = tk.Button(
            body,
            text="Hubungkan ke Channel",
            font=("Segoe UI", 11, "bold"),
            bg="#0284C7",
            fg="#FFFFFF",
            activebackground="#0369A1",
            activeforeground="#FFFFFF",
            relief="flat",
            cursor="hand2",
            command=self.toggle_connection
        )
        self.btn_toggle.pack(fill="x", ipady=8)

        # Footer
        footer = tk.Label(self, text="© FYJ Channel Remote • Powered by Antigravity", font=("Segoe UI", 8), fg="#64748B", bg="#0F172A", pady=8)
        footer.pack(side="bottom")

    def toggle_connection(self):
        if not self.is_connected:
            server = self.server_entry.get().strip()
            channel = self.channel_entry.get().strip().upper()
            name = self.name_entry.get().strip()
            ip_val = self.ip_entry.get().strip()
            mac_val = self.mac_entry.get().strip()

            if not server or not channel or not name:
                messagebox.showwarning("Peringatan", "Kolom Server, Channel, dan Nama Komputer wajib diisi!", parent=self)
                return

            self.is_connected = True
            self.btn_toggle.configure(text="Putuskan Sambungan", bg="#DC2626", activebackground="#B91C1C")
            self.status_led.configure(fg="#34D399")
            self.status_text.configure(text=f"Terhubung ke [{channel}]", fg="#34D399")
            self.server_entry.configure(state="disabled")
            self.channel_entry.configure(state="disabled")
            self.name_entry.configure(state="disabled")
            self.ip_entry.configure(state="disabled")
            self.mac_entry.configure(state="disabled")

            # Jalankan agent di thread background dengan data kustom
            self.agent_instance = FYJClientAgent(server, channel, name)
            if ip_val:
                self.agent_instance.local_ip = ip_val
            if mac_val:
                self.agent_instance.mac = mac_val
            self.agent_thread = threading.Thread(target=self._run_agent_loop, daemon=True)
            self.agent_thread.start()
        else:
            self._disconnect()

    def _disconnect(self):
        self.is_connected = False
        if self.agent_instance:
            self.agent_instance.running = False
        self.btn_toggle.configure(text="Hubungkan ke Channel", bg="#0284C7", activebackground="#0369A1")
        self.status_led.configure(fg="#EF4444")
        self.status_text.configure(text="Status: Terputus", fg="#94A3B8")
        self.server_entry.configure(state="normal")
        self.channel_entry.configure(state="normal")
        self.name_entry.configure(state="normal")
        self.ip_entry.configure(state="normal")
        self.mac_entry.configure(state="normal")

    def _run_agent_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.agent_instance.connect_and_run())
        except Exception:
            pass
        finally:
            self.after(0, self._disconnect)

if __name__ == "__main__":
    app = FYJAgentApp()
    app.mainloop()
