import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import torch
from safetensors.torch import save_file

from azurai import backend, flux, features


def snapshot(root):
    for name in flux.FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if name.endswith('.safetensors'):
            save_file({'test': torch.zeros(1)}, str(path))
        else:
            path.write_text('{}' if name.endswith('.json') else 'test', encoding='utf-8')
    (root / 'model_index.json').write_text(json.dumps({'_class_name': 'Flux2KleinPipeline'}))


class FluxTests(unittest.TestCase):
    def entry(self, root):
        return {'id': 'flux', 'backend': 'flux2-klein', 'path': root, 'name': 'Klein',
                'config': flux.REPO, 'revision': flux.REVISION}

    def test_download_installs_only_complete_pinned_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'klein'
            entry = self.entry(target)
            def download(repo, revision, local_dir, allow_patterns):
                self.assertEqual((repo, revision), (flux.REPO, flux.REVISION))
                self.assertNotIn('flux-2-klein-base-4b.safetensors', allow_patterns)
                snapshot(Path(local_dir))
            with patch.object(flux, 'snapshot_download', side_effect=download):
                flux.download(entry, lambda *_: None)
            flux.validate(entry)
            self.assertEqual(json.loads((target / 'azurai_model.json').read_text())['revision'], flux.REVISION)
            self.assertEqual(list(Path(directory).glob('*.part')), [])
            with patch.object(flux, 'snapshot_download') as fetch:
                flux.download(entry, lambda *_: None)
                fetch.assert_not_called()

    def test_failed_download_does_not_install_partial_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'klein'
            def partial(*args, **kwargs):
                Path(kwargs['local_dir']).mkdir()
                (Path(kwargs['local_dir']) / 'model_index.json').write_text('{}')
            with patch.object(flux, 'snapshot_download', side_effect=partial), self.assertRaises(ValueError):
                flux.download(self.entry(root), lambda *_: None)
            self.assertFalse(root.exists())
            self.assertEqual(list(Path(directory).glob('*.part')), [])

    def test_wrong_architecture_and_distilled_snapshot_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot(root)
            for config in ({'_class_name': 'StableDiffusionPipeline'},
                           {'_class_name': 'Flux2KleinPipeline', 'is_distilled': True}):
                (root / 'model_index.json').write_text(json.dumps(config))
                with self.assertRaises(ValueError):
                    flux.validate(self.entry(root))

    def test_shards_do_not_appear_as_sd15_checkpoints_or_multiple_models(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / 'models/text2img/klein'
            snapshot(bundle)
            config = root / 'config'
            config.mkdir()
            (config / 'models.json').write_text(json.dumps([{**self.entry('models/text2img/klein'), 'path': 'models/text2img/klein'}]))
            with patch.object(backend, 'ROOT', root), patch.object(backend, 'CONFIG_DIR', config), \
                 patch.object(features, 'ROOT', root), patch.object(features, 'CONFIG_DIR', config):
                self.assertEqual(len(backend.InferenceService().models()), 1)
                self.assertEqual(features.discover_features()[0]['model_count'], 1)

    def test_offline_requires_both_bundle_and_output_checker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot(root)
            service = backend.InferenceService()
            with patch.object(service, 'models', return_value=[self.entry(root)]), \
                 patch.object(service, '_has_asset', return_value=False):
                with self.assertRaisesRegex(ValueError, 'offline'):
                    service.select(offline=True)
            with patch.object(flux, 'snapshot_download') as fetch, \
                 patch.object(service, 'models', return_value=[self.entry(root)]), self.assertRaisesRegex(ValueError, 'offline'):
                service.download_checkpoint('flux', True, lambda *_: None)
            fetch.assert_not_called()

    def test_flux_policy_uses_bf16_on_ampere_and_fp32_on_cpu_or_turing(self):
        host = {'cuda': True, 'capability': [8, 6], 'ram_free_gb': 32, 'ram_total_gb': 64,
                'vram_free_gb': 8, 'vram_total_gb': 12}
        chosen = backend.memory_policy(host, backend='flux2-klein')
        self.assertEqual(chosen['precision'], 'BF16')
        self.assertEqual(chosen['mode'], 'Tiết kiệm VRAM')
        self.assertEqual(backend.memory_policy({**host, 'capability': [7, 5]}, backend='flux2-klein')['precision'], 'FP32')
        self.assertEqual(backend.memory_policy({**host, 'cuda': False}, precision='BF16', backend='flux2-klein')['precision'], 'FP32')
        with self.assertRaises(ValueError):
            backend.memory_policy({**host, 'capability': [7, 5]}, precision='BF16', backend='flux2-klein')

    def test_native_loader_keeps_flow_scheduler_and_cpu_output_filter(self):
        service = backend.InferenceService()
        pipe = Mock()
        pipe.scheduler = SimpleNamespace(config={'flow': True})
        with patch.object(service, 'fingerprint', return_value='digest'), \
             patch.object(service, 'assets', return_value=[]), patch.object(service, '_has_asset', return_value=True), \
             patch.object(service, 'asset_path', return_value=Path('/cache/safety/safety_checker/config.json')), \
             patch('diffusers.Flux2KleinPipeline.from_pretrained', return_value=pipe) as load, \
             patch.object(backend.StableDiffusionSafetyChecker, 'from_pretrained') as checker, \
             patch.object(backend.CLIPImageProcessor, 'from_pretrained'), \
             patch.object(backend.DPMSolverMultistepScheduler, 'from_config') as sd_scheduler:
            loaded, _ = service.load(self.entry(Path('/models/klein')), {'mode': 'CPU', 'precision': 'FP32'}, True, lambda *_: None)
            self.assertIs(loaded, pipe)
            self.assertTrue(load.call_args.kwargs['local_files_only'])
            self.assertEqual(load.call_args.kwargs['torch_dtype'], torch.float32)
            self.assertIs(pipe.azurai_safety_checker, checker.return_value)
            sd_scheduler.assert_not_called()
            load.reset_mock()
            service.load(self.entry(Path('/models/klein')), {'mode': 'CPU', 'precision': 'FP32'}, True, lambda *_: None)
            load.assert_not_called()

    def test_negative_embeddings_and_output_filter_are_used(self):
        pixels = np.zeros((1, 64, 64, 3), dtype=np.float32)
        pipe = Mock(return_value=SimpleNamespace(images=pixels))
        embedding = torch.zeros(1, 4, 96)
        pipe.encode_prompt.return_value = (embedding, None)
        checker = Mock(return_value=(pixels, [True]))
        checker.device, checker.dtype = 'cpu', torch.float32
        extractor = Mock(return_value=SimpleNamespace(pixel_values=torch.zeros(1, 3, 8, 8)))
        result = flux.run(pipe, checker, extractor, 'cat', 'blur', guidance_scale=4, output_type='np')
        self.assertIs(pipe.call_args.kwargs['negative_prompt_embeds'], embedding)
        self.assertNotIn('negative_prompt', pipe.call_args.kwargs)
        self.assertEqual(result.nsfw_content_detected, [True])
        checker.assert_called_once()
        pipe.reset_mock()
        flux.run(pipe, checker, extractor, 'cat', 'blur', guidance_scale=1, output_type='np')
        pipe.encode_prompt.assert_not_called()

    def test_flux_generation_saves_backend_revision_and_negative_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot(root / 'bundle')
            entry = self.entry(root / 'bundle')
            service = backend.InferenceService()
            pipe = Mock()
            pipe.scheduler = SimpleNamespace(config={'flow': True})
            host = {'cuda': False, 'ram_free_gb': 32, 'ram_total_gb': 64}
            result = SimpleNamespace(images=np.zeros((1, 256, 256, 3), dtype=np.float32), nsfw_content_detected=[False])
            with patch.object(backend, 'ROOT', root), patch.object(backend, 'hardware', return_value=host), \
                 patch.object(service, 'select', return_value=(entry, 'manual')), \
                 patch.object(service, 'load', return_value=(pipe, 'digest')), patch.object(flux, 'run', return_value=result):
                path, _, _ = service.generate('cat', 'blur', 256, 256, 2, 4, 42)
            metadata = json.loads(Path(path).with_suffix('.json').read_text())
            self.assertEqual(metadata['backend'], 'flux2-klein')
            self.assertEqual(metadata['config_revision'], flux.REVISION)
            self.assertEqual(metadata['model_sha256'], 'digest')
            self.assertEqual(metadata['negative_prompt'], 'blur')

    def test_blocked_image_is_not_exported(self):
        service = backend.InferenceService()
        host = {'cuda': False, 'ram_free_gb': 32, 'ram_total_gb': 64}
        with patch.object(backend, 'hardware', return_value=host), \
             patch.object(service, 'select', return_value=(self.entry(Path('/bundle')), 'manual')), \
             patch.object(service, 'load', return_value=(Mock(), 'digest')), \
             patch.object(flux, 'run', return_value=SimpleNamespace(nsfw_content_detected=[True])):
            with self.assertRaisesRegex(ValueError, 'chặn ảnh'):
                service.generate('cat', '', 256, 256, 2, 4, 42)

    def test_real_tiny_klein_pipeline_runs_denoising_and_decoding(self):
        from diffusers import Flux2KleinPipeline, Flux2Transformer2DModel, AutoencoderKLFlux2, FlowMatchEulerDiscreteScheduler
        from transformers import Qwen3Config, Qwen3ForCausalLM, Qwen2TokenizerFast
        from tokenizers import Tokenizer, models, pre_tokenizers
        transformer = Flux2Transformer2DModel(in_channels=128, num_layers=1, num_single_layers=1,
            num_attention_heads=2, attention_head_dim=16, joint_attention_dim=96,
            timestep_guidance_channels=16, axes_dims_rope=(4, 4, 4, 4), guidance_embeds=False)
        vae = AutoencoderKLFlux2(block_out_channels=(8, 8, 8, 8), layers_per_block=1,
                                norm_num_groups=8, mid_block_add_attention=False)
        encoder = Qwen3ForCausalLM(Qwen3Config(vocab_size=32, hidden_size=32, intermediate_size=64,
            num_hidden_layers=1, num_attention_heads=4, num_key_value_heads=2, head_dim=8))
        tokenizer = Tokenizer(models.WordLevel({'[UNK]': 0}, unk_token='[UNK]'))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        pipe = Flux2KleinPipeline(FlowMatchEulerDiscreteScheduler(use_dynamic_shifting=True), vae,
                                 encoder, Qwen2TokenizerFast(tokenizer_object=tokenizer), transformer)
        pipe.set_progress_bar_config(disable=True)
        old_threads = torch.get_num_threads()
        try:
            torch.set_num_threads(2)
            kwargs = dict(prompt_embeds=torch.zeros(1, 4, 96), negative_prompt_embeds=torch.zeros(1, 4, 96),
                          height=64, width=64, num_inference_steps=2, guidance_scale=4, output_type='np')
            one = pipe(**kwargs, generator=torch.Generator().manual_seed(42)).images
            two = pipe(**kwargs, generator=torch.Generator().manual_seed(42)).images
        finally:
            torch.set_num_threads(old_threads)
        self.assertEqual(one.shape, (1, 64, 64, 3))
        self.assertTrue(np.isfinite(one).all())
        np.testing.assert_allclose(one, two)


class FluxPackageTests(unittest.TestCase):
    def test_bundle_can_be_packaged_without_sd15_and_without_outputs(self):
        import zipfile
        from scripts import package
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config').mkdir()
            (root / 'config/models.json').write_text(json.dumps([
                {'path': 'models/missing-sd15.safetensors'},
                {'backend': 'flux2-klein', 'path': 'models/text2img/klein'}]))
            snapshot(root / 'models/text2img/klein')
            (root / 'outputs').mkdir()
            (root / 'outputs/private.png').write_bytes(b'private')
            target = root / 'package.zip'
            with patch.object(package, 'ROOT', root), patch.object(package, 'FILES', ['config/models.json']):
                package.build_archive(target)
            with zipfile.ZipFile(target) as archive:
                names = set(archive.namelist())
                self.assertIn('AZURAI/models/text2img/klein/tokenizer/chat_template.jinja', names)
                self.assertIn('AZURAI/models/text2img/klein/transformer/diffusion_pytorch_model.safetensors', names)
                self.assertFalse(any('outputs/' in name for name in names))
                self.assertIsNone(archive.testzip())

    def test_partial_bundle_is_not_packaged_as_a_working_model(self):
        from scripts import package
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config').mkdir()
            (root / 'config/models.json').write_text(json.dumps([
                {'backend': 'flux2-klein', 'path': 'models/klein'}]))
            (root / 'models/klein').mkdir(parents=True)
            with patch.object(package, 'ROOT', root), patch.object(package, 'FILES', ['config/models.json']):
                with self.assertRaises(ValueError):
                    package.build_archive(root / 'package.zip')
            self.assertFalse((root / 'package.zip').exists())


if __name__ == '__main__':
    unittest.main()
