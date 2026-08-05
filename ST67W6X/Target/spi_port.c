/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    spi_port.c
  * @author  ST67 Application Team
  * @brief   SPI bus interface porting layer implementation
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */

/**
  * This file is based on QCC74xSDK provided by Qualcomm.
  * See https://git.codelinaro.org/clo/qcc7xx/QCCSDK-QCC74x for more information.
  *
  * Reference source: examples/stm32_spi_host/QCC743_SPI_HOST/Core/Src/spi_iface.c
  */

/* Includes ------------------------------------------------------------------*/
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>

#include "bsp_conf.h"
#include "spi_port.h"
#include "logging.h"
#include "main.h"
#include "FreeRTOS.h"
#include "task.h"

/* USER CODE BEGIN Includes */

/* USER CODE END Includes */

/* Global variables ----------------------------------------------------------*/
/* USER CODE BEGIN GV */

/* USER CODE END GV */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private defines -----------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macros ------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
/** SPI transaction complete callback */
static spi_transaction_complete_t spi_port_transaction_complete_cb = NULL;

static const char spi_port_error_str[] = "SPI not initialized\n";
static volatile spi_port_diagnostics_t spi_port_diag = {0};

enum
{
  SPI_PORT_CB_NONE = 0,
  SPI_PORT_CB_TX = 1,
  SPI_PORT_CB_RX = 2,
  SPI_PORT_CB_TXRX = 3,
  SPI_PORT_CB_ERROR = 4
};

static void spi_port_diag_begin(uint16_t len, uint8_t dma, uint8_t tx_present)
{
  spi_port_diag.sequence++;
  spi_port_diag.started_tick = (uint32_t)xTaskGetTickCount();
  spi_port_diag.completed_tick = 0U;
  spi_port_diag.length = len;
  spi_port_diag.dma = dma;
  spi_port_diag.tx_present = tx_present;
  spi_port_diag.active = 1U;
  spi_port_diag.last_callback = SPI_PORT_CB_NONE;
  spi_port_diag.hal_state = (uint32_t)NCP_SPI_HANDLE.State;
  spi_port_diag.hal_error = (uint32_t)HAL_SPI_GetError(&NCP_SPI_HANDLE);
}

static uint32_t spi_port_tick_from_isr(void)
{
  if (xTaskGetSchedulerState() == taskSCHEDULER_NOT_STARTED)
  {
    return HAL_GetTick();
  }

  return (uint32_t)xTaskGetTickCountFromISR();
}

static void spi_port_diag_complete(uint8_t callback)
{
  spi_port_diag.completed_tick = spi_port_tick_from_isr();
  spi_port_diag.callback_count++;
  spi_port_diag.last_callback = callback;
  spi_port_diag.active = 0U;
  spi_port_diag.hal_state = (uint32_t)NCP_SPI_HANDLE.State;
  spi_port_diag.hal_error = (uint32_t)HAL_SPI_GetError(&NCP_SPI_HANDLE);
}


/* USER CODE BEGIN PV */

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
/* USER CODE BEGIN PFP */

/* USER CODE END PFP */

/* Functions Definition ------------------------------------------------------*/
void *spi_port_memcpy(void *dest, const void *src, unsigned int len)
{
  /* USER CODE BEGIN memcpy_1 */

  /* USER CODE END memcpy_1 */
  uint8_t *d = (uint8_t *)dest;
  const uint8_t *s = (const uint8_t *)src;

  /* Copy bytes until the destination address is aligned to 4 bytes */
  while (((uint32_t) d % 4 != 0) && len > 0)
  {
    *d++ = *s++;
    len--;
  }

  /* Copy 4-byte blocks */
  uint32_t *d32 = (uint32_t *)d;
  const uint32_t *s32 = (const uint32_t *)s;
  while (len >= 4U)
  {
    *d32++ = *s32++;
    len -= 4U;
  }

  /* Copy remaining bytes */
  d = (uint8_t *)d32;
  s = (const uint8_t *)s32;
  while (len > 0U)
  {
    *d++ = *s++;
    len--;
  }
  /* USER CODE BEGIN memcpy_2 */

  /* USER CODE END memcpy_2 */

  return dest;
  /* USER CODE BEGIN memcpy_End */

  /* USER CODE END memcpy_End */
}

int32_t spi_port_init(spi_transaction_complete_t transaction_complete_cb)
{
  /* USER CODE BEGIN spi_port_init_1 */

  /* USER CODE END spi_port_init_1 */
  if (NCP_SPI_HANDLE.State == HAL_SPI_STATE_RESET)
  {
    LogError(spi_port_error_str);
    return -1;
  }

  /* Powering up the NCP using GPIO CHIP_EN */
  HAL_GPIO_WritePin(CHIP_EN_GPIO_Port, CHIP_EN_Pin, GPIO_PIN_SET);

  if (transaction_complete_cb != NULL)
  {
    spi_port_transaction_complete_cb = transaction_complete_cb;
  }
  /* USER CODE BEGIN spi_port_init_2 */

  /* USER CODE END spi_port_init_2 */

  return 0;
  /* USER CODE BEGIN spi_port_init_End */

  /* USER CODE END spi_port_init_End */
}

int32_t spi_port_deinit(void)
{
  /* USER CODE BEGIN spi_port_deinit_1 */

  /* USER CODE END spi_port_deinit_1 */
  /* Switch off the NCP using GPIO CHIP_EN */
  HAL_GPIO_WritePin(CHIP_EN_GPIO_Port, CHIP_EN_Pin, GPIO_PIN_RESET);

  spi_port_transaction_complete_cb = NULL;
  /* USER CODE BEGIN spi_port_deinit_2 */

  /* USER CODE END spi_port_deinit_2 */

  return 0;
  /* USER CODE BEGIN spi_port_deinit_End */

  /* USER CODE END spi_port_deinit_End */
}

int32_t spi_port_transfer(void *tx_buf, void *rx_buf, uint16_t len, uint32_t timeout)
{
  /* USER CODE BEGIN spi_port_transfer_1 */

  /* USER CODE END spi_port_transfer_1 */
  HAL_StatusTypeDef status;

  spi_port_diag_begin(len, 0U, (tx_buf != NULL) ? 1U : 0U);

  if (NCP_SPI_HANDLE.State == HAL_SPI_STATE_RESET)
  {
    LogError(spi_port_error_str);
    return -1;
  }

#if defined (__DCACHE_PRESENT) && (__DCACHE_PRESENT == 1U)
  SCB_CleanInvalidateDCache_by_Addr(rx_buf, len);
#endif /* __DCACHE_PRESENT */

  /* Check whether host data is to be transmitted to the NCP, otherwise read only data from the NCP */
  if (tx_buf != NULL)
  {
#if defined (__DCACHE_PRESENT) && (__DCACHE_PRESENT == 1U)
    SCB_CleanDCache_by_Addr(tx_buf, len);
#endif /* __DCACHE_PRESENT */
    status = HAL_SPI_TransmitReceive(&NCP_SPI_HANDLE, tx_buf, rx_buf, len, timeout);
  }
  else
  {
    assert_param(len <= SPI_DMA_XFER_SIZE_THRESHOLD);
    uint8_t tx_dummy[SPI_DMA_XFER_SIZE_THRESHOLD] = {0};
    status = HAL_SPI_TransmitReceive(&NCP_SPI_HANDLE, tx_dummy, rx_buf, len, timeout);
  }
  /* USER CODE BEGIN spi_port_transfer_2 */

  /* USER CODE END spi_port_transfer_2 */

  if (status != HAL_OK)
  {
    LogError("SPI diagnostic: mode=poll len=%u status=%u hal_state=%u hal_error=0x%08lx ready=%ld\n",
             (unsigned int)len,
             (unsigned int)status,
             (unsigned int)NCP_SPI_HANDLE.State,
             (unsigned long)HAL_SPI_GetError(&NCP_SPI_HANDLE),
             (long)spi_port_is_ready());
  }
  return ((status == HAL_OK) ? 0 : -1);
  /* USER CODE BEGIN spi_port_transfer_End */

  /* USER CODE END spi_port_transfer_End */
}

int32_t spi_port_transfer_dma(void *tx_buf, void *rx_buf, uint16_t len)
{
  /* USER CODE BEGIN spi_port_transfer_dma_1 */

  /* USER CODE END spi_port_transfer_dma_1 */
  HAL_StatusTypeDef status;

  spi_port_diag_begin(len, 1U, (tx_buf != NULL) ? 1U : 0U);

  if (NCP_SPI_HANDLE.State == HAL_SPI_STATE_RESET)
  {
    LogError(spi_port_error_str);
    return -1;
  }

#if defined (__DCACHE_PRESENT) && (__DCACHE_PRESENT == 1U)
  SCB_CleanInvalidateDCache_by_Addr(rx_buf, len);
#endif /* __DCACHE_PRESENT */

  /* Check whether host data is to be transmitted to the NCP, otherwise read only data from the NCP */
  if (tx_buf != NULL)
  {
#if defined (__DCACHE_PRESENT) && (__DCACHE_PRESENT == 1U)
    SCB_CleanDCache_by_Addr(tx_buf, len);
#endif /* __DCACHE_PRESENT */
    /* USER CODE BEGIN spi_port_transfer_dma_trx */
    status = HAL_SPI_TransmitReceive_DMA(&NCP_SPI_HANDLE, tx_buf, rx_buf, len);
    /* USER CODE END spi_port_transfer_dma_trx */
  }
  else
  {
    /* USER CODE BEGIN spi_port_transfer_dma_rx */
    status = HAL_SPI_Receive_DMA(&NCP_SPI_HANDLE, rx_buf, len);
    /* USER CODE END spi_port_transfer_dma_rx */
  }
  /* USER CODE BEGIN spi_port_transfer_dma_2 */

  /* USER CODE END spi_port_transfer_dma_2 */

  if (status != HAL_OK)
  {
    LogError("SPI diagnostic: mode=dma len=%u tx_present=%u status=%u hal_state=%u hal_error=0x%08lx ready=%ld\n",
             (unsigned int)len,
             (tx_buf != NULL) ? 1U : 0U,
             (unsigned int)status,
             (unsigned int)NCP_SPI_HANDLE.State,
             (unsigned long)HAL_SPI_GetError(&NCP_SPI_HANDLE),
             (long)spi_port_is_ready());
  }
  return ((status == HAL_OK) ? 0 : -1);
  /* USER CODE BEGIN spi_port_transfer_dma_End */

  /* USER CODE END spi_port_transfer_dma_End */
}

int32_t spi_port_is_ready(void)
{
  /* USER CODE BEGIN spi_port_is_ready_1 */

  /* USER CODE END spi_port_is_ready_1 */
  /* Check whether NCP data are available on the SPI bus */
  return (int32_t)HAL_GPIO_ReadPin(SPI_RDY_GPIO_Port, SPI_RDY_Pin);
  /* USER CODE BEGIN spi_port_is_ready_End */

  /* USER CODE END spi_port_is_ready_End */
}

int32_t spi_port_set_cs(int32_t state)
{
  /* USER CODE BEGIN spi_port_set_cs_1 */

  /* USER CODE END spi_port_set_cs_1 */
  if (state == 1)
  {
    /* Activate Chip Select before starting transfer */
    HAL_GPIO_WritePin(SPI_CS_GPIO_Port, SPI_CS_Pin, GPIO_PIN_SET);
  }
  else
  {
    /* Disable Chip Select when transfer is complete */
    HAL_GPIO_WritePin(SPI_CS_GPIO_Port, SPI_CS_Pin, GPIO_PIN_RESET);
  }
  /* USER CODE BEGIN spi_port_set_cs_2 */

  /* USER CODE END spi_port_set_cs_2 */

  return 0;
  /* USER CODE BEGIN spi_port_set_cs_End */

  /* USER CODE END spi_port_set_cs_End */
}

/* USER CODE BEGIN FD */

/* USER CODE END FD */

/* Weak functions redefinition -----------------------------------------------*/
void HAL_SPI_TxCpltCallback(SPI_HandleTypeDef *hspi)
{
  /* USER CODE BEGIN HAL_SPI_TxCpltCallback_1 */

  /* USER CODE END HAL_SPI_TxCpltCallback_1 */
  if (hspi == &NCP_SPI_HANDLE)
  {
    spi_port_diag_complete(SPI_PORT_CB_TX);
    if (spi_port_transaction_complete_cb != NULL) { spi_port_transaction_complete_cb(); }
  }
  /* USER CODE BEGIN HAL_SPI_TxCpltCallback_End */

  /* USER CODE END HAL_SPI_TxCpltCallback_End */
}

void HAL_SPI_RxCpltCallback(SPI_HandleTypeDef *hspi)
{
  /* USER CODE BEGIN HAL_SPI_RxCpltCallback_1 */

  /* USER CODE END HAL_SPI_RxCpltCallback_1 */
  if (hspi == &NCP_SPI_HANDLE)
  {
    spi_port_diag_complete(SPI_PORT_CB_RX);
    if (spi_port_transaction_complete_cb != NULL) { spi_port_transaction_complete_cb(); }
  }
  /* USER CODE BEGIN HAL_SPI_RxCpltCallback_End */

  /* USER CODE END HAL_SPI_RxCpltCallback_End */
}

void HAL_SPI_TxRxCpltCallback(SPI_HandleTypeDef *hspi)
{
  /* USER CODE BEGIN HAL_SPI_TxRxCpltCallback_1 */

  /* USER CODE END HAL_SPI_TxRxCpltCallback_1 */
  if (hspi == &NCP_SPI_HANDLE)
  {
    spi_port_diag_complete(SPI_PORT_CB_TXRX);
    if (spi_port_transaction_complete_cb != NULL) { spi_port_transaction_complete_cb(); }
  }
  /* USER CODE BEGIN HAL_SPI_TxRxCpltCallback_End */

  /* USER CODE END HAL_SPI_TxRxCpltCallback_End */
}

void HAL_SPI_ErrorCallback(SPI_HandleTypeDef *hspi)
{
  /* USER CODE BEGIN HAL_SPI_ErrorCallback_1 */

  /* USER CODE END HAL_SPI_ErrorCallback_1 */
  if (hspi == &NCP_SPI_HANDLE)
  {
    spi_port_diag.error_callback_count++;
    spi_port_diag_complete(SPI_PORT_CB_ERROR);
    if (spi_port_transaction_complete_cb != NULL) { spi_port_transaction_complete_cb(); }
  }
  /* USER CODE BEGIN HAL_SPI_ErrorCallback_End */

  /* USER CODE END HAL_SPI_ErrorCallback_End */
}

/* USER CODE BEGIN WFR */

/* USER CODE END WFR */

int32_t spi_port_get_diagnostics(spi_port_diagnostics_t *diagnostics)
{
  if (diagnostics == NULL)
  {
    return -1;
  }
  taskENTER_CRITICAL();
  *diagnostics = spi_port_diag;
  taskEXIT_CRITICAL();
  return 0;
}

int32_t spi_port_abort_transfer(void)
{
  HAL_StatusTypeDef status = HAL_SPI_Abort(&NCP_SPI_HANDLE);
  spi_port_diag.active = 0U;
  spi_port_diag.hal_state = (uint32_t)NCP_SPI_HANDLE.State;
  spi_port_diag.hal_error = (uint32_t)HAL_SPI_GetError(&NCP_SPI_HANDLE);
  return (status == HAL_OK) ? 0 : -1;
}
