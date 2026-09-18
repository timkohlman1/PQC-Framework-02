#include "pqc_timebase.h"

#include <limits.h>
#include <string.h>

#include "main.h"

#define PQC_TIMEBASE_COUNTER_MAX 0xFFFFFFFFUL
#define PQC_TIMEBASE_BRIDGE_EXPECTED_BITS 16U

static TIM_HandleTypeDef s_timebase_tim2;
static volatile uint32_t s_timebase_overflow_count;
static PQC_TimebaseBootHandoff s_boot_handoff;
static PQC_TimebaseProvenance s_provenance;

static uint32_t PQC_TimebaseTimerInputClockHz(void)
{
    RCC_ClkInitTypeDef clocks;
    uint32_t flash_latency = 0U;
    uint32_t pclk1_hz = HAL_RCC_GetPCLK1Freq();

    memset(&clocks, 0, sizeof(clocks));
    HAL_RCC_GetClockConfig(&clocks, &flash_latency);
    (void)flash_latency;

    if (clocks.APB1CLKDivider == RCC_HCLK_DIV1) {
        return pclk1_hz;
    }
    if (pclk1_hz > (UINT32_MAX / 2U)) {
        return 0U;
    }
    return pclk1_hz * 2U;
}

static uint16_t PQC_TimebaseReadBridgeCounter(void)
{
#if defined(LPTIM2)
    uint16_t first;
    uint16_t second;
    do {
        first = (uint16_t)LPTIM2->CNT;
        second = (uint16_t)LPTIM2->CNT;
    } while (first != second);
    return second;
#else
    return 0U;
#endif
}

static void PQC_TimebaseResolveBootHandoff(void)
{
    s_provenance.reset_origin_valid = 0U;
    s_provenance.bridge_valid = 0U;
    s_provenance.reset_origin_kind = 0U;
    s_provenance.reset_origin_to_application_timebase_us = 0U;

    if (s_boot_handoff.valid == 0U) {
        return;
    }
    if ((s_boot_handoff.bridge_counter_hz != PQC_APPLICATION_TIMEBASE_HZ) ||
        (s_boot_handoff.bridge_counter_bits != PQC_TIMEBASE_BRIDGE_EXPECTED_BITS)) {
        return;
    }
#if defined(LPTIM2) && defined(LPTIM_ISR_ARRM)
    if ((LPTIM2->ISR & LPTIM_ISR_ARRM) != 0U) {
        return;
    }
    s_provenance.reset_origin_to_application_timebase_us =
        s_boot_handoff.reset_origin_to_handoff_us +
        (uint64_t)PQC_TimebaseReadBridgeCounter();
    s_provenance.reset_origin_kind = s_boot_handoff.reset_origin_kind;
    s_provenance.bridge_valid = 1U;
    s_provenance.reset_origin_valid = 1U;
#endif
}

void PQC_TimebaseConfigureBootHandoff(const PQC_TimebaseBootHandoff *handoff)
{
    memset(&s_boot_handoff, 0, sizeof(s_boot_handoff));
    if (handoff != NULL) {
        s_boot_handoff = *handoff;
    }
}

int PQC_TimebaseInitialize(void)
{
    uint32_t timer_input_hz;
    uint32_t divider;

    memset(&s_provenance, 0, sizeof(s_provenance));
    s_provenance.schema_version = PQC_APPLICATION_TIMEBASE_SCHEMA_VERSION;
    s_provenance.counter_hz = PQC_APPLICATION_TIMEBASE_HZ;
    s_provenance.counter_bits = PQC_APPLICATION_TIMEBASE_COUNTER_BITS;

    /* Resolve the bootloader handoff bridge before this function touches any
     * timer peripheral. wolfBoot leaves LPTIM2 running from HSI16 / 16 at
     * exactly 1 MHz solely to bridge the bootloader/application clock change. */
    PQC_TimebaseResolveBootHandoff();

    timer_input_hz = PQC_TimebaseTimerInputClockHz();
    if ((timer_input_hz == 0U) ||
        ((timer_input_hz % PQC_APPLICATION_TIMEBASE_HZ) != 0U)) {
        return -1;
    }
    divider = timer_input_hz / PQC_APPLICATION_TIMEBASE_HZ;
    if ((divider == 0U) || (divider > 0x10000UL)) {
        return -1;
    }

    __HAL_RCC_TIM2_CLK_ENABLE();
    memset(&s_timebase_tim2, 0, sizeof(s_timebase_tim2));
    s_timebase_tim2.Instance = TIM2;
    s_timebase_tim2.Init.Prescaler = divider - 1U;
    s_timebase_tim2.Init.CounterMode = TIM_COUNTERMODE_UP;
    s_timebase_tim2.Init.Period = PQC_TIMEBASE_COUNTER_MAX;
    s_timebase_tim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    s_timebase_tim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;

    if (HAL_TIM_Base_Init(&s_timebase_tim2) != HAL_OK) {
        return -1;
    }

    s_timebase_overflow_count = 0U;
    __HAL_TIM_SET_COUNTER(&s_timebase_tim2, 0U);
    __HAL_TIM_CLEAR_FLAG(&s_timebase_tim2, TIM_FLAG_UPDATE);
    __HAL_TIM_ENABLE_IT(&s_timebase_tim2, TIM_IT_UPDATE);
    HAL_NVIC_SetPriority(TIM2_IRQn, 15U, 0U);
    HAL_NVIC_EnableIRQ(TIM2_IRQn);
    if (HAL_TIM_Base_Start(&s_timebase_tim2) != HAL_OK) {
        HAL_NVIC_DisableIRQ(TIM2_IRQn);
        return -1;
    }

    s_provenance.timer_input_clock_hz = timer_input_hz;
    s_provenance.prescaler = divider - 1U;
    s_provenance.initialized = 1U;
    return 0;
}

uint64_t PQC_TimebaseNowUs(void)
{
    uint32_t high_before;
    uint32_t high_after;
    uint32_t low;
    uint32_t pending;

    if (s_provenance.initialized == 0U) {
        return 0U;
    }

    do {
        high_before = s_timebase_overflow_count;
        low = (uint32_t)TIM2->CNT;
        pending = (TIM2->SR & TIM_SR_UIF);
        high_after = s_timebase_overflow_count;
    } while (high_before != high_after);

    /* If the hardware wrapped but the very-low-priority update IRQ has not
     * executed yet, account for that pending wrap in this read. */
    if ((pending != 0U) && (low < 0x80000000UL)) {
        high_before++;
    }
    return ((uint64_t)high_before << 32) | (uint64_t)low;
}

uint64_t PQC_TimebaseElapsedUs(uint64_t start_us, uint64_t end_us)
{
    return end_us - start_us;
}

bool PQC_TimebaseResetRelativeUs(uint64_t application_timestamp_us, uint64_t *reset_relative_us)
{
    if ((reset_relative_us == NULL) || (s_provenance.reset_origin_valid == 0U)) {
        return false;
    }
    *reset_relative_us =
        s_provenance.reset_origin_to_application_timebase_us + application_timestamp_us;
    return true;
}

uint32_t PQC_TimebaseLegacyMilliseconds(uint64_t elapsed_us)
{
    uint64_t milliseconds = elapsed_us / 1000ULL;
    return milliseconds > UINT32_MAX ? UINT32_MAX : (uint32_t)milliseconds;
}

const PQC_TimebaseProvenance *PQC_TimebaseGetProvenance(void)
{
    return &s_provenance;
}

void PQC_TimebaseTIM2IRQHandler(void)
{
    if ((TIM2->SR & TIM_SR_UIF) != 0U) {
        __HAL_TIM_CLEAR_FLAG(&s_timebase_tim2, TIM_FLAG_UPDATE);
        s_timebase_overflow_count++;
    }
}
