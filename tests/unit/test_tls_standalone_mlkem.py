from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT/'scripts') not in sys.path: sys.path.insert(0,str(ROOT/'scripts'))
from framework.tls_algorithms import resolve_tls_algorithm_set

def _bundle(group, mode='pqc_tls_server_auth'):
    return {'experiment':{'mqtt':{'tls':{'mode':mode,'authentication':'server','certificate_profile':'mldsa65','server_signature_algorithm':'mldsa65','key_exchange_group':group}}}}

def test_standalone_mlkem_groups_resolve_exact_parameter_set():
    for group, flag in [('ML_KEM_512','mlkem_512'),('ML_KEM_768','mlkem_768'),('ML_KEM_1024','mlkem_1024')]:
        selected=resolve_tls_algorithm_set(_bundle(group))
        assert selected['group_name']==group
        assert selected['mlkem_standalone'] is True
        assert selected['hybrid'] is False
        assert selected[flag] is True

def test_standalone_group_rejects_hybrid_mode():
    try: resolve_tls_algorithm_set(_bundle('ML_KEM_768','pqc_hybrid_tls_server_auth'))
    except ValueError: pass
    else: raise AssertionError('standalone ML-KEM must not silently resolve as hybrid')
