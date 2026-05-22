from controllers.system_controller import SystemController
from controllers.rx_controller import RXController
from controllers.tx_controller import TXController

def create_controller(controller_type, controller_id):
    match controller_type:
        case "system":
            return SystemController()
        case "rx":
            return RXController(controller_id)
        case "tx":
            return TXController(controller_id)
        case _:
            raise ValueError(f"Unknown controller type: {controller_type}")
