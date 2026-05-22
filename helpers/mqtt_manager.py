import paho.mqtt.client as mqtt

from helpers.messages import BUS_TOPIC, parse_message, make_message


class MqttManager:
    def __init__(self, broker: str, port: int, keepalive: int = 60):
        self.broker = broker
        self.port = port
        self.keepalive = keepalive

        self.client = mqtt.Client()
        self._message_handler = None
        self._connect_handler = None

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def set_message_handler(self, handler):
        self._message_handler = handler

    def set_connect_handler(self, handler):
        self._connect_handler = handler

    def connect(self):
        self.client.connect(self.broker, self.port, self.keepalive)

    def start(self):
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    def subscribe_bus(self):
        self.client.subscribe(BUS_TOPIC)

    def send_message(self, src: str, node_id: int, cmd: str, payload=None):
        self.client.publish(
            BUS_TOPIC,
            make_message(src, node_id, cmd, payload or {}),
        )

    def _on_connect(self, client, userdata, flags, rc):
        self.subscribe_bus()
        if self._connect_handler is not None:
            self._connect_handler(rc)

    def _on_message(self, client, userdata, msg):
        if self._message_handler is None:
            return

        message = parse_message(msg.payload)
        self._message_handler(message)