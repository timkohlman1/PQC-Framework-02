#include "pqc_result_buffer.h"

#include <stdio.h>
#include <string.h>

typedef struct {
    uint32_t state[8];
    uint64_t bit_count;
    uint8_t block[64];
    size_t block_used;
} PQC_SHA256Context;

static uint8_t s_buffer[PQC_RESULT_BUFFER_CAPACITY_BYTES]
    __attribute__((section(".pqc_result_buffer"), aligned(32), used));
static size_t s_used;
static uint32_t s_records;
static uint32_t s_dropped;
static bool s_overflowed;

static uint32_t rotr32(uint32_t value, uint32_t bits) { return (value >> bits) | (value << (32U - bits)); }
static uint32_t choose32(uint32_t x, uint32_t y, uint32_t z) { return (x & y) ^ (~x & z); }
static uint32_t majority32(uint32_t x, uint32_t y, uint32_t z) { return (x & y) ^ (x & z) ^ (y & z); }
static uint32_t sigma0(uint32_t x) { return rotr32(x, 2U) ^ rotr32(x, 13U) ^ rotr32(x, 22U); }
static uint32_t sigma1(uint32_t x) { return rotr32(x, 6U) ^ rotr32(x, 11U) ^ rotr32(x, 25U); }
static uint32_t gamma0(uint32_t x) { return rotr32(x, 7U) ^ rotr32(x, 18U) ^ (x >> 3U); }
static uint32_t gamma1(uint32_t x) { return rotr32(x, 17U) ^ rotr32(x, 19U) ^ (x >> 10U); }

static const uint32_t k_sha256[64] = {
  0x428a2f98U,0x71374491U,0xb5c0fbcfU,0xe9b5dba5U,0x3956c25bU,0x59f111f1U,0x923f82a4U,0xab1c5ed5U,
  0xd807aa98U,0x12835b01U,0x243185beU,0x550c7dc3U,0x72be5d74U,0x80deb1feU,0x9bdc06a7U,0xc19bf174U,
  0xe49b69c1U,0xefbe4786U,0x0fc19dc6U,0x240ca1ccU,0x2de92c6fU,0x4a7484aaU,0x5cb0a9dcU,0x76f988daU,
  0x983e5152U,0xa831c66dU,0xb00327c8U,0xbf597fc7U,0xc6e00bf3U,0xd5a79147U,0x06ca6351U,0x14292967U,
  0x27b70a85U,0x2e1b2138U,0x4d2c6dfcU,0x53380d13U,0x650a7354U,0x766a0abbU,0x81c2c92eU,0x92722c85U,
  0xa2bfe8a1U,0xa81a664bU,0xc24b8b70U,0xc76c51a3U,0xd192e819U,0xd6990624U,0xf40e3585U,0x106aa070U,
  0x19a4c116U,0x1e376c08U,0x2748774cU,0x34b0bcb5U,0x391c0cb3U,0x4ed8aa4aU,0x5b9cca4fU,0x682e6ff3U,
  0x748f82eeU,0x78a5636fU,0x84c87814U,0x8cc70208U,0x90befffaU,0xa4506cebU,0xbef9a3f7U,0xc67178f2U
};

static void sha256_transform(PQC_SHA256Context *ctx, const uint8_t block[64]) {
    uint32_t w[64], a,b,c,d,e,f,g,h,t1,t2;
    unsigned int i;
    for (i=0U;i<16U;i++) w[i]=((uint32_t)block[4U*i]<<24)|((uint32_t)block[4U*i+1U]<<16)|((uint32_t)block[4U*i+2U]<<8)|block[4U*i+3U];
    for (;i<64U;i++) w[i]=gamma1(w[i-2U])+w[i-7U]+gamma0(w[i-15U])+w[i-16U];
    a=ctx->state[0]; b=ctx->state[1]; c=ctx->state[2]; d=ctx->state[3]; e=ctx->state[4]; f=ctx->state[5]; g=ctx->state[6]; h=ctx->state[7];
    for(i=0U;i<64U;i++){ t1=h+sigma1(e)+choose32(e,f,g)+k_sha256[i]+w[i]; t2=sigma0(a)+majority32(a,b,c); h=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+t2; }
    ctx->state[0]+=a; ctx->state[1]+=b; ctx->state[2]+=c; ctx->state[3]+=d; ctx->state[4]+=e; ctx->state[5]+=f; ctx->state[6]+=g; ctx->state[7]+=h;
}
static void sha256_init(PQC_SHA256Context *ctx) {
    static const uint32_t initial[8]={0x6a09e667U,0xbb67ae85U,0x3c6ef372U,0xa54ff53aU,0x510e527fU,0x9b05688cU,0x1f83d9abU,0x5be0cd19U};
    memcpy(ctx->state,initial,sizeof(initial)); ctx->bit_count=0U; ctx->block_used=0U;
}
static void sha256_update(PQC_SHA256Context *ctx,const uint8_t *data,size_t length){ size_t n; ctx->bit_count+=(uint64_t)length*8U; while(length){ n=64U-ctx->block_used; if(n>length)n=length; memcpy(ctx->block+ctx->block_used,data,n); ctx->block_used+=n; data+=n; length-=n; if(ctx->block_used==64U){sha256_transform(ctx,ctx->block);ctx->block_used=0U;}}}
static void sha256_final(PQC_SHA256Context *ctx,uint8_t digest[32]){ uint64_t bits=ctx->bit_count; unsigned int i; ctx->block[ctx->block_used++]=0x80U; if(ctx->block_used>56U){while(ctx->block_used<64U)ctx->block[ctx->block_used++]=0U;sha256_transform(ctx,ctx->block);ctx->block_used=0U;} while(ctx->block_used<56U)ctx->block[ctx->block_used++]=0U; for(i=0U;i<8U;i++)ctx->block[63U-i]=(uint8_t)(bits>>(8U*i)); sha256_transform(ctx,ctx->block); for(i=0U;i<8U;i++){digest[4U*i]=(uint8_t)(ctx->state[i]>>24);digest[4U*i+1U]=(uint8_t)(ctx->state[i]>>16);digest[4U*i+2U]=(uint8_t)(ctx->state[i]>>8);digest[4U*i+3U]=(uint8_t)ctx->state[i];}}

static bool append_escaped(char *output, size_t output_size, size_t *used, const char *text) {
    size_t i;
    for (i=0U; text != NULL && text[i] != '\0'; ++i) {
        char c=text[i]; const char *escape=NULL; char single[2]={c,'\0'};
        if(c=='"') escape="\\\""; else if(c=='\\') escape="\\\\"; else if(c=='\n') escape="\\n"; else if(c=='\r') escape="\\r"; else if(c=='\t') escape="\\t"; else escape=single;
        { size_t n=strlen(escape); if((*used+n)>=output_size) return false; memcpy(output+*used,escape,n); *used+=n; }
    }
    return true;
}

void PQC_ResultBufferReset(void) { s_used=0U; s_records=0U; s_dropped=0U; s_overflowed=false; }

bool PQC_ResultBufferAppendText(uint32_t iteration, const char *context, const char *text) {
    char record[768]; size_t used=0U; int n;
    const char *safe_context=(context!=NULL)?context:"unspecified";
    const char *safe_text=(text!=NULL)?text:"";
    n=snprintf(record,sizeof(record),"{\"schema_version\":%u,\"source\":\"stm32\",\"iteration\":%lu,\"context\":\"",PQC_RESULT_SCHEMA_VERSION,(unsigned long)iteration);
    if (n < 0 || (size_t)n >= sizeof(record)) goto drop;
    used = (size_t)n;
    if(!append_escaped(record,sizeof(record),&used,safe_context)) goto drop;
    if (used + 10U >= sizeof(record)) goto drop;
    memcpy(record + used, "\",\"text\":\"", 10U);
    used += 10U;
    if(!append_escaped(record,sizeof(record),&used,safe_text)) goto drop;
    if (used + 3U >= sizeof(record)) goto drop;
    record[used++] = '"';
    record[used++] = '}';
    record[used++] = '\n';
    if(s_used+used>PQC_RESULT_BUFFER_CAPACITY_BYTES) goto drop;
    memcpy(s_buffer+s_used,record,used); s_used+=used; s_records++; return true;
drop:
    s_dropped++; s_overflowed=true; return false;
}
const uint8_t *PQC_ResultBufferData(void){return s_buffer;}
size_t PQC_ResultBufferSize(void){return s_used;}
void PQC_ResultBufferStatusGet(PQC_ResultBufferStatus *status){if(status==NULL)return; status->schema_version=PQC_RESULT_SCHEMA_VERSION; status->record_count=s_records; status->dropped_record_count=s_dropped; status->used_bytes=(uint32_t)s_used; status->overflowed=s_overflowed?1U:0U;}
void PQC_ResultBufferHashData(const uint8_t *data, size_t length, uint8_t digest[32]){PQC_SHA256Context ctx;if(digest==NULL)return;if(data==NULL&&length!=0U){memset(digest,0,32U);return;}sha256_init(&ctx);sha256_update(&ctx,data,length);sha256_final(&ctx,digest);}
void PQC_ResultBufferSha256(uint8_t digest[32]){PQC_ResultBufferHashData(s_buffer,s_used,digest);}
void PQC_ResultBufferSha256Hex(char output[65]){static const char hex[]="0123456789abcdef";uint8_t digest[32];unsigned int i;if(output==NULL)return;PQC_ResultBufferSha256(digest);for(i=0U;i<32U;i++){output[2U*i]=hex[digest[i]>>4];output[2U*i+1U]=hex[digest[i]&0x0fU];}output[64]='\0';}
