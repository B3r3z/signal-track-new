# Tryby pracy systemu

Ten dokument opisuje tryby pracy SignalTrack widoczne w aktualnym kodzie.
Najwazniejsza opcja znajduje sie w `config.yaml`:

```yaml
beamforming:
  mode: optimize
```

Wartosci obslugiwane przez `algorithms/beamforming.py`:

- `optimize`
- `scan`
- `manual_sweep`
- `theta` jako alias legacy dla `optimize`
- `fi` jako alias legacy dla `manual_sweep`

## Wspolny przebieg pomiaru

Niezaleznie od trybu beamformingu system dziala w cyklu:

1. `SystemController` wybiera konfiguracje TX: `phase_map` i `amplitude_map`.
2. System wysyla do RX polecenie przygotowania odbioru (`RX_CAPTURE`).
3. System wysyla do TX polecenie impulsu (`TX_PULSE`) z tym samym `trial_id`
   i `target_time`.
4. Kazdy TX nadaje swoj impuls z faza i amplituda przypisana do jego ID.
5. RX mierza moc odebranego sygnalu i odsyla metryki.
6. `SystemController` zapisuje wynik do CSV.
7. Algorytm beamformingu decyduje, jaka konfiguracja TX bedzie uzyta dalej.

Metryka optymalizacji pochodzi z odbiornika wskazanego przez:

```yaml
targets:
  tc1:
    rx_id: "1"

beamforming:
  target: tc1
```

Czyli `target: tc1` oznacza: optymalizujemy pod RX o ID `"1"`.

## `optimize`

Tryb `optimize` sluzy do znalezienia najlepszej konfiguracji kierunkowej dla
wybranego targetu.

Konfiguracja:

```yaml
beamforming:
  mode: optimize
  target: tc1
  geometry: linear
  tx_array_order: ["0", "1", "2", "3"]
  tx_antenna_spacing_lambda: 0.5
  scan_angles_deg: [-60, -45, -30, -15, 0, 15, 30, 45, 60]
  repeats_per_angle: 3
  tx_signal_amplitude: 0.7
```

Dzialanie:

- kandydatami sa katy z `scan_angles_deg`,
- dla kazdego kata system liczy fazy TX z geometrii liniowej,
- kazdy kat jest mierzony `repeats_per_angle` razy,
- metryki sa usredniane,
- system zapamietuje najlepszy kat,
- po przejsciu przez cala liste ustawia `finished: true` i wraca do najlepszej
  znalezionej konfiguracji.

Wzor na krok fazowy:

```text
phase_step = -2 * pi * d/lambda * sin(theta)
```

Fazy w komunikatach runtime sa w radianach. Katy w configu sa w stopniach.

Ten tryb ma sens, gdy:

- TX tworza w przyblizeniu liniowy szyk antenowy,
- `tx_array_order` odpowiada fizycznej kolejnosci anten,
- znany jest odstep anten w dlugosciach fali (`tx_antenna_spacing_lambda`).

## `scan`

Tryb `scan` uzywa tej samej listy katow i tej samej geometrii co `optimize`,
ale nie konczy sweepu.

Konfiguracja:

```yaml
beamforming:
  mode: scan
  target: tc1
  geometry: linear
  tx_array_order: ["0", "1", "2", "3"]
  tx_antenna_spacing_lambda: 0.5
  scan_angles_deg: [-60, -30, 0, 30, 60]
  repeats_per_angle: 3
  tx_signal_amplitude: 0.7
```

Dzialanie:

- system przechodzi po katach z `scan_angles_deg`,
- po ostatnim kacie wraca do pierwszego,
- `finished` pozostaje `false`,
- najlepszy wynik nadal jest zapamietywany informacyjnie, ale tryb nie blokuje
  sie na najlepszej konfiguracji.

Ten tryb jest dobry do testow, strojenia i obserwacji zachowania ukladu w czasie.

## `manual_sweep`

Tryb `manual_sweep` nie liczy faz z kata. Uzywa recznie podanych map faz
i amplitud.

Konfiguracja:

```yaml
beamforming:
  mode: manual_sweep
  target: tc1
  repeats_per_angle: 3
  phase_map_sweep_deg:
    - {"0": 0, "1": 0, "2": 0, "3": 0}
    - {"0": 0, "1": 180, "2": 0, "3": 180}
  amplitude_map_sweep:
    - {"0": 0.7, "1": 0.7, "2": 0.7, "3": 0.7}
    - {"0": 0.7, "1": 0.7, "2": 0.7, "3": 0.7}
```

Dzialanie:

- kandydatami sa kolejne wpisy z `phase_map_sweep_deg`,
- fazy w configu sa podawane w stopniach,
- kod konwertuje je do radianow przed wyslaniem do TX,
- `amplitude_map_sweep` musi miec tyle samo wpisow co `phase_map_sweep_deg`,
- po ostatniej konfiguracji system wraca do pierwszej,
- `finished` pozostaje `false`.

Ten tryb jest dobry, gdy:

- chcemy sprawdzic konkretne reczne ustawienia faz,
- fizyczny uklad anten nie pasuje do prostego modelu liniowego,
- robimy diagnostyke synchronizacji albo porownanie kilku znanych stanow.

Alias legacy:

```yaml
beamforming:
  mode: fi
```

jest traktowany tak samo jak:

```yaml
beamforming:
  mode: manual_sweep
```

## `theta`

`theta` to stara nazwa trybu katowego. W aktualnym kodzie:

```yaml
beamforming:
  mode: theta
```

jest traktowane tak samo jak:

```yaml
beamforming:
  mode: optimize
```

Nowe konfiguracje powinny uzywac `optimize`, bo ta nazwa lepiej opisuje
zachowanie: system skanuje katy i na koncu wybiera najlepszy.

## Kalibracja przed beamformingiem

Kalibracja nie jest osobnym `beamforming.mode`, ale jest dodatkowym etapem
przed normalnym sweepem.

Konfiguracja:

```yaml
calibration:
  enabled: true
  continue_on_failure: false
```

Gdy kalibracja jest wlaczona, `SystemController` najpierw tworzy kolejke prob,
w ktorych aktywny jest pojedynczy TX, a pozostale TX maja amplitude `0.0`.
Dopiero po przejsciu tej kolejki zaczyna sie normalny tryb `optimize`, `scan`
albo `manual_sweep`.

## Tryb testowy

Tryb testowy jest ustawiany poza sekcja `beamforming`:

```yaml
runtime:
  test_mode: true
```

Sluzy do uruchamiania logiki bez pelnego hardware. Kontrolery nadal komunikuja
sie przez MQTT, ale wybrane operacje RF/synchronizacji moga byc pominiete przez
kontrolery.

## Tryb ciagly TX

W kodzie istnieje tez diagnostyczny tryb ciaglego nadawania TX:

```python
self.tx_continuous_mode = True
```

To nie jest obecnie typowy tryb ustawiany przez `config.yaml`. Jest to tryb
serwisowy do diagnostyki nadajnika i analizatora widma, w ktorym TX nadaje
ciagle zamiast czekac na zaplanowane impulsy systemowe.

## Ktory tryb wybrac?

Najczestszy wybor:

- `optimize` - normalny eksperyment beamformingu, szukanie najlepszego kata
  dla jednego targetu.
- `scan` - ciagly sweep katow do obserwacji i diagnostyki.
- `manual_sweep` - reczne konfiguracje faz, gdy chcemy sprawdzic konkretne
  stany albo gdy geometria liniowa nie pasuje do stanowiska.

W typowym uruchomieniu na wielu komputerach wszystkie procesy powinny uzywac
tego samego `config.yaml`, a `mqtt.broker` powinien wskazywac jeden wspolny
broker MQTT widoczny dla wszystkich maszyn.
