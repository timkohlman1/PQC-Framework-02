#ifndef PQC_TLS_INSTRUMENTATION_H
#define PQC_TLS_INSTRUMENTATION_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum
{
    PQC_TLS_PHASE_SERVER_HELLO = 0,
    PQC_TLS_PHASE_ENCRYPTED_EXTENSIONS,
    PQC_TLS_PHASE_CERTIFICATE,
    PQC_TLS_PHASE_CERTIFICATE_VERIFY,
    PQC_TLS_PHASE_FINISHED,
    PQC_TLS_PHASE_COUNT
} PQC_TLSPhase;

typedef enum
{
    PQC_TLS_PRIMITIVE_P256_KEYGEN = 0,
    PQC_TLS_PRIMITIVE_P256_SHARED_SECRET,
    PQC_TLS_PRIMITIVE_P384_KEYGEN,
    PQC_TLS_PRIMITIVE_P384_SHARED_SECRET,
    PQC_TLS_PRIMITIVE_P521_KEYGEN,
    PQC_TLS_PRIMITIVE_P521_SHARED_SECRET,
    PQC_TLS_PRIMITIVE_X25519_KEYGEN,
    PQC_TLS_PRIMITIVE_X25519_SHARED_SECRET,
    PQC_TLS_PRIMITIVE_MLKEM768_KEYGEN,
    PQC_TLS_PRIMITIVE_MLKEM768_DECAPSULATE,
    PQC_TLS_PRIMITIVE_MLKEM1024_KEYGEN,
    PQC_TLS_PRIMITIVE_MLKEM1024_DECAPSULATE,
    PQC_TLS_PRIMITIVE_RSA_VERIFY,
    PQC_TLS_PRIMITIVE_RSA_SIGN,
    PQC_TLS_PRIMITIVE_MLDSA65_VERIFY,
    PQC_TLS_PRIMITIVE_MLDSA65_SIGN,
    PQC_TLS_PRIMITIVE_SHA256,
    PQC_TLS_PRIMITIVE_HKDF_EXTRACT,
    PQC_TLS_PRIMITIVE_HKDF_EXPAND,
    PQC_TLS_PRIMITIVE_X509_VERIFY,
    PQC_TLS_PRIMITIVE_COUNT
} PQC_TLSPrimitive;

typedef struct
{
    uint32_t count;
    uint32_t total_cycles;
    uint32_t min_cycles;
    uint32_t max_cycles;
    uint32_t first_start_cycle;
    uint32_t last_end_cycle;
    uint32_t first_start_tick_ms;
    uint32_t last_end_tick_ms;
} PQC_TLSTimingAggregate;

#define PQC_TLS_X509_VERIFY_INVOCATION_CAPACITY 4U

typedef struct
{
    uint32_t start_cycle;
    uint32_t end_cycle;
    uint32_t elapsed_cycles;
} PQC_TLSInvocationTiming;

typedef struct
{
    uint32_t handshake_start_cycle;
    uint32_t handshake_end_cycle;
    uint32_t handshake_elapsed_cycles;
    uint32_t handshake_start_tick_ms;
    uint32_t handshake_end_tick_ms;
    uint32_t handshake_elapsed_ms;
    uint32_t stack_before_min_free_bytes;
    uint32_t stack_after_min_free_bytes;
    uint32_t heap_before_free_bytes;
    uint32_t heap_before_min_ever_free_bytes;
    uint32_t heap_after_free_bytes;
    uint32_t heap_after_min_ever_free_bytes;
    int handshake_result;
    uint8_t cycle_counter_available;
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

void PQC_TLS_InstrumentationHandshakeBegin(void);
void PQC_TLS_InstrumentationHandshakeEnd(int result);

void PQC_TLS_InstrumentationSetPostMemory(
    uint32_t stack_min_free_bytes,
    uint32_t heap_free_bytes,
    uint32_t heap_min_ever_free_bytes);

void PQC_TLS_InstrumentationPhaseBegin(PQC_TLSPhase phase);
void PQC_TLS_InstrumentationPhaseEnd(PQC_TLSPhase phase);

void PQC_TLS_InstrumentationPrimitiveBegin(PQC_TLSPrimitive primitive);
void PQC_TLS_InstrumentationPrimitiveEnd(PQC_TLSPrimitive primitive);

const PQC_TLSInstrumentationSnapshot *PQC_TLS_InstrumentationSnapshot(void);
void PQC_TLS_InstrumentationReport(void (*write_line)(const char *text));

#ifdef __cplusplus
}
#endif

#endif
