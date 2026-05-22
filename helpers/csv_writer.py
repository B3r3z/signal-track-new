import csv
from pathlib import Path
import numpy as np


class CSVWriter:

    def __init__(self, results_dir):
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def write_rx_iq(self, rx_id, samples):
        path = self.results_dir / f"rx_{rx_id}_iq.csv"

        samples = np.asarray(samples).flatten()

        with open(path, "a", newline="") as f:
            writer = csv.writer(f)

            for i, s in enumerate(samples):
                writer.writerow([
                    i,
                    float(np.real(s)),
                    float(np.imag(s)),
                ])
