"""Pinned FLUX.2 Klein Base snapshots; weights stay outside Git."""
import json
import secrets
import shutil
from pathlib import Path

from huggingface_hub import snapshot_download
from safetensors import safe_open

REPO = "black-forest-labs/FLUX.2-klein-base-4B"
REVISION = "a3b4f4849157f664bdbc776fd7453c2783562f4d"
FILES = [
    "LICENSE.md", "README.md",
    "model_index.json", "scheduler/scheduler_config.json", "transformer/config.json",
    "transformer/diffusion_pytorch_model.safetensors", "vae/config.json",
    "vae/diffusion_pytorch_model.safetensors", "text_encoder/config.json",
    "text_encoder/generation_config.json", "text_encoder/model.safetensors.index.json",
    "text_encoder/model-00001-of-00002.safetensors", "text_encoder/model-00002-of-00002.safetensors",
    "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json", "tokenizer/special_tokens_map.json",
    "tokenizer/added_tokens.json", "tokenizer/chat_template.jinja", "tokenizer/merges.txt", "tokenizer/vocab.json",
]
SAFETY_REPO = "stable-diffusion-v1-5/stable-diffusion-v1-5"
SAFETY_REVISION = "451f4fe16113bff5a5d2269ed5ad43b0592e9a14"
SAFETY_FILES = ["safety_checker/config.json", "feature_extractor/preprocessor_config.json"]
SAFETY_WEIGHTS = ["safety_checker/model.safetensors", "safety_checker/pytorch_model.bin"]


def is_flux(entry):
    return entry.get("backend") == "flux2-klein"


def missing_files(entry):
    root = Path(entry["path"])
    return [name for name in FILES if not (root / name).is_file() or not (root / name).stat().st_size]


def validate(entry):
    missing = missing_files(entry)
    if missing:
        raise ValueError("Chưa đủ bộ FLUX.2 Klein. Bấm Tải checkpoint để tải model; thiếu: " + ", ".join(missing))
    root = Path(entry["path"])
    try:
        config = json.loads((root / "model_index.json").read_text(encoding="utf-8"))
        if config.get("_class_name") != "Flux2KleinPipeline" or config.get("is_distilled", False) is not False:
            raise ValueError("Cần đúng FLUX.2 Klein Base, không phải bản distilled hoặc pipeline khác.")
        for name in FILES:
            if name.endswith(".safetensors"):
                with safe_open(root / name, framework="pt", device="cpu") as tensors:
                    if not list(tensors.keys()):
                        raise ValueError("Thành phần model rỗng: " + name)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Bộ FLUX.2 Klein không hợp lệ; hãy tải lại.") from exc


def download(entry, progress):
    target = Path(entry["path"])
    if target.exists():
        validate(entry)
        return "FLUX.2 Klein đã có. Bấm Chuẩn bị mô hình để tải bộ lọc và nạp thử."
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + "." + secrets.token_hex(4) + ".part")
    try:
        progress(0, "Đang tải FLUX.2 Klein Base 4B: transformer, VAE, text encoder và tokenizer…")
        snapshot_download(REPO, revision=REVISION, local_dir=str(temporary), allow_patterns=FILES)
        validate({**entry, "path": temporary})
        (temporary / "azurai_model.json").write_text(json.dumps({"repo": REPO, "revision": REVISION}), encoding="utf-8")
        # Local download bookkeeping is unnecessary once the validated snapshot is installed.
        shutil.rmtree(temporary / ".cache", ignore_errors=True)
        temporary.rename(target)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    progress(1, "Đã tải đầy đủ FLUX.2 Klein Base 4B.")
    return "Đã tải và kiểm tra FLUX.2 Klein. Bấm Chuẩn bị mô hình để nạp thử."


def safety_entry(entry):
    return {**entry, "config": SAFETY_REPO, "revision": SAFETY_REVISION}


def run(pipe, checker, extractor, prompt, negative, **kwargs):
    """Klein takes negative embeddings rather than SD's negative_prompt argument."""
    import numpy as np
    from types import SimpleNamespace
    from PIL import Image
    if negative.strip() and kwargs["guidance_scale"] > 1:
        kwargs["negative_prompt_embeds"] = pipe.encode_prompt(prompt=negative.strip(),
                                                               max_sequence_length=512)[0]
    result = pipe(prompt=prompt, **kwargs)
    images = np.asarray(result.images)
    if not np.isfinite(images).all():
        raise ValueError("Lỗi số học khi tạo ảnh. Chọn FP32 và thử lại.")
    pil = [Image.fromarray((np.clip(array, 0, 1) * 255).round().astype("uint8")) for array in images]
    inputs = extractor(pil, return_tensors="pt").pixel_values.to(device=checker.device, dtype=checker.dtype)
    checked, flags = checker(images=images, clip_input=inputs)
    return SimpleNamespace(images=checked, nsfw_content_detected=flags)
