from types import SimpleNamespace

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
