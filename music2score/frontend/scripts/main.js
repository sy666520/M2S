/* ============================================================
   music2score 前端逻辑
   - 上传 → 轮询任务 → 渲染谱面（五线谱 / 简谱 / 六线谱）
   - 试听：原曲用 <audio>，转出的谱用 WebAudio 合成，方便核对识别是否准确
   ============================================================ */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  const midiName = (m) => `${NOTE_NAMES[m % 12]}${Math.floor(m / 12) - 1}`;

  const state = {
    mode: "file",          // file = 本地上传，url = 链接导入
    file: null,
    jobId: null,
    meta: null,
    sourceMeta: null,
    view: "staff",
    pages: { staff: null, jianpu: null, tab: null },
    audioEl: null,
    audioCtx: null,
    notesCache: null,
    license: null,
  };

  /* ---------------- 初始化 ---------------- */
  async function init() {
    // 入场序列：错峰点亮
    document.querySelectorAll(".reveal").forEach((el, i) => {
      requestAnimationFrame(() => setTimeout(() => el.classList.add("in"), 60 + i * 70));
    });

    bindSourceSwitch();
    bindUpload();
    bindTabs();
    bindZoom();
    bindPlayback();
    bindExport();
    bindEditorGlobal();
    bindBilling();
    await loadMeta();
    await refreshLicense();
    loadSponsor();
  }

  async function loadMeta() {
    try {
      const res = await fetch("/api/meta");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.desktop) {
        // 桌面版没有浏览器地址栏，也没必要引导装到手机
        document.body.classList.add("is-desktop");
        const inst = document.querySelector(".chip-link");
        if (inst) inst.hidden = true;
      }
      // 拍号 / 调性选项由后端下发，前后端保持一致
      if (Array.isArray(data.meters) && data.meters.length) {
        const ms = $("#meterSelect");
        ms.innerHTML = data.meters
          .map((m) => `<option value="${m.id}">${m.label}</option>`).join("");
      }
      if (Array.isArray(data.keys) && data.keys.length) {
        const ks = $("#keySelect");
        const groups = {};
        ks.innerHTML = "";
        for (const k of data.keys) {
          if (!k.group) {
            ks.insertAdjacentHTML("beforeend", `<option value="${k.id}">${k.label}</option>`);
            continue;
          }
          groups[k.group] = groups[k.group] || [];
          groups[k.group].push(`<option value="${k.id}">${k.label}</option>`);
        }
        for (const [g, opts] of Object.entries(groups)) {
          ks.insertAdjacentHTML("beforeend",
            `<optgroup label="${g}">${opts.join("")}</optgroup>`);
        }
      }
      const sel = $("#engineSelect");
      sel.innerHTML = "";
      const byName = {};
      for (const t of data.transcribers) {
        byName[t.name] = t;
        const opt = document.createElement("option");
        opt.value = t.name;
        opt.textContent = t.label
          + (t.polyphonic ? "（多声部）" : "")
          + (t.slow ? "（较慢）" : "");
        sel.appendChild(opt);
      }
      if (!data.transcribers.length) {
        const opt = document.createElement("option");
        opt.textContent = "无可用的识别引擎";
        sel.appendChild(opt);
        sel.disabled = true;
      } else {
        // 后端标了 preferred 的就是默认引擎
        const pref = data.transcribers.find((t) => t.preferred) || data.transcribers[0];
        sel.value = pref.name;
        $("#engineChip").textContent = `引擎 ${pref.label}`;
      }
      const hint = $("#engineHint");
      const showHint = () => {
        const t = byName[sel.value];
        if (t && t.hint) {
          hint.textContent = t.hint;
          hint.hidden = false;
        } else {
          hint.hidden = true;
        }
      };
      sel.addEventListener("change", () => {
        $("#engineChip").textContent = `引擎 ${sel.selectedOptions[0].textContent}`;
        showHint();
      });
      showHint();

      // 链接导入：站点提示 + 浏览器组件是否就绪（抖音需要）
      const ui = data.url_import;
      if (ui) {
        $("#platformChips").innerHTML = (ui.platforms || [])
          .map((p) => `<span>${escapeHtml(p)}</span>`).join("");
        if (!ui.browser) {
          $("#urlHint").textContent =
            "抖音链接需要浏览器组件（pip install playwright && playwright install chromium）；B站、YouTube 等可直接导入。";
        }
      }
    } catch (e) {
      $("#engineChip").textContent = "后端未连接";
      showError("无法连接后端服务，请确认服务已启动（backend/main.py）。");
    }
  }

  /* ---------------- 来源切换 ---------------- */
  function bindSourceSwitch() {
    document.querySelectorAll(".source-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const mode = btn.dataset.source;
        if (mode === state.mode) return;
        state.mode = mode;
        document.querySelectorAll(".source-btn").forEach((b) => {
          const on = b === btn;
          b.classList.toggle("is-on", on);
          b.setAttribute("aria-selected", on ? "true" : "false");
        });
        $("#sourceFile").hidden = mode !== "file";
        $("#sourceUrl").hidden = mode !== "url";
        $("#runBtn").textContent = mode === "file" ? "开始转谱" : "提取并转谱";
        updateRunState();
        if (mode === "url") setTimeout(() => $("#urlInput").focus(), 60);
      });
    });

    const urlInput = $("#urlInput");
    urlInput.addEventListener("input", updateRunState);
    urlInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !$("#runBtn").disabled) { e.preventDefault(); run(); }
    });
  }

  function updateRunState() {
    const ready = state.mode === "url"
      ? !!$("#urlInput").value.trim()
      : !!state.file;
    $("#runBtn").disabled = !ready;
  }

  /* ---------------- 上传 ---------------- */
  function bindUpload() {
    const dz = $("#dropzone");
    const input = $("#fileInput");

    dz.addEventListener("click", () => input.click());
    dz.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); }
    });

    ["dragenter", "dragover"].forEach((ev) =>
      dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("is-over"); })
    );
    ["dragleave", "drop"].forEach((ev) =>
      dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("is-over"); })
    );
    dz.addEventListener("drop", (e) => {
      const f = e.dataTransfer?.files?.[0];
      if (f) setFile(f);
    });

    input.addEventListener("change", () => {
      if (input.files?.[0]) setFile(input.files[0]);
    });

    $("#clearFile").addEventListener("click", () => {
      setFile(null);
      input.value = "";
    });

    $("#runBtn").addEventListener("click", run);
  }

  function setFile(f) {
    state.file = f;
    $("#fileName").textContent = f ? f.name : "尚未选择文件";
    $("#clearFile").hidden = !f;
    if (!f) {
      $("#titleInput").value = "";
    } else {
      $("#titleInput").value = f.name.replace(/\.[^.]+$/, "");
    }
    updateRunState();
  }

  /* ---------------- 转谱 ---------------- */
  async function run() {
    const isUrl = state.mode === "url";
    const url = isUrl ? $("#urlInput").value.trim() : "";
    if (isUrl ? !url : !state.file) return;

    // 额度不足就不发请求，直接引导；后端还有 402 兜底防止前端状态过期
    if (state.license && state.license.billing_enabled !== false
        && !state.license.unlimited && (state.license.left_today ?? 0) <= 0) {
      showGate();
      return;
    }

    stopAll();

    state.jobId = null;
    state.meta = null;
    state.sourceMeta = null;
    state.pages = { staff: null, jianpu: null, tab: null };
    state.notesCache = null;
    ed = null;                 // 新任务：丢弃上一份校对草稿

    $("#runBtn").disabled = true;
    $("#progressWrap").hidden = false;
    setProgress(0.02, isUrl ? "解析链接…" : "上传中…");
    setPaperBusy(isUrl ? "正在提取音频…" : "正在识别…");
    clearResult();
    setActionsEnabled(false);

    const fd = new FormData();
    if (isUrl) fd.append("url", url); else fd.append("file", state.file);
    fd.append("transcriber", $("#engineSelect").value || "pyin");
    fd.append("meter", $("#meterSelect").value || "auto");
    fd.append("key", $("#keySelect").value || "auto");
    fd.append("title", $("#titleInput").value.trim());

    try {
      const endpoint = isUrl ? "/api/transcribe-url" : "/api/transcribe";
      const res = await fetch(endpoint, { method: "POST", body: fd });
      if (res.status === 402) {
        const body = await res.json().catch(() => ({}));
        if (body.license) applyLicense(body.license);
        $("#progressWrap").hidden = true;
        setPaperBusy(null);
        updateRunState();
        showGate();
        return;
      }
      if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
      const data = await res.json();
      state.jobId = data.job_id;
      await pollJob(data.job_id);
    } catch (e) {
      onError(e.message || String(e));
    }
  }

  async function pollJob(id) {
    const deadline = Date.now() + 12 * 60 * 1000;
    while (Date.now() < deadline) {
      const res = await fetch(`/api/jobs/${id}`);
      if (!res.ok) throw new Error(`查询任务失败 HTTP ${res.status}`);
      const job = await res.json();
      setProgress(job.progress || 0, job.stage || "");
      if (job.status === "done") { await onDone(job); return; }
      if (job.status === "error") { onError(job.error || "转谱失败"); return; }
      await sleep(380);
    }
    throw new Error("任务超时（12 分钟），请换一段更短的音频重试");
  }

  async function onDone(job) {
    state.meta = job.meta;
    state.sourceMeta = job.source_meta || null;
    setProgress(1, "完成");
    renderMeta(job.meta, job.source_meta);
    renderBadge(job.meta);
    setActionsEnabled(true);
    // 链接导入时标题由视频标题补全，回填给用户看
    if (!$("#titleInput").value && job.title) $("#titleInput").value = job.title;
    await loadView(state.view);
    setTimeout(() => { $("#progressWrap").hidden = true; }, 900);
    updateRunState();
    refreshLicense();                       // 刚用掉一次，刷新徽标
  }

  function onError(msg) {
    setPaperBusy(null);
    $("#resultBody").innerHTML =
      `<div class="alert"><strong>出错了</strong><br>${escapeHtml(msg)}</div>`;
    $("#progressWrap").hidden = true;
    updateRunState();
    setActionsEnabled(false);
  }

  function setProgress(v, stage) {
    $("#progressBar").style.width = `${Math.round((v || 0) * 100)}%`;
    $("#progressStage").textContent = stage || "";
  }

  /* ---------------- 谱面渲染 ---------------- */
  async function loadView(view) {
    if (!state.jobId) return;
    if (view === "edit") { await openEditor(); return; }
    $("#paper").classList.remove("is-editing");
    if (state.pages[view]) { renderPages(state.pages[view]); return; }

    setPaperBusy("渲染谱面…");
    try {
      const res = await fetch(`/api/jobs/${state.jobId}/score/${view}`);
      if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
      const data = await res.json();
      state.pages[view] = data.pages;
      if (data.meta) renderBadge(data.meta);
      renderPages(data.pages);
    } catch (e) {
      $("#paper").innerHTML =
        `<div class="paper-empty"><div><p class="txt">谱面渲染失败</p>
         <p class="sub">${escapeHtml(e.message || String(e))}</p></div></div>`;
    }
  }

  function renderPages(pages) {
    const paper = $("#paper");
    if (!pages || !pages.length) {
      paper.innerHTML = emptyPaper("这一段没有识别出足够的音符", "换一段旋律更清晰的音频试试。");
      return;
    }
    paper.innerHTML = pages.map((p) => `<div class="score-page">${p}</div>`).join("");
  }

  function setPaperBusy(text) {
    if (!text) return;
    $("#paper").innerHTML =
      `<div class="paper-busy"><div class="spinner"></div>
       <p style="font-size: var(--fs-200); color: var(--color-ink-soft)">${escapeHtml(text)}</p></div>`;
  }

  function emptyPaper(title, sub) {
    return `<div class="paper-empty"><div>
      <div class="glyph" aria-hidden="true">𝄞</div>
      <p class="txt">${escapeHtml(title)}</p>
      <p class="sub">${escapeHtml(sub)}</p></div></div>`;
  }

  /* ---------------- 结果信息 ---------------- */
  function clearResult() {
    $("#resultBody").innerHTML =
      `<p class="empty-note">正在识别…</p>`;
  }

  function renderMeta(m, source) {
    if (!m) return;
    const rows = [
      ["调性", m.key, ""],
      ["拍号", `${m.meter[0]}/${m.meter[1]}`, ""],
      ["速度", `<span class="num">${Math.round(m.tempo)}</span>`, "BPM"],
      ["音符数", `<span class="num">${m.note_count}</span>`, "个"],
      ["音域", m.range_low != null ? `${midiName(m.range_low)}–${midiName(m.range_high)}` : "—", ""],
      ["时长", `<span class="num">${m.source_duration.toFixed(1)}</span>`, "秒"],
    ];
    if (source && source.platform) {
      rows.unshift(["来源", `${escapeHtml(source.platform)} · 已提取音轨`, ""]);
    }
    $("#resultBody").innerHTML =
      `<div class="meta-grid">${rows.map(([k, v, u]) =>
        `<div class="meta-item"><div class="k">${k}</div>
         <div class="v">${v}${u ? ` <small>${u}</small>` : ""}</div></div>`
      ).join("")}</div>`;
  }

  function renderBadge(m) {
    if (!m) return;
    const old = document.querySelector(".score-badge");
    if (old) old.remove();
    const badge = document.createElement("div");
    badge.className = "score-badge";
    badge.innerHTML = `
      <div class="cell accent">BPM<b>${Math.round(m.tempo)}</b></div>
      <div class="cell">调性<b>${escapeHtml(m.key)}</b></div>
      <div class="cell">拍号<b>${m.meter[0]}/${m.meter[1]}</b></div>`;
    $(".stage").appendChild(badge);
  }

  function setActionsEnabled(on) {
    ["#playSource", "#playScore", "#stopPlay", "#dlMidi", "#dlXml"].forEach((s) => {
      $(s).disabled = !on;
    });
  }

  /* ---------------- 视图切换与缩放 ---------------- */
  function bindTabs() {
    document.querySelectorAll(".tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        const view = tab.dataset.view;
        if (view === state.view) return;
        // 离开校对页且未保存时先确认，避免误丢修改
        if (state.view === "edit" && ed && ed.dirty
            && !window.confirm("校对内容还没保存，确定离开？")) {
          return;
        }
        document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-selected", "false"));
        tab.setAttribute("aria-selected", "true");
        state.view = view;
        if (state.jobId) loadView(state.view);
      });
    });
  }

  function bindZoom() {
    const r = $("#zoomRange");
    r.addEventListener("input", () => {
      document.documentElement.style.setProperty("--zoom", r.value);
      $("#zoomVal").textContent = `${Number(r.value).toFixed(1)}×`;
    });
  }

  /* ============================================================
     人工校对编辑器
     - 钢琴卷帘：横向时间（拍），纵向音高（半音）
     - 拖音符主体改音高/起始位置，拖右端改时值，点空白处添加
     - 保存后后端按新音符重渲三种谱面，导出同步生效
     ============================================================ */
  const PPB = 62;        // 每拍像素宽
  const ROWH = 18;       // 每个半音行高
  const KEYW = 52;       // 左侧键盘列宽
  const BLACK_PC = new Set([1, 3, 6, 8, 10]);

  let ed = null;         // 编辑中的谱面数据
  let edCanvas = null;   // 当前画布容器
  let edDrag = null;     // 拖动状态

  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const round4 = (v) => Math.round(v * 1e4) / 1e4;

  async function openEditor() {
    if (!state.jobId) return;
    if (!ed) {
      setPaperBusy("载入音符…");
      try {
        const res = await fetch(`/api/jobs/${state.jobId}/notes`);
        if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
        const d = await res.json();
        ed = {
          notes: d.notes.map((n) => ({ beat: n.beat, dur: n.dur, midi: n.midi })),
          tempo: d.tempo,
          meter: d.meter.slice(),
          key: d.key,
          grid: (state.meta && state.meta.grid) || 0.25,
          sel: null,
          dirty: false,
          hist: [],
          ptr: -1,
        };
        pushHistory(false);
      } catch (e) {
        $("#paper").innerHTML =
          `<div class="paper-empty"><div><p class="txt">无法载入音符</p>
           <p class="sub">${escapeHtml(e.message || String(e))}</p></div></div>`;
        return;
      }
    }
    renderEditor();
  }

  function snapshot() {
    return {
      notes: ed.notes.map((n) => ({ ...n })),
      tempo: ed.tempo,
      meter: ed.meter.slice(),
      key: ed.key,
    };
  }

  function pushHistory(mark = true) {
    ed.hist = ed.hist.slice(0, ed.ptr + 1);
    ed.hist.push(snapshot());
    if (ed.hist.length > 150) ed.hist.shift();
    ed.ptr = ed.hist.length - 1;
    if (mark) markDirty();
    updateHistoryButtons();
  }

  function applySnapshot(s) {
    ed.notes = s.notes.map((n) => ({ ...n }));
    ed.tempo = s.tempo;
    ed.meter = s.meter.slice();
    ed.key = s.key;
    ed.sel = null;
    renderEditor();
  }

  function undoEdit() {
    if (!ed || ed.ptr <= 0) return;
    ed.ptr -= 1;
    applySnapshot(ed.hist[ed.ptr]);
    markDirty();
  }

  function redoEdit() {
    if (!ed || ed.ptr >= ed.hist.length - 1) return;
    ed.ptr += 1;
    applySnapshot(ed.hist[ed.ptr]);
    markDirty();
  }

  function updateHistoryButtons() {
    const u = $("#edUndo"), r = $("#edRedo");
    if (u) u.disabled = !ed || ed.ptr <= 0;
    if (r) r.disabled = !ed || ed.ptr >= ed.hist.length - 1;
  }

  function markDirty() {
    if (!ed) return;
    ed.dirty = true;
    const b = $("#edSave");
    if (b) b.classList.add("is-dirty");
  }

  function sortNotes() {
    ed.notes.sort((a, b) => (a.beat - b.beat) || (a.midi - b.midi));
  }

  function snapBeat(v) {
    const g = ed.grid || 0.25;
    return round4(Math.max(0, Math.round(v / g) * g));
  }

  function meterOptions() {
    const list = ["4/4", "3/4", "2/4", "6/8", "3/8", "12/8"];
    const cur = `${ed.meter[0]}/${ed.meter[1]}`;
    return list.map((m) => `<option value="${m}"${m === cur ? " selected" : ""}>${m}</option>`).join("");
  }

  function keyOptions() {
    let out = "";
    for (const mode of ["major", "minor"]) {
      const label = mode === "major" ? "大调" : "小调";
      out += `<optgroup label="${label}">`;
      for (const n of NOTE_NAMES) {
        const v = `${n} ${mode}`;
        out += `<option value="${v}"${v === ed.key ? " selected" : ""}>${n} ${label}</option>`;
      }
      out += "</optgroup>";
    }
    return out;
  }

  function keysHtml(rows) {
    let out = "";
    for (let r = 0; r < rows; r++) {
      const midi = ed.hi - r;
      const pc = ((midi % 12) + 12) % 12;
      const cls = "ed-key" + (BLACK_PC.has(pc) ? " is-black" : "") + (pc === 0 ? " is-c" : "");
      out += `<div class="${cls}" style="height:${ROWH}px">${pc === 0 ? midiName(midi) : ""}</div>`;
    }
    return out;
  }

  function notesHtml() {
    return ed.notes.map((n, i) => {
      const left = KEYW + n.beat * PPB;
      const top = (ed.hi - n.midi) * ROWH;
      return `<div class="ed-note${n === ed.sel ? " is-sel" : ""}" data-i="${i}"
        style="left:${left}px;top:${top + 1}px;width:${Math.max(8, n.dur * PPB - 1)}px;height:${ROWH - 2}px"
        ><span>${midiName(n.midi)}</span><i class="ed-handle"></i></div>`;
    }).join("");
  }

  function renderEditor() {
    if (!ed) return;
    const paper = $("#paper");
    paper.classList.add("is-editing");

    const bpb = ed.meter[0];
    const endBeat = ed.notes.reduce((m, n) => Math.max(m, n.beat + n.dur), 0);
    const bars = Math.max(2, Math.ceil(endBeat / bpb));
    const totalBeats = bars * bpb;
    const width = KEYW + totalBeats * PPB + 24;

    // 音高范围：上下各留 3 个半音，至少铺满 2 个八度
    let lo = 127, hi = 0;
    for (const n of ed.notes) { lo = Math.min(lo, n.midi); hi = Math.max(hi, n.midi); }
    if (!ed.notes.length) { lo = 55; hi = 79; }
    lo -= 3; hi += 3;
    if (hi - lo < 24) {
      const mid = (hi + lo) / 2;
      lo = Math.round(mid - 12); hi = Math.round(mid + 12);
    }
    lo = clamp(lo, 0, 116); hi = clamp(hi, lo + 11, 127);
    ed.lo = lo; ed.hi = hi;
    const rows = hi - lo + 1;
    const height = rows * ROWH;

    paper.innerHTML = `
      <div class="editor">
        <div class="ed-toolbar">
          <span class="ed-selinfo" id="edSel">未选中音符</span>
          <button type="button" class="ed-btn" id="edUndo" title="Ctrl+Z">撤销</button>
          <button type="button" class="ed-btn" id="edRedo" title="Ctrl+Shift+Z">重做</button>
          <span class="ed-sep"></span>
          <button type="button" class="ed-btn" id="edSplit" title="把当前音符一分为二">拆分</button>
          <button type="button" class="ed-btn" id="edMerge" title="与后一个同音高音符连写">连写</button>
          <button type="button" class="ed-btn" id="edDel" title="Delete">删除</button>
          <span class="ed-sep"></span>
          <label class="ed-field">BPM
            <input type="number" id="edTempo" min="20" max="300" step="1" value="${Math.round(ed.tempo)}">
          </label>
          <label class="ed-field">拍号<select id="edMeter">${meterOptions()}</select></label>
          <label class="ed-field">调性<select id="edKey">${keyOptions()}</select></label>
          <span class="ed-sep"></span>
          <button type="button" class="ed-btn" id="edPlay">试听</button>
          <button type="button" class="ed-btn is-primary" id="edSave">保存并刷新谱面</button>
        </div>
        <p class="ed-hint">拖动音符改音高 / 位置 · 拖右端调时值 · 点空白处添加 · ↑↓ 半音（Shift 八度）· Del 删除</p>
        <div class="ed-scroll">
          <div class="ed-canvas" id="edCanvas" style="width:${width}px;height:${height}px">
            <canvas id="edGrid"></canvas>
            <div class="ed-keys" style="height:${height}px">${keysHtml(rows)}</div>
            ${notesHtml()}
          </div>
        </div>
      </div>`;

    edCanvas = $("#edCanvas");
    drawGrid(totalBeats);
    bindEditorControls();
    updateHistoryButtons();
    updateSelInfo();
    if (ed.dirty) $("#edSave").classList.add("is-dirty");
  }

  function drawGrid(totalBeats) {
    const cv = $("#edGrid");
    const w = edCanvas.clientWidth, h = edCanvas.clientHeight;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    cv.width = Math.round(w * dpr);
    cv.height = Math.round(h * dpr);
    cv.style.width = `${w}px`;
    cv.style.height = `${h}px`;
    const c = cv.getContext("2d");
    c.scale(dpr, dpr);
    c.clearRect(0, 0, w, h);

    const rows = ed.hi - ed.lo + 1;
    for (let r = 0; r < rows; r++) {
      const midi = ed.hi - r;
      const pc = ((midi % 12) + 12) % 12;
      if (BLACK_PC.has(pc)) {
        c.fillStyle = "rgba(255,255,255,0.028)";
        c.fillRect(KEYW, r * ROWH, w - KEYW, ROWH);
      }
      if (pc === 0) {
        c.fillStyle = "rgba(242,236,225,0.09)";
        c.fillRect(KEYW, (r + 1) * ROWH - 1, w - KEYW, 1);
      }
    }

    const g = ed.grid || 0.25;
    const bpb = ed.meter[0];
    const steps = Math.round(totalBeats / g);
    for (let i = 0; i <= steps; i++) {
      const b = i * g;
      const x = Math.round(KEYW + b * PPB) + 0.5;
      const isBar = Math.abs(b % bpb) < 1e-6;
      const isBeat = Math.abs(b % 1) < 1e-6;
      c.strokeStyle = isBar ? "rgba(242,236,225,0.24)"
        : isBeat ? "rgba(242,236,225,0.10)"
          : "rgba(242,236,225,0.045)";
      c.beginPath();
      c.moveTo(x, 0);
      c.lineTo(x, h);
      c.stroke();
    }
  }

  function bindEditorControls() {
    $("#edUndo").addEventListener("click", undoEdit);
    $("#edRedo").addEventListener("click", redoEdit);
    $("#edSplit").addEventListener("click", splitSelected);
    $("#edMerge").addEventListener("click", mergeSelected);
    $("#edDel").addEventListener("click", deleteSelected);
    $("#edPlay").addEventListener("click", () => {
      if (!ed) return;
      stopAll();
      playScore({ tempo: ed.tempo, notes: ed.notes });
    });
    $("#edSave").addEventListener("click", saveEdits);

    $("#edTempo").addEventListener("change", (e) => {
      const v = Number(e.target.value);
      if (!(v >= 20 && v <= 300)) { e.target.value = Math.round(ed.tempo); return; }
      ed.tempo = v;
      pushHistory();
    });
    $("#edMeter").addEventListener("change", (e) => {
      const [a, b] = e.target.value.split("/").map(Number);
      ed.meter = [a, b];
      pushHistory();
      renderEditor();
    });
    $("#edKey").addEventListener("change", (e) => {
      ed.key = e.target.value;
      pushHistory();
    });

    edCanvas.addEventListener("mousedown", onCanvasDown);
  }

  function bindEditorGlobal() {
    window.addEventListener("mousemove", onEditorMove);
    window.addEventListener("mouseup", onEditorUp);
    document.addEventListener("keydown", onEditorKey);
  }

  function onCanvasDown(e) {
    if (!ed || !edCanvas || e.button !== 0) return;
    const rect = edCanvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const el = e.target.closest(".ed-note");
    if (el) {
      const n = ed.notes[Number(el.dataset.i)];
      if (!n) return;
      ed.sel = n;
      selectVisual(n);
      edDrag = {
        mode: e.target.classList.contains("ed-handle") ? "resize" : "move",
        note: n, x0: x, y0: y, beat0: n.beat, dur0: n.dur, midi0: n.midi, moved: false,
      };
      e.preventDefault();
    } else {
      edDrag = { mode: "add", x0: x, y0: y, moved: false };
    }
  }

  function onEditorMove(e) {
    if (!edDrag || !ed) return;
    const rect = edCanvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    if (!edDrag.moved
        && (Math.abs(x - edDrag.x0) > 3 || Math.abs(y - edDrag.y0) > 3)) {
      edDrag.moved = true;
    }
    if (!edDrag.moved) return;

    const n = edDrag.note;
    if (edDrag.mode === "move") {
      n.beat = snapBeat(edDrag.beat0 + (x - edDrag.x0) / PPB);
      n.midi = clamp(edDrag.midi0 + Math.round((edDrag.y0 - y) / ROWH), 0, 127);
      patchNoteEl(n);
    } else if (edDrag.mode === "resize") {
      n.dur = Math.max(ed.grid || 0.25, snapBeat(edDrag.dur0 + (x - edDrag.x0) / PPB));
      patchNoteEl(n);
    }
  }

  function onEditorUp(e) {
    if (!edDrag || !ed) return;
    const d = edDrag;
    edDrag = null;

    if (d.mode === "add") {
      if (d.moved) { renderEditor(); return; }
      const rect = edCanvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      if (x < KEYW || y < 0 || y > rect.height) { ed.sel = null; renderEditor(); return; }
      const note = {
        beat: snapBeat((x - KEYW) / PPB),
        dur: 1,
        midi: clamp(ed.hi - Math.floor(y / ROWH), 0, 127),
      };
      ed.notes.push(note);
      sortNotes();
      ed.sel = note;
      pushHistory();
      renderEditor();
      return;
    }

    if (d.moved) {
      const sel = d.note;
      sortNotes();
      ed.sel = sel;
      pushHistory();
      renderEditor();
    }
  }

  function onEditorKey(e) {
    if (!ed || state.view !== "edit") return;
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "select" || tag === "textarea") {
      if (e.key === "Escape") e.target.blur();
      return;
    }
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === "z") {
      e.preventDefault();
      if (e.shiftKey) redoEdit(); else undoEdit();
      return;
    }
    if (mod && e.key.toLowerCase() === "y") { e.preventDefault(); redoEdit(); return; }
    if (!ed.sel) return;

    const step = e.shiftKey ? 12 : 1;
    if (e.key === "ArrowUp") { e.preventDefault(); nudgePitch(step); }
    else if (e.key === "ArrowDown") { e.preventDefault(); nudgePitch(-step); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); nudgeBeat(-ed.grid); }
    else if (e.key === "ArrowRight") { e.preventDefault(); nudgeBeat(ed.grid); }
    else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); deleteSelected(); }
  }

  function patchNoteEl(n) {
    if (!edCanvas) return;
    const i = ed.notes.indexOf(n);
    const el = edCanvas.querySelector(`.ed-note[data-i="${i}"]`);
    if (!el) return;
    el.style.left = `${KEYW + n.beat * PPB}px`;
    el.style.top = `${(ed.hi - n.midi) * ROWH + 1}px`;
    el.style.width = `${Math.max(8, n.dur * PPB - 1)}px`;
    el.querySelector("span").textContent = midiName(n.midi);
    updateSelInfo();
  }

  function selectVisual(n) {
    if (!edCanvas) return;
    edCanvas.querySelectorAll(".ed-note").forEach((el) => {
      el.classList.toggle("is-sel", ed.notes[Number(el.dataset.i)] === n);
    });
    updateSelInfo();
  }

  function updateSelInfo() {
    const box = $("#edSel");
    if (!box) return;
    const n = ed && ed.sel;
    const has = !!n;
    ["edSplit", "edMerge", "edDel"].forEach((id) => {
      const b = $(`#${id}`);
      if (b) b.disabled = !has;
    });
    if (!has) { box.textContent = `未选中音符 · 共 ${ed ? ed.notes.length : 0} 音`; return; }
    const i = ed.notes.indexOf(n);
    box.innerHTML = `第 <b>${i + 1}</b>/${ed.notes.length} 音 · <b>${midiName(n.midi)}</b>`
      + `（MIDI ${n.midi}）· <b>${round4(n.dur)}</b> 拍 · 起于第 <b>${round4(n.beat)}</b> 拍`;
  }

  function nudgePitch(delta) {
    if (!ed.sel) return;
    ed.sel.midi = clamp(ed.sel.midi + delta, 0, 127);
    sortNotes();
    pushHistory();
    renderEditor();
  }

  function nudgeBeat(delta) {
    if (!ed.sel) return;
    ed.sel.beat = Math.max(0, round4(ed.sel.beat + delta));
    sortNotes();
    pushHistory();
    renderEditor();
  }

  function splitSelected() {
    if (!ed || !ed.sel) return;
    const n = ed.sel;
    const half = round4(n.dur / 2);
    if (half < (ed.grid || 0.25) - 1e-6) { toast("这个音符太短，不能再拆"); return; }
    const copy = { midi: n.midi, beat: round4(n.beat + half), dur: half };
    n.dur = half;
    ed.notes.push(copy);
    sortNotes();
    pushHistory();
    renderEditor();
  }

  function mergeSelected() {
    if (!ed || !ed.sel) return;
    const i = ed.notes.indexOf(ed.sel);
    const next = ed.notes[i + 1];
    if (!next) { toast("后面没有可连写的音符"); return; }
    if (next.midi !== ed.sel.midi) { toast("只能连写相同音高的相邻音符"); return; }
    ed.sel.dur = round4(next.beat + next.dur - ed.sel.beat);
    ed.notes.splice(i + 1, 1);
    pushHistory();
    renderEditor();
  }

  function deleteSelected() {
    if (!ed || !ed.sel) return;
    const i = ed.notes.indexOf(ed.sel);
    if (i < 0) return;
    ed.notes.splice(i, 1);
    ed.sel = null;
    pushHistory();
    renderEditor();
  }

  async function saveEdits() {
    if (!ed || !state.jobId) return;
    const btn = $("#edSave");
    btn.disabled = true;
    try {
      const res = await fetch(`/api/jobs/${state.jobId}/notes/edit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          notes: ed.notes.map((n) => ({
            midi: n.midi,
            beat: round4(n.beat),
            dur: round4(n.dur),
          })),
          tempo: ed.tempo,
          meter: ed.meter,
          key: ed.key,
        }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
      const data = await res.json();
      state.meta = data.meta;
      state.pages = { staff: null, jianpu: null, tab: null };  // 谱面缓存失效
      state.notesCache = null;
      ed.dirty = false;
      btn.classList.remove("is-dirty");
      renderMeta(data.meta, state.sourceMeta);
      renderBadge(data.meta);
      toast("已保存，切到其他标签页即可看到更新后的谱面");
    } catch (e) {
      toast(`保存失败：${e.message || e}`);
    } finally {
      btn.disabled = false;
    }
  }

  function toast(msg) {
    const host = document.querySelector(".editor");
    if (!host) return;
    host.querySelectorAll(".ed-toast").forEach((x) => x.remove());
    const div = document.createElement("div");
    div.className = "ed-toast";
    div.textContent = msg;
    host.appendChild(div);
    setTimeout(() => div.remove(), 2600);
  }

  /* ---------------- 授权 / 推广位 ----------------
     免费 2 次/天；看一段推广 +3 次（每日最多 3 次）；
     激活码买断后不限次。状态全部由后端算，前端只负责展示与引导。 */

  const billing = {
    sponsor: null,
    gateAd: null,
    timer: null,
    sponsorClosed: false,
  };

  async function refreshLicense() {
    try {
      const res = await fetch("/api/license");
      if (res.ok) applyLicense(await res.json());
    } catch (_) {
      /* 拿不到授权状态时不要挡住用户，后端还有一道 402 兜底 */
    }
  }

  function applyLicense(lic) {
    if (!lic) return;
    state.license = lic;
    const chip = $("#quotaChip");
    if (chip) {
      if (lic.billing_enabled === false) {
        // 全免费阶段：只显示状态，不引导付费
        chip.textContent = "全功能免费";
        chip.classList.add("is-pro");
        chip.classList.remove("is-low");
        chip.style.cursor = "default";
        chip.title = "当前版本所有功能免费，无需激活";
      } else if (lic.unlimited) {
        chip.textContent = "买断版 · 不限次";
        chip.classList.add("is-pro");
        chip.classList.remove("is-low");
      } else {
        const left = lic.left_today ?? 0;
        chip.textContent = `今天还剩 ${left} 次`;
        chip.classList.toggle("is-low", left <= 0);
        chip.classList.remove("is-pro");
      }
    }
    const watch = $("#gateWatch");
    if (watch && !lic.unlimited) {
      const adLeft = lic.ad_left_today ?? 0;
      watch.disabled = adLeft <= 0;
      watch.textContent = adLeft > 0
        ? `看推广解锁 +${lic.bonus_per_ad} 次`
        : "今日推广次数已用完";
    }
    if ($("#gateMask") && !$("#gateMask").hidden) updateGateCopy();
    if ($("#actMask") && !$("#actMask").hidden) {
      $("#actMachine").textContent = lic.machine_code || "—";
    }
  }

  function updateGateCopy() {
    const lic = state.license || {};
    const sub = $("#gateSub");
    if (!sub) return;
    const free = lic.free_per_day ?? 2;
    const per = lic.bonus_per_ad ?? 3;
    sub.textContent = `每天免费 ${free} 次，今天已用完。看一段 12 秒的推广再解锁 ${per} 次，或输入激活码永久不限次。`;
    const note = $("#gateNote");
    if (!note.textContent) {
      const adLeft = lic.ad_left_today ?? 0;
      if (adLeft <= 0) {
        note.textContent = "今天的推广次数也用完了，明天 0 点刷新。";
        note.className = "modal-note is-err";
      }
    }
  }

  async function loadSponsor() {
    if (billing.sponsorClosed) return;
    // 商业模式关闭时完全不出现推广位
    if (state.license && state.license.billing_enabled === false) return;
    try {
      const res = await fetch("/api/ads?slot=banner");
      if (!res.ok) return;
      const { item } = await res.json();
      if (!item) return;
      billing.sponsor = item;
      $("#sponsorTitle").textContent = item.title || "";
      $("#sponsorDesc").textContent = item.desc || "";
      $("#sponsorCta").textContent = item.cta || "看看";
      $("#sponsorBar").hidden = false;
      adEvent(item, "banner", "impression");
    } catch (_) {
      /* 推广位加载失败不影响主流程 */
    }
  }

  function adEvent(item, slot, type) {
    if (!item || !item.id) return;
    fetch("/api/ads/event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: item.id, slot, type }),
    }).catch(() => {});
  }

  function openSponsor(item, slot) {
    if (!item) return;
    adEvent(item, slot, "click");
    if (item.action === "activate") { openActivate(); return; }
    if (item.url) window.open(item.url, "_blank", "noopener");
  }

  async function renderGateAd() {
    const box = $("#gateAd");
    try {
      const res = await fetch("/api/ads?slot=unlock");
      const { item } = await res.json();
      if (!item) { box.hidden = true; return; }
      billing.gateAd = item;
      box.hidden = false;
      box.innerHTML = `
        <div class="gate-ad-mark" aria-hidden="true">♪</div>
        <div class="gate-ad-body">
          <strong>${escapeHtml(item.title || "")}</strong>
          <p>${escapeHtml(item.desc || "")}</p>
          <span class="gate-ad-cta">${escapeHtml(item.cta || "去看看")} →</span>
        </div>`;
      box.onclick = () => openSponsor(item, "unlock");
      adEvent(item, "unlock", "impression");
    } catch (_) {
      box.hidden = true;
    }
  }

  function showGate() {
    $("#gateMask").hidden = false;
    $("#gateProgress").hidden = true;
    $("#gateNote").textContent = "";
    $("#gateNote").className = "modal-note";
    updateGateCopy();
    renderGateAd();
  }

  function hideGate() {
    $("#gateMask").hidden = true;
    clearInterval(billing.timer);
    billing.timer = null;
    $("#gateProgress").hidden = true;
  }

  async function watchAd() {
    const btn = $("#gateWatch");
    btn.disabled = true;
    try {
      const res = await fetch("/api/license/ad/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slot: "unlock" }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        note("#gateNote", data.error || "暂时无法开始，请稍后重试", "err");
        btn.disabled = false;
        return;
      }
      startCountdown(data.session_id, data.seconds || 12);
    } catch (_) {
      note("#gateNote", "网络异常，请重试", "err");
      btn.disabled = false;
    }
  }

  function startCountdown(sid, seconds) {
    const wrap = $("#gateProgress");
    const bar = $("#gateBar");
    const label = $("#gateCountdown");
    wrap.hidden = false;
    bar.style.transition = "none";
    bar.style.width = "0%";
    void bar.offsetWidth;                      // 强制重排，让过渡从头开始
    bar.style.transition = `width ${seconds}s linear`;
    bar.style.width = "100%";

    let left = seconds;
    label.textContent = `${left} 秒后可领取`;
    clearInterval(billing.timer);
    billing.timer = setInterval(() => {
      left -= 1;
      if (left > 0) {
        label.textContent = `${left} 秒后可领取`;
        return;
      }
      clearInterval(billing.timer);
      billing.timer = null;
      label.textContent = "可以领取了";
      claimAd(sid);
    }, 1000);
  }

  async function claimAd(sid) {
    try {
      const res = await fetch("/api/license/ad/claim", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sid }),
      });
      const data = await res.json();
      if (data.license) applyLicense(data.license);
      if (!res.ok || !data.ok) {
        note("#gateNote", data.message || "领取失败，请重试", "err");
        $("#gateWatch").disabled = false;
        return;
      }
      note("#gateNote", data.message || "已解锁", "ok");
      $("#gateProgress").hidden = true;
      setTimeout(() => {
        if (state.license?.can_run) hideGate();
      }, 800);
    } catch (_) {
      note("#gateNote", "领取失败，请重试", "err");
      $("#gateWatch").disabled = false;
    }
  }

  function openActivate() {
    hideGate();
    $("#actMask").hidden = false;
    $("#actInput").value = "";
    $("#actNote").textContent = "";
    $("#actNote").className = "modal-note";
    $("#actMachine").textContent = state.license?.machine_code || "—";
    setTimeout(() => $("#actInput").focus(), 60);
  }

  async function submitActivate() {
    const code = $("#actInput").value.trim();
    if (!code) {
      note("#actNote", "请先填入激活码", "err");
      return;
    }
    const btn = $("#actSubmit");
    btn.disabled = true;
    try {
      const res = await fetch("/api/license/redeem", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
      const data = await res.json();
      if (data.license) applyLicense(data.license);
      if (!res.ok || !data.ok) {
        note("#actNote", data.message || "激活失败", "err");
        return;
      }
      note("#actNote", data.message, "ok");
      setTimeout(() => { $("#actMask").hidden = true; }, 1400);
    } catch (_) {
      note("#actNote", "网络异常，请重试", "err");
    } finally {
      btn.disabled = false;
    }
  }

  function note(sel, text, kind) {
    const el = $(sel);
    if (!el) return;
    el.textContent = text || "";
    el.className = "modal-note" + (kind === "ok" ? " is-ok" : kind === "err" ? " is-err" : "");
  }

  function bindBilling() {
    $("#quotaChip").addEventListener("click", () => {
      const lic = state.license || {};
      if (lic.billing_enabled === false) return;   // 全免费阶段不弹任何东西
      if (lic.unlimited || (lic.left_today ?? 0) > 0) openActivate();
      else showGate();
    });

    $("#gateClose").addEventListener("click", hideGate);
    $("#gateMask").addEventListener("click", (e) => {
      if (e.target.id === "gateMask") hideGate();
    });
    $("#gateWatch").addEventListener("click", watchAd);
    $("#gateActivate").addEventListener("click", openActivate);

    $("#actClose").addEventListener("click", () => { $("#actMask").hidden = true; });
    $("#actMask").addEventListener("click", (e) => {
      if (e.target.id === "actMask") $("#actMask").hidden = true;
    });
    $("#actSubmit").addEventListener("click", submitActivate);
    $("#actInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter") submitActivate();
    });
    $("#actCopy").addEventListener("click", async () => {
      const code = $("#actMachine").textContent.trim();
      try { await navigator.clipboard.writeText(code); } catch (_) {}
      $("#actCopy").textContent = "已复制";
      setTimeout(() => { $("#actCopy").textContent = "复制"; }, 1500);
    });

    $("#sponsorCta").addEventListener("click", () => openSponsor(billing.sponsor, "banner"));
    $("#sponsorClose").addEventListener("click", () => {
      billing.sponsorClosed = true;
      $("#sponsorBar").hidden = true;
    });

    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (!$("#actMask").hidden) { $("#actMask").hidden = true; return; }
      if (!$("#gateMask").hidden) hideGate();
    });
  }

  /* ---------------- 试听 ---------------- */
  function bindPlayback() {
    $("#playSource").addEventListener("click", () => {
      stopAll();
      if (!state.audioEl) {
        state.audioEl = new Audio(`/api/jobs/${state.jobId}/audio`);
      }
      state.audioEl.currentTime = 0;
      state.audioEl.play().catch((e) => showError(`无法播放原曲：${e.message}`));
    });

    $("#playScore").addEventListener("click", async () => {
      stopAll();
      try {
        if (!state.notesCache) {
          const res = await fetch(`/api/jobs/${state.jobId}/notes`);
          state.notesCache = await res.json();
        }
        playScore(state.notesCache);
      } catch (e) {
        showError(`无法试听谱面：${e.message}`);
      }
    });

    $("#stopPlay").addEventListener("click", stopAll);
  }

  function playScore(data) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) { showError("当前浏览器不支持 Web Audio"); return; }
    const ctx = new Ctx();
    state.audioCtx = ctx;
    const spb = 60 / Math.max(20, data.tempo);   // 每拍秒数

    for (const n of data.notes) {
      const t0 = ctx.currentTime + 0.08 + n.beat * spb;
      const dur = Math.max(0.06, n.dur * spb);
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "triangle";
      osc.frequency.value = 440 * Math.pow(2, (n.midi - 69) / 12);

      gain.gain.setValueAtTime(0.0001, t0);
      gain.gain.exponentialRampToValueAtTime(0.16, t0 + 0.012);
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);

      osc.connect(gain).connect(ctx.destination);
      osc.start(t0);
      osc.stop(t0 + dur + 0.04);
    }
  }

  function stopAll() {
    if (state.audioEl) { state.audioEl.pause(); state.audioEl.currentTime = 0; }
    if (state.audioCtx) {
      try { state.audioCtx.close(); } catch (_) { /* 忽略已关闭 */ }
      state.audioCtx = null;
    }
  }

  /* ---------------- 导出 ---------------- */
  function bindExport() {
    $("#dlMidi").addEventListener("click", () => download("midi"));
    $("#dlXml").addEventListener("click", () => download("musicxml"));
  }

  function download(fmt) {
    if (!state.jobId) return;
    window.location.href = `/api/jobs/${state.jobId}/export/${fmt}`;
  }

  /* ---------------- 工具 ---------------- */
  function showError(msg) {
    const body = $("#resultBody");
    body.innerHTML = `<div class="alert">${escapeHtml(msg)}</div>`;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  document.addEventListener("DOMContentLoaded", init);
})();
