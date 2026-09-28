/* SparkFun INA228 integration for the ESP-IDF energy instrument.
 *
 * Measurement conversion and INA228 calibration are delegated to the upstream
 * SparkFun INA2XX driver. This file supplies only the ESP-IDF I2C transport,
 * FreeRTOS raw snapshots. Integration and attribution belong to offline analysis.
 *
 * SparkFun SEN-31438 is nominally populated with an R015 (15 mOhm) shunt.
 * Reference-load comparison against a series DMM showed an effective sensed
 * resistance of approximately 29 mOhm for this assembled instrument. The
 * SparkFun calibration API therefore uses 29 mOhm as the current/power scaling
 * constant. This remains an empirical instrument calibration rather than a
 * traceable metrology calibration.
 */
#include "ina228_sparkfun.h"

#include <inttypes.h>
#include <stdint.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#include "driver/gpio.h"
#include "driver/i2c.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "sdkconfig.h"

#include "sfTk/sfDevINA228.h"
#include "sfTk/sfTkII2C.h"

#ifndef CONFIG_PQC_ENERGY_SAMPLE_PERIOD_MS
#define CONFIG_PQC_ENERGY_SAMPLE_PERIOD_MS 50
#endif
#ifndef CONFIG_PQC_INA228_ALERT_GPIO
#define CONFIG_PQC_INA228_ALERT_GPIO 12
#endif

namespace {

constexpr uint8_t kIna228Address = 0x40;
constexpr uint16_t kIna228DeviceIdMask = 0xFFF0;
constexpr uint16_t kIna228DeviceIdValue = 0x2280;
constexpr float kNominalShuntOhms = 0.015f;
constexpr float kCalibrationShuntOhms = 0.029f;
constexpr float kCalibrationMaxCurrentA = 10.0f;
constexpr TickType_t kI2CTimeout = pdMS_TO_TICKS(100);
constexpr uint32_t kFallbackPeriodMs = CONFIG_PQC_ENERGY_SAMPLE_PERIOD_MS;
constexpr gpio_num_t kAlertGpio = static_cast<gpio_num_t>(CONFIG_PQC_INA228_ALERT_GPIO);
constexpr uint32_t kBusConversionUs = 50;
constexpr uint32_t kShuntConversionUs = 50;
constexpr uint32_t kNominalConversionPeriodUs = kBusConversionUs + kShuntConversionUs;

const char *TAG = "ina228_sparkfun";

class EspIdfI2CBus final : public sfTkII2C
{
  public:
    sfTkError_t init(i2c_port_t port, uint8_t address)
    {
        _port = port;
        setAddress(address);
        return ksfTkErrOk;
    }

    sfTkError_t ping() override
    {
        uint8_t commandStorage[I2C_LINK_RECOMMENDED_SIZE(2)];
        i2c_cmd_handle_t cmd = i2c_cmd_link_create_static(commandStorage, sizeof(commandStorage));
        if (cmd == nullptr)
            return ksfTkErrFail;

        esp_err_t err = i2c_master_start(cmd);
        if (err == ESP_OK)
            err = i2c_master_write_byte(cmd, (address() << 1) | I2C_MASTER_WRITE, true);
        if (err == ESP_OK)
            err = i2c_master_stop(cmd);
        if (err == ESP_OK)
            err = i2c_master_cmd_begin(_port, cmd, kI2CTimeout);

        i2c_cmd_link_delete_static(cmd);
        return err == ESP_OK ? ksfTkErrOk : ksfTkErrFail;
    }

    sfTkError_t writeRegister(uint8_t *devReg, size_t regLength,
                              const uint8_t *data, size_t length) override
    {
        uint8_t commandStorage[I2C_LINK_RECOMMENDED_SIZE(2)];
        i2c_cmd_handle_t cmd = i2c_cmd_link_create_static(commandStorage, sizeof(commandStorage));
        if (cmd == nullptr)
            return ksfTkErrFail;

        esp_err_t err = i2c_master_start(cmd);
        if (err == ESP_OK)
            err = i2c_master_write_byte(cmd, (address() << 1) | I2C_MASTER_WRITE, true);
        if (err == ESP_OK && devReg != nullptr && regLength > 0)
            err = i2c_master_write(cmd, devReg, regLength, true);
        if (err == ESP_OK && data != nullptr && length > 0)
            err = i2c_master_write(cmd, const_cast<uint8_t *>(data), length, true);
        if (err == ESP_OK)
            err = i2c_master_stop(cmd);
        if (err == ESP_OK)
            err = i2c_master_cmd_begin(_port, cmd, kI2CTimeout);

        i2c_cmd_link_delete_static(cmd);
        return err == ESP_OK ? ksfTkErrOk : ksfTkErrFail;
    }

    sfTkError_t readRegister(uint8_t *devReg, size_t regLength,
                             uint8_t *data, size_t numBytes,
                             size_t &readBytes, uint32_t readDelayMs = 0) override
    {
        readBytes = 0;
        if (data == nullptr || numBytes == 0)
            return ksfTkErrInvalidParam;

        esp_err_t err = ESP_OK;
        if (devReg != nullptr && regLength > 0 && readDelayMs == 0) {
            uint8_t commandStorage[I2C_LINK_RECOMMENDED_SIZE(2)];
        i2c_cmd_handle_t cmd = i2c_cmd_link_create_static(commandStorage, sizeof(commandStorage));
            if (cmd == nullptr)
                return ksfTkErrFail;

            err = i2c_master_start(cmd);
            if (err == ESP_OK)
                err = i2c_master_write_byte(cmd, (address() << 1) | I2C_MASTER_WRITE, true);
            if (err == ESP_OK)
                err = i2c_master_write(cmd, devReg, regLength, true);
            if (err == ESP_OK)
                err = i2c_master_start(cmd);
            if (err == ESP_OK)
                err = i2c_master_write_byte(cmd, (address() << 1) | I2C_MASTER_READ, true);
            if (err == ESP_OK)
                err = i2c_master_read(cmd, data, numBytes, I2C_MASTER_LAST_NACK);
            if (err == ESP_OK)
                err = i2c_master_stop(cmd);
            if (err == ESP_OK)
                err = i2c_master_cmd_begin(_port, cmd, kI2CTimeout);

            i2c_cmd_link_delete_static(cmd);
        } else {
            if (devReg != nullptr && regLength > 0) {
                err = i2c_master_write_to_device(_port, address(), devReg, regLength,
                                                 kI2CTimeout);
                if (err == ESP_OK && readDelayMs > 0)
                    vTaskDelay(pdMS_TO_TICKS(readDelayMs));
            }
            if (err == ESP_OK)
                err = i2c_master_read_from_device(_port, address(), data, numBytes,
                                                  kI2CTimeout);
        }

        if (err != ESP_OK)
            return ksfTkErrFail;

        readBytes = numBytes;
        return ksfTkErrOk;
    }

  private:
    i2c_port_t _port = I2C_NUM_0;
};

// ADC configuration is fixed between successful configureSensor() calls.
// Cache the SparkFun-owned bitfield once, so re-triggering needs one write
// rather than a read-modify-write transaction for every retained sample.
class TriggeredINA228 final : public sfDevINA228 {
  public:
    sfTkError_t cacheTriggerConfiguration() {
        sfTkError_t rc = _theBus->readRegister(kRegAdcConfig, triggerConfig.word);
        triggerConfig.mode = INA2XX_MODE_TRIG_BUS_SHUNT;
        return rc;
    }
    sfTkError_t triggerNext() {
        return _theBus->writeRegister(kRegAdcConfig, triggerConfig.word);
    }
  private:
    sfe_ina2xx_adc_config_reg_t triggerConfig = {};
};

EspIdfI2CBus sensorBus;
TriggeredINA228 sensor;
SemaphoreHandle_t snapshotMutex = nullptr;
pqc_ina228_snapshot_t latest = {};
pqc_ina228_sample_callback_t sampleCallback = nullptr;
TaskHandle_t sensorTaskHandle = nullptr;
portMUX_TYPE alertStateMux = portMUX_INITIALIZER_UNLOCKED;
bool pauseRequested = false;
bool acquisitionPaused = false;
volatile uint32_t alertEdgeCount = 0;
volatile int64_t latestAlertTimestampUs = 0;

void IRAM_ATTR alertGpioIsr(void *)
{
    if (sensorTaskHandle == nullptr)
        return;

    BaseType_t higherPriorityTaskWoken = pdFALSE;
    const int64_t timestampUs = esp_timer_get_time();

    portENTER_CRITICAL_ISR(&alertStateMux);
    const uint32_t nextEdgeCount = alertEdgeCount + 1U;
    alertEdgeCount = nextEdgeCount;
    latestAlertTimestampUs = timestampUs;
    portEXIT_CRITICAL_ISR(&alertStateMux);

    vTaskNotifyGiveFromISR(sensorTaskHandle, &higherPriorityTaskWoken);
    if (higherPriorityTaskWoken == pdTRUE)
        portYIELD_FROM_ISR();
}

void configureAlertGpio()
{
    gpio_config_t io = {};
    io.pin_bit_mask = 1ULL << static_cast<unsigned>(kAlertGpio);
    io.mode = GPIO_MODE_INPUT;
    io.pull_up_en = GPIO_PULLUP_ENABLE;
    io.pull_down_en = GPIO_PULLDOWN_DISABLE;
    io.intr_type = GPIO_INTR_NEGEDGE;
    ESP_ERROR_CHECK(gpio_config(&io));

    /*
     * The INA228 integration is initialised before energy_session, so it owns
     * installation of the process-wide ESP-IDF GPIO ISR service. The sync
     * input later only adds its handler to this existing service.
     */
    ESP_ERROR_CHECK(gpio_install_isr_service(0));
    ESP_ERROR_CHECK(gpio_isr_handler_add(kAlertGpio, alertGpioIsr, nullptr));

    /*
     * Keep the interrupt disabled until the INA228 has been put into shutdown,
     * stale conversion-ready state has been cleared, and the ALERT routing has
     * been configured. This prevents a power-on asserted ALERT level from
     * becoming the permanent initial state with no falling edge to wake us.
     */
    ESP_ERROR_CHECK(gpio_intr_disable(kAlertGpio));
    ESP_LOGI(TAG,
             "INA228 ALERT input prepared: GPIO%d active-low conversion-ready; "
             "interrupt held disabled until sensor initialization completes",
             static_cast<int>(kAlertGpio));
}

void publishSample(const pqc_ina228_snapshot_t &sample)
{
    if (snapshotMutex != nullptr &&
        xSemaphoreTake(snapshotMutex, pdMS_TO_TICKS(100)) == pdTRUE) {
        latest = sample;
        xSemaphoreGive(snapshotMutex);
    }
    if (sampleCallback != nullptr) {
        sampleCallback(&sample);
    }
}

bool configureSensor()
{
    if (sensor.begin(&sensorBus) != ksfTkErrOk) {
        ESP_LOGE(TAG, "SparkFun sfDevINA228 begin failed");
        return false;
    }

    uint16_t deviceId = 0;
    if (sensor.getDeviceID(deviceId) != ksfTkErrOk ||
        (deviceId & kIna228DeviceIdMask) != kIna228DeviceIdValue) {
        ESP_LOGE(TAG, "INA228 identity check failed: device ID 0x%04x", deviceId);
        return false;
    }

    /*
     * Stop ADC conversions before touching conversion-ready ALERT routing.
     * The INA228 powers up converting by default, and a conversion-ready
     * condition can therefore already be active when the ESP32 attaches its
     * GPIO handler. Explicit shutdown + clear makes startup deterministic.
     */
    if (sensor.setADCMode(INA2XX_MODE_SHUTDOWN) != ksfTkErrOk) {
        ESP_LOGE(TAG, "INA228 shutdown before ALERT initialization failed");
        return false;
    }

    /* Disable conversion-ready routing while clearing any power-on state. */
    if (sensor.setConversionReadyAlert(false) != ksfTkErrOk) {
        ESP_LOGE(TAG, "INA228 conversion-ready ALERT disable failed");
        return false;
    }

    bool staleReady = false;
    sfTkError_t clearRc = sensor.isConversionReady(staleReady);
    if (clearRc != ksfTkErrOk) {
        ESP_LOGE(TAG, "INA228 initial DIAG_ALRT read failed: rc=%" PRId32,
                 static_cast<int32_t>(clearRc));
        return false;
    }

    /* SparkFun requires ADCRANGE to be selected before calibrate(). */
    if (sensor.setADCRange(false) != ksfTkErrOk) {
        ESP_LOGE(TAG, "INA228 setADCRange(false) failed");
        return false;
    }
    if (sensor.setAveragingCount(INA2XX_AVG_1) != ksfTkErrOk) {
        ESP_LOGE(TAG, "INA228 setAveragingCount failed");
        return false;
    }
    if (sensor.setBusVoltageConvTime(INA2XX_CONV_50US) != ksfTkErrOk ||
        sensor.setShuntVoltageConvTime(INA2XX_CONV_50US) != ksfTkErrOk) {
        ESP_LOGE(TAG, "INA228 conversion-time configuration failed");
        return false;
    }
    if (sensor.setAlertLatch(false) != ksfTkErrOk ||
        sensor.setAlertPolarity(false) != ksfTkErrOk) {
        ESP_LOGE(TAG, "INA228 ALERT polarity/latch configuration failed");
        return false;
    }
    if (sensor.calibrate(kCalibrationShuntOhms, kCalibrationMaxCurrentA) != ksfTkErrOk) {
        ESP_LOGE(TAG, "INA228 SparkFun calibration failed");
        return false;
    }

    /*
     * With CNVR disabled and the ADC stopped, ALERT should be idle-high via
     * the GPIO pull-up. If it is low, read DIAG_ALRT once more before arming.
     * This recovers the observed power-on condition that previously required
     * physically unplugging/replugging ALERT to produce the first edge.
     */
    int idleLevel = gpio_get_level(kAlertGpio);
    if (idleLevel == 0) {
        bool ready = false;
        const sfTkError_t rc = sensor.isConversionReady(ready);
        ESP_LOGW(TAG,
                 "INA228 ALERT low during startup clear: ready=%u rc=%" PRId32
                 "; clearing DIAG_ALRT before interrupt enable",
                 ready ? 1u : 0u, static_cast<int32_t>(rc));
        vTaskDelay(pdMS_TO_TICKS(1));
        idleLevel = gpio_get_level(kAlertGpio);
    }

    if (idleLevel == 0) {
        ESP_LOGE(TAG,
                 "INA228 ALERT remains low before continuous conversions; "
                 "check ALERT pull-up/wiring and diagnostic state");
        return false;
    }

    /*
     * Arm the GPIO before re-enabling conversion-ready routing and starting
     * continuous conversions, so the first real conversion edge is captured.
     */
    ESP_ERROR_CHECK(gpio_intr_enable(kAlertGpio));

    if (sensor.setConversionReadyAlert(true) != ksfTkErrOk) {
        ESP_LOGE(TAG, "INA228 conversion-ready ALERT enable failed");
        ESP_ERROR_CHECK(gpio_intr_disable(kAlertGpio));
        return false;
    }
    if (sensor.setADCMode(INA2XX_MODE_TRIG_BUS_SHUNT) != ksfTkErrOk) {
        ESP_LOGE(TAG, "INA228 triggered bus+shunt conversion configuration failed");
        (void)sensor.setConversionReadyAlert(false);
        ESP_ERROR_CHECK(gpio_intr_disable(kAlertGpio));
        return false;
    }

    if (sensor.cacheTriggerConfiguration() != ksfTkErrOk)
        return false;

    uint16_t shuntCal = 0;
    bool reducedRange = true;
    if (sensor.getADCRange(reducedRange) != ksfTkErrOk ||
        sensor.getShuntCal(shuntCal) != ksfTkErrOk) {
        ESP_LOGE(TAG, "INA228 configuration readback failed");
        return false;
    }

    ESP_LOGI(TAG,
             "INA228 ready via SparkFun driver: device=0x%04x ADCRANGE=%u "
             "SHUNT_CAL=%u nominal_shunt=%.3fmOhm calibrated_effective_shunt=%.3fmOhm "
             "conversion_ready_gpio=%d conversion_period=%" PRIu32 "us adc_only_ceiling=%.1fHz (not achieved sample rate) "
             "startup_ready_was_set=%u alert_idle_before_start=%d max_current_scale=%.3fA",
             deviceId, reducedRange ? 1u : 0u, shuntCal,
             static_cast<double>(kNominalShuntOhms * 1000.0f),
             static_cast<double>(kCalibrationShuntOhms * 1000.0f),
             static_cast<int>(kAlertGpio), kNominalConversionPeriodUs,
             1000000.0 / static_cast<double>(kNominalConversionPeriodUs),
             staleReady ? 1u : 0u, idleLevel,
             static_cast<double>(kCalibrationMaxCurrentA));
    return true;
}

void sensorTask(void *)
{
    bool configured = false;
    uint64_t sequence = 0;
    int64_t previousTimestampUs = 0;
    uint32_t previousEdgeCount = 0;
    pqc_ina228_snapshot_t counters = {};

    for (;;) {
        portENTER_CRITICAL(&alertStateMux);
        const bool pause = pauseRequested;
        portEXIT_CRITICAL(&alertStateMux);
        if (pause) {
            // Triggered mode returns to shutdown after its one conversion.
            // No new trigger is issued while paused; finish/retain any sample
            // already handled by the preceding iteration before acknowledging.
            (void)gpio_intr_disable(kAlertGpio);
            configured = false;
            previousTimestampUs = 0; // deliberate pause is not a sample-gap fault
            previousEdgeCount = 0;
            counters.paused = true;
            counters.valid = false;
            publishSample(counters);
            portENTER_CRITICAL(&alertStateMux);
            acquisitionPaused = true;
            portEXIT_CRITICAL(&alertStateMux);
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        portENTER_CRITICAL(&alertStateMux);
        acquisitionPaused = false;
        portEXIT_CRITICAL(&alertStateMux);
        counters.paused = false;
        if (!configured) {
            (void)ulTaskNotifyTake(pdTRUE, 0);
            configured = configureSensor();
            if (!configured) {
                counters.valid = false;
                counters.online = false;
                counters.i2c_errors++;
                publishSample(counters);
                (void)gpio_intr_disable(kAlertGpio);
                vTaskDelay(pdMS_TO_TICKS(kFallbackPeriodMs));
                continue;
            }
        }

        // One triggered bus+shunt conversion, then shutdown until we finish
        // reading it. No mixed-generation register values, silent overwritten
        // conversions, polling cadence, or integration in the capture task.
        const uint32_t pending = ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(1000));
        if (pending == 0U) {
            counters.alert_timeouts++;
            counters.valid = false;
            publishSample(counters);
            configured = false;
            (void)gpio_intr_disable(kAlertGpio);
            continue;
        }
        int64_t timestampUs;
        uint32_t edgeCount;
        portENTER_CRITICAL(&alertStateMux);
        timestampUs = latestAlertTimestampUs;
        edgeCount = alertEdgeCount;
        portEXIT_CRITICAL(&alertStateMux);
        const uint32_t edgeDelta = edgeCount - previousEdgeCount;
        if (previousEdgeCount != 0U && edgeDelta > 1U)
            counters.coalesced_alerts += edgeDelta - 1U;
        previousEdgeCount = edgeCount;

        pqc_ina228_snapshot_t next = counters;
        next.online = true;
        next.valid = false;
        next.status_flags = 0;
        next.timestamp_us = timestampUs;
        next.sample_sequence = ++sequence; // attempts, including failed reads
        const int64_t readStartUs = esp_timer_get_time();
        sfe_ina2xx_diag_alrt_reg_t flags = {};
        sfTkError_t rc = sensor.getDiagnosticFlags(flags); // also releases ALERT
        float busV = 0.0f, currentA = 0.0f, powerW = 0.0f;
        if (rc == ksfTkErrOk) rc = sensor.getBusVoltage_V(busV);
        if (rc == ksfTkErrOk) rc = sensor.getCurrent_A(currentA);
        if (rc == ksfTkErrOk) rc = sensor.getPower_W(powerW);
        next.read_duration_us = static_cast<uint32_t>(esp_timer_get_time() - readStartUs);
        next.diagnostic_flags = flags.word;
        if (rc != ksfTkErrOk) { next.i2c_errors++; next.status_flags |= 1U; }
        if (!flags.memStat || !flags.cnvrf || pending != 1U ||
            (previousTimestampUs != 0 && timestampUs <= previousTimestampUs)) {
            next.timing_errors++; next.status_flags |= 2U;
        }
        if (flags.mathOF || busV >= 85.0f ||
            currentA >= 0.16384f / kCalibrationShuntOhms ||
            currentA <= -0.16384f / kCalibrationShuntOhms) {
            next.saturation_errors++; next.status_flags |= 4U;
        }
        // Explicit acquisition-gap threshold, not a claim of achieved rate.
        if (previousTimestampUs != 0 && timestampUs - previousTimestampUs > 10000) {
            next.sample_gaps++; next.status_flags |= 8U;
        }
        previousTimestampUs = timestampUs;
        next.bus_v = busV;
        next.current_a = currentA;
        next.power_w = powerW;
        next.valid = next.status_flags == 0;
        counters = next;
        publishSample(next);

        // SparkFun owns ADC_CONFIG and scaling. Re-arm only AFTER the raw
        // snapshot is retained. This naturally runs at the bus/CPU service rate.
        portENTER_CRITICAL(&alertStateMux);
        const bool pauseAfterSample = pauseRequested;
        portEXIT_CRITICAL(&alertStateMux);
        if (!pauseAfterSample && sensor.triggerNext() != ksfTkErrOk) {
            counters.i2c_errors++;
            counters.valid = false;
            publishSample(counters);
            configured = false;
            (void)gpio_intr_disable(kAlertGpio);
        }
    }
}

} // namespace

extern "C" bool pqc_ina228_sparkfun_is_paused(void)
{
    portENTER_CRITICAL(&alertStateMux);
    const bool paused = acquisitionPaused;
    portEXIT_CRITICAL(&alertStateMux);
    return paused;
}

extern "C" void pqc_ina228_sparkfun_resume(void)
{
    portENTER_CRITICAL(&alertStateMux);
    pauseRequested = false;
    portEXIT_CRITICAL(&alertStateMux);
}

extern "C" bool pqc_ina228_sparkfun_pause(uint32_t timeout_ms)
{
    if (sensorTaskHandle == nullptr) return false;
    portENTER_CRITICAL(&alertStateMux);
    pauseRequested = true;
    portEXIT_CRITICAL(&alertStateMux);
    const TickType_t start = xTaskGetTickCount();
    while (!pqc_ina228_sparkfun_is_paused()) {
        if (xTaskGetTickCount() - start >= pdMS_TO_TICKS(timeout_ms)) {
            pqc_ina228_sparkfun_resume();
            return false;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    return true;
}

extern "C" void pqc_ina228_sparkfun_snapshot(pqc_ina228_snapshot_t *out)
{
    if (out == nullptr)
        return;

    memset(out, 0, sizeof(*out));
    if (snapshotMutex != nullptr &&
        xSemaphoreTake(snapshotMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
        *out = latest;
        xSemaphoreGive(snapshotMutex);
    }
}

extern "C" void pqc_ina228_sparkfun_set_sample_callback(pqc_ina228_sample_callback_t callback)
{
    sampleCallback = callback;
}

extern "C" void pqc_ina228_sparkfun_start(i2c_port_t port)
{
    sensorBus.init(port, kIna228Address);

    snapshotMutex = xSemaphoreCreateMutex();
    configASSERT(snapshotMutex != nullptr);
    configureAlertGpio();

    BaseType_t created = xTaskCreate(sensorTask, "ina228_sparkfun", 6144, nullptr, 8, &sensorTaskHandle);
    configASSERT(created == pdPASS);
}
