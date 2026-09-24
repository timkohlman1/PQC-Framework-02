"""Host-only behavioural tests of the portable measurement core."""
import ctypes
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def library(tmp_path_factory):
    cc = shutil.which("cc")
    if cc is None:
        pytest.skip("Host C compiler unavailable")
    out = tmp_path_factory.mktemp("benchmark") / "libbenchmark.so"
    subprocess.run(
        [cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
         "-I", str(ROOT / "Core/Inc"),
         str(ROOT / "Core/Src/pqc_baremetal_benchmark.c"), "-o", str(out)],
        check=True,
    )
    return ctypes.CDLL(str(out))


class Record(ctypes.Structure):
    _fields_ = [("operation", ctypes.c_char * 32), ("parameter", ctypes.c_char * 24),
                ("iteration", ctypes.c_uint32), ("cycles", ctypes.c_uint32),
                ("operation_result", ctypes.c_int32), ("outcome", ctypes.c_int),
                ("interrupts_masked", ctypes.c_uint8)]


class Store(ctypes.Structure):
    _fields_ = [("records", Record * 96), ("count", ctypes.c_uint32),
                ("dropped", ctypes.c_uint32), ("overflowed", ctypes.c_uint8)]


CYCLES = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_void_p)
MASK = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_void_p)
RESTORE = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint32)
OP = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)
EMIT = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_char_p)


class Hooks(ctypes.Structure):
    _fields_ = [("cycles", CYCLES), ("irq_save_disable", MASK),
                ("irq_restore", RESTORE), ("operation", OP),
                ("context", ctypes.c_void_p)]


def test_measurement_order_wrap_failure_and_post_reporting(library):
    events = []
    ticks = iter((0xFFFFFFF0, 0x10, 1, 7))
    callbacks = [CYCLES(lambda _: events.append("cycle") or next(ticks)),
                 MASK(lambda _: events.append("mask") or 1),
                 RESTORE(lambda _, p: events.append(("restore", p))),
                 OP(lambda _: events.append("operation") or 0)]
    hooks = Hooks(*callbacks, None)
    store = Store()
    library.PQC_BenchmarkReset(ctypes.byref(store))
    library.PQC_BenchmarkRun.argtypes = [ctypes.POINTER(Store), ctypes.c_char_p,
                                          ctypes.c_char_p, ctypes.c_uint32,
                                          ctypes.POINTER(Hooks), ctypes.c_bool]
    library.PQC_BenchmarkRun.restype = ctypes.c_bool
    assert library.PQC_BenchmarkRun(ctypes.byref(store), b"ML-KEM", b"768", 0,
                                     ctypes.byref(hooks), True)
    assert events == ["mask", "cycle", "operation", "cycle", ("restore", 1)]
    assert (store.count, store.records[0].cycles, store.records[0].outcome) == (1, 32, 0)
    assert library.PQC_BenchmarkRun(ctypes.byref(store), b"not_compiled", b"1024", 1,
                                     None, False)
    assert store.records[1].outcome == 1
    assert len(events) == 5
    lines = []
    reporter = EMIT(lambda i, context, text: lines.append(text.decode()) or True)
    library.PQC_BenchmarkReport.argtypes = [ctypes.POINTER(Store), EMIT]
    library.PQC_BenchmarkReport.restype = ctypes.c_bool
    assert library.PQC_BenchmarkReport(ctypes.byref(store), reporter)
    assert len(lines) == 3 and '"type":"complete"' in lines[-1]


def test_bounded_records_and_explicit_overflow(library):
    store = Store()
    library.PQC_BenchmarkReset(ctypes.byref(store))
    for i in range(96):
        assert library.PQC_BenchmarkRun(ctypes.byref(store), b"unavailable", b"x", i, None, False)
    assert not library.PQC_BenchmarkRun(ctypes.byref(store), b"unavailable", b"x", 65, None, False)
    assert (store.count, store.dropped, store.overflowed) == (96, 1, 1)


def test_setup_failure_is_explicit_and_not_fabricated(library):
    store = Store()
    library.PQC_BenchmarkReset(ctypes.byref(store))
    library.PQC_BenchmarkRecordFailure.argtypes = [
        ctypes.POINTER(Store), ctypes.c_char_p, ctypes.c_char_p,
        ctypes.c_uint32, ctypes.c_int,
    ]
    library.PQC_BenchmarkRecordFailure.restype = ctypes.c_bool
    assert library.PQC_BenchmarkRecordFailure(
        ctypes.byref(store), b"mlkem_keygen", b"ML_KEM_1024", 2, -55,
    )
    assert store.count == 1
    assert store.records[0].cycles == 0
    assert store.records[0].outcome == 2
    assert store.records[0].operation_result == -55
    lines = []
    reporter = EMIT(lambda i, context, text: lines.append(text.decode()) or True)
    library.PQC_BenchmarkReport.argtypes = [ctypes.POINTER(Store), EMIT]
    assert library.PQC_BenchmarkReport(ctypes.byref(store), reporter)
    import json
    first = json.loads(lines[0])
    assert first["reason"] == "cryptographic_operation_or_setup_failed"
    assert first["cycles"] == 0 and first["outcome"] == 2
