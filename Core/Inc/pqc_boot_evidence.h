#ifndef PQC_BOOT_EVIDENCE_H
#define PQC_BOOT_EVIDENCE_H

#include <stdint.h>

/* Called only after the measured workload. Copies no boot evidence into the
 * transient TLS buffer until the final reporting epoch is assembled. */
void PQC_BootEvidenceAppendToResultBuffer(uint32_t iteration);

#endif /* PQC_BOOT_EVIDENCE_H */
