import os
import re
import json
import time
import asyncio
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request
import paramiko
import edge_tts
import feedparser
import yt_dlp
import static_ffmpeg

static_ffmpeg.add_paths()

app = Flask(__name__)

FOLDER_ROBOCZY = "roboczy_radio"
if not os.path.exists(FOLDER_ROBOCZY):
    os.makedirs(FOLDER_ROBOCZY)

SFTP_HOST = os.environ.get("SFTP_HOST", "65.108.225.39")
SFTP_PORT = int(os.environ.get("SFTP_PORT", 2022))
SFTP_USER = os.environ.get("SFTP_USER", "radio-bot")
SFTP_PASS = os.environ.get("SFTP_PASS", "")

DIR_JINGLES = "jingles"
DIR_MAGAZYN = "magazyn_zyczen"
DIR_POBRANE = "pobrane_od_sluchaczy"
PLIK_KOLEJKA_ZDALNY = f"{DIR_MAGAZYN}/kolejka_audycji.json"
PLIK_BRAKUJACE_ZDALNY = f"{DIR_MAGAZYN}/brakujace_piosenki.txt"

GLOS_KOBIETA = "pl-PL-ZofiaNeural"
GLOS_MEZCZYZNA = "pl-PL-MarekNeural"
STREFA_EUROPA = ZoneInfo("Europe/Warsaw")

KONCERT_ZYCZEN_DNI = (4, 5)
KONCERT_ZYCZEN_START = 18
KONCERT_ZYCZEN_KONIEC = 20

PIOSENKA_NA_ZYCZENIE_DNI = (0, 1, 2, 3, 4)
PIOSENKA_NA_ZYCZENIE_START = 17
PIOSENKA_NA_ZYCZENIE_KONIEC = 18

ODSTEP_EMISJI_SEKUNDY = 420


def polacz_sftp():
    transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
    transport.connect(username=SFTP_USER, password=SFTP_PASS)
    sftp = paramiko.SFTPClient.from_transport(transport)
    for folder in (DIR_JINGLES, DIR_MAGAZYN, DIR_POBRANE):
        try:
            sftp.stat(folder)
        except IOError:
            sftp.mkdir(folder)
    return transport, sftp


async def _generuj_segment_async(tekst, glos, plik_wyjsciowy):
    communicate = edge_tts.Communicate(tekst, glos)
    await communicate.save(plik_wyjsciowy)


def generuj_audio_mp3(lista_kwestii, nazwa_pliku_koncowego):
    sciezka_koncowa = os.path.join(FOLDER_ROBOCZY, nazwa_pliku_koncowego)
    pliki_tymczasowe = []
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        for idx, (glos, tekst) in enumerate(lista_kwestii):
            if not tekst or not tekst.strip():
                continue
            temp_path = os.path.join(FOLDER_ROBOCZY, f"temp_{idx}_{nazwa_pliku_koncowego}")
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
        print(f"Blad TTS: {e}")
        return None
    finally:
        for temp_f in pliki_tymczasowe:
            if os.path.exists(temp_f):
                os.remove(temp_f)


def szukaj_piosenki_na_dysku_sftp(sftp, zapytanie):
    slowa = [s.lower() for s in re.findall(r'\w+', zapytanie) if len(s) > 2]
    if not slowa:
        return None
    foldery = (DIR_POBRANE, "radio", "italo disco", "disco polo", "muzyka mix", "muzyka klubowa", ".")
    for folder in foldery:
        try:
            for plik in sftp.listdir(folder):
                if plik.lower().endswith(".mp3"):
                    if all(sl in plik.lower() for sl in slowa):
                        return f"{folder}/{plik}" if folder != "." else plik
        except Exception:
            continue
    return None


def pobierz_piosenke_z_sieci(zapytanie, nazwa_docelowa):
    sciezka = os.path.join(FOLDER_ROBOCZY, nazwa_docelowa)
    opcje = {
        'format': 'bestaudio/best',
        'outtmpl': f"{sciezka}.%(ext)s",
        'default_search': 'ytsearch1',
        'noplaylist': True,
        'quiet': True,
        'socket_timeout': 20,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }
    try:
        with yt_dlp.YoutubeDL(opcje) as ydl:
            ydl.download([zapytanie])
        gotowy = f"{sciezka}.mp3"
        if os.path.exists(gotowy):
            return gotowy
    except Exception as e:
        print(f"Blad yt-dlp: {e}")
    return None


def zapisz_brakujacy_utwor_sftp(sftp, tresc_sms, numer_nadawcy, szukany_utwor):
    teraz = datetime.now(STREFA_EUROPA).strftime("%Y-%m-%d %H:%M:%S")
    wpis = f"[{teraz}] Od: {numer_nadawcy} | Szukano: {szukany_utwor} | SMS: {tresc_sms}\n"
    lokalny = os.path.join(FOLDER_ROBOCZY, "temp_brakujace.txt")
    try:
        try:
            sftp.get(PLIK_BRAKUJACE_ZDALNY, lokalny)
        except IOError:
            pass
        with open(lokalny, "a", encoding="utf-8") as f:
            f.write(wpis)
        sftp.put(lokalny, PLIK_BRAKUJACE_ZDALNY)
    except Exception as e:
        print(f"Blad zapisu brakujacych: {e}")
    finally:
        if os.path.exists(lokalny):
            os.remove(lokalny)


def wczytaj_kolejke_sftp(sftp):
    lokalny = os.path.join(FOLDER_ROBOCZY, "temp_kolejka.json")
    try:
        sftp.get(PLIK_KOLEJKA_ZDALNY, lokalny)
        with open(lokalny, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []
    finally:
        if os.path.exists(lokalny):
            os.remove(lokalny)


def zapisz_kolejke_sftp(sftp, lista_kolejki):
    lokalny = os.path.join(FOLDER_ROBOCZY, "temp_kolejka.json")
    try:
        with open(lokalny, "w", encoding="utf-8") as f:
            json.dump(lista_kolejki, f, ensure_ascii=False, indent=2)
        sftp.put(lokalny, PLIK_KOLEJKA_ZDALNY)
    except Exception as e:
        print(f"Blad zapisu kolejki: {e}")
    finally:
        if os.path.exists(lokalny):
            os.remove(lokalny)
def pobierz_wiadomosci_rss():
    try:
        feed = feedparser.parse("https://rmf24.pl")
        if feed.entries:
            naglowki = [w.title.strip() for w in feed.entries[:3] if w.title.strip()]
            if naglowki:
                tekst = "Oto najważniejsze informacje z kraju i ze świata. "
                for i, h in enumerate(naglowki, 1):
                    tekst += f"Wiadomość numer {i}: {h}. "
                return tekst
    except Exception as e:
        print(f"Blad RSS: {e}")
    return "Na naszej antenie gramy dla Was najlepsze przeboje bez przerwy! "


def inteligentna_korekta(tekst):
    slownik = {
        "zeby": "żeby", "zyczenia": "życzenia", "zycze": "życzę", "zyczymy": "życzymy",
        "pozdrowienia": "pozdrowienia", "pozdro": "pozdrowienia", "pozdrawiam": "pozdrawiam",
        "dzien": "dzień", "urodziny": "urodziny", "urodzin": "urodzin",
        "dziekuje": "dziękuję", "dzieki": "dzięki", "sie": "się", "ze": "że",
        "dzis": "dziś", "tez": "też", "wogole": "w ogóle", "narazie": "na razie"
    }
    return " ".join([slownik.get(s.strip(".,!?"), s) for s in tekst.lower().split()])


def czy_wiadomosc_bezpieczna(tekst):
    if not tekst or len(tekst.strip()) < 3:
        return False
    return any(l in "aąeęioóuy" for l in tekst.lower())


def zbuduj_zapowiedz_godzinowa(godzina_24h):
    wysw_godzina = 24 if godzina_24h == 0 else godzina_24h
    wiadomosci = pobierz_wiadomosci_rss() if 6 <= godzina_24h <= 16 else ""
    ramowka = (
        "Przypominamy o naszych audycjach prowadzonych przez Zofię i Marka! "
        "Aby wziąć udział, rozpocznij swój SMS od słów Koncert Życzeń lub Piosenka na Życzenie. "
        "Piosenkę na Życzenie gramy od poniedziałku do piątku od siedemnastej do osiemnastej, "
        "a wielki Koncert Życzeń w piątki i soboty od osiemnastej do dwudziestej. "
        "Wyślij SMS na nasz całkowicie darmowy numer telefonu: plus jeden, osiemset dwanaście, czterysta dwanaście, dwadzieścia dziewięć siedemdziesiąt pięć."
    )
    tekst = f"Radio Strefa Zero. Wybiła godzina {wysw_godzina}. {wiadomosci} {ramowka} Wracamy do najlepszej muzyki!"
    return [(GLOS_KOBIETA, tekst)]


def przetworz_sms_w_tle(tresc_sms, numer_nadawcy):
    transport = None
    sftp = None
    try:
        transport, sftp = polacz_sftp()
        teraz = datetime.now(STREFA_EUROPA)
        znacznik = teraz.strftime("%Y%m%d_%H%M%S")
        t_low = tresc_sms.lower()

        if "koncert" in t_low:
            typ_audycji = "koncert"
            czysta = re.sub(r'(?i)^koncert\s*życzeń[:\-\s]*|^koncert\s*zyczen[:\-\s]*', '', tresc_sms).strip()
        elif "piosenka" in t_low or "muzyka" in t_low:
            typ_audycji = "piosenka"
            czysta = re.sub(r'(?i)^piosenka\s*na\s*życzenie[:\-\s]*|^piosenka\s*na\s*zyczenie[:\-\s]*', '', tresc_sms).strip()
        else:
            typ_audycji = "piosenka"
            czysta = tresc_sms.strip()

        imie = "Słuchacza"
        match_podpis = re.search(r'[-–—]\s*([A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż]{2,15})', czysta)
        if match_podpis:
            imie = match_podpis.group(1).capitalize()

        zapytanie = re.sub(r'[-–—]\s*[A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż]{2,15}', '', czysta).strip()
        czy_piosenka = (typ_audycji == "piosenka") or any(w in t_low for w in ("piosenk", "zagraj", "utwór"))

        sciezka_piosenki = None
        if czy_piosenka and len(zapytanie) > 2:
            sciezka_piosenki = szukaj_piosenki_na_dysku_sftp(sftp, zapytanie)
            if not sciezka_piosenki:
                bezp_nazwa = re.sub(r'[^a-zA-Z0-9_\-]', '_', zapytanie)[:40] + f"_{znacznik}"
                lokalne_mp3 = pobierz_piosenke_z_sieci(zapytanie, bezp_nazwa)
                if lokalne_mp3 and os.path.exists(lokalne_mp3):
                    zdalna = f"{DIR_POBRANE}/{bezp_nazwa}.mp3"
                    sftp.put(lokalne_mp3, zdalna)
                    sciezka_piosenki = zdalna
                    os.remove(lokalne_mp3)
                else:
                    zapisz_brakujacy_utwor_sftp(sftp, tresc_sms, numer_nadawcy, zapytanie)
                    return

        poprawiona = inteligentna_korekta(czysta)
        if typ_audycji == "koncert":
            kwestie = [
                (GLOS_KOBIETA, f"Marek, mamy nową wiadomość do naszego Koncertu Życzeń! Napisał do nas {imie}."),
                (GLOS_MEZCZYZNA, f"Świetnie Zofia, już przejmuję mikrofon i czytam! Oto treść wiadomości: {poprawiona}."),
                (GLOS_KOBIETA, "Dziękujemy za udział w Koncercie Życzeń! Pozdrawiamy gorąco i gramy dalej w Radiu Strefa Zero!")
            ]
        else:
            kwestie = [
                (GLOS_MEZCZYZNA, f"Zofia, spójrz na naszą linię SMS. W paśmie Piosenka na Życzenie odezwał się {imie}."),
                (GLOS_KOBIETA, f"Już przekazuję dalej na antenę! Nasz słuchacz pisze tak: {poprawiona}."),
                (GLOS_MEZCZYZNA, "Świetny wybór! Zostajemy w klimacie Piosenki na Życzenie w Radiu Strefa Zero.")
            ]

        nazwa_glosu = f"wiadomosc_{znacznik}.mp3"
        lokalny_glos = generuj_audio_mp3(kwestie, nazwa_glosu)
        if lokalny_glos and os.path.exists(lokalny_glos):
            zdalny_glos = f"{DIR_MAGAZYN}/{nazwa_glosu}"
            sftp.put(lokalny_glos, zdalny_glos)
            os.remove(lokalny_glos)
            kolejka = wczytaj_kolejke_sftp(sftp)
            kolejka.append({
                "audycja": typ_audycji,
                "czas_zgloszenia": time.time(),
                "plik_glos": zdalny_glos,
                "plik_piosenka": sciezka_piosenki
            })
            zapisz_kolejke_sftp(sftp, kolejka)
    except Exception as e:
        print(f"Blad przetwarzania SMS: {e}")
    finally:
        if sftp:
            sftp.close()
        if transport:
            transport.close()


def petla_zegara_i_emisji():
    ostatnia_godzina = -1
    ostatnia_emisja = 0
    while True:
        try:
            teraz = datetime.now(STREFA_EUROPA)
            dzien = teraz.weekday()
            godzina = teraz.hour
            teraz_ts = time.time()

            if teraz.minute == 0 and godzina != ostatnia_godzina:
                transport, sftp = polacz_sftp()
                try:
                    for p in sftp.listdir(DIR_JINGLES):
                        if p.startswith("godzina_") and p.endswith(".mp3"):
                            sftp.remove(f"{DIR_JINGLES}/{p}")
                    nazwa = teraz.strftime("godzina_%Y%m%d_%H%M%S.mp3")
                    sciezka = generuj_audio_mp3(zbuduj_zapowiedz_godzinowa(godzina), nazwa)
                    if sciezka and os.path.exists(sciezka):
                        sftp.put(sciezka, f"{DIR_JINGLES}/{nazwa}")
                        os.remove(sciezka)
                finally:
                    sftp.close()
                    transport.close()
                ostatnia_godzina = godzina

            aktywna = None
            if dzien in KONCERT_ZYCZEN_DNI and KONCERT_ZYCZEN_START <= godzina < KONCERT_ZYCZEN_KONIEC:
                aktywna = "koncert"
            elif dzien in PIOSENKA_NA_ZYCZENIE_DNI and PIOSENKA_NA_ZYCZENIE_START <= godzina < PIOSENKA_NA_ZYCZENIE_KONIEC:
                aktywna = "piosenka"

            if aktywna and (teraz_ts - ostatnia_emisja >= ODSTEP_EMISJI_SEKUNDY):
                transport, sftp = polacz_sftp()
                try:
                    kolejka = wczytaj_kolejke_sftp(sftp)
                    paczka = next((el for el in kolejka if el.get("audycja") == aktywna), None)
                    if paczka:
                        for p in sftp.listdir(DIR_JINGLES):
                            if p.startswith("wiadomosc_") and p.endswith(".mp3"):
                                sftp.remove(f"{DIR_JINGLES}/{p}")
                        nazwa_g = os.path.basename(paczka["plik_glos"])
                        sftp.rename(paczka["plik_glos"], f"{DIR_JINGLES}/{nazwa_g}")
                        if paczka.get("plik_piosenka"):
                            lok_utwor = os.path.join(FOLDER_ROBOCZY, "emisja_utwor.mp3")
                            sftp.get(paczka["plik_piosenka"], lok_utwor)
                            sftp.put(lok_utwor, f"{DIR_JINGLES}/wiadomosc_utwor_{int(teraz_ts)}.mp3")
                            if os.path.exists(lok_utwor):
                                os.remove(lok_utwor)
                        kolejka.remove(paczka)
                        zapisz_kolejke_sftp(sftp, kolejka)
                        ostatnia_emisja = teraz_ts
                finally:
                    sftp.close()
                    transport.close()
        except Exception as e:
            print(f"Blad petli: {e}")
        time.sleep(15)


threading.Thread(target=petla_zegara_i_emisji, daemon=True).start()


@app.route('/sms', methods=['POST'])
def odbierz_sms():
    tresc = request.form.get('Body', '')
    nadawca = request.form.get('From', 'Nieznany')
    if not czy_wiadomosc_bezpieczna(tresc):
        return "OK", 200
    threading.Thread(target=przetworz_sms_w_tle, args=(tresc, nadawca), daemon=True).start()
    return "OK", 200


@app.route('/generuj-godzine', methods=['GET', 'POST'])
def endpoint_generuj_godzine():
    try:
        teraz = datetime.now(STREFA_EUROPA)
        wysw = 24 if teraz.hour == 0 else teraz.hour
        nazwa = teraz.strftime("godzina_%Y%m%d_%H%M%S.mp3")
        sciezka = generuj_audio_mp3(zbuduj_zapowiedz_godzinowa(teraz.hour), nazwa)
        if sciezka and os.path.exists(sciezka):
            transport, sftp = polacz_sftp()
            try:
                for p in sftp.listdir(DIR_JINGLES):
                    if p.startswith("godzina_") and p.endswith(".mp3"):
                        sftp.remove(f"{DIR_JINGLES}/{p}")
                sftp.put(sciezka, f"{DIR_JINGLES}/{nazwa}")
            finally:
                sftp.close()
                transport.close()
            os.remove(sciezka)
            return {"status": "success", "message": f"Wygenerowano zapowiedz dla godziny {wysw}."}, 200
