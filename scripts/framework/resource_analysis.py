"""A3 offline resources: bytes, regional accounting, build and run lifetimes.

Opt-in companion to A1/A2. Never modifies captures or invokes a toolchain.
Only manifest-selected scalar records and hash-matched application ELF/bin
artifacts are read; bootloader/signing/credential artifacts are not followed.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from statistics import median

from framework.analysis_paths import result_path
from framework.run_evidence import sha256_file
from framework.timing_dataset import DatasetError, _has_symlink, _verify_header, read_json, verify_source_inputs
from framework.timing_metrics import decode_epochs, uint

VERSION = "1.2.0"
# Metric -> (region, accounting meaning). Subsets overlap their backing reservations.
STATIC = {
    "application_static_demand_bytes": ("application", "static_storage_minus_pool_backing_and_identified_experiment_storage"),
    "excluded_experiment_storage_bytes": ("instrumentation", "identified_experiment_storage_excluded_from_ram_estimate"),
    "configured_application_ram_bytes": ("application", "disjoint_linker_reservations_including_1KiB_L4R5_mailbox"),
    "mailbox_reserved_bytes": ("RAM2", "maintained_L4R5_handoff_reservation"),
    "freertos_heap_reserved_bytes": ("RAM/heap_4", "backing_array_subset_of_static_storage"),
    "tls_instrumentation_reserved_bytes": ("RAM", "identified_instrumentation_objects_subset_of_static_storage"),
    "flash_section_bytes": ("FLASH", "loadable_section_bytes"),
    "application_image_span_bytes": ("FLASH", "image_address_span_including_gaps"),
    "application_binary_bytes": ("FLASH", "retained_binary_file_size"),
    "ram_static_base_bytes": ("RAM", "static_storage_including_heap_backing"),
    "ram_linker_reserved_bytes": ("RAM", "static_and_minimum_heap_msp_reservation"),
    "ram2_section_bytes": ("RAM2", "allocated_section_storage"),
    "ram3_section_bytes": ("RAM3", "allocated_section_storage"),
    "result_buffer_reserved_bytes": ("RAM3", "reservation_subset_of_ram3"),
    "workspace_reserved_bytes": ("RAM3", "reservation_subset_of_ram3"),
}
RUNTIME = {
    "freertos_heap_total_bytes": ("RAM/heap_4", "reservation_within_static_storage"),
    "freertos_heap_peak_used_bytes": ("RAM/heap_4", "run_lifetime_peak_allocation_including_dynamic_task_stacks"),
    "freertos_heap_min_free_bytes": ("RAM/heap_4", "run_lifetime_minimum_free"),
    "freertos_heap_final_used_bytes": ("RAM/heap_4", "current_allocation_at_checkpoint_including_dynamic_task_stacks"),
    "freertos_heap_final_free_bytes": ("RAM/heap_4", "current_free_at_checkpoint"),
    "sbrk_capacity_bytes": ("RAM/newlib", "capacity_not_use"),
    "sbrk_peak_used_bytes": ("RAM/newlib", "run_lifetime_peak_allocation"),
    "sbrk_final_used_bytes": ("RAM/newlib", "current_allocation_at_checkpoint"),
    "msp_reserved_bytes": ("RAM/MSP", "linker_minimum_reservation"),
    "msp_peak_used_bytes": ("RAM/MSP", "watermark_since_main_excludes_startup"),
    "msp_measurement_window_bytes": ("RAM/MSP", "observable_window_not_use"),
    "mldsa_workspace_total_bytes": ("RAM3/workspace", "reservation_within_ram3"),
    "mldsa_workspace_peak_used_bytes": ("RAM3/workspace", "run_lifetime_maximum_requested_capacity"),
}
TLS = {name: ("RAM/task_stack" if name.startswith("stack") else "RAM/heap_4",
              "lifetime_minimum_free_at_handshake_checkpoint" if "min" in name else "current_free_at_handshake_checkpoint")
       for name in ("stack_before_min_free_bytes", "stack_after_min_free_bytes", "heap_before_free_bytes",
                    "heap_after_free_bytes", "heap_before_min_ever_free_bytes", "heap_after_min_ever_free_bytes")}
TOTAL_REASON = "independent_regional_peaks_are_not_a_simultaneous_system_peak; heap_and_task_stacks_overlap_static_storage; RAM3_result_buffer_and_startup_limits_apply"


def _union(intervals):
    end, total = -1, 0
    for low, high in sorted(intervals):
        if low < 0 or high < low:
            raise ValueError("invalid_address_interval")
        total += max(0, high - max(low, end))
        end = max(end, high)
    return total


def elf_resources(data, *, objects_out=None):
    """Bounded ELF32 little-endian ARM EXEC decoder for maintained L4 layouts.

    Count allocated sections by VMA; Flash by section LMA, not segment padding,
    debug sections or ELF file length. Region boundaries come from ELF symbols.
    """
    def unpack(fmt, offset):
        if offset < 0 or offset + struct.calcsize(fmt) > len(data):
            raise ValueError("truncated_elf")
        return struct.unpack_from(fmt, data, offset)
    def block(offset, size):
        if offset < 0 or size < 0 or offset + size > len(data):
            raise ValueError("truncated_elf")
        return data[offset:offset + size]
    if data[:7] != b"\x7fELF\x01\x01\x01":
        raise ValueError("unsupported_elf_encoding")
    h = unpack("<HHIIIIIHHHHHH", 16)
    if h[0:2] != (2, 40) or h[2] != 1 or h[8] != 32 or h[10] != 40 or not 0 < h[11] <= 4096:
        raise ValueError("unsupported_elf_layout")
    sections = [unpack("<IIIIIIIIII", h[5] + i * 40) for i in range(h[11])]
    segments = [unpack("<IIIIIIII", h[4] + i * 32) for i in range(h[9])]
    def string(table, offset):
        if offset >= len(table) or b"\0" not in table[offset:]:
            raise ValueError("invalid_elf_string")
        return table[offset:table.index(b"\0", offset)].decode("ascii")
    names = sections[h[12]]
    names = block(names[4], names[5])
    symbols = {}
    objects = []
    owner_file = ""
    for s in sections:
        if s[1] != 2:
            continue
        if s[9] != 16 or s[5] % 16:
            raise ValueError("unsupported_symbol_table")
        table = sections[s[6]]
        strings = block(table[4], table[5])
        for offset in range(s[4], s[4] + s[5], 16):
            name, value, size, info, _, index = unpack("<IIIBBH", offset)
            label = string(strings, name)
            if info & 15 == 4:
                owner_file = label
            if index:
                symbols[label] = value
                if info & 15 == 1 and size:
                    objects.append((owner_file, label, value, value + size))
    regions = {r: (symbols[f"__{r.lower()}_region_start__"], symbols[f"__{r.lower()}_region_end__"])
               for r in ("RAM", "RAM2", "RAM3")}
    # This decoder intentionally supports only the maintained STM32L4R5 layout.
    if regions != {"RAM": (0x20000000, 0x20030000), "RAM2": (0x10000000, 0x10010000), "RAM3": (0x20040000, 0x200a0000)}:
        raise ValueError("unsupported_target_memory_regions")
    allocated = {r: [] for r in regions}
    flash, sizes = [], {}
    for s in sections:
        name, kind, flags, addr, off, size, *_ = s
        if not flags & 2 or not size:
            continue
        label = string(names, name)
        sizes[label] = size
        owner = next((r for r, (lo, hi) in regions.items() if lo <= addr and addr + size <= hi), None)
        if owner:
            allocated[owner].append((addr, addr + size))
        elif not 0x08000000 <= addr < addr + size <= 0x08200000:
            raise ValueError("unaccounted_allocated_section")
        if kind == 8:  # NOBITS: storage reservation, no Flash payload
            continue
        block(off, size)
        loads = [p for p in segments if p[0] == 1 and p[1] <= off and off + size <= p[1] + p[4]
                 and p[2] + off - p[1] == addr]
        if len(loads) != 1:
            raise ValueError("ambiguous_section_load_address")
        p = loads[0]; lma = p[3] + off - p[1]
        if not 0x08000000 <= lma < lma + size <= 0x08200000:
            raise ValueError("unsupported_nonflash_load_section")
        flash.append((lma, lma + size))
    if not flash:
        raise ValueError("no_flash_sections")
    low, high = regions["RAM"]
    if not low <= symbols["_end"] <= symbols["__user_heap_stack_end__"] <= high:
        raise ValueError("invalid_linker_ram_symbols")
    # The maintained relocated L4R5 layout reserves the first 1 KiB of RAM2
    # for boot/OTA handoff, even when no ELF section occupies it. This explicit
    # target-layout policy is not inferred from an empty RAM2 section table.
    mailbox = (regions["RAM2"][0], regions["RAM2"][0] + 1024)
    primary = symbols["__user_heap_stack_end__"] - low
    if any(a < low or b > low + primary for a, b in allocated["RAM"]):
        raise ValueError("ram_section_outside_linker_reservation")
    heap = [(a,b) for _,n,a,b in objects if n == "ucHeap" and low <= a < b <= symbols["_end"]]
    instrumentation = [(a,b) for owner,_,a,b in objects
                       if owner == "pqc_tls_instrumentation.c" and low <= a < b <= symbols["_end"]]
    if objects_out is not None:
        # Optional validated object lineage for separately versioned overhead analyses.
        # Restrict to SRAM; STT_FILE ownership is useful for local objects only.
        objects_out.extend(dict(owner=owner, name=name, start=a, end=b)
                           for owner,name,a,b in objects
                           if any(lo <= a < b <= hi for lo,hi in regions.values()))
    return dict(configured_application_ram_bytes=primary + _union([mailbox, *allocated["RAM2"]]) + _union(allocated["RAM3"]),
                mailbox_reserved_bytes=1024,
                freertos_heap_reserved_bytes=_union(heap) if heap else None,
                tls_instrumentation_reserved_bytes=_union(instrumentation) if instrumentation else None,
                flash_section_bytes=_union(flash), application_image_span_bytes=max(b for a,b in flash)-min(a for a,b in flash),
                ram_static_base_bytes=symbols["_end"]-low,
                ram_linker_reserved_bytes=symbols["__user_heap_stack_end__"]-low,
                ram2_section_bytes=_union(allocated["RAM2"]), ram3_section_bytes=_union(allocated["RAM3"]),
                result_buffer_reserved_bytes=sizes.get(".pqc_result_buffer", 0),
                workspace_reserved_bytes=sizes.get(".pqc_mldsa_workspace", 0))


PEAKS=('freertos_heap_peak_used_bytes','mldsa_workspace_peak_used_bytes','sbrk_peak_used_bytes','msp_peak_used_bytes')


def experiment_object(obj):
    owner,name=obj['owner'],obj['name']
    return (owner in ('pqc_tls_instrumentation.c','pqc_result_buffer.c','pqc_timebase.c','pqc_network_phases.c')
        or owner=='pqc_wolfmqtt_build_only.c' and name=='s_ready_metrics_2_snapshot'
        or owner=='main.c' and (name.startswith(('app_uart_line_','smoke_line.','status_line.'))))


def ram_estimate_components(values,objects):
    if values['freertos_heap_reserved_bytes'] is None:raise ValueError('heap backing symbol required')
    removed=[o for o in objects if experiment_object(o) and 0x20000000<=o['start']<o['end']<=0x20030000]
    overhead=_union([(o['start'],o['end']) for o in removed])
    static=(values['ram_static_base_bytes']-values['freertos_heap_reserved_bytes']-overhead+
        values['ram2_section_bytes']+values['ram3_section_bytes']-values['result_buffer_reserved_bytes']-values['workspace_reserved_bytes'])
    if static<0:raise ValueError('negative disjoint static demand')
    return dict(application_static_bytes=static,excluded_experiment_bytes=overhead+values['result_buffer_reserved_bytes']+values['mailbox_reserved_bytes'],
        primary_instrumentation_bytes=overhead,removed_objects=removed)


def ram_run_estimate(static,peaks):
    if any(type(peaks.get(k)) is not int or peaks[k]<0 for k in PEAKS):raise ValueError('valid unsaturated regional peaks required')
    return static+sum(peaks[k] for k in PEAKS)


def _read(path, inputs, expected=None, size=None):
    if _has_symlink(path):
        raise ValueError("symlink_resource_input_refused")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    inputs.append(dict(path=str(path), sha256=digest, size_bytes=len(data)))
    if expected is not None and digest != expected or size is not None and len(data) != size:
        raise ValueError("resource_hash_or_size_mismatch")
    return data


def _artifact(root, manifest, role, inputs):
    items = [a for a in manifest["artifacts"] if a.get("role") == role and a.get("acquisition", {}).get("status") == "available"]
    if len(items) != 1:
        raise ValueError("artifact_missing_or_ambiguous:" + role)
    item = items[0]; name = item.get("path")
    allowed = {"application_elf": "firmware.elf", "application_binary": "firmware.bin", "run_provenance": "run-provenance.json"}
    if role in allowed and name != allowed[role]:
        raise ValueError("unsupported_resource_artifact_path")
    if role == "diagnostic_uart" and (not isinstance(name, str) or Path(name).name != name or not name.startswith("uart") or not name.endswith(".log")):
        raise ValueError("unsupported_uart_path")
    if not item.get("sha256") or type(item.get("size_bytes")) is not int:
        raise ValueError("missing_resource_identity")
    return _read(root / name, inputs, item["sha256"], item["size_bytes"])


def _build_root(run):
    """Relocate the recorded /workspace results prefix only, never arbitrary paths."""
    root = result_path(run["input_path"])
    ref = run["build_references"].get("preparation_manifest") or run["build_references"].get("build_manifest")
    if not ref:
        return root
    results = next((p for p in root.parents if p.name == "results"), None)
    if results is None:
        raise ValueError("build_reference_outside_results")
    path = Path(ref)
    if path.is_relative_to("/workspace/results"):
        path = results / path.relative_to("/workspace/results")
    elif not path.is_absolute():
        repo = results.parent
        path = repo / path
    if ".." in path.parts or not path.is_relative_to(results) or path.name != "manifest.json":
        raise ValueError("unsafe_build_reference")
    return path.parent


def _row(metric, definition, value=None, reason=None, **lineage):
    return dict(metric=metric, region=definition[0], accounting=definition[1], value_bytes=value,
                unit="bytes", metric_version=VERSION, validity="unavailable" if value is None else "valid",
                reason=reason, **lineage)


def extract_resources(dataset):
    """Return build table, runtime observations, and hashes of consumed inputs.

    Build ID is the recorded ELF SHA-256, never a reusable build number. A failed
    deployment verification remains visible; static evidence proves only a build.
    """
    verify_source_inputs(dataset.metadata)
    builds, runtime, inputs = {}, [], []
    for run in dataset.runs:
        root = result_path(run["input_path"])
        firmware_id = run.get("firmware_sha256")
        build_id = None
        lineage = dict(run_key=run["run_key"], run_id=run["run_id"], build_id=build_id,
                       epoch_index=None, iteration_id=None, scope="run_lifetime", source_records=[], source_sha256=None)
        manifest = {}
        build_input_start = len(inputs)
        try:
            manifest = read_json(_read(root / "manifest.json", inputs, run["manifest_sha256"]))
            _verify_header(manifest)
            build_root = _build_root(run)
            bm = read_json(_read(build_root / "manifest.json", inputs))
            _verify_header(bm)
            elf = _artifact(build_root, bm, "application_elf", inputs)
            elf_hash = hashlib.sha256(elf).hexdigest()
            if firmware_id != elf_hash:
                # Secure-boot runs identify the signed image, not the ELF. Require
                # the preparation's explicit, hash-verified build/image linkage.
                provenance = read_json(_artifact(build_root, bm, "run_provenance", inputs))
                if provenance.get("schema") != {"name": "pqc-run-provenance", "version": 1}:
                    raise ValueError("unsupported_build_provenance")
                records = provenance.get("records", {})
                fw = records.get("firmware", {})
                role = fw.get("evidence_role")
                build_reference = records.get("build_reference")
                # Hardware-test builds deliberately have no normal-workflow
                # build_reference. Their hash-verified preparation provenance
                # records the ELF identity explicitly under records.build.
                build = records.get("build")
                if (build_reference is None and isinstance(build, dict)
                        and build.get("purpose") == "automated_test"
                        and build.get("artifact_identity_algorithm") == "sha256-elf"
                        and type(build.get("return_code")) is int and build["return_code"] == 0):
                    build_reference = {"artifact_sha256": build.get("artifact_identity")}
                if not isinstance(build_reference, dict):
                    raise ValueError("run_build_reference_unavailable")
                if (not firmware_id or fw.get("sha256") != firmware_id
                        or role not in ("signed_application", "application_binary")
                        or build_reference.get("artifact_sha256") != elf_hash
                        or not any(a.get("role") == role and a.get("sha256") == firmware_id
                                   and a.get("acquisition", {}).get("status") == "available" for a in bm["artifacts"])):
                    raise ValueError("run_build_hash_mismatch")
            objects = []
            values = elf_resources(elf, objects_out=objects)
            estimate_components = None
            try:
                estimate_components = ram_estimate_components(values, objects)
                values['application_static_demand_bytes'] = estimate_components['application_static_bytes']
                values['excluded_experiment_storage_bytes'] = estimate_components['excluded_experiment_bytes']
            except (ValueError, KeyError, TypeError):
                pass  # Missing reservation symbols do not invalidate Flash sizes.
            build_id = elf_hash
            lineage["build_id"] = build_id
            binary_reason = None
            try:
                binary = _artifact(build_root, bm, "application_binary", inputs)
                values["application_binary_bytes"] = len(binary)
            except (OSError, ValueError, TypeError, KeyError):
                binary_reason = "retained_application_binary_unavailable_or_invalid"
            reason = None
        except (OSError, ValueError, TypeError, KeyError, IndexError, struct.error, UnicodeError):
            values, reason, binary_reason = {}, "verified_supported_application_elf_unavailable", None
        key = build_id or "unidentified:" + run["run_key"]
        entry = builds.setdefault(key, dict(build_id=build_id, run_keys=[], firmware_identities=[], build_numbers=[], build_references=[], source_inputs=[], resources=[]))
        if reason is None and estimate_components is not None:
            entry["ram_estimate_exclusions"] = estimate_components["removed_objects"]
        entry["source_inputs"].extend(inputs[build_input_start:])
        entry["run_keys"].append(run["run_key"])
        entry["firmware_identities"].append(firmware_id)
        entry["build_numbers"].append(run.get("build_number"))
        entry["build_references"].append(run["build_references"])
        candidate = [_row(m, d, values.get(m), reason or (binary_reason if m == "application_binary_bytes" else ("symbol_evidence_unavailable" if values.get(m) is None else None)),
                          scope="build", build_id=build_id) for m,d in STATIC.items()]
        if not entry["resources"] or (reason is None and entry["resources"][0]["value_bytes"] is None):
            entry["resources"] = candidate
        elif reason is None and any(a["value_bytes"] != b["value_bytes"] for a,b in zip(entry["resources"], candidate)):
            # Different retained binary representations must not become repeated samples.
            for a,b in zip(entry["resources"], candidate):
                if a["value_bytes"] != b["value_bytes"]:
                    a.update(value_bytes=None, validity="unavailable", reason="conflicting_build_resource_evidence")
        # Diagnostic task checkpoints are observations, never added to heap peaks.
        try:
            uart = _artifact(root, manifest, "diagnostic_uart", inputs)
            from framework.timing_metrics import _fields
            for line_number, line in enumerate(uart.decode("utf-8").splitlines(), 1):
                prefix = "application task stack: "
                if not line.startswith(prefix):
                    continue
                _, fields = _fields("TASK " + line[len(prefix):])
                task, stage = fields.get("task"), fields.get("stage")
                if task not in ("defaultTask", "networkTask") or stage not in ("default_task_start", "default_task_runtime", "network_task_start", "network_task_runtime", "network_task_complete"):
                    continue
                for key, accounting in (("total_bytes", "allocated_task_stack_within_heap"),
                        ("minimum_free_bytes", "task_lifetime_minimum_free"), ("peak_used_bytes", "task_lifetime_watermark")):
                    try:
                        total, free, peak = (uint(fields.get(k)) for k in ("total_bytes", "minimum_free_bytes", "peak_used_bytes"))
                        if free + peak != total:
                            raise ValueError("inconsistent_task_stack_accounting")
                        value, why = uint(fields[key]), None
                    except ValueError:
                        value, why = None, "task_stack_unavailable_or_inconsistent"
                    runtime.append(_row("task_stack_" + key, ("RAM/task_stack", accounting), value, why,
                        **dict(lineage, scope="task_lifetime_checkpoint", task=task, stage=stage,
                            source_sha256=hashlib.sha256(uart).hexdigest(), source_records=[{"line": line_number}])))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            pass
        records = []
        runtime_reason = "memory_not_recorded"
        if run["selected_input_status"] == "verified":
            try:
                source = root / "mqtt-reporting-raw.ndjson"
                # A1 metadata verification above establishes the retained stream hash.
                epochs, errors = decode_epochs(source, run["run_id"])
                source_hash = sha256_file(source)
                if errors:
                    raise ValueError("invalid_stream")
                for epoch in epochs:
                    if epoch.errors:
                        continue
                    for rec in epoch.records:
                        fields = dict(rec["fields"])
                        if rec["context"] == "memory" and rec["marker"].startswith("freertos_heap_total_bytes="):
                            fields["freertos_heap_total_bytes"] = rec["marker"].split("=",1)[1]
                            kind = "memory"
                        elif rec["marker"] == "PQC_TLS_HANDSHAKE_MEMORY" and rec["context"] == "tls":
                            kind = "tls"
                        else:
                            continue
                        records.append((kind, fields, dict(lineage, epoch_index=epoch.index,
                            iteration_id=rec["iteration"] if kind == "tls" else None,
                            scope="lifetime_checkpoint_at_handshake" if kind == "tls" else "run_lifetime",
                            source_records=[rec["ref"]], source_sha256=source_hash, logical_sha256=epoch.logical_sha256)))
            except (OSError, ValueError, TypeError, KeyError):
                runtime_reason = "memory_stream_unavailable_or_invalid"
        else:
            runtime_reason = "selected_inputs_not_valid"
        if not any(k == "memory" for k,_,_ in records):
            runtime.extend(_row(m, d, reason=runtime_reason, **lineage) for m,d in RUNTIME.items())
        if not any(k == "tls" for k,_,_ in records):
            runtime.extend(_row(m, d, reason="handshake_memory_not_recorded", **dict(lineage, scope="lifetime_checkpoint_at_handshake")) for m,d in TLS.items())
        for kind, fields, ref in records:
            definitions = RUNTIME if kind == "memory" else TLS
            for metric, definition in definitions.items():
                try:
                    if metric == "freertos_heap_final_used_bytes":
                        value = uint(fields.get("freertos_heap_total_bytes")) - uint(fields.get("freertos_heap_final_free_bytes"))
                    else:
                        value = uint(fields.get(metric))
                    why = None
                    if metric == "msp_peak_used_bytes":
                        flag = uint(fields.get("msp_measurement_saturated"))
                        if flag not in (0, 1):
                            raise ValueError("invalid_saturation_flag")
                        if flag:
                            why = "lower_bound_observable_window_exhausted"
                    if kind == "memory" and metric.startswith("freertos_"):
                        total = uint(fields.get("freertos_heap_total_bytes"))
                        peak = uint(fields.get("freertos_heap_peak_used_bytes"))
                        minimum = uint(fields.get("freertos_heap_min_free_bytes"))
                        final = uint(fields.get("freertos_heap_final_free_bytes"))
                        if peak + minimum != total or not minimum <= final <= total:
                            raise ValueError("inconsistent_heap_accounting")
                except ValueError as exc:
                    value, why = None, str(exc)
                row = _row(metric, definition, value, why, **ref)
                if why == "lower_bound_observable_window_exhausted":
                    row["validity"] = "lower_bound"
                runtime.append(row)
        peak_rows = [r for r in runtime if r['run_key'] == run['run_key'] and r['scope'] == 'run_lifetime' and r['metric'] in PEAKS]
        try:
            if values.get('application_static_demand_bytes') is None:
                raise ValueError('verified_static_demand_unavailable')
            if len(peak_rows) != len(PEAKS) or {r['metric'] for r in peak_rows} != set(PEAKS) or any(r['validity'] != 'valid' for r in peak_rows):
                raise ValueError('unique_valid_unsaturated_regional_peaks_required')
            estimate = ram_run_estimate(values['application_static_demand_bytes'], {r['metric']: r['value_bytes'] for r in peak_rows})
            why = None
        except (ValueError, TypeError) as exc:
            estimate, why = None, str(exc)
        runtime.append(_row('peak_based_ram_estimate_bytes', ('application', 'within_run_regional_peaks_plus_static_minus_identified_experiment_storage'),
            estimate, why, **dict(lineage, source_records=[ref for r in peak_rows for ref in r['source_records']])))
        runtime.append(_row("simultaneous_system_peak_bytes", ("device", "observed_simultaneous_peak"), reason=TOTAL_REASON, **lineage))
    verify_source_inputs(dataset.metadata)
    for source in inputs:
        if sha256_file(Path(source["path"])) != source["sha256"]:
            raise DatasetError("resource_input_changed_during_analysis")
    return dict(builds=list(builds.values()), runtime=runtime, inputs=sorted({(i["path"],i["sha256"]):i for i in inputs}.values(), key=lambda i:(i["path"],i["sha256"])))


def summarise_resources(dataset, spec):
    """Descriptive build/run medians with A2's matching rules; no pooled peaks."""
    import pandas as pd
    from framework.timing_summary import (summarise, CORE_CONTROLS, OBSERVED_CONTROLS, leaves, field, comparison_field)
    timing_frames, normalized = summarise(dataset, spec)
    extracted = extract_resources(dataset)
    inventory = timing_frames["inventory"].to_dict("records")
    build_rows = []
    for build in extracted["builds"]:
        for resource in build["resources"]:
            build_rows.append({**{k:v for k,v in build.items() if k != "resources"}, **resource})
    rows, differences = [], []
    definitions = {**STATIC, **RUNTIME,
        "peak_based_ram_estimate_bytes": ("application", "within_run_regional_peaks_plus_static_minus_identified_experiment_storage"),
        "simultaneous_system_peak_bytes": ("device", "observed_simultaneous_peak")}
    groups = {name: [r for r in inventory if r["condition"] == name and not r["exclusion_reason"]]
              for name in normalized["conditions"]}
    for label, runs in groups.items():
        keys = {r["run_key"] for r in runs}
        successful = {r["run_key"] for r in runs if r["execution_outcome"] == "completed" and r["selected_input_status"] == "verified"}
        for metric, definition in definitions.items():
            if metric in STATIC:
                candidates = [r for r in build_rows if r["metric"] == metric and keys.intersection(r["run_keys"])]
                usable = [r for r in candidates if r["validity"] == "valid"]
                unit = "unique_build"
                ids = [r["build_id"] for r in usable]
                contributing = sorted({k for r in usable for k in r["run_keys"] if k in keys})
            else:
                candidates = [r for r in extracted["runtime"] if r["metric"] == metric and r["run_key"] in keys]
                # Repeated epochs or duplicate final records do not become independent runs.
                counts = {k:sum(r["run_key"] == k for r in candidates) for k in keys}
                usable = [r for r in candidates if r["validity"] == "valid" and r["run_key"] in successful and counts[r["run_key"]] == 1]
                unit = "run_lifetime"
                ids = [r["run_key"] for r in usable]
                contributing = sorted(ids)
            if metric == 'peak_based_ram_estimate_bytes' and len({r['build_id'] for r in usable}) != 1:
                usable, ids, contributing = [], [], []
            values = [r["value_bytes"] for r in usable]
            value = median(values) if values else None
            rows.append(dict(condition=label, metric=metric, region=definition[0], accounting=definition[1],
                unit="bytes", sample_unit=unit, median_bytes=value, median_KiB=value/1024 if value is not None else None,
                maximum_bytes=max(values) if values else None,
                summary_bytes=(max(values) if metric == 'peak_based_ram_estimate_bytes' else value) if values else None,
                summary_statistic='maximum_per_run_estimate' if metric == 'peak_based_ram_estimate_bytes' else 'median',
                n_observations=len(values), unavailable_or_excluded=len(candidates)-len(values),
                observation_ids=ids, run_keys=contributing, reason=None if values else "no_unambiguous_usable_resource_evidence"))
    baseline = normalized["baseline"]
    for label, runs in groups.items():
        if label == baseline:
            continue
        reference = groups[baseline]
        controls = set(CORE_CONTROLS) | set(normalized["controls"])
        for run in runs + reference:
            controls |= leaves(run.get("controls", {}))
        controls -= OBSERVED_CONTROLS | set(normalized["treatment"]) | set(normalized["not_applicable"])
        problems = [] if runs and reference else ["empty_condition_or_baseline"]
        for key in sorted(controls):
            values = [comparison_field(r,key,normalized) for r in runs + reference]
            if any(v is None or v == {} or v == "" for v in values):
                problems.append("unknown_control:" + key)
            elif len({json.dumps(v,sort_keys=True) for v in values}) > 1:
                problems.append("conflicting_control:" + key)
        for metric in definitions:
            a = next(r for r in rows if r["condition"] == baseline and r["metric"] == metric)
            b = next(r for r in rows if r["condition"] == label and r["metric"] == metric)
            reason = ";".join(problems) or a["reason"] or b["reason"]
            delta = None if reason else b["summary_bytes"]-a["summary_bytes"]
            percent_reason = reason or ("zero_baseline" if a["summary_bytes"] == 0 else None)
            differences.append(dict(condition=label, baseline=baseline, metric=metric, unit="bytes",
                delta_median_bytes=None if metric == 'peak_based_ram_estimate_bytes' else delta,
                delta_summary_bytes=delta, statistic=b['summary_statistic'],
                percent_difference=None if percent_reason else 100*delta/a["summary_bytes"],
                reason=reason, percent_reason=percent_reason, baseline_observation_ids=a["observation_ids"],
                treatment_observation_ids=b["observation_ids"], baseline_run_keys=a["run_keys"], treatment_run_keys=b["run_keys"]))
    frames = {"resource_builds": pd.DataFrame(build_rows, dtype=object),
              "resource_observations": pd.DataFrame(extracted["runtime"], dtype=object),
              "resource_distributions": pd.DataFrame(rows, dtype=object),
              "resource_differences": pd.DataFrame(differences, columns=["condition", "baseline", "metric", "unit",
                  "delta_median_bytes", "delta_summary_bytes", "statistic", "percent_difference", "reason", "percent_reason", "baseline_observation_ids",
                  "treatment_observation_ids", "baseline_run_keys", "treatment_run_keys"], dtype=object)}
    provenance = dict(version=VERSION, inputs=extracted["inputs"], definitions={**STATIC, **RUNTIME, **TLS},
        source_sha256=sha256_file(Path(__file__)), conversion="1 KiB = 1024 bytes",
        statistics="descriptive median across unique builds or one final lifetime record per successful run; RAM estimate is maximum across same-run regional estimates; no resource confidence intervals",
        combined_total_policy=TOTAL_REASON, deployment="ELF identity association is not proof that firmware was flashed or executed")
    return frames, provenance
