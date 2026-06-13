
import queue

from loguru import logger
from helpers.parameters import Parameters
from helpers.mqtt_manager import MqttManager
from helpers.protocol import command_value


class Controller:
    def __init__(self, role: str, node_id: int, config_path=None):
        self.role = role
        self.node_id = node_id

        self.parameters = Parameters(
            config_path=config_path,
            role=role,
            node_id=node_id,
        )
        self.log = logger   # <-- TO BRAKOWAŁO

        # Kolejka wiadomości MQTT — callback paho tylko wrzuca wiadomości,
        # przetwarzanie odbywa się w wątku głównym kontrolera.
        # Rozwiązuje problem blokowania wątku sieciowego paho
        # przez ciężkie operacje (odbiór USRP, obliczenia, zapis CSV).
        self._message_queue = queue.Queue()

        self.mqtt = MqttManager(
            broker=self.parameters.mqtt_broker,
            port=self.parameters.mqtt_port,
            keepalive=self.parameters.mqtt_keepalive,
        )

        self.mqtt.set_message_handler(self._enqueue_message)
        self.mqtt.set_connect_handler(self.on_connect)

    def _enqueue_message(self, message: dict):
        """Wywoływane z wątku paho — tylko wkłada do kolejki, nie blokuje."""
        self._message_queue.put(message)

    def process_pending_messages(self):
        """
        Przetwarza wszystkie oczekujące wiadomości z kolejki MQTT.
        Powinno być wywoływane regularnie z głównej pętli kontrolera.
        """
        while True:
            try:
                message = self._message_queue.get_nowait()
            except queue.Empty:
                break
            self.on_message(message)

    def connect_bus(self):
        self.mqtt.connect()
        self.mqtt.start()

    def send_message(self, cmd: str, payload=None):
        self.mqtt.send_message(
            src=self.role,
            node_id=self.node_id,
            cmd=command_value(cmd),
            payload=payload or {},
        )

    def on_connect(self, rc: int):
        pass

    def on_message(self, message: dict):
        raise NotImplementedError
