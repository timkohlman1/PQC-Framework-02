#ifndef PQC_BENCHMARK_STM32_H
#define PQC_BENCHMARK_STM32_H

/* Run exactly once, before osKernelInitialize(), and before Wi-Fi/MQTT startup.
 * This function performs no reporting. Its raw records are retained separately
 * until PQC_BenchmarkSTM32_AppendResults is called after the final measurement. */
void PQC_BenchmarkSTM32_Run(void);
void PQC_BenchmarkSTM32_AppendResults(void);

#endif
