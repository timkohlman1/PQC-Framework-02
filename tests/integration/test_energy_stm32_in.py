"""Compile the new STM32 path; native doubles establish software semantics only."""
import json
from pathlib import Path
import subprocess
import sys
import uuid

import pytest
import yaml
from framework.config_resolver import ConfigResolver

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.integration


def test_energy_native_experiment_boundary_is_one_gpio_window(tmp_path):
    (tmp_path / "main.h").write_text(r"""
#pragma once
#include <stdint.h>
typedef struct { uint32_t BSRR; } GPIO_TypeDef;
typedef struct { uint32_t Pin,Mode,Pull,Speed; } GPIO_InitTypeDef;
extern GPIO_TypeDef gpio;
#define GPIOF (&gpio)
#define GPIO_PIN_12 4096U
#define GPIO_MODE_OUTPUT_PP 1
#define GPIO_NOPULL 0
#define GPIO_SPEED_FREQ_LOW 0
#define __HAL_RCC_GPIOF_CLK_ENABLE() ((void)0)
#define __DSB() ((void)0)
uint32_t __get_PRIMASK(void);
void __disable_irq(void);
void __set_PRIMASK(uint32_t);
void HAL_GPIO_Init(GPIO_TypeDef*, GPIO_InitTypeDef*);
""")
    (tmp_path / "pqc_timebase.h").write_text(r"""
#pragma once
#include <stdint.h>
typedef struct {
    uint8_t initialized;
    uint32_t counter_hz;
} PQC_TimebaseProvenance;
const PQC_TimebaseProvenance *PQC_TimebaseGetProvenance(void);
uint64_t PQC_TimebaseNowUs(void);
""")
    (tmp_path / "pqc_result_buffer.h").write_text(r"""
#pragma once
#include <stdbool.h>
#include <stdint.h>
bool PQC_ResultBufferAppendText(uint32_t iteration, const char *context, const char *text);
""")
    (tmp_path / "test.c").write_text(r"""
#include "main.h"
#include "pqc_energy_boundary.h"
#include "pqc_timebase.h"
#include "pqc_result_buffer.h"
#include <assert.h>
#include <string.h>
GPIO_TypeDef gpio;
static uint32_t mask;
static uint64_t now = 4294967400ULL;
static char captured[256];
static PQC_TimebaseProvenance provenance = {.initialized=1, .counter_hz=1000000};
const PQC_TimebaseProvenance *PQC_TimebaseGetProvenance(void) { return &provenance; }
uint64_t PQC_TimebaseNowUs(void) { assert(mask==1); return now; }
uint32_t __get_PRIMASK(void) { return mask; }
void __disable_irq(void) { mask=1; }
void __set_PRIMASK(uint32_t m) { mask=m; }
void HAL_GPIO_Init(GPIO_TypeDef *g, GPIO_InitTypeDef *p) { (void)g; assert(p->Pin==GPIO_PIN_12); }
bool PQC_ResultBufferAppendText(uint32_t i, const char *context, const char *text) {
    assert(i==0); assert(strcmp(context,"energy_boundary")==0); strcpy(captured,text); return true;
}
int main(void) {
    PQC_EnergyBoundaryInitialize();
    assert(gpio.BSRR==(GPIO_PIN_12<<16));
    mask=0; PQC_EnergyBoundaryBegin(); assert(mask==0); assert(gpio.BSRR==GPIO_PIN_12);
    now += 1000;
    PQC_EnergyBoundaryEnd(); assert(mask==0); assert(gpio.BSRR==(GPIO_PIN_12<<16));
    PQC_EnergyBoundaryAppend(0);
    assert(strstr(captured,"scope=experiment"));
    assert(strstr(captured,"valid=1"));
    assert(strstr(captured,"clock=TIM2"));
    assert(strstr(captured,"counter_hz=1000000"));
    assert(strstr(captured,"timestamp_convention=before_gpio_write"));
    assert(strstr(captured,"s0_us=4294967400"));
    assert(strstr(captured,"s1_us=4294968400"));
    return 0;
}
""")
    command = [
        "cc", "-std=c11", "-DPQC_ENERGY_SYNC_ENABLED=1", "-I", str(tmp_path),
        "-I", str(ROOT / "Core/Inc"), str(tmp_path / "test.c"),
        str(ROOT / "Core/Src/pqc_energy_boundary.c"), "-o", str(tmp_path / "test"),
    ]
    built = subprocess.run(command, capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(tmp_path / "test")], capture_output=True, text=True, timeout=10)
    assert ran.returncode == 0, ran.stderr


@pytest.mark.parametrize("workload,uart", [("ready_metrics","minimal"), ("tls_handshake_repeat","disabled"), ("baremetal_benchmark","disabled")])
def test_real_energy_stm32_build(tmp_path, pqc_require_capabilities, pytestconfig, workload, uart):
    pqc_require_capabilities("local_toolchain", strict_mode="local_build")
    campaign = yaml.safe_load((ROOT/"configs/campaigns/baseline.yaml").read_text())
    campaign.update(id="energy-build", instruments={"energy":"esp32_ina228"}, workload=workload,
                    matrix={"workload.uart_output_mode":[uart]})
    generated_root = ROOT/".pqc-generated-state"/"energy-build-tests"/uuid.uuid4().hex
    generated_root.mkdir(parents=True)
    campaign_path = generated_root/"campaign.yaml"
    campaign_path.write_text(yaml.safe_dump(campaign))
    generated = ConfigResolver(ROOT).materialize_campaign(campaign_path, generated_root/"resolved")
    case = next((generated/"cases").glob("*.yaml"))
    from framework.hardware_test_support import session_result_dir
    results = session_result_dir(pytestconfig)/("energy-build-"+workload)
    completed = subprocess.run([sys.executable, "scripts/experiment.py", "build", "--experiment", str(case),
        "--results-dir", str(results), "--force"], cwd=ROOT, capture_output=True, text=True, timeout=300)
    errors = [line for log in results.glob("*/build.log") for line in log.read_text().splitlines() if "error:" in line]
    assert completed.returncode == 0, "\n".join(errors)+completed.stdout+completed.stderr
    manifest = json.loads(next(results.glob("*/manifest.json")).read_text())
    assert manifest["capture_acceptance"]["accepted"]
