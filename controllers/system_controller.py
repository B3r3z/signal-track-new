import csv
import json
import math
import os
import socket
import subprocess
import sys
import time

import numpy as np

from algorithms.beamforming import Beamforming
from algorithms.system_logic import SystemLogic
from controllers.controller import Controller
from helpers.csv_writer import CSVWriter
from helpers.protocol import Command, ExperimentState


class SystemController(Controller):

    def __init__(self, config_path=None):
        super().__init__("system", 0, config_path=config_path)

        self.beamforming = Beamforming(self.parameters)
        self.logic = SystemLogic(self.parameters, self.beamforming)

        self.state = ExperimentState.WAITING_FOR_COMPONENTS

        self.tx_registered = set()
        self.rx_registered = set()
        self.fsv_registered = set()

        self.tx_ready = set()
        self.rx_ready = set()
        self.fsv_ready = set()

        self.tx_ids = {str(x) for x in self.parameters.get_tx_ids()}
        self.rx_ids = {str(x) for x in self.parameters.get_rx_ids()}
        self.fsv_metric_mode = bool(
            self.parameters.fsv_enabled
            and self.parameters.fsv_required_for_beamforming
        )

        self.start_sent = False
        self._last_ready_state = None
        self.start_time_stamp = None
        self.sync_epoch_pc = None

        self.trial_id = 0
        self.last_target_time = -float(self.parameters.trial_interval_s)
        self.active_trial = None
        self.current_tx_command = self.beamforming.current_tx_command()

        self.calibration_queue = self._build_calibration_queue()

        self.csv = CSVWriter(self.parameters.results_dir)
        self.trial_csv = os.path.join(
            self.parameters.results_dir,
            "beamforming_trials.csv",
        )
        self._init_trial_csv()

    def _build_calibration_queue(self):
        if not self.parameters.calibration_enabled:
            return []

        commands = []
        tx_ids = sorted(self.tx_ids, key=lambda x: int(x))

        for tx_id in tx_ids:
            phase_map = {tid: 0.0 for tid in tx_ids}
            amplitude_map = {tid: 0.0 for tid in tx_ids}
            amplitude_map[tx_id] = float(self.parameters.tx_signal_amplitude)

            commands.append({
                "phase_map": phase_map,
                "amplitude_map": amplitude_map,
                "finished": False,
                "step": 0,
                "candidate_idx": None,
                "mode": "calibration",
                "beam_angle_deg": None,
                "best_metric": None,
                "calibration_tx_id": tx_id,
            })

        return commands

    def _init_trial_csv(self):
        os.makedirs(self.parameters.results_dir, exist_ok=True)

        header = [
            "trial_id",
            "target_time",
            "status",
            "beamforming_mode",
            "target",
            "target_rx_id",
            "beam_angle_deg",
            "candidate_idx",
            "phase_map",
            "amplitude_map",
            "rx_metrics",
            "tx_statuses",
            "fsv_metrics",
            "updated_beamforming",
            "failure_reason",
        ]

        with open(self.trial_csv, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(header)

    def on_connect(self, rc: int):
        self.log.info("System connected to MQTT")

    def on_message(self, m: dict):
        cmd = m.get("cmd")
        src = m.get("src")
        node_id = str(m.get("id"))
        payload = m.get("payload", {}) or {}

        if cmd == Command.REGISTER.value:
            self._handle_register(src, node_id)
            return

        if cmd == Command.READY.value:
            self._handle_ready(src, node_id)
            return

        if cmd in (Command.RX_METRIC.value, Command.METRIC.value) and src == "rx":
            self._handle_rx_metric(node_id, payload, legacy=(cmd == Command.METRIC.value))
            return

        if cmd in (Command.TX_DONE.value, Command.TX_ACTIVE.value) and src == "tx":
            self._handle_tx_done(node_id, payload, legacy=(cmd == Command.TX_ACTIVE.value))
            return

        if cmd == Command.FSV_PHASE_METRIC.value and src == "fsv":
            self._handle_fsv_metric(node_id, payload)

    def _handle_register(self, src, node_id):
        if src == "tx":
            self.tx_registered.add(node_id)
            self.log.info(f"TX REGISTERED | id={node_id}")
        elif src == "rx":
            self.rx_registered.add(node_id)
            self.log.info(f"RX REGISTERED | id={node_id}")
        elif src == "fsv":
            self.fsv_registered.add(node_id)
            self.log.info(f"FSV REGISTERED | id={node_id}")

    def _handle_ready(self, src, node_id):
        if src == "tx":
            self.tx_ready.add(node_id)
            self.log.info(f"TX READY | id={node_id}")
        elif src == "rx":
            self.rx_ready.add(node_id)
            self.log.info(f"RX READY | id={node_id}")
        elif src == "fsv":
            self.fsv_ready.add(node_id)
            self.log.info(f"FSV READY | id={node_id}")

        self._check_and_start()

    def _handle_rx_metric(self, rx_id, payload, legacy=False):
        trial_id = payload.get("trial_id")

        if trial_id is None and legacy:
            trial_id = self._trial_id_from_target_time(payload.get("target_time"))

        if trial_id is None:
            self.log.warning(f"[SYSTEM] Ignoring RX metric from RX{rx_id} without trial_id")
            return

        if self.active_trial is None or int(trial_id) != self.active_trial["trial_id"]:
            self.log.warning(
                f"[SYSTEM] Ignoring RX metric from RX{rx_id} for stale trial={trial_id}"
            )
            return

        power_db = payload.get("power_db", payload.get("avg_power_db", payload.get("value")))
        power_linear = payload.get(
            "power_linear",
            payload.get("avg_power_lin"),
        )

        if power_linear is None and power_db is not None:
            power_linear = 10.0 ** (float(power_db) / 10.0)

        metric = {
            "rx_id": str(rx_id),
            "target_time": payload.get("target_time"),
            "power_linear": float(power_linear),
            "power_db": (
                float(power_db)
                if power_db is not None
                else float(10.0 * np.log10(float(power_linear) + 1e-15))
            ),
            "detected_time": payload.get("detected_time"),
            "offset_ms": payload.get("offset_ms"),
            "samples_used": payload.get("samples_used"),
            "capture_ok": bool(payload.get("capture_ok", True)),
            "failure_reason": payload.get("failure_reason", ""),
        }

        self.active_trial["rx_metrics"][str(rx_id)] = metric
        if metric["capture_ok"]:
            self.log.info(
                f"[TRIAL {trial_id}] RX{rx_id} metric | "
                f"power={metric['power_db']:.2f} dB"
            )
        else:
            self.log.warning(
                f"[TRIAL {trial_id}] RX{rx_id} capture failed | "
                f"reason={metric['failure_reason']}"
            )
        self._maybe_finish_trial()

    def _handle_tx_done(self, tx_id, payload, legacy=False):
        trial_id = payload.get("trial_id")

        if trial_id is None and legacy:
            trial_id = self._trial_id_from_target_time(payload.get("target_time"))

        if trial_id is None:
            self.log.warning(f"[SYSTEM] Ignoring TX status from TX{tx_id} without trial_id")
            return

        if self.active_trial is None or int(trial_id) != self.active_trial["trial_id"]:
            self.log.warning(
                f"[SYSTEM] Ignoring TX status from TX{tx_id} for stale trial={trial_id}"
            )
            return

        self.active_trial["tx_statuses"][str(tx_id)] = {
            "tx_id": str(tx_id),
            "target_time": payload.get("target_time"),
            "samples_requested": payload.get(
                "samples_requested",
                payload.get("n_samples"),
            ),
            "samples_sent": payload.get("samples_sent", payload.get("n_samples")),
            "late": bool(payload.get("late", False)),
        }

        self.log.info(f"[TRIAL {trial_id}] TX{tx_id} status received")
        self._maybe_finish_trial()

    def _handle_fsv_metric(self, fsv_id, payload):
        trial_id = payload.get("trial_id")

        if self.active_trial is None or trial_id is None:
            return

        if int(trial_id) != self.active_trial["trial_id"]:
            return

        self.active_trial["fsv_metrics"][str(fsv_id)] = payload
        self.log.info(f"[TRIAL {trial_id}] FSV{fsv_id} metric received")
        self._maybe_finish_trial()

    def _trial_id_from_target_time(self, target_time):
        if self.active_trial is None:
            return None

        if target_time is None:
            return None

        if abs(float(target_time) - float(self.active_trial["target_time"])) < 1e-6:
            return self.active_trial["trial_id"]

        return None

    def _check_and_start(self):
        current_state = (len(self.tx_ready), len(self.rx_ready), len(self.fsv_ready))

        if current_state != self._last_ready_state:
            self.log.info(
                f"READY CHECK: TX {len(self.tx_ready)}/{len(self.tx_ids)}, "
                f"RX {len(self.rx_ready)}/{len(self.rx_ids)}, "
                f"FSV {len(self.fsv_ready)}/{'1' if self.fsv_metric_mode else '0'}"
            )
            self._last_ready_state = current_state

        if self.start_sent:
            return

        fsv_ready = (not self.fsv_metric_mode) or bool(self.fsv_ready)

        if self.tx_ready == self.tx_ids and self.rx_ready == self.rx_ids and fsv_ready:
            self.state = ExperimentState.SYNCING_CLOCKS
            self.sync_epoch_pc = math.ceil(time.time())
            self.log.info("All required components ready, sending SYNC_CLOCKS")
            self.send_message(
                Command.SYNC_CLOCKS,
                {"time_at_next_pps": 0.0},
            )

            wait_after_pps_s = 0.2
            wait_time_s = max(
                0.0,
                (self.sync_epoch_pc - time.time()) + wait_after_pps_s,
            )
            if wait_time_s > 0:
                time.sleep(wait_time_s)

            self.logic.start()
            self.current_tx_command = self.beamforming.current_tx_command()
            self.send_message(Command.START, {})
            self.start_sent = True
            self.start_time_stamp = self.sync_epoch_pc
            self.state = ExperimentState.READY_TO_MEASURE
            self.log.info("START sent, system ready to measure")

    def _next_target_time(self):
        if self.start_time_stamp is None:
            raise RuntimeError("System clock has not been synchronized yet")

        elapsed_hw = time.time() - self.start_time_stamp
        min_target = elapsed_hw + float(self.parameters.trial_lead_time_s)
        grid_target = self.last_target_time + float(self.parameters.trial_interval_s)
        target_time = max(min_target, grid_target)
        self.last_target_time = target_time
        return target_time

    def _start_next_trial(self):
        if self.calibration_queue:
            tx_command = self.calibration_queue.pop(0)
        else:
            tx_command = self.current_tx_command

        self.trial_id += 1
        target_time = self._next_target_time()
        target = str(self.parameters.beamforming_target)
        target_rx_id = (
            self.parameters.get_target_rx_id(target)
            if self.rx_ids
            else ""
        )

        self.active_trial = {
            "trial_id": self.trial_id,
            "target_time": target_time,
            "target": target,
            "target_rx_id": target_rx_id,
            "tx_command": tx_command,
            "rx_metrics": {},
            "tx_statuses": {},
            "fsv_metrics": {},
            "started_pc": time.time(),
            "status": "RUNNING",
            "failure_reason": "",
        }

        self.state = ExperimentState.ARMING_TRIAL

        self.log.info(
            f"[TRIAL {self.trial_id}] scheduling | "
            f"target_time={target_time:.6f} | mode={tx_command.get('mode')}"
        )

        capture_payload = {
            "trial_id": self.trial_id,
            "target_time": target_time,
            "pre_trigger_s": float(self.parameters.pre_trigger_s),
            "capture_time_s": float(self.parameters.capture_time_s),
        }
        if self.rx_ids:
            self.send_message(Command.RX_CAPTURE, capture_payload)

        tx_payload = {
            "trial_id": self.trial_id,
            "target": target,
            "target_time": target_time,
            "target_pc_unix": self.start_time_stamp + target_time,
            "beam_angle_deg": tx_command.get("beam_angle_deg"),
            "phase_map": tx_command.get("phase_map", {}),
            "amplitude_map": tx_command.get("amplitude_map", {}),
        }
        self.send_message(Command.TX_PULSE, tx_payload)

        self.state = ExperimentState.WAITING_FOR_RESULTS

    def _maybe_finish_trial(self):
        if self.active_trial is None:
            return

        got_all_rx = set(self.active_trial["rx_metrics"].keys()) >= self.rx_ids
        got_all_tx = set(self.active_trial["tx_statuses"].keys()) >= self.tx_ids
        got_required_fsv = (
            not self.fsv_metric_mode
            or bool(self.active_trial["fsv_metrics"])
        )

        if got_all_rx and got_all_tx and got_required_fsv:
            self._finish_trial()

    def _check_trial_timeout(self):
        if self.active_trial is None:
            return

        deadline_pc = (
            self.start_time_stamp
            + float(self.active_trial["target_time"])
            + float(self.parameters.capture_time_s)
            + float(self.parameters.trial_timeout_s)
        )

        if time.time() <= deadline_pc:
            return

        missing_rx = sorted(self.rx_ids - set(self.active_trial["rx_metrics"].keys()))
        missing_tx = sorted(self.tx_ids - set(self.active_trial["tx_statuses"].keys()))
        missing_fsv = []
        if self.fsv_metric_mode and not self.active_trial["fsv_metrics"]:
            missing_fsv = ["fsv"]

        self.active_trial["status"] = "FAILED"
        self.active_trial["failure_reason"] = (
            f"timeout missing_rx={missing_rx} "
            f"missing_tx={missing_tx} missing_fsv={missing_fsv}"
        )
        self.log.warning(
            f"[TRIAL {self.active_trial['trial_id']}] timeout | "
            f"{self.active_trial['failure_reason']}"
        )
        self._finish_trial(update_beamforming=False)

    def _finish_trial(self, update_beamforming=True):
        trial = self.active_trial
        self.state = ExperimentState.PROCESSING_RESULTS

        any_late = any(
            bool(status.get("late", False))
            for status in trial["tx_statuses"].values()
        )
        any_partial_tx = any(
            int(status.get("samples_sent", 0))
            < int(status.get("samples_requested", 0))
            for status in trial["tx_statuses"].values()
        )
        any_failed_rx = any(
            not bool(metric.get("capture_ok", True))
            for metric in trial["rx_metrics"].values()
        )
        any_failed_fsv = any(
            not bool(metric.get("analyzer_ok", True))
            for metric in trial["fsv_metrics"].values()
        )

        if any_late:
            trial["status"] = "FAILED"
            trial["failure_reason"] = "late TX command"
            update_beamforming = False

        if any_partial_tx:
            trial["status"] = "FAILED"
            trial["failure_reason"] = "partial TX send"
            update_beamforming = False

        if any_failed_rx:
            trial["status"] = "FAILED"
            failure_reason = next(
                (
                    metric.get("failure_reason")
                    for metric in trial["rx_metrics"].values()
                    if not bool(metric.get("capture_ok", True))
                ),
                "RX capture failed",
            )
            trial["failure_reason"] = str(failure_reason)
            update_beamforming = False

        if self.fsv_metric_mode and any_failed_fsv:
            trial["status"] = "FAILED"
            failure_reason = next(
                (
                    metric.get("analyzer_error")
                    for metric in trial["fsv_metrics"].values()
                    if not bool(metric.get("analyzer_ok", True))
                ),
                "FSV capture failed",
            )
            trial["failure_reason"] = str(failure_reason)
            update_beamforming = False

        if trial["status"] == "RUNNING":
            trial["status"] = "OK"

        if trial["status"] != "OK":
            update_beamforming = False

        target_rx_id = str(trial["target_rx_id"])

        if self.fsv_metric_mode:
            metric_linear = self._fsv_metric_linear(trial)
            if metric_linear is None:
                update_beamforming = False
                if not trial["failure_reason"]:
                    trial["failure_reason"] = "missing FSV metric"
        elif target_rx_id not in trial["rx_metrics"]:
            update_beamforming = False
            if not trial["failure_reason"]:
                trial["failure_reason"] = f"missing target RX metric: {target_rx_id}"
            metric_linear = None
        else:
            metric_linear = float(trial["rx_metrics"][target_rx_id]["power_linear"])

        next_tx_command = None

        if update_beamforming and trial["tx_command"].get("mode") != "calibration":
            next_tx_command = self.logic.handle_rx_metric(
                target_rx_id or "fsv",
                metric_linear,
                linear=True,
            )

            if next_tx_command is not None:
                self.current_tx_command = next_tx_command

        self._append_trial_row(trial, updated_beamforming=bool(update_beamforming))
        self.active_trial = None
        self.state = ExperimentState.READY_TO_MEASURE

    def _fsv_metric_linear(self, trial):
        if not trial["fsv_metrics"]:
            return None

        metric = next(iter(trial["fsv_metrics"].values()))

        if "signal_power_linear" in metric:
            return float(metric["signal_power_linear"])

        if "signal_power_db" in metric:
            return 10.0 ** (float(metric["signal_power_db"]) / 10.0)

        tx_metrics = metric.get("tx", {}) or {}
        measured_tx_id = str(getattr(self.parameters, "fsv_measured_tx_id", "0"))
        measured_tx = tx_metrics.get(measured_tx_id)
        if measured_tx is None and tx_metrics:
            measured_tx = next(iter(tx_metrics.values()))

        if measured_tx and "phasor_abs" in measured_tx:
            return float(measured_tx["phasor_abs"]) ** 2

        return None

    def _append_trial_row(self, trial, updated_beamforming):
        tx_command = trial["tx_command"]

        row = [
            trial["trial_id"],
            f"{float(trial['target_time']):.6f}",
            trial["status"],
            tx_command.get("mode", ""),
            trial["target"],
            trial["target_rx_id"],
            tx_command.get("beam_angle_deg", ""),
            tx_command.get("candidate_idx", ""),
            json.dumps(tx_command.get("phase_map", {}), sort_keys=True),
            json.dumps(tx_command.get("amplitude_map", {}), sort_keys=True),
            json.dumps(trial["rx_metrics"], sort_keys=True),
            json.dumps(trial["tx_statuses"], sort_keys=True),
            json.dumps(trial["fsv_metrics"], sort_keys=True),
            bool(updated_beamforming),
            trial.get("failure_reason", ""),
        ]

        with open(self.trial_csv, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(row)

    def _mqtt_port_is_open(self):
        try:
            with socket.create_connection(
                (self.parameters.mqtt_broker, int(self.parameters.mqtt_port)),
                timeout=0.5,
            ):
                return True
        except OSError:
            return False

    def _local_broker_hosts(self):
        hosts = {"localhost", "127.0.0.1", "::1"}

        try:
            hosts.add(socket.gethostname())
            hosts.add(socket.getfqdn())
        except OSError:
            pass

        try:
            for info in socket.getaddrinfo(socket.gethostname(), None):
                hosts.add(info[4][0])
        except OSError:
            pass

        try:
            result = subprocess.run(
                ["hostname", "-I"],
                check=False,
                capture_output=True,
                text=True,
                timeout=1.0,
            )
            if result.returncode == 0:
                hosts.update(result.stdout.split())
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return {str(host).strip().lower() for host in hosts if str(host).strip()}

    def _broker_is_local(self):
        broker = str(self.parameters.mqtt_broker).strip().lower()
        if broker in self._local_broker_hosts():
            return True

        try:
            addresses = {
                info[4][0].lower()
                for info in socket.getaddrinfo(broker, None)
            }
        except OSError:
            return False

        return bool(addresses & self._local_broker_hosts())

    def _start_local_mqtt_broker(self):
        if not self.parameters.mqtt_start_broker:
            return

        if self._mqtt_port_is_open():
            self.log.info("MQTT broker already running")
            return

        if not self._broker_is_local():
            self.log.info(
                f"MQTT broker {self.parameters.mqtt_broker}:"
                f"{self.parameters.mqtt_port} is not local, skipping service start"
            )
            return

        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self._run_broker_start_command(
                ["systemctl", "start", "mosquitto"],
                capture_output=True,
            )
        else:
            result = self._run_broker_start_command(
                ["sudo", "-n", "systemctl", "start", "mosquitto"],
                capture_output=True,
            )
            if result is not True and sys.stdin.isatty():
                self.log.info("MQTT broker start requires sudo password")
                self._run_broker_start_command(
                    ["sudo", "systemctl", "start", "mosquitto"],
                    capture_output=False,
                )

        time.sleep(0.5)
        if self._mqtt_port_is_open():
            self.log.info("MQTT broker started")
            return

        self.log.warning(
            "MQTT broker is not running; start it manually with: "
            "sudo systemctl start mosquitto"
        )

    def _run_broker_start_command(self, command, capture_output):
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=capture_output,
                text=True,
                timeout=None if not capture_output else 10.0,
            )
        except FileNotFoundError:
            self.log.warning(f"MQTT broker start command not found: {command[0]}")
            return False
        except subprocess.TimeoutExpired:
            self.log.warning("Starting MQTT broker timed out")
            return False

        if result.returncode == 0:
            return True

        stderr = ""
        if capture_output:
            stderr = (result.stderr or "").strip()
        if stderr:
            self.log.warning(f"MQTT broker start failed: {stderr}")
        else:
            self.log.warning(
                f"MQTT broker start failed with exit code {result.returncode}"
            )
        return False

    def run(self):
        self.log.info("SystemController running - waiting for components")
        self._start_local_mqtt_broker()
        self.connect_bus()

        while True:
            self.process_pending_messages()

            if self.start_sent:
                if self.active_trial is None:
                    self._start_next_trial()
                else:
                    self._check_trial_timeout()

            time.sleep(0.05)
