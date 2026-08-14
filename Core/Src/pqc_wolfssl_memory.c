#include "pqc_wolfssl_memory.h"

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "FreeRTOS.h"
#include "portable.h"
#include "task.h"

#ifdef RNG
#undef RNG
#endif
#include "wolfssl/wolfcrypt/types.h"

#ifndef PQC_WOLFSSL_MEMORY_DIAGNOSTICS
#define PQC_WOLFSSL_MEMORY_DIAGNOSTICS 0
#endif
#ifndef PQC_WOLFSSL_ALLOCATION_PROVENANCE
#define PQC_WOLFSSL_ALLOCATION_PROVENANCE 0
#endif
#ifndef PQC_MLDSA_WORKSPACE_SIZE_BYTES
#define PQC_MLDSA_WORKSPACE_SIZE_BYTES (64U * 1024U)
#endif
#ifndef PQC_TLS_ENABLE_MLDSA_65
#define PQC_TLS_ENABLE_MLDSA_65 0
#endif

#define PQC_MLDSA_WORKSPACE_MIN_REQUEST_BYTES (32U * 1024U)
#if PQC_WOLFSSL_ALLOCATION_PROVENANCE
#define PQC_WOLFSSL_LARGE_ALLOCATION_DIAGNOSTIC_THRESHOLD 4096U
#endif

/*
 * Normal wolfSSL allocations use FreeRTOS heap_4. Large ML-DSA scratch
 * requests use one fixed RAM3 workspace so repeated ~48 KiB work buffers do
 * not fragment or exhaust the application heap.
 */
typedef union {
    struct {
        size_t allocation_size;
#if PQC_WOLFSSL_ALLOCATION_PROVENANCE
        uint32_t allocation_sequence;
        int allocation_type;
        unsigned int allocation_line;
        const char *allocation_file;
        const char *allocation_function;
#endif
    } metadata;
    max_align_t alignment;
} PQC_WolfSSLAllocationHeader;

#if PQC_TLS_ENABLE_MLDSA_65
static uint8_t s_mldsa_workspace[PQC_MLDSA_WORKSPACE_SIZE_BYTES]
    __attribute__((section(".pqc_mldsa_workspace"), aligned(8)));
static volatile bool s_mldsa_workspace_in_use;
static volatile size_t s_mldsa_workspace_request_bytes;
static size_t s_mldsa_workspace_peak_request_bytes;
#endif

static bool s_configured;
static int s_configure_result;

#if PQC_WOLFSSL_MEMORY_DIAGNOSTICS
static size_t s_allocation_failures;
static size_t s_last_failed_request_bytes;
static size_t s_failure_free_heap_bytes;
static size_t s_failure_minimum_ever_free_heap_bytes;
static size_t s_failure_largest_free_block_bytes;
static size_t s_failure_free_block_count;
static volatile bool s_allocation_active;
static volatile size_t s_pending_request_bytes;
static volatile size_t s_pending_total_bytes;
static PQC_WolfSSLMemoryDiagnosticWriter s_diagnostic_writer;
#endif

#if PQC_WOLFSSL_ALLOCATION_PROVENANCE
static uint32_t s_allocation_sequence;
static size_t s_outstanding_wolfssl_bytes;
static size_t s_peak_outstanding_wolfssl_bytes;
#endif

static bool PQC_WolfSSL_IsRAM3WorkspacePointer(const void *pointer)
{
#if PQC_TLS_ENABLE_MLDSA_65
    return pointer == (const void *)s_mldsa_workspace;
#else
    (void)pointer;
    return false;
#endif
}

static bool PQC_WolfSSL_IsLargeMlDsaRequest(size_t size, int type)
{
#if PQC_TLS_ENABLE_MLDSA_65
    return (type == DYNAMIC_TYPE_MLDSA) &&
           (size >= PQC_MLDSA_WORKSPACE_MIN_REQUEST_BYTES);
#else
    (void)size;
    (void)type;
    return false;
#endif
}

static void *PQC_WolfSSL_ClaimMlDsaWorkspace(size_t size)
{
#if PQC_TLS_ENABLE_MLDSA_65
    bool claimed = false;

    /*
     * Record the largest capacity wolfSSL requested even when the request
     * exceeds the configured workspace. This makes the end-of-experiment
     * high-watermark useful for sizing and catches insufficient headroom.
     */
    taskENTER_CRITICAL();
    if (size > s_mldsa_workspace_peak_request_bytes) {
        s_mldsa_workspace_peak_request_bytes = size;
    }
    taskEXIT_CRITICAL();

    if (size > sizeof(s_mldsa_workspace)) {
        return NULL;
    }

    taskENTER_CRITICAL();
    if (!s_mldsa_workspace_in_use) {
        s_mldsa_workspace_in_use = true;
        s_mldsa_workspace_request_bytes = size;
        claimed = true;
    }
    taskEXIT_CRITICAL();

    return claimed ? (void *)s_mldsa_workspace : NULL;
#else
    (void)size;
    return NULL;
#endif
}

static void PQC_WolfSSL_ReleaseMlDsaWorkspace(void)
{
#if PQC_TLS_ENABLE_MLDSA_65
    taskENTER_CRITICAL();
    s_mldsa_workspace_request_bytes = 0U;
    s_mldsa_workspace_in_use = false;
    taskEXIT_CRITICAL();
#endif
}

#if PQC_WOLFSSL_MEMORY_DIAGNOSTICS
static char *PQC_WolfSSL_AppendText(char *cursor, char *end, const char *text)
{
    if (text == NULL) {
        text = "unknown";
    }

    while ((cursor < end) && (*text != '\0')) {
        *cursor++ = *text++;
    }
    return cursor;
}

static char *PQC_WolfSSL_AppendSize(char *cursor, char *end, size_t value)
{
    char digits[3U * sizeof(size_t)];
    size_t count = 0U;

    do {
        digits[count++] = (char)('0' + (value % 10U));
        value /= 10U;
    } while ((value != 0U) && (count < sizeof(digits)));

    while ((count != 0U) && (cursor < end)) {
        *cursor++ = digits[--count];
    }
    return cursor;
}

static char *PQC_WolfSSL_AppendInt(char *cursor, char *end, int value)
{
    unsigned int magnitude;

    if (value < 0) {
        if (cursor < end) {
            *cursor++ = '-';
        }
        magnitude = (unsigned int)(-(value + 1)) + 1U;
    }
    else {
        magnitude = (unsigned int)value;
    }

    return PQC_WolfSSL_AppendSize(cursor, end, (size_t)magnitude);
}

#if PQC_WOLFSSL_ALLOCATION_PROVENANCE
static const char *PQC_WolfSSL_BaseName(const char *file)
{
    const char *base = file;

    if (file == NULL) {
        return "unknown";
    }

    while (*file != '\0') {
        if ((*file == '/') || (*file == '\\')) {
            base = file + 1;
        }
        file++;
    }
    return base;
}

static const char *PQC_WolfSSL_DynamicTypeName(int type)
{
    switch (type) {
        case DYNAMIC_TYPE_CA: return "CA";
        case DYNAMIC_TYPE_CERT: return "CERT";
        case DYNAMIC_TYPE_KEY: return "KEY";
        case DYNAMIC_TYPE_PUBLIC_KEY: return "PUBLIC_KEY";
        case DYNAMIC_TYPE_SIGNER: return "SIGNER";
        case DYNAMIC_TYPE_OUT_BUFFER: return "OUT_BUFFER";
        case DYNAMIC_TYPE_IN_BUFFER: return "IN_BUFFER";
        case DYNAMIC_TYPE_SSL: return "SSL";
        case DYNAMIC_TYPE_CTX: return "CTX";
        case DYNAMIC_TYPE_RNG: return "RNG";
        case DYNAMIC_TYPE_ARRAYS: return "ARRAYS";
        case DYNAMIC_TYPE_ECC: return "ECC";
        case DYNAMIC_TYPE_TMP_BUFFER: return "TMP_BUFFER";
        case DYNAMIC_TYPE_X509: return "X509";
        case DYNAMIC_TYPE_TLSX: return "TLSX";
        case DYNAMIC_TYPE_SIGNATURE: return "SIGNATURE";
        case DYNAMIC_TYPE_PRIVATE_KEY: return "PRIVATE_KEY";
        case DYNAMIC_TYPE_PEM: return "PEM";
        case DYNAMIC_TYPE_DER: return "DER";
        case DYNAMIC_TYPE_HASH_TMP: return "HASH_TMP";
        case DYNAMIC_TYPE_MLDSA: return "MLDSA";
        default: return "OTHER";
    }
}
#endif

static void PQC_WolfSSL_RecordAllocationFailure(size_t requested_bytes)
{
    HeapStats_t stats;

    memset(&stats, 0, sizeof(stats));
    vPortGetHeapStats(&stats);

    s_allocation_failures++;
    s_last_failed_request_bytes = requested_bytes;
    s_failure_free_heap_bytes = xPortGetFreeHeapSize();
    s_failure_minimum_ever_free_heap_bytes =
        xPortGetMinimumEverFreeHeapSize();
    s_failure_largest_free_block_bytes =
        stats.xSizeOfLargestFreeBlockInBytes;
    s_failure_free_block_count = stats.xNumberOfFreeBlocks;
}

#if PQC_WOLFSSL_ALLOCATION_PROVENANCE
static void PQC_WolfSSL_WriteLargeAllocation(
    const char *operation,
    uint32_t sequence,
    size_t requested_bytes,
    size_t total_bytes,
    int type,
    const char *function,
    const char *file,
    unsigned int line,
    const char *allocator)
{
    char marker[448];
    char *cursor = marker;
    char *end = marker + sizeof(marker) - 3U;

    if ((s_diagnostic_writer == NULL) ||
        (requested_bytes < PQC_WOLFSSL_LARGE_ALLOCATION_DIAGNOSTIC_THRESHOLD)) {
        return;
    }

    cursor = PQC_WolfSSL_AppendText(cursor, end, "PQC_WOLFSSL_ALLOC seq=");
    cursor = PQC_WolfSSL_AppendSize(cursor, end, sequence);
    cursor = PQC_WolfSSL_AppendText(cursor, end, " op=");
    cursor = PQC_WolfSSL_AppendText(cursor, end, operation);
    cursor = PQC_WolfSSL_AppendText(cursor, end, " requested_bytes=");
    cursor = PQC_WolfSSL_AppendSize(cursor, end, requested_bytes);
    cursor = PQC_WolfSSL_AppendText(cursor, end, " total_bytes=");
    cursor = PQC_WolfSSL_AppendSize(cursor, end, total_bytes);
    cursor = PQC_WolfSSL_AppendText(cursor, end, " allocator=");
    cursor = PQC_WolfSSL_AppendText(cursor, end, allocator);
    cursor = PQC_WolfSSL_AppendText(cursor, end, " type=");
    cursor = PQC_WolfSSL_AppendInt(cursor, end, type);
    cursor = PQC_WolfSSL_AppendText(cursor, end, " type_name=");
    cursor = PQC_WolfSSL_AppendText(cursor, end, PQC_WolfSSL_DynamicTypeName(type));
    cursor = PQC_WolfSSL_AppendText(cursor, end, " file=");
    cursor = PQC_WolfSSL_AppendText(cursor, end, PQC_WolfSSL_BaseName(file));
    cursor = PQC_WolfSSL_AppendText(cursor, end, " line=");
    cursor = PQC_WolfSSL_AppendSize(cursor, end, line);
    cursor = PQC_WolfSSL_AppendText(cursor, end, " function=");
    cursor = PQC_WolfSSL_AppendText(cursor, end, function);
    cursor = PQC_WolfSSL_AppendText(cursor, end, " outstanding_before=");
    cursor = PQC_WolfSSL_AppendSize(cursor, end, s_outstanding_wolfssl_bytes);
    cursor = PQC_WolfSSL_AppendText(cursor, end, " peak_bytes=");
    cursor = PQC_WolfSSL_AppendSize(cursor, end, s_peak_outstanding_wolfssl_bytes);
    cursor = PQC_WolfSSL_AppendText(cursor, end, "\r\n");
    *cursor = '\0';

    s_diagnostic_writer(marker);
}
#endif
#else
static void PQC_WolfSSL_RecordAllocationFailure(size_t requested_bytes)
{
    (void)requested_bytes;
}
#endif

void *PQC_WolfSSL_TrackedMalloc(
    size_t size,
    void *heap,
    int type,
    const char *function,
    const char *file,
    unsigned int line)
{
    PQC_WolfSSLAllocationHeader *header;
    size_t total_bytes;

    (void)heap;
#if !PQC_WOLFSSL_ALLOCATION_PROVENANCE
    (void)function;
    (void)file;
    (void)line;
#endif

    if (PQC_WolfSSL_IsLargeMlDsaRequest(size, type)) {
#if PQC_WOLFSSL_ALLOCATION_PROVENANCE
        uint32_t sequence = ++s_allocation_sequence;
        PQC_WolfSSL_WriteLargeAllocation(
            "malloc", sequence, size, size, type, function, file, line, "ram3_workspace");
#endif
        void *workspace = PQC_WolfSSL_ClaimMlDsaWorkspace(size);
        if (workspace == NULL) {
            PQC_WolfSSL_RecordAllocationFailure(size);
        }
        return workspace;
    }

    if (size > (SIZE_MAX - sizeof(*header))) {
        PQC_WolfSSL_RecordAllocationFailure(size);
        return NULL;
    }

    total_bytes = sizeof(*header) + size;

#if PQC_WOLFSSL_MEMORY_DIAGNOSTICS
    s_pending_request_bytes = size;
    s_pending_total_bytes = total_bytes;
    s_allocation_active = true;
#endif

#if PQC_WOLFSSL_ALLOCATION_PROVENANCE
    {
        uint32_t sequence = ++s_allocation_sequence;
        PQC_WolfSSL_WriteLargeAllocation(
            "malloc", sequence, size, total_bytes, type, function, file, line, "freertos_heap4");
        header = (PQC_WolfSSLAllocationHeader *)pvPortMalloc(total_bytes);
        if (header != NULL) {
            header->metadata.allocation_sequence = sequence;
        }
    }
#else
    header = (PQC_WolfSSLAllocationHeader *)pvPortMalloc(total_bytes);
#endif

#if PQC_WOLFSSL_MEMORY_DIAGNOSTICS
    s_allocation_active = false;
    s_pending_request_bytes = 0U;
    s_pending_total_bytes = 0U;
#endif

    if (header == NULL) {
        PQC_WolfSSL_RecordAllocationFailure(size);
        return NULL;
    }

    header->metadata.allocation_size = size;
#if PQC_WOLFSSL_ALLOCATION_PROVENANCE
    header->metadata.allocation_type = type;
    header->metadata.allocation_line = line;
    header->metadata.allocation_file = file;
    header->metadata.allocation_function = function;
    s_outstanding_wolfssl_bytes += size;
    if (s_outstanding_wolfssl_bytes > s_peak_outstanding_wolfssl_bytes) {
        s_peak_outstanding_wolfssl_bytes = s_outstanding_wolfssl_bytes;
    }
#endif

    return (void *)(header + 1);
}

void PQC_WolfSSL_TrackedFree(
    void *pointer,
    void *heap,
    int type,
    const char *function,
    const char *file,
    unsigned int line)
{
    PQC_WolfSSLAllocationHeader *header;

    (void)heap;
    (void)type;
    (void)function;
    (void)file;
    (void)line;

    if (pointer == NULL) {
        return;
    }

    if (PQC_WolfSSL_IsRAM3WorkspacePointer(pointer)) {
        PQC_WolfSSL_ReleaseMlDsaWorkspace();
        return;
    }

    header = ((PQC_WolfSSLAllocationHeader *)pointer) - 1;

#if PQC_WOLFSSL_ALLOCATION_PROVENANCE
    if (s_outstanding_wolfssl_bytes >= header->metadata.allocation_size) {
        s_outstanding_wolfssl_bytes -= header->metadata.allocation_size;
    }
    else {
        s_outstanding_wolfssl_bytes = 0U;
    }
#endif

    vPortFree(header);
}

void *PQC_WolfSSL_TrackedRealloc(
    void *pointer,
    size_t size,
    void *heap,
    int type,
    const char *function,
    const char *file,
    unsigned int line)
{
    PQC_WolfSSLAllocationHeader *old_header;
    void *replacement;
    size_t old_size;
    size_t copy_size;

    if (pointer == NULL) {
        return PQC_WolfSSL_TrackedMalloc(
            size, heap, type, function, file, line);
    }

    if (size == 0U) {
        PQC_WolfSSL_TrackedFree(
            pointer, heap, type, function, file, line);
        return NULL;
    }

#if PQC_TLS_ENABLE_MLDSA_65
    if (PQC_WolfSSL_IsRAM3WorkspacePointer(pointer)) {
        old_size = s_mldsa_workspace_request_bytes;
        if (PQC_WolfSSL_IsLargeMlDsaRequest(size, type) &&
            (size <= sizeof(s_mldsa_workspace))) {
            s_mldsa_workspace_request_bytes = size;
            if (size > s_mldsa_workspace_peak_request_bytes) {
                s_mldsa_workspace_peak_request_bytes = size;
            }
            return pointer;
        }

        replacement = PQC_WolfSSL_TrackedMalloc(
            size, heap, type, function, file, line);
        if (replacement == NULL) {
            return NULL;
        }
        copy_size = old_size < size ? old_size : size;
        memcpy(replacement, pointer, copy_size);
        PQC_WolfSSL_ReleaseMlDsaWorkspace();
        return replacement;
    }
#endif

    old_header = ((PQC_WolfSSLAllocationHeader *)pointer) - 1;
    old_size = old_header->metadata.allocation_size;

    replacement = PQC_WolfSSL_TrackedMalloc(
        size, heap, type, function, file, line);
    if (replacement == NULL) {
        return NULL;
    }

    copy_size = old_size < size ? old_size : size;
    memcpy(replacement, pointer, copy_size);
    PQC_WolfSSL_TrackedFree(
        pointer, heap, type, function, file, line);
    return replacement;
}

void PQC_WolfSSL_MemorySetDiagnosticWriter(
    PQC_WolfSSLMemoryDiagnosticWriter writer)
{
#if PQC_WOLFSSL_MEMORY_DIAGNOSTICS
    s_diagnostic_writer = writer;
#else
    (void)writer;
#endif
}

int PQC_WolfSSL_MemoryConfigure(void)
{
    if (!s_configured) {
        s_configure_result = 0;
        s_configured = true;
    }
    return s_configure_result;
}

void PQC_WolfSSL_MemorySnapshotGet(PQC_WolfSSLMemorySnapshot *snapshot)
{
    HeapStats_t stats;

    if (snapshot == NULL) {
        return;
    }

    memset(snapshot, 0, sizeof(*snapshot));
    snapshot->configured = s_configured;
    snapshot->configure_result = s_configure_result;
#if PQC_TLS_ENABLE_MLDSA_65
    snapshot->mldsa_workspace_size_bytes = sizeof(s_mldsa_workspace);
    snapshot->mldsa_workspace_request_bytes = s_mldsa_workspace_request_bytes;
    snapshot->mldsa_workspace_in_use = s_mldsa_workspace_in_use;
    snapshot->mldsa_workspace_peak_request_bytes =
        s_mldsa_workspace_peak_request_bytes;
#endif

#if PQC_WOLFSSL_MEMORY_DIAGNOSTICS
    memset(&stats, 0, sizeof(stats));
    vPortGetHeapStats(&stats);

    snapshot->allocation_failures = s_allocation_failures;
    snapshot->last_failed_request_bytes = s_last_failed_request_bytes;
    snapshot->allocation_active = s_allocation_active;
    snapshot->pending_request_bytes = s_pending_request_bytes;
    snapshot->pending_total_bytes = s_pending_total_bytes;

    if (s_allocation_failures != 0U) {
        snapshot->free_heap_bytes = s_failure_free_heap_bytes;
        snapshot->minimum_ever_free_heap_bytes =
            s_failure_minimum_ever_free_heap_bytes;
        snapshot->largest_free_block_bytes =
            s_failure_largest_free_block_bytes;
        snapshot->free_block_count = s_failure_free_block_count;
    }
    else {
        snapshot->free_heap_bytes = xPortGetFreeHeapSize();
        snapshot->minimum_ever_free_heap_bytes =
            xPortGetMinimumEverFreeHeapSize();
        snapshot->largest_free_block_bytes =
            stats.xSizeOfLargestFreeBlockInBytes;
        snapshot->free_block_count = stats.xNumberOfFreeBlocks;
    }
#else
    (void)stats;
#endif
}

bool PQC_WolfSSL_MemoryStatusLine(
    char *buffer,
    size_t buffer_length,
    const char *stage)
{
#if PQC_WOLFSSL_MEMORY_DIAGNOSTICS
    PQC_WolfSSLMemorySnapshot snapshot;
    int written;

    if ((buffer == NULL) || (buffer_length == 0U) || (stage == NULL)) {
        return false;
    }

    PQC_WolfSSL_MemorySnapshotGet(&snapshot);
    written = snprintf(
        buffer,
        buffer_length,
        "PQC_WOLFSSL_MEMORY stage=%s allocator=freertos_heap4 "
        "mldsa_workspace=ram3 workspace_size_bytes=%lu "
        "workspace_peak_request_bytes=%lu configured=%d "
        "allocation_failures=%lu last_failed_request_bytes=%lu "
        "free_heap_bytes=%lu minimum_ever_free_heap_bytes=%lu "
        "largest_free_block_bytes=%lu free_block_count=%lu\r\n",
        stage,
        (unsigned long)snapshot.mldsa_workspace_size_bytes,
        (unsigned long)snapshot.mldsa_workspace_peak_request_bytes,
        snapshot.configured ? 1 : 0,
        (unsigned long)snapshot.allocation_failures,
        (unsigned long)snapshot.last_failed_request_bytes,
        (unsigned long)snapshot.free_heap_bytes,
        (unsigned long)snapshot.minimum_ever_free_heap_bytes,
        (unsigned long)snapshot.largest_free_block_bytes,
        (unsigned long)snapshot.free_block_count);

    return (written > 0) && ((size_t)written < buffer_length);
#else
    (void)buffer;
    (void)buffer_length;
    (void)stage;
    return false;
#endif
}
