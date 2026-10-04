"""Human-readable diagnostics only; never used to accept evidence."""
import json
from pathlib import Path


def run_failure(path, return_code):
    parts = [f"Runtime command exited {return_code}"]
    try:
        data = json.loads(Path(path).read_text())
        stage = (data.get('execution_outcome') or {}).get('failure_stage') or (data.get('run') or {}).get('failure_stage')
        if stage:
            parts.append(str(stage).replace('_', ' '))
        for section, key in [('energy_capture', 'failure_reasons'), ('capture_acceptance', 'reasons')]:
            reasons = (data.get(section) or {}).get(key) or []
            parts.extend(str(reason) for reason in reasons[:3])
    except (OSError, ValueError, TypeError, AttributeError):
        parts.append('run manifest missing or unreadable')
    return '; '.join(dict.fromkeys(parts))


def campaign_failure(data):
    """Prefer the cause of stopping, then the latest retained failed slot."""
    cleanup = data.get('cleanup') or {}
    if cleanup.get('errors'):
        return 'Cleanup failed: ' + '; '.join(map(str, cleanup['errors']))
    if (data.get('failure') or {}).get('message'):
        return str(data['failure']['message'])
    for run in reversed(data.get('runs', [])):
        if run.get('state') in {'failed', 'blocked'}:
            failure = run.get('failure') or {}
            reason = failure.get('message') or failure.get('stage') or 'failure reason unavailable in retained evidence'
            return f"{run.get('case_id', 'Run')} #{run.get('repetition_index', '?')}: {reason}"
    return ''
