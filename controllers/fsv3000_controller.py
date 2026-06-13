import csv
import math
import os
import queue
import threading
import time
from datetime import datetime, timezone
from loguru import logger 

import numpy as np

from controllers.controller import Controller
from helpers.protocol import Command


def wrap_deg(x):
    return (float(x) + 180.0) % 360.0 - 180.0


def db10(x, eps=1e-15):
    return 10.0 * math.log10(float(x) + eps)


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


class FSV3000IqClient:
    """
    Minimalny klient R&S FSV3000 do pobierania IQ przez SCPI.

    Domyślnie używa RsInstrument. Dla resource zakończonego ::SOCKET
    wymusza backend SocketIo, więc zwykle nie trzeba instalować VISA.
    """

    def __init__(self, parameters):
        self.parameters = parameters
        self.resource = getattr(parameters, "fsv_resource", None)
        if not self.resource:
            ip_or_resource = str(getattr(parameters, "fsv_ip", "192.168.0.10"))
            if "::" in ip_or_resource:
                self.resource = ip_or_resource
            else:
                socket_port = int(getattr(parameters, "fsv_socket_port", 5025))
                self.resource = f"TCPIP::{ip_or_resource}::{socket_port}::SOCKET"

        self.center_freq_hz = float(
            getattr(parameters, "fsv_center_freq_hz", getattr(parameters, "tx_signal_frequency", 868e6))
        )
        self.sample_rate_sps = float(getattr(parameters, "fsv_iq_sample_rate_sps", 1e6))
        self.capture_time_s = float(getattr(parameters, "fsv_capture_time_s", 0.20))
        self.ref_level_dbm = float(getattr(parameters, "fsv_ref_level_dbm", 0.0))
        self.trigger_source = str(getattr(parameters, "fsv_trigger_source", "IFP")).upper()
        self.trigger_level_dbm = float(getattr(parameters, "fsv_trigger_level_dbm", -40.0))
        self.timeout_ms = int(getattr(parameters, "fsv_timeout_ms", 20000))
        self.test_mode = bool(getattr(parameters, "fsv_test_mode", getattr(parameters, "test_mode", False)))
        self.inst = None

    def open(self):
        if self.test_mode:
            return

        try:
            from RsInstrument import RsInstrument
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependency RsInstrument. Install it with: "
                "python3 -m pip install RsInstrument"
            ) from exc

        if self.resource.upper().endswith("::SOCKET"):
            self.inst = RsInstrument(self.resource, True, False, "SelectVisa='socket'")
        else:
            self.inst = RsInstrument(self.resource, True, False)

        self.inst.visa_timeout = self.timeout_ms
        self.inst.opc_timeout = self.timeout_ms
        self.inst.instrument_status_checking = False

        idn = self.inst.query_str("*IDN?").strip()
        self.configure()
        return idn

    def close(self):
        if self.inst is None:
            return
        try:
            self.inst.go_to_local()
        except Exception:
            pass
        try:
            self.inst.close()
        except Exception:
            pass

    def _write(self, cmd, required=False, opc=False):
        if self.inst is None:
            return
        try:
            if opc:
                self.inst.write_with_opc(cmd)
            else:
                self.inst.write_str(cmd)
        except Exception:
            if required:
                raise

    def scpi_err(self):
        return self.inst.query_str("SYST:ERR?").strip()

    def configure(self):
        if self.test_mode:
            return
        if self.inst is None:
            raise RuntimeError("FSV3000 not opened")

        self.inst.write_str("*CLS")

        logger.info("Before INST:LIST? {}", self.inst.query_str("INST:LIST?").strip())
        logger.info("Before INST:SEL? {}", self.inst.query_str("INST:SEL?").strip())

        # Spróbuj wybrać kanał IQ Analyzer
        self.inst.write_str("INST:SEL 'IQ Analyzer'")
        err = self.scpi_err()

        # Jeśli nie istnieje, utwórz kanał typu IQ
        if not err.startswith("0,"):
            logger.info("IQ Analyzer not selected, creating channel | err={}", err)

            self.inst.write_str("INST:CRE:NEW IQ, 'IQ Analyzer'")
            err = self.scpi_err()
            if not err.startswith("0,"):
                raise RuntimeError(f"Cannot create IQ Analyzer channel: {err}")

            self.inst.write_str("INST:SEL 'IQ Analyzer'")
            err = self.scpi_err()
            if not err.startswith("0,"):
                raise RuntimeError(f"Cannot select IQ Analyzer channel: {err}")

        logger.info("After INST:LIST? {}", self.inst.query_str("INST:LIST?").strip())
        logger.info("After INST:SEL? {}", self.inst.query_str("INST:SEL?").strip())

        self._write("INIT:CONT OFF", required=True)
        self._write(f"FREQ:CENT {self.center_freq_hz}", required=True)
        self._write(f"DISP:WIND:TRAC:Y:SCAL:RLEV {self.ref_level_dbm}")

        self._write("FORM REAL,32", required=True)
        self._write("TRAC:IQ ON", required=True)
        self._write("TRAC:IQ:DATA:FORM IQP", required=True)
        self._write(f"TRAC:IQ:SRAT {self.sample_rate_sps}", required=True)

        record_len = int(self.sample_rate_sps * self.capture_time_s)
        self._write(f"TRAC:IQ:RLEN {record_len}", required=True)

        # Na testy IMM, potem można wrócić do IFP
        trig_src = self.trigger_source.upper()

        if trig_src not in ("IMM", "IFP", "EXT"):
            trig_src = "IFP"

        self._write(f"TRIG:SOUR {trig_src}", required=True)

        if trig_src == "IFP":
            self._write(f"TRIG:LEV:IFP {self.trigger_level_dbm}", required=False)

        elif trig_src == "EXT":
            self._write(f"TRIG:LEV {self.trigger_level_dbm}", required=False)

        logger.info(
            "FSV trigger configured | source={} | level={} dBm",
            trig_src,
            self.trigger_level_dbm,
        )

        err = self.scpi_err()
        if not err.startswith("0,"):
            raise RuntimeError(f"FSV3000 config error: {err}")

    def capture_iq(self, synthetic_phase_by_tx=None, tone_offsets=None):
        if self.test_mode:
            return self._fake_iq(synthetic_phase_by_tx or {}, tone_offsets or {})

        if self.inst is None:
            raise RuntimeError("FSV3000 not opened")

        self.inst.write_with_opc("INIT:IMM", timeout=self.timeout_ms)
        raw = np.asarray(
            self.inst.query_bin_or_ascii_float_list("TRAC:IQ:DATA:MEM?"),
            dtype=np.float32,
        )

        if raw.size < 4:
            raise RuntimeError(f"Too few IQ values from FSV3000: {raw.size}")
        if raw.size % 2 != 0:
            raw = raw[:-1]

        iq = raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)
        return iq.astype(np.complex64)

    def _fake_iq(self, phase_by_tx, tone_offsets):
        fs = self.sample_rate_sps
        n_total = max(4096, int(fs * self.capture_time_s))
        n = np.arange(n_total, dtype=np.float64)
        rng = np.random.default_rng()
        noise = 0.01 * (rng.normal(size=n_total) + 1j * rng.normal(size=n_total))

        pulse_len = max(512, int(float(getattr(self.parameters, "iq_samples_per_packet", 32768)) / float(getattr(self.parameters, "tx_samp_rate", 500e3)) * fs))
        pulse_len = min(pulse_len, n_total)
        start = max(0, n_total // 2 - pulse_len // 2)
        end = min(n_total, start + pulse_len)

        sig = np.zeros(n_total, dtype=np.complex128)
        for tx_id, phase_deg in phase_by_tx.items():
            f0 = float(tone_offsets.get(str(tx_id), tone_offsets.get(int(tx_id), 0.0)))
            sig[start:end] += np.exp(1j * (2.0 * np.pi * f0 * n[start:end] / fs + math.radians(float(phase_deg))))
        return (sig + noise).astype(np.complex64)


def _find_pulse_window(iq, fs, expected_pulse_s):
    power = np.abs(iq) ** 2
    n_total = len(iq)
    pulse_len = int(max(32, min(n_total, round(float(expected_pulse_s) * float(fs)))))

    if n_total > 2 * pulse_len:
        cumsum = np.cumsum(power, dtype=np.float64)
        cumsum = np.insert(cumsum, 0, 0.0)
        sliding_avg = (cumsum[pulse_len:] - cumsum[:-pulse_len]) / pulse_len
        peak_start = int(np.argmax(sliding_avg))
        peak_end = min(n_total, peak_start + pulse_len)
    else:
        peak_start = 0
        peak_end = n_total

    return peak_start, peak_end


def analyze_iq_by_tone(iq, fs, tone_offsets_hz, expected_pulse_s):
    iq = np.asarray(iq, dtype=np.complex64)
    if len(iq) < 16:
        raise ValueError("IQ buffer too short")

    peak_start, peak_end = _find_pulse_window(iq, fs, expected_pulse_s)
    sig = iq[peak_start:peak_end]
    if len(sig) < 16:
        sig = iq
        peak_start = 0
        peak_end = len(iq)

    n = np.arange(peak_start, peak_end, dtype=np.float64)
    result = {}

    for tx_id, f0 in tone_offsets_hz.items():
        mixer = np.exp(-1j * 2.0 * np.pi * float(f0) * n / float(fs))
        phasor = np.mean(sig.astype(np.complex128) * mixer)
        phase_deg = wrap_deg(math.degrees(math.atan2(phasor.imag, phasor.real)))
        result[str(tx_id)] = {
            "phase_raw_deg": float(phase_deg),
            "phasor_abs": float(abs(phasor)),
        }

    signal_power = float(np.mean(np.abs(sig) ** 2))
    return {
        "tx": result,
        "samples_total": int(len(iq)),
        "samples_used": int(len(sig)),
        "peak_start_sample": int(peak_start),
        "peak_end_sample": int(peak_end),
        "signal_power_db": db10(signal_power),
    }


class FSV3000Controller(Controller):
    """
    Pełnoprawny komponent SignalTrack.

    - REGISTER/READY do systemu.
    - Po TX_PULSE uzbraja FSV3000 i pobiera IQ.
    - Liczy fazę osobno dla każdego TX przez demodulację po tx_tone_offsets.
    - Wysyła FSV_PHASE_METRIC do systemu.

    Warunek separacji faz TX: TX muszą mieć różne tone_offset_hz. Jeśli wszystkie TX
    nadają na tym samym offsetcie, FSV widzi fazę sumy wektorowej, a nie fazę każdego TX osobno.
    """

    def __init__(self, fsv_id=0, config_path=None):
        super().__init__("fsv", int(fsv_id), config_path=config_path)
        self.fsv_id = int(fsv_id)
        self.analyzer = FSV3000IqClient(self.parameters)
        self.capture_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.last_phase_cmd_deg = {}
        self.expected_pulse_s = float(getattr(self.parameters, "fsv_expected_pulse_s", 0.0))
        if self.expected_pulse_s <= 0.0:
            self.expected_pulse_s = float(getattr(self.parameters, "iq_samples_per_packet", 32768)) / float(getattr(self.parameters, "tx_samp_rate", 500e3))

        self.local_csv = os.path.join(self.parameters.results_dir, f"fsv3000_phase_fsv{self.fsv_id}.csv")
        os.makedirs(self.parameters.results_dir, exist_ok=True)
        self._init_local_csv()

    def _init_local_csv(self):
        header = [
            "trial_id",
            "timestamp_pc_iso",
            "beam_angle_deg",
            "tx0_phase_cmd_deg",
            "tx1_phase_cmd_deg",
            "tx2_phase_cmd_deg",
            "tx3_phase_cmd_deg",
            "analyzer_phase_deg",
        ]

        with open(self.local_csv, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(header)

    def _append_local_csv(self, payload):
        tx = payload.get("tx", {})

        row = [
            payload.get("trial_id", ""),
            payload.get("timestamp_pc_iso", now_iso()),
            payload.get("beam_angle_deg", ""),
            tx.get("0", {}).get("phase_cmd_deg", ""),
            tx.get("1", {}).get("phase_cmd_deg", ""),
            tx.get("2", {}).get("phase_cmd_deg", ""),
            tx.get("3", {}).get("phase_cmd_deg", ""),
            payload.get("analyzer_phase_deg", ""),
        ]

        with open(self.local_csv, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(row)

    def on_connect(self, rc):
        self.log.info(f"FSV3000 connected to MQTT | id={self.fsv_id} | rc={rc}")

    def on_message(self, m):
        cmd = m.get("cmd")
        payload = m.get("payload", {}) or {}

        if cmd == Command.START.value:
            self.log.info("FSV START received")

        elif cmd == Command.TX_PULSE.value:
            if not bool(getattr(self.parameters, "fsv_enabled", False)):
                return

            target_time = payload.get("target_time")
            if target_time is None:
                return

            phase_map = payload.get("phase_map", {}) or {}
            self.last_phase_cmd_deg = {
                str(k): wrap_deg(math.degrees(float(v))) for k, v in phase_map.items()
            }
            self.capture_queue.put({
                "trial_id": payload.get("trial_id"),
                "target_time": float(target_time),
                "target_pc_unix": payload.get("target_pc_unix"),
                "beam_angle_deg": payload.get("beam_angle_deg", ""),
                "phase_cmd_deg": dict(self.last_phase_cmd_deg),
            })

    def _worker(self):
        while not self.stop_event.is_set():
            try:
                item = self.capture_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            target_time = float(item["target_time"])
            trial_id = item.get("trial_id")
            beam_angle_deg = item.get("beam_angle_deg", "")
            phase_cmd_deg = item.get("phase_cmd_deg", {})
            tone_offsets = getattr(self.parameters, "tx_tone_offsets", {})

            try:
                target_pc_unix = item.get("target_pc_unix")

                if target_pc_unix is not None:
                    pre_capture_s = float(getattr(self.parameters, "fsv_pre_capture_s", 0.05))
                    sleep_until = float(target_pc_unix) - pre_capture_s
                    delay = sleep_until - time.time()

                    if delay > 0:
                        self.log.info(
                            f"[FSV] Czekam do okna impulsu | "
                            f"delay={delay:.3f}s | target_pc={float(target_pc_unix):.3f}"
                        )
                        time.sleep(delay)
                iq = self.analyzer.capture_iq(
                    synthetic_phase_by_tx=phase_cmd_deg,
                    tone_offsets=tone_offsets,
                )
                analysis = analyze_iq_by_tone(
                    iq=iq,
                    fs=self.analyzer.sample_rate_sps,
                    tone_offsets_hz=tone_offsets,
                    expected_pulse_s=self.expected_pulse_s,
                )
                measured_tx_id = str(getattr(self.parameters, "fsv_measured_tx_id", "0"))

                min_signal_power_db = float(
                    getattr(self.parameters, "fsv_min_signal_power_db", -80.0)
                )

                min_phasor_abs = float(
                    getattr(self.parameters, "fsv_min_phasor_abs", 1e-5)
                )

                measured_tx = analysis["tx"].get(measured_tx_id, {})

                valid_measurement = True
                validation_error = ""

                if analysis["samples_total"] <= 0 or analysis["samples_used"] <= 0:
                    valid_measurement = False
                    validation_error = "No IQ samples used"

                elif analysis["signal_power_db"] < min_signal_power_db:
                    valid_measurement = False
                    validation_error = (
                        f"Signal too weak: {analysis['signal_power_db']:.2f} dB "
                        f"< {min_signal_power_db:.2f} dB"
                    )

                elif float(measured_tx.get("phasor_abs", 0.0)) < min_phasor_abs:
                    valid_measurement = False
                    validation_error = (
                        f"Phasor too weak for TX{measured_tx_id}: "
                        f"{float(measured_tx.get('phasor_abs', 0.0)):.6g} "
                        f"< {min_phasor_abs:.6g}"
                    )
                analyzer_phase_deg = ""

                # bierzemy jedną fazę z analizatora, najlepiej z TX0 jeśli istnieje
                measured_tx_id = str(getattr(self.parameters, "fsv_measured_tx_id", "0"))

                analyzer_phase_deg = ""
                if measured_tx_id in analysis["tx"]:
                    analyzer_phase_deg = analysis["tx"][measured_tx_id]["phase_raw_deg"]
                elif analysis["tx"]:
                    analyzer_phase_deg = next(iter(analysis["tx"].values()))["phase_raw_deg"]
                tx_payload = {}

                for tx_id, d in analysis["tx"].items():
                    tx_id_str = str(tx_id)

                    cmd_deg = phase_cmd_deg.get(tx_id_str, "")
                    raw_deg = d.get("phase_raw_deg")
                    phasor_abs = d.get("phasor_abs")

                    if cmd_deg != "" and raw_deg is not None:
                        phase_error_deg = wrap_deg(float(raw_deg) - float(cmd_deg))
                    else:
                        phase_error_deg = ""

                    tx_payload[tx_id_str] = {
                        "phase_cmd_deg": cmd_deg,
                        "phase_raw_deg": raw_deg,
                        "phase_error_deg": phase_error_deg,
                        "phasor_abs": phasor_abs,
                    }

                analyzer_phase_deg = ""
                if "0" in analysis["tx"]:
                    analyzer_phase_deg = analysis["tx"]["0"]["phase_raw_deg"]
                elif analysis["tx"]:
                    analyzer_phase_deg = next(iter(analysis["tx"].values()))["phase_raw_deg"]
                out = {
                    "trial_id": trial_id,
                    "timestamp_pc_iso": now_iso(),
                    "timestamp_pc_unix": time.time(),
                    "target_time": target_time,
                    "beam_angle_deg": beam_angle_deg,

                    "analyzer_ok": bool(valid_measurement),
                    "analyzer_error": validation_error,

                    "samples_total": analysis["samples_total"],
                    "samples_used": analysis["samples_used"],
                    "peak_start_sample": analysis["peak_start_sample"],
                    "peak_end_sample": analysis["peak_end_sample"],
                    "signal_power_db": analysis["signal_power_db"],

                    "tx": tx_payload,
                    "analyzer_phase_deg": analyzer_phase_deg,
                }
            except Exception as e:
                self.log.exception(f"FSV3000 capture failed | target={target_time:.6f} | {e}")
                out = {
                    "trial_id": trial_id,
                    "timestamp_pc_iso": now_iso(),
                    "timestamp_pc_unix": time.time(),
                    "target_time": target_time,
                    "beam_angle_deg": beam_angle_deg,
                    "analyzer_ok": False,
                    "analyzer_error": repr(e),
                    "tx": {},
                    "analyzer_phase_deg": "",
                }

            self._append_local_csv(out)
            self.send_message(Command.FSV_PHASE_METRIC, out)
            self.log.info(f"FSV_PHASE_METRIC sent | target={target_time:.6f} | ok={out.get('analyzer_ok')}")

    def run(self):
        self.log.info(f"FSV3000 starting | id={self.fsv_id} | resource={self.analyzer.resource}")
        self.connect_bus()
        self.send_message(Command.REGISTER, {"resource": self.analyzer.resource})

        if bool(getattr(self.parameters, "fsv_enabled", False)):
            idn = self.analyzer.open()
            if idn:
                self.log.info(f"FSV3000 IDN: {idn}")
        else:
            self.log.warning("fsv_enabled=False, controller works in MQTT only mode")

        self.worker_thread.start()
        self.send_message(Command.READY, {"resource": self.analyzer.resource})

        while not self.stop_event.is_set():
            self.process_pending_messages()
            time.sleep(0.2)

    def stop(self):
        self.stop_event.set()
        self.analyzer.close()
