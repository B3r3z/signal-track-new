from pathlib import Path


class Parameters:

    def __init__(self, config_path=None, role=None, node_id=None):

        self.test_mode = False
        self.config_path = config_path
        self.role = role
        self.node_id = None if node_id is None else str(node_id)
        self.raw_config = {}
        self.node_config = {}

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
        # TIMING PROB
        # ============================================================

        self.trial_lead_time_s = 1.5
        self.trial_timeout_s = 4.0
        self.trial_interval_s = 5.0
        self.pre_trigger_s = 0.01
        self.capture_time_s = 0.1

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
        self.beamforming_mode = "optimize"
        self.beamforming_target = "tc1"

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

        self.targets = {
            "tc1": {
                "rx_id": self.beamforming_target_rx_id,
            }
        }

        self.calibration_enabled = True
        self.calibration_continue_on_failure = False

        self.fsv_enabled = False
        self.fsv_capture_every_trial = True
        self.fsv_required_for_beamforming = False

        if config_path is not None:
            self.apply_config(config_path, role=role, node_id=node_id)

    def apply_config(self, config_path, role=None, node_id=None):
        config_file = Path(config_path)

        if not config_file.exists():
            raise FileNotFoundError(f"Config file not found: {config_file}")

        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError(
                "PyYAML is required for --config. Install dependency: pyyaml"
            ) from exc

        with open(config_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        self.raw_config = data
        self.config_path = str(config_file)
        self.role = role
        self.node_id = None if node_id is None else str(node_id)

        self._apply_runtime(data.get("runtime", {}), data)
        self._apply_mqtt(data.get("mqtt", {}))
        self._apply_timing(data.get("timing", {}))
        self._apply_rf(data.get("rf", {}))
        self._apply_nodes(data.get("nodes", {}))
        self._apply_targets(data.get("targets", {}))
        self._apply_beamforming(data.get("beamforming", {}))
        self._apply_calibration(data.get("calibration", {}))
        self._apply_fsv(data.get("fsv", {}))
        self._select_node_config(role, node_id)

    def _apply_runtime(self, cfg, root):
        self.test_mode = bool(
            cfg.get("test_mode", root.get("test_mode", self.test_mode))
        )
        self.results_dir = str(
            cfg.get("results_dir", root.get("results_dir", self.results_dir))
        )

    def _apply_mqtt(self, cfg):
        self.mqtt_broker = cfg.get("broker", self.mqtt_broker)
        self.mqtt_port = int(cfg.get("port", self.mqtt_port))
        self.mqtt_keepalive = int(cfg.get("keepalive", self.mqtt_keepalive))

    def _apply_timing(self, cfg):
        self.trial_lead_time_s = float(
            cfg.get("trial_lead_time_s", self.trial_lead_time_s)
        )
        self.trial_timeout_s = float(
            cfg.get("trial_timeout_s", self.trial_timeout_s)
        )
        self.trial_interval_s = float(
            cfg.get("trial_interval_s", self.trial_interval_s)
        )
        self.pre_trigger_s = float(cfg.get("pre_trigger_s", self.pre_trigger_s))
        self.capture_time_s = float(cfg.get("capture_time_s", self.capture_time_s))

    def _apply_rf(self, cfg):
        if "center_freq" in cfg:
            self.center_freq = float(cfg["center_freq"])

        if "tx_samp_rate" in cfg:
            self.tx_samp_rate = float(cfg["tx_samp_rate"])

        if "rx_samp_rate" in cfg:
            self.rx_samp_rate = float(cfg["rx_samp_rate"])

        if "tx_gain_db" in cfg:
            self.tx_gain_db = float(cfg["tx_gain_db"])

        if "rx_gain_db" in cfg:
            self.rx_gain_db = float(cfg["rx_gain_db"])

        if "iq_samples_per_packet" in cfg:
            self.iq_samples_per_packet = int(cfg["iq_samples_per_packet"])

        if "tx_signal_amplitude" in cfg:
            self.tx_signal_amplitude = float(cfg["tx_signal_amplitude"])

        if "tx_signal_frequency" in cfg:
            self.tx_signal_frequency = float(cfg["tx_signal_frequency"])
        else:
            self.tx_signal_frequency = self.center_freq

        if "tx_tone_offset_hz" in cfg:
            self.tx_tone_offset_hz = float(cfg["tx_tone_offset_hz"])

        if "tx_tone_offsets" in cfg:
            self.tx_tone_offsets = {
                int(tx_id): float(offset)
                for tx_id, offset in cfg["tx_tone_offsets"].items()
            }

    def _apply_nodes(self, cfg):
        tx_nodes = cfg.get("tx", {})
        rx_nodes = cfg.get("rx", {})

        if tx_nodes:
            self.tx_usrp_serial_map = {
                str(node_id): str(node_cfg.get("serial", ""))
                for node_id, node_cfg in tx_nodes.items()
            }
            self.tx_count = len(self.tx_usrp_serial_map)

        if rx_nodes:
            self.rx_usrp_serial_map = {
                str(node_id): str(node_cfg.get("serial", ""))
                for node_id, node_cfg in rx_nodes.items()
            }
            self.rx_count = len(self.rx_usrp_serial_map)

    def _apply_targets(self, cfg):
        if cfg:
            self.targets = {
                str(name): {
                    **value,
                    "rx_id": str(value.get("rx_id")),
                }
                for name, value in cfg.items()
            }

            if self.beamforming_target in self.targets:
                self.beamforming_target_rx_id = (
                    self.targets[self.beamforming_target]["rx_id"]
                )

    def _apply_beamforming(self, cfg):
        mode = cfg.get("mode")
        if mode is not None:
            self.beamforming_mode = str(mode)
            self.beamforming_input_mode = str(mode)

        self.beamforming_target = str(
            cfg.get("target", self.beamforming_target)
        )

        if self.beamforming_target in self.targets:
            self.beamforming_target_rx_id = (
                self.targets[self.beamforming_target]["rx_id"]
            )

        if "tx_array_order" in cfg:
            self.tx_array_order = [str(x) for x in cfg["tx_array_order"]]

        if "tx_antenna_spacing_lambda" in cfg:
            self.tx_antenna_spacing_lambda = float(
                cfg["tx_antenna_spacing_lambda"]
            )

        if "scan_angles_deg" in cfg:
            self.beam_angle_sweep_deg = [float(x) for x in cfg["scan_angles_deg"]]

        if "repeats_per_angle" in cfg:
            self.measurement_per_phase = int(cfg["repeats_per_angle"])

        if "tx_signal_amplitude" in cfg:
            self.tx_signal_amplitude = float(cfg["tx_signal_amplitude"])

        if "phase_map_sweep_deg" in cfg:
            self.phase_map_sweep_deg = cfg["phase_map_sweep_deg"]

        if "amplitude_map_sweep" in cfg:
            self.amplitude_map_sweep = cfg["amplitude_map_sweep"]

    def _apply_calibration(self, cfg):
        self.calibration_enabled = bool(
            cfg.get("enabled", self.calibration_enabled)
        )
        self.calibration_continue_on_failure = bool(
            cfg.get(
                "continue_on_failure",
                self.calibration_continue_on_failure,
            )
        )

    def _apply_fsv(self, cfg):
        self.fsv_enabled = bool(cfg.get("enabled", self.fsv_enabled))
        self.fsv_capture_every_trial = bool(
            cfg.get("capture_every_trial", self.fsv_capture_every_trial)
        )
        self.fsv_required_for_beamforming = bool(
            cfg.get(
                "required_for_beamforming",
                self.fsv_required_for_beamforming,
            )
        )

        for key, value in cfg.items():
            setattr(self, f"fsv_{key}", value)

    def _select_node_config(self, role, node_id):
        if role not in ("tx", "rx"):
            return

        node_id = str(node_id)
        nodes = self.raw_config.get("nodes", {}).get(role, {})

        if node_id not in nodes:
            raise ValueError(
                f"Missing config section for {role} node id={node_id}"
            )

        self.node_config = nodes[node_id] or {}

        if role == "tx":
            self.tx_use_external_clock = bool(
                self.node_config.get(
                    "external_clock",
                    self.tx_use_external_clock,
                )
            )
            self.tx_use_external_time_source = bool(
                self.node_config.get(
                    "external_time_source",
                    self.tx_use_external_time_source,
                )
            )

        if role == "rx":
            self.rx_use_external_clock = bool(
                self.node_config.get(
                    "external_clock",
                    self.rx_use_external_clock,
                )
            )
            self.rx_use_external_time_source = bool(
                self.node_config.get(
                    "external_time_source",
                    self.rx_use_external_time_source,
                )
            )

    def get_target_rx_id(self, target=None):
        target = str(target or self.beamforming_target)

        if target not in self.targets:
            raise ValueError(f"Unknown beamforming target: {target}")

        return str(self.targets[target]["rx_id"])

    def get_expected_node_ids(self, role):
        if role == "tx":
            return self.get_tx_ids()
        if role == "rx":
            return self.get_rx_ids()
        raise ValueError(f"Unknown role: {role}")

    def get_rx_ids(self):
        return list(self.rx_usrp_serial_map.keys())

    def get_tx_ids(self):
        return list(self.tx_usrp_serial_map.keys())

    def get_rx_serial(self, rx_id):
        return self.rx_usrp_serial_map[str(rx_id)]

    def get_tx_serial(self, tx_id):
        return self.tx_usrp_serial_map[str(tx_id)]
