from controllers.system_controller import SystemController
from controllers.rx_controller import RXController
from controllers.tx_controller import TXController


def create_controller(controller_type, controller_id, config_path=None):
    match controller_type:
        case "system":
            return SystemController(config_path=config_path)
        case "rx":
            return RXController(controller_id, config_path=config_path)
        case "tx":
            return TXController(controller_id, config_path=config_path)
        case "fsv":
            from controllers.fsv3000_controller import FSV3000Controller
            return FSV3000Controller(controller_id, config_path=config_path)
        case _:
            raise ValueError(f"Unknown controller type: {controller_type}")
