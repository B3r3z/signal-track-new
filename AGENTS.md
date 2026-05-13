# AGENTS.md

## Project Overview

Python beamforming signal tracker using USRP SDR hardware and MQTT messaging.

## Structure

- `signaltrack/` — main application directory (entry point: `main.py`)
- `helpers/parameters.py` — central config: `rx_count`, `tx_count`, USRP serial maps, MQTT settings, `test_mode`

## Running

```bash
cd signaltrack
python3 main.py system
python3 main.py rx 0
python3 main.py tx 1
```

## Key Config (`helpers/parameters.py`)

- `rx_count` / `tx_count` — number of receivers/transmitters
- `tx_usrp_serial_map` / `rx_usrp_serial_map` — maps device IDs to Linux USRP serial numbers
- `test_mode = True` — use when no USRP hardware connected (home/lab without devices)
- `mqtt_broker = "localhost"` — set to broker IP in field; `"localhost"` when testing locally

## Prerequisites

- Install Mosquitto MQTT broker: `sudo apt install mosquitto mosquitto-clients`
- Discover connected USRPs: `uhd_find_devices`
- Python virtualenv: create `.venv`, then populate `requirements.txt` and install

## Dev Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Branch

- Main branch: `main`
