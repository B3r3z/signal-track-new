import os
import glob
import numpy as np
import matplotlib.pyplot as plt
import scipy.signal

def plot_results(results_dir="results"):
    # Znajdź wszystkie pliki .npy w folderze
    search_pattern = os.path.join(results_dir, "*.npy")
    files = glob.glob(search_pattern)
    
    if not files:
        print(f"Brak plików do narysowania w folderze: {results_dir}")
        return
        
    # Uporządkuj pliki wg czasu modyfikacji (od najnowszego)
    files.sort(key=os.path.getmtime, reverse=True)
    
    # Bierzemy najnowszy, świeży plik testu (lub zmień na "files[1]" itd.)
    target_file = files[0]
    print(f"Rysuję najnowszy zrzut wideo fali: {target_file}")
    
    # 1. Załadowanie binarnej klatki ze stacji
    raw_iq = np.load(target_file)
    
    # 2. Obliczenie Prawdziwej Mocy z części urojonej i rzeczywistej
    power = np.abs(raw_iq)**2 
    
    # 3. Zbudowanie idealnej Osi Czasu Odbiornika na start na 0 ms, ze stałym rate:
    # Okno dla odbiornika posiada 500e3 sampe rate -> co 2 mikrosekundy nowa próbka.
    samp_rate = 500e3
    t_ms = np.arange(len(power)) / samp_rate * 1000.0
    
    # 4. Magia Matematyczna - Poszukiwawanie Wzgórz by nakreślić dowody pingu
    # 'distance=1000' sprawia, że ignoruje on sąsiednie pagórki w obrębie tego samego uderzenia
    peaks, _ = scipy.signal.find_peaks(power, height=np.max(power)*0.2, distance=1000)
    
    # RYSOWANIE
    plt.figure(figsize=(14, 6))
    
    # Wykres Pustego szumu lub Ściany Energii
    plt.plot(t_ms, power, label="Energia uderzenia Radaru", color="darkcyan", linewidth=1.2)
    
    # Dodanie krwisto czerwonych Pinezek gdzie algorytm matematycznie w Oknie zidentyfikował nanosekundowy szczyt Pingów!
    if len(peaks) > 0:
        plt.plot(t_ms[peaks], power[peaks], "ro", markersize=8, label=f"Wykryto kolizje sprzętu! (Piki: {len(peaks)})")
        
        for p in peaks:
            # Wypisz dymek nad Czerwoną znaczkiem żeby fizycznie pokazać ułamek MS
            plt.annotate(f"{t_ms[p]:.3f} ms",
                         (t_ms[p], power[p]), textcoords="offset points", xytext=(0,10), ha='center',
                         fontsize=10, fontweight='bold', color='red')

    plt.title(f"Dokładny Skalpel Analizy Fali - {os.path.basename(target_file)}", fontsize=14, fontweight='bold')
    plt.xlabel("Mijające Milisekundy w otwartym na pusto okienku (ms)", fontsize=11)
    plt.ylabel("Potęga Wyłapanego Sygnału (Power)", fontsize=11)
    
    # Dekoracje Optyczne
    plt.grid(True, linestyle="--", alpha=0.7)
    plt.tight_layout()
    plt.legend()
    plt.show()

if __name__ == "__main__":
    plot_results()
