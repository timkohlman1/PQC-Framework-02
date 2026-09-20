from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_linux_wrapper_forwards_campaign_hardware_environment():
    source = (REPO_ROOT / "scripts" / "dev.sh").read_text(encoding="utf-8")
    assert '${PQC_CAMPAIGN_HW:-}' in source
    assert 'campaign_env_args="$campaign_env_args -e PQC_CAMPAIGN_HW"' in source
    assert '${PQC_CAMPAIGN_HW_CONFIG:-}' in source
    assert 'campaign_env_args="$campaign_env_args -e PQC_CAMPAIGN_HW_CONFIG"' in source
    assert '$campaign_env_args' in source
