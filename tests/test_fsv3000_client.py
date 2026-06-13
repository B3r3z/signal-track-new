from types import SimpleNamespace

import controllers.fsv3000_controller as fsv_module

from controllers.fsv3000_controller import FSV3000IqClient


def test_fsv_client_defaults_to_socket_resource_without_visa():
    params = SimpleNamespace(fsv_ip="192.168.8.20", test_mode=True)

    client = FSV3000IqClient(params)

    assert client.resource == "TCPIP::192.168.8.20::5025::SOCKET"


def test_fsv_client_keeps_explicit_resource():
    params = SimpleNamespace(
        fsv_resource="TCPIP::192.168.8.20::hislip0",
        test_mode=True,
    )

    client = FSV3000IqClient(params)

    assert client.resource == "TCPIP::192.168.8.20::hislip0"


def test_fsv_client_uses_raw_socket_for_socket_resource(monkeypatch):
    opened = []

    class FakeSocketClient:
        def __init__(self, resource, timeout_ms):
            self.resource = resource
            self.timeout_ms = timeout_ms

        def open(self):
            opened.append(("open", self.resource, self.timeout_ms))

        def query_str(self, cmd):
            opened.append(("query", cmd))
            return "Rohde&Schwarz,FSV3000,SN,FW"

    monkeypatch.setattr(fsv_module, "RawSocketScpiClient", FakeSocketClient)
    monkeypatch.setattr(FSV3000IqClient, "configure", lambda self: None)

    params = SimpleNamespace(
        fsv_ip="192.168.8.20",
        fsv_timeout_ms=1234,
        test_mode=False,
    )

    client = FSV3000IqClient(params)
    idn = client.open()

    assert idn == "Rohde&Schwarz,FSV3000,SN,FW"
    assert opened == [
        ("open", "TCPIP::192.168.8.20::5025::SOCKET", 1234),
        ("query", "*IDN?"),
    ]
