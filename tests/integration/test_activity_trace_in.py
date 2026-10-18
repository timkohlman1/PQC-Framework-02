"""Native C boundary exercise; no assertion about physical radio states."""
import json
import subprocess
from pathlib import Path
import pytest
from framework.activity_trace import extract_activity
from framework.timing_metrics import _fields
ROOT=Path(__file__).resolve().parents[2]
pytestmark=pytest.mark.integration

def test_activity_native_bounded_transport(tmp_path):
    (tmp_path/'main.h').write_text("#include <stdint.h>\nuint32_t __get_PRIMASK(void);\nvoid __disable_irq(void);\nvoid __set_PRIMASK(uint32_t);\n")
    (tmp_path/'harness.c').write_text(r'''
#include "pqc_activity_trace.h"
#include "pqc_timebase.h"
#include "pqc_result_buffer.h"
#include <stdio.h>
#include <stdlib.h>
#include <assert.h>
static uint32_t mask;
static uint64_t now;
static PQC_TimebaseProvenance provenance;
uint32_t __get_PRIMASK(void) { return mask; }
void __disable_irq(void) { mask=1; }
void __set_PRIMASK(uint32_t m) { mask=m; }
uint64_t PQC_TimebaseNowUs(void) { assert(mask==1); return now; }
const PQC_TimebaseProvenance *PQC_TimebaseGetProvenance(void) { return &provenance; }
int main(int argc,char **argv) {
    int mode=argc>1?atoi(argv[1]):0; uint16_t a,b; unsigned i,j;
    now=(1ULL<<32)+123; provenance.initialized=1;
    PQC_ResultBufferReset(); PQC_ActivityReset(); assert(mask==0);
    a=PQC_ActivityBegin(PQC_ACT_READY_WAIT,0); now+=100;
    b=PQC_ActivityCommand("AT+CWJAP=\"private-ssid\",\"private-passphrase\"\r\n");
    PQC_ActivitySPI(1); now+=100;
    PQC_ActivityEnd(a,-3); PQC_ActivityEnd(b,0);
    mask=1; PQC_ActivityEvent(PQC_ACT_READY_RECEIVED,0); assert(mask==1); mask=0;
    now+=10000; PQC_ActivitySPI(0);
    if(mode==1) for(i=0;i<140;i++) PQC_ActivityEvent(PQC_ACT_CHIP_ENABLE,1);
    if(mode==2) for(i=0;i<300;i++) PQC_ActivitySPI(0);
    if(mode==3) { now+=11000000; PQC_ActivitySPI(0); }
    if(mode==4) { now=1; PQC_ActivityEvent(PQC_ACT_CHIP_ENABLE,1); }
    if(mode==5) PQC_ActivityEnd(a,0);
    if(mode==6) (void)PQC_ActivityBegin(PQC_ACT_CONNECT_WAIT,0);
    if(mode==7) { PQC_ActivityReset(); a=PQC_ActivityBegin(PQC_ACT_TCPIP_INIT,0); now++; PQC_ActivityEnd(a,0); }
    if(mode==8) { for(i=0;i<140;i++) PQC_ActivityEvent(PQC_ACT_CHIP_ENABLE,1); now+=10200000; PQC_ActivitySPI(0); }
    if(mode==9) { now+=((uint64_t)1<<32); PQC_ActivitySPI(0); }
    if(mode==10) for(i=0;i<70000;i++) PQC_ActivitySPI(0);
    if(mode==11) {
        for(i=0;i<140;i++) PQC_ActivityEvent(PQC_ACT_CHIP_ENABLE,1);
        for(i=2;i<1024;i++) { now=(1ULL<<32)+123+i*10000U;
            for(j=0;j<255;j++) { PQC_ActivitySPI(1); PQC_ActivitySPI(0); } }
    }
    PQC_ActivityAppend(0); /* Active trace cannot format into the result buffer. */
    if(mode!=4 && mode!=9) assert(PQC_ResultBufferSize()==0);
    PQC_ResultBufferReset();
    PQC_ActivityStop(); assert(mask==0); now++;
    PQC_ActivityEvent(PQC_ACT_CHIP_ENABLE,1); PQC_ActivitySPI(1);
    PQC_ActivityAppend(0);
    PQC_ResultBufferStatus status; PQC_ResultBufferStatusGet(&status);
    assert(!status.overflowed && status.dropped_record_count==0);
    assert(PQC_ResultBufferSize()+24319U<32768U);
    fwrite(PQC_ResultBufferData(),1,PQC_ResultBufferSize(),stdout);
}
''')
    exe=tmp_path/'run'
    subprocess.run(['gcc','-std=c11','-Wall','-Wextra','-Werror','-DPQC_ACTIVITY_TRACE_ENABLED=1',
        '-I'+str(tmp_path),'-I'+str(ROOT/'Core/Inc'),str(tmp_path/'harness.c'),
        str(ROOT/'Core/Src/pqc_activity_trace.c'),str(ROOT/'Core/Src/pqc_result_buffer.c'),'-o',str(exe)],check=True,capture_output=True,text=True)
    for mode in range(12):
        output=subprocess.check_output([str(exe),str(mode)],text=True)
        assert 'private-ssid' not in output and 'private-passphrase' not in output
        records=[]
        for line in output.splitlines():
            item=json.loads(line); marker,fields=_fields(item['text'])
            records.append(dict(marker=marker,fields=fields,context=item['context']))
        trace=extract_activity(records)
        assert trace['origin_us']>=2**32
        if mode==0:
            assert trace['event_complete'] and trace['spi_complete']
            assert trace['spans'][0]['end_us']-trace['spans'][0]['start_us']==200
            assert trace['spans'][0]['result']==-3
            assert trace['spans'][1]['name']=='at_cwjap' and trace['spans'][1]['value']==2
            assert trace['spi_counts']==[(1,0),(0,1)]
        if mode in (1,8): assert trace['dropped'] and not trace['event_complete']
        if mode==2: assert not trace['saturated'] and trace['spi_counts'][1][1]==301
        if mode==10: assert trace['saturated'] and not trace['spi_complete']
        if mode==11: assert trace['wire_clipped_bins'] and not trace['spi_complete']
        if mode==3: assert trace['clipped'] and not trace['spi_complete']
        if mode in (4,5,9): assert trace['errors'] and not trace['event_complete']
        if mode==6: assert trace['unfinished'] and not trace['event_complete']
        if mode==7: assert len(trace['spans'])==1 and trace['spans'][0]['name']=='tcpip_init'
