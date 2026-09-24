#include "pqc_benchmark_stm32.h"
#include "pqc_baremetal_benchmark.h"
#include "pqc_result_buffer.h"
#include "pqc_wolfssl_memory.h"
#include "main.h"

#include <stdio.h>
#include <string.h>

#ifdef RNG
#undef RNG
#endif
#include "wolfssl/wolfcrypt/sha256.h"
#include "wolfssl/wolfcrypt/error-crypt.h"
#if defined(WOLFSSL_HAVE_MLDSA) && !defined(WOLFSSL_MLDSA_VERIFY_ONLY)
#include "wolfssl/wolfcrypt/wc_mldsa.h"
#endif
#if defined(WOLFSSL_HAVE_MLKEM)
#include "wolfssl/wolfcrypt/wc_mlkem.h"
#endif

#ifndef PQC_BENCHMARK_ITERATIONS
#define PQC_BENCHMARK_ITERATIONS 10U
#endif
#if PQC_BENCHMARK_ITERATIONS < 1 || PQC_BENCHMARK_ITERATIONS > 10
#error "PQC_BENCHMARK_ITERATIONS must be between 1 and 10"
#endif

/* No FreeRTOS, socket, UART or result-buffer calls are made by operations. */
static PQC_BenchmarkStore s_results;
static unsigned char s_input[32];
static unsigned char s_digest[WC_SHA256_DIGEST_SIZE];
static int s_setup_status;
static int s_self_test_status;
static unsigned int s_dwt_available;

typedef struct {
    unsigned int type;
#if defined(WOLFSSL_HAVE_MLKEM)
    unsigned char rand_key[WC_ML_KEM_MAKEKEY_RAND_SZ];
    unsigned char rand_enc[WC_ML_KEM_ENC_RAND_SZ];
    MlKemKey key;
    unsigned char ciphertext[WC_ML_KEM_MAX_CIPHER_TEXT_SIZE];
    unsigned char secret_enc[WC_ML_KEM_SS_SZ];
    unsigned char secret_dec[WC_ML_KEM_SS_SZ];
    word32 ciphertext_size;
#endif
} PQC_KemContext;

#if defined(WOLFSSL_HAVE_MLKEM)
static PQC_KemContext s_kem;
#endif
#if defined(WOLFSSL_HAVE_MLDSA) && !defined(WOLFSSL_MLDSA_VERIFY_ONLY)
/* Fixed, public seeds exercise deterministic wolfCrypt APIs without RNG
 * acquisition inside the measurement interval. Never use for key material. */
typedef struct {
    wc_MlDsaKey key;
    byte key_seed[MLDSA_SEED_SZ];
    byte sign_seed[MLDSA_RND_SZ];
    byte signature[WC_MLDSA_65_SIG_SIZE];
    word32 signature_len;
    int verified;
} PQC_MlDsaContext;
static PQC_MlDsaContext s_mldsa;

static int mldsa_keygen(void *context)
{
    PQC_MlDsaContext *m = (PQC_MlDsaContext *)context;
    return wc_MlDsaKey_MakeKeyFromSeed(&m->key, m->key_seed);
}
static int mldsa_sign(void *context)
{
    PQC_MlDsaContext *m = (PQC_MlDsaContext *)context;
    m->signature_len = sizeof(m->signature);
    return wc_MlDsaKey_SignCtxWithSeed(&m->key, NULL, 0U,
        m->signature, &m->signature_len, s_input, (word32)sizeof(s_input),
        m->sign_seed);
}
static int mldsa_verify(void *context)
{
    PQC_MlDsaContext *m = (PQC_MlDsaContext *)context;
    int result;
    m->verified = 0;
    result = wc_MlDsaKey_VerifyCtx(&m->key, m->signature, m->signature_len,
        NULL, 0U, s_input, (word32)sizeof(s_input), &m->verified);
    if (result != 0) return result;
    return m->verified == 1 ? 0 : -7;
}
#endif

static uint32_t stm_cycles(void *context)
{
    (void)context;
    return DWT->CYCCNT;
}
static uint32_t stm_irq_disable(void *context)
{
    uint32_t previous;
    (void)context;
    previous = __get_PRIMASK();
    __disable_irq();
    __DSB();
    __ISB();
    return previous;
}
static void stm_irq_restore(void *context, uint32_t previous)
{
    (void)context;
    __set_PRIMASK(previous);
}
static int hash_operation(void *context)
{
    wc_Sha256 sha;
    int result;

    (void)context;
    result = wc_InitSha256(&sha);
    if (result == 0) {
        result = wc_Sha256Update(&sha, s_input, (word32)sizeof(s_input));
        if (result == 0)
            result = wc_Sha256Final(&sha, s_digest);
    }
    wc_Sha256Free(&sha);
    return result;
}
#if defined(WOLFSSL_HAVE_MLKEM)
static int kem_keygen(void *context)
{
    PQC_KemContext *k = (PQC_KemContext *)context;
    return wc_MlKemKey_MakeKeyWithRandom(&k->key, k->rand_key,
                                         WC_ML_KEM_MAKEKEY_RAND_SZ);
}
static int kem_encapsulate(void *context)
{
    PQC_KemContext *k = (PQC_KemContext *)context;
    return wc_MlKemKey_EncapsulateWithRandom(&k->key, k->ciphertext,
             k->secret_enc, k->rand_enc, WC_ML_KEM_ENC_RAND_SZ);
}
static int kem_decapsulate(void *context)
{
    PQC_KemContext *k = (PQC_KemContext *)context;
    return wc_MlKemKey_Decapsulate(&k->key, k->secret_dec,
                                   k->ciphertext, k->ciphertext_size);
}
#endif

static void record_unavailable(const char *operation, const char *parameter,
                               uint32_t iteration)
{
    (void)PQC_BenchmarkRun(&s_results, operation, parameter, iteration, NULL, false);
}
static void record_failure(const char *operation, const char *parameter,
                           uint32_t iteration, int result)
{
    (void)PQC_BenchmarkRecordFailure(&s_results, operation, parameter,
                                     iteration, result);
}
static void measure(const char *operation, const char *parameter,
                    uint32_t iteration, int (*function)(void *), void *context)
{
    PQC_BenchmarkHooks hooks = {
        stm_cycles, stm_irq_disable, stm_irq_restore, function, context
    };
    if (s_dwt_available == 0U) {
        /* DWT is unavailable, not a failed cryptographic operation. */
        (void)PQC_BenchmarkRun(&s_results, operation, parameter,
                               iteration, NULL, true);
    } else {
        (void)PQC_BenchmarkRun(&s_results, operation, parameter,
                                iteration, &hooks, true);
        /* Zero cycles is not evidence that a real cryptographic operation
         * completed instantaneously. Treat it as an invalid measurement. */
        if (s_results.count != 0U) {
            PQC_BenchmarkRecord *r = &s_results.records[s_results.count - 1U];
            if (r->cycles == 0U || r->cycles > 0x7fffffffUL) {
                r->outcome = PQC_BENCHMARK_INVALID_MEASUREMENT;
            }
        }
    }
}

static void measure_kem(int type, const char *parameter, uint32_t iteration,
                        int compiled)
{
    static const char *operations[] = {
        "mlkem_keygen", "mlkem_encapsulate", "mlkem_decapsulate"
    };
    unsigned int index;
    if (!compiled) {
        if (iteration == 0U) {
            for (index = 0U; index < 3U; ++index)
                record_unavailable(operations[index], parameter, iteration);
        }
        return;
    }
#if defined(WOLFSSL_HAVE_MLKEM)
    memset(&s_kem, 0, sizeof(s_kem));
    for (index = 0U; index < sizeof(s_kem.rand_key); ++index)
        s_kem.rand_key[index] = (unsigned char)(index + iteration + 1U);
    for (index = 0U; index < sizeof(s_kem.rand_enc); ++index)
        s_kem.rand_enc[index] = (unsigned char)(index + iteration + 73U);
    s_setup_status = wc_MlKemKey_Init(&s_kem.key, type, NULL, INVALID_DEVID);
    if (s_setup_status != 0) {
        for (index = 0U; index < 3U; ++index) {
            if (s_setup_status == NOT_COMPILED_IN)
                record_unavailable(operations[index], parameter, iteration);
            else
                record_failure(operations[index], parameter, iteration, s_setup_status);
        }
        return;
    }
    s_setup_status = wc_MlKemKey_CipherTextSize(&s_kem.key, &s_kem.ciphertext_size);
    if (s_setup_status != 0 || s_kem.ciphertext_size > sizeof(s_kem.ciphertext)) {
        for (index = 0U; index < 3U; ++index)
            record_failure(operations[index], parameter, iteration, s_setup_status != 0 ? s_setup_status : -2);
        (void)wc_MlKemKey_Free(&s_kem.key);
        return;
    }
    measure(operations[0], parameter, iteration, kem_keygen, &s_kem);
    if (s_results.records[s_results.count - 1U].outcome != PQC_BENCHMARK_OK) {
        record_failure(operations[1], parameter, iteration, -3);
        record_failure(operations[2], parameter, iteration, -3);
    } else {
        measure(operations[1], parameter, iteration, kem_encapsulate, &s_kem);
        if (s_results.records[s_results.count - 1U].outcome != PQC_BENCHMARK_OK) {
            record_failure(operations[2], parameter, iteration, -4);
        } else {
            measure(operations[2], parameter, iteration, kem_decapsulate, &s_kem);
            if (s_results.records[s_results.count - 1U].outcome == PQC_BENCHMARK_OK &&
                memcmp(s_kem.secret_enc, s_kem.secret_dec, sizeof(s_kem.secret_enc)) != 0) {
                s_results.records[s_results.count - 1U].outcome = PQC_BENCHMARK_OPERATION_FAILED;
                s_results.records[s_results.count - 1U].operation_result = -5;
                s_self_test_status = -5;
            }
        }
    }
    (void)wc_MlKemKey_Free(&s_kem.key);
    PQC_WolfSSL_BenchmarkMemoryEnable(true);
#else
    (void)type;
#endif
}

static void measure_mldsa(uint32_t iteration)
{
    static const char *operations[] = {
        "mldsa_keygen", "mldsa_sign", "mldsa_verify"
    };
#if defined(WOLFSSL_HAVE_MLDSA) && !defined(WOLFSSL_MLDSA_VERIFY_ONLY)
    unsigned int index;
    PQC_BenchmarkRecord *record;
    memset(&s_mldsa, 0, sizeof(s_mldsa));
    for (index = 0U; index < sizeof(s_mldsa.key_seed); ++index)
        s_mldsa.key_seed[index] = (byte)(index + iteration + 19U);
    for (index = 0U; index < sizeof(s_mldsa.sign_seed); ++index)
        s_mldsa.sign_seed[index] = (byte)(index + iteration + 97U);
    s_setup_status = wc_MlDsaKey_Init(&s_mldsa.key, NULL, INVALID_DEVID);
    if (s_setup_status == 0)
        s_setup_status = wc_MlDsaKey_SetParams(&s_mldsa.key, 3U);
    if (s_setup_status != 0) {
        for (index = 0U; index < 3U; ++index)
            record_failure(operations[index], "ML_DSA_65", iteration, s_setup_status);
        wc_MlDsaKey_Free(&s_mldsa.key);
        PQC_WolfSSL_BenchmarkMemoryEnable(true);
        return;
    }
    measure(operations[0], "ML_DSA_65", iteration, mldsa_keygen, &s_mldsa);
    record = &s_results.records[s_results.count - 1U];
    if (record->outcome != PQC_BENCHMARK_OK) {
        record_failure(operations[1], "ML_DSA_65", iteration, -8);
        record_failure(operations[2], "ML_DSA_65", iteration, -8);
    } else {
        measure(operations[1], "ML_DSA_65", iteration, mldsa_sign, &s_mldsa);
        record = &s_results.records[s_results.count - 1U];
        if (record->outcome != PQC_BENCHMARK_OK ||
            s_mldsa.signature_len != WC_MLDSA_65_SIG_SIZE) {
            if (record->outcome == PQC_BENCHMARK_OK) {
                record->outcome = PQC_BENCHMARK_OPERATION_FAILED;
                record->operation_result = -9;
            }
            record_failure(operations[2], "ML_DSA_65", iteration, -9);
        } else {
            measure(operations[2], "ML_DSA_65", iteration, mldsa_verify, &s_mldsa);
        }
    }
    wc_MlDsaKey_Free(&s_mldsa.key);
    /* All key-owned scratch allocations are freed before resetting arena. */
    PQC_WolfSSL_BenchmarkMemoryEnable(true);
    memset(&s_mldsa, 0, sizeof(s_mldsa));
#else
    if (iteration == 0U) {
        unsigned int index;
        for (index = 0U; index < 3U; ++index)
            record_unavailable(operations[index], "ML_DSA_65", iteration);
    }
#endif
}

void PQC_BenchmarkSTM32_Run(void)
{
    uint32_t iteration;
    unsigned int index;
    PQC_BenchmarkReset(&s_results);
    s_self_test_status = 0;
    s_setup_status = 0;
    for (index = 0U; index < sizeof(s_input); ++index)
        s_input[index] = (unsigned char)index;
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0U;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
    s_dwt_available = (DWT->CTRL & DWT_CTRL_CYCCNTENA_Msk) != 0U;
    /* wolfCrypt uses a dedicated fixed-size allocator throughout this phase;
     * it is deactivated before the RTOS/reporting phase starts. */
    PQC_WolfSSL_BenchmarkMemoryEnable(true);
    for (iteration = 0U; iteration < PQC_BENCHMARK_ITERATIONS; ++iteration) {
        static const unsigned char expected_sha256[WC_SHA256_DIGEST_SIZE] = {
            0x63, 0x0d, 0xcd, 0x29, 0x66, 0xc4, 0x33, 0x66,
            0x91, 0x12, 0x54, 0x48, 0xbb, 0xb2, 0x5b, 0x4f,
            0xf4, 0x12, 0xa4, 0x9c, 0x73, 0x2d, 0xb2, 0xc8,
            0xab, 0xc1, 0xb8, 0x58, 0x1b, 0xd7, 0x10, 0xdd
        };
        measure("sha256_hash", "32_bytes", iteration, hash_operation, NULL);
        if (s_results.count != 0U &&
            s_results.records[s_results.count - 1U].outcome == PQC_BENCHMARK_OK &&
            memcmp(s_digest, expected_sha256, sizeof(expected_sha256)) != 0) {
            s_results.records[s_results.count - 1U].outcome = PQC_BENCHMARK_OPERATION_FAILED;
            s_results.records[s_results.count - 1U].operation_result = -6;
            s_self_test_status = -6;
        }
        /* Every requested parameter has a record, even when not compiled. */
#if defined(PQC_TLS_ENABLE_MLKEM_512) && PQC_TLS_ENABLE_MLKEM_512
        measure_kem(WC_ML_KEM_512, "ML_KEM_512", iteration, 1);
#else
        measure_kem(0, "ML_KEM_512", iteration, 0);
#endif
#if defined(PQC_TLS_ENABLE_MLKEM_768) && PQC_TLS_ENABLE_MLKEM_768
        measure_kem(WC_ML_KEM_768, "ML_KEM_768", iteration, 1);
#else
        measure_kem(0, "ML_KEM_768", iteration, 0);
#endif
#if defined(PQC_TLS_ENABLE_MLKEM_1024) && PQC_TLS_ENABLE_MLKEM_1024
        measure_kem(WC_ML_KEM_1024, "ML_KEM_1024", iteration, 1);
#else
        measure_kem(0, "ML_KEM_1024", iteration, 0);
#endif
        measure_mldsa(iteration);
    }
    /* The summary must not report success if an earlier repetition failed. */
    for (index = 0U; index < s_results.count; ++index) {
        if (s_self_test_status == 0 &&
            s_results.records[index].outcome != PQC_BENCHMARK_OK &&
            s_results.records[index].outcome != PQC_BENCHMARK_UNAVAILABLE)
            s_self_test_status = -10;
    }
    if (s_results.dropped != 0U || s_results.overflowed != 0U)
        s_self_test_status = -11;
    PQC_WolfSSL_BenchmarkMemoryEnable(false);
#if defined(WOLFSSL_HAVE_MLKEM)
    memset(&s_kem, 0, sizeof(s_kem));
#endif
}

static bool append_line(uint32_t iteration, const char *context, const char *text)
{
    return PQC_ResultBufferAppendText(iteration, context, text);
}
void PQC_BenchmarkSTM32_AppendResults(void)
{
    char provenance[384];
    int size;
    /* Called strictly after the final cryptographic measurement. */
    size = snprintf(provenance, sizeof(provenance),
      "{\"type\":\"benchmark_provenance\",\"cpu\":\"cortex-m4\","
      "\"cycle_counter\":\"dwt_cyccnt_32\",\"hclk_hz\":%lu,"
      "\"interrupt_policy\":\"primask_each_operation\","
      "\"allocator\":\"dedicated_static_arena\","
      "\"rng_policy\":\"fixed_public_benchmark_seeds\","
      "\"iterations\":%u,\"setup_status\":%d,\"self_test_status\":%d}",
      (unsigned long)HAL_RCC_GetHCLKFreq(), (unsigned)PQC_BENCHMARK_ITERATIONS,
      s_setup_status, s_self_test_status);
    if (size >= 0 && (size_t)size < sizeof(provenance))
        (void)PQC_ResultBufferAppendText(0U, "baremetal_benchmark", provenance);
    (void)PQC_BenchmarkReport(&s_results, append_line);
}
