import time
import uhd
import sys

def test_pps_connection():
    print("Inicjowanie USRP (poszukiwanie podłączonego urządzenia)...")
    try:
        usrp = uhd.usrp.MultiUSRP("")
    except Exception as e:
        print(f"Błąd podczas połączenia z USRP: {e}")
        return

    print("Ustawianie źródła zegara (clock) na 'internal'...")
    try:
        usrp.set_clock_source("internal")
    except Exception as e:
        print(f"Błąd źródła zegara: {e}")

    print("Ustawianie źródła czasu na 'external' (PPS IN)...")
    try:
        usrp.set_time_source("external")
    except Exception as e:
        print(f"Błąd źródła czasu: {e}")
    
    # Przerwa na stabilizację sygnału
    time.sleep(1.0)

    # Ustawiamy natychmiastowy czas na 0.0 w zegarze USRP, by zacząć test od znanej wartości
    usrp.set_time_now(uhd.types.TimeSpec(0.0))
    # Ponownie nakazujemy by przy pierwszym zewnętrznym impulsie PPS zegar ustawił równe 1.0
    usrp.set_time_next_pps(uhd.types.TimeSpec(1.0))
    
    print("\n" + "="*60)
    print("  NASŁUCHIWANIE NA SYNCHRONIZACJĘ PPS W CZASIE RZECZYWISTYM  ")
    print("  (wyjście możesz zamknąć skrótem Ctrl + C)")
    print("="*60 + "\n")
    
    try:
        # get_time_last_pps() zwraca dokładny czas zegarowy USRP, w którym uderzyło sprzętowe zbocze PPS
        last_pps_time = usrp.get_time_last_pps().get_real_secs()
        last_print_time = time.time()
        
        while True:
            # Odpytujemy układ FPGA o uwieczniony sprzętowy czas z ostatniego zarejestrowanego zbocza PPS
            current_pps_time = usrp.get_time_last_pps().get_real_secs()
            
            # Jeżeli ten czas w sprzęcie się zmienił, to znaczy że nadeszło w pełni poprawne zbocze PPS!
            if current_pps_time != last_pps_time:
                print(f"[+] {time.strftime('%H:%M:%S')} | Otrzymano impuls PPS! "
                      f"Wewnętrzny czas (USRP Time): {current_pps_time:8.3f} s")
                last_pps_time = current_pps_time
                last_print_time = time.time()  # Aktualizujemy czas wypisania dla logiki alarmu
            else:
                # Skoro PPS musi nadejść co 1 sekundę, a mija np. ponad 2.5 sekundy, to znaczy 
                # że przewód został wypięty lub moduł GPS stracił na długo fixa.
                if time.time() - last_print_time > 2.5:
                    print(f"[-] {time.strftime('%H:%M:%S')} | UWAGA: Brak sygnału! (ostatnio odnotowano go ponad 2 sekundy temu)")
                    # Resetujemy czas logowania, aby wyświetlać błąd co 2.5 sekundy dopóki kable są wyjęte
                    last_print_time = time.time()
            
            # Odpytujemy sprzęt 20 razy na sekundę, co zapewnia natychmiastową reakcję w terminalu
            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n\nTest zakończony przez użytkownika (Ctrl+C).")
    except RuntimeError as e:
        print(f"\nWystąpił błąd podczas oczekiwania na impuls: {e}")

if __name__ == "__main__":
    test_pps_connection()
