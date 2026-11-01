/**
 * FYJ Channel Remote - Main Web Master Application
 * Menghubungkan dashboard dengan WebSocket Relay Server dan mengelola armada PC.
 */

class FYJMasterApp {
  constructor() {
    this.currentChannel = "LAB-UTAMA";
    this.ws = null;
    this.agents = new Map(); // agentId -> agentData
    this.selectedAgents = new Set(); // Set of selected agentId
    this.scripts = []; // List of automation scripts
    this.reconnectTimer = null;
    this.isDemoActive = false;
    this.demoStream = null;

    this.initElements();
    this.bindEvents();
    this.fetchServerStatus();
    this.fetchScripts();
    this.connectWebSocket();
  }

  initElements() {
    this.channelSelect = document.getElementById("channelSelect");
    this.lblActiveChannel = document.getElementById("lblActiveChannel");
    this.lblEmptyChannel = document.getElementById("lblEmptyChannel");
    this.lblLanInfo = document.getElementById("lblLanInfo");
    this.connIndicator = document.getElementById("connIndicator");
    this.connStatusText = document.getElementById("connStatusText");
    this.statAgentCount = document.getElementById("statAgentCount");
    this.clientGrid = document.getElementById("clientGrid");
    this.emptyState = document.getElementById("emptyState");
    this.searchInput = document.getElementById("searchInput");
    this.toastContainer = document.getElementById("toastContainer");

    // Selection elements
    this.btnSelectAll = document.getElementById("btnSelectAll");
    this.btnDeselectAll = document.getElementById("btnDeselectAll");
    this.selectionCounterBadge = document.getElementById("selectionCounterBadge");

    // Script elements
    this.quickScriptList = document.getElementById("quickScriptList");
    this.scriptsTableBody = document.getElementById("scriptsTableBody");
    this.scriptSearchInput = document.getElementById("scriptSearchInput");
    this.scriptsTargetDesc = document.getElementById("scriptsTargetDesc");

    // Terminal elements
    this.modalScriptOutput = document.getElementById("modalScriptOutput");
    this.terminalLogs = document.getElementById("terminalLogs");
    this.outScriptTitle = document.getElementById("outScriptTitle");
    this.outTargetDesc = document.getElementById("outTargetDesc");
    this.outStatusPill = document.getElementById("outStatusPill");
    this.btnCopyTerminal = document.getElementById("btnCopyTerminal");
  }

  // === KONEKSI WEBSOCKET MASTER ===
  connectWebSocket() {
    if (this.ws) {
      try { this.ws.close(); } catch (e) {}
    }

    const host = window.location.hostname || "127.0.0.1";
    const wsUrl = `ws://${host}:8081?role=master&channel=${this.currentChannel}`;
    this.updateConnStatus(false, "Menghubungkan ke Relay...");

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.updateConnStatus(true, "Terhubung ke Server");
        this.showToast(`Bergabung ke Channel: ${this.currentChannel}`, "success");
        if (window.remoteEngine) {
          window.remoteEngine.setWebSocket(this.ws);
        }
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.handleServerMessage(data);
        } catch (e) {
          console.error("Error parsing WS message:", e);
        }
      };

      this.ws.onclose = () => {
        this.updateConnStatus(false, "Terputus dari Relay");
        this.scheduleReconnect();
      };

      this.ws.onerror = () => {
        this.updateConnStatus(false, "Koneksi Error");
      };
    } catch (e) {
      this.updateConnStatus(false, "Gagal Membuat WS");
      this.scheduleReconnect();
    }
  }

  scheduleReconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => {
      this.connectWebSocket();
    }, 3000);
  }

  updateConnStatus(isOnline, text) {
    if (isOnline) {
      this.connIndicator.classList.add("online");
    } else {
      this.connIndicator.classList.remove("online");
    }
    this.connStatusText.textContent = text;
  }

  // === HANDLER PESAN SERVER ===
  handleServerMessage(data) {
    const type = data.type;

    if (type === "channel_state") {
      this.agents.clear();
      (data.agents || []).forEach(agent => {
        this.agents.set(agent.id, agent);
      });
      // Bersihkan agent terpilih yang sudah tidak ada
      const validIds = new Set(this.agents.keys());
      this.selectedAgents.forEach(id => {
        if (!validIds.has(id)) this.selectedAgents.delete(id);
      });
      this.updateSelectionUI();
      this.renderGrid();
    } else if (type === "agent_joined") {
      this.agents.set(data.agent.id, data.agent);
      this.renderGrid();
      this.showToast(`Klien baru terhubung: ${data.agent.name}`, "info");
    } else if (type === "agent_left") {
      const existing = this.agents.get(data.agent_id);
      if (existing) {
        this.showToast(`Klien terputus: ${existing.name}`, "warning");
      }
      this.agents.delete(data.agent_id);
      this.selectedAgents.delete(data.agent_id);
      this.updateSelectionUI();
      this.renderGrid();
      if (window.remoteEngine && window.remoteEngine.activeAgentId === data.agent_id) {
        window.remoteEngine.stopRemote();
        this.showToast("Sesi remote ditutup karena klien terputus.", "danger");
      }
    } else if (type === "agent_updated") {
      if (this.agents.has(data.agent.id)) {
        Object.assign(this.agents.get(data.agent.id), data.agent);
      } else {
        this.agents.set(data.agent.id, data.agent);
      }
      this.renderGrid();
    } else if (type === "device_deleted") {
      this.agents.delete(data.agent_id);
      this.selectedAgents.delete(data.agent_id);
      this.updateSelectionUI();
      this.renderGrid();
      this.showToast(`Perangkat berhasil dihapus dari sistem.`, "info");
    } else if (type === "agent_stats") {
      if (this.agents.has(data.agent_id)) {
        const ag = this.agents.get(data.agent_id);
        Object.assign(ag, data.stats);
        this.updateCardStats(data.agent_id);
      }
    } else if (type === "screen_frame") {
      if (window.remoteEngine && window.remoteEngine.activeAgentId === data.agent_id) {
        window.remoteEngine.onFrameReceived(data.frame, data.timestamp);
      }
      this.updateCardThumbnail(data.agent_id, data.frame);
    } else if (type === "script_result") {
      this.handleScriptResult(data);
    }
  }

  // === SELECTION SYSTEM LOGIC ===
  toggleSelectAgent(agentId, isChecked) {
    if (isChecked) {
      this.selectedAgents.add(agentId);
    } else {
      this.selectedAgents.delete(agentId);
    }
    const card = document.getElementById(`card-${agentId}`);
    if (card) {
      if (isChecked) card.classList.add("is-selected");
      else card.classList.remove("is-selected");
    }
    this.updateSelectionUI();
  }

  selectAllAgents() {
    this.agents.forEach((_, id) => {
      this.selectedAgents.add(id);
      const card = document.getElementById(`card-${id}`);
      if (card) {
        card.classList.add("is-selected");
        const cb = card.querySelector(".pc-checkbox");
        if (cb) cb.checked = true;
      }
    });
    this.updateSelectionUI();
    this.showToast(`Semua komputer (${this.agents.size} PC) dipilih!`, "info");
  }

  deselectAllAgents() {
    this.selectedAgents.clear();
    document.querySelectorAll(".pc-card").forEach(card => card.classList.remove("is-selected"));
    document.querySelectorAll(".pc-checkbox").forEach(cb => cb.checked = false);
    this.updateSelectionUI();
  }

  updateSelectionUI() {
    const count = this.selectedAgents.size;
    if (count > 0) {
      this.selectionCounterBadge.textContent = `${count} PC Dipilih`;
      this.selectionCounterBadge.classList.add("has-selected");
      if (this.scriptsTargetDesc) {
        this.scriptsTargetDesc.textContent = `Target: ${count} PC Terpilih`;
      }
    } else {
      this.selectionCounterBadge.textContent = "0 PC Dipilih (Target Semua)";
      this.selectionCounterBadge.classList.remove("has-selected");
      if (this.scriptsTargetDesc) {
        this.scriptsTargetDesc.textContent = `Target: Semua PC di Channel`;
      }
    }
  }

  getTargetAgentIds() {
    if (this.selectedAgents.size > 0) {
      return Array.from(this.selectedAgents);
    }
    return Array.from(this.agents.keys());
  }

  // === RENDER GRID MONITORING ===
  renderGrid() {
    const query = (this.searchInput.value || "").toLowerCase();
    this.statAgentCount.textContent = this.agents.size;

    if (this.agents.size === 0) {
      this.emptyState.style.display = "flex";
      this.clientGrid.style.display = "none";
      return;
    }

    this.emptyState.style.display = "none";
    this.clientGrid.style.display = "grid";

    // Rebuild cards yang cocok dengan filter
    this.clientGrid.innerHTML = "";
    this.agents.forEach(agent => {
      const match = (agent.name || "").toLowerCase().includes(query) ||
                    (agent.hostname || "").toLowerCase().includes(query) ||
                    (agent.ip || "").toLowerCase().includes(query) ||
                    (agent.mac || "").toLowerCase().includes(query);
      if (match) {
        this.createCardElement(agent);
      }
    });
  }

  createCardElement(agent) {
    const card = document.createElement("div");
    const isOffline = (agent.status === "offline");
    const isSelected = this.selectedAgents.has(agent.id);

    card.className = `pc-card ${agent.is_locked ? "is-locked" : ""} ${isOffline ? "is-offline" : ""} ${isSelected ? "is-selected" : ""}`;
    card.id = `card-${agent.id}`;

    const hostSub = (agent.hostname && agent.hostname !== agent.name) ? `<span class="pc-host-sub">(${agent.hostname})</span>` : '';
    const macDisplay = agent.mac || "00:00:00:00:00:00";
    const dotClass = isOffline ? "status-dot-offline" : "status-dot-pc";
    const dotTitle = isOffline ? "Status: Offline (Menunggu Klien)" : "Status: Online (Live Desktop)";
    const thumbSrc = agent.last_frame ? `data:image/jpeg;base64,${agent.last_frame}` : "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='320' height='180' fill='%230B0F19'></svg>";

    card.innerHTML = `
      <div class="card-header">
        <div class="pc-check-title">
          <label class="custom-checkbox-wrapper" title="Pilih PC ini untuk aksi">
            <input type="checkbox" class="pc-checkbox" data-id="${agent.id}" ${isSelected ? 'checked' : ''}>
            <span class="checkbox-mark"></span>
          </label>
          <span class="${dotClass}" title="${dotTitle}"></span>
          <div class="pc-name-container">
            <span class="pc-name" title="${agent.name}">${agent.name}</span>
            ${hostSub}
          </div>
        </div>
        <div class="card-header-actions">
          ${isOffline ? '<span class="badge-offline-tag">OFFLINE</span>' : ''}
          <button class="btn-mini btn-edit-device" data-action="edit" data-id="${agent.id}" title="Edit Host Name, IP & MAC Address">✏️</button>
          <button class="btn-mini btn-delete-device" data-action="delete" data-id="${agent.id}" title="Hapus Perangkat Tidak Digunakan">🗑️</button>
        </div>
      </div>

      <div class="card-net-bar">
        <span class="net-tag net-ip" title="Alamat IP"><i class="tag-ico">🌐</i> <span id="ip-val-${agent.id}">${agent.ip || "127.0.0.1"}</span></span>
        <span class="net-tag net-mac" title="MAC Address"><i class="tag-ico">🏷️</i> <span id="mac-val-${agent.id}">${macDisplay}</span></span>
      </div>

      <div class="card-screen" data-id="${agent.id}">
        ${isOffline ? `
          <div class="offline-placeholder">
            <span class="offline-ico">📡</span>
            <span class="offline-title">Menunggu Klien Aktif</span>
            <span class="offline-hint">Jalankan <code>run_agent.bat</code> di PC ini</span>
          </div>
          <div class="screen-hover-overlay">
            <button class="btn-card-control" data-action="edit" data-id="${agent.id}">
              ⚙️ Pengaturan PC
            </button>
          </div>
        ` : `
          <img id="thumb-${agent.id}" src="${thumbSrc}" alt="${agent.name}">
          ${agent.is_locked ? '<div class="lock-banner">🔒 TERKUNCI</div>' : ''}
          <div class="screen-hover-overlay">
            <button class="btn-card-control" data-action="control" data-id="${agent.id}">
              🕹️ Kendalikan
            </button>
          </div>
        `}
      </div>

      <div class="card-footer">
        ${isOffline ? `
          <div class="offline-footer-row">
            <span class="offline-notes-tag" title="${agent.notes || ''}">📍 ${agent.notes || "Lokasi belum diatur"}</span>
            <div class="card-btn-group">
              <button class="btn-mini" data-action="edit" data-id="${agent.id}" title="Edit Detail">⚙️</button>
              <button class="btn-mini btn-delete-device" data-action="delete" data-id="${agent.id}" title="Hapus Perangkat">🗑️</button>
            </div>
          </div>
        ` : `
          <div class="perf-bars">
            <div class="metric-bar-group">
              <div class="bar-meta">
                <span>CPU</span>
                <span id="cpu-val-${agent.id}">${agent.cpu || 0}%</span>
              </div>
              <div class="progress-track">
                <div id="cpu-bar-${agent.id}" class="progress-fill cpu" style="width: ${agent.cpu || 0}%"></div>
              </div>
            </div>
            <div class="metric-bar-group">
              <div class="bar-meta">
                <span>RAM</span>
                <span id="ram-val-${agent.id}">${agent.ram || 0}%</span>
              </div>
              <div class="progress-track">
                <div id="ram-bar-${agent.id}" class="progress-fill ram" style="width: ${agent.ram || 0}%"></div>
              </div>
            </div>
          </div>

          <div class="card-actions-quick">
            <span class="active-window-label" id="win-title-${agent.id}" title="${agent.active_window || ''}">
              ${agent.active_window || "Desktop"}
            </span>
            <div class="card-btn-group">
              <button class="btn-mini lock-toggle" data-action="toggle-lock" data-id="${agent.id}" title="Kunci / Buka Layar">🔒</button>
              <button class="btn-mini" data-action="msg" data-id="${agent.id}" title="Kirim Pesan">💬</button>
              <button class="btn-mini" data-action="power" data-id="${agent.id}" title="Opsi Daya">⚡</button>
              <button class="btn-mini" data-action="edit" data-id="${agent.id}" title="Edit Host Name & Jaringan">⚙️</button>
              <button class="btn-mini btn-delete-device" data-action="delete" data-id="${agent.id}" title="Hapus Perangkat">🗑️</button>
            </div>
          </div>
        `}
      </div>
    `;

    // Checkbox listener
    const chk = card.querySelector(".pc-checkbox");
    if (chk) {
      chk.addEventListener("change", (e) => {
        this.toggleSelectAgent(agent.id, e.target.checked);
      });
    }

    // Tombol Edit
    card.querySelectorAll('[data-action="edit"]').forEach(btn => {
      btn.addEventListener("click", () => {
        this.openEditDeviceModal(agent.id);
      });
    });

    // Tombol Hapus Perangkat
    card.querySelectorAll('[data-action="delete"]').forEach(btn => {
      btn.addEventListener("click", () => {
        this.confirmDeleteDevice(agent.id, agent.name);
      });
    });

    if (!isOffline) {
      card.querySelector('[data-action="control"]')?.addEventListener("click", () => {
        window.remoteEngine.startRemote(agent.id, agent);
      });

      card.querySelector('.card-screen')?.addEventListener("dblclick", () => {
        window.remoteEngine.startRemote(agent.id, agent);
      });

      card.querySelector('[data-action="toggle-lock"]')?.addEventListener("click", () => {
        this.toggleLockSingle(agent.id);
      });

      card.querySelector('[data-action="msg"]')?.addEventListener("click", () => {
        this.openMessageModal(agent.id, agent.name);
      });

      card.querySelector('[data-action="power"]')?.addEventListener("click", () => {
        this.openPowerModal(agent.id);
      });
    }

    this.clientGrid.appendChild(card);
  }

  updateCardThumbnail(agentId, base64Frame) {
    if (this.agents.has(agentId)) {
      this.agents.get(agentId).last_frame = base64Frame;
      if (this.agents.get(agentId).status === "offline") {
        this.agents.get(agentId).status = "online";
        this.renderGrid();
        return;
      }
    }
    const thumbImg = document.getElementById(`thumb-${agentId}`);
    if (thumbImg) {
      thumbImg.src = `data:image/jpeg;base64,${base64Frame}`;
    }
  }

  updateCardStats(agentId) {
    const ag = this.agents.get(agentId);
    if (!ag) return;

    const cpuVal = document.getElementById(`cpu-val-${agentId}`);
    const cpuBar = document.getElementById(`cpu-bar-${agentId}`);
    const ramVal = document.getElementById(`ram-val-${agentId}`);
    const ramBar = document.getElementById(`ram-bar-${agentId}`);
    const winTitle = document.getElementById(`win-title-${agentId}`);
    const card = document.getElementById(`card-${agentId}`);

    if (cpuVal) cpuVal.textContent = `${ag.cpu}%`;
    if (cpuBar) cpuBar.style.width = `${ag.cpu}%`;
    if (ramVal) ramVal.textContent = `${ag.ram}%`;
    if (ramBar) ramBar.style.width = `${ag.ram}%`;
    if (winTitle) {
      winTitle.textContent = ag.active_window || "Desktop";
      winTitle.title = ag.active_window || "";
    }

    if (card) {
      if (ag.is_locked) {
        card.classList.add("is-locked");
      } else {
        card.classList.remove("is-locked");
      }
    }
  }

  // === PERINTAH MASAL & KONTROL (VEYON ACTIONS) ===
  sendCommand(targetId, command, params = {}) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.showToast("WebSocket belum terhubung!", "danger");
      return;
    }
    this.ws.send(JSON.stringify({
      type: "remote_command",
      target_id: targetId,
      command: command,
      params: params
    }));
  }

  // Kunci / Buka Kunci dengan dukungan Perangkat Terpilih
  executeLockAction() {
    const targets = this.getTargetAgentIds();
    if (targets.length === 0) {
      this.showToast("Tidak ada perangkat yang terdeteksi.", "warning");
      return;
    }

    if (this.selectedAgents.size > 0) {
      this.selectedAgents.forEach(id => {
        this.sendCommand(id, "lock", { message: "PERHATIAN: Layar Dikunci oleh Pengawas Lab" });
        if (this.agents.has(id)) this.agents.get(id).is_locked = true;
      });
      this.showToast(`Layar ${this.selectedAgents.size} PC terpilih berhasil dikunci!`, "warning");
    } else {
      this.sendCommand("all", "lock", { message: "PERHATIAN: Layar Dikunci oleh Pengawas Lab" });
      this.agents.forEach(a => a.is_locked = true);
      this.showToast(`Semua layar (${this.agents.size} PC) berhasil dikunci!`, "warning");
    }
    this.renderGrid();
  }

  executeUnlockAction() {
    const targets = this.getTargetAgentIds();
    if (targets.length === 0) return;

    if (this.selectedAgents.size > 0) {
      this.selectedAgents.forEach(id => {
        this.sendCommand(id, "unlock");
        if (this.agents.has(id)) this.agents.get(id).is_locked = false;
      });
      this.showToast(`Kunci layar ${this.selectedAgents.size} PC terpilih berhasil dibuka!`, "success");
    } else {
      this.sendCommand("all", "unlock");
      this.agents.forEach(a => a.is_locked = false);
      this.showToast(`Semua layar komputer berhasil dibuka!`, "success");
    }
    this.renderGrid();
  }

  toggleLockSingle(agentId) {
    const ag = this.agents.get(agentId);
    if (!ag) return;
    if (ag.is_locked) {
      this.sendCommand(agentId, "unlock");
      ag.is_locked = false;
      this.showToast(`Membuka kunci layar: ${ag.name}`, "info");
    } else {
      this.sendCommand(agentId, "lock", { message: "Layar Dikunci oleh Pengawas Lab" });
      ag.is_locked = true;
      this.showToast(`Mengunci layar: ${ag.name}`, "warning");
    }
    this.renderGrid();
  }

  // === FITUR DEMO MODE (SCREEN BROADCAST MASTER) ===
  async toggleDemoMode() {
    const actionLabel = document.getElementById("lblDemoActionTitle");
    if (!this.isDemoActive) {
      try {
        this.demoStream = await navigator.mediaDevices.getDisplayMedia({ video: true });
        this.isDemoActive = true;
        if (actionLabel) actionLabel.textContent = "Hentikan Demo Layar";
        this.showToast("Mode Demo Layar Pengajar Aktif!", "success");

        this.sendCommand("all", "message", {
          title: "Demo Layar Pengajar",
          message: "Pengajar sedang membagikan layar presentasi."
        });

        this.demoStream.getVideoTracks()[0].onended = () => {
          this.stopDemoMode();
        };
      } catch (err) {
        this.showToast("Gagal memulai tangkapan layar guru.", "danger");
      }
    } else {
      this.stopDemoMode();
    }
  }

  stopDemoMode() {
    this.isDemoActive = false;
    if (this.demoStream) {
      this.demoStream.getTracks().forEach(t => t.stop());
      this.demoStream = null;
    }
    const actionLabel = document.getElementById("lblDemoActionTitle");
    if (actionLabel) actionLabel.textContent = "Demo Layar Pengajar";
    this.showToast("Demo Layar dihentikan.", "info");
  }

  // === HAPUS PERANGKAT (DELETE DEVICE) ===
  confirmDeleteDevice(agentId, agentName) {
    const name = agentName || (this.agents.get(agentId)?.name || agentId);
    if (confirm(`Yakin ingin menghapus perangkat "${name}" dari sistem dan database?\nPerangkat yang tidak aktif tidak akan muncul lagi di grid.`)) {
      this.deleteDevice(agentId);
    }
  }

  deleteDevice(agentId) {
    const payload = {
      agent_id: agentId,
      channel: this.currentChannel
    };

    // Kirim WebSocket event
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        type: "delete_device",
        agent_id: agentId,
        channel: this.currentChannel
      }));
    }

    // Panggil REST API delete
    fetch("/api/devices/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
    .then(r => r.json())
    .then(() => {
      this.agents.delete(agentId);
      this.selectedAgents.delete(agentId);
      this.updateSelectionUI();
      this.renderGrid();
      this.showToast("Perangkat berhasil dihapus dari daftar.", "success");
    })
    .catch(err => {
      console.error("Gagal hapus perangkat:", err);
      // Tetap remove secara lokal
      this.agents.delete(agentId);
      this.selectedAgents.delete(agentId);
      this.updateSelectionUI();
      this.renderGrid();
    });
  }

  // === AUTOMATION SCRIPT MANAGER ===
  fetchScripts() {
    fetch("/api/scripts")
      .then(r => r.json())
      .then(scripts => {
        this.scripts = Array.isArray(scripts) ? scripts : [];
        this.renderScriptsTable();
        this.renderQuickScripts();
      })
      .catch(e => {
        console.error("Error fetching scripts:", e);
      });
  }

  renderQuickScripts() {
    if (!this.quickScriptList) return;
    this.quickScriptList.innerHTML = "";

    if (this.scripts.length === 0) {
      this.quickScriptList.innerHTML = `<div style="padding: 8px 14px; font-size: 11px; color: var(--text-dim);">Belum ada skrip tersimpan.</div>`;
      return;
    }

    this.scripts.slice(0, 6).forEach(script => {
      const btn = document.createElement("button");
      btn.className = "quick-script-item";
      btn.innerHTML = `
        <span class="q-name" title="${script.name}">${script.name}</span>
        <span class="q-play">▶ Jalankan</span>
      `;
      btn.addEventListener("click", () => {
        this.closeAllDropdowns();
        this.executeScript(script);
      });
      this.quickScriptList.appendChild(btn);
    });
  }

  renderScriptsTable() {
    if (!this.scriptsTableBody) return;
    const query = (this.scriptSearchInput?.value || "").toLowerCase();
    this.scriptsTableBody.innerHTML = "";

    const filtered = this.scripts.filter(s => {
      return (s.name || "").toLowerCase().includes(query) ||
             (s.description || "").toLowerCase().includes(query) ||
             (s.language || "").toLowerCase().includes(query) ||
             (s.type || "").toLowerCase().includes(query);
    });

    if (filtered.length === 0) {
      this.scriptsTableBody.innerHTML = `
        <tr>
          <td colspan="6" style="text-align: center; padding: 24px; color: var(--text-dim);">
            Tidak ada skrip yang cocok dengan pencarian.
          </td>
        </tr>
      `;
      return;
    }

    filtered.forEach(s => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="col-name">
          <a href="javascript:void(0)" class="script-name-link" title="Klik untuk edit / lihat">${s.name}</a>
        </td>
        <td class="col-desc">
          <div class="script-desc-text" title="${s.description || ''}">${s.description || '-'}</div>
        </td>
        <td class="col-platform">
          <span class="badge-platform">${s.platform || 'Windows'}</span>
        </td>
        <td class="col-lang">
          <span class="badge-lang">${s.language || 'PowerShell'}</span>
        </td>
        <td class="col-type">
          <span class="badge-type">${s.type || 'Custom'}</span>
        </td>
        <td class="col-actions">
          <div class="col-actions-cell">
            <button class="btn-table-action apply" title="Terapkan / Jalankan Skrip ke PC Terpilih">
              ▶ Terapkan
            </button>
            <button class="btn-table-action edit" title="Edit Skrip">
              ✏️ Edit
            </button>
            <button class="btn-table-action del" title="Hapus Skrip">
              🗑️ Hapus
            </button>
          </div>
        </td>
      `;

      // Event click nama / edit
      tr.querySelector(".script-name-link").addEventListener("click", () => this.openEditScriptModal(s.id));
      tr.querySelector(".btn-table-action.edit").addEventListener("click", () => this.openEditScriptModal(s.id));

      // Event Terapkan
      tr.querySelector(".btn-table-action.apply").addEventListener("click", () => {
        this.executeScript(s);
      });

      // Event Hapus
      tr.querySelector(".btn-table-action.del").addEventListener("click", () => {
        this.confirmDeleteScript(s.id, s.name);
      });

      this.scriptsTableBody.appendChild(tr);
    });
  }

  openNewScriptModal() {
    document.getElementById("modalEditScriptTitle").textContent = "📝 Buat Skrip Baru";
    document.getElementById("scriptFormId").value = "";
    document.getElementById("scriptFormName").value = "";
    document.getElementById("scriptFormDesc").value = "";
    document.getElementById("scriptFormPlatform").value = "Windows";
    document.getElementById("scriptFormLang").value = "PowerShell";
    document.getElementById("scriptFormType").value = "Custom";
    document.getElementById("scriptFormCode").value = "# Masukkan perintah di sini\nWrite-Output 'Hello from FYJ Remote'";
    document.getElementById("modalEditScript").classList.remove("hidden");
  }

  openEditScriptModal(scriptId) {
    const script = this.scripts.find(s => s.id === scriptId);
    if (!script) return;

    document.getElementById("modalEditScriptTitle").textContent = "✏️ Edit Skrip Otomasi";
    document.getElementById("scriptFormId").value = script.id;
    document.getElementById("scriptFormName").value = script.name || "";
    document.getElementById("scriptFormDesc").value = script.description || "";
    document.getElementById("scriptFormPlatform").value = script.platform || "Windows";
    document.getElementById("scriptFormLang").value = script.language || "PowerShell";
    document.getElementById("scriptFormType").value = script.type || "Custom";
    document.getElementById("scriptFormCode").value = script.code || "";
    document.getElementById("modalEditScript").classList.remove("hidden");
  }

  saveScriptFromModal() {
    const id = document.getElementById("scriptFormId").value;
    const name = document.getElementById("scriptFormName").value.trim();
    const description = document.getElementById("scriptFormDesc").value.trim();
    const platform = document.getElementById("scriptFormPlatform").value;
    const language = document.getElementById("scriptFormLang").value;
    const type = document.getElementById("scriptFormType").value;
    const code = document.getElementById("scriptFormCode").value;

    if (!name) {
      alert("Nama skrip tidak boleh kosong!");
      return;
    }

    const payload = {
      id: id || undefined,
      name: name,
      description: description,
      platform: platform,
      language: language,
      type: type,
      code: code
    };

    fetch("/api/scripts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
    .then(r => r.json())
    .then(data => {
      document.getElementById("modalEditScript").classList.add("hidden");
      this.fetchScripts();
      this.showToast(`Skrip [${name}] berhasil disimpan!`, "success");
    })
    .catch(err => {
      alert("Gagal menyimpan skrip.");
    });
  }

  confirmDeleteScript(scriptId, scriptName) {
    if (confirm(`Yakin ingin menghapus skrip "${scriptName}"?`)) {
      fetch("/api/scripts/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: scriptId })
      })
      .then(r => r.json())
      .then(() => {
        this.fetchScripts();
        this.showToast(`Skrip "${scriptName}" berhasil dihapus.`, "info");
      })
      .catch(() => alert("Gagal menghapus skrip."));
    }
  }

  // === TERAPKAN / JALANKAN SKRIP KE PC KLIEN ===
  executeScript(script) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.showToast("WebSocket relay server belum terhubung!", "danger");
      return;
    }

    const targets = this.getTargetAgentIds();
    if (targets.length === 0) {
      this.showToast("Tidak ada PC aktif untuk menerima skrip.", "warning");
      return;
    }

    let targetDesc = "Semua Komputer di Channel";
    let targetId = "all";

    if (this.selectedAgents.size > 0) {
      targetDesc = `${this.selectedAgents.size} PC Terpilih`;
      targetId = Array.from(this.selectedAgents).join(",");
    }

    if (!confirm(`Terapkan skrip "${script.name}" ke ${targetDesc}?`)) {
      return;
    }

    // Tampilkan modal output terminal
    this.outScriptTitle.textContent = `Skrip: ${script.name}`;
    this.outTargetDesc.textContent = `Target: ${targetDesc}`;
    this.outStatusPill.className = "output-tag status-pill";
    this.outStatusPill.textContent = "Mengirim Instruksi...";
    this.terminalLogs.textContent = `[${new Date().toLocaleTimeString()}] Mengirimkan skrip [${script.name}] ke target...\nBahasa: ${script.language || 'PowerShell'}\nKode:\n${script.code}\n\nMenunggu balasan eksekusi dari klien...\n----------------------------------------\n`;
    this.modalScriptOutput.classList.remove("hidden");

    // Kirim WebSocket execute_script
    if (this.selectedAgents.size > 0) {
      this.selectedAgents.forEach(agId => {
        this.ws.send(JSON.stringify({
          type: "execute_script",
          target_id: agId,
          script: script
        }));
      });
    } else {
      this.ws.send(JSON.stringify({
        type: "execute_script",
        target_id: "all",
        script: script
      }));
    }

    this.showToast(`Mengeksekusi skrip [${script.name}]...`, "info");
  }

  handleScriptResult(data) {
    const ag = this.agents.get(data.agent_id);
    const pcName = ag ? `${ag.name} (${ag.ip || data.agent_id})` : (data.agent_name || data.agent_id);
    const timeStr = new Date().toLocaleTimeString();

    const isSuccess = data.success !== undefined ? data.success : (data.returncode === 0);
    const statusText = isSuccess ? "BERHASIL (Sukses)" : `GAGAL / PERINGATAN`;
    const outputContent = data.output || data.stdout || "(Tidak ada output standar)";

    const block = `\n[${timeStr}] Hasil dari PC: ${pcName}\nStatus: ${statusText}\nOUTPUT:\n${outputContent}\n${data.stderr ? `ERROR:\n${data.stderr}\n` : ""}========================================\n`;

    this.terminalLogs.textContent += block;
    this.terminalLogs.scrollTop = this.terminalLogs.scrollHeight;

    if (isSuccess) {
      this.outStatusPill.className = "output-tag status-pill success";
      this.outStatusPill.textContent = "Selesai (Sukses)";
      this.showToast(`Skrip berhasil di ${pcName}`, "success");
    } else {
      this.outStatusPill.className = "output-tag status-pill failed";
      this.outStatusPill.textContent = "Selesai (Ada Error)";
      this.showToast(`Skrip gagal dieksekusi di ${pcName}`, "danger");
    }
  }

  // === MODAL CONTROLLERS ===
  openMessageModal(targetId, targetName) {
    if (targetId === "selected") {
      const count = this.selectedAgents.size;
      document.getElementById("msgTarget").value = count > 0 ? `${count} PC Terpilih` : "Semua Komputer di Channel";
      document.getElementById("msgTarget").setAttribute("data-target-id", count > 0 ? "selected" : "all");
    } else {
      document.getElementById("msgTarget").value = targetId === "all" ? "Semua Komputer di Channel" : `${targetName} (${targetId})`;
      document.getElementById("msgTarget").setAttribute("data-target-id", targetId);
    }
    document.getElementById("modalMsg").classList.remove("hidden");
  }

  openUrlModal() {
    const count = this.selectedAgents.size;
    document.getElementById("urlTargetDesc").value = count > 0 ? `${count} PC Terpilih` : "Semua Komputer di Channel";
    document.getElementById("modalUrl").classList.remove("hidden");
  }

  openPowerModal(targetId) {
    document.getElementById("powerChannelName").textContent = targetId === "all" ? this.currentChannel : `Target: ${targetId}`;
    document.getElementById("modalPower").setAttribute("data-target-id", targetId);
    document.getElementById("modalPower").classList.remove("hidden");
  }

  openEditDeviceModal(agentId) {
    const ag = this.agents.get(agentId);
    if (!ag) return;
    document.getElementById("editAgentId").value = agentId;
    document.getElementById("editName").value = ag.name || "";
    document.getElementById("editHostname").value = ag.hostname || ag.name || "";
    document.getElementById("editIp").value = ag.ip || "127.0.0.1";
    document.getElementById("editMac").value = ag.mac || "00:00:00:00:00:00";
    document.getElementById("editNotes").value = ag.notes || "";
    document.getElementById("modalEditDevice").classList.remove("hidden");
  }

  openNewDeviceModal() {
    document.getElementById("editAgentId").value = "";
    document.getElementById("editName").value = "PC Baru";
    document.getElementById("editHostname").value = "";
    document.getElementById("editIp").value = "";
    document.getElementById("editMac").value = "";
    document.getElementById("editNotes").value = "";
    document.getElementById("modalEditDevice").classList.remove("hidden");
  }

  fetchServerStatus() {
    fetch("/api/status")
      .then(r => r.json())
      .then(data => {
        if (data.local_ips && data.local_ips.length > 0) {
          const mainIp = data.local_ips.find(ip => ip !== "127.0.0.1") || "127.0.0.1";
          this.lblLanInfo.textContent = `Hubungkan Klien ke: ws://${mainIp}:8081`;
        }
        if (data.channels) {
          this.updateChannelDropdown(Object.keys(data.channels));
        }
      })
      .catch(() => {});
  }

  updateChannelDropdown(channelNames) {
    this.channelSelect.innerHTML = "";
    channelNames.forEach(name => {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      if (name === this.currentChannel) opt.selected = true;
      this.channelSelect.appendChild(opt);
    });
  }

  switchChannel(newChannel) {
    if (newChannel === this.currentChannel) return;
    this.currentChannel = newChannel;
    this.lblActiveChannel.textContent = newChannel;
    this.lblEmptyChannel.textContent = newChannel;
    this.agents.clear();
    this.selectedAgents.clear();
    this.updateSelectionUI();
    this.renderGrid();
    this.connectWebSocket();
  }

  // === TOAST NOTIFICATION HELPER ===
  showToast(text, type = "info") {
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    let icon = "ℹ️";
    if (type === "success") icon = "✅";
    if (type === "warning") icon = "⚠️";
    if (type === "danger") icon = "❌";

    toast.innerHTML = `<span>${icon}</span> <span>${text}</span>`;
    this.toastContainer.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateX(100%)";
      toast.style.transition = "all 0.3s";
      setTimeout(() => toast.remove(), 300);
    }, 3500);
  }

  // === DROPDOWN HELPERS ===
  toggleDropdown(wrapperId) {
    const wrapper = document.getElementById(wrapperId);
    if (!wrapper) return;
    const wasOpen = wrapper.classList.contains("open");
    this.closeAllDropdowns();
    if (!wasOpen) {
      wrapper.classList.add("open");
    }
  }

  closeAllDropdowns() {
    document.querySelectorAll(".dropdown-wrapper").forEach(w => w.classList.remove("open"));
  }

  // === EVENT BINDING ===
  bindEvents() {
    // Channel Change
    this.channelSelect.addEventListener("change", (e) => {
      this.switchChannel(e.target.value);
    });

    // Sizing Grid Buttons
    document.querySelectorAll(".btn-size").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".btn-size").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        const size = btn.getAttribute("data-size");
        this.clientGrid.className = `client-grid grid-${size}`;
      });
    });

    // Search Input
    this.searchInput.addEventListener("input", () => this.renderGrid());

    // Selection buttons
    if (this.btnSelectAll) {
      this.btnSelectAll.addEventListener("click", () => this.selectAllAgents());
    }
    if (this.btnDeselectAll) {
      this.btnDeselectAll.addEventListener("click", () => this.deselectAllAgents());
    }

    // Dropdown Triggers
    document.getElementById("btnDropScreen")?.addEventListener("click", (e) => {
      e.stopPropagation();
      this.toggleDropdown("dropScreen");
    });
    document.getElementById("btnDropComm")?.addEventListener("click", (e) => {
      e.stopPropagation();
      this.toggleDropdown("dropComm");
    });
    document.getElementById("btnDropScript")?.addEventListener("click", (e) => {
      e.stopPropagation();
      this.toggleDropdown("dropScript");
    });
    document.getElementById("btnDropPower")?.addEventListener("click", (e) => {
      e.stopPropagation();
      this.toggleDropdown("dropPower");
    });

    // Close dropdowns when clicking outside
    document.addEventListener("click", () => {
      this.closeAllDropdowns();
    });

    // Dropdown item actions: Kontrol Layar
    document.getElementById("itemLockAction")?.addEventListener("click", () => {
      this.closeAllDropdowns();
      this.executeLockAction();
    });
    document.getElementById("itemUnlockAction")?.addEventListener("click", () => {
      this.closeAllDropdowns();
      this.executeUnlockAction();
    });
    document.getElementById("itemDemoAction")?.addEventListener("click", () => {
      this.closeAllDropdowns();
      this.toggleDemoMode();
    });

    // Dropdown item actions: Pesan & Web
    document.getElementById("itemMsgAction")?.addEventListener("click", () => {
      this.closeAllDropdowns();
      this.openMessageModal("selected", "Komputer");
    });
    document.getElementById("itemUrlAction")?.addEventListener("click", () => {
      this.closeAllDropdowns();
      this.openUrlModal();
    });

    // Dropdown item actions: Skrip
    document.getElementById("itemManageScripts")?.addEventListener("click", () => {
      this.closeAllDropdowns();
      document.getElementById("modalScripts").classList.remove("hidden");
      this.renderScriptsTable();
    });
    document.getElementById("itemAddNewScript")?.addEventListener("click", () => {
      this.closeAllDropdowns();
      this.openNewScriptModal();
    });

    // Dropdown item actions: Power
    document.querySelectorAll("#dropPower .dropdown-item[data-power]").forEach(item => {
      item.addEventListener("click", () => {
        this.closeAllDropdowns();
        const action = item.getAttribute("data-power");
        this.executePowerAction(action);
      });
    });

    // Script Manager Actions
    document.getElementById("btnOpenNewScriptModal")?.addEventListener("click", () => {
      this.openNewScriptModal();
    });
    this.scriptSearchInput?.addEventListener("input", () => {
      this.renderScriptsTable();
    });
    document.getElementById("btnSaveScriptConfirm")?.addEventListener("click", () => {
      this.saveScriptFromModal();
    });

    // Terminal Copy Button
    if (this.btnCopyTerminal) {
      this.btnCopyTerminal.addEventListener("click", () => {
        navigator.clipboard.writeText(this.terminalLogs.textContent);
        this.showToast("Output terminal disalin ke clipboard!", "info");
      });
    }

    // Modal Close Buttons
    document.querySelectorAll("[data-close]").forEach(el => {
      el.addEventListener("click", () => {
        const modalId = el.getAttribute("data-close");
        document.getElementById(modalId)?.classList.add("hidden");
      });
    });

    // Kirim Pesan Confirm
    document.getElementById("btnSendMsgConfirm").addEventListener("click", () => {
      const targetMode = document.getElementById("msgTarget").getAttribute("data-target-id");
      const title = document.getElementById("msgTitle").value.trim();
      const body = document.getElementById("msgBody").value.trim();
      if (!body) {
        alert("Pesan tidak boleh kosong!");
        return;
      }

      if (targetMode === "selected" && this.selectedAgents.size > 0) {
        this.selectedAgents.forEach(id => {
          this.sendCommand(id, "message", { title: title, message: body });
        });
        this.showToast(`Pesan berhasil dikirim ke ${this.selectedAgents.size} PC terpilih!`, "success");
      } else {
        this.sendCommand("all", "message", { title: title, message: body });
        this.showToast("Pesan pop-up berhasil dikirim ke semua PC!", "success");
      }
      document.getElementById("modalMsg").classList.add("hidden");
    });

    // Buka URL Confirm
    document.getElementById("btnPushUrlConfirm").addEventListener("click", () => {
      const url = document.getElementById("urlInput").value.trim();
      if (!url) {
        alert("URL tidak boleh kosong!");
        return;
      }

      if (this.selectedAgents.size > 0) {
        this.selectedAgents.forEach(id => {
          this.sendCommand(id, "open_url", { url: url });
        });
        this.showToast(`URL dibuka di ${this.selectedAgents.size} PC terpilih: ${url}`, "success");
      } else {
        this.sendCommand("all", "open_url", { url: url });
        this.showToast(`URL disebarkan ke semua PC: ${url}`, "success");
      }
      document.getElementById("modalUrl").classList.add("hidden");
    });

    // Tombol Hapus di dalam Modal Edit Device
    document.getElementById("btnDeleteDeviceModal")?.addEventListener("click", () => {
      const agentId = document.getElementById("editAgentId").value;
      if (!agentId) {
        document.getElementById("modalEditDevice").classList.add("hidden");
        return;
      }
      const agName = document.getElementById("editName").value;
      if (confirm(`Yakin ingin menghapus perangkat "${agName}" dari sistem?`)) {
        document.getElementById("modalEditDevice").classList.add("hidden");
        this.deleteDevice(agentId);
      }
    });

    // Add Channel Modal
    document.getElementById("btnAddChannel").addEventListener("click", () => {
      document.getElementById("modalAddChannel").classList.remove("hidden");
    });

    // Tambah Perangkat Baru Manual
    const btnAddDev = document.getElementById("btnAddNewDevice");
    if (btnAddDev) {
      btnAddDev.addEventListener("click", () => {
        this.openNewDeviceModal();
      });
    }

    // Simpan Perubahan Edit Device (Host Name, IP, MAC Address, Notes)
    document.getElementById("btnSaveDeviceEdit").addEventListener("click", () => {
      let agentId = document.getElementById("editAgentId").value;
      const name = document.getElementById("editName").value.trim();
      const hostname = document.getElementById("editHostname").value.trim();
      const ip = document.getElementById("editIp").value.trim();
      const mac = document.getElementById("editMac").value.trim().toUpperCase();
      const notes = document.getElementById("editNotes").value.trim();

      if (!name) {
        alert("Nama tampilan perangkat tidak boleh kosong!");
        return;
      }

      if (!agentId) {
        agentId = `dev_${Date.now() % 1000000}`;
      }

      const payload = {
        type: "update_device",
        agent_id: agentId,
        name: name,
        hostname: hostname,
        ip: ip,
        mac: mac,
        notes: notes,
        channel: this.currentChannel
      };

      // Kirim via WebSocket ke server
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify(payload));
      }

      // Simpan juga via REST API
      fetch("/api/devices/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }).catch(() => {});

      // Update / Add in-memory dan UI
      if (this.agents.has(agentId)) {
        const ag = this.agents.get(agentId);
        ag.name = name;
        ag.hostname = hostname;
        ag.ip = ip;
        ag.mac = mac;
        ag.notes = notes;
      } else {
        this.agents.set(agentId, {
          id: agentId,
          name: name,
          hostname: hostname,
          ip: ip || "127.0.0.1",
          mac: mac || "00:00:00:00:00:00",
          notes: notes,
          status: "offline",
          channel: this.currentChannel,
          cpu: 0,
          ram: 0,
          is_locked: false
        });
      }

      document.getElementById("modalEditDevice").classList.add("hidden");
      this.renderGrid();
      this.showToast(`Data perangkat [${name}] berhasil disimpan!`, "success");
    });

    document.getElementById("btnSaveNewChannel").addEventListener("click", () => {
      const newName = document.getElementById("newChannelInput").value.trim().toUpperCase();
      if (!newName) {
        alert("Nama channel tidak boleh kosong!");
        return;
      }
      fetch("/api/channels", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel_name: newName })
      })
      .then(r => r.json())
      .then(() => {
        document.getElementById("modalAddChannel").classList.add("hidden");
        document.getElementById("newChannelInput").value = "";
        this.fetchServerStatus();
        this.switchChannel(newName);
        this.showToast(`Channel baru [${newName}] berhasil dibuat!`, "success");
      })
      .catch(() => {
        alert("Gagal menambahkan channel ke server.");
      });
    });
  }

  executePowerAction(action) {
    const targets = this.getTargetAgentIds();
    if (targets.length === 0) return;

    const count = this.selectedAgents.size;
    const targetDesc = count > 0 ? `${count} PC Terpilih` : `SEMUA komputer di channel ${this.currentChannel}`;

    if (confirm(`Peringatan: Yakin ingin mengeksekusi '${action}' pada ${targetDesc}?`)) {
      if (count > 0) {
        this.selectedAgents.forEach(id => {
          this.sendCommand(id, "power", { action: action });
        });
      } else {
        this.sendCommand("all", "power", { action: action });
      }
      this.showToast(`Instruksi daya '${action}' dikirimkan ke ${targetDesc}!`, "warning");
    }
  }
}

// Inisialisasi Aplikasi Saat Halaman Selesai Dimuat
window.addEventListener("DOMContentLoaded", () => {
  window.app = new FYJMasterApp();
});
