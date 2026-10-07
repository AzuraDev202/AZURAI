"""AZURAI Studio: custom HTML interface backed by the existing inference service."""
import argparse
import json
import secrets
import threading
import time
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from safetensors import SafetensorError

from backend import (
    AUTO,
    MEMORY_MODES,
    PRECISIONS,
    ROOT,
    InferenceService,
    hardware,
    memory_policy,
)

SERVICE = InferenceService()
DEFAULT_OFFLINE = False
JOBS = {}
GUARD = threading.Lock()
ACTIVE = None
SIZE_PRESETS = {
    "Nhẹ": {"square": (384, 384), "landscape": (512, 384), "portrait": (384, 512),
             "wide": (576, 320), "tall": (320, 576)},
    "Tiêu chuẩn": {"square": (512, 512), "landscape": (768, 576), "portrait": (576, 768),
                   "wide": (768, 448), "tall": (448, 768)},
    "Cao": {"square": (768, 768), "landscape": (1024, 768), "portrait": (768, 1024),
            "wide": (1024, 576), "tall": (576, 1024)},
}
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


class Settings(BaseModel):
    selection: str = AUTO
    mode: Literal["Tự động", "Tiết kiệm VRAM", "Offload theo mô-đun", "CPU"] = AUTO
    precision: Literal["Tự động", "FP32", "FP16"] = AUTO
    offline: bool = False


class Generation(Settings):
    prompt: str = Field(min_length=1, max_length=4000)
    negative: str = Field(default="", max_length=4000)
    width: int = Field(default=512, ge=256, le=1024, multiple_of=64)
    height: int = Field(default=512, ge=256, le=1024, multiple_of=64)
    steps: int = Field(default=20, ge=1, le=50)
    guidance: float = Field(default=7, ge=1, le=15)
    seed: int = Field(default=-1, ge=-1, le=2147483647)


@app.middleware("http")
async def local_only(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.url.hostname not in ("localhost", "127.0.0.1") or (
            origin and origin != str(request.base_url).rstrip("/")):
        return JSONResponse({"detail": "Hãy truy cập giao diện AZURAI qua localhost."}, status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/")
def home():
    return FileResponse(ROOT / "index.html")


@app.get("/studio.js")
def javascript():
    return FileResponse(ROOT / "studio.js", media_type="text/javascript")


@app.get("/studio.css")
def stylesheet():
    return FileResponse(ROOT / "studio.css", media_type="text/css")


@app.get("/api/options")
def options():
    return {"models": [{"id": AUTO, "name": AUTO}] + [
        {"id": entry["id"], "name": entry["name"]} for entry in SERVICE.models()],
        "modes": MEMORY_MODES, "precisions": PRECISIONS, "presets": SIZE_PRESETS,
        "offline": DEFAULT_OFFLINE}


@app.get("/api/device")
def device(selection: str = AUTO, mode: str = AUTO, precision: str = AUTO, offline: bool = False):
    if mode not in MEMORY_MODES or precision not in PRECISIONS:
        raise HTTPException(400, "Chế độ bộ nhớ hoặc precision không hợp lệ.")
    info = hardware()
    report, suggested_size = SERVICE.inspect(selection, mode, precision, offline)
    selected = None
    try:
        entry, _ = SERVICE.select(selection, offline)
        selected = {"name": entry["name"], "path": str(entry["path"]), "ready": not SERVICE.assets(entry)}
    except (ValueError, OSError, SafetensorError) as exc:
        report += f"\n\n{exc}"
    return {"hardware": info, "policy": memory_policy(info, mode, precision), "selected": selected,
            "report": report.replace("**", "").replace("`", ""), "suggested_size": suggested_size}


def worker(job, operation, data):
    global ACTIVE

    def progress(value, message):
        with GUARD:
            JOBS[job].update(progress=max(0, min(1, float(value))), message=message)

    try:
        if operation == "generate":
            image, _, message = SERVICE.generate(**data.model_dump(), progress=progress)
        elif operation == "prepare":
            message = SERVICE.prepare(**data.model_dump(), progress=progress)
            image = None
        else:
            message = SERVICE.download_checkpoint(data.selection, data.offline, progress)
            image = None
        with GUARD:
            JOBS[job].update(state="done", path=image, filename=Path(image).name if image else None,
                             message=message, progress=1)
    except Exception as exc:  # noqa: BLE001 -- background jobs must report failures to the browser
        message = str(exc)
        if "out of memory" in message.lower() or "not enough memory" in message.lower():
            with SERVICE.lock:
                SERVICE.unload()
            message = "Máy xử lý hết bộ nhớ. Giảm kích thước ảnh và chọn Tiết kiệm VRAM, rồi thử lại."
        with GUARD:
            JOBS[job].update(state="error", message=message)
    finally:
        with GUARD:
            ACTIVE = None


def start_job(operation, data):
    global ACTIVE
    if data.selection not in [AUTO, *[entry["id"] for entry in SERVICE.models()]]:
        raise HTTPException(400, "Mô hình không còn trong danh sách. Bấm Kiểm tra lại.")
    with GUARD:
        if ACTIVE:
            raise HTTPException(409, "AZURAI đang xử lý một yêu cầu. Hãy chờ hoàn tất.")
        for key in list(JOBS):
            if time.time() - JOBS[key]["created"] > 86400:
                del JOBS[key]
        while len(JOBS) >= 32:
            del JOBS[next(iter(JOBS))]
        job = secrets.token_hex(16)
        ACTIVE = job
        JOBS[job] = {"state": "running", "progress": 0, "message": "Đang chuẩn bị mô hình…",
                     "created": time.time(), "operation": operation}
    try:
        threading.Thread(target=worker, args=(job, operation, data), daemon=True).start()
    except RuntimeError:
        with GUARD:
            ACTIVE = None
            del JOBS[job]
        raise
    return {"id": job}


@app.post("/api/generate", status_code=202)
def generate(data: Generation):
    if not data.prompt.strip():
        raise HTTPException(400, "Hãy nhập mô tả hình ảnh.")
    return start_job("generate", data)


@app.post("/api/prepare", status_code=202)
def prepare(data: Settings):
    return start_job("prepare", data)


@app.post("/api/checkpoint", status_code=202)
def checkpoint(data: Settings):
    if data.offline:
        raise HTTPException(400, "Tắt offline để tải checkpoint.")
    return start_job("checkpoint", data)


@app.get("/api/jobs/{job}")
def status(job: str):
    with GUARD:
        if job not in JOBS:
            raise HTTPException(404, "Không tìm thấy yêu cầu. Yêu cầu có thể đã hết hạn hoặc máy chủ đã khởi động lại.")
        result = JOBS[job].copy()
    result.pop("path", None)
    return result


@app.get("/api/images/{job}")
def image(job: str):
    with GUARD:
        result = JOBS.get(job, {}).copy()
    if result.get("state") != "done" or not result.get("path"):
        raise HTTPException(404, "Ảnh chưa sẵn sàng.")
    path = Path(result["path"])
    if not path.is_file():
        raise HTTPException(404, "File ảnh đã được di chuyển hoặc xóa.")
    return FileResponse(path, media_type="image/png", filename=path.name)


@app.get("/api/library")
def library():
    outputs = ROOT / "outputs"
    images = sorted(outputs.glob("*.png"), key=lambda path: path.stat().st_mtime, reverse=True)[:60]
    items = []
    for path in images:
        metadata = {}
        try:
            sidecar = path.with_suffix(".json")
            if sidecar.is_file() and sidecar.stat().st_size < 1024 * 1024:
                metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        if not isinstance(metadata, dict):
            metadata = {}
        items.append({"filename": path.name, "prompt": str(metadata.get("prompt", "")),
                      "width": metadata.get("width"), "height": metadata.get("height")})
    return {"images": items}


@app.get("/api/library/{filename}")
def library_image(filename: str):
    outputs = (ROOT / "outputs").resolve()
    path = (outputs / filename).resolve()
    if Path(filename).name != filename or not path.is_relative_to(outputs) or path.suffix.lower() != ".png" or not path.is_file():
        raise HTTPException(404, "Không tìm thấy ảnh trong thư viện.")
    return FileResponse(path, media_type="image/png", filename=path.name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--config")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()
    SERVICE = InferenceService(args.model, args.config)
    DEFAULT_OFFLINE = args.offline
    uvicorn.run(app, host="127.0.0.1", port=args.port)
