#include "pqc_tls_instrumentation.h"

#include "main.h"
#include "pqc_timebase.h"
#include <stdio.h>
#include <string.h>

typedef struct
{
    uint32_t start_cycle;
    uint64_t start_us;
    uint16_t record_index;
    uint8_t active;
} PQC_TLSSpan;

#define PQC_TLS_ACTIVE_STACK_CAPACITY 16U

static PQC_TLSInstrumentationSnapshot s_snapshot;
static PQC_TLSSpan s_event_spans[PQC_TLS_EVENT_COUNT];
static PQC_TLSInstrumentationEvent s_active_stack[PQC_TLS_ACTIVE_STACK_CAPACITY];
static uint8_t s_active_depth;
static uint8_t s_handshake_active;
static uint32_t s_pending_iteration;
static uint32_t s_pending_handshake_index;

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

static void PQC_TLS_FormatU64(uint64_t value, char *buffer, size_t buffer_size)
{
    char reversed[21];
    size_t count = 0U;
    size_t i;

    if ((buffer == NULL) || (buffer_size == 0U)) {
        return;
    }

    do {
        reversed[count++] = (char)('0' + (value % 10U));
        value /= 10U;
    } while ((value != 0U) && (count < sizeof(reversed)));

    if (count >= buffer_size) {
        buffer[0] = '\0';
        return;
    }

    for (i = 0U; i < count; ++i) {
        buffer[i] = reversed[count - 1U - i];
    }
    buffer[count] = '\0';
}

static uint8_t PQC_TLS_IsPhase(PQC_TLSInstrumentationEvent event)
{
    return (event >= PQC_TLS_PHASE_FIRST) && (event <= PQC_TLS_PHASE_LAST);
}

static uint8_t PQC_TLS_IsPrimitive(PQC_TLSInstrumentationEvent event)
{
    return (event >= PQC_TLS_PRIMITIVE_FIRST) && (event <= PQC_TLS_PRIMITIVE_LAST);
}

static uint32_t PQC_TLS_PhaseIndex(PQC_TLSInstrumentationEvent event)
{
    return (uint32_t)(event - PQC_TLS_PHASE_FIRST);
}

static uint32_t PQC_TLS_PrimitiveIndex(PQC_TLSInstrumentationEvent event)
{
    return (uint32_t)(event - PQC_TLS_PRIMITIVE_FIRST);
}

static uint8_t PQC_TLS_EventNeedsOrderedRecord(PQC_TLSInstrumentationEvent event)
{
    /* SHA-2 hooks are intentionally aggregate-only in the ordered hierarchy.
     * A normal TLS 1.3 handshake may invoke the digest helpers hundreds of
     * times, which would crowd out the semantic phase/security records that
     * the bounded hierarchy exists to preserve. Their existing aggregate
     * count/total/min/max timing remains authoritative evidence. */
    return (event != PQC_TLS_PRIMITIVE_SHA256) &&
           (event != PQC_TLS_PRIMITIVE_SHA384);
}

static uint8_t PQC_TLS_EventLevel(PQC_TLSInstrumentationEvent event)
{
    if (event == PQC_TLS_EVENT_HANDSHAKE) {
        return PQC_TLS_LEVEL_WORKLOAD;
    }
    if (PQC_TLS_IsPhase(event) != 0U) {
        return PQC_TLS_LEVEL_PROTOCOL_PHASE;
    }
    if (event == PQC_TLS_PRIMITIVE_X509_VERIFY) {
        return PQC_TLS_LEVEL_SECURITY_FUNCTION;
    }
    return PQC_TLS_LEVEL_CRYPTO_OPERATION;
}

static void PQC_TLS_MarkHierarchyIncomplete(void)
{
    s_snapshot.hierarchy_incomplete = 1U;
    if (s_snapshot.invalid_sequence_count != UINT16_MAX) {
        s_snapshot.invalid_sequence_count++;
    }
}

static void PQC_TLS_Accumulate(
    PQC_TLSTimingAggregate *aggregate,
    uint32_t start_cycle,
    uint32_t end_cycle,
    uint64_t start_us,
    uint64_t end_us)
{
    uint32_t elapsed_cycles = end_cycle - start_cycle;
    uint64_t elapsed_us = PQC_TimebaseElapsedUs(start_us, end_us);

    if (aggregate->count == 0U) {
        aggregate->min_cycles = elapsed_cycles;
        aggregate->max_cycles = elapsed_cycles;
        aggregate->first_start_cycle = start_cycle;
        aggregate->min_us = elapsed_us;
        aggregate->max_us = elapsed_us;
        aggregate->first_start_us = start_us;
    }
    else {
        if (elapsed_cycles < aggregate->min_cycles) aggregate->min_cycles = elapsed_cycles;
        if (elapsed_cycles > aggregate->max_cycles) aggregate->max_cycles = elapsed_cycles;
        if (elapsed_us < aggregate->min_us) aggregate->min_us = elapsed_us;
        if (elapsed_us > aggregate->max_us) aggregate->max_us = elapsed_us;
    }

    aggregate->count++;
    aggregate->total_cycles += elapsed_cycles;
    aggregate->total_us += elapsed_us;
    aggregate->last_end_cycle = end_cycle;
    aggregate->last_end_us = end_us;
}

static uint16_t PQC_TLS_CurrentParentSequence(void)
{
    int depth;
    for (depth = (int)s_active_depth - 1; depth >= 0; --depth) {
        PQC_TLSInstrumentationEvent parent_event = s_active_stack[depth];
        uint16_t record_index = s_event_spans[parent_event].record_index;
        if (record_index != PQC_TLS_EVENT_PARENT_NONE &&
            record_index < s_snapshot.event_record_count) {
            return s_snapshot.events[record_index].sequence;
        }
    }
    return PQC_TLS_EVENT_PARENT_NONE;
}

static uint16_t PQC_TLS_ReserveEventRecord(PQC_TLSInstrumentationEvent event)
{
    uint16_t index;
    PQC_TLSInstrumentationRecord *record;

    if (s_snapshot.event_record_count >= PQC_TLS_INSTRUMENTATION_EVENT_CAPACITY) {
        s_snapshot.event_overflowed = 1U;
        s_snapshot.event_truncated = 1U;
        s_snapshot.hierarchy_incomplete = 1U;
        if (s_snapshot.dropped_event_count != UINT16_MAX) {
            s_snapshot.dropped_event_count++;
        }
        return PQC_TLS_EVENT_PARENT_NONE;
    }

    index = s_snapshot.event_record_count++;
    record = &s_snapshot.events[index];
    memset(record, 0, sizeof(*record));
    record->sequence = index;
    record->parent_sequence = PQC_TLS_CurrentParentSequence();
    record->semantic_event = (uint16_t)event;
    record->level = PQC_TLS_EventLevel(event);
    record->depth = s_active_depth;
    record->result = PQC_TLS_INSTRUMENTATION_RESULT_UNSPECIFIED;
    return index;
}

static void PQC_TLS_PushActive(PQC_TLSInstrumentationEvent event)
{
    if (s_active_depth >= PQC_TLS_ACTIVE_STACK_CAPACITY) {
        s_snapshot.event_truncated = 1U;
        s_snapshot.hierarchy_incomplete = 1U;
        PQC_TLS_MarkHierarchyIncomplete();
        return;
    }
    s_active_stack[s_active_depth++] = event;
}

static void PQC_TLS_RemoveActive(PQC_TLSInstrumentationEvent event)
{
    int index;

    if (s_active_depth == 0U) {
        PQC_TLS_MarkHierarchyIncomplete();
        return;
    }

    if (s_active_stack[s_active_depth - 1U] == event) {
        s_active_depth--;
        return;
    }

    /* A mismatched end is retained as incomplete evidence instead of silently
     * repairing the hierarchy. Remove the matching entry, if present, so a
     * later valid span can still be recorded without corrupting the stack. */
    PQC_TLS_MarkHierarchyIncomplete();
    for (index = (int)s_active_depth - 2; index >= 0; --index) {
        if (s_active_stack[index] == event) {
            uint8_t move;
            for (move = (uint8_t)index; move + 1U < s_active_depth; ++move) {
                s_active_stack[move] = s_active_stack[move + 1U];
            }
            s_active_depth--;
            return;
        }
    }
}

void PQC_TLS_InstrumentationReset(uint32_t iteration, uint32_t handshake_index)
{
    if (s_handshake_active != 0U) {
        return;
    }
    memset(&s_snapshot, 0, sizeof(s_snapshot));
    memset(s_event_spans, 0, sizeof(s_event_spans));
    memset(s_active_stack, 0, sizeof(s_active_stack));
    s_active_depth = 0U;
    s_pending_iteration = iteration;
    s_pending_handshake_index = handshake_index;
    s_snapshot.iteration = iteration;
    s_snapshot.handshake_index = handshake_index;
}

void PQC_TLS_InstrumentationSetContext(uint32_t iteration, uint32_t handshake_index)
{
    if (s_handshake_active != 0U) {
        return;
    }
    s_pending_iteration = iteration;
    s_pending_handshake_index = handshake_index;
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

void PQC_TLS_InstrumentationBegin(PQC_TLSInstrumentationEvent event)
{
    PQC_TLSSpan *span;
    uint16_t record_index;

    if (event >= PQC_TLS_EVENT_COUNT) return;

    if (event == PQC_TLS_EVENT_HANDSHAKE) {
        uint32_t stack_before = s_snapshot.stack_before_min_free_bytes;
        uint32_t heap_before = s_snapshot.heap_before_free_bytes;
        uint32_t heap_min_before = s_snapshot.heap_before_min_ever_free_bytes;
        const PQC_TimebaseProvenance *provenance;

        memset(&s_snapshot, 0, sizeof(s_snapshot));
        memset(s_event_spans, 0, sizeof(s_event_spans));
        memset(s_active_stack, 0, sizeof(s_active_stack));
        s_active_depth = 0U;

        s_snapshot.iteration = s_pending_iteration;
        s_snapshot.handshake_index = s_pending_handshake_index;
        s_snapshot.stack_before_min_free_bytes = stack_before;
        s_snapshot.heap_before_free_bytes = heap_before;
        s_snapshot.heap_before_min_ever_free_bytes = heap_min_before;
        s_snapshot.cycle_counter_available = PQC_TLS_EnableCycleCounter();
        provenance = PQC_TimebaseGetProvenance();
        s_snapshot.timebase_available =
            (provenance != NULL && provenance->initialized != 0U) ? 1U : 0U;
        s_handshake_active = 1U;
    }
    else if (!s_handshake_active) {
        return;
    }

    span = &s_event_spans[event];
    if (span->active != 0U) {
        PQC_TLS_MarkHierarchyIncomplete();
        return;
    }

    if (PQC_TLS_EventNeedsOrderedRecord(event) != 0U) {
        record_index = PQC_TLS_ReserveEventRecord(event);
        PQC_TLS_PushActive(event);
    }
    else {
        record_index = PQC_TLS_EVENT_PARENT_NONE;
    }
    span->record_index = record_index;
    span->active = 1U;

    /* Clock reads remain the final non-trivial work at begin. No allocation,
     * formatting, UART or network I/O occurs on this path. */
    span->start_us = PQC_TimebaseNowUs();
    span->start_cycle = PQC_TLS_ReadCycleCounter();

    if (record_index != PQC_TLS_EVENT_PARENT_NONE) {
        PQC_TLSInstrumentationRecord *record = &s_snapshot.events[record_index];
        record->start_cycle = span->start_cycle;
        record->start_us = span->start_us;
    }

    if (event == PQC_TLS_EVENT_HANDSHAKE) {
        s_snapshot.handshake_start_us = span->start_us;
        s_snapshot.handshake_start_cycle = span->start_cycle;
    }
}

void PQC_TLS_InstrumentationEnd(PQC_TLSInstrumentationEvent event, int32_t result)
{
    PQC_TLSSpan *span;
    uint32_t end_cycle;
    uint64_t end_us;

    if (event >= PQC_TLS_EVENT_COUNT) return;
    if ((event != PQC_TLS_EVENT_HANDSHAKE) && !s_handshake_active) return;

    span = &s_event_spans[event];
    if (span->active == 0U) {
        PQC_TLS_MarkHierarchyIncomplete();
        return;
    }

    /* Clock reads are the first work at end: no formatting or I/O occurs. */
    end_cycle = PQC_TLS_ReadCycleCounter();
    end_us = PQC_TimebaseNowUs();
    span->active = 0U;

    if (span->record_index != PQC_TLS_EVENT_PARENT_NONE &&
        span->record_index < s_snapshot.event_record_count) {
        PQC_TLSInstrumentationRecord *record = &s_snapshot.events[span->record_index];
        record->end_cycle = end_cycle;
        record->elapsed_cycles = end_cycle - span->start_cycle;
        record->end_us = end_us;
        record->elapsed_us = PQC_TimebaseElapsedUs(span->start_us, end_us);
        record->completed = 1U;
        record->result = result;
        record->result_available =
            result == PQC_TLS_INSTRUMENTATION_RESULT_UNSPECIFIED ? 0U : 1U;
    }

    if (PQC_TLS_EventNeedsOrderedRecord(event) != 0U) {
        PQC_TLS_RemoveActive(event);
    }

    if (event == PQC_TLS_EVENT_HANDSHAKE) {
        unsigned int i;
        s_snapshot.handshake_end_cycle = end_cycle;
        s_snapshot.handshake_end_us = end_us;
        s_snapshot.handshake_result = (int)result;
        s_snapshot.handshake_elapsed_cycles = end_cycle - span->start_cycle;
        s_snapshot.handshake_elapsed_us = PQC_TimebaseElapsedUs(span->start_us, end_us);

        for (i = 0U; i < (unsigned int)PQC_TLS_EVENT_COUNT; ++i) {
            if (s_event_spans[i].active != 0U) {
                s_event_spans[i].active = 0U;
                PQC_TLS_MarkHierarchyIncomplete();
            }
        }
        if (s_active_depth != 0U) {
            s_active_depth = 0U;
            PQC_TLS_MarkHierarchyIncomplete();
        }
        s_handshake_active = 0U;
        return;
    }

    if (PQC_TLS_IsPhase(event) != 0U) {
        PQC_TLS_Accumulate(&s_snapshot.phases[PQC_TLS_PhaseIndex(event)],
            span->start_cycle, end_cycle, span->start_us, end_us);
        return;
    }

    if (PQC_TLS_IsPrimitive(event) != 0U) {
        uint32_t primitive = PQC_TLS_PrimitiveIndex(event);

        if (event == PQC_TLS_PRIMITIVE_X509_VERIFY) {
            uint8_t invocation = s_snapshot.x509_verify_invocation_count;
            if (invocation < PQC_TLS_X509_VERIFY_INVOCATION_CAPACITY) {
                PQC_TLSInvocationTiming *record =
                    &s_snapshot.x509_verify_invocations[invocation];
                record->start_cycle = span->start_cycle;
                record->end_cycle = end_cycle;
                record->elapsed_cycles = end_cycle - span->start_cycle;
                record->start_us = span->start_us;
                record->end_us = end_us;
                record->elapsed_us = PQC_TimebaseElapsedUs(span->start_us, end_us);
                s_snapshot.x509_verify_invocation_count = (uint8_t)(invocation + 1U);
            }
            else {
                s_snapshot.x509_verify_invocation_overflow = 1U;
            }
        }

        PQC_TLS_Accumulate(&s_snapshot.primitives[primitive],
            span->start_cycle, end_cycle, span->start_us, end_us);
    }
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

const PQC_TLSInstrumentationSnapshot *PQC_TLS_InstrumentationSnapshot(void)
{
    return &s_snapshot;
}

static const char *PQC_TLS_PhaseName(uint32_t phase)
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

static const char *PQC_TLS_PrimitiveName(uint32_t primitive)
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
        "mlkem512_keygen",
        "mlkem512_decapsulate",
        "mlkem768_keygen",
        "mlkem768_decapsulate",
        "mlkem1024_keygen",
        "mlkem1024_decapsulate",
        "rsa_verify",
        "rsa_sign",
        "ecdsa_verify",
        "ecdsa_sign",
        "mldsa65_verify",
        "mldsa65_sign",
        "sha256",
        "sha384",
        "hkdf_extract",
        "hkdf_expand",
        "x509_verify",
        "mldsa44_verify",
        "mldsa44_sign"
    };
    return primitive < PQC_TLS_PRIMITIVE_COUNT ? names[primitive] : "unknown";
}

static const char *PQC_TLS_EventName(PQC_TLSInstrumentationEvent event)
{
    if (event == PQC_TLS_EVENT_HANDSHAKE) return "handshake";
    if (PQC_TLS_IsPhase(event) != 0U) return PQC_TLS_PhaseName(PQC_TLS_PhaseIndex(event));
    if (PQC_TLS_IsPrimitive(event) != 0U) return PQC_TLS_PrimitiveName(PQC_TLS_PrimitiveIndex(event));
    return "unknown";
}

static const char *PQC_TLS_EventKind(uint8_t level)
{
    switch (level) {
        case PQC_TLS_LEVEL_WORKLOAD: return "workload";
        case PQC_TLS_LEVEL_PROTOCOL_PHASE: return "protocol_phase";
        case PQC_TLS_LEVEL_SECURITY_FUNCTION: return "security_function";
        case PQC_TLS_LEVEL_CRYPTO_OPERATION: return "cryptographic_operation";
        default: return "unknown";
    }
}

void PQC_TLS_InstrumentationMLDSASampling(
    uint32_t attempts, uint32_t rejected, uint32_t accepted,
    uint32_t aborted, int32_t result)
{
    PQC_TLSSpan *span = s_event_spans[PQC_TLS_PRIMITIVE_MLDSA44_SIGN].active
        ? &s_event_spans[PQC_TLS_PRIMITIVE_MLDSA44_SIGN]
        : &s_event_spans[PQC_TLS_PRIMITIVE_MLDSA65_SIGN];
    PQC_TLSMLDSASamplingRecord *record;
    if (!s_handshake_active || !span->active) return;
    if (span->record_index == PQC_TLS_EVENT_PARENT_NONE ||
        s_snapshot.mldsa_sampling_count >= PQC_TLS_MLDSA_SAMPLING_CAPACITY) {
        if (s_snapshot.mldsa_sampling_dropped != UINT16_MAX)
            s_snapshot.mldsa_sampling_dropped++;
        return;
    }
    record = &s_snapshot.mldsa_sampling[s_snapshot.mldsa_sampling_count++];
    record->event_sequence = s_snapshot.events[span->record_index].sequence;
    record->attempts = attempts;
    record->rejected = rejected;
    record->accepted = accepted;
    record->aborted = aborted;
    record->result = result;
}

void PQC_TLS_InstrumentationReport(void (*write_line)(const char *text))
{
    char line[384];
    unsigned int i;
    if (write_line == NULL) return;

    /* Keep timing and memory on separate bounded records. Formatting happens
     * only after the measured handshake/workload boundary. */
    {
        char start_us[21];
        char end_us[21];
        char elapsed_us[21];
        PQC_TLS_FormatU64(s_snapshot.handshake_start_us, start_us, sizeof(start_us));
        PQC_TLS_FormatU64(s_snapshot.handshake_end_us, end_us, sizeof(end_us));
        PQC_TLS_FormatU64(s_snapshot.handshake_elapsed_us, elapsed_us, sizeof(elapsed_us));
        (void)snprintf(line, sizeof(line),
            "PQC_TLS_HANDSHAKE_TIMING result=%d cycle_counter_available=%u timebase_available=%u "
            "start_cycle=%lu end_cycle=%lu elapsed_cycles=%lu "
            "start_us=%s end_us=%s elapsed_us=%s\r\n",
            s_snapshot.handshake_result,
            (unsigned int)s_snapshot.cycle_counter_available,
            (unsigned int)s_snapshot.timebase_available,
            (unsigned long)s_snapshot.handshake_start_cycle,
            (unsigned long)s_snapshot.handshake_end_cycle,
            (unsigned long)s_snapshot.handshake_elapsed_cycles,
            start_us, end_us, elapsed_us);
    }
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

    (void)snprintf(line, sizeof(line),
        "PQC_TLS_EVENT_BUFFER schema=1 iteration=%lu handshake=%lu count=%u capacity=%u "
        "dropped=%u overflow=%u truncated=%u incomplete=%u invalid_sequence_count=%u\r\n",
        (unsigned long)s_snapshot.iteration,
        (unsigned long)s_snapshot.handshake_index,
        (unsigned int)s_snapshot.event_record_count,
        (unsigned int)PQC_TLS_INSTRUMENTATION_EVENT_CAPACITY,
        (unsigned int)s_snapshot.dropped_event_count,
        (unsigned int)s_snapshot.event_overflowed,
        (unsigned int)s_snapshot.event_truncated,
        (unsigned int)s_snapshot.hierarchy_incomplete,
        (unsigned int)s_snapshot.invalid_sequence_count);
    write_line(line);

    (void)snprintf(line, sizeof(line),
        "PQC_MLDSA_SAMPLING_BUFFER schema=1 iteration=%lu handshake=%lu count=%u capacity=%u dropped=%u\r\n",
        (unsigned long)s_snapshot.iteration, (unsigned long)s_snapshot.handshake_index,
        (unsigned int)s_snapshot.mldsa_sampling_count,
        (unsigned int)PQC_TLS_MLDSA_SAMPLING_CAPACITY,
        (unsigned int)s_snapshot.mldsa_sampling_dropped);
    write_line(line);
    for (i = 0U; i < (unsigned int)s_snapshot.mldsa_sampling_count; ++i) {
        const PQC_TLSMLDSASamplingRecord *record = &s_snapshot.mldsa_sampling[i];
        (void)snprintf(line, sizeof(line),
            "PQC_MLDSA_SAMPLING schema=1 index=%u event_sequence=%u backend=wolfcrypt_software "
            "attempts=%lu rejected=%lu accepted=%lu aborted=%lu result=%ld\r\n",
            i, (unsigned int)record->event_sequence,
            (unsigned long)record->attempts, (unsigned long)record->rejected,
            (unsigned long)record->accepted, (unsigned long)record->aborted,
            (long)record->result);
        write_line(line);
    }

    for (i = 0U; i < (unsigned int)s_snapshot.event_record_count; ++i) {
        const PQC_TLSInstrumentationRecord *record = &s_snapshot.events[i];
        char start_us[21];
        char end_us[21];
        char elapsed_us[21];
        int parent_sequence = record->parent_sequence == PQC_TLS_EVENT_PARENT_NONE
            ? -1 : (int)record->parent_sequence;
        PQC_TLS_FormatU64(record->start_us, start_us, sizeof(start_us));
        PQC_TLS_FormatU64(record->end_us, end_us, sizeof(end_us));
        PQC_TLS_FormatU64(record->elapsed_us, elapsed_us, sizeof(elapsed_us));
        (void)snprintf(line, sizeof(line),
            "PQC_TLS_EVENT sequence=%u parent_sequence=%d level=%u depth=%u kind=%s "
            "name=%s completed=%u result_available=%u result=%ld "
            "start_cycle=%lu end_cycle=%lu elapsed_cycles=%lu "
            "start_us=%s end_us=%s elapsed_us=%s\r\n",
            (unsigned int)record->sequence,
            parent_sequence,
            (unsigned int)record->level,
            (unsigned int)record->depth,
            PQC_TLS_EventKind(record->level),
            PQC_TLS_EventName((PQC_TLSInstrumentationEvent)record->semantic_event),
            (unsigned int)record->completed,
            (unsigned int)record->result_available,
            (long)record->result,
            (unsigned long)record->start_cycle,
            (unsigned long)record->end_cycle,
            (unsigned long)record->elapsed_cycles,
            start_us, end_us, elapsed_us);
        write_line(line);
    }

    for (i = 0U; i < (unsigned int)PQC_TLS_PHASE_COUNT; ++i) {
        const PQC_TLSTimingAggregate *m = &s_snapshot.phases[i];
        if (m->count == 0U) continue;
        {
            char total_us[21];
            char min_us[21];
            char max_us[21];
            char first_start_us[21];
            char last_end_us[21];
            PQC_TLS_FormatU64(m->total_us, total_us, sizeof(total_us));
            PQC_TLS_FormatU64(m->min_us, min_us, sizeof(min_us));
            PQC_TLS_FormatU64(m->max_us, max_us, sizeof(max_us));
            PQC_TLS_FormatU64(m->first_start_us, first_start_us, sizeof(first_start_us));
            PQC_TLS_FormatU64(m->last_end_us, last_end_us, sizeof(last_end_us));
            (void)snprintf(line, sizeof(line),
                "PQC_TLS_PHASE name=%s count=%lu total_cycles=%lu min_cycles=%lu "
                "max_cycles=%lu first_start_cycle=%lu last_end_cycle=%lu "
                "total_us=%s min_us=%s max_us=%s first_start_us=%s last_end_us=%s\r\n",
                PQC_TLS_PhaseName(i),
                (unsigned long)m->count,
                (unsigned long)m->total_cycles,
                (unsigned long)m->min_cycles,
                (unsigned long)m->max_cycles,
                (unsigned long)m->first_start_cycle,
                (unsigned long)m->last_end_cycle,
                total_us, min_us, max_us, first_start_us, last_end_us);
        }
        write_line(line);
    }

    for (i = 0U; i < (unsigned int)PQC_TLS_PRIMITIVE_COUNT; ++i) {
        const PQC_TLSTimingAggregate *m = &s_snapshot.primitives[i];
        char total_us[21];
        char min_us[21];
        char max_us[21];
        char first_start_us[21];
        char last_end_us[21];
        if (m->count == 0U) continue;
        PQC_TLS_FormatU64(m->total_us, total_us, sizeof(total_us));
        PQC_TLS_FormatU64(m->min_us, min_us, sizeof(min_us));
        PQC_TLS_FormatU64(m->max_us, max_us, sizeof(max_us));
        PQC_TLS_FormatU64(m->first_start_us, first_start_us, sizeof(first_start_us));
        PQC_TLS_FormatU64(m->last_end_us, last_end_us, sizeof(last_end_us));
        (void)snprintf(line, sizeof(line),
            "PQC_TLS_PRIMITIVE name=%s count=%lu total_cycles=%lu "
            "min_cycles=%lu max_cycles=%lu first_start_cycle=%lu "
            "last_end_cycle=%lu total_us=%s min_us=%s max_us=%s "
            "first_start_us=%s last_end_us=%s "
            "timing_source=dwt_cycles elapsed_time_source=monotonic_us\r\n",
            PQC_TLS_PrimitiveName(i),
            (unsigned long)m->count,
            (unsigned long)m->total_cycles,
            (unsigned long)m->min_cycles,
            (unsigned long)m->max_cycles,
            (unsigned long)m->first_start_cycle,
            (unsigned long)m->last_end_cycle,
            total_us, min_us, max_us, first_start_us, last_end_us);
        write_line(line);
    }

    for (i = 0U; i < (unsigned int)s_snapshot.x509_verify_invocation_count; ++i) {
        const PQC_TLSInvocationTiming *record = &s_snapshot.x509_verify_invocations[i];
        char start_us[21];
        char end_us[21];
        char elapsed_us[21];
        PQC_TLS_FormatU64(record->start_us, start_us, sizeof(start_us));
        PQC_TLS_FormatU64(record->end_us, end_us, sizeof(end_us));
        PQC_TLS_FormatU64(record->elapsed_us, elapsed_us, sizeof(elapsed_us));
        (void)snprintf(line, sizeof(line),
            "PQC_TLS_X509_VERIFY sequence=%u start_cycle=%lu end_cycle=%lu "
            "elapsed_cycles=%lu start_us=%s end_us=%s elapsed_us=%s "
            "timing_source=dwt_cycles elapsed_time_source=monotonic_us scope=duration_only\r\n",
            i + 1U,
            (unsigned long)record->start_cycle,
            (unsigned long)record->end_cycle,
            (unsigned long)record->elapsed_cycles,
            start_us, end_us, elapsed_us);
        write_line(line);
    }
    if (s_snapshot.x509_verify_invocation_overflow != 0U) {
        (void)snprintf(line, sizeof(line),
            "PQC_TLS_X509_VERIFY overflow=1 capacity=%u\r\n",
            (unsigned int)PQC_TLS_X509_VERIFY_INVOCATION_CAPACITY);
        write_line(line);
    }
}
