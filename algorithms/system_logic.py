
from algorithms.beamforming import Beamforming 

class SystemLogic:
    def __init__(self, parameters, beamforming):
        self.parameters = parameters
        self.beamforming = beamforming

    def start(self):
        self.beamforming.start()

    def handle_rx_iq(self, rx_id, samples):
        self.beamforming.on_rx_iq(rx_id, samples)
        return self.beamforming.compute_tx_command()

    def handle_rx_metric(self, rx_id, metric, *, linear=False):
        self.beamforming.on_rx_metric(rx_id, metric, linear=linear)
        return self.beamforming.compute_tx_command()


