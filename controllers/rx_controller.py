import csv
import os
import time

import numpy as np

from controllers.controller import Controller
from helpers.protocol import Command
from helpers.sync_monitor import SyncMonitor


class RXController(Controller):

    def __init__(self, rx_id, config_path=None):
        super().__init__("rx", rx_id, config_path=config_path)

        self.rx_id = rx_id
        self.serial = self.parameters.get_rx_serial(rx_id)

        self.running = False
        self.ready_sent = False
        self.usrp = None
        self.rx_streamer = None

        os.makedirs(self.parameters.results_dir, exist_ok=True)

        self.power_csv = os.path.join(
            self.parameters.results_dir,
            f"rx_power_rx{self.rx_id}.csv",
        )

        with open(self.power_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "trial_id",
                "target_time",
                "detected_time",
                "offset_ms",
                "samples_used",
                "power_db",
                "max_power_db",
                "power_linear",
                "max_power_linear",
            ])

    def _configure_clock_source(self):
        if self.parameters.rx_use_external_clock:
            try:
                self.usrp.set_clock_source("external")
                self.log.info(f"[RX {self.rx_id}] Ustawiony zewnetrzny clock 10 MHz")
                return "external"
            except Exception as e:
                self.log.warning(
                    f"[RX {self.rx_id}] Brak zewnetrznego 10 MHz, fallback do internal: {e}"
                )

        try:
            self.usrp.set_clock_source("internal")
            self.log.info(f"[RX {self.rx_id}] Uzywany wewnetrzny clock")
            return "internal"
        except Exception as e:
            self.log.error(f"[RX {self.rx_id}] Setting internal clock failed: {e}")
            return None

    def _init_usrp(self):
        import uhd

        self.log.info(f"RX REAL MODE -> init USRP | serial={self.serial}")
        try:
            self.usrp = uhd.usrp.MultiUSRP(f"serial={self.serial}")
        except Exception as e:
            self.log.error(f"RX init failed: {e}")
            self.usrp = None
            return False

        if self._configure_clock_source() is None:
            return False

        try:
            self.usrp.set_rx_rate(self.parameters.rx_samp_rate)
            self.usrp.set_rx_freq(self.parameters.center_freq)
            self.usrp.set_rx_gain(self.parameters.rx_gain_db)
        except Exception as e:
            self.log.error(f"[RX {self.rx_id}] RF config failed: {e}")
            return False

        self.log.info(
            f"[RX {self.rx_id}] RF CHECK | "
            f"center_freq={self.parameters.center_freq} | "
            f"rate={self.parameters.rx_samp_rate} | "
            f"gain={self.parameters.rx_gain_db}"
        )

        try:
            st_args = uhd.usrp.StreamArgs("fc32", "sc16")
            self.rx_streamer = self.usrp.get_rx_stream(st_args)
        except Exception as e:
            self.log.error(f"[RX {self.rx_id}] RX streamer init failed: {e}")
            return False

        if self.parameters.rx_use_external_time_source:
            try:
                self.usrp.set_time_source("external")
                self.log.info(f"[RX {self.rx_id}] Ustawiony zewnetrzny time source PPS")
            except Exception as e:
                self.log.error(f"[RX {self.rx_id}] Setting external time source failed: {e}")
                return False
        else:
            self.log.info(f"[RX {self.rx_id}] Uzywany wewnetrzny time source")

        self.log.info(f"[RX {self.rx_id}] USRP initialized")

        if self.parameters.rx_use_external_time_source and not self.parameters.test_mode:
            sync_monitor = SyncMonitor(self.usrp, self.rx_id, "rx")

            if sync_monitor.wait_for_pps_lock(timeout=5.0, verbose=True):
                sync_monitor.print_sync_stats()
                self.log.info(f"[RX {self.rx_id}] PPS zsynchronizowany")
            else:
                self.log.error(f"[RX {self.rx_id}] Brak synchronizacji PPS")
                return False

        return True

    def _recv_window(self, target_time, pre_trigger_s=None, capture_time_s=None):
        import uhd

        margin_sec = float(
            self.parameters.pre_trigger_s if pre_trigger_s is None else pre_trigger_s
        )
        window_duration = float(
            self.parameters.capture_time_s if capture_time_s is None else capture_time_s
        )
        num_samps = max(1, int(self.parameters.rx_samp_rate * window_duration))
        start_time = float(target_time) - margin_sec

        stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.num_done)
        stream_cmd.num_samps = num_samps
        stream_cmd.stream_now = False
        stream_cmd.time_spec = uhd.types.TimeSpec(start_time)

        self.rx_streamer.issue_stream_cmd(stream_cmd)

        md = uhd.types.RXMetadata()
        samples = np.zeros((1, num_samps), dtype=np.complex64)

        timeout_s = max(4.0, margin_sec + window_duration + 1.0)
        num_rx = self.rx_streamer.recv(samples, md, timeout_s)
        received_samples = samples[0, :num_rx].copy()
        error_code = md.error_code
        capture_ok = (
            num_rx == num_samps
            and error_code == uhd.types.RXMetadataErrorCode.none
        )
        failure_reasons = []

        if num_rx == 0:
            self.log.error(
                f"[RX {self.rx_id}] Otrzymano pusty bufor - mozliwy late command"
            )
            failure_reasons.append("empty RX buffer")

        if md.has_time_spec:
            self.log.info(
                f"[RX {self.rx_id}] RX meta timestamp: "
                f"{md.time_spec.get_real_secs():.6f}"
            )

        if num_rx != num_samps:
            self.log.error(
                f"[RX {self.rx_id}] Niepelny odbior RX | "
                f"received={num_rx} expected={num_samps}"
            )
            failure_reasons.append(
                f"partial RX capture ({num_rx}/{num_samps})"
            )

        if error_code != uhd.types.RXMetadataErrorCode.none:
            self.log.error(f"[RX {self.rx_id}] Blad bufora RX: {error_code}")
            failure_reasons.append(f"metadata error: {error_code}")

        return received_samples, start_time, {
            "ok": bool(capture_ok),
            "received": int(num_rx),
            "expected": int(num_samps),
            "failure_reason": "; ".join(failure_reasons),
        }

    def on_connect(self, rc: int):
        self.log.info(f"RX connected to MQTT | id={self.rx_id}")

    def on_message(self, m: dict):
        cmd = m.get("cmd")

        if cmd == Command.START.value:
            self.log.info("RX START received - ready for captures")
            self.running = True

        elif cmd == Command.SYNC_CLOCKS.value:
            self._sync_clocks()

        elif cmd == Command.STOP.value:
            self.log.info("RX STOP received")
            self.running = False

        elif cmd in (Command.RX_CAPTURE.value, Command.RX_PULSE.value):
            if cmd == Command.RX_PULSE.value:
                self.log.warning(
                    f"[RX {self.rx_id}] Legacy RX_PULSE received - treating as RX_CAPTURE"
                )
            self._handle_capture(m.get("payload", {}) or {})

    def _sync_clocks(self):
        if self.usrp is None:
            self.log.warning(
                f"[RX {self.rx_id}] SYNC_CLOCKS ignored - USRP not initialized"
            )
            return

        import uhd

        if self.parameters.rx_use_external_time_source:
            self.usrp.set_time_next_pps(uhd.types.TimeSpec(0.0))
            self.log.info(f"[RX {self.rx_id}] Uzbrojono PPS")
        else:
            self.usrp.set_time_now(uhd.types.TimeSpec(0.0))
            self.log.info(f"[RX {self.rx_id}] Zegar wyzerowany lokalnie")

    def _handle_capture(self, payload):
        trial_id = payload.get("trial_id")
        target_time = payload.get("target_time")

        if target_time is None:
            self.log.error(f"[RX {self.rx_id}] RX_CAPTURE bez target_time")
            return

        target_time = float(target_time)
        pre_trigger_s = float(
            payload.get("pre_trigger_s", self.parameters.pre_trigger_s)
        )
        capture_time_s = float(
            payload.get("capture_time_s", self.parameters.capture_time_s)
        )

        self.log.info(
            f"[RX {self.rx_id}] Start capture | "
            f"trial={trial_id} | target={target_time:.6f}"
        )

        if not self.parameters.test_mode and self.rx_streamer is not None:
            samples, start_time, capture_status = self._recv_window(
                target_time,
                pre_trigger_s=pre_trigger_s,
                capture_time_s=capture_time_s,
            )
        else:
            start_time = target_time - pre_trigger_s
            num_samps = max(1, int(self.parameters.rx_samp_rate * capture_time_s))
            samples = (
                np.random.randn(num_samps)
                + 1j * np.random.randn(num_samps)
            ).astype(np.complex64)
            capture_status = {
                "ok": True,
                "received": int(len(samples)),
                "expected": int(len(samples)),
                "failure_reason": "",
            }

        self._append_iq_csv(samples, start_time)

        if capture_status["ok"]:
            metric = self._compute_power_metric(samples, start_time, target_time)
        else:
            metric = {
                "target_time": target_time,
                "detected_time": None,
                "offset_ms": None,
                "samples_used": int(capture_status["received"]),
                "power_linear": 0.0,
                "power_db": -150.0,
                "max_power_linear": 0.0,
                "max_power_db": -150.0,
            }

        self._append_power_csv(trial_id, metric)

        if capture_status["ok"]:
            self.log.info(
                f"[RX {self.rx_id}] trial={trial_id} | "
                f"target={target_time:.6f} | "
                f"detected={metric['detected_time']:.9f} | "
                f"offset={metric['offset_ms']:.3f} ms | "
                f"power={metric['power_db']:.2f} dB"
            )
        else:
            self.log.warning(
                f"[RX {self.rx_id}] trial={trial_id} capture failed | "
                f"reason={capture_status['failure_reason']}"
            )

        self.send_message(Command.RX_METRIC, {
            "trial_id": trial_id,
            "rx_id": str(self.rx_id),
            "target_time": target_time,
            "detected_time": metric["detected_time"],
            "offset_ms": metric["offset_ms"],
            "samples_used": metric["samples_used"],
            "power_linear": metric["power_linear"],
            "power_db": metric["power_db"],
            "avg_power_lin": metric["power_linear"],
            "avg_power_db": metric["power_db"],
            "max_power_lin": metric["max_power_linear"],
            "max_power_db": metric["max_power_db"],
            "capture_ok": bool(capture_status["ok"]),
            "failure_reason": capture_status["failure_reason"],
            "samples_received": capture_status["received"],
            "samples_expected": capture_status["expected"],
        })

    def _append_iq_csv(self, samples, start_time):
        iq_file = os.path.join(
            self.parameters.results_dir,
            f"rx_iq_rx{self.rx_id}.csv",
        )

        with open(iq_file, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            for k, s in enumerate(samples):
                t = start_time + k / self.parameters.rx_samp_rate
                writer.writerow([
                    f"{t:.9f}",
                    float(np.real(s)),
                    float(np.imag(s)),
                ])

    def _compute_power_metric(self, samples, start_time, target_time):
        eps = 1e-15
        power_all_lin = np.abs(samples) ** 2
        peak_idx = int(np.argmax(power_all_lin))
        detected_time = start_time + peak_idx / self.parameters.rx_samp_rate
        offset_ms = (detected_time - target_time) * 1000.0

        signal_window_sec = 0.002
        half_window = int((signal_window_sec * self.parameters.rx_samp_rate) / 2)
        i0 = max(0, peak_idx - half_window)
        i1 = min(len(samples), peak_idx + half_window + 1)
        signal_power_lin = power_all_lin[i0:i1]

        avg_power_lin = float(np.mean(signal_power_lin))
        max_power_lin = float(np.max(signal_power_lin))

        return {
            "target_time": target_time,
            "detected_time": detected_time,
            "offset_ms": offset_ms,
            "samples_used": len(signal_power_lin),
            "power_linear": avg_power_lin,
            "power_db": float(10.0 * np.log10(avg_power_lin + eps)),
            "max_power_linear": max_power_lin,
            "max_power_db": float(10.0 * np.log10(max_power_lin + eps)),
        }

    def _append_power_csv(self, trial_id, metric):
        with open(self.power_csv, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                trial_id,
                f"{metric['target_time']:.6f}",
                (
                    f"{metric['detected_time']:.9f}"
                    if metric["detected_time"] is not None
                    else ""
                ),
                (
                    f"{metric['offset_ms']:.3f}"
                    if metric["offset_ms"] is not None
                    else ""
                ),
                metric["samples_used"],
                metric["power_db"],
                metric["max_power_db"],
                metric["power_linear"],
                metric["max_power_linear"],
            ])

    def run(self):
        self.log.info(f"RX starting | id={self.rx_id}")
        self.connect_bus()

        self.send_message(Command.REGISTER, {"serial": self.serial})
        self.log.info("RX registration sent")

        if not self.parameters.test_mode:
            if not self._init_usrp():
                self.log.error("RX USRP init failed -> exiting")
                return

        self.send_message(Command.READY, {})
        self.ready_sent = True
        self.log.info("RX READY sent")

        while not self.running:
            self.process_pending_messages()
            time.sleep(0.05)

        self.log.info("RX entering RUN state - waiting for RX_CAPTURE commands")

        while True:
            self.process_pending_messages()
            time.sleep(0.01)
