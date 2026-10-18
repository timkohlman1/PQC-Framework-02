#include "pqc_activity_trace.h"
#if PQC_ACTIVITY_TRACE_ENABLED
#include "main.h"
#include "pqc_timebase.h"
#include "pqc_result_buffer.h"
#include <stdio.h>
#include <string.h>
#define EVENT_CAPACITY 128U
#define BIN_CAPACITY 1024U
#define BIN_US 10000U
/* Explicit little-endian wire layout: u32 elapsed_us, u16 kind/code,
 * u16 span token, i32 value. kind=0 instant, 1 begin, 2 end. */
static uint8_t events[EVENT_CAPACITY * 12U], spi_wire[3072U];
static uint16_t bins[BIN_CAPACITY * 2U];
static uint8_t open_span[EVENT_CAPACITY];
static uint64_t origin_us;
static uint32_t elapsed_us, count, dropped, errors, saturated, clipped;
static uint8_t active;
static uint32_t lock(void) { uint32_t m=__get_PRIMASK(); __disable_irq(); return m; }
static void put16(uint8_t *p,uint16_t x) { p[0]=(uint8_t)x; p[1]=(uint8_t)(x>>8); }
static void put32(uint8_t *p,uint32_t x) { put16(p,(uint16_t)x); put16(p+2,(uint16_t)(x>>16)); }
static uint32_t tick(void) {
    uint64_t now=PQC_TimebaseNowUs();
    if(now<origin_us || now-origin_us>UINT32_MAX) { errors++; active=0; return elapsed_us; }
    elapsed_us=(uint32_t)(now-origin_us); return elapsed_us;
}
static uint16_t record(uint16_t code,uint16_t token,int32_t value,uint16_t kind) {
    uint32_t t=tick(); uint8_t *p;
    if(!active) return 0;
    if(count==EVENT_CAPACITY) { dropped++; return 0; }
    p=events+12U*count; put32(p,t); put16(p+4,code | (uint16_t)(kind<<14));
    put16(p+6,token); put32(p+8,(uint32_t)value); count++;
    return (uint16_t)count;
}
void PQC_ActivityReset(void) {
    uint32_t m=lock(); active=0; __set_PRIMASK(m);
    /* Called once before the network tasks start producing trace data. */
    memset(events,0,sizeof(events)); memset(bins,0,sizeof(bins)); memset(open_span,0,sizeof(open_span));
    m=lock(); count=dropped=errors=saturated=clipped=elapsed_us=0;
    origin_us=PQC_TimebaseNowUs(); active=PQC_TimebaseGetProvenance()->initialized!=0;
    if(!active) { errors++; }
    __set_PRIMASK(m);
}
void PQC_ActivityStop(void) { uint32_t m=lock(); if(active) (void)tick(); active=0; __set_PRIMASK(m); }
uint16_t PQC_ActivityBegin(uint16_t code,int32_t value) {
    uint32_t m=lock(); uint16_t token=0;
    if(active) { token=record(code,(uint16_t)(count+1U),value,1); if(token) open_span[token-1U]=1; }
    __set_PRIMASK(m); return token;
}
void PQC_ActivityEnd(uint16_t token,int32_t result) {
    uint32_t m=lock();
    if(active && token) {
        if(token>count || !open_span[token-1U]) errors++;
        else { uint8_t *p=events+12U*(token-1U); uint16_t code=(uint16_t)(p[4]|((p[5]&63U)<<8));
            open_span[token-1U]=0; (void)record(code,token,result,2); }
    }
    __set_PRIMASK(m);
}
void PQC_ActivityEvent(uint16_t code,int32_t value) { uint32_t m=lock(); if(active) (void)record(code,0,value,0); __set_PRIMASK(m); }
void PQC_ActivitySPI(uint8_t host_write) {
    uint32_t m=lock();
    if(active) { uint32_t bin=tick()/BIN_US;
        if(active) { if(bin>=BIN_CAPACITY) clipped++;
            else { uint16_t *p=bins+bin*2U+(host_write?0U:1U); if(*p==UINT16_MAX) saturated++; else (*p)++; } }
    }
    __set_PRIMASK(m);
}
uint16_t PQC_ActivityCommand(const char *command) {
    static const char *const commands[] = {"AT","CWNETMODE","GET_CLOCK","SET_CLOCK","GMR","IORST","SLWKIO","PWR","CWANTENABLE","CWANT","CWMODE","CWAUTOCONN","CWCOUNTRY","SLWKDTIM","CIPSTAMAC","CIPAPMAC","CWJAP","CWJAPS","CWRECONNCFG","CWSTATE","GET_AP_DTIM","SYSRAM","SYSSTORE","CWLAP","CWLAPOPT","CWQAP","WPS","EFUSE","VBAT","CMD","FS"};
    const char *p=command; size_t len; unsigned i; uint16_t code=100;
    if(!p) return PQC_ActivityBegin(code,0);
    if(strncmp(p,"AT+",3)==0) p+=3;
    len=strcspn(p,"=?\r\n");
    for(i=0;i<sizeof(commands)/sizeof(commands[0]);i++)
        if(strlen(commands[i])==len && strncmp(p,commands[i],len)==0) { code=(uint16_t)(101U+i); break; }
    /* Store command class and query/set form only, never argument strings. */
    return PQC_ActivityBegin(code,p[len]=='?'?1:(p[len]=='='?2:0));
}
static char *decimal(uint64_t v,char b[21]) { char *p=b+20; *p=0; do { *--p=(char)('0'+v%10U); v/=10U; } while(v); return p; }
static void chunks(uint32_t iteration,const char *stream,const uint8_t *data,uint32_t size) {
    static const char alphabet[]="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    char line[640], encoded[513]; uint32_t offset;
    for(offset=0;offset<size;offset+=384U) {
        uint32_t n=size-offset,i,j=0; if(n>384U) n=384U;
        for(i=0;i<n;i+=3U) { uint32_t v=(uint32_t)data[offset+i]<<16;
            if(i+1U<n) v|=(uint32_t)data[offset+i+1U]<<8;
            if(i+2U<n) v|=data[offset+i+2U];
            encoded[j++]=alphabet[(v>>18)&63U]; encoded[j++]=alphabet[(v>>12)&63U];
            encoded[j++]=i+1U<n?alphabet[(v>>6)&63U]:'='; encoded[j++]=i+2U<n?alphabet[v&63U]:'=';
        }
        encoded[j]=0;
        (void)snprintf(line,sizeof(line),"PQC_ACTIVITY_DATA schema=2 stream=%s offset=%lu base64=%s",stream,(unsigned long)offset,encoded);
        (void)PQC_ResultBufferAppendText(iteration,"activity_trace",line);
    }
}
void PQC_ActivityAppend(uint32_t iteration) {
    char line[384], origin[21]; uint32_t used=elapsed_us/BIN_US+1U;
    uint32_t retained=0, wire_size=0, i, wire_clipped;
    if(active) return; /* Serialization is forbidden during measurement. */
    if(used>BIN_CAPACITY) used=BIN_CAPACITY;
    for(i=0;i<used;i++) {
        uint8_t encoded[6]; uint32_t n=0, direction;
        for(direction=0;direction<2U;direction++) {
            uint32_t value=bins[2U*i+direction];
            do { uint8_t b=(uint8_t)(value&127U); value>>=7;
                encoded[n++]=(uint8_t)(b|(value?128U:0U)); } while(value);
        }
        if(wire_size+n>sizeof(spi_wire)) break;
        memcpy(spi_wire+wire_size,encoded,n); wire_size+=n; retained++;
    }
    wire_clipped=used-retained; used=retained;
    (void)snprintf(line,sizeof(line),"PQC_ACTIVITY_TRACE schema=2 clock=TIM2 origin_us=%s elapsed_us=%lu events=%lu bins=%lu bin_us=10000 dropped=%lu errors=%lu saturated=%lu clipped=%lu wire_clipped_bins=%lu encoding=le12_varuint16_base64",
        decimal(origin_us,origin),(unsigned long)elapsed_us,(unsigned long)count,(unsigned long)used,
        (unsigned long)dropped,(unsigned long)errors,(unsigned long)saturated,(unsigned long)clipped,(unsigned long)wire_clipped);
    (void)PQC_ResultBufferAppendText(iteration,"activity_trace",line);
    chunks(iteration,"events",events,count*12U); chunks(iteration,"spi",spi_wire,wire_size);
}
#endif
