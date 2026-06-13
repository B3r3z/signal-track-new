from helpers.protocol import Command, ExperimentState, TrialSpec, command_value


def test_protocol_command_constants_for_trial_flow():
    assert Command.REGISTER.value == "REGISTER"
    assert Command.READY.value == "READY"
    assert Command.SYNC_CLOCKS.value == "SYNC_CLOCKS"
    assert Command.START.value == "START"
    assert Command.TX_PULSE.value == "TX_PULSE"
    assert Command.RX_CAPTURE.value == "RX_CAPTURE"
    assert Command.RX_METRIC.value == "RX_METRIC"
    assert Command.TX_DONE.value == "TX_DONE"


def test_protocol_state_constants_for_experiment_flow():
    assert ExperimentState.WAITING_FOR_COMPONENTS.value == "WAITING_FOR_COMPONENTS"
    assert ExperimentState.ARMING_TRIAL.value == "ARMING_TRIAL"
    assert ExperimentState.WAITING_FOR_RESULTS.value == "WAITING_FOR_RESULTS"
    assert ExperimentState.FINISHED.value == "FINISHED"
    assert ExperimentState.ERROR.value == "ERROR"


def test_trial_spec_and_command_value_helpers():
    trial = TrialSpec(
        trial_id=7,
        target_time=12.5,
        target="tc1",
        beam_angle_deg=30.0,
        phase_map={"0": 0.0},
        amplitude_map={"0": 0.7},
    )

    assert trial.trial_id == 7
    assert trial.target == "tc1"
    assert command_value(Command.TX_PULSE) == "TX_PULSE"
    assert command_value("CUSTOM") == "CUSTOM"
