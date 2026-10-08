"""Separate packaged resources from writable desktop data."""
import os
import sys
from pathlib import Path

RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
if getattr(sys, "frozen", False):
    default_root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AZURAI"
else:
    default_root = RESOURCE_ROOT
ROOT = Path(os.environ.get("AZURAI_DATA_DIR", default_root)).expanduser().resolve()
CONFIG_DIR = ROOT / "config"
FRONTEND_DIR = RESOURCE_ROOT / "frontend"
