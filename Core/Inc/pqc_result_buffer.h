#ifndef PQC_RESULT_BUFFER_H
#define PQC_RESULT_BUFFER_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PQC_RESULT_BUFFER_CAPACITY_BYTES (32U * 1024U)
#define PQC_RESULT_SCHEMA_VERSION 1U

typedef struct {
    uint32_t schema_version;
    uint32_t record_count;
    uint32_t dropped_record_count;
    uint32_t used_bytes;
    uint8_t overflowed;
} PQC_ResultBufferStatus;

void PQC_ResultBufferReset(void);
bool PQC_ResultBufferAppendText(uint32_t iteration, const char *context, const char *text);
const uint8_t *PQC_ResultBufferData(void);
size_t PQC_ResultBufferSize(void);
void PQC_ResultBufferStatusGet(PQC_ResultBufferStatus *status);
void PQC_ResultBufferSha256(uint8_t digest[32]);
void PQC_ResultBufferSha256Hex(char output[65]);

#ifdef __cplusplus
}
#endif
#endif
