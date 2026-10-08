"""Discover feature groups from model folders and the model registry."""
import json

from .paths import CONFIG_DIR, ROOT
from . import flux

GROUPS = {
    "text2img": ("text-to-image", "Text to Image", "Tạo hình ảnh từ mô tả", True),
    "text2vid": ("text-to-video", "Text to Video", "Tạo video từ mô tả", False),
}


def discover_features():
    registry = json.loads((CONFIG_DIR / "models.json").read_text(encoding="utf-8"))
    features = []
    for folder, (task, name, description, supported) in GROUPS.items():
        directory = ROOT / "models" / folder
        entries = [entry for entry in registry if entry.get("task", "text-to-image") == task]
        if not directory.is_dir() and not entries:
            continue
        bundles = [(ROOT / entry["path"]).resolve() for entry in entries if flux.is_flux(entry)]
        paths = {path.resolve() for path in directory.rglob("*.safetensors")
                 if path.is_file() and not any(path.resolve().is_relative_to(root) for root in bundles)}
        paths.update((ROOT / entry["path"]).resolve() for entry in entries if (ROOT / entry["path"]).is_file())
        paths.update(root for root in bundles if not flux.missing_files({"path": root}))
        features.append({"id": task, "name": name, "description": description,
                         "folder": f"models/{folder}", "model_count": len(paths),
                         "models": sorted(path.name for path in paths), "supported": supported,
                         "message": "Mở Studio để tạo ảnh hoặc chuẩn bị mô hình." if supported
                         else "Backend hiện chưa hỗ trợ tạo video."})
    return features

