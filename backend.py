"""Inference service shared by the UI and future AZURAI integrations."""
import gc
import hashlib
import importlib.metadata
import json
import secrets
import shutil
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen

import numpy as np
import psutil
import torch
from diffusers import DPMSolverMultistepScheduler, StableDiffusionPipeline
from diffusers.pipelines.stable_diffusion import StableDiffusionSafetyChecker
from huggingface_hub import hf_hub_download
from huggingface_hub.errors import HfHubHTTPError
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from safetensors import SafetensorError, safe_open
from transformers import CLIPImageProcessor

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".cache" / "huggingface"
AUTO = "Tự động"
MEMORY_MODES = [AUTO, "Tiết kiệm VRAM", "Offload theo mô-đun", "CPU"]
PRECISIONS = [AUTO, "FP32", "FP16"]
REQUIRED = ["model_index.json", "unet/config.json", "vae/config.json", "text_encoder/config.json",
            "scheduler/scheduler_config.json", "tokenizer/vocab.json", "tokenizer/merges.txt",
            "tokenizer/tokenizer_config.json", "tokenizer/special_tokens_map.json",
            "feature_extractor/preprocessor_config.json", "safety_checker/config.json"]


def hardware():
    """Query the inference host, never browser hardware."""
    ram = psutil.virtual_memory()
    info = {"ram_free_gb": ram.available / 2**30, "ram_total_gb": ram.total / 2**30,
            "cuda": torch.cuda.is_available(), "device": "CPU"}
    if info["cuda"]:
        free, total = torch.cuda.mem_get_info(0)
        info.update(device=torch.cuda.get_device_name(0), vram_free_gb=free / 2**30,
                    vram_total_gb=total / 2**30, capability=list(torch.cuda.get_device_capability(0)))
    return info


def memory_policy(info, mode=AUTO, precision=AUTO):
    if mode not in MEMORY_MODES or precision not in PRECISIONS:
        raise ValueError("Chế độ bộ nhớ hoặc precision không hợp lệ.")
    cpu = not info["cuda"] or mode == "CPU"
    # Conservative numerical fallback for Turing, based on the observed NaNs.
    dtype = "FP32" if cpu or info.get("capability") == [7, 5] else "FP16"
    if precision != AUTO and not cpu:
        dtype = precision
    if mode == AUTO:
        threshold = 8 if dtype == "FP32" else 6
        mode = "CPU" if cpu else (
            "Offload theo mô-đun" if info["vram_free_gb"] >= threshold else "Tiết kiệm VRAM")
    elif cpu:
        mode = "CPU"
    reasons = [f"RAM còn trống {info['ram_free_gb']:.1f}/{info['ram_total_gb']:.1f} GB."]
    if cpu:
        reasons.append("Dùng CPU vì không có CUDA hoặc bạn đã chọn CPU.")
    else:
        reasons.append(f"VRAM còn trống {info['vram_free_gb']:.1f}/{info['vram_total_gb']:.1f} GB; chọn {mode}.")
    reasons.append(f"Precision: {dtype}" + (
        " (mặc định thận trọng trên compute capability 7.5 để tránh lỗi FP16 đã gặp)."
        if precision == AUTO and not cpu and info.get("capability") == [7, 5] else "."))
    size = 384 if info["ram_free_gb"] < 2 or (not cpu and info["vram_free_gb"] < 2) else 512
    reasons.append(f"Gợi ý {size}×{size}; đây là ước lượng, bộ nhớ còn phụ thuộc prompt, steps và tiến trình khác.")
    return {"mode": mode, "precision": dtype, "size": size, "reason": " ".join(reasons)}


def validate_checkpoint(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"Chưa có checkpoint: {path}. Đặt file tại vị trí này hoặc bấm Tải checkpoint.")
    with safe_open(path, framework="pt", device="cpu") as tensors:
        shapes = {"model.diffusion_model.input_blocks.0.0.weight": [320, 4, 3, 3],
                  "cond_stage_model.transformer.text_model.embeddings.token_embedding.weight": [49408, 768]}
        for name, shape in shapes.items():
            if name not in tensors.keys() or tensors.get_slice(name).get_shape() != shape:  # noqa: SIM118
                raise ValueError("Checkpoint không đúng kiến trúc SD1.5 text-to-image được hỗ trợ.")
        if "first_stage_model.encoder.conv_in.weight" not in tensors.keys():  # noqa: SIM118
            raise ValueError("Checkpoint thiếu VAE.")


def file_hash(path, progress=None):
    digest = hashlib.sha256()
    total, read = path.stat().st_size, 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024**2), b""):
            digest.update(chunk)
            read += len(chunk)
            if progress:
                progress(read / total, "Đang tính SHA-256 checkpoint…")
    return digest.hexdigest()


class InferenceService:
    def __init__(self, model=None, config=None):
        self.lock = threading.RLock()
        self.pipe = None
        self.active = None
        self.hashes = {}
        self.override_model = Path(model).resolve() if model else None
        self.override_config = config

    def models(self):
        registry = json.loads((ROOT / "models.json").read_text(encoding="utf-8"))
        for entry in registry:
            entry["path"] = (ROOT / entry["path"]).resolve()
        known = {entry["path"] for entry in registry}
        candidates = sorted((ROOT / "models").rglob("*.safetensors"))
        if self.override_model:
            candidates.insert(0, self.override_model)
        for path in candidates:
            path = path.resolve()
            if path not in known:
                registry.append({"id": str(path), "name": path.name, "path": path,
                                 "config": self.override_config or registry[0]["config"]})
                known.add(path)
        if self.override_config:
            for entry in registry:
                entry["config"] = self.override_config
                entry.pop("revision", None)
        if self.override_model:
            registry.sort(key=lambda entry: entry["path"] != self.override_model)
        return registry

    def asset_path(self, entry, filename, offline=True):
        config = Path(entry["config"])
        if config.is_dir():
            path = config / filename
            if not path.is_file():
                raise FileNotFoundError(filename)
            return path
        return Path(hf_hub_download(entry["config"], filename, cache_dir=str(CACHE),
                                   local_files_only=offline, revision=entry.get("revision", "main")))

    def assets(self, entry):
        missing = []
        for filename in REQUIRED:
            try:
                self.asset_path(entry, filename)
            except (OSError, ValueError, HfHubHTTPError):
                missing.append(filename)
        weights = ["safety_checker/model.safetensors", "safety_checker/pytorch_model.bin"]
        if not any(self._has_asset(entry, name) for name in weights):
            missing.append("safety_checker/model.safetensors (hoặc pytorch_model.bin)")
        return missing

    def _has_asset(self, entry, name):
        try:
            return self.asset_path(entry, name).stat().st_size > 0
        except (OSError, ValueError, HfHubHTTPError):
            return False

    def select(self, selection=AUTO, offline=False):
        entries = self.models()
        if selection != AUTO:
            chosen = next((item for item in entries if item["id"] == selection), None)
            if chosen is None:
                raise ValueError("Mô hình không còn trong danh sách; hãy kiểm tra lại.")
            validate_checkpoint(chosen["path"])
            return chosen, "Bạn chọn mô hình thủ công."
        valid = []
        for entry in entries:
            try:
                validate_checkpoint(entry["path"])
                valid.append(entry)
            except (ValueError, OSError, SafetensorError):
                continue
        if not valid:
            raise ValueError("Chưa có checkpoint SD1.5 hợp lệ. Chọn mô hình bên dưới để xem vị trí và tải file.")
        ready = [entry for entry in valid if not self.assets(entry)]
        if offline and not ready:
            missing = ", ".join(self.assets(valid[0]))
            raise ValueError(f"Chưa đủ thành phần offline cho {valid[0].get('name', valid[0]['id'])}. Thiếu: {missing}. "
                             "Tắt offline và bấm Chuẩn bị mô hình trước.")
        return (ready or valid)[0], (
            f"Chọn SD1.5 hợp lệ đã có trên máy xử lý ({len(valid)} checkpoint hỗ trợ); "
            "ưu tiên bộ thành phần đã sẵn sàng. Các checkpoint SD1.5 dùng cùng kiến trúc; "
            "tiết kiệm bộ nhớ bằng offload và độ phân giải, không suy đoán từ dung lượng file.")

    def inspect(self, selection=AUTO, mode=AUTO, precision=AUTO, offline=False):
        info = hardware()
        policy = memory_policy(info, mode, precision)
        lines = [f"**Máy xử lý ảnh:** {info['device']} (máy chạy Python, không phải máy mở trình duyệt).",
                 policy["reason"]]
        try:
            entry, reason = self.select(selection, offline)
            missing = self.assets(entry)
            lines += [f"**Mô hình đã chọn:** {entry['name']}. {reason}", f"Vị trí checkpoint: `{entry['path']}`",
                      "**Offline:** " + ("Sẵn sàng về file; bấm Chuẩn bị mô hình để kiểm tra nạp thực tế."
                                           if not missing else "Chưa sẵn sàng. Thiếu: " + ", ".join(missing))]
        except (ValueError, OSError, SafetensorError) as exc:
            lines.append(f"**Cần chuẩn bị:** {exc}")
            if selection != AUTO:
                entry = next((e for e in self.models() if e["id"] == selection), None)
                if entry:
                    lines.append(f"Vị trí checkpoint: `{entry['path']}`")
        return "\n\n".join(lines), policy["size"]

    def unload(self):
        self.pipe, self.active = None, None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def fingerprint(self, entry, progress):
        path = entry["path"]
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        if key not in self.hashes:
            digest = file_hash(path, progress)
            if entry.get("sha256") and digest != entry["sha256"]:
                raise ValueError("SHA-256 không khớp giá trị trong models.json.")
            self.hashes[key] = digest
        return self.hashes[key]

    def load(self, entry, policy, offline, progress):
        digest = self.fingerprint(entry, progress)
        key = (digest, entry["config"], entry.get("revision", "main"), policy["mode"], policy["precision"])
        if self.pipe is not None and self.active == key:
            return self.pipe, digest
        self.unload()
        progress(0, "Đang kiểm tra/tải cấu hình và tokenizer…")
        if offline and self.assets(entry):
            raise ValueError("Thiếu thành phần offline. Tắt offline và bấm Chuẩn bị mô hình.")
        for filename in REQUIRED:
            self.asset_path(entry, filename, offline)
        # Pin all subsequent loads to the same resolved snapshot.
        config_path = self.asset_path(entry, "model_index.json", offline).parent
        dtype = torch.float32 if policy["precision"] == "FP32" else torch.float16
        progress(0.1, "Đang kiểm tra/tải bộ lọc an toàn…")
        if not any(self._has_asset(entry, name) for name in [
                "safety_checker/model.safetensors", "safety_checker/pytorch_model.bin"]):
            self.asset_path(entry, "safety_checker/model.safetensors", offline)
        checker = StableDiffusionSafetyChecker.from_pretrained(
            str(config_path), subfolder="safety_checker", dtype=dtype, local_files_only=True)
        extractor = CLIPImageProcessor.from_pretrained(
            str(config_path), subfolder="feature_extractor", local_files_only=True)
        progress(0.3, "Đang nạp checkpoint local…")
        pipe = StableDiffusionPipeline.from_single_file(
            str(entry["path"]), config=str(config_path), torch_dtype=dtype, local_files_only=True,
            safety_checker=checker, feature_extractor=extractor)
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(
            pipe.scheduler.config, algorithm_type="dpmsolver++", use_karras_sigmas=True)
        pipe.enable_attention_slicing()
        pipe.vae.enable_slicing()
        pipe.vae.enable_tiling()
        if policy["mode"] == "CPU":
            pipe.to("cpu")
        elif policy["mode"] == "Tiết kiệm VRAM":
            pipe.enable_sequential_cpu_offload(gpu_id=0)
        else:
            pipe.enable_model_cpu_offload(gpu_id=0)
        self.pipe, self.active = pipe, key
        return pipe, digest

    def prepare(self, selection, mode, precision, offline, progress):
        with self.lock:
            entry, _ = self.select(selection, offline)
            policy = memory_policy(hardware(), mode, precision)
            self.load(entry, policy, offline, progress)
            progress(1, "Mô hình đã sẵn sàng.")
            return f"Đã nạp {entry['name']}; {policy['mode']}, {policy['precision']}. Có thể tạo ảnh offline."

    def download_checkpoint(self, selection, offline, progress):
        if offline:
            raise ValueError("Đang bật offline. Tắt offline để tải checkpoint.")
        with self.lock:
            entry = next((e for e in self.models() if e["id"] == selection), None)
            if not entry or not entry.get("download_url"):
                raise ValueError("Chọn SD1.5 chính thức để tải, hoặc đặt checkpoint thủ công tại vị trí hướng dẫn.")
            target = entry["path"]
            if target.exists():
                validate_checkpoint(target)
                return "Checkpoint đã có; không tải lại. Bấm Chuẩn bị mô hình để tải thành phần bổ trợ."
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(f".{secrets.token_hex(4)}.part")
            try:
                with urlopen(entry["download_url"], timeout=60) as response, temporary.open("xb") as output:
                    total = int(response.headers.get("Content-Length", 0))
                    if total and shutil.disk_usage(target.parent).free < total + 512 * 1024**2:
                        raise ValueError("Không đủ dung lượng đĩa để tải checkpoint.")
                    received = 0
                    for chunk in iter(lambda: response.read(4 * 1024**2), b""):
                        output.write(chunk)
                        received += len(chunk)
                        progress(received / total if total else 0,
                                 f"Đang tải checkpoint: {received / 2**20:.0f} MB")
                    if total and received != total:
                        raise ValueError("Tải chưa hoàn tất; hãy thử lại.")
                validate_checkpoint(temporary)
                self.fingerprint({**entry, "path": temporary}, progress)
                temporary.rename(target)
            finally:
                temporary.unlink(missing_ok=True)
            return "Đã tải và kiểm tra cấu trúc checkpoint. Bấm Chuẩn bị mô hình để nạp thử và tải thành phần bổ trợ."

    def generate(self, prompt, negative, width, height, steps, guidance, seed,
                 selection=AUTO, mode=AUTO, precision=AUTO, offline=False, progress=lambda *_: None):
        if not prompt.strip():
            raise ValueError("Bạn hãy nhập mô tả ảnh trước.")
        for value in (width, height, steps):
            if value is None or int(value) != value:
                raise ValueError("Kích thước và steps phải là số nguyên.")
        width, height, steps = int(width), int(height), int(steps)
        if width % 64 or height % 64 or not (256 <= width <= 1024 and 256 <= height <= 1024):
            raise ValueError("Kích thước phải là bội số của 64, từ 256 đến 1024.")
        if not 1 <= steps <= 50 or not 1 <= float(guidance) <= 15:
            raise ValueError("Steps phải từ 1 đến 50; CFG từ 1 đến 15.")
        if seed is None or int(seed) != seed or not -1 <= int(seed) <= 2147483647:
            raise ValueError("Seed phải là số nguyên từ -1 đến 2147483647.")
        seed = secrets.randbelow(2147483648) if int(seed) == -1 else int(seed)
        with self.lock:
            started = time.perf_counter()
            entry, selection_reason = self.select(selection, offline)
            info = hardware()
            policy = memory_policy(info, mode, precision)
            try:
                pipe, digest = self.load(entry, policy, offline, progress)

                def on_step(pipeline, step, timestep, callback_kwargs):
                    progress((step + 1) / steps, f"Đang tạo ảnh: {step + 1}/{steps}")
                    return callback_kwargs

                with torch.inference_mode():
                    result = pipe(prompt=prompt.strip(), negative_prompt=negative.strip(), width=width,
                                  height=height, num_inference_steps=steps, guidance_scale=float(guidance),
                                  generator=torch.Generator(device="cpu").manual_seed(seed),
                                  callback_on_step_end=on_step, output_type="np")
                if result.nsfw_content_detected and any(result.nsfw_content_detected):
                    raise ValueError("Bộ lọc an toàn đã chặn ảnh. Hãy điều chỉnh prompt.")
                if not np.isfinite(result.images).all():
                    raise ValueError("Lỗi số học khi tạo ảnh. Chọn FP32 và thử lại.")
                image = Image.fromarray((result.images[0] * 255).round().astype("uint8"))
                versions = {name: importlib.metadata.version(name) for name in [
                    "torch", "diffusers", "transformers", "accelerate", "safetensors", "Pillow", "numpy"]}
                config_path = self.asset_path(entry, "model_index.json").parent
                asset_hashes = {name: file_hash(config_path / name) for name in REQUIRED}
                safety = next(config_path / name for name in ["safety_checker/model.safetensors",
                              "safety_checker/pytorch_model.bin"] if (config_path / name).is_file())
                safety_key = (str(safety), safety.stat().st_size, safety.stat().st_mtime_ns)
                if safety_key not in self.hashes:
                    self.hashes[safety_key] = file_hash(safety)
                asset_hashes[str(safety.relative_to(config_path))] = self.hashes[safety_key]
                parameters = {"schema_version": 2, "prompt": prompt.strip(), "negative_prompt": negative.strip(),
                              "width": width, "height": height, "steps": steps, "guidance": float(guidance),
                              "seed": seed, "model": entry["path"].name, "model_sha256": digest,
                              "config": entry["config"], "config_revision": config_path.name,
                              "asset_sha256": asset_hashes, "scheduler_class": type(pipe.scheduler).__name__,
                              "scheduler_config": dict(pipe.scheduler.config), "library_versions": versions,
                              "python_version": sys.version, "cuda_version": torch.version.cuda,
                              "hardware": info, "memory_mode": policy["mode"], "precision": policy["precision"],
                              "selection_reason": selection_reason + " " + policy["reason"]}
                outputs = ROOT / "outputs"
                outputs.mkdir(exist_ok=True)
                timestamp = datetime.now(timezone(timedelta(hours=7)))
                path = outputs / f"{timestamp:%Y%m%d_%H%M%S}_{seed}_{secrets.token_hex(3)}.png"
                encoded = json.dumps(parameters, ensure_ascii=False, indent=2)
                metadata = PngInfo()
                metadata.add_text("parameters", encoded)
                image.save(path, pnginfo=metadata)
                path.with_suffix(".json").write_text(encoded, encoding="utf-8")
                return str(path), str(path), (
                    f"Hoàn tất · {entry['name']} · Seed {seed} · {time.perf_counter() - started:.1f} giây\n"
                    f"{selection_reason}\n{policy['reason']}")
            except (torch.cuda.OutOfMemoryError, MemoryError) as exc:
                self.unload()
                raise ValueError("Hết bộ nhớ trên máy xử lý. Giảm xuống 384×384 hoặc 256×256, chọn Tiết kiệm VRAM; "
                                 "đóng tiến trình khác hoặc chọn mô hình nhẹ hơn nếu có. Pipeline đã được giải phóng; "
                                 "bạn có thể thử lại mà không cần khởi động lại.") from exc
