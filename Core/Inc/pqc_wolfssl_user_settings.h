#ifndef PQC_WOLFSSL_USER_SETTINGS_H
#define PQC_WOLFSSL_USER_SETTINGS_H

/*
 * Phase M6 STM32 wolfSSL source-build smoke configuration.
 *
 * This configuration is intentionally minimal. It enables enough wolfCrypt from
 * the repository-local wolfSSL source tree to compile and run a SHA-256 smoke
 * check on STM32. It does not enable TLS handshakes, sockets, filesystem-backed
 * certificates, private-key loading, MQTT, or ST67W61M1 transport support.
 */
#define WOLFCRYPT_ONLY
#define SINGLE_THREADED
#define NO_FILESYSTEM
#define NO_WRITEV
#define NO_DEV_RANDOM
#define NO_MAIN_DRIVER
#define NO_WOLFSSL_DIR
#define WOLFSSL_USER_IO
#define NO_ERROR_STRINGS
#define NO_OLD_TLS
#define NO_TLS
#define WOLFSSL_NO_ASM
#define WOLFSSL_NO_MALLOC
#define NO_WOLFSSL_MEMORY
#define USE_SLOW_SHA256
#define WC_NO_HARDEN

/* Keep the Phase M6 crypto surface narrow. SHA-256 remains enabled. */
#define NO_DH
#define NO_DSA
#define NO_RSA
#define NO_ECC
#define NO_MD5
#define NO_SHA
#define NO_SHA512
#define NO_HMAC
#define NO_DES3
#define NO_AES
#define NO_RC4
#define NO_PWDBASED
#define NO_CODING
#define NO_ASN
#define NO_CERTS
#define NO_SESSION_CACHE
#define NO_WOLFSSL_CLIENT
#define NO_WOLFSSL_SERVER

#endif /* PQC_WOLFSSL_USER_SETTINGS_H */
