from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_tls_handshake_boundary_defers_diagnostics_until_after_connect():
    source = read("Core/Src/pqc_wolfmqtt_build_only.c")

    begin = source.index("PQC_TLS_InstrumentationBegin(PQC_TLS_EVENT_HANDSHAKE);")
    connect = source.index("result = wolfSSL_connect(socket_context->tls);", begin)
    end = source.index("PQC_TLS_InstrumentationEnd(PQC_TLS_EVENT_HANDSHAKE, result);", connect)
    report = source.index("PQC_TLS_InstrumentationReport(", end)

    critical = source[begin:end]
    assert begin < connect < end < report
    assert "PQC_WolfMQTT_DiagnosticMarker" not in critical
    assert "snprintf" not in critical
    assert "uxTaskGetStackHighWaterMark" not in critical
    assert "xPortGetFreeHeapSize" not in critical
    assert "xPortGetMinimumEverFreeHeapSize" not in critical


def test_stack_and_heap_measurements_bracket_but_do_not_enter_handshake():
    source = read("Core/Src/pqc_wolfmqtt_build_only.c")

    pre_stack = source.index("stack_before_words = uxTaskGetStackHighWaterMark(NULL);")
    begin = source.index("PQC_TLS_InstrumentationBegin(PQC_TLS_EVENT_HANDSHAKE);")
    end = source.index("PQC_TLS_InstrumentationEnd(PQC_TLS_EVENT_HANDSHAKE, result);")
    post_stack = source.index("stack_after_words = uxTaskGetStackHighWaterMark(NULL);", end)

    assert pre_stack < begin < end < post_stack


def test_tls13_phase_hooks_cover_requested_receive_transitions():
    source = read("Middlewares/Third_Party/wolfSSL/src/tls13.c")

    for phase in (
        "PQC_TLS_PHASE_SERVER_HELLO",
        "PQC_TLS_PHASE_ENCRYPTED_EXTENSIONS",
        "PQC_TLS_PHASE_CERTIFICATE",
        "PQC_TLS_PHASE_CERTIFICATE_VERIFY",
        "PQC_TLS_PHASE_FINISHED",
    ):
        assert f"PQC_TLS_InstrumentationBegin({phase})" in source
        assert f"PQC_TLS_InstrumentationEnd({phase}, ret)" in source


def test_crypto_hooks_cover_selected_tls_primitives():
    internal = read("Middlewares/Third_Party/wolfSSL/src/internal.c")
    tls = read("Middlewares/Third_Party/wolfSSL/src/tls.c")
    kdf = read("Middlewares/Third_Party/wolfSSL/wolfcrypt/src/kdf.c")
    sha = read("Middlewares/Third_Party/wolfSSL/wolfcrypt/src/sha256.c")
    sha384 = read("Middlewares/Third_Party/wolfSSL/wolfcrypt/src/sha512.c")

    assert "PQC_TLS_PRIMITIVE_P256_KEYGEN" in internal
    assert "PQC_TLS_PRIMITIVE_P256_SHARED_SECRET" in internal
    assert "PQC_TLS_PRIMITIVE_RSA_VERIFY" in internal
    assert "PQC_TLS_PRIMITIVE_X509_VERIFY" in internal
    assert "PQC_TLS_PRIMITIVE_MLKEM512_KEYGEN" in tls
    assert "PQC_TLS_PRIMITIVE_MLKEM512_DECAPSULATE" in tls
    assert "PQC_TLS_PRIMITIVE_MLKEM768_KEYGEN" in tls
    assert "PQC_TLS_PRIMITIVE_MLKEM768_DECAPSULATE" in tls
    assert "PQC_TLS_PRIMITIVE_HKDF_EXTRACT" in kdf
    assert "PQC_TLS_PRIMITIVE_HKDF_EXPAND" in kdf
    assert "PQC_TLS_PRIMITIVE_SHA256" in sha
    assert "PQC_TLS_PRIMITIVE_SHA384" in sha384



def test_rsa_verify_instrumentation_covers_pss_and_pkcs1_software_paths():
    internal = read("Middlewares/Third_Party/wolfSSL/src/internal.c")

    verify_rsa_sign_start = internal.index("int VerifyRsaSign(")
    verify_rsa_sign_end = internal.index("/* Handle async pending response */", verify_rsa_sign_start)
    verify_rsa_sign = internal[verify_rsa_sign_start:verify_rsa_sign_end]

    pss_call = "wc_RsaPSS_VerifyInline(verifySig, sigSz, &out, hashType, mgf,"
    pkcs1_call = "wc_RsaSSL_VerifyInline(verifySig, sigSz, &out, key);"

    assert pss_call in verify_rsa_sign
    assert pkcs1_call in verify_rsa_sign
    assert verify_rsa_sign.count(
        "PQC_TLS_InstrumentationBegin(PQC_TLS_PRIMITIVE_RSA_VERIFY)"
    ) >= 2
    assert verify_rsa_sign.count(
        "PQC_TLS_InstrumentationEnd(PQC_TLS_PRIMITIVE_RSA_VERIFY, ret)"
    ) >= 2

    rsa_verify_start = internal.index("int RsaVerify(")
    rsa_verify_end = internal.index("int VerifyRsaSign(", rsa_verify_start)
    rsa_verify = internal[rsa_verify_start:rsa_verify_end]

    assert "wc_RsaSSL_VerifyInline(in, inSz, out, key);" in rsa_verify
    assert (
        "PQC_TLS_InstrumentationBegin(PQC_TLS_PRIMITIVE_RSA_VERIFY)"
        in rsa_verify
    )
    assert (
        "PQC_TLS_InstrumentationEnd(PQC_TLS_PRIMITIVE_RSA_VERIFY, ret)"
        in rsa_verify
    )


def test_instrumentation_report_is_post_handshake_only():
    source = read("Core/Src/pqc_tls_instrumentation.c")

    end_fn = source.index("void PQC_TLS_InstrumentationEnd")
    report_fn = source.index("void PQC_TLS_InstrumentationReport")
    assert end_fn < report_fn
    assert "snprintf" not in source[end_fn:report_fn]


def test_stale_tls_context_only_cmake_description_removed():
    cmake = read("CMakeLists.txt")

    assert "TLS 1.2 client WOLFSSL_CTX" not in cmake
    assert "No transport, certificate loading, handshake" not in cmake
    assert "STM32 wolfSSL TLS 1.3 runtime source integration" in cmake


def test_tls_io_diagnostics_are_compile_time_disabled_by_default():
    source = read("Core/Src/pqc_wolfmqtt_build_only.c")

    assert "#define PQC_WOLFMQTT_TLS_IO_TRACE 0" in source
    assert "#if PQC_WOLFMQTT_TLS_IO_TRACE\n    if (socket_context->tls_recv_calls == 1U)" in source
    assert "#if PQC_WOLFMQTT_TLS_IO_TRACE\n    if (socket_context->tls_send_calls == 1U)" in source
    assert 'PQC_WolfMQTT_DiagnosticCode("io_recv"' not in source
    assert 'PQC_WolfMQTT_DiagnosticCode("io_send"' not in source


def test_successful_tls_setup_path_does_not_emit_uart_before_handshake():
    source = read("Core/Src/pqc_wolfmqtt_build_only.c")

    method = source.index("tls_method = wolfTLSv1_3_client_method();")
    begin = source.index("PQC_TLS_InstrumentationBegin(PQC_TLS_EVENT_HANDSHAKE);", method)
    setup = source[method:begin]

    # Diagnostics in this range are failure-only branches. The prior
    # unconditional context/session/CA success markers were removed.
    assert "context create begin" not in setup
    assert "before_context_create" not in setup
    assert "after_context_create" not in setup
    assert "before_session_create" not in setup
    assert "after_session_create" not in setup
    assert "trust anchor: pem_sha256" not in setup


def test_handshake_summary_is_split_into_bounded_timing_and_memory_records():
    source = read("Core/Src/pqc_tls_instrumentation.c")

    assert 'char line[384];' in source
    assert 'PQC_TLS_HANDSHAKE_TIMING result=' in source
    assert 'PQC_TLS_HANDSHAKE_MEMORY ' in source
    assert 'PQC_TLS_HANDSHAKE_METRICS result=' not in source


def test_primitive_report_captures_both_available_clock_sources():
    source = read("Core/Src/pqc_tls_instrumentation.c")
    primitive_report = source[source.index('"PQC_TLS_PRIMITIVE name=%s'): ]

    assert 'timing_source=dwt_cycles elapsed_time_source=monotonic_us' in primitive_report
    assert 'total_us=%s' in primitive_report
    assert 'first_start_us=%s' in primitive_report
    assert 'last_end_us=%s' in primitive_report
    assert 'first_start_tick_ms=' not in primitive_report
    assert 'last_end_tick_ms=' not in primitive_report


def test_public_instrumentation_api_is_generic_and_event_parameterised():
    header = read("Core/Inc/pqc_tls_instrumentation.h")

    assert "PQC_TLS_InstrumentationBegin(PQC_TLSInstrumentationEvent event)" in header
    assert "PQC_TLS_InstrumentationEnd(PQC_TLSInstrumentationEvent event, int32_t result)" in header
    assert "PQC_TLS_InstrumentationHandshakeBegin" not in header
    assert "PQC_TLS_InstrumentationPhaseBegin" not in header
    assert "PQC_TLS_InstrumentationPrimitiveBegin" not in header
    assert "PQC_TLS_InstrumentationSetContext(uint32_t iteration, uint32_t handshake_index)" in header
    assert "PQC_TLS_INSTRUMENTATION_EVENT_CAPACITY" in header
    assert "PQC_TLSInstrumentationRecord" in header



def test_legacy_wolfssl_startup_smokes_are_removed():
    build_only = read("Core/Src/pqc_wolfssl_build_only.c")
    transport = read("Core/Src/pqc_wolfssl_transport.c")
    main = read("Core/Src/main.c")

    assert "wolfSSL TLS startup self-test:" not in build_only
    assert "wolfSSL transport startup self-test:" not in transport
    assert "APP_PrintWolfSSLRuntimeSmoke" not in main
    assert "APP_PrintWolfSSLTransportStatus" not in main
    assert "runtime_validation=live_mqtt_tls_workflow" in build_only

def test_crypto_hooks_cover_every_ready_metrics_algorithm_family():
    internal = read("Middlewares/Third_Party/wolfSSL/src/internal.c")
    tls = read("Middlewares/Third_Party/wolfSSL/src/tls.c")
    tls13 = read("Middlewares/Third_Party/wolfSSL/src/tls13.c")
    asn = read("Middlewares/Third_Party/wolfSSL/wolfcrypt/src/asn.c")
    report = read("Core/Src/pqc_tls_instrumentation.c")

    for primitive in (
        "PQC_TLS_PRIMITIVE_P256_KEYGEN",
        "PQC_TLS_PRIMITIVE_P256_SHARED_SECRET",
        "PQC_TLS_PRIMITIVE_P384_KEYGEN",
        "PQC_TLS_PRIMITIVE_P384_SHARED_SECRET",
        "PQC_TLS_PRIMITIVE_P521_KEYGEN",
        "PQC_TLS_PRIMITIVE_P521_SHARED_SECRET",
        "PQC_TLS_PRIMITIVE_X25519_KEYGEN",
        "PQC_TLS_PRIMITIVE_X25519_SHARED_SECRET",
    ):
        assert primitive in internal

    for primitive in (
        "PQC_TLS_PRIMITIVE_MLKEM512_KEYGEN",
        "PQC_TLS_PRIMITIVE_MLKEM512_DECAPSULATE",
        "PQC_TLS_PRIMITIVE_MLKEM768_KEYGEN",
        "PQC_TLS_PRIMITIVE_MLKEM768_DECAPSULATE",
        "PQC_TLS_PRIMITIVE_MLKEM1024_KEYGEN",
        "PQC_TLS_PRIMITIVE_MLKEM1024_DECAPSULATE",
    ):
        assert primitive in tls

    # TLS CertificateVerify and X.509 chain verification use different wolfSSL
    # paths. Signature-family aggregates must cover both layers consistently.
    assert "PQC_TLS_PRIMITIVE_RSA_VERIFY" in internal
    assert "PQC_TLS_PRIMITIVE_RSA_VERIFY" in asn
    assert "PQC_TLS_PRIMITIVE_RSA_SIGN" in tls13
    assert "PQC_TLS_PRIMITIVE_ECDSA_VERIFY" in internal
    assert "PQC_TLS_PRIMITIVE_ECDSA_VERIFY" in asn
    assert "PQC_TLS_PRIMITIVE_ECDSA_SIGN" in internal
    assert "PQC_TLS_PRIMITIVE_MLDSA65_VERIFY" in tls13
    assert "PQC_TLS_PRIMITIVE_MLDSA65_VERIFY" in asn
    assert "PQC_TLS_PRIMITIVE_MLDSA65_SIGN" in tls13

    for name in (
        '"p256_keygen"', '"p256_shared_secret"',
        '"p384_keygen"', '"p384_shared_secret"',
        '"p521_keygen"', '"p521_shared_secret"',
        '"x25519_keygen"', '"x25519_shared_secret"',
        '"mlkem512_keygen"', '"mlkem512_decapsulate"',
        '"mlkem768_keygen"', '"mlkem768_decapsulate"',
        '"mlkem1024_keygen"', '"mlkem1024_decapsulate"',
        '"rsa_verify"', '"rsa_sign"',
        '"ecdsa_verify"', '"ecdsa_sign"',
        '"mldsa65_verify"', '"mldsa65_sign"',
        '"sha256"', '"sha384"',
    ):
        assert name in report


def test_tls_ready_metrics_validator_requires_profile_specific_instrumentation():
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "experiment_cli_tls_instrumentation", ROOT / "scripts/experiment.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    scripts_path = ROOT / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    from framework.config_resolver import ConfigResolver

    resolver = ConfigResolver(ROOT)
    cases = resolver.expand_campaign("tls_key_exchange") + resolver.expand_campaign("tls_authentication")
    assert cases, "expected canonical TLS campaign cases"

    for case in cases:
        bundle = resolver.to_legacy_bundle(case, resolve_secrets=False)
        markers = module._mqtt_e2e_required_uart_markers(bundle)
        tls = bundle["experiment"]["mqtt"]["tls"]
        group = tls["key_exchange_group"].lower()
        certificate_profile = str(tls.get("certificate_profile", "")).strip().lower()
        signature = str(tls.get("server_signature_algorithm", "")).strip().lower()
        mutual = str(tls.get("authentication", "server")).lower() == "mutual"

        assert "PQC_TLS_HANDSHAKE_TIMING result=1 cycle_counter_available=1" in markers
        assert "PQC_TLS_HANDSHAKE_MEMORY" in markers
        assert "PQC_TLS_PRIMITIVE name=x509_verify" in markers
        assert "PQC_TLS_PRIMITIVE name=sha256" in markers
        if certificate_profile == "ecdsa-p384":
            assert "PQC_TLS_PRIMITIVE name=sha384" in markers
        else:
            assert "PQC_TLS_PRIMITIVE name=sha384" not in markers
        assert "ST67 DNS: required=true" not in markers

        if "x25519" in group:
            assert "PQC_TLS_PRIMITIVE name=x25519_keygen" in markers
        if "mlkem512" in group or "ml_kem_512" in group:
            assert "PQC_TLS_PRIMITIVE name=mlkem512_keygen" in markers
            assert "PQC_TLS_PRIMITIVE name=mlkem512_decapsulate" in markers
        if "mlkem768" in group or "ml_kem_768" in group:
            assert "PQC_TLS_PRIMITIVE name=mlkem768_keygen" in markers
            assert "PQC_TLS_PRIMITIVE name=mlkem768_decapsulate" in markers
        if "mlkem1024" in group or "ml_kem_1024" in group:
            assert "PQC_TLS_PRIMITIVE name=mlkem1024_keygen" in markers
            assert "PQC_TLS_PRIMITIVE name=mlkem1024_decapsulate" in markers
        if signature == "mldsa65":
            assert "PQC_TLS_PRIMITIVE name=mldsa65_verify" in markers
        if mutual and signature == "mldsa65":
            assert "PQC_TLS_PRIMITIVE name=mldsa65_sign" in markers


def test_all_tls_hook_end_calls_propagate_meaningful_results():
    hook_files = (
        "Middlewares/Third_Party/wolfSSL/src/tls13.c",
        "Middlewares/Third_Party/wolfSSL/src/tls.c",
        "Middlewares/Third_Party/wolfSSL/src/internal.c",
        "Middlewares/Third_Party/wolfSSL/wolfcrypt/src/asn.c",
        "Middlewares/Third_Party/wolfSSL/wolfcrypt/src/kdf.c",
        "Middlewares/Third_Party/wolfSSL/wolfcrypt/src/sha256.c",
        "Middlewares/Third_Party/wolfSSL/wolfcrypt/src/sha512.c",
    )

    for path in hook_files:
        source = read(path)
        assert "PQC_TLS_InstrumentationEnd(" in source
        assert "PQC_TLS_INSTRUMENTATION_RESULT_UNSPECIFIED" not in source


def test_verification_hooks_normalize_separate_validity_outputs():
    internal = read("Middlewares/Third_Party/wolfSSL/src/internal.c")
    tls13 = read("Middlewares/Third_Party/wolfSSL/src/tls13.c")
    asn = read("Middlewares/Third_Party/wolfSSL/wolfcrypt/src/asn.c")

    assert "((ssl->eccVerifyRes != 0) ? 0 : VERIFY_SIGN_ERROR)" in internal
    assert "((res == 1) ? 0 : SIG_VERIFY_E)" in tls13
    assert "((sigCtx->verify != 0) ? 0 : ASN_SIG_CONFIRM_E)" in asn


def test_common_tls_hook_families_pass_underlying_return_code():
    tls13 = read("Middlewares/Third_Party/wolfSSL/src/tls13.c")
    tls = read("Middlewares/Third_Party/wolfSSL/src/tls.c")
    internal = read("Middlewares/Third_Party/wolfSSL/src/internal.c")
    kdf = read("Middlewares/Third_Party/wolfSSL/wolfcrypt/src/kdf.c")
    sha256 = read("Middlewares/Third_Party/wolfSSL/wolfcrypt/src/sha256.c")
    sha512 = read("Middlewares/Third_Party/wolfSSL/wolfcrypt/src/sha512.c")

    for phase in (
        "PQC_TLS_PHASE_SERVER_HELLO",
        "PQC_TLS_PHASE_ENCRYPTED_EXTENSIONS",
        "PQC_TLS_PHASE_CERTIFICATE",
        "PQC_TLS_PHASE_CERTIFICATE_VERIFY",
        "PQC_TLS_PHASE_FINISHED",
    ):
        assert f"PQC_TLS_InstrumentationEnd({phase}, ret)" in tls13

    assert "PQC_TLS_InstrumentationEnd(PQC_TLS_PRIMITIVE_MLKEM512_KEYGEN, ret)" in tls
    assert "PQC_TLS_InstrumentationEnd(PQC_TLS_PRIMITIVE_X25519_KEYGEN, ret)" in internal
    assert "PQC_TLS_InstrumentationEnd(PQC_TLS_PRIMITIVE_X509_VERIFY, ret)" in internal
    assert "PQC_TLS_InstrumentationEnd(PQC_TLS_PRIMITIVE_HKDF_EXTRACT, ret)" in kdf
    assert "PQC_TLS_InstrumentationEnd(PQC_TLS_PRIMITIVE_HKDF_EXPAND, ret)" in kdf
    assert "PQC_TLS_InstrumentationEnd(PQC_TLS_PRIMITIVE_SHA256, pqcRet)" in sha256
    assert "PQC_TLS_InstrumentationEnd(PQC_TLS_PRIMITIVE_SHA256, ret)" in sha256
    assert "PQC_TLS_InstrumentationEnd(PQC_TLS_PRIMITIVE_SHA384, pqcRet)" in sha512
    assert "PQC_TLS_InstrumentationEnd(PQC_TLS_PRIMITIVE_SHA384, ret)" in sha512


def test_tls_dns_resolution_does_not_emit_success_uart_before_handshake():
    source = read("Core/Src/pqc_wolfmqtt_build_only.c")
    resolve = source.index("result = PQC_WolfMQTT_ResolveBroker(")
    begin = source.index("PQC_TLS_InstrumentationBegin(PQC_TLS_EVENT_HANDSHAKE);", resolve)
    pre_handshake = source[resolve:begin]

    assert "host, &address, !socket_context->tls_requested" in pre_handshake
    assert "if (!socket_context->tls_requested)" in source[source.rfind("if (!socket_context->tls_requested)", 0, resolve):resolve]
