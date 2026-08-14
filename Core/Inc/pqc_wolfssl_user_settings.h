#ifndef PQC_WOLFSSL_USER_SETTINGS_H
#define PQC_WOLFSSL_USER_SETTINGS_H

#define SINGLE_THREADED
#define NO_FILESYSTEM
#define NO_WRITEV
#define NO_DEV_RANDOM
#define NO_MAIN_DRIVER
#define NO_WOLFSSL_DIR
#define WOLFSSL_USER_IO
#define WOLFSSL_NO_SOCK
#define NO_ERROR_STRINGS
#define NO_OLD_TLS
#define WOLFSSL_NO_TLS12
#define WOLFSSL_NO_ASM
#define WOLFSSL_SP_MATH_ALL
#define USE_SLOW_SHA256
#define WC_NO_HARDEN
#define NO_WOLFSSL_SERVER
#define WOLFSSL_TLS13
#define HAVE_HKDF
#ifndef PQC_TLS_ENABLE_RSA
#define PQC_TLS_ENABLE_RSA 1
#endif
#ifndef PQC_TLS_ENABLE_RSA_PSS
#define PQC_TLS_ENABLE_RSA_PSS 1
#endif
#ifndef PQC_TLS_ENABLE_ECC
#define PQC_TLS_ENABLE_ECC 1
#endif
#ifndef PQC_TLS_ENABLE_CERT_ECC
#define PQC_TLS_ENABLE_CERT_ECC 0
#endif
#ifndef PQC_TLS_ECC_BITS
#define PQC_TLS_ECC_BITS 256
#endif
#ifndef PQC_TLS_ECC_MIN_BITS
#define PQC_TLS_ECC_MIN_BITS 256
#endif
#ifndef PQC_TLS_ENABLE_CURVE25519
#define PQC_TLS_ENABLE_CURVE25519 0
#endif
#ifndef PQC_TLS_ENABLE_MLKEM_768
#define PQC_TLS_ENABLE_MLKEM_768 0
#endif
#ifndef PQC_TLS_ENABLE_MLKEM_1024
#define PQC_TLS_ENABLE_MLKEM_1024 0
#endif
#ifndef PQC_TLS_ENABLE_MLDSA_65
#define PQC_TLS_ENABLE_MLDSA_65 0
#endif
#ifndef PQC_TLS_ENABLE_MLDSA_65_SIGN
#define PQC_TLS_ENABLE_MLDSA_65_SIGN 0
#endif
#define WOLFSSL_SMALL_STACK


#ifndef PQC_WOLFSSL_MEMORY_DIAGNOSTICS
#define PQC_WOLFSSL_MEMORY_DIAGNOSTICS 0
#endif
#ifndef PQC_WOLFSSL_ALLOCATION_PROVENANCE
#define PQC_WOLFSSL_ALLOCATION_PROVENANCE 0
#endif
#ifndef PQC_MLDSA_WORKSPACE_SIZE_BYTES
#define PQC_MLDSA_WORKSPACE_SIZE_BYTES (64U * 1024U)
#endif



/*
 * Diagnostic allocator override.
 *
 * wolfSSL's wolfcrypt/types.h honors XMALLOC_OVERRIDE by leaving XMALLOC,
 * XREALLOC and XFREE under application control. Preserve the native wolfSSL
 * heap/type arguments and attach the original source call site while routing
 * the actual allocation through the project FreeRTOS heap_4 allocator.
 */
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

#define XMALLOC_OVERRIDE
#if PQC_WOLFSSL_ALLOCATION_PROVENANCE
#define XMALLOC(size, heap, type) \
    PQC_WolfSSL_TrackedMalloc( \
        (size), (heap), (type), __func__, __FILE__, __LINE__)
#define XREALLOC(pointer, size, heap, type) \
    PQC_WolfSSL_TrackedRealloc( \
        (pointer), (size), (heap), (type), __func__, __FILE__, __LINE__)
#define XFREE(pointer, heap, type) \
    PQC_WolfSSL_TrackedFree( \
        (pointer), (heap), (type), __func__, __FILE__, __LINE__)
#else
#define XMALLOC(size, heap, type) \
    PQC_WolfSSL_TrackedMalloc((size), (heap), (type), NULL, NULL, 0U)
#define XREALLOC(pointer, size, heap, type) \
    PQC_WolfSSL_TrackedRealloc( \
        (pointer), (size), (heap), (type), NULL, NULL, 0U)
#define XFREE(pointer, heap, type) \
    PQC_WolfSSL_TrackedFree((pointer), (heap), (type), NULL, NULL, 0U)
#endif


#if PQC_TLS_ENABLE_MLKEM_768 || PQC_TLS_ENABLE_MLKEM_1024 || PQC_TLS_ENABLE_MLDSA_65
#define WOLFSSL_EXPERIMENTAL_SETTINGS
#define WOLFSSL_SHA3
#define WOLFSSL_SHAKE128
#define WOLFSSL_SHAKE256
#endif

#if PQC_TLS_ENABLE_MLDSA_65
#define WOLFSSL_HAVE_MLDSA
#if !PQC_TLS_ENABLE_MLDSA_65_SIGN
#define WOLFSSL_MLDSA_VERIFY_ONLY
#endif
#define WOLFSSL_NO_ML_DSA_44
#define WOLFSSL_NO_ML_DSA_87
#endif

#if PQC_TLS_ENABLE_MLKEM_768 || PQC_TLS_ENABLE_MLKEM_1024
#define WOLFSSL_HAVE_MLKEM
#define WOLFSSL_PQC_HYBRIDS
#define WOLFSSL_TLSX_PQC_MLKEM_STORE_OBJ
#define WOLFSSL_MLKEM_MAKEKEY_SMALL_MEM
#define WOLFSSL_NO_ML_KEM_512
#if PQC_TLS_ENABLE_MLKEM_768
#define WOLFSSL_NO_ML_KEM_1024
#else
#define WOLFSSL_NO_ML_KEM_768
#endif
#endif
#if PQC_TLS_ENABLE_ECC || PQC_TLS_ENABLE_CERT_ECC
#define HAVE_ECC
#define ECC_USER_CURVES
#define ECC_MIN_KEY_SZ PQC_TLS_ECC_MIN_BITS
#if PQC_TLS_ENABLE_CERT_ECC || PQC_TLS_ECC_BITS == 256
#undef NO_ECC256
#endif
#if PQC_TLS_ENABLE_ECC && PQC_TLS_ECC_BITS == 384
#define HAVE_ECC384
#define WOLFSSL_SP_384
#elif PQC_TLS_ENABLE_ECC && PQC_TLS_ECC_BITS == 521
#define HAVE_ECC521
#define WOLFSSL_SP_521
#endif
#endif
#if PQC_TLS_ENABLE_CURVE25519
#define HAVE_CURVE25519
#define CURVE25519_SMALL
#endif
#define HAVE_TLS_EXTENSIONS
#define HAVE_SUPPORTED_CURVES
#define HAVE_AESGCM
#define ECC_TIMING_RESISTANT
#define WOLFSSL_BASE64_ENCODE
#define WOLFSSL_PEM_TO_DER
#define WOLFSSL_CERT_GEN_CACHE
#define NO_DH
#define NO_DSA
#if !PQC_TLS_ENABLE_RSA
#define NO_RSA
#endif
#if PQC_TLS_ENABLE_RSA && PQC_TLS_ENABLE_RSA_PSS
#define WC_RSA_PSS
#elif PQC_TLS_ENABLE_RSA
#define NO_RSA_PSS
#endif
#define NO_MD5
#define NO_SHA
#define NO_SHA512
#define NO_DES3
#define NO_RC4
#define NO_PWDBASED
#define NO_SESSION_CACHE
#define NO_ASN_TIME

int PQC_WolfSSL_HardwareSeed(unsigned char *output, unsigned int size);
#define CUSTOM_RAND_GENERATE_SEED PQC_WolfSSL_HardwareSeed

#endif
