from gtts import gTTS
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request
import os
import re
import threading
import time
import paramiko

app = Flask(__name__)

FOLDER_AUDIO = "nagrania_sms"
if not os.path.exists(FOLDER_AUDIO):
    os.makedirs(FOLDER_AUDIO)

PLIK_BRAKUJACE = "brakujace_piosenki.txt"

# --- CONFIG SFTP AZURACAST (Bezpośrednie połączenie z pominięciem Cloudflare) ---
SFTP_HOST = os.environ.get("SFTP_HOST", "65.108.225.39")
SFTP_PORT = int(os.environ.get("SFTP_PORT", 2022))
SFTP_USER = os.environ.get("SFTP_USER", "radio-bot")
SFTP_PASS = os.environ.get("SFTP_PASS", "")

STREFA_EUROPA = ZoneInfo("Europe/Warsaw")

def wyslij_do_azuracast(sciezka_pliku_mp3):
    """Wysyła plik MP3 bezpośrednio na dysk radia przez SFTP omijając blokady sieciowe"""
    nazwa_pliku = os.path.basename(sciezka_pliku_mp3)
    sciezka_zdalna = f"jingles/{nazwa_pliku}"
    
    transport = None
    sftp = None
    try:
        transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        transport.connect(username=SFTP_USER, password=SFTP_PASS)
        sftp = paramiko.SFTPClient.from_transport(transport)
        
        sftp.put(sciezka_pliku_mp3, sciezka_zdalna)
        print(f"[SFTP AZURACAST] Sukces! Plik {nazwa_pliku} został wgrany do folderu jingles.")
        return True, f"Sukces SFTP: {nazwa_pliku}"
    except Exception as e:
        info_blad = f"Błąd SFTP: {str(e)}"
        print(f"[SFTP BŁĄD] {info_blad}")
        return False, info_blad
    finally:
        if sftp:
            sftp.close()
        if transport:
            transport.close()

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

def pętla_zegara_radiowego():
    ostatnia_zapowiedziana_godzina = -1
    while True:
        teraz = datetime.now(STREFA_EUROPA)
        if teraz.minute == 0 and teraz.hour != ostatnia_zapowiedziana_godzina:
            wyswietlana_godzina = 24 if teraz.hour == 0 else teraz.hour
            
            tekst_wiadomosci = "Na antenie Radio Strefa Zero gramy dla Was najlepsze klubowe kawałki bez przerwy! "

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
        
        tekst_wiadomosci = "Na antenie Radio Strefa Zero gramy dla Was najlepsze klubowe kawałki bez przerwy! "
        
        komunikat_godzinowy = (
            f"Radio Strefa Zero. Wybiła godzina {wyswietlana_godzina}. "
            f"{tekst_wiadomosci} "
            "Chcesz wziąć udział w Koncercie Życzeń, zamówić ulubioną piosenkę lub przesłać pozdrowienia dla bliskich? "
            "Napisz SMS na naszą linię pod numer: plus jeden, osiemset dwanaście, czterysta dwanaście, dwadzieścia dziewięć siedemdziesiąt pięć!"
        )
        
        sciezka_pliku = zapisz_tekst_jako_mp3(komunikat_godzinowy)
        if sciezka_pliku and os.path.exists(sciezka_pliku):
            wynik_wysylki, powod_statusu = wyslij_do_azuracast(sciezka_pliku)
            if os.path.exists(sciezka_pliku):
                os.remove(sciezka_pliku)
            if wynik_wysylki:
                return {"status": "success", "message": f"Wygenerowano zapowiedz dla godziny {wyswietlana_godzina}. {powod_statusu}"}, 200
            else:
                return {"status": "error", "message": f"Problem z przesylaniem: {powod_statusu}"}, 500
        else:
            return {"status": "error", "message": "Nie udalo sie stworzyc MP3"}, 500
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

@app.route('/', methods=['GET'])
def strona_startowa():
    return {"status": "online", "message": "Radio-bot dziala poprawnie"}, 200

if __name__ == '__main__':
    watek_zegar = threading.Thread(target=pętla_zegara_radiowego, daemon=True)
    watek_zegar.start()
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
