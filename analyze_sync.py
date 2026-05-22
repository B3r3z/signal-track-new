"""
Analiza synchronizacji czasowej TX0 vs TX1.

Każdy nadajnik nadaje na innej częstotliwości tonu (TX0=50kHz, TX1=150kHz).
Skrypt rozdziela oba sygnały filtrami pasmowymi, wyznacza czas dotarcia
każdego z nich i oblicza różnicę = błąd synchronizacji.
"""
import os
import glob
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt, hilbert, find_peaks


# ── Parametry (muszą zgadzać się z parameters.py) ──
SAMP_RATE = 500e3
TX0_FREQ  = 50e3      # ton TX0
TX1_FREQ  = 150e3     # ton TX1
PULSE_LEN = 200       # próbek (0.4 ms)


def bandpass(sig, f_center, fs, bw=40e3, order=4):
    """Filtr pasmowy wokół f_center ± bw/2."""
    low  = (f_center - bw / 2) / (fs / 2)
    high = (f_center + bw / 2) / (fs / 2)
    # Ograniczenie do zakresu (0, 1)
    low  = max(low, 0.001)
    high = min(high, 0.999)
    b, a = butter(order, [low, high], btype='band')
    return filtfilt(b, a, sig)


def envelope(sig):
    """Obwiednia sygnału (moduł transformaty Hilberta)."""
    return np.abs(hilbert(sig))


def find_arrival(env, threshold_frac=0.5):
    """
    Znajduje moment dotarcia impulsu jako pierwszy próbkę,
    w której obwiednia przekracza threshold_frac * max.
    Daje powtarzalny wynik niezależny od kształtu szczytu.
    """
    peak_idx = np.argmax(env)
    peak_val = env[peak_idx]
    threshold = peak_val * threshold_frac
    # Szukaj pierwszego przekroczenia progu (od lewej)
    above = np.where(env[:peak_idx + 1] >= threshold)[0]
    if len(above) > 0:
        return above[0]
    return peak_idx


def analyze_file(filepath):
    """Analizuje pojedynczy plik .npy i zwraca wyniki."""
    raw_iq = np.load(filepath)
    n = len(raw_iq)
    t_ms = np.arange(n) / SAMP_RATE * 1000.0

    # ── Rozdzielenie sygnałów ──
    tx0_filtered = bandpass(raw_iq.real, TX0_FREQ, SAMP_RATE)
    tx1_filtered = bandpass(raw_iq.real, TX1_FREQ, SAMP_RATE)

    tx0_env = envelope(tx0_filtered)
    tx1_env = envelope(tx1_filtered)

    # ── Wyznaczenie czasu dotarcia ──
    tx0_arrival = find_arrival(tx0_env)
    tx1_arrival = find_arrival(tx1_env)

    tx0_time_ms = tx0_arrival / SAMP_RATE * 1000.0
    tx1_time_ms = tx1_arrival / SAMP_RATE * 1000.0
    delta_us    = (tx1_arrival - tx0_arrival) / SAMP_RATE * 1e6  # w mikrosekundach

    return {
        "t_ms": t_ms,
        "tx0_env": tx0_env,
        "tx1_env": tx1_env,
        "tx0_arrival": tx0_arrival,
        "tx1_arrival": tx1_arrival,
        "tx0_time_ms": tx0_time_ms,
        "tx1_time_ms": tx1_time_ms,
        "delta_us": delta_us,
    }


# def plot_single(filepath):
#     """Rysuje analizę jednego pliku."""
#     r = analyze_file(filepath)
#     fname = os.path.basename(filepath)
#
#     fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
#     fig.suptitle(f"Analiza synchronizacji TX — {fname}", fontsize=14, fontweight="bold")
#
#     # 1) Surowy sygnał
#     raw = np.load(filepath)
#     power = np.abs(raw) ** 2
#     axes[0].plot(r["t_ms"], power, color="darkcyan", linewidth=0.8)
#     axes[0].set_ylabel("Moc surowa")
#     axes[0].set_title("Surowy sygnał (oba TX razem)")
#     axes[0].grid(True, alpha=0.3)
#
#     # 2) Obwiednie po rozdzieleniu
#     axes[1].plot(r["t_ms"], r["tx0_env"], color="dodgerblue", linewidth=1.2, label=f"TX0 (50 kHz) → {r['tx0_time_ms']:.3f} ms")
#     axes[1].plot(r["t_ms"], r["tx1_env"], color="orangered",  linewidth=1.2, label=f"TX1 (150 kHz) → {r['tx1_time_ms']:.3f} ms")
#     axes[1].axvline(r["tx0_time_ms"], color="dodgerblue", linestyle="--", alpha=0.7)
#     axes[1].axvline(r["tx1_time_ms"], color="orangered",  linestyle="--", alpha=0.7)
#     axes[1].set_ylabel("Obwiednia")
#     axes[1].set_title("Sygnały rozdzielone filtrami pasmowymi")
#     axes[1].legend(loc="upper right")
#     axes[1].grid(True, alpha=0.3)
#
#     # 3) Zbliżenie na moment dotarcia
#     center = (r["tx0_arrival"] + r["tx1_arrival"]) // 2
#     margin = int(SAMP_RATE * 0.002)  # ±2ms
#     lo = max(0, center - margin)
#     hi = min(len(r["t_ms"]), center + margin)
#
#     axes[2].plot(r["t_ms"][lo:hi], r["tx0_env"][lo:hi], color="dodgerblue", linewidth=1.5, label="TX0")
#     axes[2].plot(r["t_ms"][lo:hi], r["tx1_env"][lo:hi], color="orangered",  linewidth=1.5, label="TX1")
#     axes[2].axvline(r["tx0_time_ms"], color="dodgerblue", linestyle="--", linewidth=2)
#     axes[2].axvline(r["tx1_time_ms"], color="orangered",  linestyle="--", linewidth=2)
#
#     axes[2].set_ylabel("Obwiednia (zoom)")
#     axes[2].set_xlabel("Czas (ms)")
#     axes[2].set_title(f"ZBLIŻENIE — Różnica czasu dotarcia: {r['delta_us']:.1f} µs")
#     axes[2].legend(loc="upper right")
#     axes[2].grid(True, alpha=0.3)
#
#     plt.tight_layout()
#     plt.show()
#
#     return r


def analyze_all(results_dir="results"):
    """Analizuje wszystkie pliki .npy i wypisuje statystyki synchronizacji."""
    files = sorted(glob.glob(os.path.join(results_dir, "*.npy")), key=os.path.getmtime)
    if not files:
        print(f"Brak plików .npy w {results_dir}")
        return

    deltas = []
    tx0_times = []
    tx1_times = []

    print(f"\n{'='*70}")
    print(f"  RAPORT SYNCHRONIZACJI TX0 vs TX1")
    print(f"  Liczba plików: {len(files)}")
    print(f"{'='*70}")
    print(f"{'Plik':<35} {'TX0 (ms)':>10} {'TX1 (ms)':>10} {'Δ (µs)':>10}")
    print(f"{'-'*70}")

    for f in files:
        try:
            r = analyze_file(f)
            deltas.append(r["delta_us"])
            tx0_times.append(r["tx0_time_ms"])
            tx1_times.append(r["tx1_time_ms"])
            print(f"{os.path.basename(f):<35} {r['tx0_time_ms']:>10.3f} {r['tx1_time_ms']:>10.3f} {r['delta_us']:>10.1f}")
        except Exception as e:
            print(f"{os.path.basename(f):<35} BŁĄD: {e}")

    if deltas:
        deltas = np.array(deltas)
        tx0_times = np.array(tx0_times)
        tx1_times = np.array(tx1_times)

        print(f"{'-'*70}")
        print(f"")
        print(f"  CZAS DOTARCIA TX0 (50 kHz):")
        print(f"    Średni:    {np.mean(tx0_times):>8.3f} ms")
        print(f"    Min/Max:   {np.min(tx0_times):>8.3f} / {np.max(tx0_times):.3f} ms")
        print(f"")
        print(f"  CZAS DOTARCIA TX1 (150 kHz):")
        print(f"    Średni:    {np.mean(tx1_times):>8.3f} ms")
        print(f"    Min/Max:   {np.min(tx1_times):>8.3f} / {np.max(tx1_times):.3f} ms")
        print(f"")
        print(f"  RÓŻNICA TX1 - TX0:")
        print(f"    Średnia:   {np.mean(deltas):>+8.1f} µs")
        print(f"    Odch. std: {np.std(deltas):>8.1f} µs")
        print(f"    Min/Max:   {np.min(deltas):>+8.1f} / {np.max(deltas):+.1f} µs")
        print(f"{'='*70}")



if __name__ == "__main__":
    results_dir = "results"
    analyze_all(results_dir)
