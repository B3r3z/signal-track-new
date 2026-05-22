import time
import os
import csv
import numpy as np

from controllers.controller import Controller
from helpers.sync_monitor import SyncMonitor


class RXController(Controller):

    def __init__(self, rx_id):
        super().__init__("rx", rx_id)

        self.rx_id = rx_id
        self.serial = self.parameters.get_rx_serial(rx_id)

        self.running = False
        self.ready_sent = False
        self.usrp = None
        self.rx_streamer = None

        import os
        import csv

        os.makedirs(self.parameters.results_dir, exist_ok=True)

        self.power_csv = os.path.join(
            self.parameters.results_dir,
            f"rx_power_rx{self.rx_id}.csv"
        )

        with open(self.power_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "target_time",
                "detected_time",
                "offset_ms",
                "samples_used",
                "avg_power_db",
                "max_power_db",
                "avg_power_lin",
                "max_power_lin"
            ])

    def _init_usrp(self):
        import uhd

        self.log.info(f"RX REAL MODE → init USRP | serial={self.serial}")
        try:
            self.usrp = uhd.usrp.MultiUSRP(f"serial={self.serial}")
        except Exception as e:
            self.log.error(f"RX init failed: {e}")
            self.usrp = None
            return False

        try:
            if self.parameters.rx_use_external_clock:
                self.usrp.set_clock_source("external")
                self.log.info(f"[RX {self.rx_id}] Ustawiony zewnętrzny clock (OCXO 10 MHz)")
            else:
                self.usrp.set_clock_source("internal")
                self.log.info(f"[RX {self.rx_id}] Ustawiony WEWNĘTRZNY clock (brak OCXO)")
        except Exception as e:
            self.log.error(f"[RX {self.rx_id}] Setting clock source failed: {e}")

        self.usrp.set_rx_rate(self.parameters.rx_samp_rate)
        self.usrp.set_rx_freq(self.parameters.center_freq)
        self.usrp.set_rx_gain(self.parameters.rx_gain_db)
        self.log.info(
            f"[RX {self.rx_id}] RF CHECK | "
            f"center_freq={self.parameters.center_freq} | "
            f"rate={self.parameters.rx_samp_rate} | "
            f"gain={self.parameters.rx_gain_db}"
        )
        # Inicjalizacja streamera RX
        st_args = uhd.usrp.StreamArgs("fc32", "sc16")
        self.rx_streamer = self.usrp.get_rx_stream(st_args)

        # =======================================================================
        # WERYFIKACJA: Jeśli brak zewnętrznego czasu (brak GPS PPS), ustawiamy czas lokalny
        # =======================================================================
        if self.parameters.rx_use_external_time_source:
            try:
                self.usrp.set_time_source("external")
                self.log.info(f"[RX {self.rx_id}] Ustawiony zewnętrzny time source (GPS PPS)")
            except Exception as e:
                self.log.error(f"[RX {self.rx_id}] Setting external time source failed: {e}")
        else:
            self.log.info(f"[RX {self.rx_id}] Używany WEWNĘTRZNY zegar (brak GPS PPS)")

        self.log.info(f"[RX {self.rx_id}] Ukończono inicjalizację parametrów radia.")
        self.log.info(f"[RX {self.rx_id}] USRP initialized")
        
        return True

    #nasluch tylko w oknie
    def _recv_window(self, target_time):
        import uhd
        margin_sec = 0.01  # Zaczynamy nasłuch 10ms przed spodziewanym czasem
        window_duration = 0.065  # Nasłuchujemy powietrze przez 25ms łącznie
        num_samps = int(self.parameters.rx_samp_rate * window_duration)
        start_time = target_time - margin_sec

        stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.num_done)
        stream_cmd.num_samps = num_samps
        stream_cmd.stream_now = False
        stream_cmd.time_spec = uhd.types.TimeSpec(start_time)

        self.rx_streamer.issue_stream_cmd(stream_cmd)

        md = uhd.types.RXMetadata()
        # Ważne: Biblioteka C++ UHD pod Pythonem wymaga zainicjowania tablicy 2D pod ilość kanałów, w przeciwnym razie wyrzuca SegFault
        samples = np.zeros((1, num_samps), dtype=np.complex64)

    #     # Ściągnięcie fizycznych próbek z bufora FPGA ze wskazanego skrawka czasu
        num_rx = self.rx_streamer.recv(samples, md, 4.0)
        
    #     # Uwidocznienie statystyk paczki!
        if num_rx == 0:
            self.log.error(f"[RX {self.rx_id}] OTRZYMANO PUSTY BUFOR (0 próbek)! Okno przepadło (Prawdopodobnie LATE COMMAND - komenda poszła w przeszłość!)")
        
        if md.has_time_spec:
            self.log.info(f"[RX {self.rx_id}] Pomyślne pobranie pakietu, RX meta timestamp: {md.time_spec.get_real_secs():.6f}")
        if md.error_code != uhd.types.RXMetadataErrorCode.none:
            self.log.error(f"[RX {self.rx_id}] BŁĄD BUFORA RX: {md.error_code}")
        
        rms_power = float(np.sqrt(np.mean(np.abs(samples[0])**2)))
        max_power = float(np.max(np.abs(samples[0])**2))
        self.log.info(f"[RX {self.rx_id}] STATYSTYKI MOCY (szum i uderzenia): Próbki: {num_samps} | RMS: {rms_power:.8f} | Max: {max_power:.8f}")

        # Powrót do użytecznego, spłaszczonego formatu macierzy 1D po bezpiecznym imporcie
        return samples[0], start_time

    def on_connect(self, rc: int):
        self.log.info(f"RX connected to MQTT | id={self.rx_id}")

    def on_message(self, m: dict):
        if m["cmd"] == "START":
            self.log.info("RX START received → ready for pulses")
            self.running = True

        elif m["cmd"] == "SYNC_CLOCKS":
            import uhd
            if self.parameters.rx_use_external_time_source:
                # RX z GPS PPS — zerowanie na krawędzi następnego PPS (precyzyjne)
                self.usrp.set_time_next_pps(uhd.types.TimeSpec(0.0))
                self.log.info(f"[RX {self.rx_id}] <==== UZBROJONO PPS ====> Zegar zrównany na następny PPS")
            else:
                # RX BEZ PPS — zerowanie natychmiast (przybliżone, ale wystarczające do otwarcia okna)
                self.usrp.set_time_now(uhd.types.TimeSpec(0.0))
                self.log.info(f"[RX {self.rx_id}] <==== ZEGAR WYZEROWANY NATYCHMIAST ====> (brak PPS, czas przybliżony)")

        elif m["cmd"] == "STOP":
            self.log.info("RX STOP received")
            self.running = False
            
        elif m["cmd"] == "RX_PULSE":
            import os
            import csv

            payload = m.get("payload", {})
            target_time = payload.get("target_time")

            if target_time is None:
                self.log.error(f"[RX {self.rx_id}] RX_PULSE bez target_time")
                return

            self.log.info(
                f"[RX {self.rx_id}] Start nasłuchu dla t={target_time:.6f}"
            )

            # odbiór próbek
            if not self.parameters.test_mode and self.rx_streamer is not None:
                samples, start_time = self._recv_window(target_time)
            else:
                start_time = target_time - 0.01
                samples = (
                    np.random.randn(12500)
                    + 1j * np.random.randn(12500)
                ).astype(np.complex64)

            os.makedirs(self.parameters.results_dir, exist_ok=True)

            # ZAPIS IQ CSV
            iq_file = os.path.join(
                self.parameters.results_dir,
                f"rx_iq_rx{self.rx_id}.csv"
            )

            with open(iq_file, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)

                for k, s in enumerate(samples):
                    t = start_time + k / self.parameters.rx_samp_rate
                    writer.writerow([
                        f"{t:.9f}",
                        float(np.real(s)),
                        float(np.imag(s))
                    ])

            # ============================================================
            # OBLICZANIE MOCY W MOMENCIE ODEBRANIA SYGNAŁU
            # ============================================================

            eps = 1e-15

            # moc chwilowa każdej próbki IQ
            power_all_lin = np.abs(samples) ** 2

            # próbka, w której sygnał był najsilniejszy
            peak_idx = int(np.argmax(power_all_lin))

            # czas odebrania maksimum sygnału
            detected_time = start_time + peak_idx / self.parameters.rx_samp_rate
            offset_ms = (detected_time - target_time) * 1000.0
            # okno wokół maksimum sygnału, z którego liczymy średnią moc
            # tutaj: 2 ms całkowitego okna, czyli +/- 1 ms od maksimum
            signal_window_sec = 0.002
            half_window = int((signal_window_sec * self.parameters.rx_samp_rate) / 2)

            i0 = max(0, peak_idx - half_window)
            i1 = min(len(samples), peak_idx + half_window + 1)

            signal_power_lin = power_all_lin[i0:i1]

            N = len(signal_power_lin)

            avg_power_lin = float(np.mean(signal_power_lin))
            max_power_lin = float(np.max(signal_power_lin))

            # wartości w dB, to jest raczej dBFS / pseudo-dBm, nie prawdziwe skalibrowane dBm
            avg_power = float(10.0 * np.log10(avg_power_lin + eps))
            max_power = float(10.0 * np.log10(max_power_lin + eps))

            with open(self.power_csv, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    f"{target_time:.6f}",
                    f"{detected_time:.9f}",
                    f"{offset_ms:.3f}",
                    N,
                    avg_power,
                    max_power,
                    avg_power_lin,
                    max_power_lin
                ])

            self.log.info(
                f"[RX {self.rx_id}] "
                f"target={target_time:.6f} | "
                f"t_odebrania={detected_time:.9f} | "
                f"offset={offset_ms:.3f} ms | "
                f"AvgPower={avg_power:.2f} dB | "
                f"MaxPower={max_power:.2f} dB | "
                f"próbki_do_średniej={N}"
            )

            # WYSYŁKA DO SYSTEMU
            self.send_message("METRIC", {
                "value": avg_power,
                "avg_power_db": avg_power,
                "max_power_db": max_power,
                "avg_power_lin": avg_power_lin,
                "max_power_lin": max_power_lin,
                "samples_used": N,
                "target_time": target_time,
                "detected_time": detected_time,
                "offset_ms": offset_ms
            })


    def run(self):
        self.log.info(f"RX starting | id={self.rx_id}")
        self.connect_bus()

        self.send_message("REGISTER", {"serial": self.serial})
        self.log.info("RX registration sent")

        if not self.parameters.test_mode:
            if not self._init_usrp():
                self.log.error("RX USRP init failed → exiting")
                return

        self.send_message("READY", {})
        self.ready_sent = True
        self.log.info("RX READY sent")

        while not self.running:
            self.process_pending_messages()
            time.sleep(0.05)

        self.log.info("RX entering RUN state - waiting for RX_PULSE commands")

        while True:
            self.process_pending_messages()
            time.sleep(0.01)