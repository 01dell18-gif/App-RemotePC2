# FYJ Channel Remote ⚡
> **Aplikasi Web Modern untuk Kontrol & Monitoring Komputer Jarak Jauh (Classroom & Lab Management)**  
> *Didesain sebagai alternatif modern, ringan, dan web-native dari Veyon (`C:\Program Files\Veyon`).*

---

## 🌟 Mengapa FYJ Channel Remote?

**Veyon** adalah perangkat lunak monitoring komputer lab yang sangat populer, namun memiliki beberapa friksi teknis di era modern:
1. **Wajib Install Aplikasi Desktop Master (`veyon-master.exe`):** Pengawas atau guru harus menginstal aplikasi Qt6 C++ yang berat di PC pengendali.
2. **Keterbatasan Platform Master:** Guru tidak bisa mengontrol lab dari iPad, tablet Android, laptop non-Windows, atau browser web tanpa remote desktop tambahan.
3. **Konfigurasi Kunci Kriptografi Rumit (`authkeys`):** Administrator harus membuat pasangan kunci publik/privat secara manual dan memindahkannya ke setiap PC klien menggunakan USB atau jaringan.

### Keunggulan "FYJ Channel Remote":
* ✅ **100% Web-Native Master Controller:** Cukup buka browser (Chrome, Edge, Safari, Firefox) di PC, laptop, atau tablet. Tanpa instalasi software apa pun pada sisi pengawas.
* ✅ **Channel-Based Pairing:** Konsep *Channel* (misal `LAB-UTAMA`, `LAB-DKV-1`, `RUANG-KELAS-A`) memudahkan segmentasi komputer per ruangan.
* ✅ **Zero-Configuration Client Agent:** Klien cukup menjalankan `run_agent.bat` atau `run_agent_gui.bat`, memilih channel, dan langsung terhubung.
* ✅ **Fitur Lengkap Ekuivalen Veyon:**
  * **Monitoring Grid Matrix:** Pantau puluhan layar PC murid secara bersamaan dalam tampilan grid responsif (Ukuran S/M/L).
  * **Interactive Full Control Mode:** Kendalikan mouse, klik, scroll, dan ketikan keyboard secara real-time dengan latensi rendah.
  * **Screen Lock (`screenlock.dll` Veyon):** Kunci semua layar murid dengan pesan instruksi khusus untuk memusatkan perhatian ke guru.
  * **Broadcast / Demo Mode (`demo.dll` Veyon):** Guru dapat membagikan layar presentasinya langsung ke seluruh PC siswa.
  * **Remote Announcements (`textmessage.dll` Veyon):** Kirim pesan pop-up massal atau perorangan ke layar siswa.
  * **Push URL / Web Opener (`desktopservices.dll` Veyon):** Buka link materi secara otomatis di browser default seluruh siswa.
  * **Power Control (`powercontrol.dll` Veyon):** Matikan (Shutdown), Restart, Lock Workstation, atau Sign Out seluruh PC sekali klik.

---

## 🏗️ Arsitektur Sistem

```
┌────────────────────────────────────────────────────────┐
│             WEB MASTER CONTROLLER (BROWSER)            │
│  - HTML5 Canvas Low-Latency Stream Renderer            │
│  - Multi-Screen Matrix Grid (Monitoring 30+ PC)        │
│  - Global Action Bar (Lock, Message, URL, Power)       │
└──────────────────────────┬─────────────────────────────┘
                           │ HTTP: 8080 | WebSocket: 8081
                           ▼
┌────────────────────────────────────────────────────────┐
│             FYJ GATEWAY & RELAY SERVER                 │
│  - Python Asyncio WebSocket Relay Hub                  │
│  - Channel Routing & Authentication Token Isolator     │
│  - HTTP Static & REST API Server                       │
└──────────────────────────▲─────────────────────────────┘
                           │ WebSocket: 8081
       ┌───────────────────┼───────────────────┐
       ▼                   ▼                   ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  AGENT PC-01 │    │  AGENT PC-02 │    │  AGENT PC-03 │
│  (Target PC) │    │  (Target PC) │    │  (Target PC) │
└──────────────┘    └──────────────┘    └──────────────┘
 - Desktop Capture (DXGI/GDI)
 - Windows Input Injection (ctypes User32 API)
 - Topmost Screen Lock Overlay
 - Power & System Service
```

---

## 🚀 Panduan Memulai Cepat (Quick Start)

### 1. Menjalankan Server & Web Master
Pada komputer server atau komputer guru:
1. Klik ganda file:
   ```cmd
   start_fyj_remote.bat
   ```
   *(atau `run_server.bat`)*
2. File batch akan otomatis:
   * Memeriksa apakah Python sudah terpasang. Jika belum, sistem akan mengunduh dan memasangnya secara otomatis (*silent install*).
   * Memeriksa dependensi pustaka (`websockets`, `pillow`, `psutil`). Jika belum ada, sistem akan menginstalnya via pip secara otomatis.
   * Mendeteksi alamat IP LAN komputer server.
   * Menyalakan server dan langsung membuka browser di `http://localhost:8080`.
3. Komputer/perangkat lain di jaringan LAN/Wi-Fi (Laptop guru, iPad/Tablet, atau HP) dapat langsung membuka dashboard melalui alamat IP yang tertera pada konsol server (contoh: `http://10.10.10.159:8080`).

---

### 2. Menjalankan Agent di Komputer Siswa/Klien
Pada komputer yang ingin dipantau / dikontrol:
1. **Opsi A (Dengan Antarmuka Grafis / GUI):**
   * Klik ganda `run_agent_gui.bat`.
   * Masukkan alamat Server WebSocket (contoh: `ws://192.168.1.100:8081`).
   * Pilih nama Channel (contoh: `LAB-UTAMA`).
   * Klik **"Hubungkan ke Channel"**.
2. **Opsi B (Mode CLI / Background):**
   * Klik ganda `run_agent.bat` atau jalankan via terminal:
     ```cmd
     python agent/fyj_agent.py --server ws://192.168.1.100:8081 --channel LAB-UTAMA
     ```

---

## 📁 Struktur Direktori

```
App-Remote2/
├── server/
│   └── server.py             # Server Relay WebSocket & HTTP Web Master
├── agent/
│   ├── fyj_agent.py          # Script Target Client Agent (Capture, Input, Control)
│   ├── fyj_agent_gui.py      # Antarmuka Grafis (Tkinter) Klien
│   └── requirements.txt      # Daftar dependensi Python
├── web/
│   ├── index.html            # Antarmuka Dashboard Web Master
│   ├── css/
│   │   └── style.css         # Desain sistem cyber-modern dark theme
│   └── js/
│       ├── app.js            # Logika dashboard, grid monitoring, aksi massal
│       └── remote.js         # Engine kontrol interaktif kanvas & input handler
├── run_server.bat            # 1-Klik peluncur server & browser
├── run_agent.bat             # 1-Klik peluncur agent klien (CLI)
├── run_agent_gui.bat         # 1-Klik peluncur agent klien (GUI)
└── README.md                 # Dokumentasi teknis & panduan lengkap
```

---

## 🛠️ Tombol Pintas & Shortcut Windows Remote

Saat berada dalam mode kendali langsung (*Full Remote Control*):
* `[Win]`: Membuka menu Start Windows.
* `[Win+D]`: Menampilkan desktop secara langsung.
* `[Alt+Tab]`: Berpindah antar-jendela aplikasi.
* `[TaskMgr]`: Membuka Task Manager Windows (`Ctrl+Shift+Esc`).
* `[Kontrol Penuh / Lihat Saja]`: Beralih antara mode interaktif dan mode observasi.
* `[⛶ Layar Penuh]`: Memaksimalkan tampilan kontrol ke seluruh layar monitor.
* `Esc` atau `← Kembali ke Grid`: Menutup sesi kontrol dan kembali ke dashboard monitoring.

---

## 🔒 Lisensi & Keamanan
Aplikasi ini dikembangkan untuk tujuan edukasi, manajemen lab komputer, dan administrasi sistem yang sah. Selalu gunakan otentikasi jaringan yang aman pada lingkungan produksi.

