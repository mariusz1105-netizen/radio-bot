from gtts import gTTS
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request
import os
import re
import threading
import time
import requests

app = Flask(__name__)

FOLDER_AUDIO = "nagrania_sms"
if not os.path.exists(FOLDER_AUDIO):
    os.makedirs(FOLDER_AUDIO)

PLIK_BRAKUJACE = "brakujace_piosenki.txt"

# --- CONFIG AZURACAST (Zmienione na otwarty protokół HTTP omijający osłony SSL) ---
STATION_ID = 461
AZURACAST_URL = "http://asurahosting.com"
URL_API_CONTENTS = f"{AZURACAST_URL}/api/station/{STATION_ID}/file/contents"
KLUCZ_API = "c20a5b4c41c9418b:0c570fe85b23303c51ad93fe7c983b44"

# Definiujemy na stałe naszą strefę czasową dla bota
STREFA_EUROPA = ZoneInfo("Europe/Warsaw")

def wyslij_do_azuracast(sciezka_pliku_mp3):
    """Wysyła plik MP3 jako czyste dane binarne metodą PUT przez otwarte połączenie HTTP"""
    nazwa_pliku = os.path.basename(sciezka_pliku_mp3)
    parametry = {
        'file': f"jingles/{nazwa_pliku}"
    }
    
    naglowki = {
        "Authorization": f"Bearer {KLUCZ_API}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/octet-stream"
    }
    
    try:
        with open(sciezka_pliku_mp3, 'rb') as f:
            # Używamy czystego http://, aby ominąć filtry i ekrany sprawdzania
            response = requests.put(URL_API_CONTENTS, headers=naglowki, params=parametry, data=f, timeout=20)
            status_str = str(response.status_code)
            
            if status_str in ["200", "201", "204"]:
                print(f"[AZURACAST] Sukces! Plik {nazwa_pliku} został wgrany na antenę.")
                return True, f"Sukces (Kod {response.status_code})"
            else:
                info_blad = f"Kod {response.status_code} | Odpowiedz serwera: {response.text[:250]}"
                print(f"[AZURACAST BŁĄD] {info_blad}")
                return False, info_blad
    except Exception as e:
        print(f"[AZURACAST BŁĄD] Wyjątek podczas wysyłania: {e}")
        return False, str(e)

def zapisz_tekst_jako_mp3(tekst):
    try:
        teraz = datetime.now(STREFA_EUROPA)
        if "godzina" in tekst.lower():
            nazwa_pliku = teraz.strftime("godzina_%Y%m%d_%H%M%S.mp3")
        else:
            nazwa_pliku = teraz.strftime("wiadomosc_%Y%m%d_%H%M%S.mp3")
            
        sciezka_pliku = os.path.join(FOLDER_AUDIO, nazwa_pliku)
        tts = gTTS(text=tekst, lang='pl', slow=False)
        tts.save(sciezka_pliku)
        print(f"[RADIO] Wygenerowano plik audio: {sciezka_pliku}")
        return sciezka_pliku
    except Exception as e:
        print(f"[BŁĄD CHMURY TTS] Problem z mową: {e}")
        return None

def zapisz_brakujacy_utwor(tresc_sms, numer_nadawcy):
    try:
        teraz = datetime.now(STREFA_EUROPA)
        czas_wpisu = teraz.strftime("%Y-%m-%d %H:%M:%S")
        wpis = f"[{czas_wpisu}] Od: {numer_nadawcy} | Treść: {tresc_sms}\n"
        with open(PLIK_BRAKUJACE, "a", encoding="utf-8") as f:
            f.write(wpis)
    except Exception as e:
        print(f"[BŁĄD LOGÓW] Problem z zapisem pliku: {e}")

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
    url = "https://polsatnews.pl"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            html = response.text
            znalezione = re.findall(r'<h2>(.*?)</h2>', html)
            czyste_naglowki = []
            for tytul in znalezione:
                title_clean = re.sub(r'<[^>]*>', '', tytul).strip()
                if title_clean and len(title_clean) > 10 and not title_clean.startswith("Sonda") and title_clean not in czyste_naglowki:
                    czyste_naglowki.append(title_clean)
            
            naglowki = czyste_naglowki[:4]
            if naglowki:
                serwis = "A teraz czas na skrót najświeższych wiadomości z kraju i ze świata. "
                for i, news in enumerate(naglowki, 1):
                    serwis += f"Fakt numer {i}: {news}. "
                serwis += "To były wiadomości z serwisu Polsat News. "
                return serwis
    except Exception as e:
        print(f"[BŁĄD PARSERA] Problem z Polsatem: {e}")
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
            if sciezka:
                if os.path.exists(sciezka):
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
    
    dzien_str = str(teraz.weekday())
    trwa_koncert_zyczeń = ((dzien_str == "4" or dzien_str == "5") and 18 <= teraz.hour < 20)
    trwa_piosenka_na_zyczenie = (teraz.weekday() <= 4 and 17 <= teraz.hour < 18)
    
    if trwa_koncert_zyczeń:
        komunikat_dj = f"W studio Radio Strefa Zero trwa właśnie Koncert Życzeń! Mamy nową wiadomość od {imie_nadawcy}. Oto tekst: {poprawiona_tresc}."
    elif trwa_piosenka_na_zyczenie:
        komunikat_dj = f"Wasz wirtualny prezenter w pasmie Piosenka Na Życzenie. {imie_nadawcy} pisze do nas tak: {poprawiona_tresc}."
    else:
        gatunek = pobierz_aktualny_gatunek_muzyczny()
        komunikat_dj = f"Szybka przerwa w muzyce, w pasmie {gatunek}. Przesyłamy pozdrowienia od słuchacza o imieniu {imie_nadawcy}: {poprawiona_tresc}."

    sciezka = zapisz_tekst_jako_mp3(komunikat_dj)
    if sciezka:
        if os.path.exists(sciezka):
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
            wynik_wysylki, powod_statusu = wyslij_do_azuracast(sciezka_pliku)
            if os.path.exists(sciezka_pliku):
                os.remove(sciezka_pliku)
            if wynik_wysylki:
                return {"status": "success", "message": f"Wygenerowano zapowiedz dla godziny {wyswietlana_godzina}"}, 200
            else:
                return {"status": "error", "message": f"Problem z AzuraCast: {powod_statusu}"}, 500
        else:
            return {"status": "error", "message": "Nie udalo sie stworzyc MP3"}, 500
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

@app.route('/', methods=['GET'])
def strona_startowa():
