#ifndef PQC_WOLFSSL_USER_SETTINGS_H
#define PQC_WOLFSSL_USER_SETTINGS_H

/*
 * Phase M6.1 STM32 wolfSSL TLS-context lifecycle configuration.
 *
 * This enables only the library surface needed to initialize wolfSSL, create
 * and free a TLS 1.2 client WOLFSSL_CTX, and clean up global wolfSSL state.
 * It does not enable sockets, certificate loading, private-key loading, MQTT,
 * Wi-Fi, or an ST67W61M1 transport backend.
 */
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
#define WOLFSSL_NO_ASM
#define USE_SLOW_SHA256
#define WC_NO_HARDEN

/* Client-only TLS 1.2 context support. */
#define NO_WOLFSSL_SERVER
#define WOLFSSL_NO_TLS13
#define WOLFSSL_STATIC_PSK

/*
 * Phase M6.1 does not provide a cryptographic entropy source. random.c is
 * linked because wolfSSL client-context code references RNG lifecycle APIs,
 * but this callback deliberately fails if any later code attempts to seed an
 * RNG. Context creation/free must not consume entropy in this phase.
 */
static inline int PQC_WolfSSL_UnavailableSeed(unsigned char* output,
                                               unsigned int size)
{
    (void)output;
    (void)size;
    return -1;
}
#define CUSTOM_RAND_GENERATE_SEED PQC_WolfSSL_UnavailableSeed

/* Keep the enabled cryptographic surface narrow. */
#define NO_DH
#define NO_DSA
#define NO_RSA
#define NO_ECC
#define NO_MD5
#define NO_SHA
#define NO_SHA512
#define NO_DES3
#define NO_RC4
#define NO_PWDBASED
#define NO_CODING
#define NO_ASN
#define NO_CERTS
#define NO_SESSION_CACHE

/* AES/HMAC/SHA-256 remain available for the minimal TLS client build. */

#endif /* PQC_WOLFSSL_USER_SETTINGS_H */
