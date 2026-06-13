import math
from types import SimpleNamespace

import pytest

from algorithms.beamforming import Beamforming


def make_params(**overrides):
    values = {
        "beamforming_mode": "optimize",
        "beamforming_input_mode": "optimize",
        "beam_angle_sweep_deg": [-30.0, 0.0, 30.0],
        "measurement_per_phase": 1,
        "tx_array_order": ["0", "1", "2", "3"],
        "tx_antenna_spacing_lambda": 0.5,
        "tx_signal_amplitude": 0.7,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_angle_to_phase_map_for_linear_array():
    params = make_params(beam_angle_sweep_deg=[30.0])
    beamforming = Beamforming(params)

    command = beamforming.current_tx_command()

    assert command["beam_angle_deg"] == 30.0
    assert command["phase_step_rad"] == pytest.approx(-math.pi / 2)
    assert command["phase_step_deg"] == pytest.approx(-90.0)
    assert command["phase_map"] == pytest.approx(
        {
            "0": 0.0,
            "1": -math.pi / 2,
            "2": -math.pi,
            "3": -3 * math.pi / 2,
        }
    )
    assert command["amplitude_map"] == {
        "0": 0.7,
        "1": 0.7,
        "2": 0.7,
        "3": 0.7,
    }


def test_optimize_mode_selects_best_angle_using_power_linear():
    beamforming = Beamforming(make_params())

    assert beamforming.current_tx_command()["beam_angle_deg"] == -30.0

    beamforming.on_rx_metric("2", 1.0, linear=True)
    next_command = beamforming.compute_tx_command()
    assert next_command["beam_angle_deg"] == 0.0
    assert next_command["finished"] is False

    beamforming.on_rx_metric("2", 4.0, linear=True)
    next_command = beamforming.compute_tx_command()
    assert next_command["beam_angle_deg"] == 30.0
    assert next_command["finished"] is False

    beamforming.on_rx_metric("2", 2.0, linear=True)
    final_command = beamforming.compute_tx_command()

    assert final_command["finished"] is True
    assert final_command["beam_angle_deg"] == 0.0
    assert final_command["best_beam_angle_deg"] == 0.0
    assert final_command["best_candidate_idx"] == 1
    assert final_command["best_metric"] == pytest.approx(10.0 * math.log10(4.0))
    assert final_command["best_phase_map"] == pytest.approx(
        beamforming.candidates[1]["phase_map"]
    )


def test_scan_mode_cycles_through_angles():
    beamforming = Beamforming(
        make_params(
            beamforming_mode="scan",
            beamforming_input_mode="scan",
            beam_angle_sweep_deg=[-10.0, 10.0],
        )
    )

    assert beamforming.current_tx_command()["candidate_idx"] == 0

    beamforming.on_rx_metric("2", 1.0, linear=True)
    next_command = beamforming.compute_tx_command()
    assert next_command["candidate_idx"] == 1
    assert next_command["beam_angle_deg"] == 10.0
    assert next_command["finished"] is False

    beamforming.on_rx_metric("2", 2.0, linear=True)
    wrapped_command = beamforming.compute_tx_command()
    assert wrapped_command["candidate_idx"] == 0
    assert wrapped_command["beam_angle_deg"] == -10.0
    assert wrapped_command["finished"] is False
