#include "wifi_time.h"

#include <string.h>
#include <stdlib.h>
#include "esp_err.h"
#include <sys/time.h>
#include <time.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/portmacro.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

static const char *TAG = "pqc_wifi_time";
static portMUX_TYPE status_mux = portMUX_INITIALIZER_UNLOCKED;
static pqc_wifi_time_snapshot_t status;
static bool sntp_started;

void pqc_wifi_time_snapshot(pqc_wifi_time_snapshot_t *out)
{
    if (out == NULL) return;
    taskENTER_CRITICAL(&status_mux);
    *out = status;
    taskEXIT_CRITICAL(&status_mux);
}

static void on_time_sync(struct timeval *tv)
{
    (void)tv;
    taskENTER_CRITICAL(&status_mux);
    status.time_synced = true;
    status.last_sync_monotonic_us = esp_timer_get_time();
    taskEXIT_CRITICAL(&status_mux);
    ESP_LOGI(TAG, "Network clock synchronized");
}

static void on_wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        taskENTER_CRITICAL(&status_mux);
        status.connected = false;
        status.ip[0] = '\0';
        taskEXIT_CRITICAL(&status_mux);
        ESP_LOGW(TAG, "Wi-Fi disconnected; reconnecting");
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *event = (const ip_event_got_ip_t *)data;
        char address[16];
        esp_ip4addr_ntoa(&event->ip_info.ip, address, sizeof(address));
        taskENTER_CRITICAL(&status_mux);
        status.connected = true;
        strlcpy(status.ip, address, sizeof(status.ip));
        taskEXIT_CRITICAL(&status_mux);
        ESP_LOGI(TAG, "Wi-Fi connected; IP %s", address);
        if (!sntp_started) {
            esp_sntp_config_t ntp = ESP_NETIF_SNTP_DEFAULT_CONFIG(CONFIG_PQC_NTP_SERVER);
            ntp.sync_cb = on_time_sync;
            esp_err_t err = esp_netif_sntp_init(&ntp);
            if (err == ESP_OK) {
                sntp_started = true;
            } else {
                ESP_LOGE(TAG, "SNTP init failed: %s", esp_err_to_name(err));
            }
        }
    }
}

void pqc_wifi_time_start(void)
{
    /* Credentials reside in the local, ignored sdkconfig only. */
    const char *ssid = CONFIG_PQC_WIFI_SSID;
    const char *password = CONFIG_PQC_WIFI_PASSWORD;
    setenv("TZ", CONFIG_PQC_TIMEZONE, 1);
    tzset();
    if (ssid[0] == '\0') {
        ESP_LOGW(TAG, "Wi-Fi is not configured; use menuconfig to set a local SSID");
        return;
    }
    if (strlen(ssid) > 32 || strlen(password) > 63) {
        ESP_LOGE(TAG, "Wi-Fi SSID/password exceeds supported length");
        return;
    }
    taskENTER_CRITICAL(&status_mux);
    status.configured = true;
    taskEXIT_CRITICAL(&status_mux);

    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        /* NVS contains only instrument networking state. Never erase NVS during a campaign. */
        ESP_LOGE(TAG, "NVS unavailable (%s); manual maintenance required", esp_err_to_name(err));
        return;
    }
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "NVS init failed: %s", esp_err_to_name(err));
        return;
    }
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_t *station = esp_netif_create_default_wifi_sta();
    ESP_ERROR_CHECK(station == NULL ? ESP_FAIL : ESP_OK);
    wifi_init_config_t wifi_init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&wifi_init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_wifi_event, NULL));
    wifi_config_t wifi_config = {0};
    strlcpy((char *)wifi_config.sta.ssid, ssid, sizeof(wifi_config.sta.ssid));
    strlcpy((char *)wifi_config.sta.password, password, sizeof(wifi_config.sta.password));
    wifi_config.sta.threshold.authmode = WIFI_AUTH_OPEN;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    ESP_ERROR_CHECK(esp_wifi_start());
}
