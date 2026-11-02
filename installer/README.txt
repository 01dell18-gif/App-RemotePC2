FOLDER INSTALLER FYJ CHANNEL REMOTE
=====================================================
Folder ini berisi aplikasi dan dependensi pustaka offline untuk
memastikan FYJ Channel Remote dapat diinstal dan dijalankan secara
otomatis pada komputer target (klien/siswa) maupun komputer master
tanpa ketergantungan koneksi internet.

DAFTAR FILE:
1. python-3.11.9-amd64.exe
   Installer resmi Python 3.11 (64-bit) untuk Windows.
   Diinstal otomatis dalam silent mode (/quiet) oleh start_fyj_remote.bat
   jika komputer target belum memiliki Python.

2. packages/
   Kumpulan binary wheel (.whl) pustaka yang dibutuhkan:
   - websockets (WebSocket client & server)
   - pillow (Screen frame processing & screenshot manipulation)
   - psutil (Monitoring CPU, RAM, OS status)
   - mss (Ultra-fast cross-platform screen capture)
   - pywin32 (Windows User32 API injection, screen lock, window control)

MEKANISME KERJA OTOMATIS:
Saat start_fyj_remote.bat dijalankan:
1. Memeriksa apakah Python sudah terpasang.
2. Jika belum, menginstal Python secara otomatis dari folder ini tanpa perlu download lagi.
3. Memeriksa apakah pustaka sudah lengkap.
4. Jika belum, memasang pustaka dari subfolder 'packages' secara offline.
5. Menjalankan aplikasi web secara otomatis.
