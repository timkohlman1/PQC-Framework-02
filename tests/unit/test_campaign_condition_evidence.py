from pathlib import Path
import importlib.util


REPO_ROOT = Path(__file__).resolve().parents[2]


def _experiment_module():
    path = REPO_ROOT / "scripts" / "experiment.py"
    spec = importlib.util.spec_from_file_location("pqc_experiment_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_campaign_condition_snapshot_is_copied_per_run(tmp_path: Path):
    module = _experiment_module()
    source = tmp_path / "control" / "gateway-network-degradation.log"
    source.parent.mkdir()
    source.write_text("PQC_APPLIED_STATE_BEGIN\nqdisc netem\n", encoding="utf-8")
    result_dir = tmp_path / "run"
    result_dir.mkdir()

    name = module._copy_campaign_condition_snapshot(
        source_log=source,
        result_dir=result_dir,
    )

    assert name == "gateway-network-degradation.log"
    copied = result_dir / name
    assert copied.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")

    source.write_text("mutated campaign log\n", encoding="utf-8")
    assert copied.read_text(encoding="utf-8") != source.read_text(encoding="utf-8")


def test_campaign_condition_snapshot_missing_source_is_not_fabricated(tmp_path: Path):
    module = _experiment_module()
    result_dir = tmp_path / "run"
    result_dir.mkdir()

    name = module._copy_campaign_condition_snapshot(
        source_log=tmp_path / "missing.log",
        result_dir=result_dir,
    )

    assert name is None
    assert not (result_dir / "gateway-network-degradation.log").exists()
