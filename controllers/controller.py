
from loguru import logger
from helpers.parameters import Parameters
from helpers.mqtt_manager import MqttManager


class Controller:
    def __init__(self, role: str, node_id: int):
        self.role = role
        self.node_id = node_id

        self.parameters = Parameters()
        self.log = logger   # <-- TO BRAKOWAŁO

        self.mqtt = MqttManager(
            broker=self.parameters.mqtt_broker,
            port=self.parameters.mqtt_port,
            keepalive=self.parameters.mqtt_keepalive,
        )

        self.mqtt.set_message_handler(self.on_message)
        self.mqtt.set_connect_handler(self.on_connect)

    def connect_bus(self):
        self.mqtt.connect()
        self.mqtt.start()

    def send_message(self, cmd: str, payload=None):
        self.mqtt.send_message(
            src=self.role,
            node_id=self.node_id,
            cmd=cmd,
            payload=payload or {},
        )

    def on_connect(self, rc: int):
        pass

    def on_message(self, message: dict):
        raise NotImplementedError



# from loguru import logger as log

# class Controller:
#     def __init__(self, controller_type, controller_id):
#         self.controller_type = controller_type
#         self.controller_id = controller_id
#         self.log = log.bind(
#             type=controller_type,
#             id=controller_id
#         )

#     def run(self):
#         raise NotImplementedError
