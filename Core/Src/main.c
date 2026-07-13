/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
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
/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "cmsis_os.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include "pqc_lwip_build_only.h"
#include "pqc_lwip_loopback.h"
#include "pqc_network_interface.h"
#include "pqc_wolfssl_build_only.h"
#include "pqc_wolfssl_transport.h"
#include "pqc_wolfmqtt_build_only.h"
#include "w6x_api.h"
#include "spi_iface.h"
#include "logging.h"
#include "FreeRTOS.h"
#include "task.h"
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
UART_HandleTypeDef hlpuart1;

SPI_HandleTypeDef hspi1;
DMA_HandleTypeDef hdma_spi1_tx;
DMA_HandleTypeDef hdma_spi1_rx;

/* Definitions for defaultTask */
osThreadId_t defaultTaskHandle;
const osThreadAttr_t defaultTask_attributes = {
  .name = "defaultTask",
  .stack_size = 512 * 4,
  .priority = (osPriority_t) osPriorityNormal,
};
/* USER CODE BEGIN PV */

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_DMA_Init(void);
static void MX_LPUART1_UART_Init(void);
static void MX_SPI1_Init(void);
void StartDefaultTask(void *argument);

/* USER CODE BEGIN PFP */

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

static void APP_UART_WriteString(const char *text)
{
  uint16_t length = 0U;

  while (text[length] != '\0')
  {
    length++;
  }

  HAL_UART_Transmit(&hlpuart1, (uint8_t *)text, length, HAL_MAX_DELAY);
}

static void APP_UART_WriteUint32(uint32_t value)
{
  char digits[10];
  uint32_t count = 0U;

  if (value == 0U)
  {
    APP_UART_WriteString("0");
    return;
  }

  while ((value > 0U) && (count < sizeof(digits)))
  {
    digits[count] = (char)('0' + (value % 10U));
    value /= 10U;
    count++;
  }

  while (count > 0U)
  {
    count--;
    HAL_UART_Transmit(&hlpuart1, (uint8_t *)&digits[count], 1U, HAL_MAX_DELAY);
  }
}

static void APP_PrintST67PinState(const char *stage)
{
  APP_UART_WriteString("ST67 SPI bring-up pins: stage=");
  APP_UART_WriteString(stage);
  APP_UART_WriteString(" boot=");
  APP_UART_WriteUint32((uint32_t)HAL_GPIO_ReadPin(BOOT_GPIO_Port, BOOT_Pin));
  APP_UART_WriteString(" chip_en=");
  APP_UART_WriteUint32((uint32_t)HAL_GPIO_ReadPin(CHIP_EN_GPIO_Port, CHIP_EN_Pin));
  APP_UART_WriteString(" ready=");
  APP_UART_WriteUint32((uint32_t)HAL_GPIO_ReadPin(SPI_RDY_GPIO_Port, SPI_RDY_Pin));
  APP_UART_WriteString(" cs=");
  APP_UART_WriteUint32((uint32_t)HAL_GPIO_ReadPin(SPI_CS_GPIO_Port, SPI_CS_Pin));
  APP_UART_WriteString("\r\n");
}

static void APP_RunST67SPIBringup(void)
{
  W6X_Status_t status;
  void *logging_service;

  APP_UART_WriteString(
      "ST67 SPI bring-up: begin context=freertos_task scheduler=running "
      "evidence=stm32-st67-gpio-spi-bringup-only "
      "wifi_association=not-attempted ip=unavailable tls_handshake=unavailable "
      "mqtt_connect=unavailable end_to_end=unavailable\r\n");

  /*
   * BOOT low selects normal mission execution for this board configuration.
   * Keep CHIP_EN and the active-high chip select low until the vendor driver
   * performs its documented startup sequence.
   */
  HAL_GPIO_WritePin(BOOT_GPIO_Port, BOOT_Pin, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(CHIP_EN_GPIO_Port, CHIP_EN_Pin, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(SPI_CS_GPIO_Port, SPI_CS_Pin, GPIO_PIN_RESET);
  APP_PrintST67PinState("pre_init");

  /* Make the low level visible in a logic-analyser capture before W6X_Init(). */
  osDelay(20U);

  logging_service = vLoggingInit(APP_UART_WriteString);
  if (logging_service == NULL)
  {
    APP_UART_WriteString(
        "ST67 SPI bring-up: result=logging_init_failed "
        "driver_init=not-attempted\r\n");
    APP_PrintST67PinState("logging_failed");
    return;
  }

  APP_UART_WriteString("ST67 SPI bring-up: W6X_Init begin\r\n");
  status = W6X_Init();

  APP_UART_WriteString("ST67 SPI bring-up: W6X_Init result=");
  APP_UART_WriteUint32((uint32_t)status);
  APP_UART_WriteString(" status_ok=");
  APP_UART_WriteUint32((status == W6X_STATUS_OK) ? 1U : 0U);
  APP_UART_WriteString("\r\n");
  APP_PrintST67PinState("post_init");

  if (status == W6X_STATUS_OK)
  {
    APP_UART_WriteString(
        "ST67 SPI bring-up: complete result=passed "
        "transport=spi-module-initialized wifi_association=not-attempted "
        "ip=unavailable tls_handshake=unavailable mqtt_connect=unavailable "
        "end_to_end=unavailable\r\n");
  }
  else
  {
    APP_UART_WriteString(
        "ST67 SPI bring-up: complete result=failed "
        "transport=spi-module-init-failed wifi_association=not-attempted "
        "ip=unavailable tls_handshake=unavailable mqtt_connect=unavailable "
        "end_to_end=unavailable\r\n");
  }
}

static void APP_PrintLwIPRuntimeSmoke(const char *context, bool scheduler_running)
{
  static char smoke_line[512];

  PQC_LwIP_BuildOnly_Init();

  if (PQC_LwIP_BuildOnly_RuntimeSmokeLineForContext(
          smoke_line, (uint32_t)sizeof(smoke_line), context, scheduler_running))
  {
    APP_UART_WriteString(smoke_line);
  }
  else
  {
    APP_UART_WriteString("lwIP runtime smoke: context=unavailable scheduler=unavailable reason=format_failed network=unavailable wifi=unavailable link=unavailable ip=unavailable tcp=unavailable tls_handshake=unavailable certs=not-loaded mqtt_connect=unavailable mqtt_publish=unavailable reconnect=unavailable st67w61m1=unavailable end_to_end=unavailable\r\n");
  }
}

static void APP_RunLwIPLocalLoopbackSmoke(void)
{
  char status_line[768];
  const PQC_LwIPLoopbackStatus status = PQC_LwIP_Loopback_RunUdpSmoke();

  if (PQC_LwIP_Loopback_StatusLine(
          status_line, (uint32_t)sizeof(status_line), &status))
  {
    APP_UART_WriteString(status_line);
  }
  else
  {
    APP_UART_WriteString("lwIP local loopback smoke: context=freertos_task scheduler=running evidence=stm32-local-lwip-loopback-only protocol=udp address=127.0.0.1 result=format_failed wifi_module=unavailable link=unavailable hardware_ip_acquisition=unavailable external_ping=unavailable external_tcp=unavailable tls_handshake=unavailable mqtt_connect=unavailable mqtt_publish=unavailable reconnect=unavailable broker_access=unavailable st67w61m1=unavailable end_to_end=unavailable\r\n");
  }
}

static void APP_PrintNetworkInterfaceStatus(void)
{
  char status_line[384];

  PQC_NetworkInterface_Init();

  if (PQC_NetworkInterface_StatusLine(status_line, (uint32_t)sizeof(status_line)))
  {
    APP_UART_WriteString(status_line);
  }
  else
  {
    APP_UART_WriteString("lwIP network interface: evidence=lwip-netif-state-only backend=unavailable boundary=present lwip_netif_up=0 lwip_link_up=0 lwip_ipv4_any=1 lwip_ipv4=0.0.0.0 link=unavailable ip=unavailable tcp=unavailable transport=unavailable wifi_module=unavailable st67w61m1=unavailable tls_handshake=unavailable mqtt_connect=unavailable mqtt_publish=unavailable reconnect=unavailable end_to_end=unavailable reason=format_failed\r\n");
  }
}

static void APP_PrintWolfSSLRuntimeSmoke(const char *context, bool scheduler_running)
{
  static char smoke_line[640];

  if (PQC_WolfSSL_BuildOnly_RuntimeSmokeLineForContext(
          smoke_line, (uint32_t)sizeof(smoke_line), context, scheduler_running))
  {
    APP_UART_WriteString(smoke_line);
  }
  else
  {
    APP_UART_WriteString("wolfSSL TLS context smoke: context=unavailable scheduler=unavailable evidence=tls-context-lifecycle-only unavailable reason=format_failed tls_handshake=unavailable certs=not-loaded transport=unavailable mqtt_connect=unavailable mqtt_publish=unavailable reconnect=unavailable wifi=unavailable link=unavailable ip=unavailable tcp=unavailable st67w61m1=unavailable end_to_end=unavailable secrets=not-compiled-in\r\n");
  }
}

static void APP_PrintWolfMQTTRuntimeStatus(void)
{
  static char status_line[640];

  if (PQC_WolfMQTT_RuntimeStatusLine(
          status_line, (uint32_t)sizeof(status_line), "freertos_task", true))
  {
    APP_UART_WriteString(status_line);
  }
  else
  {
    APP_UART_WriteString("wolfMQTT runtime smoke: context=freertos_task scheduler=running evidence=stm32-fake-no-network-initialization-only backend=fake_no_network init_result=unavailable client_initialized=0 callbacks=unavailable transport=unavailable wifi=unavailable link=unavailable ip=unavailable tcp=unavailable tls_handshake=unavailable mqtt_connect=unavailable mqtt_publish=unavailable reconnect=unavailable st67w61m1=unavailable end_to_end=unavailable reason=format_failed\r\n");
  }
}

static void APP_PrintWolfSSLTransportStatus(void)
{
  char status_line[384];

  PQC_WolfSSL_Transport_Init();

  if (PQC_WolfSSL_Transport_StatusLine(status_line, (uint32_t)sizeof(status_line)))
  {
    APP_UART_WriteString(status_line);
  }
  else
  {
    APP_UART_WriteString("wolfSSL transport boundary: evidence=unavailable-transport-only boundary=present callbacks=present network_boundary=present connect=unavailable read=unavailable write=unavailable socket_io=not-performed tls_handshake=unavailable certs=not-loaded mqtt_connect=unavailable mqtt_publish=unavailable reconnect=unavailable wifi=unavailable st67w61m1=unavailable end_to_end=unavailable reason=format_failed\r\n");
  }
}

static void APP_PrintFreeRTOSSchedulerStarting(void)
{
  APP_UART_WriteString("FreeRTOS scheduler starting: cmsis_rtos=v2 default_task=defaultTask tick_hz=");
  APP_UART_WriteUint32((uint32_t)configTICK_RATE_HZ);
  APP_UART_WriteString(" heap_bytes=");
  APP_UART_WriteUint32((uint32_t)configTOTAL_HEAP_SIZE);
  APP_UART_WriteString(" default_task_stack_words=512\r\n");
}

static void APP_PrintUnavailable(void)
{
  APP_UART_WriteString("unavailable");
}

static void APP_PrintApplicationMemoryCheckpoint(const char *stage, BaseType_t include_task_stack)
{
  size_t heap_total_bytes = (size_t)configTOTAL_HEAP_SIZE;
  size_t heap_free_bytes = xPortGetFreeHeapSize();
  size_t heap_min_ever_free_bytes = xPortGetMinimumEverFreeHeapSize();
  size_t heap_current_used_bytes = heap_total_bytes - heap_free_bytes;
  size_t heap_peak_used_bytes = heap_total_bytes - heap_min_ever_free_bytes;

  APP_UART_WriteString("application memory checkpoint: stage=");
  APP_UART_WriteString(stage);
  APP_UART_WriteString(" heap_total_bytes=");
  APP_UART_WriteUint32((uint32_t)heap_total_bytes);
  APP_UART_WriteString(" heap_free_bytes=");
  APP_UART_WriteUint32((uint32_t)heap_free_bytes);
  APP_UART_WriteString(" heap_min_ever_free_bytes=");
  APP_UART_WriteUint32((uint32_t)heap_min_ever_free_bytes);
  APP_UART_WriteString(" heap_current_used_bytes=");
  APP_UART_WriteUint32((uint32_t)heap_current_used_bytes);
  APP_UART_WriteString(" heap_peak_used_bytes=");
  APP_UART_WriteUint32((uint32_t)heap_peak_used_bytes);
  APP_UART_WriteString(" task_stack_total_bytes=");

  if (include_task_stack != pdFALSE)
  {
    UBaseType_t stack_high_water_words = uxTaskGetStackHighWaterMark(NULL);
    uint32_t stack_total_bytes = (uint32_t)defaultTask_attributes.stack_size;
    uint32_t stack_high_water_bytes = (uint32_t)stack_high_water_words * (uint32_t)sizeof(StackType_t);
    uint32_t stack_used_bytes =
        (stack_high_water_bytes <= stack_total_bytes) ?
        (stack_total_bytes - stack_high_water_bytes) : 0U;

    APP_UART_WriteUint32(stack_total_bytes);
    APP_UART_WriteString(" task_stack_high_water_bytes=");
    APP_UART_WriteUint32(stack_high_water_bytes);
    APP_UART_WriteString(" task_stack_used_bytes=");
    APP_UART_WriteUint32(stack_used_bytes);
  }
  else
  {
    APP_PrintUnavailable();
    APP_UART_WriteString(" task_stack_high_water_bytes=");
    APP_PrintUnavailable();
    APP_UART_WriteString(" task_stack_used_bytes=");
    APP_PrintUnavailable();
  }

  APP_UART_WriteString("\r\n");
}

static void APP_PrintApplicationClock(const char *name, uint32_t value)
{
  APP_UART_WriteString("application clock ");
  APP_UART_WriteString(name);
  APP_UART_WriteString(": ");
  APP_UART_WriteUint32(value);
  APP_UART_WriteString("\r\n");
}

static void APP_PrintApplicationClockConfiguration(void)
{
  APP_PrintApplicationClock("sysclk_hz", HAL_RCC_GetSysClockFreq());
  APP_PrintApplicationClock("hclk_hz", HAL_RCC_GetHCLKFreq());
  APP_PrintApplicationClock("pclk1_hz", HAL_RCC_GetPCLK1Freq());
  APP_PrintApplicationClock("pclk2_hz", HAL_RCC_GetPCLK2Freq());
}

#ifdef SECURE_BOOT_APPLICATION
#define PQC_BOOT_TIMING_MAILBOX_ADDR      0x10000000UL
#define PQC_BOOT_TIMING_MAILBOX_MAGIC     0x50514354UL
#define PQC_BOOT_TIMING_MAILBOX_VERSION   2UL

typedef struct
{
  uint32_t magic;
  uint32_t version;
  uint32_t elapsed_cycles;
  uint32_t verification_result;
  uint32_t max_stack_used_bytes;
  uint32_t sysclk_hz;
  uint32_t hclk_hz;
  uint32_t pclk1_hz;
  uint32_t pclk2_hz;
} PQC_BootTimingMailbox;

static void APP_PrintWolfBootClock(const char *name, uint32_t value)
{
  APP_UART_WriteString("wolfBoot clock ");
  APP_UART_WriteString(name);
  APP_UART_WriteString(": ");
  APP_UART_WriteUint32(value);
  APP_UART_WriteString("\r\n");
}

static void APP_PrintWolfBootVerificationTiming(void)
{
  volatile const PQC_BootTimingMailbox *mailbox =
      (volatile const PQC_BootTimingMailbox *)PQC_BOOT_TIMING_MAILBOX_ADDR;

  if ((mailbox->magic == PQC_BOOT_TIMING_MAILBOX_MAGIC) &&
      (mailbox->version == PQC_BOOT_TIMING_MAILBOX_VERSION))
  {
    APP_UART_WriteString("wolfBoot verification cycles: ");
    APP_UART_WriteUint32(mailbox->elapsed_cycles);
    APP_UART_WriteString(" cycles\r\n");

    APP_PrintWolfBootClock("sysclk_hz", mailbox->sysclk_hz);
    APP_PrintWolfBootClock("hclk_hz", mailbox->hclk_hz);
    APP_PrintWolfBootClock("pclk1_hz", mailbox->pclk1_hz);
    APP_PrintWolfBootClock("pclk2_hz", mailbox->pclk2_hz);

    APP_UART_WriteString("wolfBoot verification result: ");
    APP_UART_WriteUint32(mailbox->verification_result);
    APP_UART_WriteString("\r\n");

    if (mailbox->max_stack_used_bytes != 0xFFFFFFFFUL)
    {
      APP_UART_WriteString("wolfBoot verification max stack used: ");
      APP_UART_WriteUint32(mailbox->max_stack_used_bytes);
      APP_UART_WriteString(" bytes\r\n");
    }
  }
}
#endif

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_DMA_Init();
  MX_LPUART1_UART_Init();
  MX_SPI1_Init();
  /* USER CODE BEGIN 2 */

#ifdef SECURE_BOOT_APPLICATION
  APP_PrintWolfBootVerificationTiming();

  const char secure_boot_msg[] = "stm32-basic_hal1 secure-boot app v0.1.0\r\n";
  HAL_UART_Transmit(&hlpuart1, (uint8_t *)secure_boot_msg, sizeof(secure_boot_msg) - 1, HAL_MAX_DELAY);

  const char boot_msg[] = "stm32-basic_hal1 boot v0.1.0\r\n";
#else
  const char boot_msg[] = "\r\nstm32-basic_hal1 boot v0.1.0\r\n";
#endif
  HAL_UART_Transmit(&hlpuart1, (uint8_t *)boot_msg, sizeof(boot_msg) - 1, HAL_MAX_DELAY);
  APP_PrintLwIPRuntimeSmoke("pre_scheduler", false);
  APP_PrintNetworkInterfaceStatus();
  APP_PrintWolfSSLRuntimeSmoke("pre_scheduler", false);
  APP_PrintWolfSSLTransportStatus();

  /* USER CODE END 2 */

  /* Init scheduler */
  osKernelInitialize();

  /* USER CODE BEGIN RTOS_MUTEX */
  /* add mutexes, ... */
  /* USER CODE END RTOS_MUTEX */

  /* USER CODE BEGIN RTOS_SEMAPHORES */
  /* add semaphores, ... */
  /* USER CODE END RTOS_SEMAPHORES */

  /* USER CODE BEGIN RTOS_TIMERS */
  /* start timers, add new ones, ... */
  /* USER CODE END RTOS_TIMERS */

  /* USER CODE BEGIN RTOS_QUEUES */
  /* add queues, ... */
  /* USER CODE END RTOS_QUEUES */

  /* Create the thread(s) */
  /* creation of defaultTask */
  defaultTaskHandle = osThreadNew(StartDefaultTask, NULL, &defaultTask_attributes);

  /* USER CODE BEGIN RTOS_THREADS */
  if (defaultTaskHandle == NULL)
  {
    APP_UART_WriteString("FreeRTOS defaultTask create failed\r\n");
    Error_Handler();
  }
  APP_UART_WriteString("FreeRTOS defaultTask created: name=defaultTask priority=osPriorityNormal stack_words=512\r\n");
  APP_PrintApplicationMemoryCheckpoint("pre_scheduler", pdFALSE);
  /* USER CODE END RTOS_THREADS */

  /* USER CODE BEGIN RTOS_EVENTS */
  /* add events, ... */
  /* USER CODE END RTOS_EVENTS */

  /* USER CODE BEGIN RTOS_SCHEDULER_START */
  APP_PrintFreeRTOSSchedulerStarting();
  /* USER CODE END RTOS_SCHEDULER_START */

  /* Start scheduler */
  osKernelStart();

  /* We should never get here as control is now taken by the scheduler */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
    /* Scheduler should own normal application execution. */
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  if (HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE1_BOOST) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI;
  RCC_OscInitStruct.PLL.PLLM = 1;
  RCC_OscInitStruct.PLL.PLLN = 15;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = RCC_PLLQ_DIV2;
  RCC_OscInitStruct.PLL.PLLR = RCC_PLLR_DIV2;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_5) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief LPUART1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_LPUART1_UART_Init(void)
{

  /* USER CODE BEGIN LPUART1_Init 0 */

  /* USER CODE END LPUART1_Init 0 */

  /* USER CODE BEGIN LPUART1_Init 1 */

  /* USER CODE END LPUART1_Init 1 */
  hlpuart1.Instance = LPUART1;
  hlpuart1.Init.BaudRate = 115200;
  hlpuart1.Init.WordLength = UART_WORDLENGTH_8B;
  hlpuart1.Init.StopBits = UART_STOPBITS_1;
  hlpuart1.Init.Parity = UART_PARITY_NONE;
  hlpuart1.Init.Mode = UART_MODE_TX_RX;
  hlpuart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  hlpuart1.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
  hlpuart1.Init.ClockPrescaler = UART_PRESCALER_DIV1;
  hlpuart1.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;
  hlpuart1.FifoMode = UART_FIFOMODE_DISABLE;
  if (HAL_UART_Init(&hlpuart1) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_SetTxFifoThreshold(&hlpuart1, UART_TXFIFO_THRESHOLD_1_8) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_SetRxFifoThreshold(&hlpuart1, UART_RXFIFO_THRESHOLD_1_8) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_DisableFifoMode(&hlpuart1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN LPUART1_Init 2 */

  /* USER CODE END LPUART1_Init 2 */

}

/**
  * @brief SPI1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_SPI1_Init(void)
{

  /* USER CODE BEGIN SPI1_Init 0 */

  /* USER CODE END SPI1_Init 0 */

  /* USER CODE BEGIN SPI1_Init 1 */

  /* USER CODE END SPI1_Init 1 */
  /* SPI1 parameter configuration*/
  hspi1.Instance = SPI1;
  hspi1.Init.Mode = SPI_MODE_MASTER;
  hspi1.Init.Direction = SPI_DIRECTION_2LINES;
  hspi1.Init.DataSize = SPI_DATASIZE_8BIT;
  hspi1.Init.CLKPolarity = SPI_POLARITY_LOW;
  hspi1.Init.CLKPhase = SPI_PHASE_1EDGE;
  hspi1.Init.NSS = SPI_NSS_SOFT;
  hspi1.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_4;
  hspi1.Init.FirstBit = SPI_FIRSTBIT_MSB;
  hspi1.Init.TIMode = SPI_TIMODE_DISABLE;
  hspi1.Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
  hspi1.Init.CRCPolynomial = 7;
  hspi1.Init.CRCLength = SPI_CRC_LENGTH_DATASIZE;
  hspi1.Init.NSSPMode = SPI_NSS_PULSE_ENABLE;
  if (HAL_SPI_Init(&hspi1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN SPI1_Init 2 */

  /* USER CODE END SPI1_Init 2 */

}

/**
  * Enable DMA controller clock
  */
static void MX_DMA_Init(void)
{

  /* DMA controller clock enable */
  __HAL_RCC_DMAMUX1_CLK_ENABLE();
  __HAL_RCC_DMA1_CLK_ENABLE();

  /* DMA interrupt init */
  /* DMA1_Channel1_IRQn interrupt configuration */
  HAL_NVIC_SetPriority(DMA1_Channel1_IRQn, 5, 0);
  HAL_NVIC_EnableIRQ(DMA1_Channel1_IRQn);
  /* DMA1_Channel2_IRQn interrupt configuration */
  HAL_NVIC_SetPriority(DMA1_Channel2_IRQn, 5, 0);
  HAL_NVIC_EnableIRQ(DMA1_Channel2_IRQn);

}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  /* USER CODE BEGIN MX_GPIO_Init_1 */

  /* USER CODE END MX_GPIO_Init_1 */

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOE_CLK_ENABLE();
  __HAL_RCC_GPIOC_CLK_ENABLE();
  __HAL_RCC_GPIOF_CLK_ENABLE();
  __HAL_RCC_GPIOH_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_GPIOD_CLK_ENABLE();
  __HAL_RCC_GPIOG_CLK_ENABLE();
  HAL_PWREx_EnableVddIO2();

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOE, BOOT_Pin|CHIP_EN_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(SPI_CS_GPIO_Port, SPI_CS_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_7, GPIO_PIN_RESET);

  /*Configure GPIO pins : PE2 PE3 */
  GPIO_InitStruct.Pin = GPIO_PIN_2|GPIO_PIN_3;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  GPIO_InitStruct.Alternate = GPIO_AF13_SAI1;
  HAL_GPIO_Init(GPIOE, &GPIO_InitStruct);

  /*Configure GPIO pins : PF0 PF1 PF2 */
  GPIO_InitStruct.Pin = GPIO_PIN_0|GPIO_PIN_1|GPIO_PIN_2;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_OD;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  GPIO_InitStruct.Alternate = GPIO_AF4_I2C2;
  HAL_GPIO_Init(GPIOF, &GPIO_InitStruct);

  /*Configure GPIO pin : PF7 */
  GPIO_InitStruct.Pin = GPIO_PIN_7;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  GPIO_InitStruct.Alternate = GPIO_AF13_SAI1;
  HAL_GPIO_Init(GPIOF, &GPIO_InitStruct);

  /*Configure GPIO pins : PC0 PC1 PC2 PC3
                           PC4 PC5 */
  GPIO_InitStruct.Pin = GPIO_PIN_0|GPIO_PIN_1|GPIO_PIN_2|GPIO_PIN_3
                          |GPIO_PIN_4|GPIO_PIN_5;
  GPIO_InitStruct.Mode = GPIO_MODE_ANALOG_ADC_CONTROL;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOC, &GPIO_InitStruct);

  /*Configure GPIO pin : PA0 */
  GPIO_InitStruct.Pin = GPIO_PIN_0;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  GPIO_InitStruct.Alternate = GPIO_AF1_TIM2;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /*Configure GPIO pins : PA1 PA3 */
  GPIO_InitStruct.Pin = GPIO_PIN_1|GPIO_PIN_3;
  GPIO_InitStruct.Mode = GPIO_MODE_ANALOG_ADC_CONTROL;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /*Configure GPIO pin : PB0 */
  GPIO_InitStruct.Pin = GPIO_PIN_0;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  GPIO_InitStruct.Alternate = GPIO_AF2_TIM3;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /*Configure GPIO pin : PB1 */
  GPIO_InitStruct.Pin = GPIO_PIN_1;
  GPIO_InitStruct.Mode = GPIO_MODE_ANALOG_ADC_CONTROL;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /*Configure GPIO pins : PB2 PB6 */
  GPIO_InitStruct.Pin = GPIO_PIN_2|GPIO_PIN_6;
  GPIO_InitStruct.Mode = GPIO_MODE_ANALOG;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /*Configure GPIO pin : USER_BUTTON_Pin */
  GPIO_InitStruct.Pin = USER_BUTTON_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_IT_FALLING;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(USER_BUTTON_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pins : PE7 PE8 PE10 PE12 */
  GPIO_InitStruct.Pin = GPIO_PIN_7|GPIO_PIN_8|GPIO_PIN_10|GPIO_PIN_12;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  GPIO_InitStruct.Alternate = GPIO_AF1_TIM1;
  HAL_GPIO_Init(GPIOE, &GPIO_InitStruct);

  /*Configure GPIO pin : BOOT_Pin */
  GPIO_InitStruct.Pin = BOOT_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(BOOT_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : CHIP_EN_Pin */
  GPIO_InitStruct.Pin = CHIP_EN_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
  HAL_GPIO_Init(CHIP_EN_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : SPI_RDY_Pin */
  GPIO_InitStruct.Pin = SPI_RDY_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_IT_RISING_FALLING;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(SPI_RDY_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pins : PE14 PE15 */
  GPIO_InitStruct.Pin = GPIO_PIN_14|GPIO_PIN_15;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  GPIO_InitStruct.Alternate = GPIO_AF3_TIM1_COMP1;
  HAL_GPIO_Init(GPIOE, &GPIO_InitStruct);

  /*Configure GPIO pin : PB10 */
  GPIO_InitStruct.Pin = GPIO_PIN_10;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  GPIO_InitStruct.Alternate = GPIO_AF1_TIM2;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /*Configure GPIO pins : PB12 PB13 PB15 */
  GPIO_InitStruct.Pin = GPIO_PIN_12|GPIO_PIN_13|GPIO_PIN_15;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  GPIO_InitStruct.Alternate = GPIO_AF13_SAI2;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /*Configure GPIO pin : PB14 */
  GPIO_InitStruct.Pin = GPIO_PIN_14;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  GPIO_InitStruct.Alternate = GPIO_AF14_TIM15;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /*Configure GPIO pins : PD8 PD9 */
  GPIO_InitStruct.Pin = GPIO_PIN_8|GPIO_PIN_9;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  GPIO_InitStruct.Alternate = GPIO_AF7_USART3;
  HAL_GPIO_Init(GPIOD, &GPIO_InitStruct);

  /*Configure GPIO pin : SPI_CS_Pin */
  GPIO_InitStruct.Pin = SPI_CS_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
  HAL_GPIO_Init(SPI_CS_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : PD15 */
  GPIO_InitStruct.Pin = GPIO_PIN_15;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  GPIO_InitStruct.Alternate = GPIO_AF2_TIM4;
  HAL_GPIO_Init(GPIOD, &GPIO_InitStruct);

  /*Configure GPIO pin : PC6 */
  GPIO_InitStruct.Pin = GPIO_PIN_6;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  GPIO_InitStruct.Alternate = GPIO_AF13_SAI2;
  HAL_GPIO_Init(GPIOC, &GPIO_InitStruct);

  /*Configure GPIO pin : PC7 */
  GPIO_InitStruct.Pin = GPIO_PIN_7;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  GPIO_InitStruct.Alternate = GPIO_AF2_TIM3;
  HAL_GPIO_Init(GPIOC, &GPIO_InitStruct);

  /*Configure GPIO pins : PC8 PC9 PC10 PC11
                           PC12 */
  GPIO_InitStruct.Pin = GPIO_PIN_8|GPIO_PIN_9|GPIO_PIN_10|GPIO_PIN_11
                          |GPIO_PIN_12;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  GPIO_InitStruct.Alternate = GPIO_AF12_SDMMC1;
  HAL_GPIO_Init(GPIOC, &GPIO_InitStruct);

  /*Configure GPIO pins : PA8 PA10 */
  GPIO_InitStruct.Pin = GPIO_PIN_8|GPIO_PIN_10;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  GPIO_InitStruct.Alternate = GPIO_AF10_OTG_FS;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /*Configure GPIO pin : PA9 */
  GPIO_InitStruct.Pin = GPIO_PIN_9;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /*Configure GPIO pin : PD0 */
  GPIO_InitStruct.Pin = GPIO_PIN_0;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  GPIO_InitStruct.Alternate = GPIO_AF9_CAN1;
  HAL_GPIO_Init(GPIOD, &GPIO_InitStruct);

  /*Configure GPIO pin : PD2 */
  GPIO_InitStruct.Pin = GPIO_PIN_2;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  GPIO_InitStruct.Alternate = GPIO_AF12_SDMMC1;
  HAL_GPIO_Init(GPIOD, &GPIO_InitStruct);

  /*Configure GPIO pins : PD3 PD4 PD5 PD6 */
  GPIO_InitStruct.Pin = GPIO_PIN_3|GPIO_PIN_4|GPIO_PIN_5|GPIO_PIN_6;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  GPIO_InitStruct.Alternate = GPIO_AF7_USART2;
  HAL_GPIO_Init(GPIOD, &GPIO_InitStruct);

  /*Configure GPIO pins : PB3 PB4 PB5 */
  GPIO_InitStruct.Pin = GPIO_PIN_3|GPIO_PIN_4|GPIO_PIN_5;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  GPIO_InitStruct.Alternate = GPIO_AF6_SPI3;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /*Configure GPIO pin : PB7 */
  GPIO_InitStruct.Pin = GPIO_PIN_7;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /*Configure GPIO pins : PB8 PB9 */
  GPIO_InitStruct.Pin = GPIO_PIN_8|GPIO_PIN_9;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_OD;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  GPIO_InitStruct.Alternate = GPIO_AF4_I2C1;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /*Configure GPIO pin : PE0 */
  GPIO_InitStruct.Pin = GPIO_PIN_0;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  GPIO_InitStruct.Alternate = GPIO_AF2_TIM4;
  HAL_GPIO_Init(GPIOE, &GPIO_InitStruct);

  /* EXTI interrupt init*/
  HAL_NVIC_SetPriority(EXTI15_10_IRQn, 5, 0);
  HAL_NVIC_EnableIRQ(EXTI15_10_IRQn);

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */

void HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin)
{
  if (GPIO_Pin == SPI_RDY_Pin)
  {
    if (HAL_GPIO_ReadPin(SPI_RDY_GPIO_Port, SPI_RDY_Pin) == GPIO_PIN_SET)
    {
      (void)spi_on_txn_data_ready();
    }
    else
    {
      (void)spi_on_header_ack();
    }
  }
}

/* USER CODE END 4 */

/* USER CODE BEGIN Header_StartDefaultTask */
/**
  * @brief  Function implementing the defaultTask thread.
  * @param  argument: Not used
  * @retval None
  */
/* USER CODE END Header_StartDefaultTask */
void StartDefaultTask(void *argument)
{
  /* USER CODE BEGIN 5 */
  const char task_started_msg[] = "FreeRTOS defaultTask started: periodic tick task active\r\n";
  const char tick_msg[] = "tick\r\n";

  BaseType_t runtime_checkpoint_reported = pdFALSE;

  HAL_UART_Transmit(&hlpuart1, (uint8_t *)task_started_msg, sizeof(task_started_msg) - 1, HAL_MAX_DELAY);
  APP_RunST67SPIBringup();
  APP_UART_WriteString("FreeRTOS task-context smoke starting: context=freertos_task scheduler=running serialized=true\r\n");
  APP_PrintLwIPRuntimeSmoke("freertos_task", true);
  APP_RunLwIPLocalLoopbackSmoke();
  APP_PrintWolfSSLRuntimeSmoke("freertos_task", true);
  APP_PrintWolfMQTTRuntimeStatus();
  APP_UART_WriteString("FreeRTOS task-context smoke complete: context=freertos_task scheduler=running network=unavailable tls_handshake=unavailable mqtt=unavailable\r\n");
  APP_PrintApplicationClockConfiguration();
  APP_PrintApplicationMemoryCheckpoint("default_task_start", pdTRUE);

  /* Infinite loop */
  for(;;)
  {
    HAL_GPIO_TogglePin(GPIOB, GPIO_PIN_7);
    HAL_UART_Transmit(&hlpuart1, (uint8_t *)tick_msg, sizeof(tick_msg) - 1, HAL_MAX_DELAY);
    osDelay(1000);

    if (runtime_checkpoint_reported == pdFALSE)
    {
      APP_PrintApplicationMemoryCheckpoint("default_task_runtime", pdTRUE);
      runtime_checkpoint_reported = pdTRUE;
    }
  }
  /* USER CODE END 5 */
}

/**
  * @brief  Period elapsed callback in non blocking mode
  * @note   This function is called  when TIM1 interrupt took place, inside
  * HAL_TIM_IRQHandler(). It makes a direct call to HAL_IncTick() to increment
  * a global variable "uwTick" used as application time base.
  * @param  htim : TIM handle
  * @retval None
  */
void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
  /* USER CODE BEGIN Callback 0 */

  /* USER CODE END Callback 0 */
  if (htim->Instance == TIM1)
  {
    HAL_IncTick();
  }
  /* USER CODE BEGIN Callback 1 */

  /* USER CODE END Callback 1 */
}

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
