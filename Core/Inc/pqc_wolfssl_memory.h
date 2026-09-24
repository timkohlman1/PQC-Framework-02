#ifndef PQC_WOLFSSL_MEMORY_H
#define PQC_WOLFSSL_MEMORY_H

#include <stdbool.h>
#include <stddef.h>

void *PQC_WolfSSL_TrackedMalloc(
    size_t size, void *heap, int type,
    const char *function, const char *file, unsigned int line);
void *PQC_WolfSSL_TrackedRealloc(
    void *pointer, size_t size, void *heap, int type,
    const char *function, const char *file, unsigned int line);
void PQC_WolfSSL_TrackedFree(
    void *pointer, void *heap, int type,
    const char *function, const char *file, unsigned int line);

typedef void (*PQC_WolfSSLMemoryDiagnosticWriter)(const char *text);

typedef struct {
    bool configured;
    int configure_result;
    size_t allocation_failures;
    size_t last_failed_request_bytes;
    size_t free_heap_bytes;
    size_t minimum_ever_free_heap_bytes;
    size_t largest_free_block_bytes;
    size_t free_block_count;
    bool allocation_active;
    size_t pending_request_bytes;
    size_t pending_total_bytes;
    size_t mldsa_workspace_size_bytes;
    size_t mldsa_workspace_request_bytes;
    bool mldsa_workspace_in_use;
    size_t mldsa_workspace_peak_request_bytes;
} PQC_WolfSSLMemorySnapshot;

/* Enables an allocator independent of FreeRTOS for the pre-scheduler phase. */
void PQC_WolfSSL_BenchmarkMemoryEnable(bool enabled);
int PQC_WolfSSL_MemoryConfigure(void);
void PQC_WolfSSL_MemorySetDiagnosticWriter(
    PQC_WolfSSLMemoryDiagnosticWriter writer);
void PQC_WolfSSL_MemorySnapshotGet(PQC_WolfSSLMemorySnapshot *snapshot);
bool PQC_WolfSSL_MemoryStatusLine(
    char *buffer,
    size_t buffer_length,
    const char *stage);

#endif
