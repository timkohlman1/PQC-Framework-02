#include "pqc_tls_instrumentation.h"

#include "main.h"
#include <stdio.h>
#include <string.h>

typedef struct
{
    uint32_t start_cycle;
    uint32_t start_tick_ms;
    uint8_t active;
} PQC_TLSSpan;

static PQC_TLSInstrumentationSnapshot s_snapshot;
static PQC_TLSSpan s_phase_spans[PQC_TLS_PHASE_COUNT];
static PQC_TLSSpan s_primitive_spans[PQC_TLS_PRIMITIVE_COUNT];
static uint8_t s_handshake_active;

static uint32_t PQC_TLS_ReadCycleCounter(void)
{
#if defined(DWT) && defined(CoreDebug) && defined(DWT_CTRL_CYCCNTENA_Msk) && \
    defined(CoreDebug_DEMCR_TRCENA_Msk)
    return DWT->CYCCNT;
#else
    return 0U;
#endif
}

static uint8_t PQC_TLS_EnableCycleCounter(void)
{
#if defined(DWT) && defined(CoreDebug) && defined(DWT_CTRL_CYCCNTENA_Msk) && \
    defined(CoreDebug_DEMCR_TRCENA_Msk)
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0U;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
    __DSB();
    __ISB();
    return (DWT->CTRL & DWT_CTRL_CYCCNTENA_Msk) != 0U ? 1U : 0U;
#else
    return 0U;
#endif
}

static void PQC_TLS_Accumulate(
    PQC_TLSTimingAggregate *aggregate,
    uint32_t start_cycle,
    uint32_t end_cycle,
    uint32_t start_tick_ms,
    uint32_t end_tick_ms)
{
    uint32_t elapsed_cycles = end_cycle - start_cycle;

    if (aggregate->count == 0U) {
        aggregate->min_cycles = elapsed_cycles;
        aggregate->max_cycles = elapsed_cycles;
        aggregate->first_start_cycle = start_cycle;
        aggregate->first_start_tick_ms = start_tick_ms;
    }
    else {
        if (elapsed_cycles < aggregate->min_cycles) aggregate->min_cycles = elapsed_cycles;
        if (elapsed_cycles > aggregate->max_cycles) aggregate->max_cycles = elapsed_cycles;
    }

    aggregate->count++;
    aggregate->total_cycles += elapsed_cycles;
    aggregate->last_end_cycle = end_cycle;
    aggregate->last_end_tick_ms = end_tick_ms;
}

void PQC_TLS_InstrumentationSetPreMemory(
    uint32_t stack_min_free_bytes,
    uint32_t heap_free_bytes,
    uint32_t heap_min_ever_free_bytes)
{
    s_snapshot.stack_before_min_free_bytes = stack_min_free_bytes;
    s_snapshot.heap_before_free_bytes = heap_free_bytes;
    s_snapshot.heap_before_min_ever_free_bytes = heap_min_ever_free_bytes;
}

void PQC_TLS_InstrumentationHandshakeBegin(void)
{
    uint32_t stack_before = s_snapshot.stack_before_min_free_bytes;
    uint32_t heap_before = s_snapshot.heap_before_free_bytes;
    uint32_t heap_min_before = s_snapshot.heap_before_min_ever_free_bytes;

    memset(&s_snapshot, 0, sizeof(s_snapshot));
    memset(s_phase_spans, 0, sizeof(s_phase_spans));
    memset(s_primitive_spans, 0, sizeof(s_primitive_spans));

    s_snapshot.stack_before_min_free_bytes = stack_before;
    s_snapshot.heap_before_free_bytes = heap_before;
    s_snapshot.heap_before_min_ever_free_bytes = heap_min_before;
    s_snapshot.cycle_counter_available = PQC_TLS_EnableCycleCounter();
    s_handshake_active = 1U;

    /* These are deliberately the final operations before wolfSSL_connect(). */
    s_snapshot.handshake_start_tick_ms = HAL_GetTick();
    s_snapshot.handshake_start_cycle = PQC_TLS_ReadCycleCounter();
}

void PQC_TLS_InstrumentationHandshakeEnd(int result)
{
    /* These are deliberately the first measurements after wolfSSL_connect(). */
    s_snapshot.handshake_end_cycle = PQC_TLS_ReadCycleCounter();
    s_snapshot.handshake_end_tick_ms = HAL_GetTick();
    s_handshake_active = 0U;

    s_snapshot.handshake_result = result;
    s_snapshot.handshake_elapsed_cycles =
        s_snapshot.handshake_end_cycle - s_snapshot.handshake_start_cycle;
    s_snapshot.handshake_elapsed_ms =
        s_snapshot.handshake_end_tick_ms - s_snapshot.handshake_start_tick_ms;
}

void PQC_TLS_InstrumentationSetPostMemory(
    uint32_t stack_min_free_bytes,
    uint32_t heap_free_bytes,
    uint32_t heap_min_ever_free_bytes)
{
    s_snapshot.stack_after_min_free_bytes = stack_min_free_bytes;
    s_snapshot.heap_after_free_bytes = heap_free_bytes;
    s_snapshot.heap_after_min_ever_free_bytes = heap_min_ever_free_bytes;
}

void PQC_TLS_InstrumentationPhaseBegin(PQC_TLSPhase phase)
{
    PQC_TLSSpan *span;
    if (!s_handshake_active || phase >= PQC_TLS_PHASE_COUNT) return;
    span = &s_phase_spans[phase];
    span->start_tick_ms = HAL_GetTick();
    span->start_cycle = PQC_TLS_ReadCycleCounter();
    span->active = 1U;
}

void PQC_TLS_InstrumentationPhaseEnd(PQC_TLSPhase phase)
{
    PQC_TLSSpan *span;
    uint32_t end_cycle;
    uint32_t end_tick_ms;
    if (!s_handshake_active || phase >= PQC_TLS_PHASE_COUNT) return;
    span = &s_phase_spans[phase];
    if (!span->active) return;
    end_cycle = PQC_TLS_ReadCycleCounter();
    end_tick_ms = HAL_GetTick();
    span->active = 0U;
    PQC_TLS_Accumulate(&s_snapshot.phases[phase],
        span->start_cycle, end_cycle, span->start_tick_ms, end_tick_ms);
}

void PQC_TLS_InstrumentationPrimitiveBegin(PQC_TLSPrimitive primitive)
{
    PQC_TLSSpan *span;
    if (!s_handshake_active || primitive >= PQC_TLS_PRIMITIVE_COUNT) return;
    span = &s_primitive_spans[primitive];
    span->start_tick_ms = 0U;
    span->start_cycle = PQC_TLS_ReadCycleCounter();
    span->active = 1U;
}

void PQC_TLS_InstrumentationPrimitiveEnd(PQC_TLSPrimitive primitive)
{
    PQC_TLSSpan *span;
    uint32_t end_cycle;
    uint32_t end_tick_ms;
    if (!s_handshake_active || primitive >= PQC_TLS_PRIMITIVE_COUNT) return;
    span = &s_primitive_spans[primitive];
    if (!span->active) return;
    end_cycle = PQC_TLS_ReadCycleCounter();
    end_tick_ms = 0U;
    span->active = 0U;

    if (primitive == PQC_TLS_PRIMITIVE_X509_VERIFY) {
        uint8_t invocation = s_snapshot.x509_verify_invocation_count;
        if (invocation < PQC_TLS_X509_VERIFY_INVOCATION_CAPACITY) {
            PQC_TLSInvocationTiming *record =
                &s_snapshot.x509_verify_invocations[invocation];
            record->start_cycle = span->start_cycle;
            record->end_cycle = end_cycle;
            record->elapsed_cycles = end_cycle - span->start_cycle;
            s_snapshot.x509_verify_invocation_count = (uint8_t)(invocation + 1U);
        }
        else {
            s_snapshot.x509_verify_invocation_overflow = 1U;
        }
    }

    PQC_TLS_Accumulate(&s_snapshot.primitives[primitive],
        span->start_cycle, end_cycle, span->start_tick_ms, end_tick_ms);
}

const PQC_TLSInstrumentationSnapshot *PQC_TLS_InstrumentationSnapshot(void)
{
    return &s_snapshot;
}

static const char *PQC_TLS_PhaseName(PQC_TLSPhase phase)
{
    static const char *const names[PQC_TLS_PHASE_COUNT] = {
        "server_hello",
        "encrypted_extensions",
        "certificate",
        "certificate_verify",
        "finished"
    };
    return phase < PQC_TLS_PHASE_COUNT ? names[phase] : "unknown";
}

static const char *PQC_TLS_PrimitiveName(PQC_TLSPrimitive primitive)
{
    static const char *const names[PQC_TLS_PRIMITIVE_COUNT] = {
        "p256_keygen",
        "p256_shared_secret",
        "p384_keygen",
        "p384_shared_secret",
        "p521_keygen",
        "p521_shared_secret",
        "x25519_keygen",
        "x25519_shared_secret",
        "mlkem768_keygen",
        "mlkem768_decapsulate",
        "mlkem1024_keygen",
        "mlkem1024_decapsulate",
        "rsa_verify",
        "rsa_sign",
        "mldsa65_verify",
        "mldsa65_sign",
        "sha256",
        "hkdf_extract",
        "hkdf_expand",
        "x509_verify"
    };
    return primitive < PQC_TLS_PRIMITIVE_COUNT ? names[primitive] : "unknown";
}

void PQC_TLS_InstrumentationReport(void (*write_line)(const char *text))
{
    char line[320];
    unsigned int i;
    if (write_line == NULL) return;

    /* Keep timing and memory on separate bounded records. The original combined
     * record exceeded its UART formatting buffer on hardware and concatenated
     * the first phase record onto a truncated handshake line. */
    (void)snprintf(line, sizeof(line),
        "PQC_TLS_HANDSHAKE_TIMING result=%d cycle_counter_available=%u "
        "start_cycle=%lu end_cycle=%lu elapsed_cycles=%lu "
        "start_tick_ms=%lu end_tick_ms=%lu elapsed_ms=%lu\r\n",
        s_snapshot.handshake_result,
        (unsigned int)s_snapshot.cycle_counter_available,
        (unsigned long)s_snapshot.handshake_start_cycle,
        (unsigned long)s_snapshot.handshake_end_cycle,
        (unsigned long)s_snapshot.handshake_elapsed_cycles,
        (unsigned long)s_snapshot.handshake_start_tick_ms,
        (unsigned long)s_snapshot.handshake_end_tick_ms,
        (unsigned long)s_snapshot.handshake_elapsed_ms);
    write_line(line);

    (void)snprintf(line, sizeof(line),
        "PQC_TLS_HANDSHAKE_MEMORY "
        "stack_before_min_free_bytes=%lu stack_after_min_free_bytes=%lu "
        "heap_before_free_bytes=%lu heap_after_free_bytes=%lu "
        "heap_before_min_ever_free_bytes=%lu heap_after_min_ever_free_bytes=%lu\r\n",
        (unsigned long)s_snapshot.stack_before_min_free_bytes,
        (unsigned long)s_snapshot.stack_after_min_free_bytes,
        (unsigned long)s_snapshot.heap_before_free_bytes,
        (unsigned long)s_snapshot.heap_after_free_bytes,
        (unsigned long)s_snapshot.heap_before_min_ever_free_bytes,
        (unsigned long)s_snapshot.heap_after_min_ever_free_bytes);
    write_line(line);

    for (i = 0U; i < (unsigned int)PQC_TLS_PHASE_COUNT; ++i) {
        const PQC_TLSTimingAggregate *m = &s_snapshot.phases[i];
        if (m->count == 0U) continue;
        (void)snprintf(line, sizeof(line),
            "PQC_TLS_PHASE name=%s count=%lu total_cycles=%lu min_cycles=%lu "
            "max_cycles=%lu first_start_cycle=%lu last_end_cycle=%lu "
            "first_start_tick_ms=%lu last_end_tick_ms=%lu\r\n",
            PQC_TLS_PhaseName((PQC_TLSPhase)i),
            (unsigned long)m->count,
            (unsigned long)m->total_cycles,
            (unsigned long)m->min_cycles,
            (unsigned long)m->max_cycles,
            (unsigned long)m->first_start_cycle,
            (unsigned long)m->last_end_cycle,
            (unsigned long)m->first_start_tick_ms,
            (unsigned long)m->last_end_tick_ms);
        write_line(line);
    }

    for (i = 0U; i < (unsigned int)PQC_TLS_PRIMITIVE_COUNT; ++i) {
        const PQC_TLSTimingAggregate *m = &s_snapshot.primitives[i];
        if (m->count == 0U) continue;
        (void)snprintf(line, sizeof(line),
            "PQC_TLS_PRIMITIVE name=%s count=%lu total_cycles=%lu "
            "min_cycles=%lu max_cycles=%lu first_start_cycle=%lu "
            "last_end_cycle=%lu timing_source=dwt_cycles\r\n",
            PQC_TLS_PrimitiveName((PQC_TLSPrimitive)i),
            (unsigned long)m->count,
            (unsigned long)m->total_cycles,
            (unsigned long)m->min_cycles,
            (unsigned long)m->max_cycles,
            (unsigned long)m->first_start_cycle,
            (unsigned long)m->last_end_cycle);
        write_line(line);
    }

    for (i = 0U; i < (unsigned int)s_snapshot.x509_verify_invocation_count; ++i) {
        const PQC_TLSInvocationTiming *record =
            &s_snapshot.x509_verify_invocations[i];
        (void)snprintf(line, sizeof(line),
            "PQC_TLS_X509_VERIFY sequence=%u start_cycle=%lu end_cycle=%lu "
            "elapsed_cycles=%lu timing_source=dwt_cycles scope=duration_only\r\n",
            i + 1U,
            (unsigned long)record->start_cycle,
            (unsigned long)record->end_cycle,
            (unsigned long)record->elapsed_cycles);
        write_line(line);
    }
    if (s_snapshot.x509_verify_invocation_overflow != 0U) {
        (void)snprintf(line, sizeof(line),
            "PQC_TLS_X509_VERIFY overflow=1 capacity=%u\r\n",
            (unsigned int)PQC_TLS_X509_VERIFY_INVOCATION_CAPACITY);
        write_line(line);
    }
}
