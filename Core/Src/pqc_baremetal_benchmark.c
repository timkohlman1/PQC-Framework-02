#include "pqc_baremetal_benchmark.h"

#include <stdio.h>
#include <string.h>

static void bounded_label(char *dest, size_t capacity, const char *source)
{
    size_t index = 0U;
    if (source != NULL) {
        while (index + 1U < capacity && source[index] != '\0') {
            const char c = source[index];
            /* A label is a token, not arbitrary JSON supplied by a caller. */
            dest[index] = ((c >= 'a' && c <= 'z') ||
                           (c >= 'A' && c <= 'Z') ||
                           (c >= '0' && c <= '9') ||
                           c == '_' || c == '-' || c == '.') ? c : '_';
            ++index;
        }
    }
    dest[index] = '\0';
}

void PQC_BenchmarkReset(PQC_BenchmarkStore *store)
{
    if (store != NULL) {
        memset(store, 0, sizeof(*store));
    }
}

bool PQC_BenchmarkRun(PQC_BenchmarkStore *store,
                      const char *operation, const char *parameter,
                      uint32_t iteration, const PQC_BenchmarkHooks *hooks,
                      bool available)
{
    PQC_BenchmarkRecord *record;
    uint32_t previous = 0U, begin = 0U, end = 0U;
    int result;
    if (store == NULL) return false;
    if (store->count >= PQC_BENCHMARK_RECORD_CAPACITY) {
        ++store->dropped;
        store->overflowed = 1U;
        return false;
    }
    record = &store->records[store->count++];
    memset(record, 0, sizeof(*record));
    bounded_label(record->operation, sizeof(record->operation), operation);
    bounded_label(record->parameter, sizeof(record->parameter), parameter);
    record->iteration = iteration;
    if (!available) {
        record->outcome = PQC_BENCHMARK_UNAVAILABLE;
        return true;
    }
    if (hooks == NULL || hooks->cycles == NULL || hooks->operation == NULL ||
        hooks->irq_save_disable == NULL || hooks->irq_restore == NULL) {
        record->outcome = PQC_BENCHMARK_INVALID_MEASUREMENT;
        return true;
    }
    /* The caller must initialise the DWT and the cryptographic inputs first.
     * Save PRIMASK, mask IRQs, then read DWT. No formatting, allocation, or
     * reporting is performed between the cycle reads. */
    previous = hooks->irq_save_disable(hooks->context);
    begin = hooks->cycles(hooks->context);
    result = hooks->operation(hooks->context);
    end = hooks->cycles(hooks->context);
    hooks->irq_restore(hooks->context, previous);
    record->interrupts_masked = 1U;
    record->operation_result = result;
    /* Unsigned subtraction supports a single 32-bit DWT wrap. A duration
     * spanning one full counter period cannot be distinguished from a short
     * duration by this module; callers must bound operations accordingly. */
    record->cycles = end - begin;
    record->outcome = result == 0 ? PQC_BENCHMARK_OK : PQC_BENCHMARK_OPERATION_FAILED;
    return true;
}

bool PQC_BenchmarkRecordFailure(PQC_BenchmarkStore *store,
                                const char *operation, const char *parameter,
                                uint32_t iteration, int result)
{
    PQC_BenchmarkRecord *record;
    if (store == NULL) return false;
    if (store->count >= PQC_BENCHMARK_RECORD_CAPACITY) {
        ++store->dropped;
        store->overflowed = 1U;
        return false;
    }
    record = &store->records[store->count++];
    memset(record, 0, sizeof(*record));
    bounded_label(record->operation, sizeof(record->operation), operation);
    bounded_label(record->parameter, sizeof(record->parameter), parameter);
    record->iteration = iteration;
    record->operation_result = result;
    record->outcome = PQC_BENCHMARK_OPERATION_FAILED;
    return true;
}

bool PQC_BenchmarkReport(const PQC_BenchmarkStore *store,
                         bool (*emit)(uint32_t, const char *, const char *))
{
    uint32_t index;
    char line[320];
    int size;
    if (store == NULL || emit == NULL) return false;
    for (index = 0U; index < store->count; ++index) {
        const PQC_BenchmarkRecord *record = &store->records[index];
        const char *reason =
            record->outcome == PQC_BENCHMARK_UNAVAILABLE ?
                "algorithm_not_compiled" :
            record->outcome == PQC_BENCHMARK_INVALID_MEASUREMENT ?
                "invalid_counter_or_hooks" :
            record->outcome == PQC_BENCHMARK_OPERATION_FAILED ?
                "cryptographic_operation_or_setup_failed" : "none";
        size = snprintf(line, sizeof(line),
                        "{\"benchmark_schema\":%u,\"operation\":\"%s\","
                        "\"parameter\":\"%s\",\"iteration\":%lu,"
                        "\"cycles\":%lu,\"result\":%ld,\"outcome\":%u,"
                        "\"interrupts_masked\":%u,\"reason\":\"%s\"}",
                        PQC_BENCHMARK_SCHEMA_VERSION, record->operation,
                        record->parameter, (unsigned long)record->iteration,
                        (unsigned long)record->cycles, (long)record->operation_result,
                        (unsigned)record->outcome, (unsigned)record->interrupts_masked,
                        reason);
        if (size < 0 || (size_t)size >= sizeof(line) ||
            !emit(record->iteration, "baremetal_benchmark", line)) return false;
    }
    size = snprintf(line, sizeof(line),
                    "{\"benchmark_schema\":%u,\"type\":\"complete\","
                    "\"records\":%lu,\"dropped\":%lu,\"overflowed\":%u}",
                    PQC_BENCHMARK_SCHEMA_VERSION, (unsigned long)store->count,
                    (unsigned long)store->dropped, (unsigned)store->overflowed);
    return size >= 0 && (size_t)size < sizeof(line) && emit(0U, "baremetal_benchmark", line);
}
