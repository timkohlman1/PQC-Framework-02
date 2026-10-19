"""Real ML-DSA signatures with instrumentation on/off and both signing paths."""
from pathlib import Path
import re,subprocess
import pytest
ROOT=Path(__file__).resolve().parents[2]
pytestmark=pytest.mark.integration
SETTINGS='#define WOLFCRYPT_ONLY\n#define WOLFSSL_HAVE_MLDSA\n#define WOLFSSL_NO_ML_DSA_44\n#define WOLFSSL_NO_ML_DSA_87\n#define WOLFSSL_MLDSA_NO_ASN1\n#define WOLFSSL_SHA3\n#define WOLFSSL_SHAKE128\n#define WOLFSSL_SHAKE256\n#define WOLFSSL_NO_ASM\n#define NO_RSA\n#define NO_DH\n#define NO_DSA\n#define NO_AES\n#define NO_DES3\n#define NO_RC4\n#define NO_MD4\n#define NO_MD5\n#define NO_SHA\n#define NO_HMAC\n#define NO_PWDBASED\n#define NO_CODING\n#define NO_ASN\n#define SINGLE_THREADED\n#define NO_FILESYSTEM\n'
HARNESS='#include <wolfssl/wolfcrypt/wc_mldsa.h>\n#include <wolfssl/wolfcrypt/error-crypt.h>\n#include <stdio.h>\n#include <assert.h>\n#include "pqc_tls_instrumentation.h"\nstatic unsigned calls,att,rej,acc,abrt; static int outcome;\nvoid PQC_TLS_InstrumentationMLDSASampling(uint32_t a,uint32_t r,uint32_t c,uint32_t b,int32_t ret) { calls++;att=a;rej=r;acc=c;abrt=b;outcome=ret; }\nint main(void) {\n wc_MlDsaKey key; byte seed[32]={0}, sig[5000]; unsigned i,j;word32 len; int verified;\n assert(wc_MlDsaKey_Init(&key,NULL,INVALID_DEVID)==0);\n assert(wc_MlDsaKey_SetParams(&key,3)==0);\n assert(wc_MlDsaKey_MakeKeyFromSeed(&key,seed)==0);\n for(i=0;i<8;i++) { seed[0]=(byte)i;len=sizeof(sig);calls=0;\n  assert(wc_MlDsaKey_SignCtxWithSeed(&key,NULL,0,sig,&len,(const byte*)"test",4,seed)==0);\n#ifdef PQC_TLS_INSTRUMENTATION\n  assert(calls==1 && outcome==0 && att==rej+1 && acc==1 && abrt==0);\n  fprintf(stderr,"seed=%u attempts=%u rejected=%u\\n",i,att,rej);\n#endif\n  verified=0;assert(wc_MlDsaKey_VerifyCtx(&key,sig,len,NULL,0,(const byte*)"test",4,&verified)==0 && verified==1);\n  for(j=0;j<len;j++)printf("%02x",sig[j]);puts("");\n }\n len=1;calls=0;assert(wc_MlDsaKey_SignCtxWithSeed(&key,NULL,0,sig,&len,(const byte*)"test",4,seed)==BUFFER_E);\n#ifdef PQC_TLS_INSTRUMENTATION\n assert(calls==1 && att==0 && rej==0 && acc==0 && abrt==0 && outcome==BUFFER_E);\n#endif\n wc_MlDsaKey_Free(&key);return 0;\n}\n'

@pytest.mark.parametrize('level',[2,3])
@pytest.mark.parametrize('small',[False,True])
def test_real_mldsa_sampling_preserves_signatures(tmp_path,small,level):
    (tmp_path/'user_settings.h').write_text(SETTINGS.replace("WOLFSSL_NO_ML_DSA_44", "WOLFSSL_NO_ML_DSA_65") if level == 2 else SETTINGS)
    (tmp_path/'harness.c').write_text(HARNESS.replace("SetParams(&key,3)", f"SetParams(&key,{level})"))
    wolf=ROOT/'Middlewares/Third_Party/wolfSSL'
    outputs=[];counts=None
    for instrumented in (False,True):
        exe=tmp_path/('on' if instrumented else 'off')
        cmd=['cc','-O2','-ffunction-sections','-fdata-sections','-Wl,--gc-sections','-DWOLFSSL_USER_SETTINGS',
             '-I'+str(tmp_path),'-I'+str(ROOT/'Core/Inc'),'-I'+str(wolf)]
        if instrumented:cmd+=['-DPQC_TLS_INSTRUMENTATION']
        if small:cmd+=['-DWOLFSSL_MLDSA_SIGN_SMALL_MEM']
        cmd += [str(tmp_path/'harness.c')]+[str(wolf/'wolfcrypt/src'/n) for n in ('wc_mldsa.c','sha3.c','memory.c')]+['-o',str(exe)]
        subprocess.run(cmd,check=True,capture_output=True,text=True)
        run=subprocess.run([str(exe)],check=True,capture_output=True,text=True,timeout=60)
        outputs.append(run.stdout)
        if instrumented:counts=[(int(a),int(b)) for a,b in re.findall(r'attempts=(\d+) rejected=(\d+)',run.stderr)]
    assert outputs[0]==outputs[1] # every signature byte is unchanged
    assert len(counts)==8 and any(b==0 for a,b in counts) and any(b>1 for a,b in counts)
    assert all(a==b+1 for a,b in counts)

@pytest.mark.parametrize('level',[2,3])
def test_native_sampling_recorder_linkage_reset_and_overflow(tmp_path,level):
    from framework.mldsa_sampling import extract_mldsa_sampling
    from framework.timing_metrics import _fields
    (tmp_path/'main.h').write_text('#pragma once\n')
    (tmp_path/'pqc_timebase.h').write_text('''#include <stdint.h>
typedef struct {uint8_t initialized;} PQC_TimebaseProvenance;
uint64_t PQC_TimebaseNowUs(void);
uint64_t PQC_TimebaseElapsedUs(uint64_t,uint64_t);
const PQC_TimebaseProvenance *PQC_TimebaseGetProvenance(void);
''')
    (tmp_path/'recorder.c').write_text(r'''
#include "pqc_tls_instrumentation.h"
#include "pqc_timebase.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static uint64_t t;
static const PQC_TimebaseProvenance p={1};
uint64_t PQC_TimebaseNowUs(void){return ++t;}
uint64_t PQC_TimebaseElapsedUs(uint64_t a,uint64_t b){return b-a;}
const PQC_TimebaseProvenance *PQC_TimebaseGetProvenance(void){return &p;}
static void output(const char *s){assert(strlen(s)<384);fputs(s,stdout);}
int main(void){
 unsigned i;const PQC_TLSInstrumentationSnapshot *s;
 assert(PQC_TLS_InstrumentationMLDSAEvent(2,0)==PQC_TLS_PRIMITIVE_MLDSA44_VERIFY);
 assert(PQC_TLS_InstrumentationMLDSAEvent(3,0)==PQC_TLS_PRIMITIVE_MLDSA65_VERIFY);
 assert(PQC_TLS_InstrumentationMLDSAEvent(99,1)==PQC_TLS_EVENT_COUNT);
 PQC_TLS_InstrumentationMLDSASampling(1,0,1,0,0);
 PQC_TLS_InstrumentationReset(8,2);
 PQC_TLS_InstrumentationBegin(PQC_TLS_EVENT_HANDSHAKE);
 for(i=0;i<5;i++){
   PQC_TLS_InstrumentationBegin(PQC_TLS_InstrumentationMLDSAEvent(MLDSA_LEVEL, 1));
   PQC_TLS_InstrumentationMLDSASampling(i+1,i,1,0,0);
   PQC_TLS_InstrumentationEnd(PQC_TLS_InstrumentationMLDSAEvent(MLDSA_LEVEL, 1),0);
 }
 PQC_TLS_InstrumentationEnd(PQC_TLS_EVENT_HANDSHAKE,1);
 s=PQC_TLS_InstrumentationSnapshot();
 assert(s->mldsa_sampling_count==4 && s->mldsa_sampling_dropped==1);
 PQC_TLS_InstrumentationReport(output);
 PQC_TLS_InstrumentationReset(9,3);
 PQC_TLS_InstrumentationBegin(PQC_TLS_EVENT_HANDSHAKE);
 PQC_TLS_InstrumentationMLDSASampling(9,8,1,0,0); /* No active sign: ignored. */
 PQC_TLS_InstrumentationBegin(PQC_TLS_InstrumentationMLDSAEvent(MLDSA_LEVEL, 1));
 PQC_TLS_InstrumentationMLDSASampling(3,2,1,0,0);
 PQC_TLS_InstrumentationEnd(PQC_TLS_InstrumentationMLDSAEvent(MLDSA_LEVEL, 1),0);
 PQC_TLS_InstrumentationEnd(PQC_TLS_EVENT_HANDSHAKE,1);
 s=PQC_TLS_InstrumentationSnapshot();
 assert(s->mldsa_sampling_count==1 && s->mldsa_sampling_dropped==0);
 assert(s->mldsa_sampling[0].event_sequence==1);
 PQC_TLS_InstrumentationReport(output);
 return 0;
}
''')
    exe=tmp_path/'recorder'
    subprocess.run(['cc','-std=c11',f'-DMLDSA_LEVEL={level}','-Wall','-Wextra','-Werror','-I'+str(tmp_path),'-I'+str(ROOT/'Core/Inc'),str(tmp_path/'recorder.c'),str(ROOT/'Core/Src/pqc_tls_instrumentation.c'),'-o',str(exe)],check=True,capture_output=True,text=True)
    output=subprocess.check_output([str(exe)],text=True)
    records=[dict(marker=_fields(s)[0],fields=_fields(s)[1]) for s in output.splitlines()]
    rows=extract_mldsa_sampling(records)
    assert len(rows)==6 and all(r['reason']=='sampling_buffer_incomplete' for r in rows[:5])
    assert rows[-1]['validity']=='valid' and rows[-1]['rejected']==2 and rows[-1]['iteration']=='9'
