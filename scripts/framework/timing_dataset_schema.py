"""A1 scalar dataset contract. No pandas/numpy inference is used for CSV types."""
from __future__ import annotations

SCHEMA_NAME = "pqc-timing-dataset"
SCHEMA_VERSION = 1
PARSER_VERSION = "1.3.0"
METRIC_VERSION = "1"
NULL = r"\N"

# Every column is nullable unless an invariant in the loader says otherwise.
RUN_COLUMNS = {
    **dict.fromkeys((
        "run_key", "run_id", "input_path", "manifest_sha256", "capture_index_sha256",
        "manifest_status", "execution_outcome", "execution_result", "failure_stage",
        "capture_acceptance", "selected_input_status", "configuration_identity",
        "firmware_identity", "firmware_sha256", "build_number", "source_commit",
        "preparation_run_id", "campaign_id", "case_id", "condition_identity",
        "retry_of_run_id", "workload", "application", "target", "gateway",
        "network_condition", "tls_kex", "tls_auth", "auth_mode", "secure_boot",
        "firmware_mode", "evidence_class", "capture_class", "timing_policy_exclusion",
    ), "string"),
    **dict.fromkeys(("return_code", "repetition_index", "attempt_index", "payload_bytes",
                    "chunk_bytes", "observed_stream_count", "observed_iteration_count"), "integer"),
    **dict.fromkeys(("preparation_verified", "boot_stack_profiling", "boot_uart_diagnostics"), "boolean"),
    **dict.fromkeys(("input_paths", "controls", "build_references", "iteration_ids",
                    "capture_reasons", "inventory_reasons"), "json"),
}
TIMING_COLUMNS = {
    **dict.fromkeys(("run_key", "run_id", "observation_id", "metric", "unit",
                    "metric_version", "scope", "validity", "reason", "operation_outcome",
                    "clock_source", "timestamp_origin", "start_boundary", "end_boundary",
                    "source_sha256", "logical_sha256", "comparison_inclusion", "timing_policy_exclusion"), "string"),
    **dict.fromkeys(("epoch_index", "iteration_id", "handshake_id", "invocation_sequence",
                    "result_code", "value_us", "start_us", "end_us", "reset_offset_us",
                    "counter_hz"), "integer"),
    "source_records": "json", "clock_provenance": "json",
}
ISSUE_COLUMNS = {
    **dict.fromkeys(("issue_id", "run_key", "run_id", "severity", "code", "artifact",
                    "metric", "detail"), "string"),
    "epoch_index": "integer", "iteration_id": "integer", "source_records": "json",
}
TABLES = {"runs": RUN_COLUMNS, "timings": TIMING_COLUMNS, "issues": ISSUE_COLUMNS}
METRICS = {
    "tls_handshake": {"formula": "end_us - start_us", "boundary": "outer instrumented TLS handshake", "requires": "timebase_available=1, successful result=1; any recorded outer event must agree"},
    "mqtt_readiness": {"formula": "mqtt_readiness_checkpoint_us - tcp_connect_start_us", "boundary": "TCP connect attempt to first MQTT CONNACK plaintext byte", "requires": "RM2 v3 checkpoints and valid TIM2 provenance; mqtt_readiness_valid=1"},
    "rtfb": {"formula": "reset_origin_to_application_timebase_us + application_first_byte_us", "boundary": "operational wolfBoot entry to first application payload byte", "requires": "RM2 v3; matching valid reset offset/origin; reset_metrics_valid=1"},
    "rtlb": {"formula": "reset_origin_to_application_timebase_us + application_last_byte_us", "boundary": "operational wolfBoot entry to last application payload byte", "requires": "RM2 v3; matching valid reset offset/origin; reset_metrics_valid=1"},
    "ttfb": {"formula": "application_first_byte_us - tcp_connect_start_us", "boundary": "TCP connect attempt (after DNS) to first application payload byte", "requires": "RM2 v3 matching checkpoints/scalar and complete payload"},
    "ttlb": {"formula": "application_last_byte_us - tcp_connect_start_us", "boundary": "TCP connect attempt (after DNS) to last application payload byte", "requires": "RM2 v3 matching checkpoints/scalar and complete payload"},
    "req_tfb": {"formula": "application_first_byte_us - application_request_us", "boundary": "application request to first application payload byte", "requires": "RM2 v3 matching checkpoints/scalar and complete payload"},
    "req_tlb": {"formula": "application_last_byte_us - application_request_us", "boundary": "application request to last application payload byte", "requires": "RM2 v3 matching checkpoints/scalar and complete payload"},
}
for _definition in METRICS.values():
    _definition.update(unit="us", version=METRIC_VERSION, missing="null with reason; never a sentinel zero")

SUPPORTED_INPUTS = {
    "manifest": {"name": "pqc-run-evidence", "version": 3},
    "capture_contract_version": 2,
    "resolved_case": {"name": "pqc-resolved-case-snapshot", "version": 1},
    "provenance": {"name": "pqc-run-provenance", "version": 1},
    "reporting_envelope_version": 1, "logical_record_version": 1,
    "ready_metrics_2_marker_version": 3, "tls_event_buffer_version": 1,
    "tls_repeat_status_version": 1,
    "tls_handshake_marker": "PQC_TLS_HANDSHAKE_TIMING current start_us/end_us/elapsed_us fields",
}
