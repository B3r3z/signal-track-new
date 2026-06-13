from dataclasses import dataclass
from enum import Enum


class Command(str, Enum):
    REGISTER = "REGISTER"
    READY = "READY"
    SYNC_CLOCKS = "SYNC_CLOCKS"
    START = "START"
    STOP = "STOP"
    TX_PULSE = "TX_PULSE"
    RX_CAPTURE = "RX_CAPTURE"
    RX_PULSE = "RX_PULSE"
    TX_DONE = "TX_DONE"
    TX_ACTIVE = "TX_ACTIVE"
    RX_METRIC = "RX_METRIC"
    METRIC = "METRIC"
    FSV_PHASE_METRIC = "FSV_PHASE_METRIC"


class ExperimentState(str, Enum):
    WAITING_FOR_COMPONENTS = "WAITING_FOR_COMPONENTS"
    SYNCING_CLOCKS = "SYNCING_CLOCKS"
    READY_TO_MEASURE = "READY_TO_MEASURE"
    ARMING_TRIAL = "ARMING_TRIAL"
    WAITING_FOR_RESULTS = "WAITING_FOR_RESULTS"
    PROCESSING_RESULTS = "PROCESSING_RESULTS"
    FINISHED = "FINISHED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class TrialSpec:
    trial_id: int
    target_time: float
    target: str
    beam_angle_deg: float | None
    phase_map: dict
    amplitude_map: dict


def command_value(cmd):
    if isinstance(cmd, Command):
        return cmd.value
    return str(cmd)

