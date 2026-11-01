/**
 * FYJ Channel Remote - Remote Control Engine
 * Menangani interaksi mouse, keyboard, dan render stream kanvas berlatensi rendah.
 */

class RemoteEngine {
  constructor() {
    this.overlay = document.getElementById("remoteOverlay");
    this.canvas = document.getElementById("remoteCanvas");
    this.ctx = this.canvas.getContext("2d");
    this.container = document.getElementById("canvasContainer");

    this.activeAgentId = null;
    this.activeAgentInfo = null;
    this.isControlling = true; // Mode interaksi aktif (vs view-only)
    this.ws = null;

    // Metrik performa
    this.frameCount = 0;
    this.lastFpsCalcTime = Date.now();
    this.fpsElem = document.getElementById("remoteFps");
    this.latencyElem = document.getElementById("remoteLatency");

    this.imageBuffer = new Image();
    this.imageBuffer.onload = () => {
      this.renderFrame();
    };

    this.setupListeners();
  }

  setWebSocket(ws) {
    this.ws = ws;
  }

  startRemote(agentId, agentInfo) {
    this.activeAgentId = agentId;
    this.activeAgentInfo = agentInfo;

    document.getElementById("remoteTargetName").textContent = agentInfo.name || "Target PC";
    document.getElementById("remoteTargetMeta").textContent = `${agentInfo.ip || "Unknown IP"} • ${agentInfo.os || "Windows"} • ${agentInfo.resolution || "1920x1080"}`;

    this.overlay.classList.remove("hidden");
    document.body.style.overflow = "hidden";

    // Beritahu server dan agent untuk beralih ke mode kontrol resolusi tinggi (active mode)
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        type: "set_agent_mode",
        target_id: agentId,
        mode: "active"
      }));
    }

    this.frameCount = 0;
    this.lastFpsCalcTime = Date.now();
  }

  stopRemote() {
    if (!this.activeAgentId) return;

    // Beritahu agent untuk kembali ke mode hemat bandwidth (thumbnail)
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        type: "set_agent_mode",
        target_id: this.activeAgentId,
        mode: "thumbnail"
      }));
    }

    this.activeAgentId = null;
    this.activeAgentInfo = null;
    this.overlay.classList.add("hidden");
    document.body.style.overflow = "auto";
  }

  onFrameReceived(base64Data, timestamp) {
    if (!this.activeAgentId) return;

    // Hitung estimasi latensi round-trip
    if (timestamp) {
      const now = Date.now() / 1000;
      const latencyMs = Math.max(1, Math.round((now - timestamp) * 1000));
      this.latencyElem.textContent = `${latencyMs} ms`;
    }

    // Hitung FPS
    this.frameCount++;
    const elapsed = Date.now() - this.lastFpsCalcTime;
    if (elapsed >= 1000) {
      const fps = Math.round((this.frameCount * 1000) / elapsed);
      this.fpsElem.textContent = `${fps}`;
      this.frameCount = 0;
      this.lastFpsCalcTime = Date.now();
    }

    // Muat gambar ke buffer kanvas
    this.imageBuffer.src = `data:image/jpeg;base64,${base64Data}`;
  }

  renderFrame() {
    const img = this.imageBuffer;
    if (!img.width || !img.height) return;

    // Sesuaikan resolusi kanvas sesuai aspek rasio frame
    if (this.canvas.width !== img.width || this.canvas.height !== img.height) {
      this.canvas.width = img.width;
      this.canvas.height = img.height;
    }

    this.ctx.drawImage(img, 0, 0, this.canvas.width, this.canvas.height);
  }

  getNormalizedCoordinates(e) {
    const rect = this.canvas.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    return {
      x: Math.max(0, Math.min(1, x)),
      y: Math.max(0, Math.min(1, y))
    };
  }

  sendInput(inputData) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN || !this.activeAgentId || !this.isControlling) {
      return;
    }
    this.ws.send(JSON.stringify({
      type: "remote_input",
      target_id: this.activeAgentId,
      ...inputData
    }));
  }

  setupListeners() {
    // Navigasi & Tombol HUD
    document.getElementById("btnBackToGrid").addEventListener("click", () => this.stopRemote());
    document.getElementById("btnCloseRemote").addEventListener("click", () => this.stopRemote());

    // Toggle Input Mode (Kontrol vs View Only)
    const btnMode = document.getElementById("btnToggleInputMode");
    btnMode.addEventListener("click", () => {
      this.isControlling = !this.isControlling;
      if (this.isControlling) {
        btnMode.textContent = "🎮 Kontrol Penuh";
        btnMode.style.background = "var(--accent-emerald)";
      } else {
        btnMode.textContent = "👁️ Lihat Saja";
        btnMode.style.background = "var(--accent-amber)";
      }
    });

    // Fullscreen Toggle
    document.getElementById("btnToggleFullscreen").addEventListener("click", () => {
      if (!document.fullscreenElement) {
        this.overlay.requestFullscreen().catch(() => {});
      } else {
        document.exitFullscreen().catch(() => {});
      }
    });

    // Shortcut toolbar Windows
    document.querySelectorAll(".btn-shortcut").forEach(btn => {
      btn.addEventListener("click", () => {
        const shortcut = btn.getAttribute("data-shortcut");
        this.sendInput({
          input_type: "shortcut",
          name: shortcut
        });
      });
    });

    // === MOUSE EVENTS PADA KANVAS ===
    this.canvas.addEventListener("mousemove", (e) => {
      const pos = this.getNormalizedCoordinates(e);
      this.sendInput({
        input_type: "mouse_move",
        x: pos.x,
        y: pos.y
      });
    });

    this.canvas.addEventListener("mousedown", (e) => {
      e.preventDefault();
      const pos = this.getNormalizedCoordinates(e);
      let btn = "left";
      if (e.button === 1) btn = "middle";
      if (e.button === 2) btn = "right";

      this.sendInput({
        input_type: "mouse_event",
        action: "down",
        button: btn,
        x: pos.x,
        y: pos.y
      });
    });

    this.canvas.addEventListener("mouseup", (e) => {
      e.preventDefault();
      const pos = this.getNormalizedCoordinates(e);
      let btn = "left";
      if (e.button === 1) btn = "middle";
      if (e.button === 2) btn = "right";

      this.sendInput({
        input_type: "mouse_event",
        action: "up",
        button: btn,
        x: pos.x,
        y: pos.y
      });
    });

    this.canvas.addEventListener("contextmenu", (e) => {
      e.preventDefault(); // Matikan klik kanan browser agar masuk ke target PC
    });

    this.canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      const delta = e.deltaY < 0 ? 1 : -1;
      this.sendInput({
        input_type: "wheel",
        delta: delta
      });
    }, { passive: false });

    // === KEYBOARD EVENTS ===
    window.addEventListener("keydown", (e) => {
      if (this.overlay.classList.contains("hidden") || !this.isControlling) return;

      // Blokir tombol browser tertentu agar tidak tab keluar
      if (["Tab", "Alt", "F5"].includes(e.key)) {
        e.preventDefault();
      }

      this.sendInput({
        input_type: "key_event",
        action: "down",
        key: e.key
      });
    });

    window.addEventListener("keyup", (e) => {
      if (this.overlay.classList.contains("hidden") || !this.isControlling) return;
      this.sendInput({
        input_type: "key_event",
        action: "up",
        key: e.key
      });
    });
  }
}

// Inisialisasi engine
window.remoteEngine = new RemoteEngine();

