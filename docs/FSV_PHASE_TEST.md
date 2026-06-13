# Test systemowy TX + FSV3000

Cel: uruchomic normalny przeplyw SignalTrack z jednym TX i analizatorem
Rohde & Schwarz FSV3000, bez RX. System wysyla `TX_PULSE`, TX nadaje impuls,
FSV mierzy IQ i odsyla `FSV_PHASE_METRIC` do `SystemController`.

## Procesy

Na komputerach/terminalach uruchamiamy:

```bash
python3 main.py system --config config.system_fsv_phase_test.yaml
python3 main.py tx 0 --config config.system_fsv_phase_test.yaml
python3 main.py fsv 0 --config config.system_fsv_phase_test.yaml
```

Broker MQTT musi dzialac przed startem procesow:

```bash
sudo systemctl start mosquitto
```

W configu `mqtt.broker` ma wskazywac maszyne z brokerem, np.:

```yaml
mqtt:
  broker: 192.168.8.143
```

## Co zostalo dodane w kodzie

Tryb FSV-as-metric wlacza sie przez:

```yaml
fsv:
  enabled: true
  required_for_beamforming: true
```

W tym trybie:

- system wymaga gotowego komponentu `fsv`,
- nie wymaga zadnego RX w `nodes.rx`,
- proba konczy sie po `TX_DONE` oraz `FSV_PHASE_METRIC`,
- metryka z FSV jest zapisywana w `beamforming_trials.csv`,
- algorytm beamformingu moze przejsc do nastepnego kandydata na podstawie FSV.

## Config testowy

Plik:

```bash
config.system_fsv_phase_test.yaml
```

Domyslnie FSV jest laczony przez surowy SCPI socket:

```yaml
fsv:
  ip: 192.168.8.20
  socket_port: 5025
```

Kod sklada z tego resource:

```text
TCPIP::192.168.8.20::5025::SOCKET
```

Dla takiego resource kod uzywa wlasnego klienta TCP i nie wymaga R&S VISA,
`rsvisa` ani `RsInstrument`.

Konfiguracja uzywa jednego TX:

```yaml
nodes:
  tx:
    "0":
      serial: "3273ABF"
      external_clock: false
      external_time_source: true
  rx: {}
```

oraz recznego sweepu faz:

```yaml
beamforming:
  mode: manual_sweep
  tx_array_order: ["0"]
  repeats_per_angle: 1
  phase_map_sweep_deg:
    - {"0": 0}
    - {"0": 90}
    - {"0": 180}
    - {"0": 270}
```

TX generuje ton z offsetem 10 kHz:

```yaml
rf:
  tx_tone_offset_hz: 10000
  tx_tone_offsets:
    "0": 10000
```

FSV demoduluje IQ po tym samym offsetcie i raportuje faze.

## Timing FSV

`SystemController` dodaje do `TX_PULSE` pole:

```json
"target_pc_unix": 1234567890.123
```

FSV uzywa tego czasu, zeby uzbroic akwizycje przed impulsem TX:

```yaml
fsv:
  trigger_source: IMM
  pre_capture_s: 0.15
```

To jest wazne, bo bez tego FSV moglby zaczac akwizycje zbyt wczesnie albo zbyt
pozno wzgledem zaplanowanego impulsu. `IMM` jest tu celowe: analizator nie czeka
na trigger od mocy, tylko zbiera okno IQ w znanym czasie.

## Interpretacja

Wyniki sa w:

```bash
results/beamforming_trials.csv
results/fsv3000_phase_fsv0.csv
```

Nie oczekuj, ze faza absolutna z FSV bedzie rowna komendzie TX. Tor RF dodaje
staly offset:

```text
phase_measured = phase_command + rf_path_offset + drift
```

Patrz na zmiany wzgledne. Przy komendach:

```text
0, 90, 180, 270
```

zmierzona faza powinna robic podobne skoki wzgledem pierwszego pomiaru:

```text
0, +90, +180, -90
```

W `fsv3000_phase_fsv0.csv` podstawowa kolumna to `analyzer_phase_deg`.
W `beamforming_trials.csv` pelny payload FSV jest w kolumnie `fsv_metrics`.

## Najczestsze problemy

Jesli system czeka i nie startuje:

- sprawdz, czy dzialaja trzy procesy: `system`, `tx 0`, `fsv 0`,
- sprawdz, czy wszystkie uzywaja tego samego `mqtt.broker`,
- sprawdz, czy `fsv.enabled: true`.

Jesli FSV nie odsyla metryk:

- sprawdz IP albo `resource` analizatora,
- ustaw `trigger_source: IMM` na start; `IFP` moze timeoutowac, jesli trigger
  IF power nie lapie impulsu,
- jesli koniecznie uzywasz `IFP`, sprawdz `trigger_level_dbm`,
- sprawdz, czy `FSV3000Controller` loguje odebranie `TX_PULSE`.

Jesli TX nie startuje przez PPS:

- `external_time_source: true` wymaga podanego PPS,
- dla testu bez PPS mozna ustawic `external_time_source: false`, ale wtedy
  planowanie czasu PC/USRP moze byc mniej dokladne.

Jesli sygnal jest za mocny albo za slaby:

- zacznij od `tx_gain_db: 20`,
- uzyj tlumika RF,
- dopasuj `fsv.ref_level_dbm`,
- obserwuj `signal_power_db` i `phasor_abs` w metryce FSV.
