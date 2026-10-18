"""Optional application TLS controls; omitted fields retain historical identities.

These are application wolfSSL settings, never wolfBoot settings. ML-DSA keys
are provisioned, so key-generation tuning has no operation to measure here.
"""
DEFAULTS = dict(tls_small_stack=True, tls_task_stack_bytes=8192, tls_heap_bytes=98304,
    mlkem_small_code=False, mlkem_makekey_small_mem=True,
    mlkem_encapsulate_small_mem=False, mldsa_small_code=False)
OPTIONS = {key: [False, True] for key in DEFAULTS if type(DEFAULTS[key]) is bool}
OPTIONS['tls_task_stack_bytes'] = [8192, 49152, 65536]
OPTIONS['tls_heap_bytes'] = [98304, 131072]
LABELS = dict(tls_small_stack='TLS small-stack implementation',
    tls_task_stack_bytes='TLS task stack allocation (bytes)',
    tls_heap_bytes='Application FreeRTOS heap reservation (bytes)',
    mlkem_small_code='ML-KEM small-code implementation',
    mlkem_makekey_small_mem='ML-KEM small-memory key generation',
    mlkem_encapsulate_small_mem='ML-KEM small-memory encapsulation / decapsulation',
    mldsa_small_code='ML-DSA small-code implementation')
MACROS = dict(tls_small_stack='PQC_TLS_SMALL_STACK',
    tls_task_stack_bytes='PQC_TLS_TASK_STACK_BYTES',
    tls_heap_bytes='PQC_TLS_HEAP_BYTES',
    mlkem_small_code='PQC_MLKEM_SMALL_CODE',
    mlkem_makekey_small_mem='PQC_MLKEM_MAKEKEY_SMALL_MEM',
    mlkem_encapsulate_small_mem='PQC_MLKEM_ENCAPSULATE_SMALL_MEM',
    mldsa_small_code='PQC_MLDSA_SMALL_CODE')


def applicable(key, *, transport='tls', mlkem=False, mldsa=False):
    return transport == 'tls' and (mlkem if key.startswith('mlkem_') else
                                  mldsa if key.startswith('mldsa_') else True)


def resolve(choices, *, transport='tls', mlkem=False, mldsa=False, application=True):
    values = {key: choices.get(key, default) for key, default in DEFAULTS.items()}
    for key, value in values.items():
        if type(value) is not type(DEFAULTS[key]) or value not in OPTIONS[key]:
            raise ValueError(f'{key} must be one of {OPTIONS[key]}')
        if key in choices and (not application or not applicable(key, transport=transport, mlkem=mlkem, mldsa=mldsa)):
            raise ValueError(f'{key} requires the corresponding application TLS operation')
    # Disabling small-stack moves substantial temporary arrays back to the task
    # stack. This validation floor is not proof that every configuration fits.
    if not values['tls_small_stack'] and values['tls_task_stack_bytes'] < 49152:
        raise ValueError('tls_small_stack=false requires tls_task_stack_bytes >= 49152; hold this allocation fixed in an A/B stack-option comparison')
    if values['tls_task_stack_bytes'] >= 49152 and values['tls_heap_bytes'] < 131072:
        raise ValueError('large TLS task stacks require tls_heap_bytes=131072; the stack is allocated inside this shared pool')
    return values


def cmake(values):
    return ''.join(f'set({MACROS[key]} {("ON" if value else "OFF") if type(value) is bool else value})\n'
                   for key, value in values.items())
