# SDD: Architektura systemu beamformingu SDR

## 1. Cel dokumentu

Ten dokument opisuje, jak system powinien działać docelowo, żeby realnie wykonywać beamforming z użyciem wielu USRP B210.

Nie jest to opis obecnego kodu jeden do jednego. To jest opis oczekiwanej funkcjonalności i docelowej architektury, do której kod powinien zostać uporządkowany.

Główna teza: obecna architektura miesza sterowanie eksperymentem, synchronizację czasu, pomiar RF, logikę beamformingu i diagnostykę FSV w jednym przepływie. Dla prostych testów może to działać przypadkowo, ale dla stabilnego beamformingu potrzebny jest bardziej jednoznaczny model pracy.

## 2. Cel systemu

System ma sterować układem SDR, w którym kilka nadajników TX emituje ten sam sygnał z kontrolowaną różnicą fazy, a jeden lub więcej odbiorników RX mierzy efekt sumowania fal w przestrzeni.

Docelowo system powinien umożliwiać:

- jednoczesne nadawanie impulsu przez kilka TX,
- ustawianie osobnej fazy i amplitudy dla każdego TX,
- pomiar mocy odebranej przez RX dla danej konfiguracji faz,
- przeszukiwanie wielu konfiguracji faz,
- wybór konfiguracji dającej największą moc na wybranym RX,
- zapis powtarzalnych wyników do CSV,
- diagnostykę synchronizacji i fazy z użyciem FSV, jeśli jest dostępny.

## 3. Założenie fizyczne

Beamforming działa tylko wtedy, gdy sygnały z nadajników mają stabilną relację fazową.

To oznacza, że:

- wszystkie USRP TX muszą mieć wspólny zegar odniesienia `10 MHz`,
- wszystkie USRP TX i RX muszą mieć wspólny impuls czasu `PPS`,
- wszystkie TX muszą nadawać w tym samym czasie sprzętowym,
- każdy TX musi generować ten sam sygnał bazowy, ale z własną fazą,
- faza zadana w kodzie musi odpowiadać fazie sygnału wygenerowanego w sprzęcie.

Jeśli każdy TX ma swój niezależny czas albo niezależnie dryfującą fazę, to wartości typu `TX1 = 90 deg` nie mają stabilnego znaczenia fizycznego. Wtedy system nie robi beamformingu, tylko wysyła kilka niespójnych sygnałów.

## 4. Model działania eksperymentu

Pojedynczy pomiar powinien wyglądać tak:

1. `SystemController` wybiera konfigurację faz i amplitud.
2. `SystemController` wybiera jeden wspólny czas sprzętowy `target_time`.
3. `SystemController` wysyła dokładnie jeden rozkaz `TX_PULSE`.
4. `SystemController` wysyła dokładnie jeden rozkaz `RX_CAPTURE`.
5. Każdy TX bierze swoją fazę z `phase_map`.
6. Każdy TX nadaje impuls dokładnie w `target_time`.
7. RX odbiera próbki w zaplanowanym oknie wokół `target_time`.
8. RX liczy metrykę mocy impulsu.
9. RX odsyła wynik do systemu.
10. `SystemController` zapisuje wynik i wybiera następną konfigurację.

Ważne: jeden zaplanowany impuls musi odpowiadać jednemu rekordowi eksperymentu.

Nie powinno być sytuacji, w której dla jednego `target_time` system wysyła dwa `TX_PULSE`, dwa `RX_CAPTURE` albo miesza wyniki z różnych prób.

## 5. Podstawowe pojęcia

### 5.1. `target_time`

`target_time` powinien oznaczać czas sprzętowy USRP, a nie luźny czas komputera PC.

Poprawne znaczenie:

```text
target_time = chwila w zegarze USRP, w której TX ma rozpocząć nadawanie
```

Niepoprawne znaczenie:

```text
target_time = czas policzony z time.time() i założenie, że USRP jest podobnie ustawiony
```

PC może służyć do planowania i logowania, ale nie powinien być źródłem prawdy o czasie RF.

### 5.2. `phase_map`

`phase_map` to mapa faz dla nadajników.

Przykład:

```json
{
  "0": 0.0,
  "1": 1.57079632679,
  "2": 3.14159265359,
  "3": 4.71238898038
}
```

Wartości powinny być przechowywane w radianach w komunikatach runtime. W plikach konfiguracyjnych można podawać stopnie, ale konwersja powinna być jednoznaczna i wykonana raz.

### 5.3. `amplitude_map`

`amplitude_map` określa amplitudę każdego TX.

Przykład:

```json
{
  "0": 0.7,
  "1": 0.7,
  "2": 0.7,
  "3": 0.7
}
```

Amplituda `0.0` oznacza, że dany TX jest wyciszony.

### 5.4. Metryka beamformingu

Metryka beamformingu powinna reprezentować moc odebranego impulsu.

Do decyzji algorytmu najlepiej używać skali liniowej:

```text
power_linear = mean(abs(iq)^2)
```

Do logów i CSV można równolegle zapisywać dB:

```text
power_db = 10 * log10(power_linear)
```

Nie należy uśredniać wielu pomiarów bezpośrednio w dB, ponieważ dB jest skalą logarytmiczną.

## 6. Proponowana architektura

Docelowo system powinien mieć wyraźnie oddzielone warstwy:

### 6.1. Warstwa konfiguracji

Odpowiada za:

- liczbę TX i RX,
- seriale USRP,
- częstotliwość pracy,
- sample rate,
- gain,
- długość impulsu,
- tryb beamformingu,
- konfigurację sweepu,
- ustawienia FSV.

Plik przykładowy:

```text
helpers/parameters.py
```

W tej warstwie nie powinno być logiki eksperymentu. To ma być konfiguracja, nie sterownik.

### 6.2. Warstwa transportu wiadomości

Odpowiada wyłącznie za MQTT:

- połączenie,
- subskrypcję,
- publikację,
- parsowanie wiadomości,
- kolejkę wiadomości.

Ważne: callback MQTT nie powinien wykonywać ciężkich operacji RF. Powinien tylko odkładać wiadomości do kolejki.

Powód: odbiór próbek z USRP albo akwizycja FSV może trwać długo. Jeśli takie operacje wykonują się w callbacku MQTT, komponent przestaje sprawnie odbierać kolejne komunikaty.

### 6.3. Warstwa sterowania eksperymentem

Odpowiada za globalny przebieg pomiaru.

Powinna wiedzieć:

- które komponenty są gotowe,
- jaki jest aktualny numer próby,
- jaki jest aktualny `target_time`,
- jaka konfiguracja faz jest testowana,
- których wyników jeszcze brakuje,
- kiedy można przejść do następnego pomiaru.

To jest rola `SystemController`.

`SystemController` nie powinien sam liczyć próbek IQ ani bezpośrednio sterować sprzętem RF. Jego rolą jest koordynacja.

### 6.4. Warstwa TX

Każdy TX powinien:

- zarejestrować się w systemie,
- zsynchronizować czas z PPS,
- czekać na `TX_PULSE`,
- wziąć swoją fazę i amplitudę z mapy,
- wygenerować próbki,
- wysłać próbki do USRP z `time_spec = target_time`,
- odesłać `TX_ACTIVE` lub `TX_DONE`.

TX nie powinien sam decydować, jaka faza jest dobra. TX jest wykonawcą polecenia.

### 6.5. Warstwa RX

Każdy RX powinien:

- zarejestrować się w systemie,
- zsynchronizować czas z PPS,
- czekać na `RX_CAPTURE`,
- odebrać próbki w zaplanowanym oknie,
- policzyć metrykę impulsu,
- odesłać `RX_METRIC`.

RX nie powinien decydować o następnej konfiguracji beamformingu.

### 6.6. Warstwa algorytmu beamformingu

Algorytm powinien być możliwie czysty i niezależny od MQTT oraz USRP.

Powinien przyjmować:

```text
trial_id
phase_map
amplitude_map
rx_metric
```

Powinien zwracać:

```text
next_phase_map
next_amplitude_map
status
```

Dzięki temu można go testować bez sprzętu.

### 6.7. Warstwa diagnostyki FSV

FSV powinien być komponentem opcjonalnym.

Może służyć do:

- pomiaru fazy sygnału,
- potwierdzenia obecności impulsu,
- diagnostyki różnic między TX,
- walidacji synchronizacji.

FSV nie powinien blokować podstawowego beamformingu, chyba że eksperyment jest uruchomiony w trybie, który wyraźnie tego wymaga.

Jeśli FSV ma rozdzielać fazy poszczególnych TX, system musi zapewnić możliwość ich rozróżnienia. Przykładowe metody:

- różne małe offsety częstotliwości dla TX,
- pomiar jednego TX naraz,
- sekwencyjna kalibracja przed właściwym beamformingiem.

Jeśli wszystkie TX nadają dokładnie ten sam ton na tym samym offsetcie, FSV widzi sumę wektorową, a nie osobne fazy każdego nadajnika.

## 7. Proponowane komunikaty MQTT

### 7.1. `REGISTER`

Komponent informuje system, że istnieje.

Przykład:

```json
{
  "src": "tx",
  "id": "0",
  "cmd": "REGISTER",
  "payload": {
    "serial": "3273AF9"
  }
}
```

### 7.2. `READY`

Komponent informuje system, że jest gotowy do pracy.

Przykład:

```json
{
  "src": "rx",
  "id": "0",
  "cmd": "READY",
  "payload": {}
}
```

### 7.3. `SYNC_CLOCKS`

System każe komponentom uzbroić zerowanie czasu na następnym PPS.

Przykład:

```json
{
  "src": "system",
  "id": "0",
  "cmd": "SYNC_CLOCKS",
  "payload": {
    "time_at_next_pps": 0.0
  }
}
```

### 7.4. `TX_PULSE`

System zleca nadajnikom impuls w konkretnym czasie sprzętowym.

Przykład:

```json
{
  "src": "system",
  "id": "0",
  "cmd": "TX_PULSE",
  "payload": {
    "trial_id": 15,
    "target_time": 12.500000,
    "phase_map": {
      "0": 0.0,
      "1": 1.57079632679,
      "2": 3.14159265359,
      "3": 4.71238898038
    },
    "amplitude_map": {
      "0": 0.7,
      "1": 0.7,
      "2": 0.7,
      "3": 0.7
    }
  }
}
```

### 7.5. `RX_CAPTURE`

System zleca odbiornikom akwizycję wokół danego czasu.

Przykład:

```json
{
  "src": "system",
  "id": "0",
  "cmd": "RX_CAPTURE",
  "payload": {
    "trial_id": 15,
    "target_time": 12.500000,
    "pre_trigger_s": 0.010,
    "capture_time_s": 0.100
  }
}
```

### 7.6. `TX_DONE`

TX raportuje, że przyjął i wykonał zlecenie.

Przykład:

```json
{
  "src": "tx",
  "id": "0",
  "cmd": "TX_DONE",
  "payload": {
    "trial_id": 15,
    "target_time": 12.500000,
    "phase_rad": 0.0,
    "amplitude": 0.7,
    "samples_requested": 32768,
    "samples_sent": 32768,
    "late": false
  }
}
```

### 7.7. `RX_METRIC`

RX raportuje metrykę odebranego impulsu.

Przykład:

```json
{
  "src": "rx",
  "id": "0",
  "cmd": "RX_METRIC",
  "payload": {
    "trial_id": 15,
    "target_time": 12.500000,
    "detected_time": 12.500214,
    "offset_ms": 0.214,
    "power_linear": 0.000031,
    "power_db": -45.08,
    "snr_db": 18.4,
    "samples_used": 32768
  }
}
```

## 8. Stan eksperymentu

`SystemController` powinien prowadzić jawny stan eksperymentu.

Przykładowe stany:

```text
WAITING_FOR_COMPONENTS
SYNCING_CLOCKS
READY_TO_MEASURE
ARMING_TRIAL
WAITING_FOR_RESULTS
PROCESSING_RESULTS
FINISHED
ERROR
```

Każdy pomiar powinien mieć własny `trial_id`.

Wyniki powinny być grupowane po `trial_id`, a nie tylko po `target_time`. `target_time` może być podobny albo zaokrąglony, ale `trial_id` jest jednoznacznym identyfikatorem próby.

## 9. Jak powinien działać sweep faz

Najprostszy tryb beamformingu to sweep ręczny.

Przykład:

```text
trial 1: TX0=0, TX1=0,   TX2=0,   TX3=0
trial 2: TX0=0, TX1=45,  TX2=90,  TX3=135
trial 3: TX0=0, TX1=90,  TX2=180, TX3=270
trial 4: TX0=0, TX1=135, TX2=270, TX3=45
```

Dla każdej konfiguracji system wykonuje kilka powtórzeń.

Potem:

1. RX liczy moc impulsu.
2. System uśrednia moc w skali liniowej.
3. System wybiera konfigurację z największą mocą na wybranym RX.

To daje prosty, eksperymentalny beamforming bez zakładania idealnego modelu propagacji.

## 10. Jak powinien działać tryb kątowy

W trybie kątowym użytkownik podaje geometrię szyku oraz listę kątów do sprawdzenia.

System liczy krok fazy:

```text
phase_step = -2 * pi * d/lambda * sin(theta)
```

Dla czterech TX:

```text
TX0 = 0 * phase_step
TX1 = 1 * phase_step
TX2 = 2 * phase_step
TX3 = 3 * phase_step
```

Ten tryb ma sens tylko wtedy, gdy kolejność `tx_array_order` odpowiada fizycznemu położeniu anten.

Jeśli fizyczny układ anten jest inny niż kolejność w konfiguracji, wiązka pójdzie w złą stronę.

## 11. Kalibracja

Przed właściwym beamformingiem system powinien mieć tryb kalibracji.

Minimalna kalibracja:

- uruchomić pojedynczo TX0, TX1, TX2, TX3,
- zmierzyć, czy każdy TX nadaje,
- sprawdzić poziom mocy,
- sprawdzić, czy RX widzi impuls w spodziewanym czasie,
- opcjonalnie zmierzyć fazę względem referencji na FSV.

Bez kalibracji można pomylić:

- błąd fazy,
- różnicę długości kabli,
- zły serial USRP,
- złą antenę,
- zły gain,
- zły offset czasu,
- fizyczną zamianę kolejności anten.

## 12. CSV i logowanie

Wyniki powinny być zapisywane tak, żeby dało się odtworzyć każdy pomiar.

Każdy wiersz CSV powinien zawierać:

- `trial_id`,
- `target_time`,
- `phase_map`,
- `amplitude_map`,
- metryki RX,
- status TX,
- informację, czy TX był spóźniony,
- informację, czy RX znalazł impuls,
- użyty tryb beamformingu,
- numer konfiguracji w sweepie.

CSV nie powinien mieszać wielu prób w jednym wierszu bez jednoznacznego identyfikatora.

## 13. Minimalna ścieżka przebudowy

Proponowana kolejność prac:

1. Przywrócić kolejkę wiadomości MQTT, żeby callback nie wykonywał ciężkich operacji.
2. Usunąć podwójne wysyłanie `TX_PULSE` i `RX_PULSE`.
3. Wprowadzić `trial_id` jako główny identyfikator pomiaru.
4. Rozdzielić `RX_CAPTURE` od `TX_PULSE`.
5. Uporządkować znaczenie `target_time` jako czasu sprzętowego USRP.
6. Naprawić metrykę beamformingu, żeby decyzje były liczone w skali liniowej.
7. Ustalić jeden format faz: konfiguracja może być w stopniach, runtime w radianach.
8. Dodać prosty tryb kalibracji TX po kolei.
9. Dopiero potem dopinać FSV jako diagnostykę.

## 14. Kryteria poprawnego działania

System można uznać za gotowy do podstawowego beamformingu, jeśli:

- wszystkie TX raportują wspólną synchronizację PPS,
- każdy `trial_id` ma dokładnie jeden `TX_PULSE`,
- każdy `trial_id` ma dokładnie jeden zestaw wyników RX,
- RX widzi impuls blisko `target_time`,
- powtarzanie tej samej konfiguracji daje podobną moc,
- zmiana faz powoduje mierzalną zmianę mocy na RX,
- najlepsza konfiguracja jest powtarzalna w kilku cyklach sweepu.

## 15. Najważniejszy wniosek architektoniczny

Kod powinien zostać przebudowany wokół pojęcia pojedynczej próby pomiarowej:

```text
trial_id + target_time + phase_map + RX metrics
```

To jest centrum całego systemu.

Jeśli każdy komponent konsekwentnie pracuje na tym samym `trial_id`, wtedy można bezpiecznie składać wyniki, diagnozować błędy i rozwijać beamforming.

Jeśli system dalej będzie opierał się tylko na luźnych komunikatach i zaokrąglonym `target_time`, to przy większej liczbie TX, RX i FSV będzie coraz trudniej odróżnić realny efekt radiowy od błędu koordynacji programu.

