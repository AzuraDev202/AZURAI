"use strict";
const $ = (id) => document.getElementById(id);
let presets = {}, aspect = "square", busy = false, latestDevice = null, statusController = null;
const examples = {
  landscape: "Mount Fuji at sunrise, a quiet lake with reflections, soft golden light, cinematic landscape photography, detailed",
  portrait: "Portrait of a young adult woman beside a window, soft natural light, realistic photography, detailed eyes",
  product: "A minimal perfume bottle on a dark stone pedestal, soft studio lighting, premium product photography",
};

async function api(url, options = {}) {
  const response = await fetch(url, options);
  let data;
  try { data = await response.json(); }
  catch { throw Error("Máy chủ chưa dùng UI mới. Khởi động lại run.ps1 và tải lại trang."); }
  if (!response.ok) {
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
    $("selectedModel").textContent = data.selected?.name || "Chưa có mô hình sẵn sàng";
    if ($("selection").value === "Tự động" && data.selected) $("selection").options[0].text = `Tự động · ${data.selected.name}`;
    $("modelReport").textContent = data.report;
    if (!data.selected || !data.selected.ready) { $("advancedSettings").open = true; $("setup").open = true; }
  } catch (error) {
    if (error.name === "AbortError") return;
    $("device").textContent = "Chưa kết nối máy xử lý";
    $("modelReport").textContent = error.message;
  }
}

async function loadOptions(initial = false) {
  const previous = settings();
  const data = await api("/api/options");
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
  document.querySelectorAll("#form input, #form select, #form textarea, #form button")
    .forEach((element) => { element.disabled = value; });
  $("buttonText").textContent = value
    ? (operation === "generate" ? "Đang sáng tạo…" : "Đang chuẩn bị…") : "Tạo hình ảnh";
}

async function monitor(id) {
  // Keep the job ID across a browser refresh so a running image can be recovered.
  const deadline = Date.now() + 3600000;
  while (Date.now() < deadline) {
    const job = await api(`/api/jobs/${id}`);
    $("status").textContent = job.message;
    if ($("noticeDialog").open && $("noticeTitle").textContent === "Trạng thái xử lý") $("noticeCopy").textContent = job.message;
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
        if (job.filename) localStorage.setItem("azuraiPreview", JSON.stringify({filename:job.filename,prompt:$("prompt").value}));
      }
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }
  throw Error("Yêu cầu vẫn có thể đang chạy. Tải lại trang để kết nối lại tiến độ.");
}

async function run(operation, resumeId = null) {
  if (busy) return;
  setBusy(true, operation);
  $("progress").hidden = false;
  $("bar").style.width = "0%";
  try {
    let id = resumeId;
    if (!id) {
      const data = settings();
      if (operation === "generate") Object.assign(data, {
        prompt: $("prompt").value, negative: $("negative").value,
        width: Number($("width").value), height: Number($("height").value),
        steps: Number($("steps").value), guidance: Number($("guidance").value), seed: Number($("seed").value),
      });
      const job = await api(`/api/${operation}`, {method: "POST", headers: {"Content-Type": "application/json"},
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
    await refreshDevice();
  }
}

document.querySelectorAll("[data-example]").forEach((button) => {
  button.onclick = () => {
    $("prompt").value = examples[button.dataset.example]; updatePromptCount(); $("prompt").focus();
    document.querySelectorAll("[data-example]").forEach(item => item.classList.toggle("selected", item === button));
  };
});
document.querySelectorAll("[data-aspect]").forEach((button) => {
  button.onclick = () => { aspect = button.dataset.aspect; applyPreset(); };
});
$("resolution").onchange = applyPreset;
for (const id of ["width", "height"]) $(id).oninput = () => { aspect = null; updateSize(); };
for (const id of ["selection", "mode", "precision", "offline"]) $(id).onchange = refreshDevice;
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
  document.querySelectorAll("[data-example]").forEach(button => button.classList.remove("selected"));
};

function showLibraryImage(item) {
  const url = `/api/library/${encodeURIComponent(item.filename)}`;
  $("result").src = url;
  $("result").hidden = false;
  $("empty").hidden = true;
  $("canvas").classList.add("has-image");
  $("download").href = url;
  $("download").hidden = false;
  $("resultInfo").textContent = item.prompt || item.filename;
  localStorage.setItem("azuraiPreview", JSON.stringify(item));
  if ($("libraryDialog").open) $("libraryDialog").close();
}

async function openLibrary() {
  $("libraryDialog").showModal();
  $("libraryGrid").textContent = "Đang tải thư viện…";
  try {
    const data = await api("/api/library");
    $("libraryGrid").replaceChildren();
    if (!data.images.length) $("libraryGrid").textContent = "Chưa có ảnh. Tạo ảnh đầu tiên để bắt đầu thư viện.";
    for (const item of data.images) {
      const button = document.createElement("button");
      button.type = "button"; button.className = "library-item";
      const image = document.createElement("img");
      image.src = `/api/library/${encodeURIComponent(item.filename)}`; image.loading = "lazy";
      image.alt = item.prompt || "Ảnh đã tạo";
      const label = document.createElement("span"); label.textContent = item.prompt || item.filename;
      button.append(image, label); button.onclick = () => showLibraryImage(item);
      $("libraryGrid").append(button);
    }
  } catch (error) { $("libraryGrid").textContent = error.message; }
}

document.querySelectorAll("[data-close]").forEach(button => {
  button.onclick = () => $(button.dataset.close).close();
});
document.querySelectorAll("[data-nav]").forEach(button => {
  button.onclick = () => {
    if (button.dataset.nav === "library") { openLibrary(); return; }
    if (button.dataset.nav === "settings") {
      $("advancedSettings").open = true;
      $("advancedSettings").scrollIntoView({behavior:"smooth", block:"center"});
      return;
    }
    document.querySelectorAll("[data-nav]").forEach(item => {
      item.classList.toggle("active", item === button);
      if (item === button) item.setAttribute("aria-current", "page"); else item.removeAttribute("aria-current");
    });
    window.scrollTo({top:0,behavior:"smooth"});
    if (button.dataset.nav === "create") $("prompt").focus({preventScroll:true});
  };
});
$("imageMenu").onclick = openLibrary;
$("notifications").onclick = () => {
  $("noticeTitle").textContent = "Trạng thái xử lý";
  $("noticeCopy").textContent = $("status").textContent || "Sẵn sàng. Chưa có yêu cầu đang chạy.";
  $("noticeDialog").showModal();
};
$("session").onclick = () => {
  $("noticeTitle").textContent = "Phiên làm việc cục bộ";
  $("noticeCopy").textContent = latestDevice?.report || "Đang kiểm tra máy xử lý…";
  $("noticeDialog").showModal();
};

(async () => {
  setBusy(true);
  try {
    await loadOptions(true);
    updatePromptCount();
    const preview = JSON.parse(localStorage.getItem("azuraiPreview") || "null");
    if (preview?.filename) showLibraryImage(preview);
    setBusy(false);
    const saved = JSON.parse(localStorage.getItem("azuraiJob") || "null");
    if (saved?.id && ["generate", "prepare", "checkpoint"].includes(saved.operation)) await run(saved.operation, saved.id);
  } catch (error) {
    $("status").textContent = error.message;
    setBusy(false);
  }
})();
