import time
import os
import numpy as np

from controllers.controller import Controller
from helpers.parameters import Parameters
from helpers.sync_monitor import SyncMonitor


class TXController(Controller):

    def __init__(self, tx_id):
        super().__init__("tx", tx_id)

        self.parameters = Parameters()

        self.tx_id = tx_id
        self.serial = self.parameters.get_tx_serial(tx_id)

        self.running = False
        self.ready_sent = False
        self.continuous_mode = False

        self.usrp = None
        self.tx_streamer = None
        self.tx_md = None

        self.tx_phase = 0.0
        self.tx_amplitude = self.parameters.tx_signal_amplitude

        os.makedirs(self.parameters.results_dir, exist_ok=True)
        self.timing_csv = os.path.join(
            self.parameters.results_dir,
            f"tx_timing_tx{self.tx_id}.csv"
        )

        with open(self.timing_csv, "w", encoding="utf-8") as f:
            f.write("tx_id,target_time,usrp_time_received,usrp_time_after_send,zapas_ms\n")

    def _init_usrp(self):
        import uhd

        self.log.info(f"TX REAL MODE → init USRP | serial={self.serial}")

        try:
            self.usrp = uhd.usrp.MultiUSRP(f"serial={self.serial}")
        except Exception as e:
            self.log.error(f"[TX {self.tx_id}] USRP init failed: {e}")
            self.usrp = None
            return False

        try:
            self.usrp.set_tx_rate(self.parameters.tx_samp_rate)
            self.usrp.set_tx_freq(self.parameters.tx_signal_frequency)
            self.usrp.set_tx_gain(self.parameters.tx_gain_db)

            try:
                self.usrp.set_tx_antenna("TX/RX")
                tx_ant = self.usrp.get_tx_antenna()
            except Exception as e:
                tx_ant = "UNKNOWN"
                self.log.warning(f"[TX {self.tx_id}] Nie ustawiono anteny TX/RX: {e}")

        except Exception as e:
            self.log.error(f"[TX {self.tx_id}] RF config failed: {e}")
            return False

        self.log.info(
            f"[TX {self.tx_id}] RF CHECK | "
            f"center_freq={self.parameters.center_freq} Hz | "
            f"tx_signal_frequency={self.parameters.tx_signal_frequency} Hz | "
            f"actual_tx_freq={self.usrp.get_tx_freq()} Hz | "
            f"tone_offset={self.parameters.tx_tone_offsets.get(int(self.tx_id), self.parameters.tx_tone_offset_hz)} Hz | "
            f"rate={self.parameters.tx_samp_rate} S/s | "
            f"actual_rate={self.usrp.get_tx_rate()} S/s | "
            f"gain={self.parameters.tx_gain_db} dB | "
            f"actual_gain={self.usrp.get_tx_gain()} dB | "
            f"antenna={tx_ant}"
        )

        # ============================================================
        # CLOCK SOURCE
        # ============================================================

        if self.parameters.tx_use_external_clock:
            try:
                self.usrp.set_clock_source("external")
                self.log.info(f"[TX {self.tx_id}] Ustawiony zewnętrzny clock: REF IN 10 MHz")
            except Exception as e:
                self.log.error(f"[TX {self.tx_id}] Setting external clock failed: {e}")
                return False
        else:
            self.log.info(f"[TX {self.tx_id}] Używany wewnętrzny clock")

        # ============================================================
        # STREAMER TX
        # ============================================================

        try:
            st_args = uhd.usrp.StreamArgs("fc32", "sc16")
            self.tx_streamer = self.usrp.get_tx_stream(st_args)
        except Exception as e:
            self.log.error(f"[TX {self.tx_id}] TX streamer init failed: {e}")
            return False

        # ============================================================
        # TIME SOURCE
        # ============================================================

        if self.parameters.tx_use_external_time_source:
            try:
                self.usrp.set_time_source("external")
                self.log.info(f"[TX {self.tx_id}] Ustawiony zewnętrzny time source: GPS PPS")
            except Exception as e:
                self.log.error(f"[TX {self.tx_id}] Setting external time source failed: {e}")
                return False
        else:
            try:
                self.usrp.set_time_now(uhd.types.TimeSpec(0.0))
                self.log.info(f"[TX {self.tx_id}] Czas USRP wyzerowany lokalnie")
            except Exception as e:
                self.log.warning(f"[TX {self.tx_id}] Nie udało się wyzerować czasu USRP: {e}")

        self.tx_md = uhd.types.TXMetadata()
        self.tx_md.start_of_burst = True
        self.tx_md.end_of_burst = False
        self.tx_md.has_time_spec = False

        self.log.info(f"[TX {self.tx_id}] USRP initialized")

        # ============================================================
        # PPS CHECK
        # ============================================================

        if self.parameters.tx_use_external_time_source and not self.parameters.test_mode:
            sync_monitor = SyncMonitor(self.usrp, self.tx_id, "tx")

            if sync_monitor.wait_for_pps_lock(timeout=5.0, verbose=True):
                sync_monitor.print_sync_stats()
                self.log.info(f"[TX {self.tx_id}] GPS PPS zsynchronizowany")
            else:
                self.log.error(f"[TX {self.tx_id}] Brak synchronizacji GPS PPS")
                return False

        elif self.parameters.test_mode:
            self.log.info(f"[TX {self.tx_id}] TEST MODE - pomijam weryfikację PPS")

        return True

    def _generate_samples(self):
        n = int(self.parameters.iq_samples_per_packet)
        fs = float(self.parameters.tx_samp_rate)

        tx_idx = int(self.tx_id)

        f0 = float(
            self.parameters.tx_tone_offsets.get(
                tx_idx,
                self.parameters.tx_tone_offset_hz
            )
        )

        amp = float(self.tx_amplitude)
        phi = float(self.tx_phase)

        t = np.arange(n, dtype=np.float32)

        sig = amp * np.exp(
            1j * (2.0 * np.pi * f0 * t / fs + phi)
        )

        sig = sig.astype(np.complex64)

        self.log.info(
            f"[TX {self.tx_id}] GENERUJĘ PRÓBKI | "
            f"n={n} | "
            f"duration={n / fs * 1000.0:.3f} ms | "
            f"amp={amp:.3f} | "
            f"phase={phi:.6f} rad | "
            f"phase_deg={np.rad2deg(phi):.3f} deg | "
            f"f0={f0:.1f} Hz | "
            f"max_abs={np.max(np.abs(sig)):.6f} | "
            f"mean_power={np.mean(np.abs(sig) ** 2):.9f}"
        )

        return sig

    def _send_samples(self, samples, target_time=None):
        if self.tx_streamer is None:
            self.log.error(f"[TX {self.tx_id}] Brak tx_streamer")
            return 0

        import uhd

        samples = np.atleast_2d(np.asarray(samples, dtype=np.complex64))

        self.tx_md.has_time_spec = False
        self.tx_md.start_of_burst = True
        self.tx_md.end_of_burst = True

        if target_time is not None:
            usrp_now = self.usrp.get_time_now().get_real_secs()

            if target_time < usrp_now:
                self.log.error(
                    f"[TX {self.tx_id}] LATE COMMAND | "
                    f"target_time={target_time:.6f} < usrp_now={usrp_now:.6f} | "
                    f"diff={usrp_now - target_time:.6f} s"
                )
                return 0

            self.tx_md.has_time_spec = True
            self.tx_md.time_spec = uhd.types.TimeSpec(target_time)

        try:
            num_sent = self.tx_streamer.send(samples, self.tx_md)

            self.log.info(
                f"[TX {self.tx_id}] SEND | "
                f"requested={samples.shape[1]} | sent={num_sent}"
            )

            return num_sent

        except Exception as e:
            self.log.error(f"[TX {self.tx_id}] Error sending samples: {e}")
            return 0

    def on_connect(self, rc: int):
        self.log.info(f"TX connected to MQTT | id={self.tx_id} | rc={rc}")

    def on_message(self, m: dict):
        cmd = m.get("cmd")

        if cmd == "START":
            self.log.info("TX START received")
            self.running = True

        elif cmd == "SYNC_CLOCKS":
            import uhd

            if self.usrp is None:
                self.log.warning(f"[TX {self.tx_id}] SYNC_CLOCKS ignored — USRP not initialized")
                return

            if self.parameters.tx_use_external_time_source:
                self.usrp.set_time_next_pps(uhd.types.TimeSpec(0.0))
                self.log.info(f"[TX {self.tx_id}] UZBROJONO zerowanie czasu na następnym PPS")
            else:
                self.usrp.set_time_now(uhd.types.TimeSpec(0.0))
                self.log.info(f"[TX {self.tx_id}] Zegar USRP wyzerowany natychmiastowo")

        elif cmd == "STOP":
            self.log.info("TX STOP received")
            self.running = False

        elif cmd == "TX_CMD":
            payload = m.get("payload", {})

            phase_map = payload.get("phase_map", {})
            amplitude_map = payload.get("amplitude_map", {})

            my_id = str(self.tx_id)

            if isinstance(phase_map, dict) and my_id in phase_map:
                self.tx_phase = float(phase_map[my_id])

            if isinstance(amplitude_map, dict) and my_id in amplitude_map:
                self.tx_amplitude = float(amplitude_map[my_id])

            self.log.info(
                f"TX_CMD received | "
                f"id={self.tx_id} | "
                f"phase={self.tx_phase:.6f} rad | "
                f"phase_deg={np.rad2deg(self.tx_phase):.3f} deg | "
                f"amp={self.tx_amplitude:.3f}"
            )

        elif cmd == "TX_PULSE":
            if self.continuous_mode:
                self.log.debug(f"[TX {self.tx_id}] TX_PULSE ignored — continuous TX mode")
                return

            payload = m.get("payload", {})
            target_time = payload.get("target_time")

            if target_time is None:
                self.log.error(f"[TX {self.tx_id}] TX_PULSE without target_time")
                return

            phase_map = payload.get("phase_map", {})
            amplitude_map = payload.get("amplitude_map", {})

            my_id = str(self.tx_id)

            if isinstance(phase_map, dict) and my_id in phase_map:
                self.tx_phase = float(phase_map[my_id])

            if isinstance(amplitude_map, dict) and my_id in amplitude_map:
                self.tx_amplitude = float(amplitude_map[my_id])

            self.log.info(
                f"[TX {self.tx_id}] TX_PULSE CONFIG | "
                f"target={target_time:.6f} | "
                f"phase={self.tx_phase:.6f} rad | "
                f"phase_deg={np.rad2deg(self.tx_phase):.3f} deg | "
                f"amp={self.tx_amplitude:.3f}"
            )

            usrp_time_received = None
            zapas_ms = None

            if not self.parameters.test_mode and self.usrp is not None:
                usrp_time_received = self.usrp.get_time_now().get_real_secs()
                zapas_ms = (target_time - usrp_time_received) * 1000.0

                self.log.info(
                    f"[TX {self.tx_id}] ODEBRANO ROZKAZ | "
                    f"usrp_now={usrp_time_received:.6f} s | "
                    f"target={target_time:.6f} s | "
                    f"zapas={zapas_ms:.3f} ms"
                )

            samples = self._generate_samples()

            if not self.parameters.test_mode:
                self._send_samples(samples, target_time=target_time)

                usrp_time_after_send = self.usrp.get_time_now().get_real_secs()

                self.log.info(
                    f"[TX {self.tx_id}] DANE PRZEKAZANE DO BUFORA USRP | "
                    f"usrp_after_send={usrp_time_after_send:.6f} s | "
                    f"target={target_time:.6f} s"
                )

                if usrp_time_received is not None and zapas_ms is not None:
                    with open(self.timing_csv, "a", encoding="utf-8") as f:
                        f.write(
                            f"{self.tx_id},"
                            f"{target_time:.6f},"
                            f"{usrp_time_received:.6f},"
                            f"{usrp_time_after_send:.6f},"
                            f"{zapas_ms:.3f}\n"
                        )

            self.send_message(
                "TX_ACTIVE",
                {
                    "n_samples": len(samples),
                    "target_time": target_time,
                    "phase": self.tx_phase,
                    "phase_deg": float(np.rad2deg(self.tx_phase)),
                    "amplitude": self.tx_amplitude,
                }
            )

    def _continuous_tx_loop(self):
        if self.tx_streamer is None:
            self.log.error(f"[TX {self.tx_id}] Cannot start continuous TX — tx_streamer is None")
            return

        samples = self._generate_samples()
        samples_2d = np.atleast_2d(np.asarray(samples, dtype=np.complex64))

        first_packet = True
        packet_counter = 0
        last_log_time = time.time()

        self.continuous_mode = True

        self.log.info(
            f"[TX {self.tx_id}] ENTER CONTINUOUS TX LOOP | "
            f"freq={self.parameters.tx_signal_frequency} Hz | "
            f"offset={self.parameters.tx_tone_offsets.get(int(self.tx_id), self.parameters.tx_tone_offset_hz)} Hz | "
            f"gain={self.parameters.tx_gain_db} dB | "
            f"amp={self.tx_amplitude} | "
            f"phase={self.tx_phase:.6f} rad | "
            f"phase_deg={np.rad2deg(self.tx_phase):.3f} deg | "
            f"buffer={samples_2d.shape[1]} samples"
        )

        while self.running:
            try:
                self.tx_md.has_time_spec = False
                self.tx_md.start_of_burst = first_packet
                self.tx_md.end_of_burst = False

                num_sent = self.tx_streamer.send(samples_2d, self.tx_md)

                if first_packet:
                    self.log.info(
                        f"[TX {self.tx_id}] CONTINUOUS TX STARTED | "
                        f"actual_freq={self.usrp.get_tx_freq()} Hz | "
                        f"actual_rate={self.usrp.get_tx_rate()} S/s | "
                        f"actual_gain={self.usrp.get_tx_gain()} dB | "
                        f"requested={samples_2d.shape[1]} | "
                        f"sent={num_sent}"
                    )
                    first_packet = False

                if num_sent != samples_2d.shape[1]:
                    self.log.warning(
                        f"[TX {self.tx_id}] UHD SEND PARTIAL | "
                        f"requested={samples_2d.shape[1]} | sent={num_sent}"
                    )

                packet_counter += 1

                now = time.time()
                if now - last_log_time >= 2.0:
                    self.log.info(
                        f"[TX {self.tx_id}] CONTINUOUS TX ALIVE | "
                        f"packets={packet_counter} | "
                        f"last_sent={num_sent} | "
                        f"usrp_time={self.usrp.get_time_now().get_real_secs():.6f}"
                    )
                    last_log_time = now

            except KeyboardInterrupt:
                self.log.info(f"[TX {self.tx_id}] KeyboardInterrupt — stopping TX")
                self.running = False
                break

            except Exception as e:
                self.log.error(f"[TX {self.tx_id}] Continuous TX error: {e}")
                self.running = False
                break

        try:
            self.tx_md.has_time_spec = False
            self.tx_md.start_of_burst = False
            self.tx_md.end_of_burst = True

            empty = np.zeros((1, 0), dtype=np.complex64)
            self.tx_streamer.send(empty, self.tx_md)

            self.log.info(f"[TX {self.tx_id}] CONTINUOUS TX STOPPED — EOB sent")

        except Exception as e:
            self.log.warning(f"[TX {self.tx_id}] EOB send failed: {e}")

    def _normal_system_loop(self):
        self.log.info("TX entering NORMAL RUN state — waiting for TX_PULSE commands")

        while True:
            time.sleep(0.1)

    def run(self):
        self.log.info(f"TX starting | id={self.tx_id}")
        self.connect_bus()

        self.send_message("REGISTER", {"serial": self.serial})
        self.log.info("TX registration sent")

        if not self.parameters.test_mode:
            if not self._init_usrp():
                self.log.error("TX USRP init failed → exiting")
                return

        self.send_message("READY", {})
        self.ready_sent = True
        self.log.info("TX READY sent")

        # ============================================================
        # TRYB CIĄGŁY DO ANALIZATORA WIDMA
        # ============================================================

        if self.parameters.tx_continuous_mode:
            self.log.info("TX configured in CONTINUOUS MODE")

            if self.parameters.tx_force_start_continuous:
                self.running = True
                self.log.warning(
                    f"[TX {self.tx_id}] FORCED START — standalone continuous TX test"
                )
            else:
                self.log.info("TX waiting for START before continuous TX")
                while not self.running:
                    time.sleep(0.05)

            self._continuous_tx_loop()
            return

        # ============================================================
        # NORMALNY TRYB SYSTEMOWY: START + TX_PULSE + beamforming
        # ============================================================

        self.log.info("TX configured in NORMAL SYSTEM MODE")
        while not self.running:
            time.sleep(0.05)

        self._normal_system_loop()