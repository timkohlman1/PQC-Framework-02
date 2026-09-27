"""Bounded gateway-side appliance control, using installed mosquitto clients.

Executed by the framework over its configured gateway; standard library only.
Never builds, resets, flashes, or configures the appliance.
"""
import json
import os
import selectors
import subprocess
import sys
import time

PREFIX = "pqc/control/instrument/energy/"


def healthy(status, token):
    try:
        return (status.get("source") == "energy" and status.get("status") == "ready"
                and status.get("association_token") == token
                and status.get("sensor_online") is True and status.get("sensor_valid") is True
                and status.get("acquisition") == "continuous"
                and 0 <= status["status_timestamp_us"] - status["sample_timestamp_us"] < 100000
                and status["ring_capacity_samples"] >= 2 and status["ring_used_samples"] >= 1
                and status["sample_record_bytes"] > 0
                and status["ring_allocated_bytes"] == status["ring_capacity_samples"] * status["sample_record_bytes"])
    except (KeyError, TypeError):
        return False


def main(args):
    base = ["-h", args["host"], "-p", str(args["port"]), "-q", "1"]
    end = time.monotonic() + args["timeout"]

    def publish(topic, data, *, final_cleanup=False):
        remaining = 5 if final_cleanup else min(5, end - time.monotonic())
        if remaining <= 0:
            raise TimeoutError("Energy control deadline expired")
        subprocess.run(["mosquitto_pub", *base, "-r", "-t", PREFIX + topic,
                        *(["-n"] if not data else ["-m", data])], check=True, timeout=remaining)

    if args["action"] == "collect":
        publish("collect", json.dumps({"type": "collect", "source": "energy",
                "run_id": args["run_id"], "association_token": args["token"],
                "expected_intervals": args["intervals"]}))
        with open(args["stream"], encoding="utf-8") as stream:
            while time.monotonic() < end:
                position = stream.tell()
                line = stream.readline()
                if not line.endswith("\n"):
                    stream.seek(position)
                    time.sleep(.05)
                    continue
                try:
                    message = json.loads(line)
                    obj = message["payload"]
                    if isinstance(obj, dict) and "payload" in obj:
                        obj = obj["payload"]
                    if isinstance(obj, str):
                        obj = json.loads(obj)
                    if (message["topic"] == f'pqc/instrument/energy/{args["run_id"]}/complete'
                            and obj.get("run_id") == args["run_id"] and obj.get("source") == "energy"):
                        print(json.dumps(obj), flush=True)
                        return 0 if obj.get("type") == "complete" else 1
                except (ValueError, KeyError, TypeError):
                    continue
        print("Energy collection timed out", flush=True)
        return 1

    # The subscriber is started before publication. -d provides an explicit
    # SUBACK so a fast readiness reply cannot be lost in a subscribe race.
    process = subprocess.Popen(["mosquitto_sub", *base, "-d", "-t", PREFIX + "status"],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    buffer = b""
    subscribed = False
    last_publish = 0
    try:
        while time.monotonic() < end:
            now = time.monotonic()
            if subscribed and now - last_publish >= 1:
                if args["action"] == "cleanup":
                    publish("collect", "")
                publish("associate", args["token"])
                last_publish = now
            for key, _ in selector.select(.1):
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    raise RuntimeError("status subscriber exited")
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if b"received SUBACK" in line:
                        subscribed = True
                    try:
                        status = json.loads(line)
                    except ValueError:
                        continue
                    if healthy(status, args["token"]):
                        print(json.dumps(status), flush=True)
                        return 0
        print("No fresh healthy energy acknowledgement", flush=True)
        return 1
    finally:
        selector.close()
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        if args["action"] == "cleanup":
            # Clear even when fresh health cannot be established. A failed
            # cleanup must not leave a probe token/collect to replay later.
            try:
                publish("collect", "", final_cleanup=True)
            finally:
                publish("associate", "", final_cleanup=True)


if __name__ == "__main__":
    try:
        sys.exit(main(json.loads(sys.argv[1])))
    except Exception as exc:
        print(f"Energy control failed: {exc}", flush=True)
        sys.exit(1)
