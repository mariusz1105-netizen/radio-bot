from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request
import os
import re
import threading
import time
import asyncio
import paramiko
import edge_tts
import feedparser

app = Flask(__name__)

FOLDER_AUDIO = "nagrania_sms"
if not os.path.exists(FOLDER_AUDIO):
    os.makedirs(FOLDER_AUDIO)

PLIK_BRAKUJACE = "brakujace_piosenki.txt"

SFTP_HOST = os.environ.get("SFTP_HOST", "65.108.225.39")
SFTP_PORT = int(os.environ.get("SFTP_PORT", 2022))
SFTP_USER = os.environ.get("SFTP_USER", "radio-bot")
SFTP_PASS = os.environ.get("SFTP_PASS", "")

GLOS_KOBIETA = "pl-PL-ZofiaNeural"
GLOS_MEZCZYZNA = "pl-PL-MarekNeural"

STREFA_EUROPA = ZoneInfo("Europe/Warsaw")

async def _generuj_segment_async(tekst, glos, plik_wyjsciowy):
    communicate = edge_tts.Communicate(tekst, glos)
    await communicate.save(plik_wyjsciowy)

def generuj_audio_mp3(lista_kwestii, nazwa_pliku_koncowego):
    sciezka_koncowa = os.path.join(FOLDER_AUDIO, nazwa_pliku_koncowego)
    pliki_tymczasowe = []
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        for idx, (glos, tekst) in enumerate(lista_kwestii):
            if not tekst or not tekst.strip():
                continue
            temp_path = os.path.join(FOLDER_AUDIO, f"temp_{idx}_{nazwa_pliku_koncowego}")
            loop.run_until_complete(_generuj_segment_async(tekst, glos, temp_path))
            if os.path.exists(temp_path):
                pliki_tymczasowe.append(temp_path)
        loop.close()
        if pliki_tymczasowe:
            with open(sciezka_koncowa, 'wb') as outfile:
                for temp_f in pliki_tymczasowe:
                    with open(temp_f, 'rb') as infile:
                        outfile.write(infile.read())
            return sciezka_koncowa
        return None
    except Exception as e:
        print(f"Błąd TTS: {e}")
        return None
    finally:
        for temp_f in pliki_tymczasowe:
            if os.path.exists(temp_f):
                os.remove(temp_f)

def wyslij_do_azuracast(sciezka_pliku_mp3, czy_godzina=False):
    nazwa_pliku = os.path.basename(sciezka_pliku_mp3)
    sciezka_zdalna = f"jingles/{nazwa_pliku}"
    transport = None
    sftp = None
    try:
        transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        transport.connect(username=SFTP_USER, password=SFTP_PASS)
        sftp = paramiko.SFTPClient.from_transport(transport)
        if czy_godzina:
            try:
                for stary_plik in sftp.listdir("jingles"):
                    if stary_plik.startswith("godzina_") and stary_plik.endswith(".mp3"):
                        sftp.remove(f"jingles/{stary_plik}")
            except Exception as clean_err:
                print(f"Info czyszczenia: {clean_err}")
        sftp.put(sciezka_pliku_mp3, sciezka_zdalna)
        return True, f"Sukces SFTP: {nazwa_pliku}"
    except Exception as e:
        return False, f"Błąd SFTP: {str(e)}"
    finally:
        if sftp:
            sftp.close()
        if transport:
            transport.close()

def pobierz_wiadomosci_rss():
    url_rss = "https://rmf24.pl"
    try:
        feed = feedparser.parse(url_rss)
        if feed.entries:
            naglowki = []
            for wpis in feed.entries[:3]:
                tytul = wpis.title.strip()
                if tytul:
                    naglowki.append(tytul)
            if naglowki:
                tekst = "Oto najważniejsze informacje z kraju i ze świata. "
                for i, h in enumerate(naglowki, 1):
                    tekst += f"Wiadomość numer {i}: {h}. "
                return tekst
    except Exception as e:
        print(f"Błąd RSS: {e}")
    return "Na naszej antenie gramy dla Was najlepsze przeboje bez przerwy! "

def zapisz_brakujacy_utwor(tresc_sms, numer_nadawcy):
    try:
        teraz = datetime.now(STREFA_EUROPA)
        czas_wpisu = teraz.strftime("%Y-%m-%d %H:%M:%S")
        wpis = f"[{czas_wpisu}] Od: {numer_nadawcy} | Treść: {tresc_sms}\n"
        with open(PLIK_BRAKUJACE, "a", encoding="utf-8") as f:
            f.write(wpis)
    except Exception as e:
        print(f"Błąd logów: {e}")

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
    if 6 <= godzina < 15:
        return "Najlepsze Hity Radiowe"
    if 15 <= godzina < 17:
        return "Italo Disco"
    if 17 <= godzina < 18:
        return "Piosenka na Życzenie"
    if 18 <= godzina < 20:
        return "Disco Polo"
    if 20 <= godzina < 21:
        return "Muzyka Mix"
    return "Muzyka Klubowa"

def zbuduj_zapowiedz_godzinowa(aktualna_godzina_24h):
    wyswietlana_godzina = 24 if aktualna_godzina_24h == 0 else aktualna_godzina_24h
    sekcja_wiadomosci = ""
    if 6 <= aktualna_godzina_24h <= 16:
        sekcja_wiadomosci = pobierz_wiadomosci_rss()

    reklama_ramowki = (
        "Przypominamy o naszych audycjach prowadzonych przez Zofię i Marka! "
        "Od poniedziałku do piątku od godziny siedemnastej do osiemnastej zapraszamy na Piosenkę na Życzenie. "
        "Natomiast w każdy piątek i sobotę od osiemnastej do dwudziestej gramy dla Was wielki Koncert Życzeń! "
        "Wyślij SMS pod numer: plus jeden, osiemset dwanaście, czterysta dwanaście, dwadzieścia dziewięć siedemdziesiąt pięć."
    )
    pelny_tekst = (
        f"Radio Strefa Zero. Wybiła godzina {wyswietlana_godzina}. "
        f"{sekcja_wiadomosci} "
        f"{reklama_ramowki} "
        "Wracamy do najlepszej muzyki!"
    )
    return [(GLOS_KOBIETA, pelny_tekst)]

def petla_zegara_radiowego():
    ostatnia_zapowiedziana_godzina = -1
    while True:
        try:
            teraz = datetime.now(STREFA_EUROPA)
            if teraz.minute == 0 and teraz.hour != ostatnia_zapowiedziana_godzina:
                nazwa_pliku = teraz.strftime("godzina_%Y%m%d_%H%M%S.mp3")
                kwestia = zbuduj_zapowiedz_godzinowa(teraz.hour)
                sciezka = generuj_audio_mp3(kwestia, nazwa_pliku)
                if sciezka and os.path.exists(sciezka):
                    wyslij_do_azuracast(sciezka, czy_godzina=True)
                    if os.path.exists(sciezka):
                        os.remove(sciezka)
                ostatnia_zapowiedziana_godzina = teraz.hour
        except Exception as e:
            print(f"Błąd zegara: {e}")
        time.sleep(15)

watek_zegar = threading.Thread(target=petla_zegara_radiowego, daemon=True)
watek_zegar.start()

@app.route('/sms', methods=['POST'])
def odbierz_sms():
    tresc_sms = request.form.get('Body', '')
    numer_nadawcy = request.form.get('From', 'Nieznany')
    if not czy_wiadomosc_jest_zrozumiala_i_bezpieczna(tresc_sms):
        return "OK", 200

    poprawiona_tresc = inteligentna_korekta(tresc_sms)
    zapisz_brakujacy_utwor(poprawiona_tresc, numer_nadawcy)

    teraz = datetime.now(STREFA_EUROPA)
    imie_nadawcy = "Słuchacza"
    match_podpis = re.search(r'[-–—]\s*([A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż]{2,15})', tresc_sms)
    if match_podpis:
        imie_nadawcy = match_podpis.group(1).capitalize()

    dzien_str = str(teraz.weekday())
    trwa_koncert_zyczeń = ((dzien_str == "4" or dzien_str == "5") and 18 <= teraz.hour < 20)
    trwa_piosenka_na_zyczenie = (teraz.weekday() <= 4 and 17 <= teraz.hour < 18)

    gatunek = pobierz_aktualny_gatunek_muzyczny()
    kwestie_audio = [
        (GLOS_KOBIETA, f"Szybka przerwa w muzyce w paśmie {gatunek}. Przesyłamy pozdrowienia od {imie_nadawcy}: {poprawiona_tresc}. Wracamy do grania!")
    ]

    if trwa_koncert_zyczeń:
        kwestie_audio = [
            (GLOS_KOBIETA, f"Marek, mamy nową wiadomość do naszego Koncertu Życzeń! Napisał do nas {imie_nadawcy}."),
            (GLOS_MEZCZYZNA, f"Świetnie Zofia, już przejmuję mikrofon i czytam! Oto treść wiadomości: {poprawiona_tresc}."),
            (GLOS_KOBIETA, "Dziękujemy za udział w Koncercie Życzeń! Pozdrawiamy gorąco i gramy dalej w Radiu Strefa Zero!")
        ]

    if trwa_piosenka_na_zyczenie:
        kwestie_audio = [
            (GLOS_MEZCZYZNA, f"Zofia, spójrz na naszą linię SMS. W paśmie Piosenka na Życzenie odezwał się {imie_nadawcy}."),
            (GLOS_KOBIETA, f"Już przekazuję dalej na antenę! Nasz słuchacz pisze tak: {poprawiona_tresc}."),
            (GLOS_MEZCZYZNA, "Świetny wybór! Zostajemy w klimacie Piosenki na Życzenie w Radiu Strefa Zero.")
        ]

    nazwa_pliku = teraz.strftime("wiadomosc_%Y%m%d_%H%M%S.mp3")
    sciezka = generuj_audio_mp3(kwestie_audio, nazwa_pliku)
    if sciezka and os.path.exists(sciezka):
        wyslij_do_azuracast(sciezka, czy_godzina=False)
        if os.path.exists(sciezka):
            os.remove(sciezka)

    return "OK", 200

@app.route('/generuj-godzine', methods=['GET', 'POST'])
def endpoint_generuj_godzine():
    try:
        teraz = datetime.now(STREFA_EUROPA)
        wyswietlana_godzina = 24 if teraz.hour == 0 else teraz.hour
        nazwa_pliku = teraz.strftime("godzina_%Y%m%d_%H%M%S.mp3")
        kwestia = zbuduj_zapowiedz_godzinowa(teraz.hour)
        sciezka_pliku = generuj_audio_mp3(kwestia, nazwa_pliku)
        if sciezka_pliku and os.path.exists(sciezka_pliku)
