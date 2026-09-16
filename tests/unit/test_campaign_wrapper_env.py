from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_powershell_wrapper_forwards_campaign_hardware_environment():
    source = (REPO_ROOT / "scripts" / "dev.ps1").read_text(encoding="utf-8")
    assert 'if ($env:PQC_CAMPAIGN_HW)' in source
    assert '$dockerArgs += @("-e", "PQC_CAMPAIGN_HW")' in source
    assert 'if ($env:PQC_CAMPAIGN_HW_CONFIG)' in source
    assert '$dockerArgs += @("-e", "PQC_CAMPAIGN_HW_CONFIG")' in source


def test_posix_wrapper_forwards_campaign_hardware_environment():
    source = (REPO_ROOT / "scripts" / "dev.sh").read_text(encoding="utf-8")
    assert '${PQC_CAMPAIGN_HW:-}' in source
    assert 'campaign_env_args="$campaign_env_args -e PQC_CAMPAIGN_HW"' in source
    assert '${PQC_CAMPAIGN_HW_CONFIG:-}' in source
    assert 'campaign_env_args="$campaign_env_args -e PQC_CAMPAIGN_HW_CONFIG"' in source
    assert '$campaign_env_args' in source
