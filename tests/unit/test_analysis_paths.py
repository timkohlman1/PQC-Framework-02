"""Known mount mapping never changes identity or permits fallback after tampering."""
import hashlib
from pathlib import Path
import pytest
from framework import analysis_paths as paths
from framework.timing_dataset import verify_source_inputs, DatasetError
from framework.research_report import dependency, verify_dependencies


@pytest.fixture
def locations(tmp_path, monkeypatch):
    native=tmp_path/'checkout';container=tmp_path/'docker/results'
    monkeypatch.setattr(paths,'ROOT',native)
    monkeypatch.setattr(paths,'CONTAINER_RESULTS',container)
    local=native/'results/run/manifest.json';local.parent.mkdir(parents=True)
    local.write_bytes(b'original evidence')
    recorded=container/'run/manifest.json'
    item=dict(path=str(recorded),consumed=True,size_bytes=local.stat().st_size,
              sha256=hashlib.sha256(local.read_bytes()).hexdigest())
    return local,recorded,{'inputs':[{'artifacts':[item]}]}


def test_mapping_preserves_recorded_dependency_and_verifies_bytes(locations):
    local,recorded,metadata=locations
    assert paths.result_path(recorded)==local
    verify_source_inputs(metadata)
    value=dependency(recorded)
    assert value['path']==str(recorded)
    verify_dependencies([value])
    local.write_bytes(b'changed evidence!')
    with pytest.raises(DatasetError,match='consumed input changed'):verify_source_inputs(metadata)
    with pytest.raises(ValueError,match='frozen dependency changed'):verify_dependencies([value])


def test_present_original_never_falls_back_to_matching_copy(locations):
    local,recorded,metadata=locations
    recorded.parent.mkdir(parents=True);recorded.write_bytes(b'tampered original')
    assert paths.result_path(recorded)==recorded
    with pytest.raises(DatasetError):verify_source_inputs(metadata)


@pytest.mark.parametrize('at_original',[False,True])
def test_symlinks_remain_refused(locations,at_original):
    local,recorded,metadata=locations
    if at_original:
        recorded.parent.mkdir(parents=True);recorded.symlink_to(local)
    else:
        real=local.with_name('real.json');local.rename(real);local.symlink_to(real)
    with pytest.raises(DatasetError):verify_source_inputs(metadata)
    with pytest.raises(ValueError,match='symlink'):dependency(recorded)


def test_missing_input_and_recorded_absence_are_distinct(locations):
    local,recorded,metadata=locations;local.unlink()
    with pytest.raises(DatasetError):verify_source_inputs(metadata)
    absent=dependency(recorded);assert absent['sha256'] is None
    verify_dependencies([absent]);local.write_text('later file')
    with pytest.raises(ValueError,match='frozen dependency changed'):verify_dependencies([absent])


def test_only_known_results_prefix_is_mapped(locations,tmp_path):
    local,recorded,_=locations
    assert paths.result_path(local)==local
    external=tmp_path/'other/results/run/manifest.json'
    assert paths.result_path(external)==external
    with pytest.raises(ValueError,match='traverse'):
        paths.result_path(paths.CONTAINER_RESULTS/'../secrets/key')
