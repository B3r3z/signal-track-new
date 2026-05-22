import time
import numpy as np
import os
import math
import csv

from controllers.controller import Controller
from helpers.parameters import Parameters
from helpers.csv_writer import CSVWriter
from algorithms.system_logic import SystemLogic
from algorithms.beamforming import Beamforming


class SystemController(Controller):

    def __init__(self):
        super().__init__("system", 0)

        self.parameters = Parameters()

        self.beamforming = Beamforming(self.parameters)
        self.logic = SystemLogic(
            self.parameters,
            self.beamforming,
        )

        self.tx_registered = set()
        self.rx_registered = set()

        self.tx_ready = set()
        self.rx_ready = set()

        self.start_sent = False
        self._last_ready_state = None

        self.tx_count = self.parameters.tx_count
        self.rx_count = self.parameters.rx_count

        self.csv = CSVWriter(self.parameters.results_dir)
        self.virtual_time = 0.0

        self.rx_metrics_by_target = {}

        # Aktualna konfiguracja TX używana przy kolejnym TX_PULSE.
        # To jest konfiguracja, która faktycznie pójdzie do nadajników
        # przy następnym impulsie.
        self.current_tx_command = self._initial_tx_command()

        # Jeden wspólny plik:
        # jeden wiersz = jeden target_time po zebraniu wszystkich RX.
        self.bf_power_csv = os.path.join(
            self.parameters.results_dir,
            "beamforming_power_sweep.csv"
        )
        self._init_bf_power_csv()

    def _init_bf_power_csv(self):
        """
        Tworzy jeden wspólny CSV do analizy sweepu beamformingu.
        Jeden wiersz = jeden target_time po zebraniu metryk ze wszystkich RX.
        """
        os.makedirs(self.parameters.results_dir, exist_ok=True)

        rx_ids_sorted = sorted(
            self.parameters.get_rx_ids(),
            key=lambda x: int(x)
        )

        tx_ids_sorted = sorted(
            self.parameters.get_tx_ids(),
            key=lambda x: int(x)
        )

        header = [
            "target_time",
            "bf_target_rx_id",
            "bf_metric_db",
            "avg_all_rx_db",

            "used_bf_step",
            "used_bf_mode",
            "used_bf_finished",
            "used_beam_angle_deg",
            "used_phase_step_deg",
            "used_best_angle_deg",
            "used_best_metric",

            "next_bf_step",
            "next_bf_mode",
            "next_bf_finished",
            "next_beam_angle_deg",
            "next_phase_step_deg",
            "next_best_angle_deg",
            "next_best_metric",
        ]

        for rid in rx_ids_sorted:
            header += [
                f"rx{rid}_avg_power_db",
                f"rx{rid}_max_power_db",
                f"rx{rid}_avg_power_lin",
                f"rx{rid}_max_power_lin",
                f"rx{rid}_detected_time",
                f"rx{rid}_offset_ms",
                f"rx{rid}_samples_used",
            ]

        for tid in tx_ids_sorted:
            header += [
                f"phase_tx{tid}_rad",
                f"phase_tx{tid}_deg",
                f"amp_tx{tid}",
            ]

        with open(self.bf_power_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)

    def _append_bf_power_row(
        self,
        target_time,
        current_by_str,
        avg_power_all_db,
        metric_for_beamforming,
        used_tx_command,
        next_tx_command=None,
    ):
        """
        Dopisuje jeden kompletny wiersz:
        - moce wszystkich RX dla danego target_time,
        - konfigurację TX faktycznie użytą w tym pomiarze,
        - konfigurację BF wyliczoną na następny pomiar.
        """
        rx_ids_sorted = sorted(
            self.parameters.get_rx_ids(),
            key=lambda x: int(x)
        )

        tx_ids_sorted = sorted(
            self.parameters.get_tx_ids(),
            key=lambda x: int(x)
        )

        if used_tx_command is None:
            used_tx_command = {}

        if next_tx_command is None:
            next_tx_command = {}

        def clean(v):
            if v is None:
                return ""
            return v

        def rx_value(rx_id, key):
            rx = current_by_str.get(str(rx_id), {})
            return clean(rx.get(key, ""))

        def rx_offset_ms(rx_id):
            rx = current_by_str.get(str(rx_id), {})
            detected = rx.get("detected_time")

            if detected is None:
                return ""

            return (float(detected) - float(target_time)) * 1000.0

        phase_map = used_tx_command.get("phase_map", {})
        amplitude_map = used_tx_command.get("amplitude_map", {})

        row = [
            f"{float(target_time):.6f}",
            str(self.parameters.beamforming_target_rx_id),
            float(metric_for_beamforming),
            float(avg_power_all_db),

            clean(used_tx_command.get("step", "")),
            clean(used_tx_command.get("mode", "")),
            clean(used_tx_command.get("finished", "")),
            clean(used_tx_command.get("beam_angle_deg", "")),
            clean(used_tx_command.get("phase_step_deg", "")),
            clean(used_tx_command.get("best_angle_deg", "")),
            clean(used_tx_command.get("best_metric", "")),

            clean(next_tx_command.get("step", "")),
            clean(next_tx_command.get("mode", "")),
            clean(next_tx_command.get("finished", "")),
            clean(next_tx_command.get("beam_angle_deg", "")),
            clean(next_tx_command.get("phase_step_deg", "")),
            clean(next_tx_command.get("best_angle_deg", "")),
            clean(next_tx_command.get("best_metric", "")),
        ]

        for rid in rx_ids_sorted:
            row += [
                rx_value(rid, "avg_power_db"),
                rx_value(rid, "max_power_db"),
                rx_value(rid, "avg_power_lin"),
                rx_value(rid, "max_power_lin"),
                rx_value(rid, "detected_time"),
                rx_offset_ms(rid),
                rx_value(rid, "samples_used"),
            ]

        for tid in tx_ids_sorted:
            tid = str(tid)

            phase_rad = phase_map.get(tid)
            amp = amplitude_map.get(tid)

            if phase_rad is None:
                row += [
                    "",
                    "",
                    clean(amp),
                ]
            else:
                row += [
                    float(phase_rad),
                    float(np.degrees(float(phase_rad))),
                    clean(amp),
                ]

        with open(self.bf_power_csv, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(row)

    def _phase_step_from_angle(self, theta_rad):
        d_over_lambda = self.parameters.tx_antenna_spacing_lambda
        return -2.0 * math.pi * d_over_lambda * math.sin(theta_rad)

    def _initial_tx_command(self):
        """
        Początkowa konfiguracja TX dla pierwszego impulsu.
        Beamforming na starcie zakłada current_idx=0, więc pierwszy TX_PULSE
        powinien użyć pierwszego kandydata.
        """
        mode = getattr(self.parameters, "beamforming_input_mode", "theta")

        if mode == "fi":
            phase_sweep = getattr(self.parameters, "phase_map_sweep_deg", [])
            amplitude_sweep = getattr(self.parameters, "amplitude_map_sweep", [])

            if phase_sweep:
                first_phase_map_deg = phase_sweep[0]
            else:
                first_phase_map_deg = {
                    str(tx_id): 0.0
                    for tx_id in self.parameters.get_tx_ids()
                }

            phase_map = {
                str(tx_id): math.radians(float(phi_deg))
                for tx_id, phi_deg in first_phase_map_deg.items()
            }

            if amplitude_sweep:
                first_amplitude_map = amplitude_sweep[0]
                amplitude_map = {
                    str(tx_id): float(amp)
                    for tx_id, amp in first_amplitude_map.items()
                }
            else:
                amplitude_map = {
                    str(tx_id): float(self.parameters.tx_signal_amplitude)
                    for tx_id in phase_map.keys()
                }

            return {
                "phase_map": phase_map,
                "amplitude_map": amplitude_map,
                "finished": False,
                "step": 0,
                "mode": "fi",
                "beam_angle_rad": None,
                "beam_angle_deg": None,
                "phase_step_rad": None,
                "phase_step_deg": None,
                "best_angle_rad": None,
                "best_angle_deg": None,
                "best_metric": None,
            }

        if mode == "theta":
            angles_deg = getattr(self.parameters, "beam_angle_sweep_deg", [0.0])
            first_angle_rad = math.radians(float(angles_deg[0]))

            amp = self.parameters.tx_signal_amplitude
            phase_step = self._phase_step_from_angle(first_angle_rad)

            phase_map = {}
            amplitude_map = {}

            for position_idx, tx_id in enumerate(self.parameters.tx_array_order):
                phase_map[str(tx_id)] = float(position_idx * phase_step)
                amplitude_map[str(tx_id)] = float(amp)

            return {
                "phase_map": phase_map,
                "amplitude_map": amplitude_map,
                "finished": False,
                "step": 0,
                "mode": "theta",
                "beam_angle_rad": float(first_angle_rad),
                "beam_angle_deg": float(math.degrees(first_angle_rad)),
                "phase_step_rad": float(phase_step),
                "phase_step_deg": float(math.degrees(phase_step)),
                "best_angle_rad": None,
                "best_angle_deg": None,
                "best_metric": None,
            }

        raise ValueError(
            f"Unknown beamforming_input_mode: {mode}. Use 'theta' or 'fi'."
        )

    def _is_all_off_command(self, tx_cmd):
        """
        Sprawdza, czy aktualna konfiguracja TX ma wszystkie amplitudy = 0.
        To może być użyteczne przy konfiguracjach testowych all-OFF.
        """
        if tx_cmd is None:
            return False

        amplitude_map = tx_cmd.get("amplitude_map", {})

        if not amplitude_map:
            return False

        return all(abs(float(v)) < 1e-12 for v in amplitude_map.values())

    def on_connect(self, rc: int):
        self.log.info("System connected to MQTT")

    def on_message(self, m: dict):
        if m["cmd"] == "REGISTER" and m["src"] == "tx":
            if m["id"] not in self.tx_registered:
                self.tx_registered.add(m["id"])
                self.log.info(f"TX REGISTERED | id={m['id']}")

        elif m["cmd"] == "REGISTER" and m["src"] == "rx":
            if m["id"] not in self.rx_registered:
                self.rx_registered.add(m["id"])
                self.log.info(f"RX REGISTERED | id={m['id']}")

        elif m["cmd"] == "READY" and m["src"] == "tx":
            if m["id"] not in self.tx_ready:
                self.tx_ready.add(m["id"])
                self.log.info(f"TX READY | id={m['id']}")
                self._check_and_start()

        elif m["cmd"] == "READY" and m["src"] == "rx":
            if m["id"] not in self.rx_ready:
                self.rx_ready.add(m["id"])
                self.log.info(f"RX READY | id={m['id']}")
                self._check_and_start()

        elif m["cmd"] == "PULSE_RESULT" and m["src"] == "rx":
            rx_id = m["id"]
            payload = m["payload"]

            target_time = payload["target_time"]
            detected_time = payload["detected_time"]
            offset = payload["offset"]

            self.log.info(
                f"[WYNIK = {offset * 1000:7.3f} ms] "
                f"RX{rx_id} wyśledził uderzenie! "
                f"Spodziewano={target_time:.3f}, "
                f"Znaleziono={detected_time:.6f}"
            )

        elif m["cmd"] == "METRIC" and m["src"] == "rx":
            rx_id = str(m["id"])
            payload = m.get("payload", {})

            metric = float(payload["value"])
            target_time = payload.get("target_time")
            samples_used = payload.get("samples_used")

            avg_power_db = float(payload.get("avg_power_db", metric))
            max_power_db = payload.get("max_power_db")
            avg_power_lin = float(
                payload.get(
                    "avg_power_lin",
                    10.0 ** (avg_power_db / 10.0)
                )
            )
            max_power_lin = payload.get("max_power_lin")
            detected_time = payload.get("detected_time")

            self.log.info(
                f"[METRIC] RX{rx_id} "
                f"target={target_time} "
                f"detected={detected_time} "
                f"avg={avg_power_db:.2f} dB"
            )

            # ============================================================
            # ZBIERANIE MOCY ZE WSZYSTKICH RX DLA TEGO SAMEGO IMPULSU
            # ============================================================

            target_key = f"{float(target_time):.6f}"

            if target_key not in self.rx_metrics_by_target:
                self.rx_metrics_by_target[target_key] = {}

            self.rx_metrics_by_target[target_key][rx_id] = {
                "avg_power_db": avg_power_db,
                "max_power_db": max_power_db,
                "avg_power_lin": avg_power_lin,
                "max_power_lin": max_power_lin,
                "samples_used": samples_used,
                "detected_time": detected_time,
            }

            current = self.rx_metrics_by_target[target_key]

            avg_lin_all = float(np.mean([
                v["avg_power_lin"] for v in current.values()
            ]))

            avg_power_all_db = float(
                10.0 * np.log10(avg_lin_all + 1e-15)
            )

            rx_parts = []

            for rid in sorted(current.keys(), key=lambda x: int(x)):
                v = current[rid]
                rx_parts.append(
                    f"RX{rid}={v['avg_power_db']:.2f} dB"
                )

            self.log.info(
                f"[MOCE ODEBRANE | target={target_key} | "
                f"odebrano={len(current)}/{self.rx_count}] "
                + " | ".join(rx_parts)
                + f" | ŚREDNIA={avg_power_all_db:.2f} dB"
            )

            # Dopiero gdy mamy wszystkie RX dla danego target_time,
            # zapisujemy jeden pełny wiersz CSV i aktualizujemy BF.
            if len(current) >= self.rx_count:

                current_by_str = {
                    str(rid): value for rid, value in current.items()
                }

                rx_detail_parts = []
                for rid in sorted(current_by_str.keys(), key=lambda x: int(x)):
                    v = current_by_str[rid]
                    rx_detail_parts.append(
                        f"RX{rid}={v['avg_power_db']:.2f} dB"
                    )

                self.log.info(
                    f"[BF RX OSOBNO] target={target_key} | "
                    + " | ".join(rx_detail_parts)
                )

                target_rx_id = str(self.parameters.beamforming_target_rx_id)

                if target_rx_id not in current_by_str:
                    self.log.error(
                        f"[BF] Brak metryki z RX{target_rx_id} "
                        f"dla target={target_key}. "
                        f"Dostępne RX: {list(current_by_str.keys())}"
                    )
                    del self.rx_metrics_by_target[target_key]
                    return

                metric_for_beamforming = float(
                    current_by_str[target_rx_id]["avg_power_db"]
                )

                self.log.info(
                    f"[BF METRYKA] target={target_key} | "
                    f"używam RX{target_rx_id}={metric_for_beamforming:.2f} dB | "
                    f"średnia diagnostycznie={avg_power_all_db:.2f} dB"
                )

                # Konfiguracja faktycznie użyta w tym target_time.
                # Dopiero po tej metryce może powstać konfiguracja na następny target.
                used_tx_command = self.current_tx_command

                tx_cmd = None

                if metric_for_beamforming > -140.0:
                    tx_cmd = self.logic.handle_rx_metric(
                        target_rx_id,
                        metric_for_beamforming
                    )
                else:
                    self.log.warning(
                        f"[BF] Pomijam pusty pomiar target={target_key}, "
                        f"RX{target_rx_id}={metric_for_beamforming:.2f} dB"
                    )

                # Jeden wspólny ładny CSV:
                # jeden wiersz = jeden target_time.
                self._append_bf_power_row(
                    target_time=float(target_key),
                    current_by_str=current_by_str,
                    avg_power_all_db=avg_power_all_db,
                    metric_for_beamforming=metric_for_beamforming,
                    used_tx_command=used_tx_command,
                    next_tx_command=tx_cmd,
                )

                if tx_cmd is not None:
                    self.current_tx_command = tx_cmd

                    self.log.info(
                        f"[BF] zapamiętuję konfigurację "
                        f"dla następnego TX_PULSE: {tx_cmd}"
                    )

                del self.rx_metrics_by_target[target_key]

    def _check_and_start(self):
        current_state = (len(self.tx_ready), len(self.rx_ready))

        if current_state != self._last_ready_state:
            self.log.info(
                f"READY CHECK: "
                f"TX {len(self.tx_ready)}/{self.tx_count}, "
                f"RX {len(self.rx_ready)}/{self.rx_count}"
            )
            self._last_ready_state = current_state

        if self.start_sent:
            return

        if (
            len(self.tx_ready) == self.tx_count
            and len(self.rx_ready) == self.rx_count
        ):
            self.log.info(
                "Wysyłam rozkaz absolutnego zrównania liczników PPS "
                "(SYNC_CLOCKS)..."
            )
            self.send_message("SYNC_CLOCKS", {})

            # Czas na złapanie wspólnej krawędzi PPS.
            time.sleep(3.0)

            self.log.info("ALL COMPONENTS READY → START")
            self.logic.start()
            self.send_message("START", {})
            self.start_sent = True

            self.virtual_time = 5.0
            self.start_time_stamp = time.time()

    def run(self):
        self.log.info("SystemController running - waiting for components")
        self.connect_bus()

        last_pulse_time = 0.0

        while True:
            self.process_pending_messages()

            if self.start_sent:
                current_time = time.time()

                if last_pulse_time == 0.0:
                    last_pulse_time = self.start_time_stamp

                if current_time - last_pulse_time >= 5.0:
                    last_pulse_time = current_time

                    self.virtual_time += 5.0
                    target_time = self.virtual_time

                    self.log.info(
                        f"[TRIGGER] Rozsyłam zlecenie jednoczesnego strzału TX "
                        f"na czas sprzętowy wirtualny: {target_time:.3f} s"
                    )

                    self.send_message("RX_PULSE", {"target_time": target_time})

                    tx_pulse_payload = {
                        "target_time": target_time,
                    }

                    if self.current_tx_command is not None:
                        tx_pulse_payload["phase_map"] = (
                            self.current_tx_command.get("phase_map", {})
                        )
                        tx_pulse_payload["amplitude_map"] = (
                            self.current_tx_command.get("amplitude_map", {})
                        )

                        self.log.info(
                            f"[TRIGGER] TX_PULSE z konfiguracją | "
                            f"target={target_time:.3f} | "
                            f"phase_map={tx_pulse_payload['phase_map']} | "
                            f"amplitude_map={tx_pulse_payload['amplitude_map']}"
                        )
                    else:
                        self.log.warning(
                            f"[TRIGGER] TX_PULSE bez konfiguracji BF | "
                            f"target={target_time:.3f}"
                        )

                    self.send_message("TX_PULSE", tx_pulse_payload)

            time.sleep(0.1)