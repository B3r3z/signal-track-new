# AGENTS.md

## Project overview

SDR beamforming system using USRP B210 devices synchronized via CDA-2990 clock distribution. Three MQTT-coordinated controllers (system, TX, RX) run as separate processes. Python 3.10+ required (uses `match`/`case`).

## Running

```bash
# Requires a running Mosquitto MQTT broker
python3 main.py system   # system controller (coordinator)
python3 main.py rx 0     # RX controller, index 0
python3 main.py tx 1     # TX controller, index 1
```

For local/test mode without hardware: set `self.test_mode = True` and `self.mqtt_broker = "localhost"` in `helpers/parameters.py`.

## Dependencies

`requirements.txt` is **incomplete**. Actual runtime imports also include:
- `uhd` — USRP Hardware Driver (system-level install, not pip)
- `scipy` — used in `analyze_sync.py`, `plot_latest.py`
- `matplotlib` — used in analysis/plotting scripts

## Architecture

| Directory | Purpose |
|---|---|
| `controllers/` | `system_controller.py` (coordinator), `tx_controller.py`, `rx_controller.py` |
| `helpers/` | `parameters.py` (all config), `mqtt_manager.py`, `messages.py`, `sync_monitor.py`, `csv_writer.py` |
| `algorithms/` | `beamforming.py` (sweep engine), `system_logic.py` (thin wrapper) |

- All MQTT messages flow through a single topic: `signaltrack/bus`
- RF parameters, USRP serial maps, and device counts live in `helpers/parameters.py` — this is the primary configuration file
- Hardware setup: 4 TX + 3 RX USRP B210 units at 868 MHz, 500 kS/s

## No automated testing or CI

There is no test framework (pytest, unittest, etc.). The GitHub Actions workflow is a placeholder. `test_pps.py` is a hardware diagnostic script, not an automated test.

## Conventions

- Documentation and code comments are in **Polish**
- Standalone analysis scripts (`analyze_sync.py`, `plot_latest.py`) operate on `.npy` files saved by controllers
- CDA-2990 hardware synchronization details are in `CDA2990_SETUP.md`
