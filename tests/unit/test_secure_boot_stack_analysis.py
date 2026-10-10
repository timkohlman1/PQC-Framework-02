"""Pure, hardware-independent checks for opt-in bootloader stack evidence."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from framework.secure_boot_stack_analysis import (  # noqa: E402
    StackEvidenceError, aggregate_runs, analyse_run, write_analysis,
)


def _run(tmp_path, *, status='measured', size='2048', change=None):
    root = tmp_path / 'run'
    root.mkdir()
    run_id = 'stack-run-1'
    manifest = root / 'manifest.json'
    manifest.write_text(json.dumps({'run_id': run_id,
                                    'boot_selection': {'boot_stack_profiling': True}}))
    stack = (f'PQC_SECURE_BOOT_STACK schema=1 boundary=selected_image_integrity_begin_to_verification_end '
             f'profiling_enabled=1 timing_comparable=0 measurement_status={status} '
             f'high_water_bytes={size if status == "measured" else "unavailable"} '
             f'watermark_capacity_bytes=4096 selected_image_valid=1')
    profile = 'PQC_SECURE_BOOT_PROFILE signature_algorithm=ecdsa_p256 mailbox_version=8'
    logical = (''.join(json.dumps({'context': 'secure_boot', 'text': text}) + '\n'
                       for text in (profile, stack))).encode()
    chunk = {'source': 'stm32', 'run_id': run_id, 'type': 'chunk', 'sequence': 0,
             'data_hex': logical.hex()}
    complete = {'source': 'stm32', 'run_id': run_id, 'type': 'complete',
                'chunk_count': 1, 'logical_bytes': len(logical),
                'logical_sha256': hashlib.sha256(logical).hexdigest(),
                'record_count': 2, 'overflowed': False, 'dropped_record_count': 0}
    if change:
        change(chunk, complete)
    (root / 'mqtt-reporting-raw.ndjson').write_text('\n'.join(json.dumps({'payload': msg})
                                                      for msg in (chunk, complete)) + '\n')
    return manifest


def test_valid_stack_and_separate_analysis_lineage(tmp_path):
    manifest = _run(tmp_path)
    row = analyse_run(manifest)
    assert row['stack_high_water_bytes'] == 2048
    assert row['timing_comparable'] is False
    summary = aggregate_runs([manifest])
    assert summary['profiles'][0]['measured_count'] == 1
    assert summary['profiles'][0]['median_stack_high_water_bytes'] == 2048
    before = manifest.read_bytes()
    destination = write_analysis(summary, tmp_path / 'analysis' / 'stack')
    assert destination.is_file()
    lineage = json.loads((destination.parent / 'secure_boot_stack_lineage.json').read_text())
    assert lineage['output']['sha256'] == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert manifest.read_bytes() == before


def test_unavailable_is_not_zero(tmp_path):
    manifest = _run(tmp_path, status='unavailable')
    row = analyse_run(manifest)
    assert row['stack_high_water_bytes'] is None
    summary = aggregate_runs([manifest])
    assert summary['profiles'][0]['unavailable_count'] == 1
    assert summary['profiles'][0]['median_stack_high_water_bytes'] is None


@pytest.mark.parametrize('change', [
    lambda chunk, complete: complete.update(logical_sha256='0' * 64),
    lambda chunk, complete: complete.update(chunk_count=2),
    lambda chunk, complete: chunk.update(run_id='incorrect'),
    lambda chunk, complete: complete.update(overflowed=True),
])
def test_reject_corrupt_stream(tmp_path, change):
    with pytest.raises(StackEvidenceError):
        analyse_run(_run(tmp_path, change=change))


def test_disabled_manifest_cannot_be_presented_as_measured(tmp_path):
    manifest = _run(tmp_path)
    data = json.loads(manifest.read_text())
    data['boot_selection']['boot_stack_profiling'] = False
    manifest.write_text(json.dumps(data))
    with pytest.raises(StackEvidenceError, match='does not select stack profiling'):
        analyse_run(manifest)



def test_default_off_and_profiled_campaign_separated():
    import yaml
    root = Path(__file__).resolve().parents[2]
    target = yaml.safe_load((root / 'configs/targets/stm32l4r5_wolfboot.yaml').read_text())
    regular = yaml.safe_load((root / 'configs/campaigns/secure_boot.yaml').read_text())
    profiled = yaml.safe_load((root / 'configs/campaigns/secure_boot_stack.yaml').read_text())
    assert target['profiles']['build']['build']['runtime_stack_high_water_instrumentation'] is False
    assert regular['fixed']['boot_stack_profiling'] is False
    assert profiled['fixed']['boot_stack_profiling'] is True
    assert regular['matrix']['secure_boot'] == profiled['matrix']['secure_boot']
