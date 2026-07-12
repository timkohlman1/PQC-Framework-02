#ifndef USER_SETTINGS_H
#define USER_SETTINGS_H

/*
 * wolfSSL looks for a generic user_settings.h when WOLFSSL_USER_SETTINGS is
 * defined. Keep the Phase M6 STM32 application smoke settings behind an
 * explicit project marker so this header does not contaminate other builds
 * that also see Core/Inc, including wolfBoot secure-boot builds.
 */
#if defined(PQC_STM32_APP_WOLFSSL_USER_SETTINGS)
#include "pqc_wolfssl_user_settings.h"
#endif

#endif /* USER_SETTINGS_H */
