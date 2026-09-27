idf_component_register(
    SRCS "main.c" "wifi_time.c" "ina228_sparkfun.cpp" "energy_session.cpp"
    INCLUDE_DIRS "."
    REQUIRES esp_wifi esp_event esp_netif nvs_flash esp_timer esp_app_format driver mqtt json mbedtls sparkfun_ina2xx
)
