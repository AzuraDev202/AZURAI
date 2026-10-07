"""Package only explicit project files; never include generated outputs."""
import argparse
import hashlib
import json
import os
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "azurai/__init__.py", "azurai/__main__.py", "azurai/paths.py",
    "azurai/api.py", "azurai/backend.py", "azurai/auth.py", "azurai/features.py", "azurai/workspace.py",
    "frontend/index.html", "frontend/assets/css/studio.css", "frontend/assets/js/studio.js",
    "frontend/assets/js/workspace.js", "frontend/assets/js/director.js",
    "frontend/assets/css/director.css", "azurai/director.py", "azurai/data.py", "scripts/backup.py", "tests/test_director.py", "tests/test_data.py", "tests/fixtures.py",
    "frontend/assets/css/dashboard.css",
    "config/models.json", "requirements.txt", "setup.ps1", "run.ps1",
    "scripts/setup.ps1", "scripts/run.ps1", "scripts/package.py",
    "README.md", "LICENSE", ".gitignore", "tests/test_backend.py", "tests/test_api.py", "tests/test_auth.py",
]


def build_archive(destination, include_models=True, include_cache=False):
    destination = Path(destination).resolve()
    files = [ROOT / name for name in FILES]
    if include_models:
        registry = json.loads((ROOT / "config" / "models.json").read_text(encoding="utf-8"))
        for entry in registry:
            model = (ROOT / entry["path"]).resolve()
            if not model.is_relative_to(ROOT):
                raise ValueError("Checkpoint đóng gói phải nằm trong thư mục dự án.")
            files.append(model)
        files += sorted((ROOT / "models").rglob("*.safetensors"))
    if include_cache:
        files += [path for path in (ROOT / ".cache" / "huggingface").rglob("*")
                  if path.is_file() and ("snapshots" in path.parts or "refs" in path.parts)
                  and not path.name.endswith(".lock")]
    files = list(dict.fromkeys(files))
    for path in files:
        if not path.is_file():
            raise FileNotFoundError(f"Thiếu file đóng gói: {path}. Dùng --without-models nếu chỉ cần mã nguồn.")
        if destination == path:
            raise ValueError("Đích ZIP trùng với file nguồn.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".zip.part")
    if temporary.exists():
        raise FileExistsError(f"Đang có file tạm: {temporary}")
    manifest = {}
    try:
        with zipfile.ZipFile(temporary, "x", allowZip64=True) as bundle:
            for path in files:
                relative = path.relative_to(ROOT).as_posix()
                print(f"Packing {relative}", flush=True)
                digest = hashlib.sha256()
                info = zipfile.ZipInfo.from_file(path, f"AZURAI/{relative}")
                info.compress_type = zipfile.ZIP_STORED if path.suffix in {".safetensors", ".bin"} else zipfile.ZIP_DEFLATED
                with path.open("rb") as source, bundle.open(info, "w", force_zip64=True) as target:
                    for chunk in iter(lambda: source.read(8 * 1024**2), b""):
                        digest.update(chunk)
                        target.write(chunk)
                manifest[relative] = {"sha256": digest.hexdigest(), "size": path.stat().st_size}
            bundle.writestr("AZURAI/package-manifest.json", json.dumps(manifest, indent=2))
        with zipfile.ZipFile(temporary) as bundle:
            expected = {f"AZURAI/{name}" for name in manifest} | {"AZURAI/package-manifest.json"}
            if set(bundle.namelist()) != expected:
                raise ValueError("Danh sách file ZIP không khớp manifest.")
            bad = bundle.testzip()
            if bad:
                raise ValueError(f"ZIP lỗi CRC: {bad}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Created {destination} ({destination.stat().st_size / 2**30:.2f} GiB)", flush=True)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "AZURA.zip")
    parser.add_argument("--without-models", action="store_true")
    parser.add_argument("--include-cache", action="store_true", help="Include cached snapshots for offline use")
    args = parser.parse_args()
    build_archive(args.output, not args.without_models, args.include_cache)
