"""Real CLI/pandas loading of synthetic packet and energy inputs; no hardware."""
import json
from pathlib import Path
import subprocess
import sys
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests'))
sys.path.insert(0,str(ROOT/'tests/unit'))
from test_energy_analysis import energy_run
from timing_dataset_support import reseal
from framework.run_evidence import register_artifact, sha256_file
from framework.packet_analysis import read_pcap
from framework.archive_table import load_archive
pytestmark=pytest.mark.integration


def test_cli_combines_packet_energy_and_recorded_data_without_mutating_sources(tmp_path):
    root=tmp_path/'raw';run=energy_run(root/'run')
    pcap=run/'gateway-network-capture.pcap'
    pcap.write_bytes((ROOT/'tests/fixtures/pcap/retransmission.pcap').read_bytes())
    _,packets=read_pcap(pcap);packet=packets[0]
    path=run/'resolved-case.json';snapshot=json.loads(path.read_text())
    snapshot['effective_non_secret_parameters']['mqtt'].update(enabled=True,
        broker={'port':packet.dst_port},orchestration={'host':packet.dst_ip})
    path.write_text(json.dumps(snapshot))
    path=run/'manifest.json';manifest=json.loads(path.read_text())
    register_artifact(manifest,result_dir=run,role='packet_capture',path=pcap,stage='synthetic',tool=__name__)
    path.write_text(json.dumps(manifest));reseal(run)
    before={p:sha256_file(p) for p in run.iterdir() if p.is_file()}
    notes=tmp_path/'notes.json';notes.write_text(json.dumps({
        'energy':{'electrical_boundary':'synthetic 5V load','evidence_reference':'fixture'},
        'network':{'client_ip':packet.src_ip,'evidence_reference':'fixture'}}))
    output=tmp_path/'flat'
    result=subprocess.run([sys.executable,str(ROOT/'scripts/export_archive_table.py'),
        '--results-root',str(root),'--output',str(output),'--annotations',str(notes)],
        text=True,capture_output=True,timeout=120)
    assert result.returncode==0,result.stdout+result.stderr
    row=load_archive(output,verify_sources=True).iloc[0]
    assert row['energy__whole_workload__energy_j']==pytest.approx(.0015)
    assert row['packet__client_to_server__packets']>0
    assert row['packet__client_to_server__overlap_bytes']>0
    assert row['recorded__PQC_RM2_METRICS__received_bytes']==20
    assert all(sha256_file(p)==digest for p,digest in before.items())
    result=subprocess.run([sys.executable,str(ROOT/'scripts/export_archive_table.py'),
        '--check',str(output),'--verify-sources'],text=True,capture_output=True,timeout=120)
    assert result.returncode==0,result.stdout+result.stderr


def test_cli_shared_application_columns_chart_plaintext_classical_and_hybrid(tmp_path):
    from test_archive_table import comparison_run
    from timing_dataset_support import EXPECTED
    for name,kex,mode in (
        ('plaintext','secp256r1','plaintext'),
        ('classical','secp256r1','classical_tls_server_auth'),
        ('hybrid','SecP256r1MLKEM768','pqc_hybrid_tls_server_auth')):
        comparison_run(tmp_path/'raw',name,kex,mode)
    output=tmp_path/'flat'
    result=subprocess.run([sys.executable,str(ROOT/'scripts/export_archive_table.py'),
        '--results-root',str(tmp_path/'raw'),'--output',str(output)],
        text=True,capture_output=True,timeout=120)
    assert result.returncode==0,result.stdout+result.stderr
    frame=load_archive(output,verify_sources=True)
    assert len(frame)==3 and frame['run_key'].nunique()==3
    assert frame['run_success'].all() and frame['selected_inputs_valid'].all()
    for metric in ('mqtt_readiness','rtfb','rtlb','ttfb','ttlb','req_tfb','req_tlb'):
        assert list(frame['timing__'+metric+'_us'])==[EXPECTED[metric]]*3
    assert frame.loc[frame.transport_mode.eq('plaintext'),'timing__tls_handshake_us'].isna().all()
    # A direct groupby on treatment fields feeds a chart; no melting metric names.
    chart=frame.groupby(['transport_mode','tls_kex','tls_auth','auth_mode'],dropna=False)[
        ['timing__ttlb_us','timing__rtlb_us']].median()
    assert len(chart)==3
    assert ('plaintext','not_applicable','not_applicable','not_applicable') in chart.index
    import matplotlib
    matplotlib.use('Agg')
    ax=chart.plot.bar(); ax.figure.savefig(tmp_path/'comparison.png')
    assert (tmp_path/'comparison.png').stat().st_size>0
