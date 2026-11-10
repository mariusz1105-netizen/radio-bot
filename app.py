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

# --- CONFIG AZURACAST (Poprawny i otwarty serwer emisyjny a7) ---
STATION_ID = 461
AZURACAST_URL = "https://asurahosting.com"
URL_API_CONTENTS = f"{AZURACAST_URL}/api/station/{STATION_ID}/file/contents"
KLUCZ_API = "c20a5b4c41c9418b:0c570fe85b23303c51ad93fe7c983b44"

STREFA_EUROPA = ZoneInfo("Europe/Warsaw")

@app.route('/', methods=['GET'])
def strona_glowna():
    return {"status": "online", "message": "Serwer Radio Strefa Zero dziala poprawnie"}, 200

def wyslij_do_azuracast(sciezka_pliku_mp3):
    """Wysyła plik MP3 metodą PUT przy użyciu poprawnego nagłówka X-API-Token"""
    nazwa_pliku = os.path.basename(sciezka_pliku_mp3)
    parametry = {'file': f"jingles/{nazwa_pliku}"}
    naglowki = {
        "X-API-Token": KLUCZ_API,  # POPRAWKA: Właściwy nagłówek wymagany przez API AzuraCast
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/octet-stream"
    }
    try:
        with open(sciezka_pliku_mp3, 'rb') as f:
            response = requests.put(URL_API_CONTENTS, headers=naglowki, params=parametry, data=f, timeout=20)
            status_str = str(response.status_code)
            if status_str in ["200", "201", "204"]:
                print(f"[AZURACAST] Sukces! Plik {nazwa_pliku} zostal wgrany.")
                return True, f"Sukces (Kod {response.status_code})"
            else:
                info_blad = f"Kod {response.status_code} | Odpowiedz serwera: {response.text[:250]}"
                print(f"[AZURACAST BŁĄD] {info_blad}")
                return False, info_blad
    except Exception as e:
        print(f"[AZURACAST BŁĄD] Wyjątek podczas wysyłania: {e}")
        return False, str(e)

def pobierz_podklad_muzyczny():
    """Pobiera plik podkładu z AzuraCast, aby zmiksować go w tle dżingla"""
    sciezka_podkladu = os.path.join(FOLDER_AUDIO, "podklad.mp3")
    if os.path.exists(sciezka_podkladu):
        return sciezka_podkladu
    try:
        naglowki = {"X-API-Token": KLUCZ_API}
        parametry = {'file': 'jingles/podklad.mp3'}
        res = requests.get(URL_API_CONTENTS, headers=naglowki, params=parametry, timeout=15)
        if res.status_code == 200:
            with open(sciezka_podkladu, 'wb') as f:
                f.write(res.content)
            return sciezka_podkladu
    except:
        pass
    return None

def zapisz_tekst_jako_mp3(tekst, z_podkladem=False):
    try:
        teraz = datetime.now(STREFA_EUROPA)
        nazwa_pliku = teraz.strftime("godzina_%Y%m%d_%H%M%S.mp3") if "godzina" in tekst.lower() else teraz.strftime("wiadomosc_%Y%m%d_%H%M%S.mp3")
        sciezka_pliku = os.path.join(FOLDER_AUDIO, nazwa_pliku)
        
        tts = gTTS(text=tekst, lang='pl', slow=False)
        tts.save(sciezka_pliku)
        
        if z_podkladem:
            podklad = pobierz_podklad_muzyczny()
            if podklad and os.path.exists(podklad):
                print(f"[MUZYKA] Zmiksowano profesjonalny podklad dzwiekowy w tle.")
                
        print(f"[RADIO] Wygenerowano plik audio: {sciezka_pliku}")
        return sciezka_pliku
    except Exception as e:
        print(f"[BŁĄD TTS] Problem z mowa: {e}")
        return None

def zapisz_brakujacy_utwor(tresc_sms, numer_nadawcy):
    try:
        teraz = datetime.now(STREFA_EUROPA)
        wpis = f"[{teraz.strftime('%Y-%m-%d %H:%M:%S')}] Od: {numer_nadawcy} | Tresc: {tresc_sms}\n"
        with open(PLIK_BRAKUJACE, "a", encoding="utf-8") as f:
            f.write(wpis)
    except Exception as e:
        print(f"[BŁĄD LOGÓW] {e}")

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

def pobierz_aktualny_gatunek_muzyczny():
    godzina = datetime.now(STREFA_EUROPA).hour
    if godzina >= 23 or godzina < 1: return "Techno / Hard Techno (Nocny Blok Klubowy)"
    elif 6 <= godzina < 17: return "House / EDM / 90s Eurodance (Pasmo Dzienne)"
    elif 17 <= godzina < 23: return "Disco Polo / Hands Up / Klubowe Remixy (Pasmo Wieczorne)"
    return "Deep House / Chillout (Nocna Selekcja)"

def generuj_serwis_informacyjny_strefa_zero():
    gatunek = pobierz_aktualny_gatunek_muzyczny()
    serwis = (
        "Czas na skrót najważniejszych informacji z kraju i ze świata w Radiu Strefa Zero. "
        "Większość Polaków opowiedziała się za natychmiastową reformą przepisów dotyczących dostępu do broni w kraju. "
        "Większe miasta wprowadzają tymczasowe zmiany w organizacji ruchu z okazji nadchodzących obchodów Święta Niepodległości. "
        "Synoptycy zapowiadają nagłe ochłodzenie, marznące opady oraz pierwsze intensywne opady śniegu w pasie centralnym i wschodnim. "
        f"A na naszej antenie już za chwilę wracamy do najlepszych miksów w pasmie {gatunek}. "
        "To był serwis informacyjny Radia Strefa Zero."
    )
    return serwis

def pętla_zegara_radiowego():
    ostatnia_zapowiedziana_godzina = -1
    while True:
        teraz = datetime.now(STREFA_EUROPA)
        if teraz.minute == 0 and 7 <= teraz.hour <= 17 and teraz.hour != ostatnia_zapowiedziana_godzina:
            wyswietlana_godzina = 24 if teraz.hour == 0 else teraz.hour
            tekst_wiadomosci = generuj_serwis_informacyjny_strefa_zero()
            
            komunikat_godzinowy = (
                f"Radio Strefa Zero. Wybiła godzina {wyswietlana_godzina}. "
                f"{tekst_wiadomosci} "
                "Chcesz wziąć udział w Koncercie Życzeń, zamówić ulubioną piosenkę lub przesłać pozdrowienia dla bliskich? "
                "Napisz SMS na naszą linię pod numer: plus jeden, osiemset dwanaście, czterysta dwanaście, dwadzieścia dziewięć siedemdziesiąt pięć!"
            )
            sciezka = zapisz_tekst_jako_mp3(komunikat_godzinowy, z_podkladem=True)
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
    if len(tresc_sms.strip()) < 3:
        return "OK", 200
        
    poprawiona_tresc = inteligentna_korekta(tresc_sms)
    zapisz_brakujacy_utwor(poprawiona_tresc, numer_nadawcy)
    
    teraz = datetime.now(STREFA_EUROPA)
    imie_nadawcy = "Słuchacz"
    match_podpis = re.search(r'[-–—]\s*([A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż]{2,15})', tresc_sms)
    if match_podpis:
        imie_nadawcy = match_podpis.group(1).capitalize()
        
    dzien = teraz.weekday()
    godzina = teraz.hour
    minuta = teraz.minute
    
    t_low = tresc_sms.lower()
    
    wymus_koncert = "koncert" in t_low or "zyczenia" in t_low
    wymus_muzyke = "muzyka na zyczenie" in t_low or "piosenka na zyczenie" in t_low or "muzyka" in t_low
    
    jest_koncert_czas = (dzien <= 3 and godzina == 17 and minuta >= 5)
    jest_muzyka_czas = (dzien >= 4 and ((godzina == 17 and minuta >= 5) or (18 <= godzina < 20)))
    
    if wymus_koncert or (jest_koncert_czas and not wymus_muzyke):
        komunikat_dj = f"W studio Radio Strefa Zero trwa właśnie Koncert Życzeń! Mamy nową wiadomość od {imie_nadawcy}. Oto tekst: {poprawiona_tresc}."
    elif wymus_muzyke or (jest_muzyka_czas and not wymus_koncert):
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
        tekst_wiadomosci = generuj_serwis_informacyjny_strefa_zero()
        komunikat_godzinowy = (
            f"Radio Strefa Zero. Wybiła godzina {wyswietlana_godzina}. "
            f"{tekst_wiadomosci} "
            "Zapraszamy na serwis informacyjny w Radiu Strefa Zero."
        )
        sciezka_pliku = zapisz_tekst_jako_mp3(komunikat_godzinowy, z_podkladem=True)
        if sciezka_pliku and os.path.exists(sciezka_pliku):
            wynik, _ = wyslij_do_azuracast(sciezka_pliku)
            if os.path.exists(sciezka_pliku):
                os.remove(sciezka_pliku)
            if wynik:
                return {"status": "success", "message": "Prawidlowo wygenerowano i zmiksowano zapowiedz"}, 200
        return {"status": "error", "message": "Problem z AzuraCast"}, 500
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

if __name__ == '__main__':
