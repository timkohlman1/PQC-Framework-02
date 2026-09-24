#ifndef PQC_BAREMETAL_BENCHMARK_H
#define PQC_BAREMETAL_BENCHMARK_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* This module owns only the measurement window and a bounded raw record store.
 * The caller owns algorithm setup, correctness validation and reporting. */
#define PQC_BENCHMARK_RECORD_CAPACITY 96U
#define PQC_BENCHMARK_OPERATION_MAX 32U
#define PQC_BENCHMARK_PARAMETER_MAX 24U
#define PQC_BENCHMARK_SCHEMA_VERSION 1U

typedef enum {
    PQC_BENCHMARK_OK = 0,
    PQC_BENCHMARK_UNAVAILABLE = 1,
    PQC_BENCHMARK_OPERATION_FAILED = 2,
    PQC_BENCHMARK_INVALID_MEASUREMENT = 3
} PQC_BenchmarkOutcome;

typedef struct {
    uint32_t (*cycles)(void *context);
    uint32_t (*irq_save_disable)(void *context);
    void (*irq_restore)(void *context, uint32_t previous);
    /* Return zero on success; operation body only. */
    int (*operation)(void *context);
    void *context;
} PQC_BenchmarkHooks;

typedef struct {
    char operation[PQC_BENCHMARK_OPERATION_MAX];
    char parameter[PQC_BENCHMARK_PARAMETER_MAX];
    uint32_t iteration;
    uint32_t cycles;
    int32_t operation_result;
    PQC_BenchmarkOutcome outcome;
    uint8_t interrupts_masked;
} PQC_BenchmarkRecord;

typedef struct {
    PQC_BenchmarkRecord records[PQC_BENCHMARK_RECORD_CAPACITY];
    uint32_t count;
    uint32_t dropped;
    uint8_t overflowed;
} PQC_BenchmarkStore;

void PQC_BenchmarkReset(PQC_BenchmarkStore *store);
/* Returns false when a record could not be retained, including a null store. */
bool PQC_BenchmarkRun(PQC_BenchmarkStore *store,
                      const char *operation, const char *parameter,
                      uint32_t iteration, const PQC_BenchmarkHooks *hooks,
                      bool available);
/* Preserve setup and validation failures without inventing a cycle count. */
bool PQC_BenchmarkRecordFailure(PQC_BenchmarkStore *store,
                                const char *operation, const char *parameter,
                                uint32_t iteration, int result);
/* Only use after all sensitive measurements have finished. */
bool PQC_BenchmarkReport(const PQC_BenchmarkStore *store,
                         bool (*emit)(uint32_t iteration, const char *context,
                                      const char *text));

#endif
