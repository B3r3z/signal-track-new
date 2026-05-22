class Parameters:

    def __init__(self):

        self.test_mode = False

        # ============================================================
        # TRYB TX
        # ============================================================

        # Beamforming systemowy: musi być False
        self.tx_continuous_mode = False
        self.tx_force_start_continuous = False

        # ============================================================
        # SYNCHRONIZACJA TX
        # ============================================================
        # Dla 4 osobnych B210 to jest konieczne do sensownego fazowania.
        # Wszystkie TX muszą mieć wspólny/stabilny 10 MHz REF IN i PPS.
        self.tx_use_external_clock = True
        self.tx_use_external_time_source = True

        # RX mogą zostać bez PPS, ale do precyzyjnych pomiarów lepiej też zsynchronizować.
        self.rx_use_external_clock = False
        self.rx_use_external_time_source = False

        # Stare flagi — zachowane dla kompatybilności
        self.use_external_clock = True
        self.use_external_time_source = True

        self.pps_timeout_sec = 2.5
        self.sync_check_interval = 0.05

        # ============================================================
        # MQTT
        # ============================================================

        self.mqtt_broker = "192.168.8.126"
        self.mqtt_port = 1883
        self.mqtt_keepalive = 60

        # ============================================================
        # RF
        # ============================================================

        self.center_freq = 868e6

        # Do beamformingu bez diagnostycznego przesunięcia.
        self.tx_tone_offset_hz = 0.0
        self.tx_tone_offsets = {
            0: 0.0,
            1: 0.0,
            2: 0.0,
            3: 0.0
        }

        # ============================================================
        # BEAMFORMING — tryb theta
        # ============================================================
        # ============================================================
        # BEAMFORMING — ręczne fazy
        # ============================================================
        # fi = nie licz faz z kąta, tylko użyj ręcznie podanej listy faz.
        self.beamforming_input_mode = "fi"

        # Zostawione informacyjnie, ale w trybie "fi" nie jest używane do liczenia faz.
        self.tx_array_order = [3, 2, 1, 0]
        self.tx_antenna_spacing_lambda = 0.5

        # W trybie "fi" to NIE jest używane.
        # Możesz zostawić dla kompatybilności.
        self.beam_angle_sweep_deg = []

        # Ręczny sweep faz.
        # Klucze oznaczają ID nadajników: TX0, TX1, TX2, TX3.
        #
        # Stan 1: 0, 0, 0, 0
        # Stan 2: 0, 180, 0, 180
        self.phase_map_sweep_deg = [
            {"0": 0.0, "1": 0.0,   "2": 0.0, "3": 0.0},
            {"0": 0.0, "1": 180.0, "2": 0.0, "3": 180.0},
        ]

        # Wszystkie TX nadają z taką samą amplitudą w obu stanach.
        # Dajemy tyle samo wpisów co phase_map_sweep_deg.
        self.amplitude_map_sweep = [
            {"0": 0.7, "1": 0.7, "2": 0.7, "3": 0.7},
            {"0": 0.7, "1": 0.7, "2": 0.7, "3": 0.7},
        ]

        # Ile impulsów/pomiarów dla jednego stanu fazowego.
        # Np. 5 oznacza:
        # 5 strzałów z 0,0,0,0,
        # potem 5 strzałów z 0,180,0,180,
        # potem znowu cykl / albo koniec, zależnie od Twojej logiki.
        self.measurement_per_phase = 3

        # Odbiornik, pod którego optymalizujesz wiązkę:
        # "0" = RX0
        # "1" = RX1
        # "2" = RX2
        #
        # Na początek wybierz środkowy RX, ten "na przeciwko".
        self.beamforming_target_rx_id = "2"

        self.comm_rx_id = 0
        self.sensing_rx_id = 0
        self.weight_comm = 1.0
        self.weight_sensing = 0.0

        # ============================================================
        # RX
        # ============================================================

        self.rx_usrp_serial_map = {
            "0": "3273AF9",
            "1": "3273AC0",
            "2": "3273B03"
        }

        self.rx_samp_rate = 500e3
        self.rx_gain_db = 30.0
        self.rx_buffer_size = int(40e3)

        self.rx_count = 3
        self.rx_repeats = 1

        self.rx_initial_avg_power_history_dbm = -100.0
        self.rx_log_history_coeff = 0.95

        # ============================================================
        # TX — 4 nadajniki
        # ============================================================

        self.tx_usrp_serial_map = {
            "0": "3273ABF",
            "1": "3273ACB",
            "2": "3273A15",
            "3": "3273ADC"
        }

        self.tx_samp_rate = 500e3
        self.tx_gain_db = 40.0
        self.tx_buffer_size = int(40e3)

        self.tx_count = 4
        self.tx_repeats = 1

        self.tx_signal_amplitude = 0.7
        self.tx_signal_frequency = self.center_freq

        # Długość jednego impulsu TX.
        # 32768 / 500e3 = 65.536 ms
        self.iq_samples_per_packet = 32768

        self.results_dir = "results"

    def get_rx_ids(self):
        return list(self.rx_usrp_serial_map.keys())

    def get_tx_ids(self):
        return list(self.tx_usrp_serial_map.keys())

    def get_rx_serial(self, rx_id):
        return self.rx_usrp_serial_map[str(rx_id)]

    def get_tx_serial(self, tx_id):
        return self.tx_usrp_serial_map[str(tx_id)]