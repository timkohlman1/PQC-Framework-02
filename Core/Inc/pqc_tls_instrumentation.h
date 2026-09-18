#ifndef PQC_TLS_INSTRUMENTATION_H
#define PQC_TLS_INSTRUMENTATION_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Semantic timing events are intentionally expressed through one generic
 * begin/end API. The event identifier defines the meaning and hierarchy of a
 * measurement; the API owns clock capture and bounded recording.
 */
typedef enum
{
    PQC_TLS_EVENT_HANDSHAKE = 0,

    PQC_TLS_PHASE_SERVER_HELLO,
    PQC_TLS_PHASE_ENCRYPTED_EXTENSIONS,
    PQC_TLS_PHASE_CERTIFICATE,
    PQC_TLS_PHASE_CERTIFICATE_VERIFY,
    PQC_TLS_PHASE_FINISHED,

    PQC_TLS_PRIMITIVE_P256_KEYGEN,
    PQC_TLS_PRIMITIVE_P256_SHARED_SECRET,
    PQC_TLS_PRIMITIVE_P384_KEYGEN,
    PQC_TLS_PRIMITIVE_P384_SHARED_SECRET,
    PQC_TLS_PRIMITIVE_P521_KEYGEN,
    PQC_TLS_PRIMITIVE_P521_SHARED_SECRET,
    PQC_TLS_PRIMITIVE_X25519_KEYGEN,
    PQC_TLS_PRIMITIVE_X25519_SHARED_SECRET,
    PQC_TLS_PRIMITIVE_MLKEM512_KEYGEN,
    PQC_TLS_PRIMITIVE_MLKEM512_DECAPSULATE,
    PQC_TLS_PRIMITIVE_MLKEM768_KEYGEN,
    PQC_TLS_PRIMITIVE_MLKEM768_DECAPSULATE,
    PQC_TLS_PRIMITIVE_MLKEM1024_KEYGEN,
    PQC_TLS_PRIMITIVE_MLKEM1024_DECAPSULATE,
    PQC_TLS_PRIMITIVE_RSA_VERIFY,
    PQC_TLS_PRIMITIVE_RSA_SIGN,
    PQC_TLS_PRIMITIVE_ECDSA_VERIFY,
    PQC_TLS_PRIMITIVE_ECDSA_SIGN,
    PQC_TLS_PRIMITIVE_MLDSA65_VERIFY,
    PQC_TLS_PRIMITIVE_MLDSA65_SIGN,
    PQC_TLS_PRIMITIVE_SHA256,
    PQC_TLS_PRIMITIVE_SHA384,
    PQC_TLS_PRIMITIVE_HKDF_EXTRACT,
    PQC_TLS_PRIMITIVE_HKDF_EXPAND,
    PQC_TLS_PRIMITIVE_X509_VERIFY,

    PQC_TLS_EVENT_COUNT
} PQC_TLSInstrumentationEvent;

#define PQC_TLS_PHASE_FIRST      PQC_TLS_PHASE_SERVER_HELLO
#define PQC_TLS_PHASE_LAST       PQC_TLS_PHASE_FINISHED
#define PQC_TLS_PHASE_COUNT      ((uint32_t)(PQC_TLS_PHASE_LAST - PQC_TLS_PHASE_FIRST + 1))
#define PQC_TLS_PRIMITIVE_FIRST  PQC_TLS_PRIMITIVE_P256_KEYGEN
#define PQC_TLS_PRIMITIVE_LAST   PQC_TLS_PRIMITIVE_X509_VERIFY
#define PQC_TLS_PRIMITIVE_COUNT  ((uint32_t)(PQC_TLS_PRIMITIVE_LAST - PQC_TLS_PRIMITIVE_FIRST + 1))

#define PQC_TLS_INSTRUMENTATION_RESULT_UNSPECIFIED ((int32_t)INT32_MIN)

typedef struct
{
    uint32_t count;
    uint32_t total_cycles;
    uint32_t min_cycles;
    uint32_t max_cycles;
    uint32_t first_start_cycle;
    uint32_t last_end_cycle;
    uint64_t total_us;
    uint64_t min_us;
    uint64_t max_us;
    uint64_t first_start_us;
    uint64_t last_end_us;
} PQC_TLSTimingAggregate;

#define PQC_TLS_X509_VERIFY_INVOCATION_CAPACITY 4U

typedef struct
{
    uint32_t start_cycle;
    uint32_t end_cycle;
    uint32_t elapsed_cycles;
    uint64_t start_us;
    uint64_t end_us;
    uint64_t elapsed_us;
} PQC_TLSInvocationTiming;

typedef struct
{
    uint32_t handshake_start_cycle;
    uint32_t handshake_end_cycle;
    uint32_t handshake_elapsed_cycles;
    uint64_t handshake_start_us;
    uint64_t handshake_end_us;
    uint64_t handshake_elapsed_us;
    uint32_t stack_before_min_free_bytes;
    uint32_t stack_after_min_free_bytes;
    uint32_t heap_before_free_bytes;
    uint32_t heap_before_min_ever_free_bytes;
    uint32_t heap_after_free_bytes;
    uint32_t heap_after_min_ever_free_bytes;
    int handshake_result;
    uint8_t cycle_counter_available;
    uint8_t timebase_available;
    uint8_t x509_verify_invocation_count;
    uint8_t x509_verify_invocation_overflow;
    PQC_TLSTimingAggregate phases[PQC_TLS_PHASE_COUNT];
    PQC_TLSTimingAggregate primitives[PQC_TLS_PRIMITIVE_COUNT];
    PQC_TLSInvocationTiming x509_verify_invocations[PQC_TLS_X509_VERIFY_INVOCATION_CAPACITY];
} PQC_TLSInstrumentationSnapshot;

void PQC_TLS_InstrumentationSetPreMemory(
    uint32_t stack_min_free_bytes,
    uint32_t heap_free_bytes,
    uint32_t heap_min_ever_free_bytes);

void PQC_TLS_InstrumentationBegin(PQC_TLSInstrumentationEvent event);
void PQC_TLS_InstrumentationEnd(PQC_TLSInstrumentationEvent event, int32_t result);

void PQC_TLS_InstrumentationSetPostMemory(
    uint32_t stack_min_free_bytes,
    uint32_t heap_free_bytes,
    uint32_t heap_min_ever_free_bytes);

const PQC_TLSInstrumentationSnapshot *PQC_TLS_InstrumentationSnapshot(void);
void PQC_TLS_InstrumentationReport(void (*write_line)(const char *text));

#ifdef __cplusplus
}
#endif

#endif
