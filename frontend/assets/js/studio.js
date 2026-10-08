"use strict";
let modelDefaults = {};
const $ = (id) => document.getElementById(id);
let presets = {}, aspect = "square", busy = false, latestDevice = null, statusController = null;
let currentUser = null, authMode = "login", pendingView = null, studioReady = false;

async function api(url, options = {}) {
  const response = await fetch(url, options);
  let data;
  try { data = await response.json(); }
  catch { throw Error("Máy chủ chưa dùng UI mới. Khởi động lại run.ps1 và tải lại trang."); }
  if (!response.ok) {
    if (response.status === 404 && url.startsWith("/api/auth/")) {
      throw Error("Máy chủ đang chạy phiên bản chưa có đăng nhập. Dừng AZURAI bằng Ctrl+C, chạy lại .\\run.ps1 trong E:\\AZURAI, rồi tải lại trang.");
    }
    if (response.status === 401 && !url.startsWith("/api/auth/")) {
      updateAccount(null); showView("home"); openAuth();
    }
    const detail = Array.isArray(data.detail)
      ? data.detail.map((item) => `${item.loc.at(-1)}: ${item.msg}`).join("; ") : data.detail;
    throw Error(detail || "Không thể xử lý yêu cầu.");
  }
  return data;
}

function fillSelect(id, values, previous) {
  const select = $(id);
  select.replaceChildren(...values.map((value) => {
    const item = typeof value === "string" ? {id: value, name: value} : value;
    return new Option(item.name, item.id);
  }));
  if ([...select.options].some((option) => option.value === previous)) select.value = previous;
}

function settings() {
  return {selection: $("selection").value, mode: $("mode").value,
    precision: $("precision").value, offline: $("offline").checked};
}

function updateSize() {
  const width = Number($("width").value), height = Number($("height").value);
  $("size").textContent = `${width} × ${height}`;
  $("resolutionSummary").textContent = `${width} × ${height}`;
  $("sizeHelp").textContent = `${aspect ? "" : "Tùy chỉnh · "}${width} × ${height} px · ${(width * height / 1e6).toFixed(2)} megapixel.`
    + (width * height > 512 * 512 ? " Kích thước lớn cần nhiều bộ nhớ hơn." : "");
  document.querySelectorAll("[data-aspect]").forEach((button) =>
    button.setAttribute("aria-pressed", String(button.dataset.aspect === aspect)));
}

function applyPreset() {
  if (!aspect) aspect = "square";
  const size = presets[$("resolution").value]?.[aspect];
  if (size) { $("width").value = size[0]; $("height").value = size[1]; }
  updateSize();
}

async function refreshDevice() {
  statusController?.abort();
  statusController = new AbortController();
  try {
    const data = await api("/api/device?" + new URLSearchParams(settings()), {signal: statusController.signal});
    latestDevice = data;
    const hardware = data.hardware;
    $("device").textContent = hardware.device.replace(/^NVIDIA GeForce /, "") + (hardware.cuda
      ? ` · ${hardware.vram_total_gb.toFixed(0)} GB` : "");
    $("device").parentElement.title = `${hardware.device} · RAM trống ${hardware.ram_free_gb.toFixed(1)} GB`
      + (hardware.cuda ? ` · VRAM trống ${hardware.vram_free_gb.toFixed(1)} GB` : "");
    if ($("selection").value === "Tự động" && data.selected) $("selection").options[0].text = `Tự động · ${data.selected.name}`;
    $("modelReport").textContent = data.report;
    if (!data.selected || !data.selected.ready) { $("setup").open = true; }
  } catch (error) {
    if (error.name === "AbortError") return;
    $("device").textContent = "Chưa kết nối máy xử lý";
    $("modelReport").textContent = error.message;
  }
}

async function loadOptions(initial = false) {
  const previous = settings();
  const data = await api("/api/options");
  modelDefaults = Object.fromEntries(data.models.map(model => [model.id, model.defaults || {}]));
  fillSelect("selection", data.models, previous.selection);
  fillSelect("mode", data.modes, previous.mode);
  fillSelect("precision", data.precisions, previous.precision);
  fillSelect("resolution", Object.keys(data.presets), $("resolution").value || "Tiêu chuẩn");
  presets = data.presets;
  if (initial) { $("offline").checked = data.offline; applyPreset(); }
  await refreshDevice();
}

function setBusy(value, operation = "generate") {
  busy = value;
  document.querySelectorAll("#form input, #form select, #form textarea, #form button, #machineSettings input, #machineSettings select, #machineSettings button, #saveDefaults, #resetDefaults")
    .forEach((element) => { element.disabled = value; });
  $("buttonText").textContent = value
    ? (operation === "generate" ? "Đang sáng tạo…" : "Đang chuẩn bị…") : "Tạo hình ảnh";
  if (typeof Director !== "undefined") Director.syncBusy();
}

async function monitor(id) {
  // Keep the job ID across a browser refresh so a running image can be recovered.
  const deadline = Date.now() + 3600000;
  while (Date.now() < deadline && currentUser) {
    const job = await api(`/api/jobs/${id}`);
    if (!currentUser) return;
    $("status").textContent = job.message;
    if ($("noticeDialog").open && $("noticeTitle").textContent === "Thông báo") $("noticeCopy").textContent = job.message;
    $("bar").style.width = `${Math.round(job.progress * 100)}%`;
    if (job.state === "error") {
      localStorage.removeItem("azuraiJob");
      throw Error(job.message);
    }
    if (job.state === "done") {
      localStorage.removeItem("azuraiJob");
      if (job.operation === "generate") {
        const url = `/api/images/${id}`;
        $("result").src = url;
        $("result").hidden = false;
        $("canvas").classList.add("has-image");
        $("empty").hidden = true;
        $("download").href = url;
        $("download").hidden = false;
        $("resultInfo").textContent = "Đã lưu ảnh PNG và thông số trên máy xử lý.";
        if (job.filename && $("generationProject").value) {
          try { await api(`/api/projects/${$("generationProject").value}/images`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({filename:job.filename})}); }
          catch (error) { $("status").textContent += " · " + error.message; }
        }
        if (job.creative?.brief) {
          Director.brief=job.creative.brief; Director.render();
          $("prompt").value=job.prompt; $("negative").value=job.negative; updatePromptCount();
        }
        Director.showFeedback(job.filename);
        if (job.filename) localStorage.setItem("azuraiPreview", JSON.stringify({filename:job.filename,prompt:$("prompt").value}));
      }
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }
  if (currentUser) throw Error("Yêu cầu vẫn có thể đang chạy. Tải lại trang để kết nối lại tiến độ.");
}

async function run(operation, resumeId = null) {
  if (!currentUser) { pendingView = "create"; openAuth(); return; }
  if (busy || (typeof Director !== "undefined" && Director.working)) return;
  setBusy(true, operation);
  $("progress").hidden = false;
  $("bar").style.width = "0%";
  try {
    let id = resumeId;
    if (!id) {
      if (operation === "generate") await Director.save();
      const data = settings();
      if (operation === "generate") Object.assign(data, {
        prompt: $("prompt").value, negative: $("negative").value,
        width: Number($("width").value), height: Number($("height").value),
        steps: Number($("steps").value), guidance: Number($("guidance").value), seed: Number($("seed").value),
      });
      let endpoint = `/api/${operation}`;
      if (operation === "generate") {
        endpoint = "/api/director/generate";
        delete data.prompt; delete data.negative; data.version = Director.version;
      }
      const job = await api(endpoint, {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(data)});
      id = job.id;
      localStorage.setItem("azuraiJob", JSON.stringify({id, operation}));
    }
    await monitor(id);
  } catch (error) {
    $("status").textContent = error.message === "Failed to fetch"
      ? "Mất kết nối máy xử lý. Kiểm tra run.ps1 rồi tải lại trang để kết nối lại yêu cầu." : error.message;
    if (error.message.includes("Không tìm thấy yêu cầu")) localStorage.removeItem("azuraiJob");
  } finally {
    setBusy(false);
    if (currentUser) await refreshDevice();
  }
}

document.querySelectorAll("[data-aspect]").forEach((button) => {
  button.onclick = () => { aspect = button.dataset.aspect; applyPreset(); };
});
$("resolution").onchange = applyPreset;
for (const id of ["width", "height"]) $(id).oninput = () => { aspect = null; updateSize(); };
for (const id of ["mode", "precision", "offline"]) $(id).onchange = refreshDevice;
$("selection").onchange = () => {
  const defaults = {steps: 20, guidance: 7, ...modelDefaults[$("selection").value]};
  if (defaults.steps) $("steps").value = defaults.steps;
  if (defaults.guidance) $("guidance").value = defaults.guidance;
  refreshDevice();
};
$("recommend").onclick = () => {
  if (!latestDevice) return;
  const size = latestDevice.suggested_size;
  aspect = "square";
  $("resolution").value = size === 384 ? "Nhẹ" : "Tiêu chuẩn";
  applyPreset();
};
$("refresh").onclick = () => loadOptions().catch((error) => { $("status").textContent = error.message; });
$("prepare").onclick = () => run("prepare");
$("checkpoint").onclick = () => run("checkpoint");
$("form").onsubmit = (event) => { event.preventDefault(); run("generate"); };
$("result").onload = () => {
  $("size").textContent = `${$("result").naturalWidth} × ${$("result").naturalHeight}`;
};
$("result").onerror = () => {
  $("status").textContent = "Không mở được ảnh. File có thể đã bị di chuyển hoặc xóa.";
  $("result").hidden = true; $("download").hidden = true; $("empty").hidden = false;
  $("canvas").classList.remove("has-image"); localStorage.removeItem("azuraiPreview");
};

function updatePromptCount() { $("promptCount").textContent = `${$("prompt").value.length}/${$("prompt").maxLength}`; }
$("prompt").oninput = () => {
  updatePromptCount();
};

function showLibraryImage(item) {
  showView("create");
  const url = `/api/assets/${encodeURIComponent(item.filename)}`;
  $("result").src = url;
  $("result").hidden = false;
  $("empty").hidden = true;
  $("canvas").classList.add("has-image");
  $("download").href = url;
  $("download").hidden = false;
  $("resultInfo").textContent = item.prompt || item.filename;
  Director.showFeedback(item.filename);
  if (item.creative) Director.restoreCreative(item.creative);
  localStorage.setItem("azuraiPreview", JSON.stringify(item));
  
}

async function openLibrary() {
  if (!currentUser) { pendingView = "library"; openAuth(); return; }
  showView("library");
}

document.querySelectorAll("[data-close]").forEach(button => {
  button.onclick = () => $(button.dataset.close).close();
});
document.querySelectorAll("[data-nav]").forEach(button => {
  button.onclick = () => {
    if (button.dataset.nav === "library") { openLibrary(); return; }
    if (!currentUser && button.dataset.nav !== "home") { pendingView = button.dataset.nav; openAuth(); return; }
    showView(button.dataset.nav);
    window.scrollTo({top:0,behavior:"smooth"});
    if (button.dataset.nav === "create") $("prompt").focus({preventScroll:true});
  };
});
$("imageMenu").onclick = () => navigate("projects");
$("notifications").onclick = () => {
  $("noticeTitle").textContent = "Thông báo";
  $("noticeCopy").textContent = $("status").textContent || "Sẵn sàng. Chưa có yêu cầu đang chạy.";
  $("noticeDialog").showModal();
};
$("session").onclick = () => {
  $("accountName").textContent = `Đã đăng nhập với tên ${currentUser?.username || ""}`;
  $("logoutError").textContent = "";
  $("accountDialog").showModal();
};

function showView(view) {
  view = ["create", "projects", "features", "library", "settings", "new-project", "project-assets"].includes(view) && currentUser ? view : "home";
  $("homeView").hidden = view !== "home";
  $("studioView").hidden = view !== "create";
  $("projectsView").hidden = view !== "projects";
  $("featuresView").hidden = view !== "features";
  $("libraryView").hidden = view !== "library";
  $("settingsView").hidden = view !== "settings";
  $("newProjectView").hidden = view !== "new-project";
  $("projectAssetsView").hidden = view !== "project-assets";
  document.querySelectorAll("[data-nav]").forEach(button => {
    const active = button.dataset.nav === view || (["create", "new-project"].includes(view) && button.dataset.nav === "features") || (view === "project-assets" && button.dataset.nav === "projects");
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
  });
  history.replaceState(null, "", `#${view}`);
  if (view === "home" && currentUser) loadRecent();
  if (view === "home" && currentUser && typeof loadDashboardStats === "function") loadDashboardStats();
  if (view === "features" && currentUser) loadFeatures();
  if (view === "projects" && currentUser) loadProjects();
  if (view === "project-assets" && currentUser) loadProjectAssets();
  if (view === "library" && currentUser) loadLibraryPage();
  if (view === "settings" && currentUser) updateSettingsSummary();
}

let featureApps = [], appFilter = "all";
function featureButton(feature, featured = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = featured ? `featured-app app-${feature.id}` : "app-tile";
  button.disabled = !feature.supported;
  button.setAttribute("aria-label", feature.supported ? feature.name : `${feature.name} — chưa hỗ trợ`);
  const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  icon.setAttribute("class", "icon"); icon.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", feature.id === "text-to-video" ? "#i-video" : "#i-image"); icon.append(use);
  if (featured) {
    const art = document.createElement("span"); art.className = "app-art";
    art.setAttribute("aria-hidden", "true");
    art.append(document.createElement("i"), document.createElement("i"), document.createElement("i"));
    button.append(art);
  }
  const title = document.createElement("span"); title.className = "app-name"; title.textContent = feature.name;
  const arrow = document.createElement("span"); arrow.className = "app-action";
  arrow.textContent = feature.supported ? (featured ? "Bắt đầu sáng tạo ↗" : "↗") : "Chưa hỗ trợ";
  button.append(icon, title, arrow);
  button.onclick = () => beginFeatureProject(feature);
  return button;
}
function renderFeatureApps() {
  const normalize = text => text.toLocaleLowerCase("vi").normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/đ/g, "d");
  const query = normalize($("featureSearch").value.trim());
  const matches = featureApps.filter(feature => (appFilter === "all" || feature.id === `text-to-${appFilter}`)
    && normalize(`${feature.name} ${feature.description || ""}`).includes(query));
  $("featuresGrid").replaceChildren(...matches.map(feature => featureButton(feature)));
  if (!matches.length) {
    const empty = document.createElement("div"); empty.className = "apps-empty";
    const title = document.createElement("strong"); title.textContent = "Không tìm thấy tính năng";
    const hint = document.createElement("p"); hint.textContent = "Thử từ khóa khác hoặc xem tất cả tính năng.";
    const reset = document.createElement("button"); reset.type = "button"; reset.className = "chip";
    reset.textContent = "Xem tất cả";
    reset.onclick = () => { $("featureSearch").value = ""; appFilter = "all"; renderFeatureApps(); $("featureSearch").focus(); };
    empty.append(title, hint, reset); $("featuresGrid").append(empty);
  }
  document.querySelectorAll("[data-app-filter]").forEach(button =>
    button.setAttribute("aria-pressed", String(button.dataset.appFilter === appFilter)));
}
$("featureSearch").oninput = renderFeatureApps;
document.querySelectorAll("[data-app-filter]").forEach(button => {
  button.onclick = () => { appFilter = button.dataset.appFilter; renderFeatureApps(); };
});
async function loadFeatures() {
  $("featuresGrid").textContent = "Đang quét mô hình…";
  try {
    const data = await api("/api/features");
    if (!currentUser) return;
    featureApps = data.features;
    $("featuredApps").replaceChildren(...featureApps.slice(0, 3).map(feature => featureButton(feature, true)));
    renderFeatureApps();
  } catch (error) { $("featuresGrid").textContent = error.message; }
}

function updateAccount(user) {
  currentUser = user;
  $("loginButton").hidden = Boolean(user);
  $("session").hidden = !user;
  $("deviceBadge").hidden = !user;
  $("homeGreeting").textContent = user ? `Chào ${user.username}, hôm nay bạn muốn tạo gì?` : "Đăng nhập để mở Studio.";
  if (!user) {
    if (typeof Director !== "undefined") Director.reset();
    $("homeStats").hidden = true;
    if (typeof clearWorkspace === "function") clearWorkspace();
    studioReady = false;
    statusController?.abort();
    latestDevice = null;
    $("homeRecent").replaceChildren();
    const placeholder = document.createElement("div");
    placeholder.className = "card recent-empty";
    placeholder.textContent = "Đăng nhập để khám phá prompt nổi bật.";
    $("homeRecent").append(placeholder);
  }
}

function openAuth(mode = "login") {
  authMode = mode;
  const register = mode === "register";
  $("authTitle").textContent = register ? "Bắt đầu hành trình sáng tạo" : "Chào mừng trở lại";
  $("authDescription").textContent = register ? "Tạo tài khoản cục bộ để mở AZURAI Studio." : "Đăng nhập để tiếp tục sáng tạo với AZURAI.";
  $("authSubmit").textContent = register ? "Tạo tài khoản" : "Đăng nhập";
  $("authSwitchCopy").textContent = register ? "Đã có tài khoản?" : "Chưa có tài khoản?";
  $("authSwitch").textContent = register ? "Đăng nhập" : "Tạo tài khoản";
  $("password").autocomplete = register ? "new-password" : "current-password";
  $("password").value = "";
  $("authError").textContent = "";
  if (!$("authDialog").open) $("authDialog").showModal();
  $("username").focus();
}

async function loadRecent() {
  try {
    const data = await api("/api/library");
    if (!currentUser) return;
    $("homeRecent").replaceChildren(...data.prompts.slice(0, 4).map(promptCard));
  } catch (error) { $("homeGreeting").textContent = error.message; }
}

async function initializeStudio() {
  if (studioReady) return;
  setBusy(true);
  try {
    await loadOptions(true);
    await restorePreferences();
    await loadProjects();
    await Director.load();
    if (!currentUser) return;
    studioReady = true;
    updatePromptCount();
    const preview = JSON.parse(localStorage.getItem("azuraiPreview") || "null");
    if (preview?.filename) {
      const view = location.hash.slice(1) || "home";
      showLibraryImage(preview); showView(view);
    }
    setBusy(false);
    const saved = JSON.parse(localStorage.getItem("azuraiJob") || "null");
    if (saved?.id && ["generate", "prepare", "checkpoint"].includes(saved.operation)) await run(saved.operation, saved.id);
  } catch (error) {
    $("status").textContent = error.message;
    setBusy(false);
  }
}

$("loginButton").onclick = () => openAuth();
$("authSwitch").onclick = () => openAuth(authMode === "login" ? "register" : "login");
$("authForm").onsubmit = async (event) => {
  event.preventDefault();
  $("authSubmit").disabled = true; $("authSwitch").disabled = true;
  $("authError").textContent = "";
  try {
    const data = await api(`/api/auth/${authMode}`, {method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({username:$("username").value, password:$("password").value})});
    updateAccount(data.user);
    $("password").value = ""; $("authDialog").close();
    await initializeStudio();
    if (currentUser) {
      if (pendingView === "library") { showView("home"); await openLibrary(); }
      else if (pendingView === "settings") { showView("settings"); }
      else showView(pendingView || "home");
    }
    pendingView = null;
  } catch (error) { $("authError").textContent = error.message; }
  finally { $("authSubmit").disabled = false; $("authSwitch").disabled = false; }
};
$("logoutButton").onclick = async () => {
  $("logoutButton").disabled = true;
  try {
    await api("/api/auth/logout", {method:"POST"});
    $("accountDialog").close();
    
    localStorage.removeItem("azuraiPreview"); localStorage.removeItem("azuraiJob");
    $("result").removeAttribute("src"); $("result").hidden = true;
    $("download").hidden = true; $("empty").hidden = false;
    $("canvas").classList.remove("has-image");
    $("prompt").value = ""; updatePromptCount();
    updateAccount(null); showView("home");
  } catch (error) { $("logoutError").textContent = error.message; }
  finally { $("logoutButton").disabled = false; }
};
$("startCreating").onclick = () => {
  if (!currentUser) { pendingView = "create"; openAuth(); }
  else { showView("create"); $("prompt").focus(); }
};
$("homeLibrary").onclick = openLibrary;
$("viewAllImages").onclick = openLibrary;
window.addEventListener("hashchange", () => {
  const view = ["#create", "#projects", "#features", "#library", "#settings", "#new-project", "#project-assets"].includes(location.hash) ? location.hash.slice(1) : "home";
  if (view !== "home" && !currentUser) { pendingView = view; openAuth(); }
  showView(view);
});
window.addEventListener("DOMContentLoaded", async () => {
  const requested = ["#create", "#projects", "#features", "#library", "#settings", "#new-project", "#project-assets"].includes(location.hash) ? location.hash.slice(1) : "home";
  try {
    const data = await api("/api/auth/session"); updateAccount(data.user);
    showView(requested);
    if (currentUser) await initializeStudio();
    else if (requested !== "home") { pendingView = requested; openAuth(); }
  } catch (error) { $("homeGreeting").textContent = error.message; }
});

