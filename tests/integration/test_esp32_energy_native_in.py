"""Compile maintained ESP32 energy code with SDK/device doubles.

These tests establish host-side source/ABI behaviour only. They are not an
ESP-IDF target build, GPIO-latency measurement, real MQTT test, or hardware
sample-rate result.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.integration


def run(command, cwd=None):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


SDK = r'''
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <vector>
#include <string>
using TickType_t=uint32_t; using UBaseType_t=unsigned; using BaseType_t=int;
using SemaphoreHandle_t=void*; using QueueHandle_t=void*; using TaskHandle_t=void*;
using portMUX_TYPE=int; using esp_err_t=int; using esp_event_base_t=void*;
using gpio_num_t=int; using i2c_port_t=int; using i2c_cmd_handle_t=void*;
#define pdTRUE 1
#define pdFALSE 0
#define pdPASS 1
#define portMAX_DELAY 0xffffffff
#define portMUX_INITIALIZER_UNLOCKED 0
#define pdMS_TO_TICKS(x) (x)
#define IRAM_ATTR
#define ESP_OK 0
#define ESP_EVENT_ANY_ID -1
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
#define ESP_LOGE(...) ((void)0)
#define ESP_LOGD(...) ((void)0)
#define ESP_ERROR_CHECK(x) assert((x)==0)
#define configASSERT(x) assert(x)
#define portENTER_CRITICAL(x) ((void)0)
#define portEXIT_CRITICAL(x) ((void)0)
#define portENTER_CRITICAL_ISR(x) ((void)0)
#define portEXIT_CRITICAL_ISR(x) ((void)0)
#define portYIELD_FROM_ISR() ((void)0)
#define MALLOC_CAP_SPIRAM 1
#define MALLOC_CAP_8BIT 2
#define GPIO_MODE_INPUT 1
#define GPIO_PULLUP_ENABLE 1
#define GPIO_PULLUP_DISABLE 0
#define GPIO_PULLDOWN_ENABLE 1
#define GPIO_PULLDOWN_DISABLE 0
#define GPIO_INTR_NEGEDGE 1
#define GPIO_INTR_ANYEDGE 2
#define I2C_NUM_0 0
#define I2C_MASTER_WRITE 0
#define I2C_MASTER_READ 1
#define I2C_MASTER_LAST_NACK 2
#define I2C_LINK_RECOMMENDED_SIZE(n) (128*(n)+128)
struct gpio_config_t {uint64_t pin_bit_mask;int mode,pull_up_en,pull_down_en,intr_type;};
inline int gpio_config(gpio_config_t*){return 0;}
extern int pinLevel;
inline int gpio_get_level(int){return pinLevel;}
inline int gpio_install_isr_service(int){return 0;}
inline int gpio_isr_handler_add(int,void(*)(void*),void*){return 0;}
inline int gpio_intr_disable(int){return 0;}
inline int gpio_intr_enable(int){return 0;}
inline int xSemaphoreTake(void*,uint32_t){return 1;}
inline int xSemaphoreGive(void*){return 1;}
inline void* xSemaphoreCreateMutex(){return (void*)1;}
inline void* xQueueCreate(unsigned,size_t){return (void*)1;}
inline int xQueueReset(void*){return 1;}
extern int lastMessage;
inline bool ackEnabled=true;
inline int xQueueReceive(void*,void*p,uint32_t){*(int*)p=lastMessage;return ackEnabled ? 1 : 0;}
inline int xQueueSend(void*,const void*,uint32_t){return 1;}
inline int xQueueSendFromISR(void*,const void*,int*){return 1;}
inline int xTaskCreate(void(*)(void*),const char*,int,void*,int,void**){return 1;}
inline void vTaskDelay(uint32_t){}
inline uint32_t xTaskGetTickCount(){static uint32_t tick=0; return tick++;}
inline uint32_t ulTaskNotifyTake(int,uint32_t){return 1;}
inline void vTaskNotifyGiveFromISR(void*,int*){}
inline int64_t esp_timer_get_time(){return 100;}
inline uint32_t esp_random(){static uint32_t n=0x12345678; return ++n;}
inline void* heap_caps_malloc(size_t n,int){return malloc(n);}
inline void* heap_caps_calloc(size_t n,size_t z,int){return calloc(n,z);}
inline void heap_caps_free(void*p){free(p);}
inline size_t heap_caps_get_total_size(int){return 8*1024*1024;}
inline size_t heap_caps_get_free_size(int){return 7800000;}
inline size_t heap_caps_get_largest_free_block(int){return 7500000;}
inline const char* esp_err_to_name(int){return "test";}
inline size_t strlcpy(char*d,const char*s,size_t n){size_t l=strlen(s);if(n){strncpy(d,s,n-1);d[n-1]=0;}return l;}
struct esp_app_desc_t {char project_name[32];char version[32];uint8_t app_elf_sha256[32];};
inline const esp_app_desc_t* esp_app_get_description(){static esp_app_desc_t a={};return &a;}
using esp_mqtt_client_handle_t=void*;
enum esp_mqtt_event_id_t {MQTT_EVENT_CONNECTED,MQTT_EVENT_DISCONNECTED,MQTT_EVENT_PUBLISHED,MQTT_EVENT_DATA};
struct event {int msg_id,topic_len,data_len,total_data_len,current_data_offset;char*topic;char*data;};
using esp_mqtt_event_handle_t=event*;
struct esp_mqtt_client_config_t {
 struct {struct {const char*uri;} address;} broker;
 struct {const char*client_id;} credentials;
 struct {int reconnect_timeout_ms; int timeout_ms;} network;
 struct {int size; int out_size;} buffer;
 struct {int stack_size;} task;
};
extern std::vector<std::string> topics,payloads;
inline int esp_mqtt_client_publish(void*,const char*t,const char*p,int,int,int){topics.emplace_back(t);payloads.emplace_back(p);return ++lastMessage;}
inline int esp_mqtt_client_subscribe(void*,const char*,int){return 0;}
inline void* esp_mqtt_client_init(esp_mqtt_client_config_t*){return (void*)1;}
inline int esp_mqtt_client_register_event(void*,esp_mqtt_event_id_t,void(*)(void*,void*,int32_t,void*),void*){return 0;}
inline int esp_mqtt_client_start(void*){return 0;}
struct mbedtls_sha256_context {};
inline void mbedtls_sha256_init(mbedtls_sha256_context*){}
inline void mbedtls_sha256_free(mbedtls_sha256_context*){}
inline int mbedtls_sha256_starts(mbedtls_sha256_context*,int){return 0;}
inline int mbedtls_sha256_update(mbedtls_sha256_context*,const unsigned char*,size_t){return 0;}
inline int mbedtls_sha256_finish(mbedtls_sha256_context*,unsigned char*p){memset(p,0,32);return 0;}
inline int mbedtls_base64_encode(unsigned char*d,size_t cap,size_t*out,const unsigned char*s,size_t n){
 static const char a[]="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
 *out=4*((n+2)/3); if(cap<*out+1) return -1;
 size_t j=0;for(size_t i=0;i<n;i+=3){unsigned v=s[i]<<16;
 if(i+1<n)v|=s[i+1]<<8;if(i+2<n)v|=s[i+2];
 d[j++]=a[v>>18];d[j++]=a[(v>>12)&63];d[j++]=i+1<n?a[(v>>6)&63]:'=';d[j++]=i+2<n?a[v&63]:'=';}
 d[j]=0;return 0;
}
inline void* i2c_cmd_link_create_static(uint8_t*p,uint32_t){return p;}
inline void i2c_cmd_link_delete_static(void*){}
inline int i2c_master_start(void*){return 0;}
inline int i2c_master_stop(void*){return 0;}
inline int i2c_master_write_byte(void*,uint8_t,bool){return 0;}
inline int i2c_master_write(void*,const uint8_t*,size_t,bool){return 0;}
inline int i2c_master_read(void*,uint8_t*,size_t,int){return 0;}
inline int i2c_master_cmd_begin(int,void*,uint32_t){return 0;}
inline int i2c_master_write_to_device(int,uint8_t,const uint8_t*,size_t,uint32_t){return 0;}
inline int i2c_master_read_from_device(int,uint8_t,uint8_t*,size_t,uint32_t){return 0;}
'''


@pytest.fixture
def sdk(tmp_path):
    (tmp_path / "sdk.h").write_text(SDK)
    for name in (
        "esp_app_desc.h", "esp_err.h", "esp_random.h", "esp_heap_caps.h", "esp_log.h", "esp_timer.h",
        "mqtt_client.h", "sdkconfig.h", "mbedtls/sha256.h", "mbedtls/base64.h",
        "driver/gpio.h", "driver/i2c.h", "freertos/FreeRTOS.h", "freertos/queue.h",
        "freertos/semphr.h", "freertos/task.h",
    ):
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('#include "sdk.h"\n')
    return tmp_path


def test_esp32_actual_recorder_emits_packed_20_byte_capture(sdk):
    cxx = shutil.which("g++")
    if cxx is None:
        pytest.skip("native C++ compiler unavailable")
    main = ROOT / "instruments/esp32_ina228/main"
    harness = sdk / "session.cpp"
    harness.write_text(r'''
#include "sdk.h"
#include "energy_session.cpp"
#include <stdio.h>
int pinLevel=0,lastMessage=0;
std::vector<std::string> topics,payloads;
extern "C" bool pqc_ina228_sparkfun_is_paused(){return false;}
extern "C" bool pqc_ina228_sparkfun_pause(uint32_t){return true;}
extern "C" void pqc_ina228_sparkfun_resume(){}
extern "C" void pqc_ina228_sparkfun_snapshot(pqc_ina228_snapshot_t*out){*out={};}
extern "C" void pqc_ina228_sparkfun_set_sample_callback(pqc_ina228_sample_callback_t){}
extern "C" void pqc_ina228_sparkfun_start(i2c_port_t){}
int main(){
 stateMutex=(void*)1; mqttClient=(void*)1; publishAckQueue=(void*)1;
 ringCapacity=1000; sampleRing=new energy_sample_record_t[ringCapacity]();
 state.mqtt_connected=true; captureGeneration=1; physicalHigh=false;
 for(int64_t t=1000000;t<=5000000;t+=10000){
   pqc_ina228_snapshot_t s={};s.online=s.valid=true;s.timestamp_us=t;
   s.bus_v=5.0;s.current_a=.1;s.power_w=.5;storeSensorSample(&s);
 }
 CaptureJob job={};strcpy(job.capture_id,"0123456789abcdef");job.generation=1;
 job.e0_us=4000000;job.e1_us=5000000;
 assert(prepareCaptureRange(&job));
 assert(publishCapture(job));
 for(size_t i=0;i<payloads.size();i++){
   printf("%s\t%s\n",topics[i].c_str(),payloads[i].c_str());
 }
 return 0;
}
''')
    exe = sdk / "session"
    run([
        cxx, "-std=c++17", "-Wformat=2", "-Werror=format", "-ffunction-sections", "-fdata-sections",
        "-I", str(sdk), "-I", str(main), str(harness), "-Wl,--gc-sections", "-o", str(exe),
    ])
    messages = []
    for line in run([str(exe)]).splitlines():
        topic, payload = line.split("\t", 1)
        messages.append((topic, json.loads(payload)))
    chunks = [obj for topic, obj in messages if topic.endswith("/chunk")]
    completions = [obj for topic, obj in messages if topic.endswith("/complete")]
    assert chunks and len(completions) == 1
    raw = b"".join(base64.b64decode(obj["data_b64"], validate=True) for obj in chunks)
    assert len(raw) == 401 * 20
    first = struct.unpack_from("<qfff", raw, 0)
    last = struct.unpack_from("<qfff", raw, len(raw) - 20)
    assert first[0] == 1_000_000 and last[0] == 5_000_000
    assert first[1:] == pytest.approx((5.0, 0.1, 0.5))
    complete = completions[0]
    assert complete["schema"] == 1
    assert complete["capture_id"] == "0123456789abcdef"
    assert complete["sample_record_bytes"] == 20
    assert complete["sample_count"] == 401
    assert complete["pretrigger_us"] == 3_000_000
    assert complete["pretrigger_complete"] is True
    assert complete["sample_fields"] == ["timestamp_us", "bus_v", "current_a", "power_w"]
    assert complete["chunk_count"] == len(chunks)
    assert complete["logical_bytes"] == len(raw)
    assert complete["firmware_sha256"] == "0" * 64


def test_falling_edge_pauses_acquisition_before_queuing_frozen_capture(sdk):
    cxx = shutil.which("g++")
    if cxx is None:
        pytest.skip("native C++ compiler unavailable")
    main = ROOT / "instruments/esp32_ina228/main"
    harness = sdk / "pause.cpp"
    harness.write_text(r'''
#include "sdk.h"
#include "energy_session.cpp"
int pinLevel=0,lastMessage=0;
std::vector<std::string> topics,payloads;
static int pauseCalls=0,resumeCalls=0;
static bool paused=false;
extern "C" bool pqc_ina228_sparkfun_is_paused(){return paused;}
extern "C" bool pqc_ina228_sparkfun_pause(uint32_t){pauseCalls++;paused=true;return true;}
extern "C" void pqc_ina228_sparkfun_resume(){resumeCalls++;paused=false;}
extern "C" void pqc_ina228_sparkfun_snapshot(pqc_ina228_snapshot_t*out){*out={};out->online=true;out->paused=paused;}
extern "C" void pqc_ina228_sparkfun_set_sample_callback(pqc_ina228_sample_callback_t){}
extern "C" void pqc_ina228_sparkfun_start(i2c_port_t){}
static void sample(int64_t t){
 pqc_ina228_snapshot_t s={};s.online=s.valid=true;s.timestamp_us=t;
 s.bus_v=5.0;s.current_a=.1;s.power_w=.5;storeSensorSample(&s);
}
int main(){
 stateMutex=(void*)1; captureQueue=(void*)1;
 ringCapacity=1000; sampleRing=new energy_sample_record_t[ringCapacity]();
 for(int64_t t=1000000;t<=5000000;t+=10000) sample(t);
 captureGeneration=1; physicalHigh=false; state.capture_active=true;
 strcpy(state.active_capture_id,"0123456789abcdef");
 activeE0Us=4000000;
 processFalling(5000000);
 assert(pauseCalls==1);
 assert(paused);
 assert(state.publishing);
 assert(!state.capture_active);
 assert(ringCount==401);
 assert(resumeCalls==0);
 return 0;
}
''')
    exe = sdk / "pause"
    run([
        cxx, "-std=c++17", "-Wformat=2", "-Werror=format", "-ffunction-sections", "-fdata-sections",
        "-I", str(sdk), "-I", str(main), str(harness), "-Wl,--gc-sections", "-o", str(exe),
    ])
    run([str(exe)])


def test_publication_cleanup_resets_ring_and_resumes_acquisition(sdk):
    cxx = shutil.which("g++")
    if cxx is None:
        pytest.skip("native C++ compiler unavailable")
    main = ROOT / "instruments/esp32_ina228/main"
    harness = sdk / "resume.cpp"
    harness.write_text(r'''
#include "sdk.h"
#include "energy_session.cpp"
int pinLevel=0,lastMessage=0;
std::vector<std::string> topics,payloads;
static int resumeCalls=0;
extern "C" bool pqc_ina228_sparkfun_is_paused(){return true;}
extern "C" bool pqc_ina228_sparkfun_pause(uint32_t){return true;}
extern "C" void pqc_ina228_sparkfun_resume(){resumeCalls++;}
extern "C" void pqc_ina228_sparkfun_snapshot(pqc_ina228_snapshot_t*out){*out={};}
extern "C" void pqc_ina228_sparkfun_set_sample_callback(pqc_ina228_sample_callback_t){}
extern "C" void pqc_ina228_sparkfun_start(i2c_port_t){}
int main(){
 stateMutex=(void*)1; ringCapacity=1000; sampleRing=new energy_sample_record_t[ringCapacity]();
 ringCount=321; ringWriteIndex=654; ringOverflowed=true;
 resumeAfterPublication();
 assert(ringCount==0);
 assert(ringWriteIndex==0);
 assert(!ringOverflowed);
 assert(resumeCalls==1);
 return 0;
}
''')
    exe = sdk / "resume"
    run([
        cxx, "-std=c++17", "-Wformat=2", "-Werror=format", "-ffunction-sections", "-fdata-sections",
        "-I", str(sdk), "-I", str(main), str(harness), "-Wl,--gc-sections", "-o", str(exe),
    ])
    run([str(exe)])


def test_sensor_compiles_against_pinned_sparkfun_api(sdk):
    cxx = shutil.which("g++")
    if cxx is None:
        pytest.skip("native C++ compiler unavailable")
    instrument = ROOT / "instruments/esp32_ina228"
    run([
        cxx, "-std=c++17", "-fsyntax-only", "-I", str(sdk),
        "-I", str(instrument / "lib/SparkFun_INA2XX_Arduino_Library/src"),
        "-I", str(instrument / "lib/SparkFun_Toolkit/src"),
        str(instrument / "main/ina228_sparkfun.cpp"),
    ])
