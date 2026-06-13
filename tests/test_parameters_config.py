import textwrap

import pytest

from helpers.parameters import Parameters


def write_config(tmp_path, body):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(textwrap.dedent(body), encoding="utf-8")
    return config_path


def test_config_loading_and_tx_node_selection(tmp_path):
    config_path = write_config(
        tmp_path,
        """
        mqtt:
          broker: localhost
          port: 1884
          keepalive: 30

        timing:
          trial_lead_time_s: 2.0
          trial_timeout_s: 5.0
          trial_interval_s: 6.0
          pre_trigger_s: 0.02
          capture_time_s: 0.2

        nodes:
          tx:
            "0":
              serial: "TX000"
              external_clock: true
              external_time_source: true
            "1":
              serial: "TX001"
              external_clock: false
              external_time_source: false
          rx:
            "0":
              serial: "RX000"
              external_clock: false
              external_time_source: false
            "1":
              serial: "RX001"
              external_clock: true
              external_time_source: true

        targets:
          tc1:
            rx_id: "1"

        beamforming:
          mode: optimize
          target: tc1
          tx_array_order: ["0", "1"]
          tx_antenna_spacing_lambda: 0.25
          scan_angles_deg: [-30, 0, 30]
          repeats_per_angle: 2
          tx_signal_amplitude: 0.5

        calibration:
          enabled: false
          continue_on_failure: true

        fsv:
          enabled: true
          capture_every_trial: false
          required_for_beamforming: false
          address: "192.168.8.200"
        """,
    )

    params = Parameters(config_path=config_path, role="tx", node_id=1)

    assert params.mqtt_broker == "localhost"
    assert params.mqtt_port == 1884
    assert params.mqtt_keepalive == 30
    assert params.trial_lead_time_s == 2.0
    assert params.trial_timeout_s == 5.0
    assert params.trial_interval_s == 6.0
    assert params.pre_trigger_s == 0.02
    assert params.capture_time_s == 0.2

    assert params.get_tx_ids() == ["0", "1"]
    assert params.get_rx_ids() == ["0", "1"]
    assert params.get_tx_serial("1") == "TX001"
    assert params.get_rx_serial("0") == "RX000"

    assert params.node_config["serial"] == "TX001"
    assert params.tx_use_external_clock is False
    assert params.tx_use_external_time_source is False

    assert params.beamforming_mode == "optimize"
    assert params.beamforming_target == "tc1"
    assert params.tx_array_order == ["0", "1"]
    assert params.tx_antenna_spacing_lambda == 0.25
    assert params.beam_angle_sweep_deg == [-30.0, 0.0, 30.0]
    assert params.measurement_per_phase == 2
    assert params.tx_signal_amplitude == 0.5
    assert params.calibration_enabled is False
    assert params.calibration_continue_on_failure is True
    assert params.fsv_enabled is True
    assert params.fsv_capture_every_trial is False
    assert params.fsv_address == "192.168.8.200"


def test_config_loading_and_rx_node_selection(tmp_path):
    config_path = write_config(
        tmp_path,
        """
        nodes:
          rx:
            "2":
              serial: "RX002"
              external_clock: true
              external_time_source: true
        """,
    )

    params = Parameters(config_path=config_path, role="rx", node_id="2")

    assert params.node_config["serial"] == "RX002"
    assert params.rx_use_external_clock is True
    assert params.rx_use_external_time_source is True


def test_missing_role_node_config_raises(tmp_path):
    config_path = write_config(
        tmp_path,
        """
        nodes:
          tx:
            "0":
              serial: "TX000"
        """,
    )

    with pytest.raises(ValueError, match="Missing config section for tx node id=1"):
        Parameters(config_path=config_path, role="tx", node_id=1)


def test_target_mapping_tc1_to_rx_id(tmp_path):
    config_path = write_config(
        tmp_path,
        """
        targets:
          tc1:
            rx_id: "2"
          tc2:
            rx_id: "0"
        beamforming:
          target: tc1
        """,
    )

    params = Parameters(config_path=config_path)

    assert params.get_target_rx_id("tc1") == "2"
    assert params.get_target_rx_id() == "2"
    assert params.beamforming_target_rx_id == "2"

    with pytest.raises(ValueError, match="Unknown beamforming target"):
        params.get_target_rx_id("missing")


def test_default_sync_configuration_prefers_pps_without_external_10mhz():
    params = Parameters()

    assert params.tx_use_external_clock is False
    assert params.rx_use_external_clock is False
    assert params.tx_use_external_time_source is True
    assert params.rx_use_external_time_source is True
