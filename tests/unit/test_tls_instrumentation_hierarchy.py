from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _compile_and_run(tmp_path: Path, program: str) -> subprocess.CompletedProcess[str]:
    (tmp_path / "main.h").write_text("#pragma once\n", encoding="utf-8")
    (tmp_path / "pqc_timebase.h").write_text(
        """#pragma once
#include <stdint.h>
typedef struct { uint8_t initialized; } PQC_TimebaseProvenance;
uint64_t PQC_TimebaseNowUs(void);
uint64_t PQC_TimebaseElapsedUs(uint64_t start_us, uint64_t end_us);
const PQC_TimebaseProvenance *PQC_TimebaseGetProvenance(void);
""",
        encoding="utf-8",
    )
    (tmp_path / "test.c").write_text(program, encoding="utf-8")
    executable = tmp_path / "tls_instrumentation_test"
    compile_result = subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(tmp_path),
            "-I",
            str(ROOT / "Core" / "Inc"),
            str(ROOT / "Core" / "Src" / "pqc_tls_instrumentation.c"),
            str(tmp_path / "test.c"),
            "-o",
            str(executable),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    return subprocess.run(
        [str(executable)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_ordering_nesting_and_context_are_retained(tmp_path: Path):
    result = _compile_and_run(
        tmp_path,
        r'''
#include "pqc_tls_instrumentation.h"
#include "pqc_timebase.h"
#include <assert.h>

static uint64_t now_us = 1000U;
static const PQC_TimebaseProvenance provenance = { 1U };
uint64_t PQC_TimebaseNowUs(void) { now_us += 10U; return now_us; }
uint64_t PQC_TimebaseElapsedUs(uint64_t start_us, uint64_t end_us) { return end_us - start_us; }
const PQC_TimebaseProvenance *PQC_TimebaseGetProvenance(void) { return &provenance; }

int main(void) {
    const PQC_TLSInstrumentationSnapshot *snapshot;
    PQC_TLS_InstrumentationSetContext(7U, 3U);
    PQC_TLS_InstrumentationBegin(PQC_TLS_EVENT_HANDSHAKE);
    PQC_TLS_InstrumentationBegin(PQC_TLS_PHASE_CERTIFICATE);
    PQC_TLS_InstrumentationBegin(PQC_TLS_PRIMITIVE_X509_VERIFY);
    PQC_TLS_InstrumentationBegin(PQC_TLS_PRIMITIVE_RSA_VERIFY);
    PQC_TLS_InstrumentationEnd(PQC_TLS_PRIMITIVE_RSA_VERIFY, PQC_TLS_INSTRUMENTATION_RESULT_UNSPECIFIED);
    PQC_TLS_InstrumentationEnd(PQC_TLS_PRIMITIVE_X509_VERIFY, 0);
    PQC_TLS_InstrumentationEnd(PQC_TLS_PHASE_CERTIFICATE, PQC_TLS_INSTRUMENTATION_RESULT_UNSPECIFIED);
    PQC_TLS_InstrumentationEnd(PQC_TLS_EVENT_HANDSHAKE, 1);

    snapshot = PQC_TLS_InstrumentationSnapshot();
    assert(snapshot->iteration == 7U);
    assert(snapshot->handshake_index == 3U);
    assert(snapshot->event_record_count == 4U);
    assert(snapshot->event_overflowed == 0U);
    assert(snapshot->event_truncated == 0U);
    assert(snapshot->hierarchy_incomplete == 0U);

    assert(snapshot->events[0].semantic_event == PQC_TLS_EVENT_HANDSHAKE);
    assert(snapshot->events[0].sequence == 0U);
    assert(snapshot->events[0].parent_sequence == PQC_TLS_EVENT_PARENT_NONE);
    assert(snapshot->events[0].level == PQC_TLS_LEVEL_WORKLOAD);
    assert(snapshot->events[0].depth == 0U);

    assert(snapshot->events[1].semantic_event == PQC_TLS_PHASE_CERTIFICATE);
    assert(snapshot->events[1].parent_sequence == 0U);
    assert(snapshot->events[1].level == PQC_TLS_LEVEL_PROTOCOL_PHASE);
    assert(snapshot->events[1].depth == 1U);

    assert(snapshot->events[2].semantic_event == PQC_TLS_PRIMITIVE_X509_VERIFY);
    assert(snapshot->events[2].parent_sequence == 1U);
    assert(snapshot->events[2].level == PQC_TLS_LEVEL_SECURITY_FUNCTION);
    assert(snapshot->events[2].depth == 2U);

    assert(snapshot->events[3].semantic_event == PQC_TLS_PRIMITIVE_RSA_VERIFY);
    assert(snapshot->events[3].parent_sequence == 2U);
    assert(snapshot->events[3].level == PQC_TLS_LEVEL_CRYPTO_OPERATION);
    assert(snapshot->events[3].depth == 3U);

    assert(snapshot->events[0].completed == 1U);
    assert(snapshot->events[1].completed == 1U);
    assert(snapshot->events[2].completed == 1U);
    assert(snapshot->events[3].completed == 1U);
    assert(snapshot->events[2].result_available == 1U);
    assert(snapshot->events[3].result_available == 0U);
    assert(snapshot->events[3].elapsed_us > 0U);
    return 0;
}
''',
    )
    assert result.returncode == 0, result.stderr


def test_event_capacity_overflow_is_explicit_and_aggregates_continue(tmp_path: Path):
    result = _compile_and_run(
        tmp_path,
        r'''
#include "pqc_tls_instrumentation.h"
#include "pqc_timebase.h"
#include <assert.h>

static uint64_t now_us = 2000U;
static const PQC_TimebaseProvenance provenance = { 1U };
uint64_t PQC_TimebaseNowUs(void) { now_us += 1U; return now_us; }
uint64_t PQC_TimebaseElapsedUs(uint64_t start_us, uint64_t end_us) { return end_us - start_us; }
const PQC_TimebaseProvenance *PQC_TimebaseGetProvenance(void) { return &provenance; }

int main(void) {
    unsigned int i;
    const PQC_TLSInstrumentationSnapshot *snapshot;
    PQC_TLS_InstrumentationBegin(PQC_TLS_EVENT_HANDSHAKE);
    for (i = 0U; i < PQC_TLS_INSTRUMENTATION_EVENT_CAPACITY; ++i) {
        PQC_TLS_InstrumentationBegin(PQC_TLS_PRIMITIVE_HKDF_EXPAND);
        PQC_TLS_InstrumentationEnd(PQC_TLS_PRIMITIVE_HKDF_EXPAND, PQC_TLS_INSTRUMENTATION_RESULT_UNSPECIFIED);
    }
    PQC_TLS_InstrumentationEnd(PQC_TLS_EVENT_HANDSHAKE, 1);

    snapshot = PQC_TLS_InstrumentationSnapshot();
    assert(snapshot->event_record_count == PQC_TLS_INSTRUMENTATION_EVENT_CAPACITY);
    assert(snapshot->dropped_event_count == 1U);
    assert(snapshot->event_overflowed == 1U);
    assert(snapshot->event_truncated == 1U);
    assert(snapshot->hierarchy_incomplete == 1U);
    assert(snapshot->primitives[PQC_TLS_PRIMITIVE_HKDF_EXPAND - PQC_TLS_PRIMITIVE_FIRST].count ==
           PQC_TLS_INSTRUMENTATION_EVENT_CAPACITY);
    return 0;
}
''',
    )
    assert result.returncode == 0, result.stderr


def test_mismatched_end_marks_hierarchy_incomplete(tmp_path: Path):
    result = _compile_and_run(
        tmp_path,
        r'''
#include "pqc_tls_instrumentation.h"
#include "pqc_timebase.h"
#include <assert.h>

static uint64_t now_us = 3000U;
static const PQC_TimebaseProvenance provenance = { 1U };
uint64_t PQC_TimebaseNowUs(void) { return ++now_us; }
uint64_t PQC_TimebaseElapsedUs(uint64_t start_us, uint64_t end_us) { return end_us - start_us; }
const PQC_TimebaseProvenance *PQC_TimebaseGetProvenance(void) { return &provenance; }

int main(void) {
    const PQC_TLSInstrumentationSnapshot *snapshot;
    PQC_TLS_InstrumentationBegin(PQC_TLS_EVENT_HANDSHAKE);
    PQC_TLS_InstrumentationBegin(PQC_TLS_PHASE_CERTIFICATE);
    PQC_TLS_InstrumentationBegin(PQC_TLS_PRIMITIVE_X509_VERIFY);
    PQC_TLS_InstrumentationEnd(PQC_TLS_PHASE_CERTIFICATE, PQC_TLS_INSTRUMENTATION_RESULT_UNSPECIFIED);
    PQC_TLS_InstrumentationEnd(PQC_TLS_PRIMITIVE_X509_VERIFY, 0);
    PQC_TLS_InstrumentationEnd(PQC_TLS_EVENT_HANDSHAKE, 1);
    snapshot = PQC_TLS_InstrumentationSnapshot();
    assert(snapshot->hierarchy_incomplete == 1U);
    assert(snapshot->invalid_sequence_count > 0U);
    return 0;
}
''',
    )
    assert result.returncode == 0, result.stderr


def test_high_frequency_sha_helpers_remain_aggregate_only(tmp_path: Path):
    result = _compile_and_run(
        tmp_path,
        r'''
#include "pqc_tls_instrumentation.h"
#include "pqc_timebase.h"
#include <assert.h>

static uint64_t now_us = 4000U;
static const PQC_TimebaseProvenance provenance = { 1U };
uint64_t PQC_TimebaseNowUs(void) { return ++now_us; }
uint64_t PQC_TimebaseElapsedUs(uint64_t start_us, uint64_t end_us) { return end_us - start_us; }
const PQC_TimebaseProvenance *PQC_TimebaseGetProvenance(void) { return &provenance; }

int main(void) {
    unsigned int i;
    const PQC_TLSInstrumentationSnapshot *snapshot;
    PQC_TLS_InstrumentationBegin(PQC_TLS_EVENT_HANDSHAKE);
    PQC_TLS_InstrumentationBegin(PQC_TLS_PRIMITIVE_X25519_KEYGEN);
    for (i = 0U; i < 300U; ++i) {
        PQC_TLS_InstrumentationBegin(PQC_TLS_PRIMITIVE_SHA256);
        PQC_TLS_InstrumentationEnd(PQC_TLS_PRIMITIVE_SHA256, PQC_TLS_INSTRUMENTATION_RESULT_UNSPECIFIED);
    }
    PQC_TLS_InstrumentationEnd(PQC_TLS_PRIMITIVE_X25519_KEYGEN, PQC_TLS_INSTRUMENTATION_RESULT_UNSPECIFIED);
    PQC_TLS_InstrumentationEnd(PQC_TLS_EVENT_HANDSHAKE, 1);

    snapshot = PQC_TLS_InstrumentationSnapshot();
    assert(snapshot->event_record_count == 2U);
    assert(snapshot->event_overflowed == 0U);
    assert(snapshot->event_truncated == 0U);
    assert(snapshot->hierarchy_incomplete == 0U);
    assert(snapshot->events[1].semantic_event == PQC_TLS_PRIMITIVE_X25519_KEYGEN);
    assert(snapshot->events[1].parent_sequence == 0U);
    assert(snapshot->primitives[PQC_TLS_PRIMITIVE_SHA256 - PQC_TLS_PRIMITIVE_FIRST].count == 300U);
    return 0;
}
''',
    )
    assert result.returncode == 0, result.stderr
