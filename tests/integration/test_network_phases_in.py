"""Real native compilation and deferred-buffer transport; no physical networking."""
import json
import subprocess
from pathlib import Path
import pytest
from framework.network_phases import extract_network_phases
from framework.timing_metrics import _fields
ROOT=Path(__file__).resolve().parents[2]
pytestmark=pytest.mark.integration


def test_native_network_markers_defer_formatting_preserve_width_and_fail_closed(tmp_path):
    source=tmp_path/'harness.c'
    source.write_text(r"""
#include "pqc_network_phases.h"
#include "pqc_timebase.h"
#include "pqc_result_buffer.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
static uint64_t now;
static PQC_TimebaseProvenance provenance;
uint64_t PQC_TimebaseNowUs(void) { return now; }
const PQC_TimebaseProvenance *PQC_TimebaseGetProvenance(void) { return &provenance; }
int main(int argc,char **argv) {
    int mode=argc>1?atoi(argv[1]):0;
    provenance.initialized=1;
    PQC_ResultBufferReset(); PQC_NetworkPhasesReset();
    now=(1ULL<<32)+123;
    PQC_NetworkPhaseBegin(PQC_NET_MODULE_INIT); now+=100;
    PQC_NetworkPhaseEnd(PQC_NET_MODULE_INIT,-3);
    assert(PQC_ResultBufferSize()==0); /* No serialization inside measured spans. */
    if(mode==1) PQC_NetworkPhaseBegin(PQC_NET_MODULE_INIT); /* repeated phase */
    if(mode==2) { now=2; PQC_NetworkPhaseBegin(PQC_NET_WIFI_INIT); now=1; PQC_NetworkPhaseEnd(PQC_NET_WIFI_INIT,0); }
    if(mode==3) { provenance.initialized=0; PQC_NetworkPhaseBegin(PQC_NET_WIFI_INIT); }
    if(mode==4) { PQC_NetworkPhaseBegin(PQC_NET_WIFI_INIT); } /* missing end */
    if(mode==5) { PQC_NetworkPhasesReset(); } /* a new run cannot inherit a span */
    if(mode==6) { /* No scan; later connection still produces a valid span. */
        now+=100; PQC_NetworkPhaseBegin(PQC_NET_WIFI_CONNECT); now+=100;
        PQC_NetworkPhaseEnd(PQC_NET_WIFI_CONNECT,0);
    }
    PQC_NetworkPhasesAppend(0);
    PQC_ResultBufferStatus status; PQC_ResultBufferStatusGet(&status);
    assert(status.record_count==8 && status.dropped_record_count==0 && !status.overflowed);
    fwrite(PQC_ResultBufferData(),1,PQC_ResultBufferSize(),stdout);
    return 0;
}
""")
    exe=tmp_path/'check'
    subprocess.run(['gcc','-std=c11','-Wall','-Wextra','-Werror','-I'+str(ROOT/'Core/Inc'),
        str(source),str(ROOT/'Core/Src/pqc_network_phases.c'),str(ROOT/'Core/Src/pqc_result_buffer.c'),'-o',str(exe)],check=True,capture_output=True,text=True)
    for mode in range(7):
        lines=subprocess.check_output([str(exe),str(mode)],text=True).splitlines()
        records=[]
        for index,line in enumerate(lines):
            item=json.loads(line);marker,fields=_fields(item['text'])
            records.append(dict(marker=marker,fields=fields,context=item['context'],ref={'record':index}))
        if mode in (1,2,3):
            with pytest.raises(ValueError): extract_network_phases(records)
            continue
        result=extract_network_phases(records)
        if mode==5:
            assert all(x['status']=='not_attempted' and x['start_us'] is None for x in result)
        else:
            assert result[0]['start_us']==2**32+123
            assert result[0]['duration_us']==100 and result[0]['result']==-3
            assert result[1]['status']==('incomplete' if mode==4 else 'not_attempted')
            assert result[1]['end_us'] is None
        if mode==6:
            scan=next(x for x in result if x['phase']=='wifi_scan')
            connect=next(x for x in result if x['phase']=='wifi_connect')
            assert scan['status']=='not_attempted' and scan['duration_us'] is None
            assert connect['status']=='completed' and connect['duration_us']==100
