# Run from repository root: python -m PyInstaller desktop/AZURAI.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH).parent
packages = ["diffusers", "transformers", "accelerate", "webview", "psycopg", "psycopg_binary"]
datas = [(str(root / name), name) for name in ("frontend", "config")]
binaries = []
hiddenimports = ["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.h11_impl",
                 "uvicorn.lifespan.on", "PIL", "torchvision", "pythonnet", "clr_loader"]
for package in packages:
    data, binary, hidden = collect_all(package)
    datas += data
    binaries += binary
    hiddenimports += hidden
for package in ("torch", "torchvision", "safetensors", "huggingface_hub", "tokenizers", "numpy", "Pillow",
                "regex", "requests", "packaging", "filelock", "tqdm", "pyyaml", "psutil"):
    datas += copy_metadata(package)
a = Analysis([str(root / "desktop_entry.py")], pathex=[str(root)], binaries=binaries,
             datas=datas, hiddenimports=hiddenimports, hookspath=[], hooksconfig={},
             runtime_hooks=[], excludes=["pytest", "IPython", "matplotlib", "tensorboard", "PyQt5", "PyQt6"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="AZURAI", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="AZURAI")
