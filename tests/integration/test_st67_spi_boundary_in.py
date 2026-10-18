"""Execute the maintained C driver with deterministic GPIO/RTOS/HAL boundaries.

These are native fault-injection checks, not physical ST67 qualification.
"""
from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[2]
BUS = ROOT / 'Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_bus'
pytestmark = pytest.mark.integration

RTOS = r'''
#ifndef FAKE_RTOS_H
#define FAKE_RTOS_H
#include <stdint.h>
#include <stdlib.h>
#include <assert.h>
typedef uint32_t TickType_t, EventBits_t;
typedef int BaseType_t;
typedef void *TaskHandle_t, *QueueHandle_t, *EventGroupHandle_t, *SemaphoreHandle_t;
#define pdTRUE 1
#define pdFALSE 0
#define pdMS_TO_TICKS(x) (x)
#define portMAX_DELAY UINT32_MAX
#define tskKERNEL_VERSION_MAJOR 11
#define taskSCHEDULER_NOT_STARTED 0
#define taskENTER_CRITICAL() ((void)0)
#define taskEXIT_CRITICAL() ((void)0)
#define portYIELD_FROM_ISR(x) ((void)(x))
void *pvPortMalloc(size_t);
void vPortFree(void *);
TickType_t xTaskGetTickCount(void), xTaskGetTickCountFromISR(void);
int xTaskGetSchedulerState(void), xPortIsInsideInterrupt(void);
void vTaskDelay(TickType_t), vTaskDelete(TaskHandle_t);
int xTaskCreate(void (*)(void *),const char *,uint32_t,void *,int,TaskHandle_t *);
uint32_t xPortGetFreeHeapSize(void), xPortGetMinimumEverFreeHeapSize(void), uxTaskGetStackHighWaterMark(void *);
EventGroupHandle_t xEventGroupCreate(void);
void vEventGroupDelete(EventGroupHandle_t);
EventBits_t xEventGroupClearBits(EventGroupHandle_t,EventBits_t), xEventGroupGetBits(EventGroupHandle_t);
EventBits_t xEventGroupSetBits(EventGroupHandle_t,EventBits_t);
int xEventGroupSetBitsFromISR(EventGroupHandle_t,EventBits_t,int *);
EventBits_t xEventGroupWaitBits(EventGroupHandle_t,EventBits_t,int,int,TickType_t);
QueueHandle_t xQueueCreate(uint32_t,uint32_t);
void vQueueDelete(QueueHandle_t);
int xQueueReceive(QueueHandle_t,void *,TickType_t), xQueueSend(QueueHandle_t,const void *,TickType_t);
uint32_t uxQueueMessagesWaiting(QueueHandle_t);
SemaphoreHandle_t xSemaphoreCreateBinary(void);
void vSemaphoreDelete(SemaphoreHandle_t);
int xSemaphoreTake(SemaphoreHandle_t,TickType_t), xSemaphoreGive(SemaphoreHandle_t), xSemaphoreGiveFromISR(SemaphoreHandle_t,int *);
#endif
'''

def headers(tmp):
    for name in ('FreeRTOS.h', 'task.h', 'queue.h', 'semphr.h', 'event_groups.h'):
        (tmp/name).write_text(RTOS)
    (tmp/'logging.h').write_text('#define LogError(...) ((void)0)\n#define LogInfo(...) ((void)0)\n')
    (tmp/'stm32l4xx.h').write_text('')
    (tmp/'w61_default_config.h').write_text('#define W61_MAX_SPI_XFER 1600\n')


def compile_run(tmp, source, modes):
    path=tmp/'harness.c'; path.write_text(source)
    exe=tmp/'exercise'
    result=subprocess.run(['gcc','-std=c11','-Wall','-Werror=implicit-function-declaration',
        '-ffunction-sections','-fdata-sections','-fsanitize=undefined',
        '-I'+str(tmp),'-I'+str(BUS),str(path),'-Wl,--gc-sections','-o',str(exe)],
        capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    for mode in modes:
        subprocess.run([str(exe),str(mode)],check=True,capture_output=True,text=True,timeout=5)


def test_header_ack_requires_live_low_and_bounded_recovery(tmp_path):
    headers(tmp_path)
    source = '#include "'+str(BUS/'spi_iface.c')+'"\n'+r'''
#include <assert.h>
static TickType_t tick, start;
static int mode, waits, cs_asserts;
TickType_t xTaskGetTickCount(void) { return tick; }
void vTaskDelay(TickType_t t) { tick+=t; }
void *pvPortMalloc(size_t n) { return malloc(n); }
void vPortFree(void *p) { free(p); }
uint32_t uxQueueMessagesWaiting(QueueHandle_t q) { return 0; }
uint32_t xPortGetFreeHeapSize(void) { return 10000; }
uint32_t xPortGetMinimumEverFreeHeapSize(void) { return 10000; }
uint32_t uxTaskGetStackHighWaterMark(void *p) { return 1000; }
int xSemaphoreTake(SemaphoreHandle_t s,TickType_t t) { return 0; }
EventBits_t xEventGroupClearBits(EventGroupHandle_t e,EventBits_t b) { return 0; }
EventBits_t xEventGroupGetBits(EventGroupHandle_t e) { return 0; }
EventBits_t xEventGroupWaitBits(EventGroupHandle_t e,EventBits_t b,int clear,int all,TickType_t t) {
    assert(++waits<12); /* Also catches the old unbounded ACK loop. */
    if(mode==1 || mode==2 || mode==4) {
        if(waits==1) { tick+=1; return SPI_EVT_HDR_ACKED; } /* deferred old edge */
    }
    tick+=t; return 0; /* no ISR required when GPIO eventually goes low */
}
int xQueueReceive(QueueHandle_t q,void *p,TickType_t t) { return pdFALSE; }
int xQueueSend(QueueHandle_t q,const void *p,TickType_t t) { assert(0); return 0; }
int32_t spi_port_is_ready(void) {
    if(mode==0) return 0; /* ACK already happened, event not yet delivered */
    if(mode==1 || mode==4) return (TickType_t)(tick-start)<40;
    return 1; /* stuck high, including repeated stale events */
}
int32_t spi_port_set_cs(int32_t state) { if(state) cs_asserts++; return 0; }
int32_t spi_port_get_diagnostics(spi_port_diagnostics_t *d) { memset(d,0,sizeof(*d)); return 0; }
int32_t spi_port_abort_transfer(void) { assert(0); return -1; }
int32_t spi_port_transfer(void *tx,void *rx,uint16_t len,uint32_t timeout) {
    memset(rx,0,len); SPI_HEADER_INIT((struct spi_header *)rx,0,0); return 0;
}
int32_t spi_port_transfer_dma(void *tx,void *rx,uint16_t len) { assert(0); return -1; }
void *spi_port_memcpy(void *d,const void *s,unsigned n) { return memcpy(d,s,n); }
int main(int argc,char **argv) {
    mode=atoi(argv[1]); tick=start=(mode==4 ? UINT32_MAX-10 : 100);
    struct spi_xfer_engine e={0}; e.event=(void *)1; e.hw_xfer_done=(void *)2;
    int ret=spi_xfer_one(&e,NULL,0);
    if(mode==0 || mode==1 || mode==4) {
        assert(ret==0); assert(spi_port_is_ready()==0);
        assert(!e.boundary_unconfirmed); assert(!e.stat.wait_hdr_ack_timeouts);
        assert(e.stat.stale_hdr_ack_events==(mode!=0));
    } else {
        assert(ret<0); assert(e.stat.wait_hdr_ack_timeouts==1);
        assert((TickType_t)(tick-start)==200); /* 100 ACK + 100 recovery */
        assert(e.boundary_unconfirmed);
        assert(spi_do_xfer(&e,0)<0); assert(cs_asserts==0);
    }
    return 0;
}
'''
    compile_run(tmp_path,source,range(5))


def test_port_records_synchronous_and_callback_outcomes(tmp_path):
    headers(tmp_path)
    (tmp_path/'pqc_activity_trace.h').write_text('#define PQC_ActivitySPI(x) ((void)0)\n#define PQC_ActivityEvent(x,y) ((void)0)\n')
    (tmp_path/'bsp_conf.h').write_text('#define NCP_SPI_HANDLE fake_spi\n')
    (tmp_path/'main.h').write_text(r'''
#ifndef FAKE_MAIN_H
#define FAKE_MAIN_H
#include <stdint.h>
#define HAL_SPI_STATE_RESET 0
#define HAL_SPI_STATE_READY 1
#define GPIO_PIN_SET 1
#define GPIO_PIN_RESET 0
#define SPI_RDY_GPIO_Port 0
#define SPI_RDY_Pin 1
#define SPI_CS_GPIO_Port 0
#define SPI_CS_Pin 2
#define CHIP_EN_GPIO_Port 0
#define CHIP_EN_Pin 3
#define assert_param(x) assert(x)
typedef enum {HAL_OK, HAL_ERROR, HAL_BUSY, HAL_TIMEOUT} HAL_StatusTypeDef;
typedef struct {uint32_t State, ErrorCode;} SPI_HandleTypeDef;
SPI_HandleTypeDef hspi1;
#define fake_spi hspi1
uint32_t HAL_SPI_GetError(SPI_HandleTypeDef *);
uint32_t HAL_GetTick(void);
int HAL_GPIO_ReadPin(int,int);
void HAL_GPIO_WritePin(int,int,int);
HAL_StatusTypeDef HAL_SPI_TransmitReceive(SPI_HandleTypeDef *,const void *,void *,uint16_t,uint32_t);
HAL_StatusTypeDef HAL_SPI_TransmitReceive_DMA(SPI_HandleTypeDef *,const void *,void *,uint16_t);
HAL_StatusTypeDef HAL_SPI_Receive_DMA(SPI_HandleTypeDef *,void *,uint16_t);
HAL_StatusTypeDef HAL_SPI_Abort(SPI_HandleTypeDef *);
#endif
''')
    source='#include "'+str(ROOT/'ST67W6X/Target/spi_port.c')+'"\n'+r'''
#include <assert.h>
static uint32_t tick=100;
static HAL_StatusTypeDef outcome;
uint32_t xTaskGetTickCount(void) { return tick; }
uint32_t xTaskGetTickCountFromISR(void) { return tick; }
int xTaskGetSchedulerState(void) { return 1; }
uint32_t HAL_GetTick(void) { return tick; }
uint32_t HAL_SPI_GetError(SPI_HandleTypeDef *p) { return p->ErrorCode; }
int HAL_GPIO_ReadPin(int p,int n) { return 0; }
void HAL_GPIO_WritePin(int p,int n,int v) { }
HAL_StatusTypeDef HAL_SPI_TransmitReceive(SPI_HandleTypeDef *p,const void *t,void *r,uint16_t n,uint32_t wait) {
    tick+=5; p->State=HAL_SPI_STATE_READY; p->ErrorCode=(outcome==HAL_OK?0:32); return outcome;
}
HAL_StatusTypeDef HAL_SPI_TransmitReceive_DMA(SPI_HandleTypeDef *p,const void *t,void *r,uint16_t n) { return outcome; }
HAL_StatusTypeDef HAL_SPI_Receive_DMA(SPI_HandleTypeDef *p,void *r,uint16_t n) { return outcome; }
HAL_StatusTypeDef HAL_SPI_Abort(SPI_HandleTypeDef *p) { return outcome; }
int main(int argc,char **argv) {
    int mode=atoi(argv[1]); uint8_t data[8]={0}; spi_port_diagnostics_t d;
    fake_spi.State=HAL_SPI_STATE_READY;
    outcome=mode==1?HAL_TIMEOUT:mode==2?HAL_BUSY:HAL_OK;
    if(mode==3) fake_spi.State=HAL_SPI_STATE_RESET;
    int ret=mode>=4?spi_port_transfer_dma(data,data,8):spi_port_transfer(data,data,8,100);
    spi_port_get_diagnostics(&d);
    if(mode>=4) {
        assert(ret==0 && d.active && d.completed_tick==0 && d.hal_status==UINT32_MAX);
        tick+=10;
        if(mode==4) HAL_SPI_TxRxCpltCallback(&fake_spi);
        else HAL_SPI_ErrorCallback(&fake_spi);
        spi_port_get_diagnostics(&d);
        assert(!d.active && d.completed_tick==110 && d.callback_count==1);
        assert(d.hal_status==(mode==4?HAL_OK:HAL_ERROR));
    } else {
        assert(!d.active && d.completed_tick==(mode==3?100:105));
        assert(d.callback_count==0 && d.last_callback==0);
        assert(d.hal_status==(mode==3?HAL_ERROR:outcome));
        assert(ret==(mode==0?0:-1));
    }
    fake_spi.State=HAL_SPI_STATE_READY;
    outcome=HAL_BUSY; assert(spi_port_transfer_dma(data,data,8)==-1);
    spi_port_get_diagnostics(&d); assert(!d.active && d.hal_status==HAL_BUSY);
    return 0;
}
'''
    compile_run(tmp_path,source,range(6))
