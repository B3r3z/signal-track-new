import math
import numpy as np


class Beamforming:
    def __init__(self, parameters):
        self.parameters = parameters
        self.mode = self._normalize_mode(
            getattr(parameters, "beamforming_mode", None)
            or getattr(parameters, "beamforming_input_mode", "optimize")
        )
        self.candidates = self._build_candidates()
        self.start()

    def _normalize_mode(self, mode):
        mode = str(mode).strip().lower()

        if mode == "theta":
            return "optimize"
        if mode == "fi":
            return "manual_sweep"

        if mode not in ("optimize", "scan", "manual_sweep"):
            raise ValueError(
                f"Unknown beamforming mode: {mode}. "
                "Use optimize, scan, manual_sweep, theta or fi."
            )

        return mode

    def start(self):
        self.current_idx = 0
        self.step_counter = 0
        self.finished = False
        self.measurement_counter = 0
        self.metric_accumulator = 0.0
        self.best_metric = -np.inf
        self.best_candidate = None

    def current_tx_command(self):
        return self._build_command(self.candidates[self.current_idx])

    def on_rx_metric(self, rx_id, metric, *, linear=False):
        if linear:
            metric_lin = float(metric)
        else:
            metric_lin = 10.0 ** (float(metric) / 10.0)

        self.metric_accumulator += metric_lin
        self.measurement_counter += 1

    def on_rx_iq(self, rx_id, samples):
        samples = np.asarray(samples, dtype=np.complex64).flatten()
        power = float(np.mean(np.abs(samples) ** 2))
        self.on_rx_metric(rx_id, power, linear=True)

    def compute_tx_command(self):
        if self.measurement_counter < self.parameters.measurement_per_phase:
            return None

        metric = self.metric_accumulator / self.measurement_counter
        current_candidate = self.candidates[self.current_idx]

        if metric > self.best_metric:
            self.best_metric = metric
            self.best_candidate = current_candidate

        self.metric_accumulator = 0.0
        self.measurement_counter = 0
        self.step_counter += 1

        if self.mode == "optimize":
            return self._advance_optimize()

        if self.mode in ("scan", "manual_sweep"):
            self.current_idx = (self.current_idx + 1) % len(self.candidates)
            return self.current_tx_command()

        return None

    def _advance_optimize(self):
        if self.current_idx + 1 >= len(self.candidates):
            self.finished = True
            if self.best_candidate is not None:
                return self._build_command(self.best_candidate, finished=True)
            return self.current_tx_command()

        self.current_idx += 1
        return self.current_tx_command()

    def _build_candidates(self):
        if self.mode in ("optimize", "scan"):
            angles = list(getattr(self.parameters, "beam_angle_sweep_deg", []))
            if not angles:
                angles = [0.0]

            return [
                self._candidate_from_angle(idx, float(angle_deg))
                for idx, angle_deg in enumerate(angles)
            ]

        return self._manual_candidates()

    def _candidate_from_angle(self, idx, angle_deg):
        theta_rad = math.radians(float(angle_deg))
        phase_step = self._phase_step_from_angle(theta_rad)
        amp = float(self.parameters.tx_signal_amplitude)

        phase_map = {}
        amplitude_map = {}

        for position_idx, tx_id in enumerate(self.parameters.tx_array_order):
            phase_map[str(tx_id)] = float(position_idx * phase_step)
            amplitude_map[str(tx_id)] = amp

        return {
            "candidate_idx": idx,
            "phase_map": phase_map,
            "amplitude_map": amplitude_map,
            "beam_angle_rad": theta_rad,
            "beam_angle_deg": float(angle_deg),
            "phase_step_rad": float(phase_step),
            "phase_step_deg": float(math.degrees(phase_step)),
        }

    def _manual_candidates(self):
        phase_sweep = getattr(self.parameters, "phase_map_sweep_deg", [])
        amplitude_sweep = getattr(self.parameters, "amplitude_map_sweep", [])

        if not phase_sweep:
            phase_sweep = [
                {
                    str(tx_id): 0.0
                    for tx_id in self.parameters.get_tx_ids()
                }
            ]

        if amplitude_sweep and len(amplitude_sweep) != len(phase_sweep):
            raise ValueError(
                "amplitude_map_sweep must have the same length as "
                "phase_map_sweep_deg"
            )

        candidates = []

        for idx, phase_map_deg in enumerate(phase_sweep):
            phase_map = {
                str(tx_id): math.radians(float(phase_deg))
                for tx_id, phase_deg in phase_map_deg.items()
            }

            if amplitude_sweep:
                amplitude_map = {
                    str(tx_id): float(amp)
                    for tx_id, amp in amplitude_sweep[idx].items()
                }
            else:
                amplitude_map = {
                    str(tx_id): float(self.parameters.tx_signal_amplitude)
                    for tx_id in phase_map.keys()
                }

            candidates.append({
                "candidate_idx": idx,
                "phase_map": phase_map,
                "amplitude_map": amplitude_map,
                "beam_angle_rad": None,
                "beam_angle_deg": None,
                "phase_step_rad": None,
                "phase_step_deg": None,
            })

        return candidates

    def _phase_step_from_angle(self, theta_rad):
        d_over_lambda = float(self.parameters.tx_antenna_spacing_lambda)
        return -2.0 * math.pi * d_over_lambda * math.sin(theta_rad)

    def _best_metric_db(self):
        if self.best_metric <= 0 or self.best_metric == -np.inf:
            return None
        return float(10.0 * np.log10(self.best_metric))

    def _build_command(self, candidate, finished=None):
        if finished is None:
            finished = self.finished

        return {
            "phase_map": {
                str(tx_id): float(phase_rad)
                for tx_id, phase_rad in candidate["phase_map"].items()
            },
            "amplitude_map": {
                str(tx_id): float(amp)
                for tx_id, amp in candidate["amplitude_map"].items()
            },
            "finished": bool(finished),
            "step": int(self.step_counter),
            "candidate_idx": int(candidate["candidate_idx"]),
            "mode": self.mode,
            "beam_angle_rad": candidate["beam_angle_rad"],
            "beam_angle_deg": candidate["beam_angle_deg"],
            "phase_step_rad": candidate["phase_step_rad"],
            "phase_step_deg": candidate["phase_step_deg"],
            "best_metric": self._best_metric_db(),
            "best_candidate_idx": (
                int(self.best_candidate["candidate_idx"])
                if self.best_candidate is not None
                else None
            ),
            "best_beam_angle_deg": (
                self.best_candidate.get("beam_angle_deg")
                if self.best_candidate is not None
                else None
            ),
            "best_phase_map": (
                {
                    str(tx_id): float(phase_rad)
                    for tx_id, phase_rad in self.best_candidate["phase_map"].items()
                }
                if self.best_candidate is not None
                else None
            ),
            "best_amplitude_map": (
                {
                    str(tx_id): float(amp)
                    for tx_id, amp in self.best_candidate["amplitude_map"].items()
                }
                if self.best_candidate is not None
                else None
            ),
        }

