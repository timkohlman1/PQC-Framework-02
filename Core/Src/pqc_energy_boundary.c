#include "pqc_energy_boundary.h"
#if PQC_ENERGY_SYNC_ENABLED
#include "main.h"
#include "pqc_timebase.h"
#include "pqc_result_buffer.h"
#include <inttypes.h>
#include <stdio.h>
static uint64_t start_us, end_us;
static uint8_t active, valid;

/* newlib-nano does not supply 64-bit printf conversion in this target. */
static char *decimal(uint64_t value, char buffer[21])
{
    char *p = buffer + 20;
    *p = '\0';
    do { *--p = (char)('0' + value % 10U); value /= 10U; } while (value);
    return p;
}

void PQC_EnergyBoundaryInitialize(void)
{
    GPIO_InitTypeDef pin = {0};
    __HAL_RCC_GPIOF_CLK_ENABLE();
    GPIOF->BSRR = (uint32_t)GPIO_PIN_12 << 16U;
    pin.Pin = GPIO_PIN_12;
    pin.Mode = GPIO_MODE_OUTPUT_PP;
    pin.Pull = GPIO_NOPULL;
    pin.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOF, &pin);
}

void PQC_EnergyBoundaryBegin(void)
{
    uint32_t mask = __get_PRIMASK();
    __disable_irq();
    valid = !active && PQC_TimebaseGetProvenance()->initialized;
    start_us = PQC_TimebaseNowUs();
    GPIOF->BSRR = GPIO_PIN_12;
    __DSB();
    active = 1U;
    __set_PRIMASK(mask);
}

void PQC_EnergyBoundaryEnd(void)
{
    uint32_t mask = __get_PRIMASK();
    __disable_irq();
    end_us = PQC_TimebaseNowUs();
    GPIOF->BSRR = (uint32_t)GPIO_PIN_12 << 16U;
    __DSB();
    valid = valid && active && end_us > start_us;
    active = 0U;
    __set_PRIMASK(mask);
}

void PQC_EnergyBoundaryAppend(uint32_t interval_index)
{
    char line[256];
    char s0[21], s1[21];
    (void)snprintf(line, sizeof(line),
        "PQC_ENERGY_BOUNDARY interval_index=%" PRIu32
        " s0_us=%s s1_us=%s"
        " valid=%u clock=TIM2 counter_hz=1000000 timestamp_convention=before_gpio_write",
        interval_index, decimal(start_us, s0), decimal(end_us, s1), (unsigned)(valid && !active));
    (void)PQC_ResultBufferAppendText(interval_index, "energy_boundary", line);
    valid = 0U;
}
#else
void PQC_EnergyBoundaryInitialize(void) {}
void PQC_EnergyBoundaryBegin(void) {}
void PQC_EnergyBoundaryEnd(void) {}
void PQC_EnergyBoundaryAppend(uint32_t index) { (void)index; }
#endif
