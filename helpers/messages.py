import json
import time

BUS_TOPIC = "signaltrack/bus"


def make_message(src, src_id, cmd, payload=None):
    return json.dumps({
        "src": src,
        "id": src_id,
        "cmd": cmd,
        "payload": payload or {},
        "timestamp": time.time(),
    }).encode("utf-8")


def parse_message(data):
    return json.loads(data.decode("utf-8"))
