import math
import numpy as np


class Beamforming:
    def __init__(self, parameters):
        self.parameters = parameters

        self.mode = getattr(
            self.parameters,
            "beamforming_input_mode",
            "theta"
        )

        if self.mode == "theta":
            self.angle_candidates = [
                math.radians(x)
                for x in self.parameters.beam_angle_sweep_deg
            ]

        
        elif self.mode == "fi":
                    self.phase_map_candidates = [
                        {
                            str(tx_id): math.radians(phi_deg)
                            for tx_id, phi_deg in phase_map.items()
                        }
                        for phase_map in self.parameters.phase_map_sweep_deg
                    ]

                    # Opcjonalny sweep amplitud.
                    # Jeśli nie ma amplitude_map_sweep w parameters.py,
                    # program zachowa stare zachowanie: wszystkie TX z tą samą amplitudą.
                    default_amp = float(self.parameters.tx_signal_amplitude)

                    if hasattr(self.parameters, "amplitude_map_sweep"):
                        if len(self.parameters.amplitude_map_sweep) != len(self.phase_map_candidates):
                            raise ValueError(
                                "amplitude_map_sweep musi mieć taką samą długość jak "
                                "phase_map_sweep_deg"
                            )

                        self.amplitude_map_candidates = [
                            {
                                str(tx_id): float(amp)
                                for tx_id, amp in amplitude_map.items()
                            }
                            for amplitude_map in self.parameters.amplitude_map_sweep
                        ]
                    else:
                        self.amplitude_map_candidates = [
                            {
                                str(tx_id): default_amp
                                for tx_id in phase_map.keys()
                            }
                            for phase_map in self.phase_map_candidates
                        ]
        else:
            raise ValueError(
                f"Unknown beamforming_input_mode: {self.mode}. "
                f"Use 'theta' or 'fi'."
            )

        self.start()

    def start(self):
        self.current_idx = 0
        self.best_metric = -np.inf

        self.best_angle = 0.0
        self.best_phase_map = None
        self.best_amplitude_map = None
        self.finished = False
        self.metric_accumulator = 0.0
        self.measurement_counter = 0
        self.step_counter = 0

    def on_rx_metric(self, rx_id, metric):
        self.metric_accumulator += float(metric)
        self.measurement_counter += 1

    def on_rx_iq(self, rx_id, samples):
        samples = np.asarray(samples, dtype=np.complex64).flatten()
        power = float(np.mean(np.abs(samples) ** 2))
        self.metric_accumulator += power
        self.measurement_counter += 1

    def compute_tx_command(self):
        if self.mode == "theta":
            return self._compute_theta_mode()

        if self.mode == "fi":
            return self._compute_fi_mode()

        return None

    def _compute_theta_mode(self):
        if self.finished:
            return self._build_from_theta(self.best_angle, True)

        if self.measurement_counter < self.parameters.measurement_per_phase:
            return None

        metric = self.metric_accumulator / self.measurement_counter
        current_angle = self.angle_candidates[self.current_idx]

        if metric > self.best_metric:
            self.best_metric = metric
            self.best_angle = current_angle

        self.current_idx += 1
        self.step_counter += 1
        self.metric_accumulator = 0.0
        self.measurement_counter = 0

        if self.current_idx >= len(self.angle_candidates):
            self.finished = True
            next_angle = self.best_angle
        else:
            next_angle = self.angle_candidates[self.current_idx]

        return self._build_from_theta(next_angle, self.finished)

    def _compute_fi_mode(self):
            if self.measurement_counter < self.parameters.measurement_per_phase:
                return None

            metric = self.metric_accumulator / self.measurement_counter

            current_phase_map = self.phase_map_candidates[self.current_idx]
            current_amplitude_map = self.amplitude_map_candidates[self.current_idx]

            if metric > self.best_metric:
                self.best_metric = metric
                self.best_phase_map = current_phase_map
                self.best_amplitude_map = current_amplitude_map

            self.current_idx += 1
            self.step_counter += 1
            self.metric_accumulator = 0.0
            self.measurement_counter = 0

            if self.current_idx >= len(self.phase_map_candidates):
                self.current_idx = 0

            next_phase_map = self.phase_map_candidates[self.current_idx]
            next_amplitude_map = self.amplitude_map_candidates[self.current_idx]

            return self._build_from_fi(next_phase_map, next_amplitude_map, False)
    def _phase_step_from_angle(self, theta_rad):
        d_over_lambda = self.parameters.tx_antenna_spacing_lambda
        return -2.0 * math.pi * d_over_lambda * math.sin(theta_rad)

    def _build_from_theta(self, beam_angle_rad, finished):
        amp = self.parameters.tx_signal_amplitude
        phase_step = self._phase_step_from_angle(beam_angle_rad)

        phase_map = {}
        amplitude_map = {}

        for position_idx, tx_id in enumerate(self.parameters.tx_array_order):
            phase_map[str(tx_id)] = float(position_idx * phase_step)
            amplitude_map[str(tx_id)] = float(amp)

        return {
            "phase_map": phase_map,
            "amplitude_map": amplitude_map,
            "finished": finished,
            "step": self.step_counter,

            "mode": "theta",

            "beam_angle_rad": float(beam_angle_rad),
            "beam_angle_deg": float(math.degrees(beam_angle_rad)),

            "phase_step_rad": float(phase_step),
            "phase_step_deg": float(math.degrees(phase_step)),

            "best_angle_rad": float(self.best_angle),
            "best_angle_deg": float(math.degrees(self.best_angle)),

            "best_metric": float(self.best_metric),
        }

    def _build_from_fi(self, phase_map, amplitude_map, finished):
            return {
                "phase_map": {
                    str(tx_id): float(phase_rad)
                    for tx_id, phase_rad in phase_map.items()
                },
                "amplitude_map": {
                    str(tx_id): float(amp)
                    for tx_id, amp in amplitude_map.items()
                },
                "finished": finished,
                "step": self.step_counter,

                "mode": "fi",

                "beam_angle_rad": None,
                "beam_angle_deg": None,

                "phase_step_rad": None,
                "phase_step_deg": None,

                "best_angle_rad": None,
                "best_angle_deg": None,

                "best_metric": float(self.best_metric),
            }