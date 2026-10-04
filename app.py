"""Local SD 1.5 text-to-image interface."""
import argparse
import json
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

import gradio as gr
import torch
from diffusers import DPMSolverMultistepScheduler, StableDiffusionPipeline
from diffusers.pipelines.stable_diffusion import StableDiffusionSafetyChecker
from PIL.PngImagePlugin import PngInfo
from transformers import CLIPImageProcessor

ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
LOCK = threading.Lock()
PIPE = None
ACTIVE_MODE = None
MODEL = ROOT / "v1-5-pruned-emaonly.safetensors"
CONFIG = "stable-diffusion-v1-5/stable-diffusion-v1-5"
OFFLINE = False
PROGRESS = gr.Progress()


def load_pipeline(mode):
    global PIPE, ACTIVE_MODE
    if PIPE is not None:
        if ACTIVE_MODE != mode:
            raise gr.Error("Hãy khởi động lại ứng dụng để đổi chế độ bộ nhớ.")
        return PIPE
    if not MODEL.is_file():
        raise gr.Error(f"Không tìm thấy mô hình: {MODEL}")
    cuda = torch.cuda.is_available()
    # GTX 16-series can produce NaNs with FP16; use full precision on these GPUs.
    full_precision = cuda and "GTX 16" in torch.cuda.get_device_name(0)
    dtype = torch.float16 if cuda and not full_precision else torch.float32
    cache = str(ROOT / ".cache" / "huggingface")
    checker = StableDiffusionSafetyChecker.from_pretrained(
        CONFIG, subfolder="safety_checker", torch_dtype=dtype,
        cache_dir=cache, local_files_only=OFFLINE,
    )
    extractor = CLIPImageProcessor.from_pretrained(
        CONFIG, subfolder="feature_extractor", cache_dir=cache, local_files_only=OFFLINE,
    )
    candidate = StableDiffusionPipeline.from_single_file(
        str(MODEL), config=CONFIG, torch_dtype=dtype,
        local_files_only=OFFLINE, cache_dir=cache,
        safety_checker=checker, feature_extractor=extractor,
    )
    candidate.scheduler = DPMSolverMultistepScheduler.from_config(
        candidate.scheduler.config, algorithm_type="dpmsolver++", use_karras_sigmas=True
    )
    candidate.enable_attention_slicing()
    candidate.vae.enable_slicing()
    candidate.vae.enable_tiling()
    if cuda:
        if mode == "Tiết kiệm VRAM (4 GB)":
            candidate.enable_sequential_cpu_offload()
        else:
            candidate.enable_model_cpu_offload()
    else:
        candidate.to("cpu")
    PIPE, ACTIVE_MODE = candidate, mode
    return PIPE


def generate(prompt, negative, width, height, steps, guidance, seed, mode, progress=PROGRESS):
    if not prompt.strip():
        raise gr.Error("Bạn hãy nhập mô tả ảnh trước.")
    width, height, steps = int(width), int(height), int(steps)
    if width % 64 or height % 64 or not (256 <= width <= 768 and 256 <= height <= 768):
        raise gr.Error("Kích thước phải là bội số của 64, từ 256 đến 768.")
    if not 1 <= steps <= 50 or not 1 <= float(guidance) <= 15:
        raise gr.Error("Steps phải từ 1 đến 50; CFG từ 1 đến 15.")
    if seed is None or int(seed) != seed or not -1 <= int(seed) <= 2147483647:
        raise gr.Error("Seed phải là số nguyên từ -1 đến 2147483647.")
    seed = secrets.randbelow(2147483648) if int(seed) == -1 else int(seed)
    with LOCK:
        started = time.perf_counter()
        progress(0, desc="Đang nạp mô hình; lần đầu có thể cần tải dữ liệu bổ trợ…")
        try:
            pipe = load_pipeline(mode)

            def on_step(pipeline, step, timestep, callback_kwargs):
                progress((step + 1) / steps, desc=f"Đang tạo ảnh: {step + 1}/{steps}")
                return callback_kwargs

            with torch.inference_mode():
                result = pipe(
                    prompt=prompt.strip(), negative_prompt=negative.strip(),
                    width=width, height=height, num_inference_steps=steps,
                    guidance_scale=float(guidance), generator=torch.Generator(device="cpu").manual_seed(seed),
                    callback_on_step_end=on_step,
                )
            if result.nsfw_content_detected and any(result.nsfw_content_detected):
                raise gr.Error("Bộ lọc an toàn đã chặn ảnh này. Hãy điều chỉnh prompt.")
            parameters = {"prompt": prompt.strip(), "negative_prompt": negative.strip(), "width": width,
                          "height": height, "steps": steps, "guidance": float(guidance), "seed": seed,
                          "model": MODEL.name, "scheduler": "DPM++ Karras"}
            OUTPUTS.mkdir(exist_ok=True)
            timestamp = datetime.now(timezone(timedelta(hours=7)))
            path = OUTPUTS / f"{timestamp:%Y%m%d_%H%M%S}_{seed}_{secrets.token_hex(3)}.png"
            metadata = PngInfo()
            metadata.add_text("parameters", json.dumps(parameters, ensure_ascii=False))
            result.images[0].save(path, pnginfo=metadata)
            path.with_suffix(".json").write_text(json.dumps(parameters, ensure_ascii=False, indent=2), encoding="utf-8")
            device = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
            return str(path), str(path), f"Hoàn tất · Seed: {seed} · {time.perf_counter() - started:.1f} giây · {device}"
        except torch.cuda.OutOfMemoryError as exc:
            torch.cuda.empty_cache()
            raise gr.Error("Thiếu VRAM. Khởi động lại, chọn chế độ 4 GB và kích thước 512×512 hoặc 384×384.") from exc
        except gr.Error:
            raise
        except Exception as exc:
            raise gr.Error(f"Không thể tạo ảnh: {exc}. Lần đầu cần mạng để tải cấu hình/tokenizer. Xem README.md.") from exc


def build_ui():
    device = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU (tạo ảnh chậm)"
    with gr.Blocks(title="AZURAI · SD 1.5") as demo:
        gr.Markdown(f"# AZURAI · Text to Image\nTạo ảnh với SD 1.5 trên máy của bạn. **Thiết bị:** {device}")
        with gr.Row():
            with gr.Column():
                prompt = gr.Textbox(label="Prompt — mô tả ảnh", lines=4, placeholder="A cozy cabin in a pine forest, golden sunlight, cinematic photography")
                negative = gr.Textbox(label="Negative prompt — chi tiết muốn tránh", lines=2, value="blurry, low quality, distorted, watermark, text")
                gr.Markdown("Prompt tiếng Anh thường cho kết quả tốt hơn. Bắt đầu với 512 × 512.")
                with gr.Row():
                    width = gr.Slider(256, 768, value=512, step=64, label="Chiều rộng")
                    height = gr.Slider(256, 768, value=512, step=64, label="Chiều cao")
                with gr.Accordion("Cài đặt nâng cao", open=False):
                    steps = gr.Slider(1, 50, value=20, step=1, label="Số bước lấy mẫu")
                    guidance = gr.Slider(1, 15, value=7, step=0.5, label="CFG — độ bám prompt")
                    seed = gr.Number(value=-1, precision=0, label="Seed (-1 = ngẫu nhiên)")
                    mode = gr.Radio(["Tiết kiệm VRAM (4 GB)", "Nhanh hơn (GPU ≥ 6 GB)"], value="Tiết kiệm VRAM (4 GB)", label="Chế độ bộ nhớ (chọn trước lần tạo đầu tiên)")
                button = gr.Button("Tạo ảnh", variant="primary")
                gr.Examples([["A cozy cabin in a pine forest, golden sunlight, cinematic photography"], ["A cute orange cat sitting by a window, soft light, detailed photograph"]], inputs=[prompt])
            with gr.Column():
                output = gr.Image(label="Ảnh kết quả", type="filepath", height=512)
                download = gr.File(label="Tải ảnh PNG")
                status = gr.Textbox(label="Trạng thái", interactive=False)
        button.click(generate, [prompt, negative, width, height, steps, guidance, seed, mode], [output, download, status], concurrency_limit=1)
        gr.Markdown("Ảnh và thông số được lưu trong thư mục `outputs`. Lần đầu cần mạng; những lần sau dùng dữ liệu đã cache.")
    return demo


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--config", default=CONFIG, help="Hugging Face repo hoặc thư mục cấu hình local")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()
    MODEL, CONFIG, OFFLINE = args.model.resolve(), args.config, args.offline
    build_ui().queue(max_size=8, default_concurrency_limit=1).launch(server_name="127.0.0.1", server_port=args.port, share=False)
