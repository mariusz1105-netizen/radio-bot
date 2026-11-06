
import pyttsx3
from datetime import datetime
from flask import Flask, request
import os
import re
import random
import threading
import time

app = Flask(__name__)

FOLDER_AUDIO = "nagrania_sms"
if not os.path.exists(FOLDER_AUDIO):
    os.makedirs(FOLDER_AUDIO)
AZURACAST_API_KEY = "4a6c45c753e78452:9933e4e1c5e97d5b9dbcd76d0e6c47ce
# Plik do zapisywania brakujących piosenek od słuchaczy
PLIK_BRAKUJACE = "brakujace_piosenki.txt"
STATION_ID = 461
AZURACAST_URL = "https://a7.asurahosting.com"
# Inicjalizujemy globalny silnik TTS raz na starcie aplikacji
try:
    engine = pyttsx3.init()
except Exception as e:
    print(f"[OSTRZEŻENIE] Problem z inicjalizacją silnika TTS: {e}")

def zapisz_tekst_jako_mp3(tekst, plec_glosu=0):
    """Generuje plik MP3 z mową syntezatora i zapisuje go w folderze projektu."""
    try:
        voices = engine.getProperty('voices')
        if voices and len(voices) > plec_glosu:
            engine.setProperty('voice', voices[plec_glosu].id)
            
        nazwa_pliku = datetime.now().strftime("godzina_%Y%m%d_%H%M%S_%f.mp3") if "godzina" in tekst.lower() else datetime.now().strftime("wiadomosc_%Y%m%d_%H%M%S_%f.mp3")
        sciezka_pliku = os.path.join(FOLDER_AUDIO, nazwa_pliku)
        
        engine.save_to_file(tekst, sciezka_pliku)
        engine.runAndWait()
        
        print(f"[RADIO] Zapisano plik audio (głos index {plec_glosu}): {sciezka_pliku}")
        return sciezka_pliku
    except Exception as e:
        print(f"[BŁĄD] Nie udało się zapisać pliku audio: {e}")
        return None

def zapisz_brakujacy_utwor(tresc_sms, numer_nadawcy):
    """Zapisuje prośbę o piosenkę do pliku tekstowego, jeśli nie ma jej w systemie."""
    try:
        czas_wpisu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        wpis = f"[{czas_wpisu}] Od: {numer_nadawcy} | Treść: {tresc_sms}\n"
        with open(PLIK_BRAKUJACE, "a", encoding="utf-8") as f:
            f.write(wpis)
        print(f"[LISTA ŻYCZEŃ] Zapisano brakujący utwór/prośbę do pliku: {PLIK_BRAKUJACE}")
    except Exception as e:
        print(f"[BŁĄD] Nie udało się zapisać brakującego utworu: {e}")

def inteligentna_korekta(tekst):
    t = tekst.lower()
    slownik_poprawek = {
        "zeby": "żeby", "zyczenia": "życzenia", "zycze": "życzę", "zyczymy": "życzymy",
        "pozdrowienia": "pozdrowienia", "pozdro": "pozdrowienia", "pozdrawiam": "pozdrawiam",
        "dzien": "dzień", "urodziny": "urodziny", "urodzin": "urodzin",
        "dziekuje": "dziękuję", "dzieki": "dzięki", "sie": "się", "ze": "że",
        "dzis": "dziś", "tez": "też", "wogole": "w ogóle", "narazie": "na razie",
        "troszke": "troszkę", "fajnie": "fajnie", "muzyka": "muzyka",
        "muzyczke": "muzyczkę", "pozdrowionka": "pozdrowionka", "caluski": "całuski",
        "kocham": "kocham", "piosenka": "piosenka", "utworek": "utworek", "zagraj": "zagraj"
    }
    slowa = t.split()
    poprawione = [slownik_poprawek.get(s.strip(".,!?"), s) for s in slowa]
    return " ".join(poprawione)

def czy_wiadomosc_jest_zrozumiala_i_bezpieczna(tekst):
    if not tekst or len(tekst.strip()) < 3:
        return False
    t_lower = tekst.lower()
    samogłoski = "aąeęioóuy"
    if not any(l in samogłoski for l in t_lower):
        return False
    for slowo in t_lower.split():
        if len(slowo) > 20:
            return False
    return True

def pobierz_aktualny_gatunek_muzyczny():
    godzina = datetime.now().hour
    if godzina >= 23 or godzina < 1:
        return "Techno / Hard Techno (Nocny Blok Klubowy)"
    elif 6 <= godzina < 17:
        return "House / EDM / 90s Eurodance (Pasmo Dienne)"
    elif 17 <= godzina < 23:
        return "Disco Polo / Hands Up / Klubowe Remixy (Pasmo Wieczorne)"
    else:
        return "Deep House / Chillout (Nocna Selekcja)"

# Wątek w tle pilnujący pełnych godzin (1:00 do 24:00) z podaniem numeru telefonu do życzeń
def pętla_zegara_radiowego():
    ostatnia_zapowiedziana_godzina = -1
    while True:
        teraz = datetime.now()
        aktualna_godzina = teraz.hour  # 0 do 23
        aktualna_minuta = teraz.minute
        
        if aktualna_minuta == 0 and aktualna_godzina != ostatnia_zapowiedziana_godzina:
            wyswietlana_godzina = 24 if aktualna_godzina == 0 else aktualna_godzina
            
            wybrany_glos_zegar = 0 if wyswietlana_godzina % 2 == 0 else 1
            
            komunikat_godzinowy = (
                f"Wybila godzina {wyswietlana_godzina}. Radio Strefa Zero. "
                "Chcesz wysłać pozdrowienia lub zamówić piosenkę? "
                "Napisz SMS na numer plus jeden, osiemset dwanaście, czterysta dwanaście, dwadzieścia dziewięć siedemdziesiąt pięć!"
            )
            
            print(f"[ZEGAR AUTOMATYCZNY] Pełna godzina {wyswietlana_godzina}:00 z numerem telefonu. Generuję zapowiedź.")
            zapisz_tekst_jako_mp3(komunikat_godzinowy, plec_glosu=wybrany_glos_zegar)
            
            ostatnia_zapowiedziana_godzina = aktualna_godzina
            
        time.sleep(20)

@app.route('/sms', methods=['POST'])
def odbierz_sms():
    tresc_sms = request.form.get('Body', '')
    numer_nadawcy = request.form.get('From', 'Nieznany')
    
    print(f"[SMS] Otrzymano wiadomość od {numer_nadawcy}: {tresc_sms}")
    
    if not czy_wiadomosc_jest_zrozumiala_i_bezpieczna(tresc_sms):
        print(f"[BLOKADA] Wiadomość odrzucona (spam lub bełkot). Nie puszczam na antenę.")
        return "OK", 200

    poprawiona_tresc = inteligentna_korekta(tresc_sms)

    # Zapisujemy każdą poprawną prośbę do pliku z brakującymi piosenkami/życzeniami
    zapisz_brakujacy_utwor(poprawiona_tresc, numer_nadawcy)

    teraz = datetime.now()
    dzien_tygodnia = teraz.weekday()
    godzina = teraz.hour
    
    imie_nadawcy = "Słuchacz"
    match_podpis = re.search(r'[-–—]\s*([A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż]{2,15})', tresc_sms)
    if match_podpis:
        imie_nadawcy = match_podpis.group(1).capitalize()
    
    trwa_koncert_zyczeń = ((dzien_tygodnia in [4, 5]) and (18 <= godzina < 20))
    trwa_piosenka_na_zyczenie = ((0 <= dzien_tygodnia <= 4) and (17 <= godzina < 18))

    if trwa_koncert_zyczeń or trwa_piosenka_na_zyczenie:
        czesc_pierwsza = f"Mamy wiadomość od {imie_nadawcy}: {poprawiona_tresc}."
        print(f"[STUDIO - Prezenter 1] {czesc_pierwsza}")
        zapisz_tekst_jako_mp3(czesc_pierwsza, plec_glosu=0)
        
        komentarze_studio = [
            f"Dokładnie tak! Pozdrawiamy {imie_nadawcy} i lecimy z kolejnym kawałkiem!",
            f"Piękne słowa od {imie_nadawcy}. Zostawcie te pozdrowienia w pamięci!",
            f"Dzięki wielkie {imie_nadawcy} za tę wiadomość. Muzyka gra dla Was cały czas!"
        ]
        czesc_druga = random.choice(komentarze_studio)
        print(f"[STUDIO - Prezenter 2] {czesc_druga}")
        zapisz_tekst_jako_mp3(czesc_druga, plec_glosu=1)
    else:
        aktualny_profil = pobierz_aktualny_gatunek_muzyczny()
        print(f"[AUTOMAT MUZYCZNY] Brak życzeń. Na antenie gra: {aktualny_profil}")
        return "OK", 200

    return "OK", 200
 wątek_zegara = threading.Thread(target=pętla_zegara_radiowego, daemon=True)
    wątek_zegara.start()
if __name__ == '__main__':
   
    
    app.run(host='0.0.0.0', port=5000)
