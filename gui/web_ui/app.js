/* ==========================================================================
   Flacify Studio — Spotify Desktop Web UI & Real-Time WebAudio DSP Engine
   ========================================================================== */

const state = {
  activeView: "library",
  libSubtab: "tracks", // 'tracks' | 'playlists' | 'albums'
  sideFilter: "all",
  sideSearch: "",
  searchQuery: "",
  selectedGenre: "all",
  sortBy: "title_asc",
  activeCollection: null, // { name, type, folder_path, cover_key, subtitle }

  library: {
    tracks: [],
    playlists: [],
    albums: [],
    genres: [],
    stats: { total_tracks: 0, total_size_str: "0 B", playlists_count: 0, albums_count: 0 },
  },
  filteredTracks: [],

  // Player & Playlist State
  playlist: [],
  currentIndex: -1,
  currentTrack: null,
  isPlaying: false,
  shuffle: false,
  repeatMode: "off", // 'off' | 'all' | 'one'
  isSeeking: false,
  volume: 100,
  isMuted: false,

  // Lyrics & Translation State
  lyrics: {
    synced: true,
    lines: [],
    rawText: "",
    translated: [],
    transLang: "none", // 'none' | 'en' | 'fa'
    activeIdx: -1,
  },

  // 10-Band Equalizer State
  eq: {
    enabled: false,
    preset: "Flat (Default)",
    bands: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    preamp: 0,
    bassBoost: 0,
    frequencies: [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000],
    presets: {},
  },

  // Queue & Saved Playlists
  queue: [],
  queueFilter: "all",
  isPaused: false,
  savedPlaylists: [],
  selectedSavedPlaylistId: null,
  lastResolveMsg: "",
};

const ROW_HEIGHT = 56;
const audioEl = document.getElementById("audio-element");

// Web Audio API Graph Nodes
let audioCtx = null;
let mediaSource = null;
let preampNode = null;
let bassBoostNode = null;
let bandNodes = [];
let analyserNode = null;

// ==========================================================================
// Helper Utilities
// ==========================================================================
function coverUrl(key) {
  if (!key) return "";
  if (key.startsWith("http://") || key.startsWith("https://")) {
    return `/api/cover?key=${encodeURIComponent(key)}`;
  }
  return `/api/cover?key=${encodeURIComponent(key)}`;
}

function audioStreamUrl(filePath) {
  return `/api/audio?path=${encodeURIComponent(filePath)}`;
}

function formatMs(ms) {
  if (!ms || ms < 0 || !isFinite(ms)) return "0:00";
  const totalSec = Math.floor(ms / 1000);
  const mins = Math.floor(totalSec / 60);
  const secs = totalSec % 60;
  return `${mins}:${secs < 10 ? "0" : ""}${secs}`;
}

function escapeHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function showToast(msg) {
  const wrap = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = msg;
  wrap.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    setTimeout(() => el.remove(), 250);
  }, 3200);
}

async function apiGet(url) {
  try {
    const res = await fetch(url);
    if (!res.ok) {
      console.warn(`GET ${url} returned HTTP ${res.status}`);
      return { ok: false, status: res.status };
    }
    return await res.json();
  } catch (err) {
    console.warn(`GET ${url} network error:`, err);
    return { ok: false, error: String(err) };
  }
}

async function apiPost(url, data = {}) {
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    return await res.json();
  } catch (err) {
    console.warn(`POST ${url} network error:`, err);
    return { ok: false, error: String(err) };
  }
}

function updateAmbientFromImage(imgUrl) {
  if (!imgUrl) {
    document.documentElement.style.setProperty("--ambient-rgb", "29, 185, 84");
    return;
  }
  const img = new Image();
  img.crossOrigin = "anonymous";
  img.onload = () => {
    try {
      const c = document.createElement("canvas");
      c.width = 16;
      c.height = 16;
      const ctx = c.getContext("2d");
      ctx.drawImage(img, 0, 0, 16, 16);
      const data = ctx.getImageData(0, 0, 16, 16).data;
      let r = 0, g = 0, b = 0, count = 0;
      for (let i = 0; i < data.length; i += 4) {
        const pr = data[i], pg = data[i + 1], pb = data[i + 2];
        const lum = (pr + pg + pb) / 3;
        if (lum > 24 && lum < 235) {
          r += pr; g += pg; b += pb; count++;
        }
      }
      if (count > 0) {
        r = Math.min(255, Math.round((r / count) * 1.15));
        g = Math.min(255, Math.round((g / count) * 1.15));
        b = Math.min(255, Math.round((b / count) * 1.15));
        document.documentElement.style.setProperty("--ambient-rgb", `${r}, ${g}, ${b}`);
      }
    } catch (_) {}
  };
  img.src = imgUrl;
}

// ==========================================================================
// Real-Time Web Audio API 10-Band Equalizer & Spectrum Visualizer
// ==========================================================================
function ensureAudioGraph() {
  if (audioCtx) {
    if (audioCtx.state === "suspended") audioCtx.resume();
    return;
  }
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    audioCtx = new Ctx();
    mediaSource = audioCtx.createMediaElementSource(audioEl);

    preampNode = audioCtx.createGain();
    bassBoostNode = audioCtx.createBiquadFilter();
    bassBoostNode.type = "lowshelf";
    bassBoostNode.frequency.value = 85;

    bandNodes = state.eq.frequencies.map((freq, idx) => {
      const f = audioCtx.createBiquadFilter();
      f.type = idx === 0 ? "lowshelf" : idx === 9 ? "highshelf" : "peaking";
      f.frequency.value = freq;
      f.Q.value = 1.4;
      f.gain.value = 0;
      return f;
    });

    analyserNode = audioCtx.createAnalyser();
    analyserNode.fftSize = 128;
    analyserNode.smoothingTimeConstant = 0.8;

    // Connect chain: source -> preamp -> bassBoost -> 10 bands -> analyser -> destination
    mediaSource.connect(preampNode);
    preampNode.connect(bassBoostNode);
    let prev = bassBoostNode;
    for (const b of bandNodes) {
      prev.connect(b);
      prev = b;
    }
    prev.connect(analyserNode);
    analyserNode.connect(audioCtx.destination);

    syncAudioGraphParams();
    requestAnimationFrame(drawVisualizers);
  } catch (e) {
    console.warn("WebAudio init error:", e);
  }
}

function syncAudioGraphParams() {
  if (!audioCtx || !preampNode) return;
  const on = state.eq.enabled;
  const preDb = on ? Number(state.eq.preamp || 0) : 0;
  preampNode.gain.value = Math.pow(10, preDb / 20);
  bassBoostNode.gain.value = on ? Number(state.eq.bassBoost || 0) : 0;
  bandNodes.forEach((node, idx) => {
    node.gain.value = on ? Number(state.eq.bands[idx] || 0) : 0;
  });

  const eqBtn = document.getElementById("btn-open-eq");
  if (eqBtn) eqBtn.classList.toggle("active", on);
}

function drawVisualizers() {
  requestAnimationFrame(drawVisualizers);
  if (!analyserNode) return;

  const freqData = new Uint8Array(analyserNode.frequencyBinCount);
  if (state.isPlaying) {
    analyserNode.getByteFrequencyData(freqData);
  } else {
    freqData.fill(0);
  }

  // 1. Mini Player Bar Visualizer
  const mini = document.getElementById("mini-visualizer");
  if (mini) {
    const ctx = mini.getContext("2d");
    const w = mini.width, h = mini.height;
    ctx.clearRect(0, 0, w, h);
    const bars = 14;
    const step = Math.floor(freqData.length / bars);
    const barW = 3;
    const gap = 2;
    for (let i = 0; i < bars; i++) {
      const val = freqData[i * step] / 255;
      const barH = Math.max(2, Math.round(val * (h - 2)));
      ctx.fillStyle = state.isPlaying ? "#1ED760" : "rgba(255,255,255,0.18)";
      ctx.fillRect(i * (barW + gap), h - barH, barW, barH);
    }
  }

  // 2. EQ Modal Spectrum Canvas
  const eqModal = document.getElementById("eq-modal");
  if (eqModal && !eqModal.classList.contains("hidden")) {
    const c = document.getElementById("eq-spectrum-canvas");
    if (c) {
      const ctx = c.getContext("2d");
      const w = c.width, h = c.height;
      ctx.clearRect(0, 0, w, h);
      const bars = 48;
      const barW = Math.floor(w / bars) - 2;
      for (let i = 0; i < bars; i++) {
        const val = freqData[i] / 255;
        const barH = Math.max(3, Math.round(val * (h - 10)));
        const grad = ctx.createLinearGradient(0, h, 0, 0);
        grad.addColorStop(0, "#1db954");
        grad.addColorStop(1, "#4ade80");
        ctx.fillStyle = grad;
        ctx.fillRect(i * (barW + 2) + 4, h - barH, barW, barH);
      }
    }
  }
}

// ==========================================================================
// Library Loading, Filtering & Virtualized Table Rendering
// ==========================================================================
async function loadLibrary(forceRefresh = false) {
  const data = await apiGet(`/api/library?refresh=${forceRefresh ? "1" : "0"}`);
  if (!data || !data.tracks) return;

  state.library = data;
  document.getElementById("nav-lib-count").textContent = data.stats.total_tracks.toLocaleString();

  // Populate Genre Select
  const genreSel = document.getElementById("lib-genre-select");
  const curGenre = state.selectedGenre;
  genreSel.innerHTML = `<option value="all">All Genres (${data.genres.length})</option>` +
    data.genres.map(g => `<option value="${escapeHtml(g)}">${escapeHtml(g)}</option>`).join("");
  if (data.genres.includes(curGenre)) {
    genreSel.value = curGenre;
  } else {
    state.selectedGenre = "all";
  }

  renderSidebarCollections();
  applyLibraryFilters();
}

function renderSidebarCollections() {
  const listEl = document.getElementById("sidebar-collections-list");
  const q = state.sideSearch.toLowerCase().trim();
  const items = [];

  if (state.sideFilter === "all" || state.sideFilter === "playlist") {
    state.library.playlists.forEach(p => items.push(p));
  }
  if (state.sideFilter === "all" || state.sideFilter === "album") {
    state.library.albums.forEach(a => items.push(a));
  }

  const filtered = q ? items.filter(it => it.name.toLowerCase().includes(q) || (it.subtitle || "").toLowerCase().includes(q)) : items;

  let html = `
    <div class="side-coll-row ${!state.activeCollection ? "active" : ""}" data-coll-name="" data-coll-type="all">
      <div class="side-coll-thumb" style="background: linear-gradient(135deg, #1db954, #0f5132); color:#fff;">♥</div>
      <div class="side-coll-meta">
        <div class="side-coll-title">All Songs</div>
        <div class="side-coll-sub">${state.library.stats.total_tracks.toLocaleString()} songs • ${state.library.stats.total_size_str}</div>
      </div>
    </div>
  `;

  html += filtered.map(c => {
    const isAct = state.activeCollection && state.activeCollection.name === c.name && state.activeCollection.type === c.type;
    const cov = coverUrl(c.cover_key);
    return `
      <div class="side-coll-row ${isAct ? "active" : ""}" data-coll-name="${escapeHtml(c.name)}" data-coll-type="${c.type}">
        <img class="side-coll-thumb" src="${cov}" loading="lazy" onerror="this.style.display='none'" />
        <div class="side-coll-meta">
          <div class="side-coll-title">${escapeHtml(c.name)}</div>
          <div class="side-coll-sub">${escapeHtml(c.subtitle)}</div>
        </div>
      </div>
    `;
  }).join("");

  listEl.innerHTML = html;

  listEl.querySelectorAll(".side-coll-row").forEach(row => {
    row.addEventListener("click", () => {
      const name = row.getAttribute("data-coll-name");
      const type = row.getAttribute("data-coll-type");
      switchView("library");
      if (!name) {
        openCollection(null);
      } else {
        const pool = type === "album" ? state.library.albums : state.library.playlists;
        const found = pool.find(x => x.name === name);
        if (found) openCollection(found);
      }
    });
  });
}

function openCollection(coll) {
  state.activeCollection = coll;
  state.libSubtab = "tracks";
  document.querySelectorAll("#lib-subtabs .seg-tab").forEach(b => {
    b.classList.toggle("active", b.dataset.subtab === "tracks");
  });

  const backBtn = document.getElementById("hero-back-btn");
  const folderBtn = document.getElementById("hero-folder-btn");
  const renameBtn = document.getElementById("hero-rename-btn");
  const heroImg = document.getElementById("hero-cover-img");
  const heroFallback = document.getElementById("hero-cover-fallback");

  if (!coll) {
    document.getElementById("hero-overline").textContent = "OFFLINE MASTER LIBRARY";
    document.getElementById("hero-title").textContent = "All Songs";
    document.getElementById("hero-subtitle").textContent =
      `${state.library.stats.total_tracks.toLocaleString()} songs • ${state.library.stats.playlists_count} playlists • ${state.library.stats.albums_count} albums • ${state.library.stats.total_size_str}`;
    backBtn.classList.add("hidden");
    folderBtn.classList.add("hidden");
    renameBtn.classList.add("hidden");
    heroImg.classList.add("hidden");
    heroFallback.classList.remove("hidden");
    updateAmbientFromImage("");
  } else {
    document.getElementById("hero-overline").textContent = coll.type === "album" ? "ALBUM" : "PLAYLIST";
    document.getElementById("hero-title").textContent = coll.name;
    document.getElementById("hero-subtitle").textContent =
      `${coll.subtitle} • ${coll.genre_summary || "Mixed"} • ${coll.folder_path}`;
    backBtn.classList.remove("hidden");
    folderBtn.classList.remove("hidden");
    renameBtn.classList.remove("hidden");
    const cUrl = coverUrl(coll.cover_key);
    heroImg.src = cUrl;
    heroImg.classList.remove("hidden");
    heroFallback.classList.add("hidden");
    updateAmbientFromImage(cUrl);
  }

  renderSidebarCollections();
  applyLibraryFilters();
}

function applyLibraryFilters() {
  const tracksContainer = document.getElementById("lib-tracks-container");
  const gridContainer = document.getElementById("lib-grid-container");

  if (state.libSubtab === "playlists" || state.libSubtab === "albums") {
    tracksContainer.classList.add("hidden");
    gridContainer.classList.remove("hidden");
    renderMediaGrid(state.libSubtab);
    return;
  }

  tracksContainer.classList.remove("hidden");
  gridContainer.classList.add("hidden");

  const q = state.searchQuery.toLowerCase().trim();
  const genre = state.selectedGenre;
  const coll = state.activeCollection;

  let list = state.library.tracks.filter(t => {
    if (coll) {
      const collNameLow = coll.name.toLowerCase();
      const inColls = (t.collections && t.collections.some(c => c.toLowerCase() === collNameLow))
        || ((t.collection_name || "").toLowerCase() === collNameLow)
        || ((t.album || "").toLowerCase() === collNameLow);
      if (!inColls) return false;
    }
    if (genre && genre !== "all") {
      if (!(t.genres_all || "").toLowerCase().includes(genre.toLowerCase())) return false;
    }
    if (q && !q.startsWith("http://") && !q.startsWith("https://")) {
      const hay = `${t.title} ${t.artist} ${t.album} ${t.collection_name} ${(t.collections || []).join(" ")} ${t.genre}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  const sort = state.sortBy;
  list.sort((a, b) => {
    if (sort === "artist_asc") return a.artist.localeCompare(b.artist);
    if (sort === "recent") return (b.mtime || 0) - (a.mtime || 0);
    if (sort === "dur_desc") return (b.duration_ms || 0) - (a.duration_ms || 0);
    if (sort === "dur_asc") return (a.duration_ms || 0) - (b.duration_ms || 0);
    if (sort === "genre_asc") return (a.genre || "zzz").localeCompare(b.genre || "zzz");
    return a.title.localeCompare(b.title);
  });

  state.filteredTracks = list;
  renderVirtualTracks();
}

function renderVirtualTracks() {
  const scrollEl = document.getElementById("view-scroll");
  const spacer = document.getElementById("virtual-tracks-spacer");
  const content = document.getElementById("virtual-tracks-content");
  const total = state.filteredTracks.length;

  spacer.style.height = `${Math.max(total * ROW_HEIGHT, 120)}px`;

  if (total === 0) {
    content.style.transform = `translateY(0px)`;
    content.innerHTML = `<div style="padding: 40px; text-align:center; color: var(--text-secondary);">No matching songs found.</div>`;
    return;
  }

  const headerOffset = spacer.offsetTop || 280;
  const scrollTop = Math.max(0, scrollEl.scrollTop - headerOffset);
  const viewH = scrollEl.clientHeight || 650;

  const firstIdx = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - 10);
  const lastIdx = Math.min(total - 1, Math.ceil((scrollTop + viewH) / ROW_HEIGHT) + 14);

  content.style.transform = `translateY(${firstIdx * ROW_HEIGHT}px)`;

  const curFp = state.currentTrack ? state.currentTrack.file_path : "";
  const html = [];

  for (let i = firstIdx; i <= lastIdx; i++) {
    const t = state.filteredTracks[i];
    const isPlayingRow = curFp && t.file_path === curFp;
    const qbLower = (t.quality_badge || "").toLowerCase();
    const qbClass = qbLower.includes("flac") ? "flac" : qbLower.includes("opus") ? "opus" : "melobot";

    const numCell = isPlayingRow && state.isPlaying
      ? `<div class="eq-bars"><span></span><span></span><span></span><span></span></div>`
      : `<span class="row-idx-text">${i + 1}</span>
         <span class="row-play-icon">▶</span>`;

    html.push(`
      <div class="track-row ${isPlayingRow ? "playing" : ""}" data-idx="${i}">
        <div class="col-num">${numCell}</div>
        <div class="col-title">
          <img class="row-thumb" src="${coverUrl(t.cover_key)}" loading="lazy" onerror="this.style.visibility='hidden'" />
          <div class="row-title-box">
            <div class="row-title-text">${escapeHtml(t.title)}</div>
            <div class="row-artist-text">${escapeHtml(t.artist)}</div>
          </div>
        </div>
        <div class="col-album" data-coll="${escapeHtml(t.collection_name)}">${escapeHtml(t.collection_name || t.album)}</div>
        <div class="col-genre">${escapeHtml(t.genre || "—")}</div>
        <div class="col-quality"><span class="q-badge ${qbClass}">${escapeHtml(t.quality_badge)}</span></div>
        <div class="col-dur">${t.duration_str}</div>
        <div class="col-act">
          <button class="row-act-btn" data-act="lyrics" data-idx="${i}" title="Karaoke Lyrics">🎤</button>
          <button class="row-act-btn" data-act="spectrum" data-idx="${i}" title="Inspect Audio Spectrum">🔬</button>
          <button class="row-act-btn" data-act="folder" data-idx="${i}" title="Reveal in Explorer">📂</button>
          <button class="row-act-btn" data-act="delete" data-idx="${i}" title="Delete Song">🗑</button>
        </div>
      </div>
    `);
  }

  content.innerHTML = html.join("");

  content.querySelectorAll(".track-row").forEach(row => {
    row.addEventListener("click", (e) => {
      const actBtn = e.target.closest(".row-act-btn");
      const idx = Number(row.getAttribute("data-idx"));
      const track = state.filteredTracks[idx];
      if (!track) return;

      if (actBtn) {
        e.stopPropagation();
        const act = actBtn.getAttribute("data-act");
        if (act === "folder") {
          apiPost("/api/shell/open", { path: track.file_path });
        } else if (act === "spectrum") {
          inspectSingleTrackSpectrum(track);
        } else if (act === "lyrics") {
          playTrackFromList(state.filteredTracks, idx);
          openLyricsDrawer();
        } else if (act === "delete") {
          if (confirm(`Delete "${track.title}" from library and disk?`)) {
            apiPost("/api/library/delete", { file_path: track.file_path, delete_from_disk: true }).then(() => {
              showToast(`Deleted "${track.title}"`);
              loadLibrary(true);
            });
          }
        }
        return;
      }

      const collCell = e.target.closest(".col-album");
      if (collCell && track.collection_name) {
        const found = state.library.playlists.find(p => p.name === track.collection_name)
          || state.library.albums.find(a => a.name === track.collection_name);
        if (found) {
          e.stopPropagation();
          openCollection(found);
          return;
        }
      }

      playTrackFromList(state.filteredTracks, idx);
    });

    row.addEventListener("dblclick", (e) => {
      e.stopPropagation();
      const idx = Number(row.getAttribute("data-idx"));
      playTrackFromList(state.filteredTracks, idx);
    });
  });
}

function renderMediaGrid(mode) {
  const grid = document.getElementById("lib-grid-container");
  const q = state.searchQuery.toLowerCase().trim();
  const source = mode === "albums" ? state.library.albums : state.library.playlists;
  const list = q ? source.filter(c => c.name.toLowerCase().includes(q) || (c.subtitle || "").toLowerCase().includes(q)) : source;

  if (list.length === 0) {
    grid.innerHTML = `<div style="grid-column: 1/-1; padding: 40px; text-align:center; color: var(--text-secondary);">No ${mode} found.</div>`;
    return;
  }

  grid.innerHTML = list.map((c, idx) => `
    <div class="media-card" data-idx="${idx}">
      <div class="media-card-art-wrap">
        <img src="${coverUrl(c.cover_key)}" loading="lazy" onerror="this.style.display='none'" />
        <button class="media-card-play" data-play-idx="${idx}" title="Play ${escapeHtml(c.name)}">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M7 5v14l11-7z"/></svg>
        </button>
      </div>
      <div class="media-card-title">${escapeHtml(c.name)}</div>
      <div class="media-card-sub">${escapeHtml(c.subtitle)}</div>
    </div>
  `).join("");

  grid.querySelectorAll(".media-card").forEach(card => {
    card.addEventListener("click", (e) => {
      const idx = Number(card.getAttribute("data-idx"));
      const coll = list[idx];
      if (!coll) return;
      if (e.target.closest(".media-card-play")) {
        e.stopPropagation();
        const collTracks = state.library.tracks.filter(t => (t.collection_name || "").toLowerCase() === coll.name.toLowerCase());
        if (collTracks.length > 0) playTrackFromList(collTracks, 0);
        return;
      }
      openCollection(coll);
    });
  });
}

// Non-repeating Shuffle Bag & Play History
let shuffleBag = [];
let shuffleHistory = [];

function resetShuffleBag() {
  shuffleBag = [];
  shuffleHistory = [];
}

function getNextShuffleIndex() {
  if (state.playlist.length <= 1) return 0;
  if (!shuffleBag.length) {
    shuffleBag = state.playlist.map((_, i) => i);
    for (let i = shuffleBag.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [shuffleBag[i], shuffleBag[j]] = [shuffleBag[j], shuffleBag[i]];
    }
    if (shuffleBag[0] === state.currentIndex && shuffleBag.length > 1) {
      const swap = Math.floor(Math.random() * (shuffleBag.length - 1)) + 1;
      [shuffleBag[0], shuffleBag[swap]] = [shuffleBag[swap], shuffleBag[0]];
    }
  }
  return shuffleBag.shift();
}

function savePlayerState() {
  try {
    localStorage.setItem("flacify_volume", state.volume);
    localStorage.setItem("flacify_muted", state.isMuted ? "1" : "0");
    localStorage.setItem("flacify_shuffle", state.shuffle ? "1" : "0");
    localStorage.setItem("flacify_repeat", state.repeatMode);
    localStorage.setItem("flacify_eq_preset", state.eq.preset);
  } catch (e) {}
}

function loadPlayerState() {
  try {
    const vol = localStorage.getItem("flacify_volume");
    if (vol !== null) {
      state.volume = parseInt(vol, 10);
      audioEl.volume = state.volume / 100;
      const vs = document.getElementById("vol-slider");
      const vf = document.getElementById("vol-fill");
      if (vs) vs.value = state.volume;
      if (vf) vf.style.width = `${state.volume}%`;
    }
    const muted = localStorage.getItem("flacify_muted");
    if (muted === "1") {
      state.isMuted = true;
      audioEl.muted = true;
      const mb = document.getElementById("btn-mute");
      if (mb) mb.classList.add("active");
    }
    const shuf = localStorage.getItem("flacify_shuffle");
    if (shuf === "1") {
      state.shuffle = true;
      const sb = document.getElementById("btn-shuffle");
      if (sb) sb.classList.add("active");
    }
    const rep = localStorage.getItem("flacify_repeat");
    if (rep && ["off", "all", "one"].includes(rep)) {
      state.repeatMode = rep;
      updateRepeatButtonUI();
    }
  } catch (e) {}
}

function updateRepeatButtonUI() {
  const btn = document.getElementById("btn-repeat");
  if (!btn) return;
  btn.classList.toggle("active", state.repeatMode !== "off");
  if (state.repeatMode === "one") {
    btn.title = "Repeat One";
  } else if (state.repeatMode === "all") {
    btn.title = "Repeat All";
  } else {
    btn.title = "Repeat Off";
  }
}

// Global Media Controller Hooks (for Windows System Tray & Native Media Keys)
window.triggerMediaPlayPause = () => {
  if (!state.currentTrack && state.library.tracks.length > 0) {
    playTrackFromList(state.filteredTracks.length ? state.filteredTracks : state.library.tracks, 0);
  } else {
    const btn = document.getElementById("btn-play-pause");
    if (btn) btn.click();
  }
};
window.triggerMediaNext = () => playNext();
window.triggerMediaPrev = () => playPrev();
window.triggerMediaStop = () => {
  audioEl.pause();
  audioEl.currentTime = 0;
};
window.triggerMediaVolume = (delta) => {
  const newVol = Math.max(0, Math.min(100, state.volume + delta));
  state.volume = newVol;
  audioEl.volume = newVol / 100;
  const vs = document.getElementById("vol-slider");
  const vf = document.getElementById("vol-fill");
  if (vs) vs.value = newVol;
  if (vf) vf.style.width = `${newVol}%`;
  savePlayerState();
};
window.triggerMediaSeek = (ms) => {
  if (audioEl.duration) {
    audioEl.currentTime = Math.max(0, Math.min(audioEl.duration, audioEl.currentTime + (ms / 1000)));
  }
};
window.triggerMediaMute = () => {
  const mb = document.getElementById("btn-mute");
  if (mb) mb.click();
};
window.triggerMediaShuffle = () => {
  const sb = document.getElementById("btn-shuffle");
  if (sb) sb.click();
};
window.triggerMediaRepeat = () => {
  const rb = document.getElementById("btn-repeat");
  if (rb) rb.click();
};

// ==========================================================================
// Playback & Synchronized Lyrics Engine
// ==========================================================================
function playTrackFromList(list, index) {
  if (!list || index < 0 || index >= list.length) return;
  ensureAudioGraph();
  if (state.playlist !== list) {
    state.playlist = list.slice();
    resetShuffleBag();
  }
  if (state.currentIndex >= 0 && state.currentIndex !== index) {
    shuffleHistory.push(state.currentIndex);
    if (shuffleHistory.length > 50) shuffleHistory.shift();
  }
  state.currentIndex = index;
  const track = state.playlist[index];
  state.currentTrack = track;

  audioEl.src = audioStreamUrl(track.file_path);
  audioEl.play().catch(e => console.warn("Audio play failed:", e));

  // Update Player Bar UI
  document.getElementById("player-title").textContent = track.title;
  document.getElementById("player-artist").textContent = track.artist;
  document.getElementById("lbl-curr-time").textContent = "0:00";
  document.getElementById("lbl-total-time").textContent = track.duration_str || "0:00";
  document.getElementById("seek-slider").value = 0;
  document.getElementById("seek-fill").style.width = "0%";

  const badgeEl = document.getElementById("player-badge");
  if (track.quality_badge) {
    badgeEl.textContent = track.quality_badge;
    badgeEl.classList.remove("hidden");
  } else {
    badgeEl.classList.add("hidden");
  }

  const cUrl = coverUrl(track.cover_key || track.file_path);
  const pImg = document.getElementById("player-cover-img");
  const pFall = document.getElementById("player-cover-fallback");
  pImg.src = cUrl;
  pImg.classList.remove("hidden");
  pFall.classList.add("hidden");

  // Update Lyrics Drawer Header
  document.getElementById("lyrics-title").textContent = track.title;
  document.getElementById("lyrics-artist").textContent = track.artist;
  document.getElementById("lyrics-cover-img").src = cUrl;
  document.getElementById("lyrics-backdrop-art").style.backgroundImage = `url("${cUrl}")`;

  if (!state.activeCollection) {
    updateAmbientFromImage(cUrl);
  }

  apiPost("/api/player/notify", {
    file_path: track.file_path,
    title: track.title,
    artist: track.artist,
  });

  renderVirtualTracks();
  loadLyricsForTrack(track);
}

function playNext() {
  if (!state.playlist.length) return;
  if (state.shuffle && state.playlist.length > 1) {
    const nextIdx = getNextShuffleIndex();
    playTrackFromList(state.playlist, nextIdx);
    return;
  }
  const nextIdx = state.currentIndex + 1;
  if (nextIdx < state.playlist.length) {
    playTrackFromList(state.playlist, nextIdx);
  } else if (state.repeatMode === "all") {
    playTrackFromList(state.playlist, 0);
  }
}

function playPrev() {
  if (!state.playlist.length) return;
  if (audioEl.currentTime > 3) {
    audioEl.currentTime = 0;
    return;
  }
  if (state.shuffle && shuffleHistory.length > 0) {
    const prevIdx = shuffleHistory.pop();
    playTrackFromList(state.playlist, prevIdx);
    return;
  }
  const prevIdx = state.currentIndex > 0 ? state.currentIndex - 1 : state.playlist.length - 1;
  playTrackFromList(state.playlist, prevIdx);
}

async function loadLyricsForTrack(track) {
  state.lyrics.lines = [];
  state.lyrics.translated = [];
  state.lyrics.activeIdx = -1;
  document.getElementById("ticker-orig").textContent = `♪ ${track.title} — ${track.artist} ♪`;
  document.getElementById("ticker-trans").textContent = "";

  const res = await apiGet(
    `/api/lyrics?path=${encodeURIComponent(track.file_path)}&title=${encodeURIComponent(track.title)}&artist=${encodeURIComponent(track.artist)}`
  );
  if (!res || !res.ok) return;

  state.lyrics.synced = res.synced;
  state.lyrics.lines = res.lines || [];
  state.lyrics.rawText = res.raw_text || "";

  if (res.preferred_trans_lang && state.lyrics.transLang === "none") {
    state.lyrics.transLang = res.preferred_trans_lang;
    updateTranslationPillUI();
  }

  renderLyricsDrawerLines();
  if (state.lyrics.lines.length > 0 && (state.lyrics.transLang === "en" || state.lyrics.transLang === "fa")) {
    triggerLyricsTranslation(state.lyrics.transLang);
  }
}

async function triggerLyricsTranslation(lang) {
  state.lyrics.transLang = lang;
  updateTranslationPillUI();

  if (lang === "none" || !state.lyrics.lines.length) {
    state.lyrics.translated = [];
    renderLyricsDrawerLines();
    updateActiveLyricTicker();
    apiPost("/api/lyrics/translate", { lines: [], target_lang: "none" });
    return;
  }

  const rawLines = state.lyrics.lines.map(l => l.text);
  const res = await apiPost("/api/lyrics/translate", { lines: rawLines, target_lang: lang });
  if (res && res.ok && Array.isArray(res.translated)) {
    state.lyrics.translated = res.translated;
    renderLyricsDrawerLines();
    updateActiveLyricTicker();
  }
}

function updateTranslationPillUI() {
  const lang = state.lyrics.transLang;
  const pillBtn = document.getElementById("btn-cycle-trans");
  const lbl = document.getElementById("lbl-trans-pill");
  if (lang === "en") {
    lbl.textContent = "EN";
    pillBtn.classList.add("active");
  } else if (lang === "fa") {
    lbl.textContent = "فا";
    pillBtn.classList.add("active");
  } else {
    lbl.textContent = "ORIG";
    pillBtn.classList.remove("active");
  }

  document.querySelectorAll("#lyrics-trans-switcher .trans-pill").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.lang === lang);
  });
}

function renderLyricsDrawerLines() {
  const container = document.getElementById("lyrics-lines-list");
  if (!state.lyrics.lines.length) {
    container.innerHTML = `
      <div style="text-align:center; padding: 60px 20px; color: var(--text-secondary);">
        <div style="font-size: 20px; font-weight:700; color:#fff; margin-bottom:8px;">No Synchronized Lyrics Embedded</div>
        <p>Click "↻ Sync LRCLIB" above to fetch synchronized time-stamped lyrics automatically.</p>
      </div>
    `;
    return;
  }

  const hasTrans = (state.lyrics.transLang === "en" || state.lyrics.transLang === "fa")
    && state.lyrics.translated.length === state.lyrics.lines.length;
  const isRtl = state.lyrics.transLang === "fa";

  container.innerHTML = state.lyrics.lines.map((l, idx) => {
    const orig = l.text;
    const tr = hasTrans ? (state.lyrics.translated[idx] || "") : "";
    const showSub = hasTrans && tr && tr.trim().toLowerCase() !== orig.trim().toLowerCase();
    return `
      <div class="lyric-line-item ${idx === state.lyrics.activeIdx ? "active" : ""}" data-idx="${idx}" data-ms="${l.time_ms}">
        <div class="lyric-orig-txt">${escapeHtml(orig)}</div>
        ${showSub ? `<div class="lyric-trans-txt ${isRtl ? "rtl" : ""}">${escapeHtml(tr)}</div>` : ""}
      </div>
    `;
  }).join("");

  container.querySelectorAll(".lyric-line-item").forEach(el => {
    el.addEventListener("click", () => {
      const ms = Number(el.getAttribute("data-ms") || 0);
      audioEl.currentTime = ms / 1000;
    });
  });
}

function updateActiveLyricTicker() {
  const lines = state.lyrics.lines;
  if (!lines.length) return;

  const posMs = audioEl.currentTime * 1000;
  let idx = 0;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].time_ms <= posMs) idx = i;
    else break;
  }

  const changed = idx !== state.lyrics.activeIdx;
  state.lyrics.activeIdx = idx;

  const orig = lines[idx].text;
  document.getElementById("ticker-orig").textContent = orig;

  const hasTrans = (state.lyrics.transLang === "en" || state.lyrics.transLang === "fa")
    && state.lyrics.translated.length === lines.length;
  const tr = hasTrans ? (state.lyrics.translated[idx] || "") : "";

  if (hasTrans && tr && tr.trim().toLowerCase() !== orig.trim().toLowerCase()) {
    document.getElementById("ticker-trans").textContent = `• ${tr}`;
  } else if (idx + 1 < lines.length) {
    document.getElementById("ticker-trans").textContent = `→ ${lines[idx + 1].text}`;
  } else {
    document.getElementById("ticker-trans").textContent = "";
  }

  if (changed) {
    const drawer = document.getElementById("lyrics-drawer");
    if (!drawer.classList.contains("hidden")) {
      const items = drawer.querySelectorAll(".lyric-line-item");
      items.forEach((el, i) => el.classList.toggle("active", i === idx));
      const activeEl = items[idx];
      if (activeEl) {
        activeEl.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }
  }
}

function openLyricsDrawer() {
  document.getElementById("lyrics-drawer").classList.remove("hidden");
  document.getElementById("btn-open-lyrics").classList.add("active");
  setTimeout(() => {
    const activeEl = document.querySelector("#lyrics-lines-list .lyric-line-item.active");
    if (activeEl) activeEl.scrollIntoView({ behavior: "smooth", block: "center" });
  }, 80);
}

// ==========================================================================
// Downloader Queue, Saved Playlists & Studio Tools
// ==========================================================================
async function pollBackendState() {
  try {
    const st = await apiGet("/api/state");
    if (!st || !st.ok) return;

    state.queue = st.queue || [];
    state.isPaused = st.is_paused;

    // Topbar resolving pill
    const resPill = document.getElementById("topbar-resolving");
    if (st.is_resolving) {
      resPill.classList.remove("hidden");
      document.getElementById("topbar-resolving-text").textContent = st.resolving_message || "Resolving Spotify URL...";
    } else {
      resPill.classList.add("hidden");
    }

    if (st.last_resolve && st.last_resolve.message && st.last_resolve.message !== state.lastResolveMsg) {
      state.lastResolveMsg = st.last_resolve.message;
      showToast(st.last_resolve.message);
      loadLibrary(true);
      loadSavedPlaylists();
    }

    // Sidebar badges
    const qPill = document.getElementById("nav-queue-count");
    const activeCnt = (st.counts.downloading || 0) + (st.counts.queued || 0);
    if (activeCnt > 0) {
      qPill.textContent = activeCnt;
      qPill.classList.remove("hidden");
    } else {
      qPill.classList.add("hidden");
    }
    document.getElementById("nav-watch-count").textContent = st.watched_playlists_count || 0;

    // Queue counts
    document.getElementById("q-cnt-all").textContent = st.counts.all || 0;
    document.getElementById("q-cnt-dl").textContent = st.counts.downloading || 0;
    document.getElementById("q-cnt-wait").textContent = st.counts.queued || 0;
    document.getElementById("q-cnt-done").textContent = st.counts.completed || 0;
    document.getElementById("q-cnt-fail").textContent = st.counts.failed || 0;
    document.getElementById("queue-speed-badge").textContent = `⚡ ${st.total_speed_str || "0 B/s"}`;
    document.getElementById("btn-queue-pause").textContent = st.is_paused ? "Resume All" : "Pause All";

    if (state.activeView === "queue") {
      renderQueueList();
    }
  } catch (_) {}
}

function getQueueBadgeClass(it) {
  if (it.status === "Failed") return "qbadge qbadge-fail";
  const b = (it.quality_badge || it.status || "").toUpperCase();
  if (b.includes("FLAC") || b.includes("HI-RES") || b.includes("24-BIT") || b.includes("16-BIT")) return "qbadge qbadge-flac";
  if (b.includes("OPUS") || b.includes("YTM") || b.includes("YOUTUBE")) return "qbadge qbadge-opus";
  if (b.includes("MELOBOT") || b.includes("TELEGRAM")) return "qbadge qbadge-melobot";
  if (b.includes("MP3") || b.includes("320") || b.includes("MUSILON")) return "qbadge qbadge-mp3";
  return "qbadge qbadge-melobot";
}

function renderQueueList() {
  const wrap = document.getElementById("queue-list-container");
  const f = state.queueFilter;
  const list = state.queue.filter(it => {
    if (f === "downloading") return it.status === "Downloading" || it.status === "Resolving";
    if (f === "queued") return it.status === "Queued" || it.status === "Paused" || it.status === "Stopped";
    if (f === "completed") return it.status === "Completed";
    if (f === "failed") return it.status === "Failed";
    return true;
  });

  if (!list.length) {
    wrap.innerHTML = `<div style="padding: 40px; text-align:center; color: var(--text-secondary);">Queue is empty. Paste a Spotify link above to begin downloading.</div>`;
    return;
  }

  wrap.innerHTML = list.map(it => `
    <div class="queue-item-card">
      <img class="row-thumb" src="${coverUrl(it.cover_key)}" onerror="this.style.visibility='hidden'" />
      <div class="row-title-box">
        <div class="row-title-text">${escapeHtml(it.title)}</div>
        <div class="row-artist-text">${escapeHtml(it.artist)} • ${escapeHtml(it.album)}</div>
      </div>
      <div class="q-prog-wrap">
        <div class="q-prog-bar"><div class="q-prog-fill" style="width:${it.progress}%"></div></div>
        <div class="q-prog-meta">
          <span>${it.status === "Downloading" ? (it.speed_str || "Downloading...") : escapeHtml(it.error_message || it.status)}</span>
          <span>${it.progress}%</span>
        </div>
      </div>
      <div><span class="${getQueueBadgeClass(it)}">${escapeHtml(it.quality_badge || it.status)}</span></div>
      <div style="display:flex; gap:4px; justify-content:flex-end;">
        ${it.status === "Failed" ? `<button class="row-act-btn" data-qact="retry_item" data-id="${it.item_id}" title="Retry">↻</button>` : ""}
        <button class="row-act-btn" data-qact="remove" data-id="${it.item_id}" title="Remove">✕</button>
      </div>
    </div>
  `).join("");

  wrap.querySelectorAll("[data-qact]").forEach(btn => {
    btn.addEventListener("click", async () => {
      await apiPost("/api/queue/action", {
        action: btn.getAttribute("data-qact"),
        item_id: btn.getAttribute("data-id"),
      });
      pollBackendState();
    });
  });
}

// Saved & Watched Playlists
async function loadSavedPlaylists() {
  const res = await apiGet("/api/saved_playlists");
  if (!res || !res.ok) return;
  state.savedPlaylists = res.playlists || [];
  const listEl = document.getElementById("saved-playlists-list");

  if (!state.savedPlaylists.length) {
    listEl.innerHTML = `<div style="color:var(--text-secondary); padding:20px; text-align:center;">No saved playlists yet. Click "+ Add URL" to save a Spotify playlist or Liked Songs.</div>`;
    return;
  }

  listEl.innerHTML = state.savedPlaylists.map(p => `
    <div class="side-coll-row ${state.selectedSavedPlaylistId === p.id ? "active" : ""}" data-pid="${escapeHtml(p.id)}">
      <img class="side-coll-thumb" src="${coverUrl(p.local_cover || p.cover_url)}" onerror="this.style.visibility='hidden'" />
      <div class="side-coll-meta">
        <div class="side-coll-title">${p.auto_sync ? "⏱ " : ""}${escapeHtml(p.name)}</div>
        <div class="side-coll-sub">${p.downloaded_count || 0} / ${p.total_tracks || p.track_count || 0} downloaded</div>
      </div>
    </div>
  `).join("");

  listEl.querySelectorAll(".side-coll-row").forEach(row => {
    row.addEventListener("click", () => {
      loadSavedPlaylistDetail(row.getAttribute("data-pid"));
    });
  });
}

let currentSavedTracks = [];
let savedTrackFilter = "all"; // 'all' | 'downloaded' | 'missing'
let savedTrackQuery = "";
let savedTrackSliceLimit = 150;

async function loadSavedPlaylistDetail(pid) {
  state.selectedSavedPlaylistId = pid;
  loadSavedPlaylists();
  const pane = document.getElementById("saved-detail-pane");
  pane.innerHTML = `<div style="padding:30px; color:var(--text-secondary);"><span class="spinner-xs"></span> Loading playlist tracks...</div>`;

  const res = await apiGet(`/api/saved_playlists/tracks?id=${encodeURIComponent(pid)}`);
  if (!res || !res.ok || !res.playlist) {
    pane.innerHTML = `<div style="padding:30px; color:#f87171;">Could not load playlist details.</div>`;
    return;
  }

  const pl = res.playlist;
  const tracks = res.tracks || [];
  currentSavedTracks = tracks;
  savedTrackFilter = "all";
  savedTrackQuery = "";
  savedTrackSliceLimit = 150;

  const downloadedCnt = tracks.filter(t => t.is_downloaded).length;
  const missingCnt = tracks.length - downloadedCnt;
  const cUrl = coverUrl(pl.local_cover || pl.cover_url);

  pane.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:16px; margin-bottom:14px; padding-bottom:14px; border-bottom:1px solid rgba(255,255,255,0.08);">
      <div style="display:flex; align-items:center; gap:16px;">
        <img src="${cUrl}" style="width:68px; height:68px; border-radius:8px; object-fit:cover; background:#222; box-shadow:0 8px 20px rgba(0,0,0,0.5);" onerror="this.style.display='none'" />
        <div>
          <h2 style="font-size:22px; font-weight:800; color:#fff;">${escapeHtml(pl.name)}</h2>
          <div style="color:var(--text-secondary); font-size:12.5px; margin-top:4px;">
            ${tracks.length.toLocaleString()} tracks • <span style="color:#4ade80;">${downloadedCnt.toLocaleString()} downloaded</span>${missingCnt > 0 ? ` • <span style="color:#f87171;">${missingCnt.toLocaleString()} missing</span>` : ""} • Last synced: ${escapeHtml(pl.last_synced_at || "Never")}
          </div>
        </div>
      </div>
      <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
        <button class="btn-primary-emerald" id="btn-pl-play-all" title="Play downloaded tracks from this playlist">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M7 5v14l11-7z"/></svg>
          <span>Play Playlist (${downloadedCnt})</span>
        </button>
        <label class="checkbox-pill" title="Automatically watch and sync new tracks added on Spotify">
          <input type="checkbox" id="chk-pl-watch" ${pl.auto_sync ? "checked" : ""} />
          <span>⏱ Watch Auto-Sync</span>
        </label>
        <button class="btn-secondary-dark" id="btn-pl-sync-now">↻ Sync with Spotify</button>
        ${missingCnt > 0 ? `<button class="btn-primary-emerald" id="btn-pl-dl-missing">Download Missing (${missingCnt})</button>` : `<button class="ghost-pill-btn" disabled style="opacity:0.6; cursor:default;">✓ All Downloaded</button>`}
        <button class="btn-danger-outline" id="btn-pl-delete">Delete</button>
      </div>
    </div>

    <!-- Quick Search & Filter Controls -->
    <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:12px; flex-wrap:wrap;">
      <div class="segmented-tabs" id="saved-filter-tabs">
        <button class="seg-tab active" data-sfilter="all">All (${tracks.length})</button>
        <button class="seg-tab" data-sfilter="downloaded">Downloaded (${downloadedCnt})</button>
        <button class="seg-tab" data-sfilter="missing">Missing (${missingCnt})</button>
      </div>
      <div style="flex:1; max-width:320px;">
        <input type="text" id="saved-track-search" class="sidebar-search-wrap" style="width:100%; height:32px; background:#202020; border:1px solid rgba(255,255,255,0.1); border-radius:16px; padding:0 14px; color:#fff; font-size:12.5px;" placeholder="Search in ${escapeHtml(pl.name)}..." autocomplete="off" />
      </div>
    </div>

    <div id="saved-tracks-list-wrap" style="max-height: calc(100vh - 360px); overflow-y:auto;"></div>
  `;

  renderFilteredSavedTracks();

  // Wire search and filter tabs
  const searchInput = document.getElementById("saved-track-search");
  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      savedTrackQuery = e.target.value.toLowerCase().trim();
      savedTrackSliceLimit = 150;
      renderFilteredSavedTracks();
    });
  }

  document.querySelectorAll("#saved-filter-tabs .seg-tab").forEach(btn => {
    btn.addEventListener("click", () => {
      savedTrackFilter = btn.dataset.sfilter;
      document.querySelectorAll("#saved-filter-tabs .seg-tab").forEach(b => b.classList.toggle("active", b === btn));
      savedTrackSliceLimit = 150;
      renderFilteredSavedTracks();
    });
  });

  // Play Playlist Button
  const playAllBtn = document.getElementById("btn-pl-play-all");
  if (playAllBtn) {
    playAllBtn.addEventListener("click", () => {
      const playable = currentSavedTracks.filter(t => t.is_downloaded && t.file_path);
      if (playable.length > 0) {
        playTrackFromList(playable, 0);
      } else {
        showToast("No downloaded tracks in this playlist yet.");
      }
    });
  }

  document.getElementById("chk-pl-watch").addEventListener("change", async (e) => {
    await apiPost("/api/saved_playlists/action", {
      action: "toggle_watch",
      playlist_id: pid,
      auto_sync: e.target.checked,
    });
    showToast(e.target.checked ? "Enabled Watch Auto-Sync" : "Disabled Watch Auto-Sync");
    loadSavedPlaylists();
  });

  document.getElementById("btn-pl-sync-now").addEventListener("click", async () => {
    const r = await apiPost("/api/saved_playlists/action", { action: "sync", playlist_id: pid, queue_new: true });
    showToast(r.message || "Sync started...");
  });

  const dlMissingBtn = document.getElementById("btn-pl-dl-missing");
  if (dlMissingBtn) {
    dlMissingBtn.addEventListener("click", async () => {
      const r = await apiPost("/api/saved_playlists/action", { action: "download_missing", playlist_id: pid });
      showToast(`Queued ${r.queued || 0} missing tracks`);
      switchView("queue");
    });
  }

  document.getElementById("btn-pl-delete").addEventListener("click", async () => {
    if (confirm(`Delete saved playlist "${pl.name}"?`)) {
      await apiPost("/api/saved_playlists/action", { action: "delete", playlist_id: pid });
      state.selectedSavedPlaylistId = null;
      pane.innerHTML = `<div class="empty-state">Playlist deleted.</div>`;
      loadSavedPlaylists();
    }
  });
}

function renderFilteredSavedTracks() {
  const wrap = document.getElementById("saved-tracks-list-wrap");
  if (!wrap) return;

  const f = savedTrackFilter;
  const q = savedTrackQuery;

  let filtered = currentSavedTracks.filter(t => {
    if (f === "downloaded" && !t.is_downloaded) return false;
    if (f === "missing" && t.is_downloaded) return false;
    if (q) {
      const hay = `${t.title} ${t.artist} ${t.album}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  if (!filtered.length) {
    wrap.innerHTML = `<div style="text-align:center; padding:40px; color:var(--text-secondary);">No tracks match the filter.</div>`;
    return;
  }

  const sliced = filtered.slice(0, savedTrackSliceLimit);
  const playableList = filtered.filter(t => t.is_downloaded && t.file_path);

  wrap.innerHTML = `
    <div class="track-table-header" style="grid-template-columns: 44px minmax(200px, 2fr) minmax(130px, 1.2fr) 130px 70px;">
      <div class="col-num">#</div>
      <div class="col-title">Title</div>
      <div class="col-album">Album</div>
      <div class="col-quality">Status</div>
      <div class="col-dur">Duration</div>
    </div>
    ${sliced.map((t, idx) => {
      const qbLower = (t.quality_badge || "").toLowerCase();
      const qbClass = qbLower.includes("flac") ? "flac" : qbLower.includes("opus") ? "opus" : "melobot";
      const isCur = state.currentTrack && t.file_path && t.file_path === state.currentTrack.file_path;

      const numCell = isCur && state.isPlaying
        ? `<div class="eq-bars"><span></span><span></span><span></span><span></span></div>`
        : `<span class="row-idx-text">${t.index || (idx + 1)}</span><span class="row-play-icon">▶</span>`;

      return `
        <div class="track-row ${isCur ? "playing" : ""}" style="grid-template-columns: 44px minmax(200px, 2fr) minmax(130px, 1.2fr) 130px 70px;" data-sidx="${idx}">
          <div class="col-num">${numCell}</div>
          <div class="col-title">
            <img class="row-thumb" src="${coverUrl(t.cover_key || t.cover_url)}" loading="lazy" onerror="this.style.visibility='hidden'" />
            <div class="row-title-box">
              <div class="row-title-text">${escapeHtml(t.title)}</div>
              <div class="row-artist-text">${escapeHtml(t.artist)}</div>
            </div>
          </div>
          <div class="col-album">${escapeHtml(t.album || "—")}</div>
          <div class="col-quality">
            <span class="q-badge ${t.is_downloaded ? qbClass : "opus"}">
              ${t.is_downloaded ? escapeHtml(t.quality_badge || "✓ Downloaded") : "Missing"}
            </span>
          </div>
          <div class="col-dur">${t.duration_str || "--:--"}</div>
        </div>
      `;
    }).join("")}
    ${filtered.length > savedTrackSliceLimit ? `
      <div style="text-align:center; padding:16px;">
        <button class="ghost-pill-btn" id="btn-saved-load-more">Load more tracks (${sliced.length} of ${filtered.length})...</button>
      </div>
    ` : ""}
  `;

  // Row click listeners to play track
  wrap.querySelectorAll(".track-row").forEach(row => {
    row.addEventListener("click", () => {
      const idx = Number(row.getAttribute("data-sidx"));
      const track = sliced[idx];
      if (!track) return;
      if (track.is_downloaded && track.file_path) {
        const pIdx = playableList.findIndex(x => x.spotify_id === track.spotify_id || x.file_path === track.file_path);
        playTrackFromList(playableList, pIdx >= 0 ? pIdx : 0);
      } else {
        showToast(`"${track.title}" is not yet downloaded.`);
      }
    });
  });

  const loadMoreBtn = document.getElementById("btn-saved-load-more");
  if (loadMoreBtn) {
    loadMoreBtn.addEventListener("click", () => {
      savedTrackSliceLimit += 250;
      renderFilteredSavedTracks();
    });
  }
}

// ==========================================================================
// Audio Studio Tools: Spectrum Inspector & Duplicate Merger
// ==========================================================================
async function inspectSingleTrackSpectrum(track) {
  switchView("tools");
  const box = document.getElementById("spectrum-single-result");
  box.classList.remove("hidden");
  box.innerHTML = `<div style="color:var(--spotify-bright); font-weight:600;">🔬 Analyzing acoustic frequency cutoff &amp; generating spectrogram for "${escapeHtml(track.title)}"...</div>`;

  const res = await apiPost("/api/tools/spectrum/inspect", { file_path: track.file_path });
  if (!res || !res.ok || !res.result) {
    box.innerHTML = `<div style="color:#f87171;">Could not inspect spectrum for this file.</div>`;
    return;
  }

  const r = res.result;
  const isAuth = r.verdict === "authentic";
  box.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
      <div>
        <div style="font-size:16px; font-weight:800;">${escapeHtml(track.title)} — ${escapeHtml(track.artist)}</div>
        <div style="color:var(--text-secondary); font-size:12.5px; margin-top:2px;">
          Measured Acoustic Roll-off: <strong style="color:#fff;">${r.cutoff_khz} kHz</strong> • Claimed Quality: ${escapeHtml(track.quality_badge)}
        </div>
      </div>
      <span class="q-badge ${isAuth ? "melobot" : "flac"}" style="font-size:12px; padding:5px 12px;">
        ${isAuth ? "✓ AUTHENTIC HIGH-RESOLUTION" : `⚠ ${escapeHtml(r.verdict.toUpperCase())} (${r.cutoff_khz} kHz)`}
      </span>
    </div>
    ${r.spectrogram_path ? `<img class="spectrogram-img" src="${coverUrl(r.spectrogram_path)}&t=${Date.now()}" />` : ""}
  `;
}

// ==========================================================================
// Equalizer UI Initialization
// ==========================================================================
async function initEqualizerUI() {
  const res = await apiGet("/api/eq");
  if (!res || !res.ok) return;

  state.eq.enabled = res.enabled;
  state.eq.preset = res.preset;
  state.eq.bands = res.bands || [0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
  state.eq.preamp = res.preamp || 0;
  state.eq.bassBoost = res.bass_boost || 0;
  state.eq.frequencies = res.frequencies || state.eq.frequencies;
  state.eq.presets = res.presets || {};

  document.getElementById("eq-enabled-toggle").checked = state.eq.enabled;

  const presetSel = document.getElementById("eq-preset-select");
  presetSel.innerHTML = Object.keys(state.eq.presets)
    .map(p => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`)
    .join("") + `<option value="Custom">Custom</option>`;
  presetSel.value = state.eq.presets[state.eq.preset] ? state.eq.preset : "Custom";

  renderEqSliders();
  syncAudioGraphParams();
}

function renderEqSliders() {
  document.getElementById("eq-preamp-slider").value = state.eq.preamp;
  document.getElementById("lbl-eq-preamp").textContent = `${state.eq.preamp >= 0 ? "+" : ""}${Number(state.eq.preamp).toFixed(1)} dB`;

  document.getElementById("eq-bass-slider").value = state.eq.bassBoost;
  document.getElementById("lbl-eq-bass").textContent = `+${Number(state.eq.bassBoost).toFixed(1)} dB`;

  const grid = document.getElementById("eq-bands-grid");
  grid.innerHTML = state.eq.frequencies.map((freq, idx) => {
    const val = Number(state.eq.bands[idx] || 0);
    const lbl = freq >= 1000 ? `${freq / 1000}k` : `${freq}`;
    return `
      <div class="eq-band-col">
        <span class="eq-band-val" id="eq-val-${idx}">${val >= 0 ? "+" : ""}${val.toFixed(1)}</span>
        <div class="eq-vslider-wrap">
          <input type="range" class="eq-vslider" data-bidx="${idx}" min="-12" max="12" step="0.5" value="${val}" />
        </div>
        <span class="eq-band-freq">${lbl}</span>
      </div>
    `;
  }).join("");

  grid.querySelectorAll(".eq-vslider").forEach(sl => {
    sl.addEventListener("input", () => {
      const idx = Number(sl.getAttribute("data-bidx"));
      const v = Number(sl.value);
      state.eq.bands[idx] = v;
      state.eq.enabled = true;
      document.getElementById("eq-enabled-toggle").checked = true;
      document.getElementById(`eq-val-${idx}`).textContent = `${v >= 0 ? "+" : ""}${v.toFixed(1)}`;
      document.getElementById("eq-preset-select").value = "Custom";
      syncAudioGraphParams();
    });
    sl.addEventListener("change", saveEqState);
  });
}

function saveEqState() {
  apiPost("/api/eq/save", {
    enabled: state.eq.enabled,
    preset: state.eq.preset,
    bands: state.eq.bands,
    preamp: state.eq.preamp,
    bass_boost: state.eq.bassBoost,
  });
}

// ==========================================================================
// Settings Initialization
// ==========================================================================
function updateMusilonUI(data) {
  const badge = document.getElementById("musilon-status-badge");
  const info = document.getElementById("musilon-info-box");
  if (!badge) return;
  badge.className = "status-pill";

  if (!data || !data.ok) {
    badge.classList.add("offline");
    badge.textContent = "Offline";
    if (info) info.classList.add("hidden");
    return;
  }

  if (data.is_vip) {
    badge.classList.add("vip");
    badge.textContent = "VIP Active";
  } else if (data.is_authenticated) {
    badge.classList.add("active");
    badge.textContent = "Account Active";
  } else if (data.configured) {
    badge.classList.add("guest");
    badge.textContent = "Credentials Saved";
  } else {
    badge.classList.add("offline");
    badge.textContent = "Not Configured";
  }

  let text = "";
  if (data.budget && data.budget.quota_text) {
    text = `👑 Quota: ${data.budget.quota_text}`;
  } else if (data.message) {
    text = data.message;
  }
  if (info) {
    if (text) {
      info.textContent = text;
      info.classList.remove("hidden");
    } else {
      info.classList.add("hidden");
    }
  }
}

function updateTelegramUI(data) {
  const badge = document.getElementById("telegram-status-badge");
  const info = document.getElementById("telegram-info-box");
  if (!badge) return;
  badge.className = "status-pill";

  if (!data || !data.ok) {
    badge.classList.add("disconnected");
    badge.textContent = "Offline";
    if (info) info.classList.add("hidden");
    return;
  }

  if (data.authorized) {
    badge.classList.add("connected");
    const u = data.user || {};
    const name = u.first_name || u.username || "Connected";
    badge.textContent = `Connected as ${name}`;
    if (info) {
      info.textContent = `✈️ Telegram Authorized: @${u.username || u.phone || "user"} (ID: ${u.id || ""})`;
      info.classList.remove("hidden");
    }
  } else if (data.phone) {
    badge.classList.add("disconnected");
    badge.textContent = "Logged Out";
    if (info) info.classList.add("hidden");
  } else {
    badge.classList.add("disconnected");
    badge.textContent = "Not Connected";
    if (info) info.classList.add("hidden");
  }
}

function updateSpotifyUI(data) {
  const badge = document.getElementById("spotify-status-badge");
  const info = document.getElementById("spotify-info-box");
  if (!badge) return;
  badge.className = "status-pill";

  if (!data || !data.ok) {
    badge.classList.add("guest");
    badge.textContent = "Guest Mode (100 cap)";
    if (info) info.classList.add("hidden");
    return;
  }

  if (data.has_user_auth) {
    badge.classList.add("connected");
    badge.textContent = `Authorized as @${data.user_name || "User"}`;
    if (info) {
      info.textContent = `🟢 Full Spotify metadata access active for playlists beyond 100 tracks.`;
      info.classList.remove("hidden");
    }
  } else if (data.configured) {
    badge.classList.add("active");
    badge.textContent = "Keys Configured";
    if (info) {
      info.textContent = `API keys active. Validated for unlimited track queries.`;
      info.classList.remove("hidden");
    }
  } else {
    badge.classList.add("guest");
    badge.textContent = "Guest Mode (100 cap)";
    if (info) info.classList.add("hidden");
  }
}

function updateFFmpegUI(data) {
  const badge = document.getElementById("ffmpeg-status-badge");
  const lbl = document.getElementById("ffmpeg-path-label");
  if (!badge) return;
  badge.className = "status-pill";

  if (!data || !data.ok || !data.installed) {
    badge.classList.add("offline");
    badge.textContent = "Missing";
    if (lbl) lbl.textContent = "FFmpeg is not installed. Click below to download standalone binary.";
    return;
  }

  badge.classList.add("connected");
  badge.textContent = "Installed & Ready";
  if (lbl) lbl.textContent = `Active binary: ${data.path}`;
}

let maintPollTimer = null;
async function startMaintenanceJob(url, label) {
  const banner = document.getElementById("maint-status-banner");
  if (banner) {
    banner.textContent = `Starting ${label}...`;
    banner.classList.remove("hidden");
  }
  const r = await apiPost(url);
  if (!r.ok) {
    if (banner) banner.textContent = r.error || r.message || "Failed to start.";
    return;
  }
  showToast(`${label} started...`);
  if (maintPollTimer) clearInterval(maintPollTimer);
  maintPollTimer = setInterval(async () => {
    const s = await apiGet("/api/maintenance/status");
    if (!s || !s.ok) return;
    if (s.running) {
      if (banner) banner.textContent = `⏳ [${s.task}] ${s.progress || "In progress..."}`;
    } else {
      clearInterval(maintPollTimer);
      maintPollTimer = null;
      if (s.result && s.result.ok) {
        if (banner) banner.textContent = `✅ ${label} completed successfully!`;
        showToast(`${label} finished!`);
        loadLibrary(true);
      } else if (banner) {
        banner.textContent = `❌ ${s.result ? s.result.error : s.progress}`;
      }
    }
  }, 1000);
}

let ffmpegPollTimer = null;
async function downloadFFmpeg() {
  const wrap = document.getElementById("ffmpeg-progress-wrap");
  const fill = document.getElementById("ffmpeg-prog-fill");
  const text = document.getElementById("ffmpeg-prog-text");
  if (wrap) wrap.classList.remove("hidden");
  if (fill) fill.style.width = "0%";
  if (text) text.textContent = "Starting...";

  await apiPost("/api/diagnostics/ffmpeg/download");
  if (ffmpegPollTimer) clearInterval(ffmpegPollTimer);
  ffmpegPollTimer = setInterval(async () => {
    const s = await apiGet("/api/diagnostics/ffmpeg/download_status");
    if (!s || !s.ok) return;
    if (fill) fill.style.width = `${s.progress}%`;
    if (text) text.textContent = `${s.progress}% — ${s.message}`;
    if (!s.downloading) {
      clearInterval(ffmpegPollTimer);
      ffmpegPollTimer = null;
      if (s.success) {
        showToast("FFmpeg installed successfully!");
        const ffRes = await apiGet("/api/diagnostics/ffmpeg");
        updateFFmpegUI(ffRes);
      } else {
        showToast(`FFmpeg download failed: ${s.message}`);
      }
    }
  }, 800);
}

async function saveAllSettings() {
  const getVal = (id) => (document.getElementById(id) ? document.getElementById(id).value.trim() : "");
  const getChk = (id) => (document.getElementById(id) ? document.getElementById(id).checked : false);
  const getNum = (id, def = 0) => (document.getElementById(id) ? Number(document.getElementById(id).value || def) : def);

  const payload = {
    output_dir: getVal("set-output-dir"),
    save_in_subfolders: getChk("set-subfolders"),
    naming_template: getVal("set-naming-template") || "{artist} - {title}",
    album_naming_template: getVal("set-album-naming-template") || "{track_num}. {artist} - {title}",
    concurrency: getNum("set-concurrency", 5),
    preferred_source: getVal("set-preferred-source"),
    preferred_quality: getVal("set-preferred-quality"),
    target_format: getVal("set-target-format"),
    allow_fallback: getChk("set-fallback"),
    lyrics_mode: getVal("set-lyrics-mode"),
    embed_lyrics: getChk("set-embed-lyrics"),
    embed_cover_art: getChk("set-embed-cover"),
    generate_m3u8: getChk("set-generate-m3u8"),
    normalize_volume: getChk("set-normalize"),
    replaygain_tagging: getChk("set-replaygain"),
    cookies_file: getVal("set-cookies-file"),
    proxy: getVal("set-proxy"),
    auto_sync_enabled: getChk("set-autosync-enabled"),
    auto_sync_interval_min: getNum("set-autosync-interval", 30),
    spotify_client_id: getVal("set-sp-id"),
    spotify_client_secret: getVal("set-sp-secret"),
    musilon_enabled: getChk("set-musilon-enabled"),
    musilon_username: getVal("set-musilon-email"),
    musilon_session_cookie: getVal("set-musilon-cookie"),
    musilon_safe_mode: getChk("set-musilon-safe-mode"),
    musilon_cooldown_min_sec: getNum("set-musilon-cd-min", 15),
    musilon_cooldown_max_sec: getNum("set-musilon-cd-max", 35),
    telegram_enabled: getChk("set-tg-enabled"),
    telegram_phone: getVal("set-tg-phone"),
    telegram_safe_delay_sec: getNum("set-tg-delay", 2),
  };

  const pwdInput = document.getElementById("set-musilon-password");
  if (pwdInput && pwdInput.value) payload.musilon_password = pwdInput.value;

  await apiPost("/api/settings", { settings: payload });
  showToast("All settings saved successfully!");
  loadLibrary(true);
}

// ==========================================================================
async function loadSettings() {
  try {
    const res = await apiGet("/api/settings");
    if (res && res.ok && res.settings) {
      const s = res.settings;
      const setVal = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.value = val !== undefined && val !== null ? val : "";
      };
      const setChk = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.checked = Boolean(val);
      };

      setVal("set-output-dir", s.output_dir);
      setChk("set-subfolders", s.save_in_subfolders);
      setVal("set-naming-template", s.naming_template);
      setVal("set-album-naming-template", s.album_naming_template);
      setVal("set-concurrency", s.concurrency);
      setVal("set-preferred-source", s.preferred_source);
      setVal("set-preferred-quality", s.preferred_quality);
      setVal("set-target-format", s.target_format);
      setChk("set-fallback", s.allow_fallback);
      setVal("set-lyrics-mode", s.lyrics_mode);
      setChk("set-embed-lyrics", s.embed_lyrics);
      setChk("set-embed-cover", s.embed_cover_art);
      setChk("set-generate-m3u8", s.generate_m3u8);
      setChk("set-normalize", s.normalize_volume);
      setChk("set-replaygain", s.replaygain_tagging);
      setVal("set-cookies-file", s.cookies_file);
      setVal("set-proxy", s.proxy);
      setChk("set-autosync-enabled", s.auto_sync_enabled);
      setVal("set-autosync-interval", s.auto_sync_interval_min);
      setVal("set-sp-id", s.spotify_client_id);
      setVal("set-sp-secret", s.spotify_client_secret);
      setVal("set-musilon-email", s.musilon_username);
      setVal("set-musilon-cookie", s.musilon_session_cookie);
      setChk("set-musilon-enabled", s.musilon_enabled);
      setChk("set-musilon-safe-mode", s.musilon_safe_mode);
      setVal("set-musilon-cd-min", s.musilon_cooldown_min_sec);
      setVal("set-musilon-cd-max", s.musilon_cooldown_max_sec);
      setVal("set-tg-phone", s.telegram_phone);
      setChk("set-tg-enabled", s.telegram_enabled);
      setVal("set-tg-delay", s.telegram_safe_delay_sec);
    }
  } catch (err) {
    console.error("Error loading /api/settings:", err);
  }

  // Query each status independently so one service delay never blocks others or UI
  apiGet("/api/auth/musilon/status")
    .then(updateMusilonUI)
    .catch((err) => updateMusilonUI({ ok: false, error: String(err) }));

  apiGet("/api/auth/telegram/status")
    .then(updateTelegramUI)
    .catch((err) => updateTelegramUI({ ok: false, error: String(err) }));

  apiGet("/api/auth/spotify/status")
    .then(updateSpotifyUI)
    .catch((err) => updateSpotifyUI({ ok: false, error: String(err) }));

  apiGet("/api/diagnostics/ffmpeg")
    .then(updateFFmpegUI)
    .catch((err) => updateFFmpegUI({ ok: false, error: String(err) }));
}

// ==========================================================================
// Navigation & Event Wiring
// ==========================================================================
function switchView(viewName) {
  state.activeView = viewName;
  document.querySelectorAll("#main-nav .nav-item").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.view === viewName);
  });
  document.querySelectorAll(".view-page").forEach(page => {
    page.classList.toggle("active", page.id === `view-${viewName}`);
  });
  document.getElementById("lyrics-drawer").classList.add("hidden");

  if (viewName === "library") renderVirtualTracks();
  if (viewName === "queue") renderQueueList();
  if (viewName === "saved") loadSavedPlaylists();
  if (viewName === "settings") loadSettings();
}

document.addEventListener("DOMContentLoaded", () => {
  // Sidebar Main Nav
  document.querySelectorAll("#main-nav .nav-item").forEach(btn => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });

  // Sidebar collection filters
  document.querySelectorAll("[data-side-filter]").forEach(btn => {
    btn.addEventListener("click", () => {
      state.sideFilter = btn.getAttribute("data-side-filter");
      document.querySelectorAll("[data-side-filter]").forEach(b => b.classList.toggle("active", b === btn));
      renderSidebarCollections();
    });
  });

  document.getElementById("sidebar-filter-input").addEventListener("input", (e) => {
    state.sideSearch = e.target.value;
    renderSidebarCollections();
  });

  // Topbar Omni Search / URL Bar
  const omniInput = document.getElementById("omni-input");
  const omniClear = document.getElementById("omni-clear");
  const omniDlBtn = document.getElementById("omni-download-btn");

  omniInput.addEventListener("input", () => {
    const val = omniInput.value.trim();
    omniClear.classList.toggle("hidden", !val);
    const isUrl = val.includes("spotify.com/") || val.startsWith("spotify:");
    omniDlBtn.classList.toggle("hidden", !isUrl);
    if (!isUrl) {
      state.searchQuery = val;
      if (state.activeView !== "library") switchView("library");
      applyLibraryFilters();
    }
  });

  omniInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const val = omniInput.value.trim();
      if (val.includes("spotify.com/") || val.startsWith("spotify:")) {
        apiPost("/api/queue/add", { url: val }).then(r => {
          showToast(r.message || "Resolving Spotify URL...");
          omniInput.value = "";
          omniDlBtn.classList.add("hidden");
          omniClear.classList.add("hidden");
          switchView("queue");
        });
      }
    }
  });

  omniDlBtn.addEventListener("click", () => {
    const val = omniInput.value.trim();
    if (!val) return;
    apiPost("/api/queue/add", { url: val }).then(r => {
      showToast(r.message || "Resolving Spotify URL...");
      omniInput.value = "";
      omniDlBtn.classList.add("hidden");
      omniClear.classList.add("hidden");
      switchView("queue");
    });
  });

  omniClear.addEventListener("click", () => {
    omniInput.value = "";
    omniClear.classList.add("hidden");
    omniDlBtn.classList.add("hidden");
    state.searchQuery = "";
    applyLibraryFilters();
  });

  document.getElementById("btn-nav-home").addEventListener("click", () => {
    switchView("library");
    openCollection(null);
  });

  document.getElementById("btn-rescan-disk").addEventListener("click", async () => {
    showToast("Rescanning downloads folder...");
    await apiPost("/api/library/rescan");
    await loadLibrary(true);
    showToast("Library synced with disk!");
  });

  document.getElementById("btn-open-downloads").addEventListener("click", () => {
    apiPost("/api/shell/open", {});
  });

  // Library Hero & Subtabs
  document.getElementById("hero-play-btn").addEventListener("click", () => {
    if (state.filteredTracks.length > 0) playTrackFromList(state.filteredTracks, 0);
  });

  document.getElementById("hero-shuffle-btn").addEventListener("click", () => {
    state.shuffle = true;
    document.getElementById("btn-shuffle").classList.add("active");
    if (state.filteredTracks.length > 0) {
      const rnd = Math.floor(Math.random() * state.filteredTracks.length);
      playTrackFromList(state.filteredTracks, rnd);
    }
  });

  document.getElementById("hero-back-btn").addEventListener("click", () => openCollection(null));
  document.getElementById("hero-folder-btn").addEventListener("click", () => {
    if (state.activeCollection) apiPost("/api/shell/open", { path: state.activeCollection.folder_path });
  });

  document.getElementById("hero-rename-btn").addEventListener("click", async () => {
    if (!state.activeCollection) return;
    const newName = prompt("Enter new name for this playlist/collection:", state.activeCollection.name);
    if (newName && newName.trim() && newName.trim() !== state.activeCollection.name) {
      const r = await apiPost("/api/library/rename_collection", {
        old_name: state.activeCollection.name,
        new_name: newName.trim(),
        folder_path: state.activeCollection.folder_path,
      });
      if (r.ok) {
        showToast(`Renamed to "${newName.trim()}"`);
        await loadLibrary(true);
        openCollection(null);
      }
    }
  });

  document.getElementById("hero-m3u-btn").addEventListener("click", async () => {
    const cname = state.activeCollection ? state.activeCollection.name : "All Songs";
    const r = await apiPost("/api/library/export_m3u8", { collection_name: cname });
    if (r.ok) showToast(`Exported ${r.count} tracks to ${r.m3u_path}`);
  });

  document.querySelectorAll("#lib-subtabs .seg-tab").forEach(btn => {
    btn.addEventListener("click", () => {
      state.libSubtab = btn.dataset.subtab;
      document.querySelectorAll("#lib-subtabs .seg-tab").forEach(b => b.classList.toggle("active", b === btn));
      applyLibraryFilters();
    });
  });

  document.getElementById("lib-genre-select").addEventListener("change", (e) => {
    state.selectedGenre = e.target.value;
    applyLibraryFilters();
  });

  document.getElementById("lib-sort-select").addEventListener("change", (e) => {
    state.sortBy = e.target.value;
    applyLibraryFilters();
  });

  document.getElementById("view-scroll").addEventListener("scroll", () => {
    if (state.activeView === "library" && state.libSubtab === "tracks") {
      renderVirtualTracks();
    }
  });

  // Queue View Actions
  document.getElementById("btn-queue-download").addEventListener("click", async () => {
    const url = document.getElementById("queue-url-input").value.trim();
    if (!url) return;
    const r = await apiPost("/api/queue/add", { url, save_playlist: false });
    showToast(r.message || r.error || "Resolving...");
    document.getElementById("queue-url-input").value = "";
  });

  document.getElementById("btn-queue-save-pl").addEventListener("click", async () => {
    const url = document.getElementById("queue-url-input").value.trim();
    if (!url) return;
    const r = await apiPost("/api/queue/add", { url, save_playlist: true });
    showToast(r.message || r.error || "Saving playlist...");
    document.getElementById("queue-url-input").value = "";
  });

  document.querySelectorAll("#queue-filter-tabs .seg-tab").forEach(btn => {
    btn.addEventListener("click", () => {
      state.queueFilter = btn.dataset.qfilter;
      document.querySelectorAll("#queue-filter-tabs .seg-tab").forEach(b => b.classList.toggle("active", b === btn));
      renderQueueList();
    });
  });

  document.getElementById("btn-queue-pause").addEventListener("click", () => {
    apiPost("/api/queue/action", { action: state.isPaused ? "resume" : "pause" }).then(pollBackendState);
  });
  document.getElementById("btn-queue-retry").addEventListener("click", () => {
    apiPost("/api/queue/action", { action: "retry_failed" }).then(pollBackendState);
  });
  document.getElementById("btn-queue-clear").addEventListener("click", () => {
    apiPost("/api/queue/action", { action: "clear_completed" }).then(pollBackendState);
  });

  document.getElementById("btn-add-saved-pl").addEventListener("click", async () => {
    const url = prompt("Paste Spotify Playlist or Liked Songs URL (https://open.spotify.com/collection/tracks):");
    if (url && url.trim()) {
      await apiPost("/api/queue/add", { url: url.trim(), save_playlist: true });
      showToast("Resolving and saving playlist...");
    }
  });

  // Tools Tabs & Actions
  document.querySelectorAll("#tools-tabs .seg-tab").forEach(btn => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tooltab;
      document.querySelectorAll("#tools-tabs .seg-tab").forEach(b => b.classList.toggle("active", b === btn));
      document.getElementById("tool-panel-spectrum").classList.toggle("hidden", tab !== "spectrum");
      document.getElementById("tool-panel-duplicates").classList.toggle("hidden", tab !== "duplicates");
    });
  });

  document.getElementById("btn-run-spectrum-batch").addEventListener("click", async () => {
    await apiPost("/api/tools/spectrum/batch", { limit: 60 });
    const statusBox = document.getElementById("spectrum-batch-status");
    const tableWrap = document.getElementById("spectrum-results-table");
    statusBox.classList.remove("hidden");

    const timer = setInterval(async () => {
      const st = await apiGet("/api/tools/spectrum/status");
      statusBox.textContent = `Auditing library spectrum: ${st.progress} / ${st.total} tracks analyzed...`;
      tableWrap.innerHTML = (st.results || []).map(r => `
        <div class="track-row" style="grid-template-columns: 1fr 120px 130px 140px;">
          <div class="row-title-text">${escapeHtml(r.title)} <span style="color:var(--text-secondary); font-weight:400;">— ${escapeHtml(r.artist)}</span></div>
          <div><span class="q-badge melobot">${escapeHtml(r.quality_badge)}</span></div>
          <div style="font-family:var(--font-mono);">${r.cutoff_khz} kHz</div>
          <div>
            <span class="q-badge ${r.verdict === "authentic" ? "melobot" : "flac"}">
              ${r.verdict === "authentic" ? "✓ Authentic" : `⚠ ${escapeHtml(r.verdict)}`}
            </span>
          </div>
        </div>
      `).join("");
      if (!st.scanning) {
        clearInterval(timer);
        statusBox.textContent = `Audit complete: ${st.results.length} tracks analyzed.`;
      }
    }, 900);
  });

  document.getElementById("btn-scan-duplicates").addEventListener("click", async () => {
    const useFp = document.getElementById("chk-dup-fingerprint").checked;
    const sumEl = document.getElementById("duplicates-summary");
    const listEl = document.getElementById("duplicates-list");
    sumEl.textContent = "Scanning library for duplicates...";
    const res = await apiPost("/api/tools/duplicates/scan", { use_acoustic_fingerprint: useFp });
    if (!res || !res.ok) return;

    sumEl.innerHTML = `Found <strong>${res.total_groups}</strong> duplicate clusters • Reclaimable space: <strong style="color:var(--spotify-bright);">${res.total_reclaimable_str}</strong>`;
    document.getElementById("btn-hardlink-duplicates").classList.toggle("hidden", res.total_groups === 0);
    document.getElementById("btn-merge-duplicates").classList.toggle("hidden", res.total_groups === 0);

    listEl.innerHTML = (res.groups || []).map(g => `
      <div style="background:#121212; padding:12px 16px; border-radius:8px; margin-top:8px; border:1px solid rgba(255,255,255,0.06);">
        <div style="font-weight:700; color:var(--spotify-bright);">Primary: ${escapeHtml(g.primary.title)} — ${escapeHtml(g.primary.artist)} (${g.primary.size_str})</div>
        <div style="font-size:12px; color:var(--text-secondary); margin-top:4px;">
          ${g.duplicates.map(d => `Duplicate: ${escapeHtml(d.file_path)} (${d.size_str})`).join("<br/>")}
        </div>
      </div>
    `).join("");
  });

  document.getElementById("btn-hardlink-duplicates").addEventListener("click", async () => {
    const useFp = document.getElementById("chk-dup-fingerprint").checked;
    const res = await apiPost("/api/tools/duplicates/merge", { mode: "hardlink", use_acoustic_fingerprint: useFp });
    if (res && res.ok) {
      showToast(`Hard-linked ${res.stats.files_merged} duplicates (Saved ${res.stats.bytes_saved_str})`);
      document.getElementById("btn-scan-duplicates").click();
    }
  });

  document.getElementById("btn-merge-duplicates").addEventListener("click", async () => {
    if (!confirm("Clean Merge will remove lower-quality duplicate files and point all playlists to the highest-quality primary file. Continue?")) return;
    const useFp = document.getElementById("chk-dup-fingerprint").checked;
    const res = await apiPost("/api/tools/duplicates/merge", { mode: "merge", use_acoustic_fingerprint: useFp });
    if (res && res.ok) {
      showToast(`Merged ${res.stats.files_merged} duplicates (Saved ${res.stats.bytes_saved_str})`);
      document.getElementById("btn-scan-duplicates").click();
      loadLibrary(true);
    }
  });

  // Settings Tab Navigation
  document.querySelectorAll("#settings-sub-tabs .settings-tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#settings-sub-tabs .settings-tab-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.dataset.tab;
      document.querySelectorAll(".settings-tab-panel").forEach(p => {
        p.classList.toggle("hidden", p.id !== `stab-${tab}`);
      });
    });
  });

  // Settings Actions
  document.getElementById("btn-browse-dir")?.addEventListener("click", async () => {
    const cur = document.getElementById("set-output-dir").value;
    const r = await apiPost("/api/dialog/folder", { current: cur });
    if (r && r.ok && r.path) {
      document.getElementById("set-output-dir").value = r.path;
    }
  });

  document.getElementById("btn-open-dir-explorer")?.addEventListener("click", () => {
    const p = document.getElementById("set-output-dir").value.trim();
    apiPost("/api/shell/open", { path: p });
  });

  document.getElementById("btn-save-settings")?.addEventListener("click", saveAllSettings);
  document.getElementById("btn-save-settings-top")?.addEventListener("click", saveAllSettings);

  // Musilon Actions
  document.getElementById("btn-musilon-login")?.addEventListener("click", async () => {
    const email = document.getElementById("set-musilon-email").value.trim();
    const pwd = document.getElementById("set-musilon-password").value.trim();
    if (!email || !pwd) {
      showToast("Please enter Musilon email and password.");
      return;
    }
    showToast("Logging in to Musilon...");
    const r = await apiPost("/api/auth/musilon/login", { username: email, password: pwd });
    if (r.ok) {
      showToast("Musilon authenticated successfully!");
      updateMusilonUI(r);
      const st = await apiGet("/api/auth/musilon/status");
      updateMusilonUI(st);
      if (r.cookie) document.getElementById("set-musilon-cookie").value = r.cookie;
    } else {
      showToast(`Login failed: ${r.error || "Unknown error"}`);
    }
  });

  document.getElementById("btn-musilon-test")?.addEventListener("click", async () => {
    showToast("Testing Musilon connection...");
    const r = await apiPost("/api/auth/musilon/test");
    updateMusilonUI(r);
    showToast(r.message || "Test completed.");
  });

  document.getElementById("btn-paste-musilon-cookie")?.addEventListener("click", async () => {
    let cookie = document.getElementById("set-musilon-cookie").value.trim();
    if (!cookie) {
      try {
        cookie = await navigator.clipboard.readText();
        document.getElementById("set-musilon-cookie").value = cookie;
      } catch (_) {}
    }
    if (!cookie) {
      showToast("Paste a session cookie into the input first.");
      return;
    }
    showToast("Validating session cookie...");
    const r = await apiPost("/api/auth/musilon/cookie", { cookie });
    updateMusilonUI(r);
    showToast(r.message || "Cookie updated.");
  });

  // Telegram Actions
  document.getElementById("btn-tg-send-code")?.addEventListener("click", async () => {
    const phone = document.getElementById("set-tg-phone").value.trim();
    if (!phone) {
      showToast("Enter a valid Telegram phone number.");
      return;
    }
    showToast("Sending verification code to Telegram...");
    const r = await apiPost("/api/auth/telegram/send_code", { phone });
    if (r.ok) {
      showToast("Code sent! Check your Telegram app.");
      const info = document.getElementById("telegram-info-box");
      if (info) {
        info.textContent = "Code sent! Check your official Telegram chat for the 5-digit code.";
        info.classList.remove("hidden");
      }
      document.getElementById("set-tg-code").focus();
    } else {
      showToast(`Failed to send code: ${r.error}`);
    }
  });

  document.getElementById("btn-tg-signin")?.addEventListener("click", async () => {
    const phone = document.getElementById("set-tg-phone").value.trim();
    const code = document.getElementById("set-tg-code").value.trim();
    const pwd = document.getElementById("set-tg-2fa").value.trim();
    if (!code) {
      showToast("Please enter the verification code sent to Telegram.");
      return;
    }
    showToast("Connecting to Telegram...");
    const r = await apiPost("/api/auth/telegram/sign_in", { phone, code, password: pwd });
    if (r.ok) {
      showToast("Connected to Telegram successfully!");
      const st = await apiGet("/api/auth/telegram/status");
      updateTelegramUI(st);
    } else {
      if (r.error && (r.error.toLowerCase().includes("2fa") || r.error.toLowerCase().includes("password"))) {
        document.getElementById("tg-2fa-row").style.display = "flex";
        document.getElementById("set-tg-2fa").focus();
        showToast("Two-Factor Authentication required. Enter your 2FA password.");
      } else {
        showToast(`Sign-in failed: ${r.error}`);
      }
    }
  });

  document.getElementById("btn-tg-check")?.addEventListener("click", async () => {
    const st = await apiGet("/api/auth/telegram/status");
    updateTelegramUI(st);
    showToast(st.authorized ? "Telegram is connected!" : "Telegram is disconnected.");
  });

  document.getElementById("btn-tg-logout")?.addEventListener("click", async () => {
    if (!confirm("Disconnect and log out of Telegram?")) return;
    await apiPost("/api/auth/telegram/logout");
    const st = await apiGet("/api/auth/telegram/status");
    updateTelegramUI(st);
    showToast("Logged out of Telegram.");
  });

  // Spotify Validate Action
  document.getElementById("btn-sp-validate")?.addEventListener("click", async () => {
    const cid = document.getElementById("set-sp-id").value.trim();
    const sec = document.getElementById("set-sp-secret").value.trim();
    if (!cid || !sec) {
      showToast("Enter both Spotify Client ID and Client Secret.");
      return;
    }
    showToast("Validating Spotify API keys...");
    const r = await apiPost("/api/auth/spotify/validate", { client_id: cid, client_secret: sec });
    if (r.ok) {
      showToast(r.message || "Spotify keys verified!");
      const st = await apiGet("/api/auth/spotify/status");
      updateSpotifyUI(st);
    } else {
      showToast(`Validation error: ${r.error}`);
    }
  });

  // FFmpeg Actions
  document.getElementById("btn-download-ffmpeg")?.addEventListener("click", downloadFFmpeg);

  // Maintenance Actions
  document.getElementById("btn-maint-clean")?.addEventListener("click", () => startMaintenanceJob("/api/maintenance/clean", "Clean Library & Cache"));
  document.getElementById("btn-maint-repair")?.addEventListener("click", () => startMaintenanceJob("/api/maintenance/repair", "Scan & Auto-Repair"));
  document.getElementById("btn-maint-retag")?.addEventListener("click", () => startMaintenanceJob("/api/maintenance/retag_genres", "Synchronize Genres"));
  document.getElementById("btn-maint-boost")?.addEventListener("click", () => startMaintenanceJob("/api/maintenance/boost_volume", "Volume Boost & Balance"));
  document.getElementById("btn-maint-replaygain")?.addEventListener("click", () => startMaintenanceJob("/api/maintenance/replaygain", "Calculate ReplayGain"));

  // Player Bar Transport Events
  document.getElementById("btn-play-pause").addEventListener("click", () => {
    if (!state.currentTrack && state.filteredTracks.length > 0) {
      playTrackFromList(state.filteredTracks, 0);
      return;
    }
    if (audioEl.paused) {
      ensureAudioGraph();
      audioEl.play();
    } else {
      audioEl.pause();
    }
  });

  document.getElementById("btn-next").addEventListener("click", playNext);
  document.getElementById("btn-prev").addEventListener("click", playPrev);

  document.getElementById("btn-shuffle").addEventListener("click", (e) => {
    state.shuffle = !state.shuffle;
    e.currentTarget.classList.toggle("active", state.shuffle);
    if (state.shuffle) resetShuffleBag();
    savePlayerState();
  });

  document.getElementById("btn-repeat").addEventListener("click", () => {
    state.repeatMode = state.repeatMode === "off" ? "all" : state.repeatMode === "all" ? "one" : "off";
    updateRepeatButtonUI();
    savePlayerState();
  });

  // Audio Element Listeners
  audioEl.addEventListener("play", () => {
    state.isPlaying = true;
    document.getElementById("icon-play").classList.add("hidden");
    document.getElementById("icon-pause").classList.remove("hidden");
    renderVirtualTracks();
  });

  audioEl.addEventListener("pause", () => {
    state.isPlaying = false;
    document.getElementById("icon-play").classList.remove("hidden");
    document.getElementById("icon-pause").classList.add("hidden");
    renderVirtualTracks();
  });

  audioEl.addEventListener("loadedmetadata", () => {
    if (audioEl.duration && !isNaN(audioEl.duration) && isFinite(audioEl.duration)) {
      document.getElementById("lbl-total-time").textContent = formatMs(audioEl.duration * 1000);
    }
  });

  audioEl.addEventListener("error", (e) => {
    console.warn("Audio element error:", audioEl.error);
    const src = audioEl.src;
    if (src && !src.includes("transcode=1")) {
      console.log("Attempting fallback with on-the-fly MP3 transcoding...");
      const sep = src.includes("?") ? "&" : "?";
      audioEl.src = src + sep + "transcode=1";
      audioEl.play().catch(err => console.error("Transcode fallback failed:", err));
    }
  });

  audioEl.addEventListener("ended", () => {
    if (state.repeatMode === "one") {
      audioEl.currentTime = 0;
      audioEl.play();
    } else {
      playNext();
    }
  });

  const seekSlider = document.getElementById("seek-slider");
  const seekFill = document.getElementById("seek-fill");

  audioEl.addEventListener("timeupdate", () => {
    if (!state.isSeeking && audioEl.duration) {
      const pct = (audioEl.currentTime / audioEl.duration) * 100;
      seekSlider.value = Math.round(pct * 10);
      seekFill.style.width = `${pct}%`;
      document.getElementById("lbl-curr-time").textContent = formatMs(audioEl.currentTime * 1000);
      document.getElementById("lbl-total-time").textContent = formatMs(audioEl.duration * 1000);
    }
    updateActiveLyricTicker();
  });

  seekSlider.addEventListener("input", () => {
    state.isSeeking = true;
    const pct = seekSlider.value / 10;
    seekFill.style.width = `${pct}%`;
    if (audioEl.duration) {
      document.getElementById("lbl-curr-time").textContent = formatMs((pct / 100) * audioEl.duration * 1000);
    }
  });

  seekSlider.addEventListener("change", () => {
    if (audioEl.duration) {
      audioEl.currentTime = (seekSlider.value / 1000) * audioEl.duration;
    }
    state.isSeeking = false;
  });

  // Volume Slider
  const volSlider = document.getElementById("vol-slider");
  const volFill = document.getElementById("vol-fill");
  volSlider.addEventListener("input", () => {
    const v = Number(volSlider.value);
    state.volume = v;
    audioEl.volume = v / 100;
    volFill.style.width = `${v}%`;
    savePlayerState();
  });

  document.getElementById("btn-mute").addEventListener("click", () => {
    state.isMuted = !state.isMuted;
    audioEl.muted = state.isMuted;
    volFill.style.width = state.isMuted ? "0%" : `${state.volume}%`;
    document.getElementById("btn-mute").classList.toggle("active", state.isMuted);
    savePlayerState();
  });

  // Lyrics Drawer Controls
  const toggleLyricsDrawer = () => {
    const d = document.getElementById("lyrics-drawer");
    const open = d.classList.contains("hidden");
    if (open) openLyricsDrawer();
    else {
      d.classList.add("hidden");
      document.getElementById("btn-open-lyrics").classList.remove("active");
    }
  };

  document.getElementById("btn-open-lyrics").addEventListener("click", toggleLyricsDrawer);
  document.getElementById("player-cover-wrap").addEventListener("click", toggleLyricsDrawer);
  document.getElementById("player-title").addEventListener("click", toggleLyricsDrawer);
  document.getElementById("player-lyric-ticker").addEventListener("click", toggleLyricsDrawer);
  document.getElementById("btn-close-lyrics").addEventListener("click", () => {
    document.getElementById("lyrics-drawer").classList.add("hidden");
    document.getElementById("btn-open-lyrics").classList.remove("active");
  });

  document.getElementById("btn-cycle-trans").addEventListener("click", () => {
    const next = state.lyrics.transLang === "none" ? "en" : state.lyrics.transLang === "en" ? "fa" : "none";
    triggerLyricsTranslation(next);
  });

  document.querySelectorAll("#lyrics-trans-switcher .trans-pill").forEach(btn => {
    btn.addEventListener("click", () => triggerLyricsTranslation(btn.dataset.lang));
  });

  document.getElementById("btn-lyrics-sync").addEventListener("click", async () => {
    if (!state.currentTrack) return;
    showToast("Searching LRCLIB for synchronized lyrics...");
    const r = await apiPost("/api/lyrics/fetch", {
      file_path: state.currentTrack.file_path,
      title: state.currentTrack.title,
      artist: state.currentTrack.artist,
      album: state.currentTrack.album,
      duration_ms: state.currentTrack.duration_ms,
    });
    if (r && r.ok) {
      state.lyrics.synced = r.synced;
      state.lyrics.lines = r.lines || [];
      state.lyrics.rawText = r.raw_text || "";
      renderLyricsDrawerLines();
      if (state.lyrics.transLang !== "none") triggerLyricsTranslation(state.lyrics.transLang);
      showToast("Synchronized lyrics fetched & embedded!");
    } else {
      showToast(r.error || "No lyrics found on LRCLIB.");
    }
  });

  document.getElementById("btn-lyrics-copy").addEventListener("click", () => {
    const txt = state.lyrics.lines.map((l, i) => {
      const tr = state.lyrics.translated[i];
      return tr && tr !== l.text ? `${l.text}\n${tr}` : l.text;
    }).join("\n\n");
    navigator.clipboard.writeText(txt);
    showToast("Lyrics copied to clipboard!");
  });

  document.getElementById("btn-lyrics-save").addEventListener("click", async () => {
    if (!state.currentTrack || !state.lyrics.rawText) return;
    const r = await apiPost("/api/lyrics/save", {
      file_path: state.currentTrack.file_path,
      raw_text: state.lyrics.rawText,
    });
    if (r && r.ok) showToast(`Saved ${r.lrc_path}`);
  });

  // Equalizer Modal Controls
  document.getElementById("btn-open-eq").addEventListener("click", () => {
    ensureAudioGraph();
    document.getElementById("eq-modal").classList.remove("hidden");
  });

  document.getElementById("btn-close-eq").addEventListener("click", () => {
    document.getElementById("eq-modal").classList.add("hidden");
  });
  document.getElementById("btn-eq-done").addEventListener("click", () => {
    document.getElementById("eq-modal").classList.add("hidden");
  });

  document.getElementById("eq-enabled-toggle").addEventListener("change", (e) => {
    state.eq.enabled = e.target.checked;
    syncAudioGraphParams();
    saveEqState();
  });

  document.getElementById("eq-preset-select").addEventListener("change", (e) => {
    const p = e.target.value;
    if (state.eq.presets[p]) {
      state.eq.preset = p;
      state.eq.bands = state.eq.presets[p].slice();
      state.eq.enabled = true;
      document.getElementById("eq-enabled-toggle").checked = true;
      renderEqSliders();
      syncAudioGraphParams();
      saveEqState();
    }
  });

  document.getElementById("btn-eq-reset").addEventListener("click", () => {
    state.eq.preset = "Flat (Default)";
    state.eq.bands = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
    state.eq.preamp = 0;
    state.eq.bassBoost = 0;
    document.getElementById("eq-preset-select").value = "Flat (Default)";
    renderEqSliders();
    syncAudioGraphParams();
    saveEqState();
  });

  document.getElementById("eq-preamp-slider").addEventListener("input", (e) => {
    state.eq.preamp = Number(e.target.value);
    document.getElementById("lbl-eq-preamp").textContent = `${state.eq.preamp >= 0 ? "+" : ""}${state.eq.preamp.toFixed(1)} dB`;
    syncAudioGraphParams();
  });
  document.getElementById("eq-preamp-slider").addEventListener("change", saveEqState);

  document.getElementById("eq-bass-slider").addEventListener("input", (e) => {
    state.eq.bassBoost = Number(e.target.value);
    document.getElementById("lbl-eq-bass").textContent = `+${state.eq.bassBoost.toFixed(1)} dB`;
    syncAudioGraphParams();
  });
  document.getElementById("eq-bass-slider").addEventListener("change", saveEqState);

  document.getElementById("btn-eq-apply-file").addEventListener("click", async () => {
    if (!state.currentTrack) {
      showToast("Play a track first to master its audio file.");
      return;
    }
    showToast("Mastering EQ curve into audio file via FFmpeg...");
    const r = await apiPost("/api/eq/apply_file", {
      file_path: state.currentTrack.file_path,
      bands: state.eq.bands,
      preamp: state.eq.preamp,
      bass_boost: state.eq.bassBoost,
    });
    showToast(r.message || "Finished mastering file.");
  });

  // Global Keyboard Shortcuts
  document.addEventListener("keydown", (e) => {
    const tag = (e.target && e.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    if (e.code === "Space") {
      e.preventDefault();
      document.getElementById("btn-play-pause").click();
    } else if (e.code === "Escape") {
      document.getElementById("lyrics-drawer").classList.add("hidden");
      document.getElementById("eq-modal").classList.add("hidden");
    } else if (e.code === "ArrowRight") {
      if (audioEl.duration) audioEl.currentTime = Math.min(audioEl.duration, audioEl.currentTime + 5);
    } else if (e.code === "ArrowLeft") {
      if (audioEl.duration) audioEl.currentTime = Math.max(0, audioEl.currentTime - 5);
    }
  });

  // Boot Studio
  loadPlayerState();
  loadLibrary();
  loadSettings();
  initEqualizerUI();
  pollBackendState();
  setInterval(pollBackendState, 1200);
});

