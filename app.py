from gtts import gTTS
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request
import os
import re
import random
import threading
import time
import requests
import xml.etree.ElementTree as ET

app = Flask(__name__)

FOLDER_AUDIO = "nagrania_sms"
if not os.path.exists(FOLDER_AUDIO):
    os.makedirs(FOLDER_AUDIO)

# Plik do zapisywania brakujących piosenek od słuchaczy
PLIK_BRAKUJACE = "brakujace_piosenki.txt"

# --- CONFIG AZURACAST ---
STATION_ID = 461
AZURACAST_URL = "https://asurahosting.com"
# Wklejony najnowszy klucz API dedykowany do jingles
KLUCZ_API = "c20a5b4c41c9418b:0c570fe85b23303c51ad93fe7c983b44"
URL_API_FILES = f"{AZURACAST_URL}/api/station/{STATION_ID}/files"

# Definiujemy na stałe naszą strefę czasową dla bota
STREFA_EUROPA = ZoneInfo("Europe/Warsaw")

def wyslij_do_azuracast(sciezka_pliku_mp3):
    """Automatycznie wysyła wygenerowany plik z życzeniami lub zegarem na serwer radiowy"""
    naglowki = {
        "Authorization": f"Bearer {KLUCZ_API}"
    }
    try:
        nazwa_pliku = os.path.basename(sciezka_pliku_mp3)
        with open(sciezka_pliku_mp3, 'rb') as f:
            pliki = {'file': (nazwa_pliku, f, 'audio/mpeg')}
            dane = {'path': 'jingles'}
            
            response = requests.post(URL_API_FILES, headers=naglowki, files=pliki, data=dane)
            
            poprawne_kody = [200, 201, 204]
            if response.status_code in poprawne_kody:
                print(f"[AZURACAST] Sukces! Plik {nazwa_pliku} przesłany do chmury stacji {STATION_ID}.")
                return True, f"Sukces (Kod {response.status_code})"
            else:
                info_blad = f"Kod {response.status_code} | Odpowiedz serwera: {response.text}"
                print(f"[AZURACAST BŁĄD] {info_blad}")
                return False, info_blad
    except Exception as e:
        print(f"[AZURACAST BŁĄD] Wyjątek podczas wysyłania: {e}")
        return False, str(e)
    
def zapisz_tekst_jako_mp3(tekst):
    """Generuje plik MP3 przy użyciu gTTS (Google Cloud) i zwraca jego lokalną ścieżkę"""
    try:
        teraz = datetime.now(STREFA_EUROPA)
        nazwa_pliku = teraz.strftime("godzina_%Y%m%d_%H%M%S.mp3") if "godzina" in tekst.lower() else teraz.strftime("wiadomosc_%Y%m%d_%H%M%S.mp3")
        sciezka_pliku = os.path.join(FOLDER_AUDIO, nazwa_pliku)
        
        # Generowanie profesjonalnego polskiego lektora gTTS
        tts = gTTS(text=tekst, lang='pl', slow=False)
        tts.save(sciezka_pliku)
        
        print(f"[RADIO] Chmura wygenerowała plik audio: {sciezka_pliku}")
        return sciezka_pliku
    except Exception as e:
        print(f"[BŁĄD CHMURY TTS] Problem z generowaniem mowy: {e}")
        return None

def zapisz_brakujacy_utwor(tresc_sms, numer_nadawcy):
    try:
        teraz = datetime.now(STREFA_EUROPA)
        czas_wpisu = teraz.strftime("%Y-%m-%d %H:%M:%S")
        wpis = f"[{czas_wpisu}] Od: {numer_nadawcy} | Treść: {tresc_sms}\n"
        with open(PLIK_BRAKUJACE, "a", encoding="utf-8") as f:
            f.write(wpis)
    except Exception as e:
        print(f"[BŁĄD LOGÓW] Problem z zapisem do pliku tekstowego: {e}")

def inteligentna_korekta(tekst):
    t = tekst.lower()
    slownik_poprawek = {
        "zeby": "żeby", "zyczenia": "życzenia", "zycze": "życzę", "zyczymy": "życzymy",
        "pozdrowienia": "pozdrowienia", "pozdro": "pozdrowienia", "pozdrawiam": "pozdrawiam",
        "dzien": "dzień", "urodziny": "urodziny", "urodzin": "urodzin",
        "dziekuje": "dziękuję", "dzieki": "dzięki", "sie": "się", "ze": "że",
        "dzis": "dziś", "tez": "też", "wogole": "w ogóle", "narazie": "na razie"
    }
    slowa = t.split()
    return " ".join([slownik_poprawek.get(s.strip(".,!?"), s) for s in slowa])

def czy_wiadomosc_jest_zrozumiala_i_bezpieczna(tekst):
    if not tekst or len(tekst.strip()) < 3:
        return False
    t_lower = tekst.lower()
    return any(l in "aąeęioóuy" for l in t_lower)

def pobierz_aktualny_gatunek_muzyczny():
    godzina = datetime.now(STREFA_EUROPA).hour
    if godzina >= 23 or godzina < 1:
        return "Techno / Hard Techno (Nocny Blok Klubowy)"
    elif 6 <= godzina < 17:
        return "House / EDM / 90s Eurodance (Pasmo Dzienne)"
    elif 17 <= godzina < 23:
        return "Disco Polo / Hands Up / Klubowe Remixy (Pasmo Wieczorne)"
    else:
        return "Deep House / Chillout (Nocna Selekcja)"

def pobierz_wiadomosci_polsat():
    """Pobiera najświeższe nagłówki z kanału RSS Polsat News"""
    url_rss = "https://polsatnews.pl"
    try:
        response = requests.get(url_rss, timeout=10)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            naglowki = [item.find('title').text for item in root.findall('.//item') if item.find('title') is not None][:4]
            if naglowki:
                serwis = "A teraz czas na skrót najświeższych wiadomości z kraju i ze świata. "
                for i, news in enumerate(naglowki, 1):
                    serwis += f"Fakt numer {i}: {news}. "
                serwis += "To były wiadomości z serwisu Polsat News. "
                return serwis
    except Exception as e:
        print(f"[BŁĄD RSS] Nie udało się sparsować wiadomości Polsatu: {e}")
    return "Na antenie Radio Strefa Zero gramy dla Was najlepsze klubowe kawałki bez przerwy! "

def pętla_zegara_radiowego():
    ostatnia_zapowiedziana_godzina = -1
    while True:
        teraz = datetime.now(STREFA_EUROPA)
        if teraz.minute == 0 and teraz.hour != ostatnia_zapowiedziana_godzina:
            wyswietlana_godzina = 24 if teraz.hour == 0 else teraz.hour
            tekst_wiadomosci = pobierz_wiadomosci_polsat()

            komunikat_godzinowy = (
                f"Radio Strefa Zero. Wybiła godzina {wyswietlana_godzina}. "
                f"{tekst_wiadomosci} "
                "Chcesz wziąć udział w Koncercie Życzeń, zamówić ulubioną piosenkę lub przesłać pozdrowienia dla bliskich? "
                "Napisz SMS na naszą linię pod numer: plus jeden, osiemset dwanaście, czterysta dwanaście, dwadzieścia dziewięć siedemdziesiąt pięć!"
            )
            sciezka = zapisz_tekst_jako_mp3(komunikat_godzinowy)
            if sciezka and os.path.exists(sciezka):
                wyslij_do_azuracast(sciezka)
                if os.path.exists(sciezka):
                    os.remove(sciezka)
            ostatnia_zapowiedziana_godzina = teraz.hour
        time.sleep(20)

@app.route('/sms', methods=['POST'])
def odbierz_sms():
    tresc_sms = request.form.get('Body', '')
    numer_nadawcy = request.form.get('From', 'Nieznany')
    
    if not czy_wiadomosc_jest_zrozumiala_i_bezpieczna(tresc_sms):
        return "OK", 200

    poprawiona_tresc = inteligentna_korekta(tresc_sms)
    zapisz_brakujacy_utwor(poprawiona_tresc, numer_nadawcy)

    teraz = datetime.now(STREFA_EUROPA)
    imie_nadawcy = "Słuchacz"
    match_podpis = re.search(r'[-–—]\s*([A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż]{2,15})', tresc_sms)
    if match_podpis:
        imie_nadawcy = match_podpis.group(1).capitalize()
    
    dni_koncertu = [4, 5]
    trwa_koncert_zyczeń = (teraz.weekday() in dni_koncertu and 18 <= teraz.hour < 20)
    trwa_piosenka_na_zyczenie = (0 <= teraz.weekday() <= 4 and 17 <= teraz.hour < 18)
    
    if trwa_koncert_zyczeń:
        komunikat_dj = f"W studio Radio Strefa Zero trwa właśnie Koncert Życzeń! Mamy nową wiadomość od {imie_nadawcy}. Oto tekst: {poprawiona_tresc}."
    elif trwa_piosenka_na_zyczenie:
        komunikat_dj = f"Wasz wirtualny prezenter w pasmie Piosenka Na Życzenie. {imie_nadawcy} pisze do nas tak: {poprawiona_tresc}."
    else:
        gatunek = pobierz_aktualny_gatunek_muzyczny()
        komunikat_dj = f"Szybka przerwa w muzyce, w pasmie {gatunek}. Przesyłamy pozdrowienia od słuchacza o imieniu {imie_nadawcy}: {poprawiona_tresc}."

    sciezka = zapisz_tekst_jako_mp3(komunikat_dj)
    if sciezka and os.path.exists(sciezka):
        wyslij_do_azuracast(sciezka)
        if os.path.exists(sciezka):
            os.remove(sciezka)
        
    return "OK", 200

@app.route('/generuj-godzine', methods=['GET', 'POST'])
def endpoint_generuj_godzine():
    try:
        teraz = datetime.now(STREFA_EUROPA)
        wyswietlana_godzina = 24 if teraz.hour == 0 else teraz.hour
        tekst_wiadomosci = pobierz_wiadomosci_polsat()
        
        komunikat_godzinowy = (
            f"Radio Strefa Zero. Wybiła godzina {wyswietlana_godzina}. "
            f"{tekst_wiadomosci} "
            "Chcesz wziąć udział w Koncercie Życzeń, zamówić ulubioną piosenkę lub przesłać pozdrowienia? "
            "Napisz SMS na naszą linię pod numer: plus jeden, osiemset dwanaście, czterysta dwanaście, dwadzieścia dziewięć siedemdziesiąt pięć!"
        )
        
        sciezka_pliku = zapisz_tekst_jako_mp3(komunikat_godzinowy)
        if sciezka_pliku and os.path.exists(sciezka_pliku):
            sukces, powod_statusu = wyslij_do_azuracast(sciezka_pliku)
            if os.path.exists(sciezka_pliku):
                os.remove(sciezka_pliku)
            if sukces:
                return {"status": "success", "message": f"Wygenerowano i wysłano zapowiedz dla godziny {wyswietlana_godzina}"}, 200
            else:
                return {"status": "error", "message": f"Błąd wysyłania do AzuraCast. Szczegóły: {powod_statusu}"}, 500
        else:
            return {"status": "error", "message": "Nie udało się wygenerować pliku MP3"}, 500
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

if __name__ == '__main__':
    watek_zegara = threading.Thread(target=pętla_zegara_radiowego, daemon=True)
    watek_zegara.start()
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
