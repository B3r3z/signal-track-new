# Software Design Document (SDD) — SignalTrack Beamforming System

## 1. System Purpose

SignalTrack is a real-time testbed for validating phased-array beamforming algorithms on physical SDR hardware. A 4-element USRP B210 transmitter array operating at 868 MHz emits phase-coherent RF pulses toward 3 spatially separated USRP B210 receivers. The system iteratively sweeps TX phase and amplitude configurations, measures received signal power, and converges on the beamforming pattern that maximizes power at a designated target receiver.

All devices are time-synchronized via a CDA-2990 clock distribution accessory (shared 10 MHz reference + 1 PPS). Eight separate processes (1 coordinator + 4 TX + 3 RX) communicate over MQTT, forming a closed control loop: transmit, measure, adjust, repeat.

---

## 2. High-Level Architecture

```
 ┌─────────────────────────────────────────────────────────────────┐
 │                    Host(s) — Python 3.10+                      │
 │                                                                │
 │  ┌────────────────┐    ┌───────────┐ ×4    ┌───────────┐ ×3   │
 │  │ System         │    │ TX Ctrl   │       │ RX Ctrl   │       │
 │  │ Controller     │    │           │       │           │       │
 │  │                │    │ USRP B210 │       │ USRP B210 │       │
 │  │ (no hardware)  │    │ (transmit)│       │ (receive) │       │
 │  │ Beamforming    │    └─────┬─────┘       └─────┬─────┘       │
 │  │ Algorithm      │          │                   │             │
 │  └───────┬────────┘          │                   │             │
 │          │                   │                   │             │
 │          └──────── MQTT Bus (signaltrack/bus) ───┘             │
 │                              │                                 │
 └──────────────────────────────│─────────────────────────────────┘
                                │
                    ┌───────────┴───────────┐
                    │  CDA-2990 Clock Dist  │
                    │  10 MHz REF + 1 PPS   │
                    └───────────────────────┘
```

The system consists of 8 separate OS processes — each launched as a `python3 main.py <role> [id]` invocation. All processes can run on the same host or be distributed across machines; the only requirement is that they share the same MQTT broker.

- **SystemController** (1 instance) — Pure software, no USRP hardware. Orchestrates startup, triggers 5-second measurement cycles, collects power metrics from all RX, runs the beamforming optimization algorithm, and logs results to CSV.
- **TXController** (4 instances, one per USRP) — Each manages a single USRP B210 transmitter. Generates IQ samples with the phase and amplitude commanded by the system, and schedules transmission at an exact hardware time.
- **RXController** (3 instances, one per USRP) — Each manages a single USRP B210 receiver. Opens a timed receive window around the expected pulse, computes power metrics, and reports them back to the system.

All communication flows through a single MQTT topic (`signaltrack/bus`) as JSON-encoded messages. Processes have no shared state beyond what they exchange over MQTT.

---

## 3. Operational Flow

### 3.1 Startup and Synchronization

Each TX/RX process follows the same startup sequence independently:

```
  Single TX or RX node                      SystemController
       │                                           │
       │──── REGISTER(serial) ────────────────────>│
       │                                           │
       │  (init USRP hardware)                     │
       │  (set clock/time source)                  │
       │  (verify PPS lock — TX only by default)   │
       │                                           │
       │──── READY ───────────────────────────────>│
       │                                           │
       :     ... other nodes do the same ...       :
       │                                           │
       │                          (all 4 TX + 3 RX │
       │                           reported READY) │
       │                                           │
       │<──── SYNC_CLOCKS ────────────────────────│
       │                                           │
       │  (set_time_next_pps(0.0) — arm FPGA       │  (wait 3 s for PPS edge)
       │   clock reset on next PPS rising edge)     │
       │                                           │
       │<──── START ──────────────────────────────│
```

Nodes register and initialize independently — there is no required order between TX and RX processes. The SystemController simply waits until the expected count of READY messages has arrived (4 TX + 3 RX) before proceeding.

**What SYNC_CLOCKS does:** Every USRP device calls `set_time_next_pps(TimeSpec(0.0))`, which arms the FPGA to reset its internal clock to zero on the next 1 PPS rising edge from the CDA-2990. Since all devices share the same PPS signal, all clocks align to within nanoseconds. The SystemController waits 3 seconds after sending SYNC_CLOCKS (guaranteeing at least one PPS edge has passed) before sending START.

### 3.2 Measurement Cycle (repeats every 5 seconds)

```
  SystemController              TX0..TX3                RX0..RX2
       │                            │                       │
       │                            │                       │
       │── RX_PULSE(target_time) ──────────────────────────>│  (1) RX arms first
       │                            │                       │
       │── TX_PULSE(target_time, ──>│                       │
       │     phase_map, amp_map)    │                       │  (2) TX schedules burst
       │                            │                       │
       │                    generate IQ with          open receive window
       │                    commanded phase           [target-10ms .. +55ms]
       │                    and amplitude             65 ms total capture
       │                            │                       │
       │                    schedule burst at          capture IQ samples
       │                    exact target_time          from USRP FPGA buffer
       │                    via UHD time_spec          │
       │                            │                       │
       │<─── TX_ACTIVE (broadcast) ─┤                       │  (3) confirmation on bus
       │                            │                       │
       │                            │                  compute power metrics:
       │                            │                  - find peak power sample
       │                            │                  - avg/max power in 2ms
       │                            │                    window around peak
       │                            │                  - detected_time, offset
       │                            │                       │
       │<──────────────────────── METRIC ──────────────────│  (4) per RX
       │                                                    │
       │  (wait for METRIC from all 3 RX)                   │
       │  (feed target RX metric to beamforming)            │
       │  (compute next TX phase/amp config)                │
       │  (log complete row to CSV)                         │
       │                                                    │
       └──── (wait 5 seconds, repeat) ─────────────────────>
```

**Ordering matters:** The SystemController sends RX_PULSE *before* TX_PULSE. RX nodes need time to arm the USRP receive window (issue a stream command to the FPGA) before the TX burst arrives on air. Both commands carry the same `target_time`.

**TX_ACTIVE** is a broadcast confirmation published on the shared bus. The SystemController logs it but does not depend on it. RX nodes do not use it.

**Timing model:** The SystemController maintains a `virtual_time` counter (starts at 5.0, increments by 5.0 each cycle). This counter is used as `target_time` — a value in the synchronized USRP hardware clock domain. Each TX schedules its burst to begin at exactly that hardware time using UHD's `time_spec`. Each RX opens a receive window starting 10 ms before `target_time` and lasting 65 ms (32500 samples at 500 kS/s).

### 3.3 Beamforming Optimization Loop

After collecting METRIC from all 3 RX for a given `target_time`, the SystemController:

1. Extracts the `avg_power_db` from the designated **target RX** (configurable via `beamforming_target_rx_id`, default RX2).
2. **Guard:** If the metric is below -140 dB, the measurement is discarded as empty/noise and the beamforming state is not updated.
3. Feeds the metric to the beamforming algorithm via `SystemLogic.handle_rx_metric()`.
4. The algorithm accumulates `measurement_per_phase` measurements (default: 3) per phase configuration, then averages them.
5. After enough measurements, it advances to the next candidate configuration and returns a new `tx_command` (phase_map + amplitude_map).
6. The SystemController stores this command and uses it for the next TX_PULSE.
7. A complete CSV row is written containing: both the TX configuration *used* for this measurement and the *next* configuration computed from it.

This creates a closed-loop optimization: transmit -> measure -> adjust phases -> repeat.

---

## 4. Beamforming Algorithm

The `Beamforming` class (`algorithms/beamforming.py`) implements a sweep-and-select optimization. It supports two modes selected via `parameters.beamforming_input_mode`, but both share the same core state machine.

### 4.1 Common State Machine

Regardless of mode, the algorithm follows this cycle for each candidate configuration:

1. **Accumulate:** Receive `measurement_per_phase` metric values (default: 3) from the target RX, summing them in `metric_accumulator`.
2. **Average:** After enough measurements, compute `metric = metric_accumulator / measurement_counter`.
3. **Compare:** If this average exceeds `best_metric`, record the current configuration as the new best.
4. **Advance:** Increment `current_idx` to move to the next candidate. Reset the accumulator and counter.
5. **Emit:** Return a `tx_command` dict containing the next candidate's `phase_map` and `amplitude_map` for the SystemController to use.

If fewer than `measurement_per_phase` measurements have arrived, `compute_tx_command()` returns `None` and the SystemController keeps using the previous configuration.

### 4.2 Theta Mode (`"theta"`)

Candidates are beam steering angles from `beam_angle_sweep_deg` (list of degrees). For each angle theta, the algorithm computes per-TX phases from array geometry:

- Inter-element phase step: `delta_phi = -2*pi * (d/lambda) * sin(theta)`
- Phase for TX at position `i` in `tx_array_order`: `phase[i] = i * delta_phi`
- All TX share the same amplitude (`tx_signal_amplitude`)

**One-shot behavior:** After sweeping all angles, the algorithm sets `finished = True` and permanently locks to the best angle. All subsequent calls to `compute_tx_command()` return the best configuration. The sweep does not repeat.

### 4.3 Fi Mode (`"fi"`)

Candidates are explicitly defined phase/amplitude maps from `phase_map_sweep_deg` and `amplitude_map_sweep`. Each entry is a dict mapping TX ID (string) to phase (degrees) or amplitude. This allows arbitrary per-TX configurations that don't need to follow array geometry.

**Infinite cycling:** After reaching the last candidate, `current_idx` wraps back to 0 and the sweep restarts. The algorithm never sets `finished = True`. It continuously cycles through configurations, updating `best_metric` along the way.

---

## 5. MQTT Message Protocol

All messages are published to the single topic `signaltrack/bus` as JSON with this envelope:

```json
{
  "src": "system" | "tx" | "rx",
  "id": <int>,
  "cmd": "<COMMAND>",
  "payload": { ... },
  "timestamp": <float>
}
```

Every process subscribes to the same topic and receives all messages. Each controller filters by `cmd` (and sometimes `src`/`id`) in its `on_message` handler.

### 5.1 Command Reference

| Command | Direction | Payload | Purpose |
|---|---|---|---|
| `REGISTER` | TX/RX -> System | `{serial}` | Node announces itself with USRP serial number |
| `READY` | TX/RX -> System | `{}` | Hardware initialized, PPS synchronized (TX) |
| `SYNC_CLOCKS` | System -> all | `{}` | Arm USRP clock reset on next PPS edge |
| `START` | System -> all | `{}` | Begin accepting pulse commands |
| `STOP` | System -> all | `{}` | Cease operations |
| `TX_PULSE` | System -> TX | see below | Schedule a single TX burst at hardware time |
| `RX_PULSE` | System -> RX | `{target_time}` | Open a receive window around target time |
| `TX_ACTIVE` | TX -> bus (broadcast) | see below | Confirmation that burst was scheduled |
| `METRIC` | RX -> System | see below | Power measurement result for one pulse |

**Unused / vestigial commands** (handler exists but no code path sends them in current flow):

| Command | Notes |
|---|---|
| `TX_CMD` | Legacy phase/amplitude update without time scheduling. Superseded by `TX_PULSE` which carries both timing and configuration. Handler still present in TXController. |
| `PULSE_RESULT` | SystemController has a handler that logs it, but no controller sends this message. |

### 5.2 Key Payload Details

**TX_PULSE payload:**
```json
{
  "target_time": 10.0,
  "phase_map":     {"0": 0.0, "1": 3.14, "2": 0.0, "3": 3.14},
  "amplitude_map": {"0": 0.7, "1": 0.7,  "2": 0.7, "3": 0.7}
}
```
Keys in `phase_map` and `amplitude_map` are TX IDs as strings. Phases are in radians. Each TX extracts its own value by its ID.

**TX_ACTIVE payload:**
```json
{
  "n_samples": 32768,
  "target_time": 10.0,
  "phase": 3.14,
  "phase_deg": 180.0,
  "amplitude": 0.7
}
```
Published after a TX schedules its burst. Informational only — no process depends on it for control flow.

**METRIC payload:**
```json
{
  "value": -42.5,
  "avg_power_db": -42.5,
  "max_power_db": -38.1,
  "avg_power_lin": 5.6e-05,
  "max_power_lin": 1.5e-04,
  "samples_used": 1000,
  "target_time": 10.0,
  "detected_time": 10.000312,
  "offset_ms": 0.312
}
```
`value` is an alias for `avg_power_db` (kept for backward compatibility). `detected_time` is the USRP-clock timestamp of the peak power sample. `offset_ms` is `(detected_time - target_time) * 1000`.

---

## 6. Signal Generation and Reception

### 6.1 TX Signal Generation

Each TXController generates a complex exponential (single-tone) IQ signal:

```
s[n] = amplitude * exp(j * (2*pi * f0 * n / fs + phase))
```

Where:
- `f0` = tone offset frequency (per-TX configurable, default 0 Hz = carrier-only)
- `fs` = 500 kS/s sample rate
- `phase` = beamforming phase assigned to this TX (radians)
- `amplitude` = beamforming amplitude (default 0.7)
- Packet size: 32768 samples = 65.536 ms pulse duration

The samples are sent to the USRP with a hardware time spec, ensuring all TX devices begin transmission at the same USRP clock instant.

### 6.2 RX Signal Reception

Each RXController issues a timed stream command:
- Start time: `target_time - 10 ms` (margin before expected pulse)
- Duration: 65 ms (matches TX pulse length)
- Total samples: `rx_samp_rate * 0.065 = 32500` samples

After reception, the controller:
1. Computes instantaneous power: `|s[n]|^2` for each sample
2. Finds the peak power sample index
3. Extracts a 2 ms window centered on the peak
4. Computes average and max power (linear and dB) within that window
5. Records `detected_time` = start_time + peak_index / sample_rate
6. Computes timing offset: `detected_time - target_time`
7. Saves raw IQ to CSV, power metrics to per-RX CSV
8. Sends METRIC message to system

---

## 7. Time Synchronization Model

### 7.1 Hardware Layer (CDA-2990)

The CDA-2990 Clock Distribution Accessory distributes:
- **10 MHz reference clock** to all TX USRPs (configurable for RX). Ensures all local oscillators and sample clocks are frequency-locked.
- **1 PPS (Pulse Per Second)** to all TX USRPs (configurable for RX). Provides a shared time epoch for absolute time alignment.

### 7.2 Software Layer (SYNC_CLOCKS)

On receiving SYNC_CLOCKS, each USRP executes `set_time_next_pps(TimeSpec(0.0))`. This arms the FPGA to latch its internal clock to zero on the next PPS rising edge. Since all devices receive the same PPS edge, their clocks align to within the propagation delay of the distribution network (typically < 1 ns for CDA-2990).

### 7.3 Virtual Time

The SystemController maintains a `virtual_time` counter (starts at 5.0, increments by 5.0 per cycle). This counter serves as the `target_time` for TX/RX pulse scheduling. It is independent of wall-clock time -- it represents offsets in the synchronized USRP hardware clock domain.

---

## 8. Data Outputs

All outputs are written to the `results/` directory.

| File | Producer | Content |
|---|---|---|
| `beamforming_power_sweep.csv` | SystemController | One row per completed measurement cycle. Contains: target_time, beamforming target RX power, average power across all RX, per-RX power breakdown, TX phase/amplitude configuration used, and next planned configuration. |
| `rx_power_rx{id}.csv` | RXController | Per-pulse power measurements: target_time, detected_time, offset, avg/max power (dB and linear) |
| `rx_iq_rx{id}.csv` | RXController | Raw IQ samples with timestamps (appended each pulse) |
| `tx_timing_tx{id}.csv` | TXController | Per-pulse timing: target_time, USRP time at command receipt, USRP time after send, margin |

---

## 9. TX Operating Modes

### 9.1 Normal System Mode (default)

TX waits for START, then responds to individual TX_PULSE commands. Each pulse is a single burst with hardware-scheduled start time. This is the mode used for beamforming sweeps.

### 9.2 Continuous Mode

Enabled via `tx_continuous_mode = True` in parameters. TX enters an infinite loop, continuously streaming IQ samples without time scheduling. Used for spectrum analyzer diagnostics and debugging. In this mode, TX_PULSE commands are ignored.

Can be force-started without waiting for a system START via `tx_force_start_continuous = True`.

---

## 10. Test Mode

Setting `test_mode = True` and `mqtt_broker = "localhost"` in `helpers/parameters.py` enables software-only operation without USRP hardware:

- USRP initialization is skipped entirely
- TX does not actually transmit (samples are generated but not sent)
- RX generates random noise IQ data instead of receiving from hardware
- PPS synchronization checks are skipped
- All MQTT communication and beamforming logic still executes normally

This allows testing the coordination protocol, message flow, and beamforming algorithm without physical hardware.

---

## 11. Offline Analysis Tools

| Script | Purpose |
|---|---|
| `analyze_sync.py` | Post-processing tool. Analyzes TX0 vs TX1 synchronization from saved `.npy` files. Uses bandpass filters (scipy) to separate TX signals by frequency offset, computes arrival time difference. Reports synchronization error statistics. |
| `plot_latest.py` | Plots the most recent `.npy` capture: instantaneous power vs time, with automatic peak detection. |
| `test_pps.py` | Hardware diagnostic. Connects to any USRP, sets time source to external (PPS IN), and monitors PPS pulses in real time. Reports alarm if PPS signal is absent for > 2.5 seconds. |

---

## 12. Configuration Reference

All runtime parameters are defined as instance attributes in `helpers/parameters.py` (class `Parameters`). There is no external config file -- changes require editing the source.

### Key parameter groups:

| Parameter | Default | Description |
|---|---|---|
| `test_mode` | `False` | Software-only mode (no USRP hardware) |
| `center_freq` | 868 MHz | RF center frequency |
| `tx_samp_rate` / `rx_samp_rate` | 500 kS/s | Sample rate |
| `tx_gain_db` | 40 dB | TX gain |
| `rx_gain_db` | 30 dB | RX gain |
| `tx_count` / `rx_count` | 4 / 3 | Number of TX/RX devices |
| `tx_usrp_serial_map` | 4 entries | Maps TX ID to USRP serial number |
| `rx_usrp_serial_map` | 3 entries | Maps RX ID to USRP serial number |
| `beamforming_input_mode` | `"fi"` | `"theta"` (angle sweep) or `"fi"` (manual phase maps) |
| `measurement_per_phase` | 3 | Pulses averaged per beamforming configuration |
| `beamforming_target_rx_id` | `"2"` | RX used for optimization metric |
| `iq_samples_per_packet` | 32768 | Samples per TX burst (65.5 ms at 500 kS/s) |
| `tx_signal_amplitude` | 0.7 | Default TX amplitude (0.0 - 1.0) |
| `tx_use_external_clock` | `True` | Use CDA-2990 10 MHz reference for TX |
| `tx_use_external_time_source` | `True` | Use CDA-2990 PPS for TX time sync |
| `rx_use_external_clock` | `False` | Use CDA-2990 10 MHz reference for RX |
| `rx_use_external_time_source` | `False` | Use CDA-2990 PPS for RX time sync |
| `tx_continuous_mode` | `False` | Continuous TX for spectrum analyzer use |
| `mqtt_broker` | `192.168.8.126` | MQTT broker address |

---

## 13. Constraints and Limitations

1. **Single-threaded MQTT callbacks:** All message handling (including RX signal processing and beamforming computation) runs in the paho-mqtt callback thread. Long processing in `on_message` blocks other message reception.

2. **No fault recovery:** If a TX or RX process crashes mid-cycle, the SystemController will wait indefinitely for the missing METRIC message. There is no timeout or node health monitoring.

3. **Fixed 5-second cycle:** The measurement interval is hardcoded in the SystemController's main loop. It is not adaptive and cannot be changed without code modification.

4. **No RX clock synchronization by default:** RX devices use internal clocks (`rx_use_external_clock = False`). This means RX devices are not frequency-locked to TX devices, which may introduce frequency offset in received signals. RX time windows have enough margin (65 ms) to compensate for clock drift.

5. **Configuration in source code:** All parameters are hardcoded in `parameters.py`. There is no external config file, CLI argument parsing for parameters, or environment variable support.

6. **Virtual time drift:** The SystemController's 5-second cycle is driven by wall-clock `time.time()`, not by the USRP hardware clock. Over long runs, the virtual_time counter may drift relative to actual USRP time if the host's wall clock and USRP clock diverge.

7. **Fi mode does not terminate:** Unlike theta mode (which sets `finished=True` after sweeping all angles), fi mode cycles through phase configurations indefinitely (wraps `current_idx` back to 0).
