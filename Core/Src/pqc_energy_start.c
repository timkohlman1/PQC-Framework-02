/* Control-plane gate: never let a flash/reset execute an unassociated workload. */
#include "pqc_energy_boundary.h"
#include <stdbool.h>
#if PQC_ENERGY_SYNC_ENABLED
#include "main.h"
extern UART_HandleTypeDef hlpuart1;

bool PQC_EnergyAwaitStart(void)
{
    static const char ready[] = "PQC_ENERGY_WAITING\r\n";
    static const char command[] = "PQC_ENERGY_GO\n";
    uint32_t started = HAL_GetTick(), announced = started - 1000U;
    unsigned position = 0U;
    while (HAL_GetTick() - started < 60000U) {
        uint8_t ch;
        if (HAL_GetTick() - announced >= 500U) {
            (void)HAL_UART_Transmit(&hlpuart1, (uint8_t *)ready, sizeof(ready)-1U, 100U);
            announced = HAL_GetTick();
        }
        if (HAL_UART_Receive(&hlpuart1, &ch, 1U, 20U) == HAL_OK) {
            position = (ch == (uint8_t)command[position]) ? position + 1U : 0U;
            if (position == sizeof(command)-1U) return true;
        }
    }
    /* Fail closed. A later run must reset the board and authorize a new boot. */
    return false;
}
#else
bool PQC_EnergyAwaitStart(void) { return true; }
#endif
