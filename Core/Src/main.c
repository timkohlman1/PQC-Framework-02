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
#include "lwip.h"
#include "pqc_wifi_config.h"
#include "pqc_network_interface.h"
#include "pqc_energy_boundary.h"
#ifndef PQC_TLS_COMPILED
#define PQC_TLS_COMPILED 1
#endif
#if PQC_TLS_COMPILED
#include "pqc_wolfssl_build_only.h"
#include "pqc_wolfssl_transport.h"
#include "pqc_wolfssl_memory.h"
#endif
#include "pqc_wolfmqtt_build_only.h"
#include "pqc_mqtt_application.h"

#ifndef PQC_TLS_HANDSHAKE_REPEAT_ENABLED
#define PQC_TLS_HANDSHAKE_REPEAT_ENABLED 0
#endif
#include "w6x_api.h"
#include "spi_iface.h"
#include "logging.h"
#include "FreeRTOS.h"
#include "task.h"
#include "pqc_ram_accounting.h"
#include "pqc_result_buffer.h"
#include "pqc_boot_evidence.h"
#include "pqc_tls_instrumentation.h"
#include "pqc_timebase.h"
#ifndef PQC_BAREMETAL_BENCHMARK_ENABLED
#define PQC_BAREMETAL_BENCHMARK_ENABLED 0
#endif
#if PQC_BAREMETAL_BENCHMARK_ENABLED
#include "pqc_benchmark_stm32.h"
#endif
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define APP_ST67_WIFI_SCAN_TIMEOUT_MS 8000U
#define APP_ST67_WIFI_SCAN_POLL_MS      20U
#define APP_ST67_WIFI_SCAN_MAX_RESULTS  10U
#define APP_ST67_ASSOC_TIMEOUT_MS      20000U
#define APP_ST67_ASSOC_POLL_MS           250U
#define APP_ST67_ASSOC_LOG_INTERVAL_MS  1000U
#define APP_ST67_DHCP_TIMEOUT_MS       15000U
#define APP_ST67_DHCP_POLL_MS            100U
#define APP_ST67_DHCP_LOG_INTERVAL_MS   1000U
/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
#if PQC_UART_OUTPUT_MODE != 0 || PQC_ENERGY_SYNC_ENABLED
UART_HandleTypeDef hlpuart1;
#endif

SPI_HandleTypeDef hspi1;
DMA_HandleTypeDef hdma_spi1_tx;
DMA_HandleTypeDef hdma_spi1_rx;

/* Definitions for defaultTask */
osThreadId_t defaultTaskHandle;
const osThreadAttr_t defaultTask_attributes = {
  .name = "defaultTask",
  .stack_size = 1024 * 4,
  .priority = (osPriority_t) osPriorityNormal,
};
/* USER CODE BEGIN PV */
static volatile APP_ST67ReadyDiagnosticSnapshot app_st67_ready_diagnostic;
osThreadId_t networkTaskHandle;
const osThreadAttr_t networkTask_attributes = {
  .name = "networkTask",
  .stack_size = 2048 * 4,
  .priority = (osPriority_t) osPriorityNormal,
};
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_DMA_Init(void);
#if PQC_UART_OUTPUT_MODE != 0 || PQC_ENERGY_SYNC_ENABLED
static void MX_LPUART1_UART_Init(void);
#endif
static void MX_SPI1_Init(void);
void StartDefaultTask(void *argument);

/* USER CODE BEGIN PFP */
void StartNetworkTask(void *argument);

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

void APP_ST67ReadyDiagnosticSnapshotGet(APP_ST67ReadyDiagnosticSnapshot *snapshot)
{
  if (snapshot == NULL)
  {
    return;
  }

  taskENTER_CRITICAL();
  snapshot->irq_count = app_st67_ready_diagnostic.irq_count;
  snapshot->rising_count = app_st67_ready_diagnostic.rising_count;
  snapshot->falling_count = app_st67_ready_diagnostic.falling_count;
  snapshot->last_rising_tick = app_st67_ready_diagnostic.last_rising_tick;
  snapshot->last_falling_tick = app_st67_ready_diagnostic.last_falling_tick;
  snapshot->last_level = app_st67_ready_diagnostic.last_level;
  taskEXIT_CRITICAL();
}

#ifndef PQC_UART_LOG_LEVEL
#define PQC_UART_LOG_LEVEL 1
#endif

#ifndef PQC_UART_OUTPUT_MODE
#define PQC_UART_OUTPUT_MODE 1
#endif

#define APP_UART_LOG_LEVEL_OFF  (-1)
#define APP_UART_LOG_LEVEL_ERROR 0
#define APP_UART_LOG_LEVEL_INFO  1
#define APP_UART_LOG_LEVEL_DEBUG 2
#define APP_UART_LINE_BUFFER_SIZE 2048U

static char app_uart_line_buffer[APP_UART_LINE_BUFFER_SIZE];
static uint32_t app_uart_line_length = 0U;
static bool app_measurement_active = false;
#if defined(PQC_TIMEBASE_HARDWARE_SELF_TEST) && PQC_TIMEBASE_HARDWARE_SELF_TEST
static uint32_t app_timebase_self_test_elapsed_us;
static uint32_t app_timebase_self_test_hal_tick_delta_ms;
static uint32_t app_timebase_self_test_valid;
#endif

static bool APP_UART_LineContains(const char *line, const char *needle)
{
  uint32_t line_index;
  uint32_t needle_index;

  if ((line == NULL) || (needle == NULL) || (needle[0] == '\0'))
  {
    return false;
  }

  for (line_index = 0U; line[line_index] != '\0'; line_index++)
  {
    for (needle_index = 0U;
         (needle[needle_index] != '\0') &&
         (line[line_index + needle_index] != '\0') &&
         (line[line_index + needle_index] == needle[needle_index]);
         needle_index++)
    {
    }
    if (needle[needle_index] == '\0')
    {
      return true;
    }
  }
  return false;
}

static bool APP_UART_LineStartsWith(const char *line, const char *prefix)
{
  uint32_t index = 0U;

  while (prefix[index] != '\0')
  {
    if (line[index] != prefix[index])
    {
      return false;
    }
    index++;
  }
  return true;
}

static bool APP_UART_LineIsWhitespaceOnly(const char *line)
{
  uint32_t index = 0U;

  while (line[index] != '\0')
  {
    if ((line[index] != ' ') && (line[index] != '\t'))
    {
      return false;
    }
    index++;
  }
  return true;
}

static bool APP_UART_ShouldEmitLine(const char *line)
{
#if PQC_UART_OUTPUT_MODE == 0
  (void)line;
  return false;
#elif PQC_UART_OUTPUT_MODE >= 2
  (void)line;
  return true;
#else
  if (app_measurement_active)
  {
    return false;
  }
#if PQC_UART_LOG_LEVEL <= APP_UART_LOG_LEVEL_OFF
  (void)line;
  return false;
#elif PQC_UART_LOG_LEVEL >= APP_UART_LOG_LEVEL_DEBUG
  (void)line;
  return true;
#else
  static const char *const debug_prefixes[] = {
      "lwIP runtime smoke: context=pre_scheduler",
      "lwIP network interface:",
      "FreeRTOS defaultTask created:",
      "FreeRTOS networkTask created:",
      "FreeRTOS scheduler starting:",
      "FreeRTOS defaultTask started:",
      "FreeRTOS networkTask started:",
      "ST67 SPI bring-up pins:",
      "ST67 Wi-Fi scan: begin",
      "ST67 Wi-Fi scan result:",
      "ST67 Wi-Fi event:",
      "ST67 Wi-Fi connect options:",
      "ST67 Wi-Fi association: begin",
      "ST67 Wi-Fi association poll:",
      "ST67 DHCP poll:",
      "ST67 DNS: required=false",
      "ST67 DNS lookup: result=not_required",
      "wolfMQTT transport: stage=close",
      "application memory checkpoint: stage=pre_scheduler",
      "application memory checkpoint: stage=default_task_runtime",
      "application task stack: stage=default_task_runtime",
      "--------------- ST67W6X info",
      "ST67W6X MW Version:",
      "AT Version:",
      "SDK Version:",
      "Wi-Fi MAC Version:",
      "BT Controller Version:",
      "BT Stack Version:",
      "Build Date:",
      "Module ID:",
      "BOM ID:",
      "Manufacturing Year:",
      "Manufacturing Week:",
      "Battery Voltage:",
      "Trim Wi-Fi hp:",
      "Trim Wi-Fi lp:",
      "Trim BLE:",
      "Trim XTAL:",
      "MAC Address:",
      "Anti-rollback Bootloader:",
      "Anti-rollback App:",
      "-----------------------------------------",
      "Netif : Link is up",
      "STA IP :",
      "IP :",
      "Gateway :",
      "Netmask :"
  };
  uint32_t index;

  if ((line[0] == '\0') || APP_UART_LineIsWhitespaceOnly(line))
  {
    return false;
  }

  if (APP_UART_LineContains(line, "failed") ||
      APP_UART_LineContains(line, "error") ||
      APP_UART_LineContains(line, "status_ok=0") ||
      APP_UART_LineContains(line, "result=timeout") ||
      APP_UART_LineContains(line, "result=connect_failed"))
  {
    return true;
  }

#if PQC_UART_LOG_LEVEL <= APP_UART_LOG_LEVEL_ERROR
  return false;
#else
  if (APP_UART_LineStartsWith(line, "ST67 SPI bring-up: W6X_RegisterAppCb result=0") ||
      APP_UART_LineStartsWith(line, "ST67 SPI bring-up: W6X_Init begin") ||
      APP_UART_LineStartsWith(line, "ST67 SPI bring-up: W6X_Init result=0") ||
      APP_UART_LineStartsWith(line, "ST67 Wi-Fi association: connect_call_status=0") ||
      APP_UART_LineStartsWith(line, "wolfMQTT TLS: stage=tcp_connect result=0"))
  {
    return false;
  }

  for (index = 0U; index < (sizeof(debug_prefixes) / sizeof(debug_prefixes[0])); index++)
  {
    if (APP_UART_LineStartsWith(line, debug_prefixes[index]))
    {
      return false;
    }
  }
  return true;
#endif
#endif
#endif
}

static void APP_UART_WriteRaw(const char *text, uint16_t length)
{
#if PQC_UART_OUTPUT_MODE != 0
  if (length > 0U)
  {
    HAL_UART_Transmit(&hlpuart1, (uint8_t *)text, length, HAL_MAX_DELAY);
  }
#else
  (void)text;
  (void)length;
#endif
}

static void APP_UART_WriteTickPrefix(void)
{
  char prefix[24];
  char digits[10];
  uint32_t tick = HAL_GetTick();
  uint32_t count = 0U;
  uint32_t digit_count;
  uint32_t index = 0U;

  prefix[index++] = '[';
  prefix[index++] = 't';
  prefix[index++] = 'i';
  prefix[index++] = 'c';
  prefix[index++] = 'k';
  prefix[index++] = '=';

  do
  {
    digits[count++] = (char)('0' + (tick % 10U));
    tick /= 10U;
  } while ((tick > 0U) && (count < sizeof(digits)));

  digit_count = count;
  while (digit_count < 10U)
  {
    prefix[index++] = '0';
    digit_count++;
  }

  while (count > 0U)
  {
    prefix[index++] = digits[--count];
  }
  prefix[index++] = ']';
  prefix[index++] = ' ';
  APP_UART_WriteRaw(prefix, (uint16_t)index);
}

static void APP_UART_FlushLine(void)
{
  app_uart_line_buffer[app_uart_line_length] = '\0';
  if (APP_UART_ShouldEmitLine(app_uart_line_buffer))
  {
    APP_UART_WriteTickPrefix();
    APP_UART_WriteRaw(app_uart_line_buffer, (uint16_t)app_uart_line_length);
    APP_UART_WriteRaw("\r\n", 2U);
  }
  app_uart_line_length = 0U;
}

static void APP_UART_WriteString(const char *text)
{
  uint32_t index = 0U;

  if (text == NULL)
  {
    return;
  }

  while (text[index] != '\0')
  {
    char character = text[index++];
    if (character == '\r')
    {
      continue;
    }
    if (character == '\n')
    {
      APP_UART_FlushLine();
      continue;
    }
    if (app_uart_line_length < (APP_UART_LINE_BUFFER_SIZE - 1U))
    {
      app_uart_line_buffer[app_uart_line_length++] = character;
    }
  }
}

static void APP_UART_WriteUint32(uint32_t value)
{
  char reversed_digits[10];
  char output[11];
  uint32_t count = 0U;
  uint32_t index = 0U;

  do
  {
    reversed_digits[count++] = (char)('0' + (value % 10U));
    value /= 10U;
  } while ((value > 0U) && (count < sizeof(reversed_digits)));

  while (count > 0U)
  {
    output[index++] = reversed_digits[count - 1U];
    count--;
  }
  output[index] = '\0';
  APP_UART_WriteString(output);
}



static void APP_UART_WriteIPv4(const uint8_t address[4])
{
  APP_UART_WriteUint32(address[0]); APP_UART_WriteString(".");
  APP_UART_WriteUint32(address[1]); APP_UART_WriteString(".");
  APP_UART_WriteUint32(address[2]); APP_UART_WriteString(".");
  APP_UART_WriteUint32(address[3]);
}


#if defined(PQC_TIMEBASE_HARDWARE_SELF_TEST) && PQC_TIMEBASE_HARDWARE_SELF_TEST
static void APP_RunTimebaseHardwareSelfTest(void)
{
  uint64_t start_us;
  uint64_t end_us;
  uint64_t elapsed_us;
  uint32_t start_tick_ms;
  uint32_t end_tick_ms;

  start_tick_ms = HAL_GetTick();
  start_us = PQC_TimebaseNowUs();
  HAL_Delay(10U);
  end_us = PQC_TimebaseNowUs();
  end_tick_ms = HAL_GetTick();
  elapsed_us = PQC_TimebaseElapsedUs(start_us, end_us);
  app_timebase_self_test_elapsed_us =
      (elapsed_us > 0xFFFFFFFFULL) ? 0xFFFFFFFFUL : (uint32_t)elapsed_us;
  app_timebase_self_test_hal_tick_delta_ms = end_tick_ms - start_tick_ms;
  app_timebase_self_test_valid = 1U;
}

static void APP_PrintTimebaseHardwareSelfTest(void)
{
  const PQC_TimebaseProvenance *provenance = PQC_TimebaseGetProvenance();
  if (app_timebase_self_test_valid == 0U)
  {
    return;
  }
  APP_UART_WriteString("PQC_TIMEBASE_SELF_TEST delay_ms=10 elapsed_us=");
  APP_UART_WriteUint32(app_timebase_self_test_elapsed_us);
  APP_UART_WriteString(" hal_tick_delta_ms=");
  APP_UART_WriteUint32(app_timebase_self_test_hal_tick_delta_ms);
  APP_UART_WriteString(" timer_input_clock_hz=");
  APP_UART_WriteUint32(provenance->timer_input_clock_hz);
  APP_UART_WriteString(" prescaler=");
  APP_UART_WriteUint32(provenance->prescaler);
  APP_UART_WriteString(" counter_hz=");
  APP_UART_WriteUint32(provenance->counter_hz);
  APP_UART_WriteString("\r\n");
}
#endif

static void APP_UART_WriteInt32(int32_t value)
{
  if (value < 0)
  {
    APP_UART_WriteString("-");
    APP_UART_WriteUint32((uint32_t)(-(value + 1)) + 1U);
  }
  else
  {
    APP_UART_WriteUint32((uint32_t)value);
  }
}

static bool APP_CStringEquals(const uint8_t *left, const char *right)
{
  uint32_t index = 0U;

  while ((left[index] != 0U) && (right[index] != '\0'))
  {
    if (left[index] != (uint8_t)right[index])
    {
      return false;
    }
    index++;
  }

  return (left[index] == 0U) && (right[index] == '\0');
}

#ifndef PQC_WIFI_SCAN_VERBOSE
#define PQC_WIFI_SCAN_VERBOSE 0
#endif

static volatile bool app_experiment_complete = false;
static volatile bool app_wifi_scan_complete = false;
static volatile int32_t app_wifi_scan_status = (int32_t)W6X_STATUS_ERROR;
static volatile uint32_t app_wifi_scan_count = 0U;
static volatile bool app_wifi_scan_configured_ssid_found = false;
static volatile int16_t app_wifi_scan_best_rssi = INT16_MIN;
static volatile uint8_t app_wifi_scan_best_channel = 0U;
static volatile W6X_WiFi_SecurityType_e app_wifi_scan_best_security = W6X_WIFI_SECURITY_UNKNOWN;

static void APP_ST67WiFiScanCallback(int32_t status, W6X_WiFi_Scan_Result_t *results)
{
  uint32_t count = 0U;

  app_wifi_scan_status = status;
  if ((status == (int32_t)W6X_STATUS_OK) && (results != NULL) && (results->AP != NULL))
  {
    app_wifi_scan_count = results->Count;
    for (count = 0U; count < results->Count; count++)
    {
      W6X_WiFi_Ap_t *ap = &results->AP[count];

#if PQC_WIFI_SCAN_VERBOSE
      APP_UART_WriteString("ST67 Wi-Fi scan result: index=");
      APP_UART_WriteUint32(count);
      APP_UART_WriteString(" ssid=");
      APP_UART_WriteString((const char *)ap->SSID);
      APP_UART_WriteString(" rssi_dbm=");
      APP_UART_WriteInt32((int32_t)ap->RSSI);
      APP_UART_WriteString(" channel=");
      APP_UART_WriteUint32((uint32_t)ap->Channel);
      APP_UART_WriteString(" security=");
      APP_UART_WriteString(W6X_WiFi_SecurityToStr((uint32_t)ap->Security));
      APP_UART_WriteString("\r\n");
#endif

      if (APP_CStringEquals(ap->SSID, PQC_WIFI_SSID) &&
          (!app_wifi_scan_configured_ssid_found || (ap->RSSI > app_wifi_scan_best_rssi)))
      {
        app_wifi_scan_configured_ssid_found = true;
        app_wifi_scan_best_rssi = ap->RSSI;
        app_wifi_scan_best_channel = ap->Channel;
        app_wifi_scan_best_security = ap->Security;
      }
    }
  }

  app_wifi_scan_complete = true;
}

static bool APP_RunST67WiFiScan(void)
{
  W6X_WiFi_Scan_Opts_t options = {0};
  W6X_Status_t status;
  uint32_t elapsed_ms = 0U;

  app_wifi_scan_complete = false;
  app_wifi_scan_status = (int32_t)W6X_STATUS_ERROR;
  app_wifi_scan_count = 0U;
  app_wifi_scan_configured_ssid_found = false;
  app_wifi_scan_best_rssi = INT16_MIN;
  app_wifi_scan_best_channel = 0U;
  app_wifi_scan_best_security = W6X_WIFI_SECURITY_UNKNOWN;

  options.Scan_type = W6X_WIFI_SCAN_ACTIVE;
  options.MaxCnt = APP_ST67_WIFI_SCAN_MAX_RESULTS;

  APP_UART_WriteString("ST67 Wi-Fi scan: begin max_results=");
  APP_UART_WriteUint32(APP_ST67_WIFI_SCAN_MAX_RESULTS);
  APP_UART_WriteString(" timeout_ms=");
  APP_UART_WriteUint32(APP_ST67_WIFI_SCAN_TIMEOUT_MS);
  APP_UART_WriteString("\r\n");

  status = W6X_WiFi_Scan(&options, APP_ST67WiFiScanCallback);
  if (status != W6X_STATUS_OK)
  {
    APP_UART_WriteString("ST67 Wi-Fi scan summary: result=start_failed status=");
    APP_UART_WriteInt32((int32_t)status);
    APP_UART_WriteString(" count=0 configured_ssid_found=0\r\n");
    return false;
  }

  while (!app_wifi_scan_complete && (elapsed_ms < APP_ST67_WIFI_SCAN_TIMEOUT_MS))
  {
    osDelay(APP_ST67_WIFI_SCAN_POLL_MS);
    elapsed_ms += APP_ST67_WIFI_SCAN_POLL_MS;
  }

  if (!app_wifi_scan_complete)
  {
    APP_UART_WriteString("ST67 Wi-Fi scan summary: result=timeout count=0 configured_ssid_found=0\r\n");
    return false;
  }

  APP_UART_WriteString("ST67 Wi-Fi scan summary: result=");
  APP_UART_WriteString((app_wifi_scan_status == (int32_t)W6X_STATUS_OK) ? "passed" : "failed");
  APP_UART_WriteString(" status=");
  APP_UART_WriteInt32(app_wifi_scan_status);
  APP_UART_WriteString(" count=");
  APP_UART_WriteUint32(app_wifi_scan_count);
  APP_UART_WriteString(" configured_ssid_found=");
  APP_UART_WriteUint32(app_wifi_scan_configured_ssid_found ? 1U : 0U);
  if (app_wifi_scan_configured_ssid_found)
  {
    APP_UART_WriteString(" best_rssi_dbm=");
    APP_UART_WriteInt32((int32_t)app_wifi_scan_best_rssi);
    APP_UART_WriteString(" channel=");
    APP_UART_WriteUint32((uint32_t)app_wifi_scan_best_channel);
    APP_UART_WriteString(" security=");
    APP_UART_WriteString(W6X_WiFi_SecurityToStr((uint32_t)app_wifi_scan_best_security));
  }
  APP_UART_WriteString("\r\n");

  return app_wifi_scan_status == (int32_t)W6X_STATUS_OK;
}

static void APP_CopyCString(uint8_t *destination, uint32_t capacity, const char *source)
{
  uint32_t index = 0U;
  while ((index + 1U < capacity) && (source[index] != '\0')) { destination[index] = (uint8_t)source[index]; index++; }
  destination[index] = 0U;
}

static volatile uint32_t app_st67_wifi_event_count = 0U;
static volatile uint32_t app_st67_error_count = 0U;
static volatile bool app_st67_wifi_connected = false;
static volatile bool app_st67_wifi_reason_available = false;
static volatile uint32_t app_st67_wifi_reason_code = 0U;

static const char *APP_W6XStatusToString(W6X_Status_t status)
{
  switch (status)
  {
    case W6X_STATUS_OK: return "OK";
    case W6X_STATUS_BUSY: return "BUSY";
    case W6X_STATUS_ERROR: return "ERROR";
    case W6X_STATUS_TIMEOUT: return "TIMEOUT";
    case W6X_STATUS_UNEXPECTED_RESPONSE: return "UNEXPECTED_RESPONSE";
    case W6X_STATUS_NOT_SUPPORTED: return "NOT_SUPPORTED";
    case W6X_STATUS_UNKNOWN: return "UNKNOWN";
    default: return "INVALID";
  }
}

static const char *APP_WiFiStateToString(W6X_WiFi_StaStateType_e state)
{
  switch (state)
  {
    case W6X_WIFI_STATE_STA_NO_STARTED_CONNECTION: return "NOT_STARTED";
    case W6X_WIFI_STATE_STA_CONNECTED: return "CONNECTED";
    case W6X_WIFI_STATE_STA_GOT_IP: return "GOT_IP";
    case W6X_WIFI_STATE_STA_CONNECTING: return "CONNECTING";
    case W6X_WIFI_STATE_STA_DISCONNECTED: return "DISCONNECTED";
    case W6X_WIFI_STATE_STA_OFF: return "OFF";
    default: return "INVALID";
  }
}

static const char *APP_WiFiEventToString(W6X_event_id_t event_id)
{
  switch (event_id)
  {
    case W6X_WIFI_EVT_CONNECTED_ID: return "CONNECTED";
    case W6X_WIFI_EVT_DISCONNECTED_ID: return "DISCONNECTED";
    case W6X_WIFI_EVT_GOT_IP_ID: return "GOT_IP";
    case W6X_WIFI_EVT_CONNECTING_ID: return "CONNECTING";
    case W6X_WIFI_EVT_REASON_ID: return "REASON";
    case W6X_WIFI_EVT_STA_CONNECTED_ID: return "STA_CONNECTED";
    case W6X_WIFI_EVT_STA_DISCONNECTED_ID: return "STA_DISCONNECTED";
    case W6X_WIFI_EVT_DIST_STA_IP_ID: return "STA_IP_ASSIGNED";
    default: return "UNKNOWN";
  }
}

static uint32_t APP_CStringLengthBounded(const char *text, uint32_t capacity)
{
  uint32_t length = 0U;

  while ((length < capacity) && (text[length] != '\0'))
  {
    length++;
  }

  return length;
}

static void APP_ST67WiFiEventCallback(W6X_event_id_t event_id, void *event_args)
{
  app_st67_wifi_event_count++;

  APP_UART_WriteString("ST67 Wi-Fi event: sequence=");
  APP_UART_WriteUint32(app_st67_wifi_event_count);
  APP_UART_WriteString(" event_id=");
  APP_UART_WriteInt32((int32_t)event_id);
  APP_UART_WriteString(" event_name=");
  APP_UART_WriteString(APP_WiFiEventToString(event_id));
  APP_UART_WriteString(" event_args_present=");
  APP_UART_WriteUint32((event_args != NULL) ? 1U : 0U);

  if ((event_id == W6X_WIFI_EVT_REASON_ID) && (event_args != NULL))
  {
    const char *reason_text = W6X_WiFi_ReasonToStr(event_args);

    app_st67_wifi_reason_code = *(const uint32_t *)event_args;
    app_st67_wifi_reason_available = true;
    APP_UART_WriteString(" reason_code=");
    APP_UART_WriteUint32(app_st67_wifi_reason_code);
    APP_UART_WriteString(" reason_text=");
    APP_UART_WriteString((reason_text != NULL) ? reason_text : "unavailable");
  }

  APP_UART_WriteString("\r\n");
}

static void APP_ST67ErrorCallback(W6X_Status_t status, const char *function_name)
{
  app_st67_error_count++;

  APP_UART_WriteString("ST67 middleware error: sequence=");
  APP_UART_WriteUint32(app_st67_error_count);
  APP_UART_WriteString(" status=");
  APP_UART_WriteInt32((int32_t)status);
  APP_UART_WriteString(" status_name=");
  APP_UART_WriteString(APP_W6XStatusToString(status));
  APP_UART_WriteString(" function=");
  APP_UART_WriteString((function_name != NULL) ? function_name : "<null>");
  APP_UART_WriteString("\r\n");
}

static W6X_App_Cb_t app_st67_callbacks = {
  .APP_wifi_cb = APP_ST67WiFiEventCallback,
  .APP_net_cb = NULL,
  .APP_mqtt_cb = NULL,
  .APP_ble_cb = NULL,
  .APP_error_cb = APP_ST67ErrorCallback
};


static bool APP_WaitForWiFiAssociation(
    W6X_WiFi_StaStateType_e *station_state,
    W6X_WiFi_Connect_t *connection,
    W6X_Status_t *last_query_status)
{
  uint32_t elapsed_ms = 0U;
  uint32_t next_log_ms = 0U;
  W6X_WiFi_StaStateType_e previous_state =
      W6X_WIFI_STATE_STA_NO_STARTED_CONNECTION;
  bool have_previous_state = false;

  while (elapsed_ms <= APP_ST67_ASSOC_TIMEOUT_MS)
  {
    *last_query_status =
        W6X_WiFi_Station_GetState(station_state, connection);

    if ((*last_query_status == W6X_STATUS_OK) &&
        ((*station_state == W6X_WIFI_STATE_STA_CONNECTED) ||
         (*station_state == W6X_WIFI_STATE_STA_GOT_IP)))
    {
      APP_UART_WriteString("ST67 Wi-Fi association poll: elapsed_ms=");
      APP_UART_WriteUint32(elapsed_ms);
      APP_UART_WriteString(" query_status=");
      APP_UART_WriteInt32((int32_t)*last_query_status);
      APP_UART_WriteString(" query_status_name=");
      APP_UART_WriteString(APP_W6XStatusToString(*last_query_status));
      APP_UART_WriteString(" state=");
      APP_UART_WriteInt32((int32_t)*station_state);
      APP_UART_WriteString(" state_name=");
      APP_UART_WriteString(APP_WiFiStateToString(*station_state));
      APP_UART_WriteString(" terminal=connected\r\n");
      return true;
    }

    if ((!have_previous_state) ||
        (*station_state != previous_state) ||
        (elapsed_ms >= next_log_ms) ||
        (*last_query_status != W6X_STATUS_OK))
    {
      APP_UART_WriteString("ST67 Wi-Fi association poll: elapsed_ms=");
      APP_UART_WriteUint32(elapsed_ms);
      APP_UART_WriteString(" query_status=");
      APP_UART_WriteInt32((int32_t)*last_query_status);
      APP_UART_WriteString(" query_status_name=");
      APP_UART_WriteString(APP_W6XStatusToString(*last_query_status));
      APP_UART_WriteString(" state=");
      APP_UART_WriteInt32((int32_t)*station_state);
      APP_UART_WriteString(" state_name=");
      APP_UART_WriteString(APP_WiFiStateToString(*station_state));
      APP_UART_WriteString(" wifi_event_count=");
      APP_UART_WriteUint32(app_st67_wifi_event_count);
      APP_UART_WriteString(" middleware_error_count=");
      APP_UART_WriteUint32(app_st67_error_count);
      APP_UART_WriteString("\r\n");

      previous_state = *station_state;
      have_previous_state = true;
      next_log_ms = elapsed_ms + APP_ST67_ASSOC_LOG_INTERVAL_MS;
    }

    if (elapsed_ms == APP_ST67_ASSOC_TIMEOUT_MS)
    {
      break;
    }

    osDelay(APP_ST67_ASSOC_POLL_MS);
    if ((APP_ST67_ASSOC_TIMEOUT_MS - elapsed_ms) <
        APP_ST67_ASSOC_POLL_MS)
    {
      elapsed_ms = APP_ST67_ASSOC_TIMEOUT_MS;
    }
    else
    {
      elapsed_ms += APP_ST67_ASSOC_POLL_MS;
    }
  }

  return false;
}

static void APP_CopyIPv4Address(
    uint8_t destination[4],
    const ip4_addr_t *source)
{
  uint32_t address = lwip_ntohl(ip4_addr_get_u32(source));

  destination[0] = (uint8_t)((address >> 24) & 0xFFU);
  destination[1] = (uint8_t)((address >> 16) & 0xFFU);
  destination[2] = (uint8_t)((address >> 8) & 0xFFU);
  destination[3] = (uint8_t)(address & 0xFFU);
}

static bool APP_WaitForDhcpAddress(
    uint8_t ip[4],
    uint8_t gateway[4],
    uint8_t netmask[4])
{
  struct netif *station_netif;
  uint32_t elapsed_ms = 0U;
  uint32_t next_log_ms = 0U;

  station_netif = netif_get_interface(NETIF_STA);
  if (station_netif == NULL)
  {
    APP_UART_WriteString(
        "ST67 DHCP poll: result=netif_unavailable interface=station\r\n");
    return false;
  }

  while (elapsed_ms <= APP_ST67_DHCP_TIMEOUT_MS)
  {
    if (netif_is_up(station_netif) &&
        netif_is_link_up(station_netif) &&
        !ip4_addr_isany_val(*netif_ip4_addr(station_netif)))
    {
      APP_CopyIPv4Address(ip, netif_ip4_addr(station_netif));
      APP_CopyIPv4Address(gateway, netif_ip4_gw(station_netif));
      APP_CopyIPv4Address(netmask, netif_ip4_netmask(station_netif));
      APP_UART_WriteString("ST67 DHCP poll: elapsed_ms=");
      APP_UART_WriteUint32(elapsed_ms);
      APP_UART_WriteString(" netif_up=1 link_up=1 address_present=1\r\n");
      return true;
    }

    if (elapsed_ms >= next_log_ms)
    {
      APP_UART_WriteString("ST67 DHCP poll: elapsed_ms=");
      APP_UART_WriteUint32(elapsed_ms);
      APP_UART_WriteString(" netif_up=");
      APP_UART_WriteUint32(netif_is_up(station_netif) ? 1U : 0U);
      APP_UART_WriteString(" link_up=");
      APP_UART_WriteUint32(netif_is_link_up(station_netif) ? 1U : 0U);
      APP_UART_WriteString(" address_present=");
      APP_UART_WriteUint32(
          ip4_addr_isany_val(*netif_ip4_addr(station_netif)) ? 0U : 1U);
      APP_UART_WriteString("\r\n");
      next_log_ms = elapsed_ms + APP_ST67_DHCP_LOG_INTERVAL_MS;
    }

    osDelay(APP_ST67_DHCP_POLL_MS);
    elapsed_ms += APP_ST67_DHCP_POLL_MS;
  }

  return false;
}

static bool APP_RunST67WiFiDhcp(void)
{
  W6X_Status_t status;
  W6X_WiFi_Connect_Opts_t options = {0};
  W6X_WiFi_StaStateType_e station_state =
      W6X_WIFI_STATE_STA_NO_STARTED_CONNECTION;
  W6X_WiFi_Connect_t connection = {0};
  W6X_Status_t association_query_status = W6X_STATUS_ERROR;
  uint8_t ip[4] = {0};
  uint8_t gateway[4] = {0};
  uint8_t netmask[4] = {0};
  bool association_success;
  bool dhcp_success;

  APP_UART_WriteString("ST67 Wi-Fi configuration: ssid=");
  APP_UART_WriteString(PQC_WIFI_SSID);
  APP_UART_WriteString(" psk=redacted psk_length=");
  APP_UART_WriteUint32(
      APP_CStringLengthBounded(PQC_WIFI_PSK, W6X_WIFI_MAX_PASSWORD_SIZE + 1U));
  APP_UART_WriteString(" ipv4_mode=");
  APP_UART_WriteString(PQC_WIFI_IPV4_MODE);
  APP_UART_WriteString("\r\n");

  if (PQC_WIFI_SSID[0] == '\0')
  {
    APP_UART_WriteString(
        "ST67 Wi-Fi association: result=config_missing ssid=<empty>"
        " state=not_attempted security=unavailable channel=0\r\n");
    return false;
  }

  char status_buf[32];

  status = W6X_WiFi_Init();

  snprintf(
      status_buf,
      sizeof(status_buf),
      "wifi init status=%ld\r\n",
      (long)status
  );

  APP_UART_WriteString(status_buf);

  if ((status != W6X_STATUS_OK) || (MX_LWIP_Init() != 0))
  {
    APP_UART_WriteString(
        "ST67 Wi-Fi association: result=wifi_init_failed ssid=");
    APP_UART_WriteString(PQC_WIFI_SSID);
    APP_UART_WriteString(
        " state=unavailable security=unavailable channel=0\r\n");
    return false;
  }

  /* Best-effort RF visibility before association with the experiment AP. */
  (void)APP_RunST67WiFiScan();

  /*
   * Match the ST MQTT demonstration: zero-initialize the options structure
   * and populate only SSID and Password. In particular, leave Secured,
   * WPS, WEP, MAC filtering, and reconnection fields at their documented
   * defaults unless a later requirement explicitly needs them.
   */
  APP_CopyCString(options.SSID, sizeof(options.SSID), PQC_WIFI_SSID);
  APP_CopyCString(options.Password, sizeof(options.Password), PQC_WIFI_PSK);

  app_st67_wifi_reason_available = false;
  app_st67_wifi_reason_code = 0U;

  APP_UART_WriteString("ST67 Wi-Fi connect options: ssid_length=");
  APP_UART_WriteUint32(
      APP_CStringLengthBounded((const char *)options.SSID, sizeof(options.SSID)));
  APP_UART_WriteString(" password_length=");
  APP_UART_WriteUint32(
      APP_CStringLengthBounded((const char *)options.Password, sizeof(options.Password)));
  APP_UART_WriteString(" mac_filter_present=");
  APP_UART_WriteUint32(
      ((options.MAC[0] | options.MAC[1] | options.MAC[2] |
        options.MAC[3] | options.MAC[4] | options.MAC[5]) != 0U) ? 1U : 0U);
  APP_UART_WriteString(" reconnection_interval_s=");
  APP_UART_WriteUint32(options.Reconnection_interval);
  APP_UART_WriteString(" reconnection_attempts=");
  APP_UART_WriteUint32(options.Reconnection_nb_attempts);
  APP_UART_WriteString(" wps=");
  APP_UART_WriteUint32(options.WPS);
  APP_UART_WriteString(" wep=");
  APP_UART_WriteUint32(options.WEP);
  APP_UART_WriteString(" secured=");
  APP_UART_WriteUint32(options.Secured);
  APP_UART_WriteString(" option_profile=st_demo_defaults");
  APP_UART_WriteString("\r\n");

  APP_UART_WriteString("ST67 Wi-Fi association: begin ssid=");
  APP_UART_WriteString(PQC_WIFI_SSID);
  APP_UART_WriteString(" timeout_ms=");
  APP_UART_WriteUint32(APP_ST67_ASSOC_TIMEOUT_MS);
  APP_UART_WriteString(" poll_ms=");
  APP_UART_WriteUint32(APP_ST67_ASSOC_POLL_MS);
  APP_UART_WriteString("\r\n");

  status = W6X_WiFi_Connect(&options);
  APP_UART_WriteString("ST67 Wi-Fi association: connect_call_status=");
  APP_UART_WriteInt32((int32_t)status);
  APP_UART_WriteString(" status_name=");
  APP_UART_WriteString(APP_W6XStatusToString(status));
  APP_UART_WriteString(" synchronous_wait=complete");
  APP_UART_WriteString(" wifi_event_count=");
  APP_UART_WriteUint32(app_st67_wifi_event_count);
  APP_UART_WriteString(" middleware_error_count=");
  APP_UART_WriteUint32(app_st67_error_count);
  if (app_st67_wifi_reason_available)
  {
    APP_UART_WriteString(" reason_code=");
    APP_UART_WriteUint32(app_st67_wifi_reason_code);
  }
  APP_UART_WriteString("\r\n");

  if (status != W6X_STATUS_OK)
  {
    APP_UART_WriteString("ST67 Wi-Fi association: result=connect_failed ssid=");
    APP_UART_WriteString(PQC_WIFI_SSID);
    APP_UART_WriteString(" status=");
    APP_UART_WriteInt32((int32_t)status);
    APP_UART_WriteString(" status_name=");
    APP_UART_WriteString(APP_W6XStatusToString(status));
    if (app_st67_wifi_reason_available)
    {
      APP_UART_WriteString(" reason_code=");
      APP_UART_WriteUint32(app_st67_wifi_reason_code);
    }
    APP_UART_WriteString(
        " state=unavailable security=unavailable channel=0\r\n");
    return false;
  }

  association_success = APP_WaitForWiFiAssociation(
      &station_state,
      &connection,
      &association_query_status);

  if (!association_success)
  {
    APP_UART_WriteString("ST67 Wi-Fi association: result=timeout ssid=");
    APP_UART_WriteString(PQC_WIFI_SSID);
    APP_UART_WriteString(" timeout_ms=");
    APP_UART_WriteUint32(APP_ST67_ASSOC_TIMEOUT_MS);
    APP_UART_WriteString(" query_status=");
    APP_UART_WriteInt32((int32_t)association_query_status);
    APP_UART_WriteString(" query_status_name=");
    APP_UART_WriteString(APP_W6XStatusToString(association_query_status));
    APP_UART_WriteString(" state=");
    APP_UART_WriteInt32((int32_t)station_state);
    APP_UART_WriteString(" state_name=");
    APP_UART_WriteString(APP_WiFiStateToString(station_state));
    APP_UART_WriteString(" wifi_event_count=");
    APP_UART_WriteUint32(app_st67_wifi_event_count);
    APP_UART_WriteString(" middleware_error_count=");
    APP_UART_WriteUint32(app_st67_error_count);
    APP_UART_WriteString(" security=unavailable channel=0\r\n");
    return false;
  }

  app_st67_wifi_connected = true;

  APP_UART_WriteString("ST67 Wi-Fi association: result=passed ssid=");
  APP_UART_WriteString((const char *)connection.SSID);
  APP_UART_WriteString(" state=connected security=");
  APP_UART_WriteUint32((uint32_t)connection.Security);
  APP_UART_WriteString(" channel=");
  APP_UART_WriteUint32((uint32_t)connection.Channel);
  APP_UART_WriteString("\r\n");

  dhcp_success = APP_WaitForDhcpAddress(ip, gateway, netmask);
  APP_UART_WriteString("ST67 DHCP: result=");
  APP_UART_WriteString(dhcp_success ? "passed ipv4=" : "failed ipv4=");
  APP_UART_WriteIPv4(ip);
  APP_UART_WriteString(" gateway=");
  APP_UART_WriteIPv4(gateway);
  APP_UART_WriteString(" netmask=");
  APP_UART_WriteIPv4(netmask);
  APP_UART_WriteString("\r\n");
  return dhcp_success;
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

static bool app_st67_network_ready = false;

static void APP_EnableST67EXTIInterrupt(void)
{
  /*
   * SPI_RDY (line 13) and USER_BUTTON (line 15) share EXTI15_10_IRQn.
   * Keep the shared IRQ disabled until the FreeRTOS scheduler is running so
   * an early SPI_RDY edge cannot call a FromISR API before the Cortex-M port
   * has initialized its interrupt-priority validation state.
   */
  __HAL_GPIO_EXTI_CLEAR_IT(SPI_RDY_Pin);
  __HAL_GPIO_EXTI_CLEAR_IT(USER_BUTTON_Pin);
  HAL_NVIC_ClearPendingIRQ(EXTI15_10_IRQn);
  HAL_NVIC_EnableIRQ(EXTI15_10_IRQn);
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
    app_st67_network_ready = false;
    return;
  }

  status = W6X_RegisterAppCb(&app_st67_callbacks);
  APP_UART_WriteString("ST67 SPI bring-up: W6X_RegisterAppCb result=");
  APP_UART_WriteUint32((uint32_t)status);
  APP_UART_WriteString(" status_ok=");
  APP_UART_WriteUint32((status == W6X_STATUS_OK) ? 1U : 0U);
  APP_UART_WriteString("\r\n");

  if (status != W6X_STATUS_OK)
  {
    APP_UART_WriteString(
        "ST67 SPI bring-up: complete result=callback_registration_failed "
        "transport=unavailable wifi_association=not-attempted ip=unavailable "
        "tls_handshake=unavailable mqtt_connect=unavailable "
        "end_to_end=unavailable\r\n");
    app_st67_network_ready = false;
    return;
  }

  APP_EnableST67EXTIInterrupt();
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
    app_st67_network_ready = APP_RunST67WiFiDhcp();
    return;
  }
  else
  {
    APP_UART_WriteString(
        "ST67 SPI bring-up: complete result=failed "
        "transport=spi-module-init-failed wifi_association=not-attempted "
        "ip=unavailable tls_handshake=unavailable mqtt_connect=unavailable "
        "end_to_end=unavailable\r\n");
  }
  app_st67_network_ready = false;
}

static void APP_PrintLwIPRuntimeSmoke(const char *context, bool scheduler_running)
{
  static char smoke_line[512];
  struct netif *station_netif = netif_get_interface(NETIF_STA);

  if ((station_netif != NULL) &&
      app_st67_wifi_connected &&
      (netif_is_up(station_netif) != 0) &&
      (netif_is_link_up(station_netif) != 0) &&
      (ip4_addr_isany_val(*netif_ip4_addr(station_netif)) == 0))
  {
    char ipv4_text[IP4ADDR_STRLEN_MAX];
    const char *ipv4_result = ip4addr_ntoa_r(
        netif_ip4_addr(station_netif),
        ipv4_text,
        (int)sizeof(ipv4_text));

    APP_UART_WriteString("lwIP runtime network: context=");
    APP_UART_WriteString((context != NULL) ? context : "unavailable");
    APP_UART_WriteString(" scheduler=");
    APP_UART_WriteString(scheduler_running ? "running" : "not_started");
    APP_UART_WriteString(
        " evidence=stm32-st67-t02-live-state network=available wifi=connected link=up ip=");
    APP_UART_WriteString((ipv4_result != NULL) ? ipv4_result : "unavailable");
    APP_UART_WriteString(
        " tcp=available transport=st67-lwip tls_handshake=unavailable "
        "mqtt_connect=unavailable mqtt_publish=unavailable reconnect=unavailable "
        "st67w61m1=available end_to_end=unavailable\r\n");
    return;
  }

  PQC_LwIP_BuildOnly_Init();

  if (PQC_LwIP_BuildOnly_RuntimeSmokeLineForContext(
          smoke_line, (uint32_t)sizeof(smoke_line), context, scheduler_running))
  {
    APP_UART_WriteString(smoke_line);
  }
  else
  {
    APP_UART_WriteString(
        "lwIP runtime smoke: context=unavailable scheduler=unavailable "
        "evidence=pre-network-build-only reason=format_failed "
        "network=unavailable wifi=unavailable link=unavailable ip=unavailable "
        "tcp=unavailable tls_handshake=unavailable certs=not-loaded "
        "mqtt_connect=unavailable mqtt_publish=unavailable reconnect=unavailable "
        "st67w61m1=unavailable end_to_end=unavailable\r\n");
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


void PQC_WolfMQTT_DiagnosticMarker(const char *marker)
{
  APP_UART_WriteString(marker);
}

static void APP_PrintWolfMQTTRuntimeStatus(void)
{
  static char status_line[768];

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


static void APP_PrintFreeRTOSSchedulerStarting(void)
{
  APP_UART_WriteString("FreeRTOS scheduler starting: cmsis_rtos=v2 default_task=defaultTask tick_hz=");
  APP_UART_WriteUint32((uint32_t)configTICK_RATE_HZ);
  APP_UART_WriteString(" heap_bytes=");
  APP_UART_WriteUint32((uint32_t)configTOTAL_HEAP_SIZE);
  APP_UART_WriteString(" default_task_stack_words=1024\r\n");
}

static void APP_PrintUnavailable(void)
{
  APP_UART_WriteString("unavailable");
}

static void APP_PrintTaskStackCheckpoint(const char *stage,
                                             const char *task_name,
                                             TaskHandle_t task_handle,
                                             uint32_t task_stack_total_bytes)
{
  UBaseType_t minimum_free_words;
  uint32_t minimum_free_bytes;

  APP_UART_WriteString("application task stack: stage=");
  APP_UART_WriteString(stage);
  APP_UART_WriteString(" task=");
  APP_UART_WriteString(task_name);
  APP_UART_WriteString(" total_bytes=");
  APP_UART_WriteUint32(task_stack_total_bytes);
  APP_UART_WriteString(" minimum_free_bytes=");

  minimum_free_words = uxTaskGetStackHighWaterMark(task_handle);
  minimum_free_bytes =
      (uint32_t)minimum_free_words * (uint32_t)sizeof(StackType_t);

  if (minimum_free_bytes <= task_stack_total_bytes)
  {
    APP_UART_WriteUint32(minimum_free_bytes);
    APP_UART_WriteString(" peak_used_bytes=");
    APP_UART_WriteUint32(task_stack_total_bytes - minimum_free_bytes);
  }
  else
  {
    APP_PrintUnavailable();
    APP_UART_WriteString(" peak_used_bytes=");
    APP_PrintUnavailable();
  }

  APP_UART_WriteString("\r\n");
}

static void APP_PrintApplicationMemoryCheckpoint(const char *stage,
                                                 BaseType_t include_default_task,
                                                 BaseType_t include_network_task)
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
  APP_UART_WriteString("\r\n");

  if (include_default_task == pdTRUE)
  {
    APP_PrintTaskStackCheckpoint(
        stage,
        "defaultTask",
        (TaskHandle_t)defaultTaskHandle,
        (uint32_t)defaultTask_attributes.stack_size);
  }

  if (include_network_task == pdTRUE)
  {
    APP_PrintTaskStackCheckpoint(
        stage,
        "networkTask",
        (TaskHandle_t)networkTaskHandle,
        (uint32_t)networkTask_attributes.stack_size);
  }
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
  //APP_PrintApplicationClock("hclk_hz", HAL_RCC_GetHCLKFreq());
  //APP_PrintApplicationClock("pclk1_hz", HAL_RCC_GetPCLK1Freq());
  //APP_PrintApplicationClock("pclk2_hz", HAL_RCC_GetPCLK2Freq());
}

#ifdef SECURE_BOOT_APPLICATION
#define PQC_BOOT_TIMING_MAILBOX_ADDR      0x10000000UL
#define PQC_BOOT_TIMING_MAILBOX_MAGIC     0x50514354UL
#define PQC_BOOT_TIMING_MAILBOX_VERSION   8UL

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
  uint32_t reset_origin_to_handoff_us_low;
  uint32_t reset_origin_to_handoff_us_high;
  uint32_t reset_origin_kind;
  uint32_t handoff_bridge_counter_hz;
  uint32_t handoff_bridge_counter_bits;
  uint32_t handoff_bridge_status;
  uint32_t integrity_cycles;
  int32_t integrity_result;
  uint32_t integrity_valid;
  uint32_t authenticity_cycles;
  int32_t authenticity_result;
  uint32_t authenticity_valid;
  uint32_t signature_algorithm_id;
  uint32_t signature_parameter_bits;
  uint32_t declared_signature_capacity_bytes;
  uint32_t verified_image_digest_valid;
  uint32_t verified_image_part;
  uint32_t verified_image_fw_size;
  uint8_t verified_image_sha256[32];
  uint32_t image_verification_cycles;
  uint32_t image_verification_valid;
  uint32_t selected_image_valid;
  uint32_t selected_image_part;
  uint32_t selected_image_fw_size;
  uint32_t stack_profiling_enabled;
  uint32_t stack_measurement_status;
  uint32_t stack_watermark_capacity_bytes;
} PQC_BootTimingMailbox;
/* The hardware dual-bank event mailbox begins at 0x10000100. */
typedef char PQC_BootTimingMailboxFitsOtaEvents[
    (sizeof(PQC_BootTimingMailbox) <= 0x100U) ? 1 : -1];

static void APP_ConfigureResetOriginHandoff(void)
{
  volatile const PQC_BootTimingMailbox *mailbox =
      (volatile const PQC_BootTimingMailbox *)PQC_BOOT_TIMING_MAILBOX_ADDR;
  PQC_TimebaseBootHandoff handoff = {0};

  if ((mailbox->magic != PQC_BOOT_TIMING_MAILBOX_MAGIC) ||
      (mailbox->version != PQC_BOOT_TIMING_MAILBOX_VERSION) ||
      (mailbox->handoff_bridge_status != 1U))
  {
    PQC_TimebaseConfigureBootHandoff(NULL);
    return;
  }

  handoff.reset_origin_to_handoff_us =
      ((uint64_t)mailbox->reset_origin_to_handoff_us_high << 32) |
      (uint64_t)mailbox->reset_origin_to_handoff_us_low;
  handoff.bridge_counter_hz = mailbox->handoff_bridge_counter_hz;
  handoff.bridge_counter_bits = mailbox->handoff_bridge_counter_bits;
  handoff.reset_origin_kind = mailbox->reset_origin_kind;
  handoff.valid = 1U;
  PQC_TimebaseConfigureBootHandoff(&handoff);
}

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
    APP_UART_WriteString("wolfBoot timing mailbox version: 8\r\n");
    APP_UART_WriteString("wolfBoot integrity valid: ");
    APP_UART_WriteUint32(mailbox->integrity_valid);
    APP_UART_WriteString("\r\n");
    if (mailbox->integrity_valid != 0U && mailbox->integrity_cycles != 0U)
    {
      APP_UART_WriteString("wolfBoot integrity cycles: ");
      APP_UART_WriteUint32(mailbox->integrity_cycles);
      APP_UART_WriteString(" cycles\r\n");
      APP_UART_WriteString("wolfBoot integrity result: ");
      APP_UART_WriteInt32(mailbox->integrity_result);
      APP_UART_WriteString("\r\n");
    }
    APP_UART_WriteString("wolfBoot authenticity valid: ");
    APP_UART_WriteUint32(mailbox->authenticity_valid);
    APP_UART_WriteString("\r\n");
    if (mailbox->authenticity_valid != 0U && mailbox->authenticity_cycles != 0U)
    {
      APP_UART_WriteString("wolfBoot authenticity cycles: ");
      APP_UART_WriteUint32(mailbox->authenticity_cycles);
      APP_UART_WriteString(" cycles\r\n");
      APP_UART_WriteString("wolfBoot authenticity result: ");
      APP_UART_WriteInt32(mailbox->authenticity_result);
      APP_UART_WriteString("\r\n");
    }
    /* The legacy generic marker is not a valid typed measurement in v4. */
    APP_PrintWolfBootClock("sysclk_hz", mailbox->sysclk_hz);
    APP_PrintWolfBootClock("hclk_hz", mailbox->hclk_hz);

    if (mailbox->stack_profiling_enabled == 1U)
    {
      APP_UART_WriteString("wolfBoot stack profiling: enabled\r\n");
      APP_UART_WriteString("wolfBoot verification stack status: ");
      APP_UART_WriteString(mailbox->stack_measurement_status == 1U &&
          mailbox->selected_image_valid == 1U ? "measured" : "unavailable");
      APP_UART_WriteString("\r\n");
    }
    if (mailbox->stack_profiling_enabled == 1U &&
        mailbox->stack_measurement_status == 1U &&
        mailbox->selected_image_valid == 1U &&
        mailbox->max_stack_used_bytes != 0xFFFFFFFFUL)
    {
      APP_UART_WriteString("wolfBoot verification max stack used: ");
      APP_UART_WriteUint32(mailbox->max_stack_used_bytes);
      APP_UART_WriteString(" bytes\r\n");
    }
  }
}
#endif

#ifdef SECURE_BOOT_APPLICATION
/* Identifier is written by the instrumented bootloader, not inferred from TLS.
 * Values intentionally match the version-5 build-profile identity catalogue. */
static const char *PQC_BootSignatureAlgorithmName(uint32_t id)
{
  switch (id)
  {
    case 1U: return "integrity_sha256";
    case 2U: return "ecdsa_p256";
    case 3U: return "ed25519";
    case 4U: return "rsa2048";
    case 5U: return "ecc384";
    case 6U: return "ecc521";
    case 7U: return "ed448";
    case 8U: return "rsa3072";
    case 9U: return "rsa4096";
    case 10U: return "mldsa44";
    case 11U: return "mldsa65";
    case 12U: return "mldsa87";
    default: return "unknown";
  }
}

#endif /* SECURE_BOOT_APPLICATION */

/* Preserve the bootloader-owned RAM2 record until deferred publication.
 * This is intentionally outside the bootloader and application timing windows;
 * no UART, broker connection, or heap allocation is used in verification. */
void PQC_BootEvidenceAppendToResultBuffer(uint32_t iteration)
{
#ifdef SECURE_BOOT_APPLICATION
  const volatile PQC_BootTimingMailbox *mailbox =
      (const volatile PQC_BootTimingMailbox *)(uintptr_t)PQC_BOOT_TIMING_MAILBOX_ADDR;
  char line[448];
  uint32_t magic = mailbox->magic;
  uint32_t version = mailbox->version;
  if ((magic != PQC_BOOT_TIMING_MAILBOX_MAGIC) ||
      (version != PQC_BOOT_TIMING_MAILBOX_VERSION))
  {
    (void)PQC_ResultBufferAppendText(iteration, "secure_boot",
        "PQC_SECURE_BOOT schema=1 mailbox_status=unavailable reason=invalid_magic_or_version");
    return;
  }
  /* Algorithm metadata is serialized only after workload measurement. A zero
   * parameter or capacity means unavailable, never a measured zero-byte key. */
  (void)snprintf(line, sizeof(line),
      "PQC_SECURE_BOOT_PROFILE schema=1 mailbox_version=%lu "
      "signature_algorithm=%s integrity_algorithm=sha256 "
      "signature_parameter_bits=%lu declared_signature_capacity_bytes=%lu "
      "signature_parameter_available=%lu declared_signature_capacity_available=%lu "
      "public_key_size_bytes=unavailable",
      (unsigned long)version,
      PQC_BootSignatureAlgorithmName(mailbox->signature_algorithm_id),
      (unsigned long)mailbox->signature_parameter_bits,
      (unsigned long)mailbox->declared_signature_capacity_bytes,
      (unsigned long)(mailbox->signature_parameter_bits != 0U),
      (unsigned long)(mailbox->declared_signature_capacity_bytes != 0U));
  (void)PQC_ResultBufferAppendText(iteration, "secure_boot", line);
  /* Stack evidence is independent of FreeRTOS task/MSP statistics. The
   * disabled mode emits no stack record; failed observations remain explicit. */
  if (mailbox->stack_profiling_enabled == 1U)
  {
    uint32_t valid = (mailbox->stack_measurement_status == 1U) &&
        (mailbox->selected_image_valid == 1U) &&
        (mailbox->max_stack_used_bytes != 0xFFFFFFFFUL) &&
        (mailbox->max_stack_used_bytes != 0U) &&
        (mailbox->stack_watermark_capacity_bytes != 0U);
    char high_water_text[16];
    if (valid)
      (void)snprintf(high_water_text, sizeof(high_water_text), "%lu",
          (unsigned long)mailbox->max_stack_used_bytes);
    else
      (void)snprintf(high_water_text, sizeof(high_water_text), "unavailable");
    (void)snprintf(line, sizeof(line),
        "PQC_SECURE_BOOT_STACK schema=1 boundary=selected_image_integrity_begin_to_verification_end "
        "profiling_enabled=1 measurement_status=%s high_water_bytes=%s "
        "watermark_capacity_bytes=%lu selected_image_valid=%lu "
        "timing_comparable=0 unavailable_reason=%s",
        valid ? "measured" : "unavailable",
        high_water_text,
        (unsigned long)mailbox->stack_watermark_capacity_bytes,
        (unsigned long)mailbox->selected_image_valid,
        valid ? "none" :
        mailbox->stack_measurement_status == 3U ? "watermark_untouched" :
        mailbox->stack_measurement_status == 4U ? "region_exhausted" :
        mailbox->stack_measurement_status == 5U ? "scan_interference" :
        mailbox->stack_measurement_status == 2U ? "initialization_unavailable" :
        "invalid_selected_image_or_status");
    (void)PQC_ResultBufferAppendText(iteration, "secure_boot", line);
  }
  /* Only the already-validated image-content SHA-256 is copied. This is
   * deliberately NOT the SHA-256 of the entire signed/packaged .bin file. */
  if ((mailbox->verified_image_digest_valid == 1U) &&
      (mailbox->integrity_valid != 0U) && (mailbox->integrity_result == 0) &&
      (mailbox->selected_image_valid == 1U) &&
      (mailbox->verified_image_part == mailbox->selected_image_part) &&
      (mailbox->verified_image_fw_size == mailbox->selected_image_fw_size))
  {
    static const char hex_digits[] = "0123456789abcdef";
    char digest_hex[65];
    uint32_t digest_i;
    for (digest_i = 0U; digest_i < 32U; ++digest_i)
    {
      uint8_t byte = mailbox->verified_image_sha256[digest_i];
      digest_hex[2U * digest_i] = hex_digits[byte >> 4];
      digest_hex[2U * digest_i + 1U] = hex_digits[byte & 0xFU];
    }
    digest_hex[64] = '\0';
    (void)snprintf(line, sizeof(line),
        "PQC_SECURE_BOOT_IMAGE schema=1 mailbox_version=%lu "
        "identity_kind=wolfboot_verified_image_content_sha256 "
        "image_sha256=%s image_part=%lu image_fw_size_bytes=%lu "
        "packaged_image_sha256=unavailable",
        (unsigned long)version, digest_hex,
        (unsigned long)mailbox->verified_image_part,
        (unsigned long)mailbox->verified_image_fw_size);
  }
  else
  {
    (void)snprintf(line, sizeof(line),
        "PQC_SECURE_BOOT_IMAGE schema=1 mailbox_version=%lu "
        "identity_kind=wolfboot_verified_image_content_sha256 "
        "image_sha256=unavailable reason=selected_image_not_verified "
        "packaged_image_sha256=unavailable", (unsigned long)version);
  }
  (void)PQC_ResultBufferAppendText(iteration, "secure_boot", line);
  (void)snprintf(line, sizeof(line),
      "PQC_SECURE_BOOT_VERIFICATION schema=1 mailbox_version=%lu "
      "boundary=selected_image_integrity_start_to_authenticity_end "
      "measurement_valid=%lu cycles=%lu hclk_hz=%lu "
      "selected_image_valid=%lu selected_image_part=%lu "
      "selected_image_fw_size_bytes=%lu",
      (unsigned long)version,
      (unsigned long)((mailbox->image_verification_valid == 1U) &&
          (mailbox->selected_image_valid == 1U) && mailbox->hclk_hz != 0U),
      (unsigned long)mailbox->image_verification_cycles,
      (unsigned long)mailbox->hclk_hz,
      (unsigned long)mailbox->selected_image_valid,
      (unsigned long)mailbox->selected_image_part,
      (unsigned long)mailbox->selected_image_fw_size);
  (void)PQC_ResultBufferAppendText(iteration, "secure_boot", line);
  /* Mailbox magic/version are structural checks, not proof against stale
   * or corrupted retained SRAM contents. */
  (void)snprintf(line, sizeof(line),
      "PQC_SECURE_BOOT schema=1 mailbox_version=%lu mailbox_status=present "
      "verification_type=integrity_sha256 measurement_valid=%lu cycles=%lu "
      "result=%ld sysclk_hz=%lu hclk_hz=%lu signature_algorithm=%s",
      (unsigned long)version,
      (unsigned long)((mailbox->integrity_valid != 0U) &&
                      (mailbox->integrity_cycles != 0U) && (mailbox->hclk_hz != 0U) &&
                      (mailbox->selected_image_valid == 1U)),
      (unsigned long)mailbox->integrity_cycles,
      (long)mailbox->integrity_result,
      (unsigned long)mailbox->sysclk_hz, (unsigned long)mailbox->hclk_hz,
      PQC_BootSignatureAlgorithmName(mailbox->signature_algorithm_id));
  (void)PQC_ResultBufferAppendText(iteration, "secure_boot", line);

  (void)snprintf(line, sizeof(line),
      "PQC_SECURE_BOOT schema=1 mailbox_version=%lu mailbox_status=present "
      "verification_type=signature_authenticity measurement_valid=%lu cycles=%lu "
      "result=%ld sysclk_hz=%lu hclk_hz=%lu signature_algorithm=%s "
      "measurement_status=%s",
      (unsigned long)version,
      (unsigned long)((mailbox->authenticity_valid != 0U) &&
                      (mailbox->authenticity_cycles != 0U) && (mailbox->hclk_hz != 0U) &&
                      (mailbox->selected_image_valid == 1U)),
      (unsigned long)mailbox->authenticity_cycles,
      (long)mailbox->authenticity_result,
      (unsigned long)mailbox->sysclk_hz, (unsigned long)mailbox->hclk_hz,
      PQC_BootSignatureAlgorithmName(mailbox->signature_algorithm_id),
      mailbox->signature_algorithm_id == 1U ? "not_applicable" :
      ((mailbox->authenticity_valid != 0U) &&
       (mailbox->authenticity_cycles != 0U) && (mailbox->hclk_hz != 0U) &&
       (mailbox->selected_image_valid == 1U))
      ? "measured" : "unavailable");
  (void)PQC_ResultBufferAppendText(iteration, "secure_boot", line);

  (void)snprintf(line, sizeof(line),
      "PQC_SECURE_BOOT_HANDOFF schema=1 mailbox_version=%lu "
      "origin_kind=%lu reset_origin_to_handoff_us_high=%lu "
      "reset_origin_to_handoff_us_low=%lu bridge_counter_hz=%lu "
      "bridge_counter_bits=%lu bridge_status=%lu",
      (unsigned long)version,
      (unsigned long)mailbox->reset_origin_kind,
      (unsigned long)mailbox->reset_origin_to_handoff_us_high,
      (unsigned long)mailbox->reset_origin_to_handoff_us_low,
      (unsigned long)mailbox->handoff_bridge_counter_hz,
      (unsigned long)mailbox->handoff_bridge_counter_bits,
      (unsigned long)mailbox->handoff_bridge_status);
  (void)PQC_ResultBufferAppendText(iteration, "secure_boot", line);
  (void)snprintf(line, sizeof(line),
      "PQC_SECURE_BOOT_TOTAL schema=1 mailbox_version=%lu "
      "boundary=hal_init_entry_to_hal_prepare_boot "
      "measurement_valid=%lu elapsed_us_high=%lu elapsed_us_low=%lu "
      "clock_domain=reset_origin_lptim2_dwt_bridge "
      "reset_to_application_startup=not_measured",
      (unsigned long)version,
      (unsigned long)(mailbox->handoff_bridge_status == 1U),
      (unsigned long)mailbox->reset_origin_to_handoff_us_high,
      (unsigned long)mailbox->reset_origin_to_handoff_us_low);
  (void)PQC_ResultBufferAppendText(iteration, "secure_boot", line);
#else
  (void)iteration;
#endif
}

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */
  /* Paint unused MSP reservation before HAL/application initialization. */
  PQC_RAM_InitializeMSPHighWatermark();

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();
#ifdef SECURE_BOOT_APPLICATION
  /* Capture the wolfBoot handoff record before the application clock tree is
   * changed. The independent 1 MHz LPTIM2 bridge continues to run across the
   * bootloader/application handoff and the application clock transition. */
  APP_ConfigureResetOriginHandoff();
#else
  PQC_TimebaseConfigureBootHandoff(NULL);
#endif

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();
  if (PQC_TimebaseInitialize() != 0)
  {
    Error_Handler();
  }
#if defined(PQC_TIMEBASE_HARDWARE_SELF_TEST) && PQC_TIMEBASE_HARDWARE_SELF_TEST
  APP_RunTimebaseHardwareSelfTest();
#endif

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_DMA_Init();
#if PQC_UART_OUTPUT_MODE != 0 || PQC_ENERGY_SYNC_ENABLED
  MX_LPUART1_UART_Init();
#endif
#if defined(PQC_TIMEBASE_HARDWARE_SELF_TEST) && PQC_TIMEBASE_HARDWARE_SELF_TEST && (PQC_UART_OUTPUT_MODE != 0)
  APP_PrintTimebaseHardwareSelfTest();
#endif
  MX_SPI1_Init();
  /* USER CODE BEGIN 2 */

#ifdef SECURE_BOOT_APPLICATION
  APP_PrintWolfBootVerificationTiming();

  const char secure_boot_msg[] = "stm32-basic_hal1 secure-boot app v0.1.0\r\n";
  APP_UART_WriteString(secure_boot_msg);

  const char boot_msg[] = "stm32-basic_hal1 boot v0.1.0\r\n";
#else
  const char boot_msg[] = "\r\nstm32-basic_hal1 boot v0.1.0\r\n";
#endif
  APP_UART_WriteString(boot_msg);
  APP_PrintLwIPRuntimeSmoke("pre_scheduler", false);
  APP_PrintNetworkInterfaceStatus();
#if PQC_TLS_COMPILED
  PQC_WolfSSL_MemorySetDiagnosticWriter(APP_UART_WriteString);
  if (PQC_WolfSSL_MemoryConfigure() != 0)
  {
    APP_UART_WriteString("PQC_WOLFSSL_MEMORY allocator configuration failed\r\n");
    Error_Handler();
  }
#endif
#if PQC_BAREMETAL_BENCHMARK_ENABLED
  /* All cryptographic measurement completes before the RTOS and ST67 run. */
  PQC_EnergyBoundaryInitialize();
  if (!PQC_EnergyAwaitStart()) { Error_Handler(); }
  PQC_EnergyBoundaryBegin();
  PQC_BenchmarkSTM32_Run();
  PQC_EnergyBoundaryEnd();
  PQC_ResultBufferReset();
  PQC_EnergyBoundaryAppend(0U);
  PQC_BenchmarkSTM32_AppendResults();
#endif

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
  APP_UART_WriteString("FreeRTOS defaultTask created: name=defaultTask priority=osPriorityNormal stack_words=1024\r\n");

  networkTaskHandle = osThreadNew(StartNetworkTask, NULL, &networkTask_attributes);
  if (networkTaskHandle == NULL)
  {
    APP_UART_WriteString("FreeRTOS networkTask create failed\r\n");
    Error_Handler();
  }
  APP_UART_WriteString("FreeRTOS networkTask created: name=networkTask priority=osPriorityNormal stack_words=2048\r\n");
  APP_PrintApplicationMemoryCheckpoint("pre_scheduler", pdFALSE, pdFALSE);
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
#if PQC_UART_OUTPUT_MODE != 0 || PQC_ENERGY_SYNC_ENABLED
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
#endif

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

  /* EXTI interrupt init. Enable from the running network task. */
  HAL_NVIC_SetPriority(EXTI15_10_IRQn, 5, 0);
  HAL_NVIC_DisableIRQ(EXTI15_10_IRQn);

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */

void HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin)
{
  if (GPIO_Pin == SPI_RDY_Pin)
  {
    GPIO_PinState ready_level = HAL_GPIO_ReadPin(SPI_RDY_GPIO_Port, SPI_RDY_Pin);
    uint32_t tick;

    /*
     * The shared EXTI line can become pending while GPIO is initialized.
     * Do not call FreeRTOS FromISR APIs until the scheduler has started.
     */
    if (xTaskGetSchedulerState() == taskSCHEDULER_NOT_STARTED)
    {
      return;
    }

    tick = (uint32_t)xTaskGetTickCountFromISR();
    app_st67_ready_diagnostic.irq_count++;
    app_st67_ready_diagnostic.last_level = (ready_level == GPIO_PIN_SET) ? 1U : 0U;

    if (ready_level == GPIO_PIN_SET)
    {
      app_st67_ready_diagnostic.rising_count++;
      app_st67_ready_diagnostic.last_rising_tick = tick;
      (void)spi_on_txn_data_ready();
    }
    else
    {
      app_st67_ready_diagnostic.falling_count++;
      app_st67_ready_diagnostic.last_falling_tick = tick;
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
  BaseType_t runtime_checkpoint_reported = pdFALSE;

  APP_UART_WriteString("FreeRTOS defaultTask started\r\n");

  for(;;)
  {
    HAL_GPIO_TogglePin(GPIOB, GPIO_PIN_7);
    osDelay(1000);

    if (runtime_checkpoint_reported == pdFALSE)
    {
      APP_PrintApplicationMemoryCheckpoint("default_task_runtime", pdTRUE, pdFALSE);
      runtime_checkpoint_reported = pdTRUE;
    }
  }
  /* USER CODE END 5 */
}

/* USER CODE BEGIN Header_StartNetworkTask */
/**
  * @brief  Runs network and protocol initialization independently of heartbeat.
  * @param  argument: Not used
  * @retval None
  */
/* USER CODE END Header_StartNetworkTask */
static bool APP_IsNetworkReady(void)
{
  return app_st67_network_ready;
}

static void APP_PrintLwIPRuntimeFixture(void)
{
  APP_PrintLwIPRuntimeSmoke("freertos_task", true);
}

/*
 * Keep the application fixture ABI intact after removing the obsolete
 * wolfSSL runtime smoke test. Some application implementations still invoke
 * this callback unconditionally. A no-op avoids a NULL indirect call without
 * reintroducing smoke-test UART output or timing overhead.
 */
static void APP_WolfSSLRuntimeFixtureNoOp(void)
{
}


static void APP_PrintNetworkTaskMemoryCheckpoint(void)
{
  APP_PrintApplicationMemoryCheckpoint("network_task_complete", pdTRUE, pdTRUE);
}

static int APP_RunReadyMetricsWorkload(void (*mark_complete)(void))
{
  return PQC_WolfMQTT_RunReadyMetricsApplication(mark_complete);
}

static int APP_RunReadyMetrics2Workload(void (*mark_complete)(void))
{
  return PQC_WolfMQTT_RunReadyMetrics2Application(mark_complete);
}

static int APP_RunTLSHandshakeRepeatWorkload(uint32_t handshakes_per_run)
{
  PQC_WolfMQTTTLSRepeatSummary summary;
  return PQC_WolfMQTT_RunTLSHandshakeRepeatApplication(handshakes_per_run, &summary);
}

static void APP_PrintMemoryHighWatermark(void)
{
  extern uint8_t __ram_region_start__;
  extern uint8_t __ram_region_end__;
  extern uint8_t __ram2_region_start__;
  extern uint8_t __ram2_region_end__;
  extern uint8_t __ram3_region_start__;
  extern uint8_t __ram3_region_end__;
  extern uint8_t _sdata;
  extern uint8_t _edata;
  extern uint8_t _sbss;
  extern uint8_t _ebss;
  extern uint8_t _end;
  extern uint8_t __user_heap_stack_end__;
  extern uint32_t _Min_Heap_Size;
  const size_t ram_total_bytes = (size_t)(
      (uintptr_t)&__ram_region_end__ - (uintptr_t)&__ram_region_start__);
  const size_t ram2_total_bytes = (size_t)(
      (uintptr_t)&__ram2_region_end__ - (uintptr_t)&__ram2_region_start__);
  const size_t ram3_total_bytes = (size_t)(
      (uintptr_t)&__ram3_region_end__ - (uintptr_t)&__ram3_region_start__);
  const size_t data_bytes =
      (size_t)((uintptr_t)&_edata - (uintptr_t)&_sdata);
  const size_t bss_bytes =
      (size_t)((uintptr_t)&_ebss - (uintptr_t)&_sbss);
  const size_t ram_static_base_bytes = (size_t)(
      (uintptr_t)&_end - (uintptr_t)&__ram_region_start__);
  const size_t linker_min_heap_bytes = (size_t)(uintptr_t)&_Min_Heap_Size;
  const size_t ram_linker_reserved_bytes = (size_t)(
      (uintptr_t)&__user_heap_stack_end__ -
      (uintptr_t)&__ram_region_start__);
  const size_t ram_linker_unreserved_bytes =
      (ram_linker_reserved_bytes <= ram_total_bytes)
          ? (ram_total_bytes - ram_linker_reserved_bytes)
          : 0U;
  const size_t heap_total_bytes = (size_t)configTOTAL_HEAP_SIZE;
  const size_t heap_final_free_bytes = xPortGetFreeHeapSize();
  const size_t heap_min_free_bytes = xPortGetMinimumEverFreeHeapSize();
  const size_t heap_peak_used_bytes =
      (heap_min_free_bytes <= heap_total_bytes)
          ? (heap_total_bytes - heap_min_free_bytes)
          : 0U;
  size_t workspace_total_bytes = 0U;
  size_t workspace_peak_used_bytes = 0U;
  size_t workspace_headroom_bytes = 0U;
  bool workspace_in_use = false;
  bool workspace_capacity_exceeded = false;
  PQC_RAMRuntimeSnapshot ram_runtime = {0};
  size_t ram_observed_required_bytes = 0U;
  size_t ram_observed_headroom_bytes = 0U;
  bool ram_observed_required_is_lower_bound = false;

  PQC_RAM_RuntimeSnapshotGet(&ram_runtime);
  ram_observed_required_bytes = ram_static_base_bytes +
      ram_runtime.sbrk_peak_used_bytes + ram_runtime.msp_peak_used_bytes;
  ram_observed_required_is_lower_bound = ram_runtime.msp_measurement_saturated;
  if (ram_observed_required_bytes <= ram_total_bytes)
  {
    ram_observed_headroom_bytes = ram_total_bytes - ram_observed_required_bytes;
  }

#if PQC_TLS_COMPILED
  {
    PQC_WolfSSLMemorySnapshot snapshot;
    PQC_WolfSSL_MemorySnapshotGet(&snapshot);
    workspace_total_bytes = snapshot.mldsa_workspace_size_bytes;
    workspace_peak_used_bytes = snapshot.mldsa_workspace_peak_request_bytes;
    workspace_in_use = snapshot.mldsa_workspace_in_use;

    if (workspace_peak_used_bytes <= workspace_total_bytes)
    {
      workspace_headroom_bytes =
          workspace_total_bytes - workspace_peak_used_bytes;
    }
    else
    {
      workspace_capacity_exceeded = true;
    }
  }
#endif

  /*
   * This is emitted only from the completion callback, after the measured
   * workload has finished and immediately before PQC_EXPERIMENT_COMPLETE.
   * RAM3 peak-used means the maximum workspace capacity loaned/requested by
   * wolfSSL, which is the authoritative sizing requirement for the fixed
   * workspace.
   */
  APP_UART_WriteString("PQC_RAM_LINKER_ACCOUNTING ram_total_bytes=");
  APP_UART_WriteUint32((uint32_t)ram_total_bytes);
  APP_UART_WriteString(" ram2_total_bytes=");
  APP_UART_WriteUint32((uint32_t)ram2_total_bytes);
  APP_UART_WriteString(" ram3_total_bytes=");
  APP_UART_WriteUint32((uint32_t)ram3_total_bytes);
  APP_UART_WriteString(" data_bytes=");
  APP_UART_WriteUint32((uint32_t)data_bytes);
  APP_UART_WriteString(" bss_bytes=");
  APP_UART_WriteUint32((uint32_t)bss_bytes);
  APP_UART_WriteString(" ram_static_base_bytes=");
  APP_UART_WriteUint32((uint32_t)ram_static_base_bytes);
  APP_UART_WriteString(" linker_min_heap_bytes=");
  APP_UART_WriteUint32((uint32_t)linker_min_heap_bytes);
  APP_UART_WriteString(" linker_min_msp_bytes=");
  APP_UART_WriteUint32((uint32_t)ram_runtime.msp_reserved_bytes);
  APP_UART_WriteString(" ram_linker_reserved_bytes=");
  APP_UART_WriteUint32((uint32_t)ram_linker_reserved_bytes);
  APP_UART_WriteString(" ram_linker_unreserved_bytes=");
  APP_UART_WriteUint32((uint32_t)ram_linker_unreserved_bytes);
  APP_UART_WriteString(" ram2_linker_used_bytes=0");
  APP_UART_WriteString(" ram2_linker_unreserved_bytes=");
  APP_UART_WriteUint32((uint32_t)ram2_total_bytes);
  APP_UART_WriteString(" ram3_workspace_reserved_bytes=");
  APP_UART_WriteUint32((uint32_t)workspace_total_bytes);
  APP_UART_WriteString(" ram3_linker_unreserved_bytes=");
  APP_UART_WriteUint32((uint32_t)((workspace_total_bytes <= ram3_total_bytes)
      ? (ram3_total_bytes - workspace_total_bytes) : 0U));
  APP_UART_WriteString(" device_linker_ram_total_bytes=");
  APP_UART_WriteUint32((uint32_t)(ram_total_bytes + ram2_total_bytes + ram3_total_bytes));
  APP_UART_WriteString(" device_linker_reserved_bytes=");
  APP_UART_WriteUint32((uint32_t)(ram_linker_reserved_bytes + workspace_total_bytes));
  APP_UART_WriteString("\r\n");

  APP_UART_WriteString(
      "PQC_MEMORY_HIGH_WATERMARK freertos_heap_total_bytes=");
  APP_UART_WriteUint32((uint32_t)heap_total_bytes);
  APP_UART_WriteString(" freertos_heap_peak_used_bytes=");
  APP_UART_WriteUint32((uint32_t)heap_peak_used_bytes);
  APP_UART_WriteString(" freertos_heap_min_free_bytes=");
  APP_UART_WriteUint32((uint32_t)heap_min_free_bytes);
  APP_UART_WriteString(" freertos_heap_final_free_bytes=");
  APP_UART_WriteUint32((uint32_t)heap_final_free_bytes);
  APP_UART_WriteString(" mldsa_workspace_total_bytes=");
  APP_UART_WriteUint32((uint32_t)workspace_total_bytes);
  APP_UART_WriteString(" mldsa_workspace_peak_used_bytes=");
  APP_UART_WriteUint32((uint32_t)workspace_peak_used_bytes);
  APP_UART_WriteString(" mldsa_workspace_headroom_bytes=");
  APP_UART_WriteUint32((uint32_t)workspace_headroom_bytes);
  APP_UART_WriteString(" mldsa_workspace_capacity_exceeded=");
  APP_UART_WriteUint32(workspace_capacity_exceeded ? 1U : 0U);
  APP_UART_WriteString(" mldsa_workspace_in_use=");
  APP_UART_WriteUint32(workspace_in_use ? 1U : 0U);
  APP_UART_WriteString(" sbrk_capacity_bytes=");
  APP_UART_WriteUint32((uint32_t)ram_runtime.sbrk_capacity_bytes);
  APP_UART_WriteString(" sbrk_peak_used_bytes=");
  APP_UART_WriteUint32((uint32_t)ram_runtime.sbrk_peak_used_bytes);
  APP_UART_WriteString(" sbrk_final_used_bytes=");
  APP_UART_WriteUint32((uint32_t)ram_runtime.sbrk_current_used_bytes);
  APP_UART_WriteString(" sbrk_ever_called=");
  APP_UART_WriteUint32(ram_runtime.sbrk_ever_called ? 1U : 0U);
  APP_UART_WriteString(" msp_reserved_bytes=");
  APP_UART_WriteUint32((uint32_t)ram_runtime.msp_reserved_bytes);
  APP_UART_WriteString(" msp_peak_used_bytes=");
  APP_UART_WriteUint32((uint32_t)ram_runtime.msp_peak_used_bytes);
  APP_UART_WriteString(" msp_headroom_bytes=");
  APP_UART_WriteUint32((uint32_t)ram_runtime.msp_headroom_bytes);
  APP_UART_WriteString(" msp_excess_bytes=");
  APP_UART_WriteUint32((uint32_t)ram_runtime.msp_excess_bytes);
  APP_UART_WriteString(" msp_measurement_window_bytes=");
  APP_UART_WriteUint32((uint32_t)ram_runtime.msp_measurement_window_bytes);
  APP_UART_WriteString(" msp_reservation_exceeded=");
  APP_UART_WriteUint32(ram_runtime.msp_reservation_exceeded ? 1U : 0U);
  APP_UART_WriteString(" msp_measurement_saturated=");
  APP_UART_WriteUint32(ram_runtime.msp_measurement_saturated ? 1U : 0U);
  APP_UART_WriteString(" ram_observed_required_bytes=");
  APP_UART_WriteUint32((uint32_t)ram_observed_required_bytes);
  APP_UART_WriteString(" ram_observed_headroom_bytes=");
  APP_UART_WriteUint32((uint32_t)ram_observed_headroom_bytes);
  APP_UART_WriteString(" ram_observed_required_is_lower_bound=");
  APP_UART_WriteUint32(ram_observed_required_is_lower_bound ? 1U : 0U);
  APP_UART_WriteString(" device_observed_workload_required_bytes=");
  APP_UART_WriteUint32((uint32_t)(ram_observed_required_bytes + workspace_peak_used_bytes));
  APP_UART_WriteString(" device_observed_workload_required_is_lower_bound=");
  APP_UART_WriteUint32(ram_observed_required_is_lower_bound ? 1U : 0U);
  APP_UART_WriteString("\r\n");
}

static void APP_MarkExperimentComplete(void)
{
  if (!app_experiment_complete)
  {
    APP_PrintMemoryHighWatermark();
    APP_UART_WriteString("PQC_EXPERIMENT_COMPLETE experiment=" PQC_MQTT_TLS_MODE " status=done\r\n");
    app_experiment_complete = true;
  }
}

static void APP_ResultBufferWriteLine(const char *text)
{
  (void)PQC_ResultBufferAppendText(0U, "tls", text);
}

static void APP_FormatU64(uint64_t value, char *buffer, size_t buffer_size)
{
  char reversed[21];
  size_t count = 0U;
  size_t index;

  if ((buffer == NULL) || (buffer_size == 0U))
  {
    return;
  }

  do
  {
    reversed[count++] = (char)('0' + (value % 10ULL));
    value /= 10ULL;
  } while ((value != 0ULL) && (count < sizeof(reversed)));

  if (count >= buffer_size)
  {
    buffer[0] = '\0';
    return;
  }

  for (index = 0U; index < count; index++)
  {
    buffer[index] = reversed[count - index - 1U];
  }
  buffer[count] = '\0';
}

static void APP_BufferReadyMetrics2Evidence(void)
{
  const PQC_WolfMQTTReadyMetrics2Snapshot *metrics =
      PQC_WolfMQTT_ReadyMetrics2Snapshot();
  const PQC_TimebaseProvenance *timebase = PQC_TimebaseGetProvenance();
  char line[768];
  char u64_a[24];
  char u64_b[24];
  char u64_c[24];
  char u64_d[24];
  char u64_e[24];
  char u64_f[24];
  char u64_g[24];
  int written;

  if ((metrics == NULL) || (timebase == NULL) ||
      (metrics->schema_version != 3U) ||
      (metrics->transfer_complete_valid == 0U))
  {
    return;
  }

  /* Ready Metrics 2 records are serialized only after the selected workload
   * has returned, so formatting/result-buffer work cannot perturb the measured
   * TCP/request/payload intervals. The outer result-buffer envelope supplies
   * source/iteration/context; these compact records preserve the scientific
   * checkpoints and derived values for later offline ingestion. */
  APP_FormatU64(timebase->reset_origin_to_application_timebase_us, u64_a, sizeof(u64_a));
  written = snprintf(
      line, sizeof(line),
      "PQC_RM2_TIMEBASE schema=3 source=TIM2 timer_input_clock_hz=%lu "
      "prescaler=%lu counter_hz=%lu counter_bits=%lu "
      "wrap_handling=update_irq_64bit_extension "
      "reset_origin=operational_wolfboot_entry reset_origin_valid=%u "
      "reset_origin_kind=%lu reset_origin_to_application_timebase_us=%s "
      "handoff_bridge=LPTIM2_HSI16_DIV16 firmware_elf_sha256_source=run_manifest",
      (unsigned long)timebase->timer_input_clock_hz,
      (unsigned long)timebase->prescaler,
      (unsigned long)timebase->counter_hz,
      (unsigned long)timebase->counter_bits,
      (unsigned int)timebase->reset_origin_valid,
      (unsigned long)timebase->reset_origin_kind,
      u64_a);
  if ((written > 0) && ((size_t)written < sizeof(line)))
  {
    (void)PQC_ResultBufferAppendText(0U, "rm2_timebase", line);
  }

  APP_FormatU64(timebase->reset_origin_to_application_timebase_us, u64_a, sizeof(u64_a));
  APP_FormatU64(metrics->tcp_connect_start_us, u64_b, sizeof(u64_b));
  APP_FormatU64(metrics->mqtt_readiness_checkpoint_us, u64_c, sizeof(u64_c));
  APP_FormatU64(metrics->mqtt_readiness_us, u64_d, sizeof(u64_d));
  APP_FormatU64(metrics->application_request_us, u64_e, sizeof(u64_e));
  APP_FormatU64(metrics->application_first_byte_us, u64_f, sizeof(u64_f));
  APP_FormatU64(metrics->application_last_byte_us, u64_g, sizeof(u64_g));
  written = snprintf(
      line, sizeof(line),
      "PQC_RM2_CHECKPOINTS schema=3 reset_origin=operational_wolfboot_entry "
      "reset_origin_valid=%u reset_origin_to_application_timebase_us=%s "
      "tcp_connect_start_us=%s mqtt_readiness_checkpoint_us=%s "
      "mqtt_readiness_definition=tcp_connect_start_to_first_mqtt_connack_plaintext_byte "
      "mqtt_readiness_us=%s mqtt_readiness_valid=%u application_request_us=%s "
      "application_first_byte_us=%s application_last_byte_us=%s",
      (unsigned int)metrics->reset_origin_valid,
      u64_a, u64_b, u64_c, u64_d,
      (unsigned int)metrics->mqtt_readiness_valid,
      u64_e, u64_f, u64_g);
  if ((written > 0) && ((size_t)written < sizeof(line)))
  {
    (void)PQC_ResultBufferAppendText(0U, "rm2_checkpoints", line);
  }

  APP_FormatU64(metrics->rtfb_us, u64_a, sizeof(u64_a));
  APP_FormatU64(metrics->rtlb_us, u64_b, sizeof(u64_b));
  APP_FormatU64(metrics->ttfb_us, u64_c, sizeof(u64_c));
  APP_FormatU64(metrics->ttlb_us, u64_d, sizeof(u64_d));
  APP_FormatU64(metrics->req_tfb_us, u64_e, sizeof(u64_e));
  APP_FormatU64(metrics->req_tlb_us, u64_f, sizeof(u64_f));
  APP_FormatU64(metrics->application_transfer_us, u64_g, sizeof(u64_g));
  written = snprintf(
      line, sizeof(line),
      "PQC_RM2_METRICS schema=3 metric_contract=ready_metrics_2_canonical_v3 "
      "payload_bytes=%lu received_bytes=%lu chunk_bytes=%lu "
      "rtfb_us=%s rtlb_us=%s ttfb_us=%s ttlb_us=%s "
      "req_tfb_us=%s req_tlb_us=%s application_transfer_us=%s "
      "reset_metrics_valid=%u complete_valid=%u",
      (unsigned long)metrics->transfer_payload_bytes,
      (unsigned long)metrics->transfer_received_bytes,
      (unsigned long)metrics->transfer_chunk_bytes,
      u64_a, u64_b, u64_c, u64_d, u64_e, u64_f, u64_g,
      (unsigned int)metrics->reset_origin_valid,
      (unsigned int)metrics->transfer_complete_valid);
  if ((written > 0) && ((size_t)written < sizeof(line)))
  {
    (void)PQC_ResultBufferAppendText(0U, "rm2_metrics", line);
  }

  APP_FormatU64(metrics->measurement_complete_us, u64_a, sizeof(u64_a));
  written = snprintf(
      line, sizeof(line),
      "PQC_RM2_COMPLETE schema=3 status=success record_count=4 "
      "measurement_complete_us=%s",
      u64_a);
  if ((written > 0) && ((size_t)written < sizeof(line)))
  {
    (void)PQC_ResultBufferAppendText(0U, "rm2_complete", line);
  }
}

static void APP_BufferMemoryEvidence(void)
{
  char line[768];
  const size_t heap_total_bytes = (size_t)configTOTAL_HEAP_SIZE;
  const size_t heap_final_free_bytes = xPortGetFreeHeapSize();
  const size_t heap_min_free_bytes = xPortGetMinimumEverFreeHeapSize();
  const size_t heap_peak_used_bytes =
      (heap_min_free_bytes <= heap_total_bytes)
          ? (heap_total_bytes - heap_min_free_bytes)
          : 0U;
  PQC_RAMRuntimeSnapshot ram_runtime = {0};
  size_t workspace_total_bytes = 0U;
  size_t workspace_peak_used_bytes = 0U;
  bool workspace_in_use = false;

  PQC_RAM_RuntimeSnapshotGet(&ram_runtime);
#if PQC_TLS_COMPILED
  {
    PQC_WolfSSLMemorySnapshot snapshot;
    PQC_WolfSSL_MemorySnapshotGet(&snapshot);
    workspace_total_bytes = snapshot.mldsa_workspace_size_bytes;
    workspace_peak_used_bytes = snapshot.mldsa_workspace_peak_request_bytes;
    workspace_in_use = snapshot.mldsa_workspace_in_use;
  }
#endif

  (void)snprintf(
      line, sizeof(line),
      "freertos_heap_total_bytes=%lu freertos_heap_peak_used_bytes=%lu "
      "freertos_heap_min_free_bytes=%lu freertos_heap_final_free_bytes=%lu "
      "sbrk_capacity_bytes=%lu sbrk_peak_used_bytes=%lu sbrk_final_used_bytes=%lu "
      "msp_reserved_bytes=%lu msp_peak_used_bytes=%lu msp_headroom_bytes=%lu "
      "msp_excess_bytes=%lu msp_measurement_window_bytes=%lu "
      "msp_reservation_exceeded=%u msp_measurement_saturated=%u "
      "mldsa_workspace_total_bytes=%lu mldsa_workspace_peak_used_bytes=%lu "
      "mldsa_workspace_in_use=%u",
      (unsigned long)heap_total_bytes,
      (unsigned long)heap_peak_used_bytes,
      (unsigned long)heap_min_free_bytes,
      (unsigned long)heap_final_free_bytes,
      (unsigned long)ram_runtime.sbrk_capacity_bytes,
      (unsigned long)ram_runtime.sbrk_peak_used_bytes,
      (unsigned long)ram_runtime.sbrk_current_used_bytes,
      (unsigned long)ram_runtime.msp_reserved_bytes,
      (unsigned long)ram_runtime.msp_peak_used_bytes,
      (unsigned long)ram_runtime.msp_headroom_bytes,
      (unsigned long)ram_runtime.msp_excess_bytes,
      (unsigned long)ram_runtime.msp_measurement_window_bytes,
      ram_runtime.msp_reservation_exceeded ? 1U : 0U,
      ram_runtime.msp_measurement_saturated ? 1U : 0U,
      (unsigned long)workspace_total_bytes,
      (unsigned long)workspace_peak_used_bytes,
      workspace_in_use ? 1U : 0U);
  (void)PQC_ResultBufferAppendText(0U, "memory", line);
}

void StartNetworkTask(void *argument)
{
  const PQC_MQTTApplicationFixture fixture = {
    .uart_write = APP_UART_WriteString,
    .run_network_bringup = APP_RunST67SPIBringup,
    .is_network_ready = APP_IsNetworkReady,
    .print_lwip_runtime = APP_PrintLwIPRuntimeFixture,
    .print_wolfssl_runtime = APP_WolfSSLRuntimeFixtureNoOp,
    .print_wolfmqtt_runtime = APP_PrintWolfMQTTRuntimeStatus,
    .run_ready_metrics_workload = APP_RunReadyMetricsWorkload,
    .run_ready_metrics_2_workload = APP_RunReadyMetrics2Workload,
    .run_tls_handshake_repeat_workload = APP_RunTLSHandshakeRepeatWorkload,
    .print_clock_configuration = APP_PrintApplicationClockConfiguration,
    .print_memory_checkpoint = APP_PrintNetworkTaskMemoryCheckpoint,
    .mark_complete = APP_MarkExperimentComplete,
  };

  (void)argument;
#if !PQC_BAREMETAL_BENCHMARK_ENABLED
  PQC_ResultBufferReset();
#endif
  APP_UART_WriteString("FreeRTOS networkTask started: initialization active\r\n");
#if !PQC_BAREMETAL_BENCHMARK_ENABLED
  PQC_EnergyBoundaryInitialize();
  if (!PQC_EnergyAwaitStart()) {
    osThreadExit();
    return;
  }
#endif
#if !PQC_TLS_HANDSHAKE_REPEAT_ENABLED && !PQC_BAREMETAL_BENCHMARK_ENABLED
  PQC_EnergyBoundaryBegin();
#endif
  app_measurement_active = true;
  PQC_MQTT_ApplicationRun(&fixture);
  app_measurement_active = false;
#if !PQC_TLS_HANDSHAKE_REPEAT_ENABLED && !PQC_BAREMETAL_BENCHMARK_ENABLED
  PQC_EnergyBoundaryEnd();
  PQC_EnergyBoundaryAppend(0U);
#endif
#if !PQC_TLS_HANDSHAKE_REPEAT_ENABLED
  APP_BufferReadyMetrics2Evidence();
  APP_BufferMemoryEvidence();
  PQC_TLS_InstrumentationReport(APP_ResultBufferWriteLine);
  PQC_BootEvidenceAppendToResultBuffer(0U);
  (void)PQC_ResultBufferAppendText(0U, "application", "workload_complete");
  {
    PQC_ResultBufferStatus result_status;
    char result_sha256[65];
    PQC_ResultBufferStatusGet(&result_status);
    PQC_ResultBufferSha256Hex(result_sha256);
    if (PQC_WolfMQTT_PublishDeferredResults(
            PQC_ResultBufferData(), PQC_ResultBufferSize(), result_sha256,
            result_status.record_count, result_status.dropped_record_count,
            result_status.overflowed != 0U) != 0)
    {
      APP_UART_WriteString("PQC_REPORTING_FAILURE stage=publish_deferred_results\r\n");
    }
  }
#endif
  osThreadExit();
}



#if PQC_WOLFSSL_MEMORY_DIAGNOSTICS
static char *APP_UART_AppendLiteral(char *cursor, char *end, const char *text)
{
  while ((cursor < end) && (*text != '\0'))
  {
    *cursor++ = *text++;
  }
  return cursor;
}

static char *APP_UART_AppendSize(char *cursor, char *end, size_t value)
{
  char digits[3U * sizeof(size_t)];
  size_t count = 0U;

  do
  {
    digits[count++] = (char)('0' + (value % 10U));
    value /= 10U;
  } while ((value != 0U) && (count < sizeof(digits)));

  while ((count != 0U) && (cursor < end))
  {
    *cursor++ = digits[--count];
  }
  return cursor;
}

static void APP_UART_WriteMallocFailureDiagnostic(void)
{
  PQC_WolfSSLMemorySnapshot snapshot;
  char line[384];
  char *cursor = line;
  char *end = line + sizeof(line) - 3U;

  PQC_WolfSSL_MemorySnapshotGet(&snapshot);

  cursor = APP_UART_AppendLiteral(
      cursor, end, "PQC_FREERTOS_ALLOC_FAIL wolfssl_allocation_active=");
  cursor = APP_UART_AppendSize(cursor, end, snapshot.allocation_active ? 1U : 0U);
  cursor = APP_UART_AppendLiteral(cursor, end, " wolfssl_requested_bytes=");
  cursor = APP_UART_AppendSize(cursor, end, snapshot.pending_request_bytes);
  cursor = APP_UART_AppendLiteral(cursor, end, " wolfssl_total_bytes=");
  cursor = APP_UART_AppendSize(cursor, end, snapshot.pending_total_bytes);
  cursor = APP_UART_AppendLiteral(cursor, end, " free_heap_bytes=");
  cursor = APP_UART_AppendSize(cursor, end, snapshot.free_heap_bytes);
  cursor = APP_UART_AppendLiteral(cursor, end, " minimum_ever_free_heap_bytes=");
  cursor = APP_UART_AppendSize(
      cursor, end, snapshot.minimum_ever_free_heap_bytes);
  cursor = APP_UART_AppendLiteral(cursor, end, " largest_free_block_bytes=");
  cursor = APP_UART_AppendSize(cursor, end, snapshot.largest_free_block_bytes);
  cursor = APP_UART_AppendLiteral(cursor, end, " free_block_count=");
  cursor = APP_UART_AppendSize(cursor, end, snapshot.free_block_count);
  cursor = APP_UART_AppendLiteral(cursor, end, "\r\n");
  *cursor = '\0';

  /*
   * APP_UART_WriteString ultimately uses HAL_UART_Transmit(..., HAL_MAX_DELAY).
   * No dynamic allocation is performed by this formatting path.
   */
  APP_UART_WriteString(line);
}

#endif

void vApplicationStackOverflowHook(TaskHandle_t task, char *task_name)
{
  (void)task;
  APP_UART_WriteString("FATAL: FreeRTOS stack overflow task=");
  APP_UART_WriteString((task_name != NULL) ? task_name : "unknown");
  APP_UART_WriteString("\r\n");
  taskDISABLE_INTERRUPTS();
  for (;;)
  {
  }
}

void vApplicationMallocFailedHook(void)
{
  /*
   * Report while interrupts are still enabled. APP_UART_WriteString() reaches
   * the blocking HAL_UART_Transmit() path, so the complete diagnostic is sent
   * before the firmware deliberately halts.
   */
#if PQC_WOLFSSL_MEMORY_DIAGNOSTICS
  APP_UART_WriteMallocFailureDiagnostic();
#endif
  APP_UART_WriteString("FATAL: FreeRTOS allocation failed\r\n");
  taskDISABLE_INTERRUPTS();
  for (;;)
  {
  }
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
