import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch
from safetensors import SafetensorError

from backend import AUTO, InferenceService, memory_policy


class PolicyTests(unittest.TestCase):
    def test_free_memory_changes_policy_for_same_gpu(self):
        host = {"cuda": True, "capability": [8, 6], "ram_free_gb": 8, "ram_total_gb": 16,
                "vram_total_gb": 24, "vram_free_gb": 3}
        self.assertEqual(memory_policy(host)["mode"], "Tiết kiệm VRAM")
        self.assertEqual(memory_policy({**host, "vram_free_gb": 12})["mode"], "Offload theo mô-đun")

    def test_cpu_ignores_fp16_override(self):
        host = {"cuda": False, "ram_free_gb": 8, "ram_total_gb": 16}
        chosen = memory_policy(host, precision="FP16")
        self.assertEqual((chosen["mode"], chosen["precision"]), ("CPU", "FP32"))

    def test_low_ram_recommends_smaller_image(self):
        host = {"cuda": True, "capability": [7, 5], "ram_free_gb": 1, "ram_total_gb": 8,
                "vram_total_gb": 4, "vram_free_gb": 3}
        self.assertEqual(memory_policy(host)["size"], 384)
        self.assertEqual(memory_policy(host)["precision"], "FP32")
        self.assertEqual(memory_policy(host, precision="FP16")["precision"], "FP16")


class ServiceTests(unittest.TestCase):
    def test_offline_rejects_missing_components(self):
        service = InferenceService()
        with patch.object(service, "models", return_value=[{"id": "test", "path": Path("test")}]), \
             patch("backend.validate_checkpoint"), patch.object(service, "assets", return_value=["tokenizer/vocab.json"]), \
             self.assertRaisesRegex(ValueError, "offline"):
            service.select(AUTO, offline=True)

    def test_failed_download_does_not_install_invalid_checkpoint(self):
        service = InferenceService()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.write_bytes(b"not a safetensors checkpoint")
            target = root / "model.safetensors"
            entry = {"id": "test", "path": target, "download_url": source.as_uri()}
            with patch.object(service, "models", return_value=[entry]), self.assertRaises(SafetensorError):
                service.download_checkpoint("test", False, lambda *_: None)
            self.assertFalse(target.exists())
            self.assertEqual(list(root.glob("*.part")), [])

    def test_oom_during_loading_releases_pipeline_and_suggests_recovery(self):
        service = InferenceService()
        host = {"cuda": False, "ram_free_gb": 8, "ram_total_gb": 16}
        with patch.object(service, "select", return_value=({}, "manual")), \
             patch("backend.hardware", return_value=host), \
             patch.object(service, "load", side_effect=torch.cuda.OutOfMemoryError("test")), \
             patch.object(service, "unload") as unload:
            with self.assertRaisesRegex(ValueError, "384×384"):
                service.generate("a cabin", "", 512, 512, 2, 7, 42)
            unload.assert_called_once()


if __name__ == "__main__":
    unittest.main()
