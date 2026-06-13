import csv
import json
import textwrap
import time

from controllers.system_controller import SystemController
from helpers.protocol import Command


def write_config(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            f"""
            runtime:
              test_mode: true
              results_dir: "{tmp_path.as_posix()}/results"

            mqtt:
              broker: localhost

            timing:
              trial_lead_time_s: 0.1
              trial_timeout_s: 0.1
              trial_interval_s: 1.0
              pre_trigger_s: 0.01
              capture_time_s: 0.02

            nodes:
              tx:
                "0":
                  serial: "TX000"
                  external_clock: false
                  external_time_source: false
              rx:
                "0":
                  serial: "RX000"
                  external_clock: false
                  external_time_source: false

            targets:
              tc1:
                rx_id: "0"

            beamforming:
              mode: optimize
              target: tc1
              tx_array_order: ["0"]
              scan_angles_deg: [0, 30]
              repeats_per_angle: 1
              tx_signal_amplitude: 0.7

            calibration:
              enabled: false
            """
        ),
        encoding="utf-8",
    )
    return config_path


def test_system_trial_flow_groups_results_by_trial_id(tmp_path):
    controller = SystemController(config_path=write_config(tmp_path))
    sent = []
    controller.send_message = lambda cmd, payload=None: sent.append((cmd, payload or {}))

    controller.start_sent = True
    controller.start_time_stamp = time.time()
    controller._start_next_trial()

    assert sent[0][0] == Command.RX_CAPTURE
    assert sent[1][0] == Command.TX_PULSE
    assert sent[0][1]["trial_id"] == 1
    assert sent[1][1]["trial_id"] == 1
    assert controller.active_trial["trial_id"] == 1

    controller.on_message({
        "src": "tx",
        "id": "0",
        "cmd": Command.TX_DONE.value,
        "payload": {
            "trial_id": 1,
            "target_time": sent[1][1]["target_time"],
            "samples_requested": 10,
            "samples_sent": 10,
            "late": False,
        },
    })

    controller.on_message({
        "src": "rx",
        "id": "0",
        "cmd": Command.RX_METRIC.value,
        "payload": {
            "trial_id": 1,
            "rx_id": "0",
            "target_time": sent[1][1]["target_time"],
            "power_linear": 2.0,
            "power_db": 3.0103,
            "detected_time": sent[1][1]["target_time"],
            "offset_ms": 0.0,
            "samples_used": 10,
        },
    })

    assert controller.active_trial is None

    with open(controller.trial_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    assert rows[0]["trial_id"] == "1"
    assert rows[0]["status"] == "OK"
    assert rows[0]["target"] == "tc1"
    assert rows[0]["target_rx_id"] == "0"
    assert rows[0]["updated_beamforming"] == "True"

    rx_metrics = json.loads(rows[0]["rx_metrics"])
    tx_statuses = json.loads(rows[0]["tx_statuses"])
    assert rx_metrics["0"]["power_linear"] == 2.0
    assert tx_statuses["0"]["samples_sent"] == 10

