"""Wait for a passive ESP32 capture that matches the STM32 GPIO window.

Executed on the gateway; standard library only. It never publishes MQTT
commands. The common result collector has already subscribed to the STM32
run-scoped results and the ESP32 fixed capture topic, so this helper only reads
that growing file until both sides expose a duration-compatible edge pair.
"""
import base64
import json
import re
import sys
import time

COMPLETE_TOPIC = "pqc/instrument/energy/capture/complete"
CAPTURE_ID = re.compile(r"[0-9a-f]{16}")
BOUNDARY = re.compile(r"(\w+)=([^\s]+)")


def _payload(line):
    message = json.loads(line)
    payload = message.get("payload")
    if isinstance(payload, dict) and "payload" in payload:
        payload = payload["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return str(message.get("topic", "")), payload


def _chunk_bytes(obj):
    if "data_hex" in obj:
        return bytes.fromhex(obj["data_hex"])
    if "data_b64" in obj:
        return base64.b64decode(obj["data_b64"], validate=True)
    raise ValueError("chunk encoding missing")


def _scan(path, run_id):
    stm32_chunks = {}
    boundaries = []
    completions = []
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            if not line.endswith("\n"):
                continue
            try:
                topic, obj = _payload(line)
            except (ValueError, KeyError, TypeError):
                continue
            if not isinstance(obj, dict):
                continue
            if topic == COMPLETE_TOPIC:
                if (obj.get("type") == "complete" and obj.get("source") == "energy"
                        and obj.get("schema") == 1
                        and CAPTURE_ID.fullmatch(str(obj.get("capture_id", "")))):
                    completions.append(obj)
                continue
            stm32_prefix = f"pqc/result/stm32/{run_id}/"
            if not topic.startswith(stm32_prefix):
                continue
            if obj.get("source") != "stm32" or obj.get("run_id") != run_id:
                continue
            if obj.get("type") == "chunk":
                try:
                    stm32_chunks[int(obj["sequence"])] = _chunk_bytes(obj)
                except (ValueError, KeyError, TypeError):
                    pass
                continue
            if obj.get("type") != "complete":
                continue
            try:
                count = int(obj["chunk_count"])
                if set(stm32_chunks) != set(range(count)):
                    stm32_chunks = {}
                    continue
                logical = b"".join(stm32_chunks[i] for i in range(count))
                for raw in logical.splitlines():
                    record = json.loads(raw)
                    if isinstance(record, dict) and record.get("context") == "energy_boundary":
                        values = dict(BOUNDARY.findall(str(record.get("text", ""))))
                        if values.get("scope") == "experiment" and values.get("valid") == "1":
                            boundaries.append((int(values["s0_us"]), int(values["s1_us"])))
            except (ValueError, KeyError, TypeError):
                pass
            stm32_chunks = {}
    return boundaries, completions


def _compatible(stm32, energy):
    try:
        s0, s1 = stm32
        e0, e1 = int(energy["e0_us"]), int(energy["e1_us"])
        stm_duration = s1 - s0
        esp_duration = e1 - e0
        tolerance = max(5000, stm_duration // 100)  # 5 ms or 1%
        return stm_duration > 0 and esp_duration > 0 and abs(stm_duration - esp_duration) <= tolerance
    except (KeyError, TypeError, ValueError):
        return False


def main(args):
    end = time.monotonic() + float(args["timeout"])
    while time.monotonic() < end:
        try:
            boundaries, completions = _scan(args["stream"], str(args["run_id"]))
            if len(boundaries) == 1:
                for completion in reversed(completions):
                    if _compatible(boundaries[0], completion):
                        print(json.dumps(completion), flush=True)
                        return 0
        except OSError:
            pass
        time.sleep(0.1)
    print("Energy capture completion timed out", flush=True)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main(json.loads(sys.argv[1])))
    except Exception as exc:
        print(f"Energy wait failed: {exc}", flush=True)
        sys.exit(1)
