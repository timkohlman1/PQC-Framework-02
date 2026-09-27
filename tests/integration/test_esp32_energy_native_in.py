"""Compile and execute maintained C/C++ capture code with SDK/device doubles.

Extracted from commit 7a25e8fc507f23a5346dfa6014087be05fab81bd.
STM32 boundary tests are excluded. These tests establish software behavior
only, not an ESP-IDF target build, GPIO latency, real SHA integrity or ESP32 rate.
"""
import base64
import json
from pathlib import Path
import shutil
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
inline unsigned uxTaskGetStackHighWaterMark(void*){return 9999;}
inline uint32_t ulTaskNotifyTake(int,uint32_t){return 1;}
inline void vTaskNotifyGiveFromISR(void*,int*){}
inline int64_t esp_timer_get_time(){return 100;}
inline void* heap_caps_malloc(size_t n,int){return malloc(n);}
inline void* heap_caps_calloc(size_t n,size_t z,int){return calloc(n,z);}
inline void heap_caps_free(void*p){free(p);}
inline size_t heap_caps_get_total_size(int){return 8*1024*1024;}
inline size_t heap_caps_get_free_size(int){return 7800000;}
inline size_t heap_caps_get_largest_free_block(int){return 7500000;}
inline void esp_fill_random(void*p,size_t n){memset(p,0x12,n);}
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
struct cJSON {char*valuestring;double valuedouble;};
cJSON* cJSON_Parse(const char*); cJSON* cJSON_GetObjectItemCaseSensitive(cJSON*,const char*);
bool cJSON_IsString(cJSON*); bool cJSON_IsNumber(cJSON*);void cJSON_Delete(cJSON*);
// Crypto double tests framing/flow only; real SHA integrity is tested by the
// host collector tests. This is deliberately not presented as a crypto test.
struct mbedtls_sha256_context {};
inline void mbedtls_sha256_init(mbedtls_sha256_context*){}
inline void mbedtls_sha256_free(mbedtls_sha256_context*){}
inline int mbedtls_sha256_starts(mbedtls_sha256_context*,int){return 0;}
inline int mbedtls_sha256_update(mbedtls_sha256_context*,const unsigned char*,size_t){return 0;}
inline int mbedtls_sha256_finish(mbedtls_sha256_context*,unsigned char*p){memset(p,0,32);return 0;}
// Base64 transport double, independently decoded by Python below.
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
    for name in ("cJSON.h", "esp_app_desc.h", "esp_random.h", "esp_heap_caps.h", "esp_log.h",
                 "esp_timer.h", "mqtt_client.h", "sdkconfig.h", "mbedtls/sha256.h", "mbedtls/base64.h",
                 "driver/gpio.h", "driver/i2c.h", "freertos/FreeRTOS.h", "freertos/queue.h",
                 "freertos/semphr.h", "freertos/task.h"):
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('#include "sdk.h"\n')
    return tmp_path


@pytest.mark.parametrize("uint32_model", ["native", "unsigned_long"])
def test_esp32_actual_ring_intervals_and_bounded_publication(sdk, uint32_model):
    cxx = shutil.which("g++")
    if cxx is None:
        pytest.skip("native C++ compiler unavailable")
    main = ROOT / "instruments/esp32_ina228/main"
    # Model the Xtensa uint32_t underlying type as well as the host type.
    # Host unsigned long may be 64-bit: this checks printf type portability,
    # not Xtensa layout, overflow behavior, or target execution.
    format_preamble = ""
    if uint32_model == "unsigned_long":
        modeled_main = sdk / "modeled_main"
        modeled_main.mkdir()
        for name in ("energy_session.cpp", "energy_session.h", "ina228_sparkfun.h"):
            (modeled_main / name).write_text(
                (main / name).read_text().replace("uint32_t", "unsigned long")
            )
        sdk_header = sdk / "sdk.h"
        sdk_header.write_text(sdk_header.read_text().replace("uint32_t", "unsigned long"))
        main = modeled_main
        format_preamble = '#include <inttypes.h>\n#undef PRIu32\n#define PRIu32 "lu"\n'
    harness = sdk / "session.cpp"
    harness_source = r'''
#include "sdk.h"
#include "energy_session.cpp"
#include <stdio.h>
int pinLevel=0,lastMessage=0;
std::vector<std::string> topics,payloads;
bool paused=false,pauseAllowed=true;int pauseCalls=0,resumeCalls=0;
extern "C" bool pqc_ina228_sparkfun_is_paused(){return paused;}
extern "C" bool pqc_ina228_sparkfun_pause(uint32_t){++pauseCalls;paused=pauseAllowed;return paused;}
extern "C" void pqc_ina228_sparkfun_resume(){++resumeCalls;paused=false;}
extern "C" void pqc_ina228_sparkfun_snapshot(pqc_ina228_snapshot_t*out){*out={};out->paused=paused;}
int main(){
 stateMutex=(void*)1; mqttClient=(void*)1; publishAckQueue=(void*)1;
 ringCapacity=16; sampleRing=new energy_sample_record_t[ringCapacity]();
 intervals=new energy_interval_record_t[kMaxIntervals]();
 state.mqttConnected=true; strcpy(sessionId,"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
 recordAssociationToken("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",32);
 auto sample=[](int i){pqc_ina228_snapshot_t s={};s.online=s.valid=true;
  s.sample_sequence=i;s.timestamp_us=1000*i;s.bus_v=5;s.current_a=.1;s.power_w=.5;
  s.diagnostic_flags=3;storeSensorSample(&s);};
 sample(1);recordSyncEdge(true,1500);sample(2);sample(3);recordSyncEdge(false,2500);sample(4);
 assert(resolveIntervalSamples(intervals[0]));
 assert(intervals[0].start_sample_sequence==1 && intervals[0].end_sample_sequence==3);
 // Wrong token never takes the sole unlabeled/old interval.
 assert(!publishClaimedIntervals("run-1","cccccccccccccccccccccccccccccccc",1));
 assert(!intervals[0].claimed);
 // A second interval in the same boot, selected in the SAME post-run collect.
 SyncEdgeEvent captured={}; captured.associationValid=true;
 strcpy(captured.token,"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb");
 recordSyncEdge(true,4200,&captured);sample(5);sample(6);recordSyncEdge(false,5500);sample(7);
 assert(intervals[1].start_timestamp_us==4200);
 topics.clear();payloads.clear();
 physicalIntervalActive=true;
 assert(!publishClaimedIntervals("run-1","bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",1));
 physicalIntervalActive=false;topics.clear();payloads.clear();
 assert(publishClaimedIntervals("run-1","bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",2));
 assert(intervals[0].claimed);
 assert(!paused && pauseCalls==resumeCalls && !state.publishing);
 for(size_t i=0;i<payloads.size();i++) puts(payloads[i].c_str());
 // An active physical edge prevents each chunk, not only initial collection.
 TracePublisher p("run-1");assert(p.append("small"));pinLevel=1;
 assert(!p.publishChunk());pinLevel=0;
 // Every failure path resumes acquisition, including PUBACK and pause failure.
 intervals[0].claimed=intervals[1].claimed=false;
 ackEnabled=false;
 assert(!publishClaimedIntervals("run-1","bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",2));
 assert(!paused && !state.publishing && !intervals[0].claimed);
 ackEnabled=true;pauseAllowed=false;
 assert(!publishClaimedIntervals("run-1","bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",2));
 assert(!paused && !state.publishing);pauseAllowed=true;
 collectionCancelled=true;
 assert(!publishClaimedIntervals("run-1","bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",2));
 assert(!paused && !state.publishing);collectionCancelled=false;
 // Ring wrap invalidates an old descriptor, with no silent truncation.
 for(int i=8;i<=25;i++) sample(i);
 assert(!resolveIntervalSamples(intervals[1]));
 assert(!publishClaimedIntervals("run-1","bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",2));
 assert(payloads.back().find("capacity_exceeded")!=std::string::npos);
 assert(!paused && pauseCalls==resumeCalls);
 // Prior runs' capacity failures cannot contaminate a new token.
 recordAssociationToken("cccccccccccccccccccccccccccccccc",32);
 recordSyncEdge(true,25500);sample(26);sample(27);recordSyncEdge(false,26500);sample(28);
 assert(publishClaimedIntervals("run-2","cccccccccccccccccccccccccccccccc",1));
 assert(!paused && !state.publishing);
 collectionStartedUs=-kCollectionLimitUs;TracePublisher expired("run-3");
 assert(expired.append("small"));assert(!expired.publishChunk());
 return 0;
}
'''
    if uint32_model == "unsigned_long":
        harness_source = harness_source.replace("uint32_t", "unsigned long")
    harness.write_text(format_preamble + harness_source)
    exe = sdk / "session"
    run([cxx, "-std=c++17", "-Wformat=2", "-Werror=format", "-ffunction-sections", "-fdata-sections", "-I", str(sdk),
         "-I", str(main), str(harness), "-Wl,--gc-sections", "-o", str(exe)])
    messages = [json.loads(line) for line in run([str(exe)]).splitlines()]
    chunks = [m for m in messages if m["type"] == "chunk"]
    logical = b"".join(base64.b64decode(m["data_b64"], validate=True) for m in chunks)
    records = [json.loads(line) for line in logical.splitlines()]
    assert records[0]["schema"] == 3
    assert records[1]["e0_us"] == 1500 and records[1]["e1_us"] == 2500
    assert [r[4] for r in records[2:5]] == [-500, 500, 1500]
    assert records[5]["interval_index"] == 1
    assert messages[-1]["sample_count"] == 6
    assert messages[-1]["interval_count"] == 2
    assert messages[-1]["logical_bytes"] == len(logical)
    assert messages[-1]["record_count"] == len(records)
    assert messages[-1]["chunk_count"] == len(chunks)


def test_sensor_compiles_against_pinned_sparkfun_api(sdk):
    cxx = shutil.which("g++")
    if cxx is None:
        pytest.skip("native C++ compiler unavailable")
    instrument = ROOT / "instruments/esp32_ina228"
    run([cxx, "-std=c++17", "-fsyntax-only", "-I", str(sdk),
         "-I", str(instrument / "lib/SparkFun_INA2XX_Arduino_Library/src"),
         "-I", str(instrument / "lib/SparkFun_Toolkit/src"),
         str(instrument / "main/ina228_sparkfun.cpp")])
