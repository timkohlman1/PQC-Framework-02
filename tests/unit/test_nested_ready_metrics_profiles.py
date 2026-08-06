from pathlib import Path
import importlib.util
import sys

ROOT = Path('configs/experiments/applications/ready_metrics')


def _load_cli():
    spec = importlib.util.spec_from_file_location('experiment_cli_nested', Path('scripts/experiment.py'))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_existing_mqtt_profiles_remain_validation_profiles():
    for path in Path('configs/experiments').glob('mqtt*_st67_e2e.yaml'):
        text = path.read_text(encoding='utf-8')
        assert 'application: mqtt_ready_metrics' not in text


def test_ready_metrics_profile_matrix_exists_and_selects_application():
    originals = sorted(Path('configs/experiments').glob('mqtt*_st67_e2e.yaml'))
    generated = sorted(ROOT.glob('ready_metrics_mqtt*_st67_e2e.yaml'))
    assert len(generated) == len(originals) == 15
    for path in generated:
        text = path.read_text(encoding='utf-8')
        assert 'application: mqtt_ready_metrics' in text
        assert text.startswith('id: ready_metrics_')


def test_nested_experiment_profiles_resolve_related_configs():
    cli = _load_cli()
    profile = ROOT / 'ready_metrics_mqtt_plaintext_st67_e2e.yaml'
    board, host, boot = cli.resolve_related_config_paths(profile)
    assert board == Path('configs/boards/board_a.yaml').resolve()
    assert host == Path('configs/hosts/gateway.yaml').resolve()
    assert boot == Path('configs/boot/direct_flash.yaml').resolve()


def test_nested_profile_is_included_in_build_fingerprint_inputs():
    sys.path.insert(0, str(Path("scripts").resolve()))
    from framework.fingerprint import _experiment_profile_input
    profile = ROOT / "ready_metrics_mqtt_plaintext_st67_e2e.yaml"
    assert _experiment_profile_input(Path.cwd(), "ready_metrics_mqtt_plaintext_st67_e2e") == profile.as_posix()
