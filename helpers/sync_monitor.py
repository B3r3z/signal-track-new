"""
Monitoring synchronizacji czasowej między USRP B210 używając CDA-2990 Clock Distribution Accessory.

CDA-2990 dostarcza:
- 10 MHz reference clock do zasilenia sygnału zegara
- 1 PPS (Pulse Per Second) dla synchronizacji czasu całkowitego

Moduł monitoruje działanie sygnału PPS i jakość synchronizacji.
"""

import time
import numpy as np
from loguru import logger as log


class SyncMonitor:
    """Monitoring wyznacznika synchronizacji PPS między nadajnikami/odbiornikami."""
    
    def __init__(self, usrp, device_id, device_type="tx"):
        """
        Args:
            usrp: Obiekt USRP (MultiUSRP)
            device_id: ID urządzenia (0, 1, itd.)
            device_type: Typ urządzenia ("tx" lub "rx")
        """
        self.usrp = usrp
        self.device_id = device_id
        self.device_type = device_type
        self.device_label = f"{device_type.upper()}{device_id}"
        
        self.pps_count = 0
        self.last_pps_time = None
        self.pps_timestamps = []
        self.pps_intervals = []
        self.errors = []
        
    def wait_for_pps_lock(self, timeout=5.0, verbose=True):
        """
        Czeka aż urządzenie otrzyma co najmniej 3 impulsy PPS (potwierdzenie synchronizacji).
        Ignoruje pierwszy PPS który może być błędny przy inicjalizacji.
        
        Args:
            timeout: Maksymalny czas oczekiwania (sekundy)
            verbose: Czy drukować status
            
        Returns:
            bool: True jeśli PPS jest zsynchronizowany, False jeśli timeout
        """
        start_time = time.time()
        self.last_pps_time = self.usrp.get_time_last_pps().get_real_secs()
        pps_count_raw = 0  # Liczba zmian (łącznie z pierwszą)
        
        if verbose:
            log.info(f"[{self.device_label}] Oczekiwanie na synchronizację PPS z CDA-2990...")
        
        while time.time() - start_time < timeout:
            current_pps_time = self.usrp.get_time_last_pps().get_real_secs()
            
            # Jeśli czas zmienił się, znaczy że nadeszło nowe zbocze PPS
            if current_pps_time != self.last_pps_time:
                pps_count_raw += 1
                
                # Ignoruj pierwszy PPS - może być błędny przy inicjalizacji
                if pps_count_raw > 1:
                    interval = current_pps_time - self.last_pps_time
                    self.pps_intervals.append(interval)
                    self.pps_count += 1
                    self.pps_timestamps.append(current_pps_time)
                    
                    if verbose:
                        log.info(f"[{self.device_label}] ✓ PPS #{self.pps_count} | "
                               f"Interwał: {interval:.3f}s | USRP time: {current_pps_time:.3f}s")
                else:
                    if verbose:
                        log.debug(f"[{self.device_label}] [SKIP] Pierwszy PPS (może być błędny zaraz po init)")
                
                self.last_pps_time = current_pps_time
                
                # Czekamy na 3 impulsy (czyli 2 prawidłowe interwały) = pewna synchronizacja
                if pps_count_raw >= 3:
                    if verbose:
                        log.info(f"[{self.device_label}] ✓✓ Zsynchronizowano z CDA-2990! "
                               f"(odebrano {self.pps_count} prawidłowych impulsów PPS)")
                    return True
            
            time.sleep(0.05)  # Sprawdzaj 20 razy na sekundę (50ms)
        
        log.warning(f"[{self.device_label}] TIMEOUT: Nie udało się zsynchronizować PPS "
                   f"(odebrano tyko {self.pps_count} impulsów w {timeout:.1f}s)")
        return False
    
    def get_sync_stats(self):
        """Zwraca statystykę synchronizacji."""
        if not self.pps_intervals:
            return {
                "device": self.device_label,
                "pps_count": 0,
                "status": "NO_PPS",
                "mean_interval": None,
                "std_interval": None,
                "min_interval": None,
                "max_interval": None
            }
        
        intervals = np.array(self.pps_intervals)
        return {
            "device": self.device_label,
            "pps_count": self.pps_count,
            "status": "SYNCED" if self.pps_count >= 2 else "PARTIAL",
            "mean_interval": float(np.mean(intervals)),
            "std_interval": float(np.std(intervals)),
            "min_interval": float(np.min(intervals)),
            "max_interval": float(np.max(intervals)),
            "expected_interval": 1.0,  # PPS powinno być co dokładnie 1 sekundę
        }
    
    def print_sync_stats(self):
        """Drukuje statystykę synchronizacji."""
        stats = self.get_sync_stats()
        
        log.info(f"\n{'='*60}")
        log.info(f"  STATYSTYKA SYNCHRONIZACJI PPS - {stats['device']}")
        log.info(f"{'='*60}")
        log.info(f"  Status: {stats['status']}")
        log.info(f"  Liczba impulsów PPS: {stats['pps_count']}")
        
        if stats['mean_interval'] is not None:
            log.info(f"  Średni interwał: {stats['mean_interval']:.6f}s "
                    f"(oczekiwany: {stats['expected_interval']:.6f}s)")
            log.info(f"  Odch. standardowe: {stats['std_interval']:.6f}s")
            log.info(f"  Min/Max interwału: {stats['min_interval']:.6f}s / {stats['max_interval']:.6f}s")
            
            # Sprawdzenie poprawności
            if abs(stats['mean_interval'] - 1.0) < 0.01:
                log.info(f"  ✓ PRAWIDŁOWA synchronizacja z CDA-2990 (interwał ≈ 1.0s)")
            else:
                log.warning(f"  ✗ BŁĘDNA synchronizacja! Interwał PPS={stats['mean_interval']:.3f}s != 1.0s")
        
        log.info(f"{'='*60}\n")
