Aby uruchomić:

wejsc do katalogu signaltrack 
cd signaltrack

python3 main.py system
python3 main.py rx 0
python3 main.py tx 1

aby zmienić ilość rx oraz tx
jest helper/parameters.py
jest tam rx_count oraz tx_count zminiamy tak liczbe nadajników i odbiorników
jest jeszcze mapa z id:
tx_usrp_serial_map
rx_usrp_serial_map

tam się deklaruje kolejne usrpy ich id na linuxie gdy jest podłaczony USRP do kompa
szuka się id 
uhd_find_devices (chyba z s)

---------
zinstaluj msquitto czyli broker do MQTT

W domu (bez przetu) -> helpers/parameters.py i tam zmiana

        self.test_mode = True

        '''mqtt params'''
        self.mqtt_broker = "localhost"

.venv dorobic ale najpierw requirements.txt dopenic# signal-track-new
