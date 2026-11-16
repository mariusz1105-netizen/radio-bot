import os
import re
import json
import time
import threading
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request
import paramiko
import requests
import yt_dlp
import asyncio
import edge_tts
from pydub import AudioSegment

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

STREFA_EUROPA = ZoneInfo("Europe/Warsaw")

# Koncert życzeń: czwartki i piątki w godzinach 18:00 - 20:00
KONCERT_ZYCZEN_DNI = (3, 4)  # 3=Czwartek, 4=Piątek
KONCERT_ZYCZEN_START = 18
KONCERT_ZYCZEN_KONIEC = 20

# Piosenka na życzenie: od poniedziałku do piątku (co 3 godziny)
PIOSENKA_NA_ZYCZENIE_DNI = (0, 1, 2, 3, 4)
PIOSENKA_NA_ZYCZENIE_START = 8
PIOSENKA_NA_ZYCZENIE_KONIEC = 22

# Odstęp emisji dla piosenek na życzenie (co 3 godziny = 10800 sekund)
ODSTEP_EMISJI_SEKUNDY = 10800

NUMER_TEL_TEKST = "plus jeden, 812, 412, 29, siedemdziesiąt pięć"


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


async def async_generuj_edge_tts(tekst, sciezka_docelowa):
    communicate = edge_tts.Communicate(tekst, "pl-PL-ZofiaNeural")
    await communicate.save(sciezka_docelowa)


def generuj_audio_mp3(lista_kwestii, nazwa_pliku_koncowego):
    sciezka_koncowa = os.path.join(FOLDER_ROBOCZY, nazwa_pliku_koncowego)
    pliki_tymczasowe = list()
    try:
        for idx, (glos, tekst) in enumerate(lista_kwestii):
            if not tekst or not tekst.strip():
                continue
            temp_path = os.path.join(
                FOLDER_ROBOCZY, f"temp_{idx}_{nazwa_pliku_koncowego}"
            )
            asyncio.run(async_generuj_edge_tts(tekst, temp_path))
            if os.path.exists(temp_path):
                pliki_tymczasowe.append(temp_path)

        if pliki_tymczasowe:
            polaczony_segment = AudioSegment.empty()
            for temp_f in pliki_tymczasowe:
                segment = AudioSegment.from_file(temp_f)
                polaczony_segment += segment
                polaczony_segment += AudioSegment.silent(duration=500)
            
            polaczony_segment.export(sciezka_koncowa, format="mp3")
            return sciezka_koncowa
        return None
    except Exception as e:
        print(f"Blad generatora Edge TTS: {e}")
        return None
    finally:
        for temp_f in pliki_tymczasowe:
            if os.path.exists(temp_f):
                os.remove(temp_f)


def szukaj_piosenki_na_dysku_sftp(sftp, zapytanie):
    slowa_kluczowe = [s.lower() for s in re.findall(r"\w+", zapytanie) if len(s) > 2]
    if not slowa_kluczowe:
        return None

    foldery_do_sprawdzenia = (DIR_POBRANE, "radio", "italo disco", "disco polo", "muzyka mix", "muzyka klubowa", ".")
    for folder in foldery_do_sprawdzenia:
        try:
            pliki = sftp.listdir(folder)
            for plik in pliki:
                if plik.lower().endswith(".mp3"):
                    nazwa_bez_rozsz = plik.lower()
                    if all(slowo in nazwa_bez_rozsz for slowo in slowa_kluczowe):
                        return f"{folder}/{plik}" if folder != "." else plik
        except Exception:
            continue
    return None


def pobierz_piosenke_z_sieci(zapytanie, nazwa_docelowa_bez_rozsz):
    sciezka_wyjsciowa = os.path.join(FOLDER_ROBOCZY, nazwa_docelowa_bez_rozsz)
    warianty_zapytan = [
        f"ytsearch1:{zapytanie} audio",
        f"ytsearch1:{zapytanie} piosenka",
        f"ytsearch1:{zapytanie}",
    ]
    opcje_ytdlp = {
        "format": "bestaudio/best",
        "outtmpl": f"{sciezka_wyjsciowa}.%(ext)s",
        "noplaylist": True,
        "quiet": True,
        "socket_timeout": 25,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }
    for query in warianty_zapytan:
        try:
            with yt_dlp.YoutubeDL(opcje_ytdlp) as ydl:
                ydl.download([query])
            gotowy_plik = f"{sciezka_wyjsciowa}.mp3"
            if os.path.exists(gotowy_plik):
                return gotowy_plik
        except Exception:
            continue
    return None


def wczytaj_kolejke_sftp(sftp):
    lokalny_json = os.path.join(FOLDER_ROBOCZY, "temp_kolejka.json")
    try:
        sftp.get(PLIK_KOLEJKA_ZDALNY, lokalny_json)
        with open(lokalny_json, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return list()
    finally:
        if os.path.exists(lokalny_json):
            os.remove(lokalny_json)


def zapisz_kolejke_sftp(sftp, lista_kolejki):
    lokalny_json = os.path.join(FOLDER_ROBOCZY, "temp_kolejka.json")
    try:
        with open(lokalny_json, "w", encoding="utf-8") as f:
            json.dump(lista_kolejki, f, ensure_ascii=False, indent=2)
        sftp.put(lokalny_json, PLIK_KOLEJKA_ZDALNY)
    except Exception as e:
        print(f"Blad zapisu kolejki: {e}")
    finally:
        if os.path.exists(lokalny_json):
            os.remove(lokalny_json)


def inteligentna_korekta(tekst):
    t = tekst.lower()
    slownik_poprawek = {
        "zeby": "żeby", "zyczenia": "życzenia", "zycze": "życzę", "zyczymy": "życzymy",
        "pozdrowienia": "pozdrowienia", "pozdrawiam": "pozdrawiam", "dzien": "dzień",
        "urodziny": "urodziny", "dziekuje": "dziękuję", "sie": "się", "ze": "że", "dzis": "dziś"
    }
    poprawione = [slownik_poprawek.get(s.strip(".,!?"), s) for s in t.split()]
    return " ".join(poprawione)


def daj_gatunek_na_godzine(godzina):
    if 18 <= godzina < 20:
        return "Wielkim Koncercie Życzeń"
    elif 8 <= godzina < 18:
        return "Piosence na Życzenie oraz najlepszych hitach"
    elif 6 <= godzina < 14:
        return "najlepszych rytmach Disco Polo i dance"
    elif 14 <= godzina < 22:
        return "najlepszym Italo Disco, Eurodance oraz klubowych bitach"
    else:
        return "nocnym, klubowym miksie muzycznym"


def zbuduj_zapowiedz_godzinowa(docelowa_godzina_24h, faza="poczatek"):
    gatunek = daj_gatunek_na_godzine(docelowa_godzina_24h)
    
    if faza == "srodek":
        return [
            ("glos", "Słuchacie Radia Strefa Zero! Jesteśmy w stałym paśmie muzycznym."),
            ("glos", f"Przypominam o naszym darmowym numerze SMS na pozdrowienia i zamówienia: {NUMER_TEL_TEKST}. Zostańcie z nami!")
        ]
    elif faza == "koniec":
        return [
            ("glos", "To już finał tego bloku godzinowego w Radiu Strefa Zero."),
            ("glos", f"Chcesz zadedykować piosenkę bliskiej osobie? Wyślij SMS na numer {NUMER_TEL_TEKST}. Za chwilę wracamy z muzyką!")
        ]
    else:
        # Propozycje nowych cyklicznych zapowiedzi i reklam stacji
        warianty_poczatek = [
            [
                ("glos", f"Radio Strefa Zero! W tej godzinie zapraszam na pasmo przy {gatunek}."),
                ("glos", f"Zamawiaj utwory i wysyłaj pozdrowienia na darmowy numer telefonu: {NUMER_TEL_TEKST}.")
            ],
            [
                ("glos", "Czas na wyjątkowy kącik wspomnień i muzyczną podróż w Radiu Strefa Zero!"),
                ("glos", f"Masz ulubiony utwór z dawnych lat? Napisz do nas na numer {NUMER_TEL_TEKST} i posłuchaj go na antenie.")
            ],
            [
                ("glos", f"Witamy w Radiu Strefa Zero! Przed nami godzina pełna energii pod znakiem: {gatunek}."),
                ("glos", f"Twoje radio, Twoja muzyka. Pamiętaj o darmowym numerze SMS: {NUMER_TEL_TEKST}.")
            ]
        ]
        return random.choice(warianty_poczatek)


def przetworz_sms_w_tle(tresc_sms, numer_nadawcy):
    transport = None
    sftp = None
    try:
        transport, sftp = polacz_sftp()
        teraz = datetime.now(STREFA_EUROPA)
        znacznik_czasu = teraz.strftime("%Y%m%d_%H%M%S")
        t_low = tresc_sms.lower()

        if "koncert" in t_low:
            typ_audycji = "koncert"
            czysta_tresc = re.sub(r"(?i)^koncert\s*życzeń[:\-\s]|^koncert\s*zyczen[:\-\s]", "", tresc_sms).strip()
        else:
            typ_audycji = "piosenka"
            czysta_tresc = re.sub(r"(?i)^piosenka\s*na\s*życzenie[:\-\s]|^piosenka\s*na\s*zyczenie[:\-\s]", "", tresc_sms).strip()

        imie_nadawcy = "Słuchacza"
        match_podpis = re.search(r"[-–—]\s*([A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż]{2,15})", czysta_tresc)
        if match_podpis:
            imie_nadawcy = match_podpis.group(1).capitalize()

        zapytanie_muzyczne = re.sub(r"[-–—]\s*[A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż]{2,15}", "", czysta_tresc).strip()
        
        sciezka_piosenki_na_dysku = None
        if len(zapytanie_muzyczne) > 2:
            sciezka_piosenki_na_dysku = szukaj_piosenki_na_dysku_sftp(sftp, zapytanie_muzyczne)
            if not sciezka_piosenki_na_dysku:
                bezpieczna_nazwa = re.sub(r"[^a-zA-Z0-9_\-]", "", zapytanie_muzyczne)[:40] + f"_{znacznik_czasu}"
                lokalne_mp3 = pobierz_piosenke_z_sieci(zapytanie_muzyczne, bezpieczna_nazwa)
                if lokalne_mp3 and os.path.exists(lokalne_mp3):
                    zdalna_piosenka = f"{DIR_POBRANE}/{bezpieczna_nazwa}.mp3"
                    sftp.put(lokalny_mp3, zdalna_piosenka)
                    sciezka_piosenki_na_dysku = zdalna_piosenka
                    os.remove(lokalny_mp3)

        poprawiona_tresc = inteligentna_korekta(czysta_tresc)

        # Kolejność: Najpierw zapowiedź reklamy/zamówienia, podanie numeru tel, a potem muzyka
        if typ_audycji == "koncert":
            kwestie_audio = [
                ("glos", f"Uwaga! Specjalne zgłoszenie do naszego Koncertu Życzeń przesłał {imie_nadawcy}."),
                ("glos", f"Oto treść wiadomości: {poprawiona_tresc}."),
                ("glos", f"Chcesz dołączyć do zabawy? Wyślij darmowy SMS na nasz numer: {NUMER_TEL_TEKST}. Gramy dalej w Radiu Strefa Zero!")
            ]
        else:
            kwestie_audio = [
                ("glos", f"Mamy nową Piosenkę na Życzenie od słuchacza: {imie_nadawcy}."),
                ("glos", f"Treść pozdrowień: {poprawiona_tresc}."),
                ("glos", f"Zamawiaj kolejne utwory pod darmowym numerem: {NUMER_TEL_TEKST}. Słuchaj Radia Strefa Zero!")
            ]

        nazwa_glosu = f"wiadomosc_{znacznik_czasu}.mp3"
        lokalny_glos = generuj_audio_mp3(kwestie_audio, nazwa_glosu)
        
        if lokalny_glos and os.path.exists(lokalny_glos):
            zdalny_glos = f"{DIR_MAGAZYN}/{nazwa_glosu}"
            sftp.put(lokalny_glos, zdalny_glos)
            os.remove(lokalny_glos)

        kolejka = wczytaj_kolejke_sftp(sftp)
        nowy_wpis = dict(
            audycja=typ_audycji,
            czas_zgloszenia=time.time(),
            plik_glos=zdalny_glos,
            plik_piosenka=sciezka_piosenki_na_dysku,
        )
        kolejka.append(nowy_wpis)
        zapisz_kolejke_sftp(sftp, kolejka)
    except Exception as e:
        print(f"Blad przetwarzania SMS w tle: {e}")
    finally:
        if sftp:
            sftp.close()
        if transport:
            transport.close()


@app.route("/sms", methods=["POST"])
def webhook_sms():
    tresc_sms = request.form.get("Body", "").strip()
    numer_nadawcy = request.form.get("From", "").strip()
    if tresc_sms:
        watek = threading.Thread(target=przetworz_sms_w_tle, args=(tresc_sms, numer_nadawcy))
        watek.start()
    return "<Response></Response>", 200


def petla_zegara_i_emisji():
    ostatnia_zapowiedziana_godzina = -1
    ostatnia_e_timestamp = 0
    ostatnia_generowana_faza = ""

    while True:
        try:
            teraz = datetime.now(STREFA_EUROPA)
            obecny_ts = time.time()

            czas_przyszly = teraz + timedelta(minutes=10)
            docelowa_godzina = czas_przyszly.hour
            minuta_teraz = teraz.minute
            godzina_teraz = teraz.hour

            # Generowanie zapowiedzi o pełnych godzinach
            if czas_przyszly.minute <= 3 and docelowa_godzina != ostatnia_zapowiedziana_godzina:
                transport, sftp = polacz_sftp()
                try:
                    nazwa_pliku = f"godzina_{czas_przyszly.strftime('%Y%m%d_%H%M%S')}.mp3"
                    sciezka = generuj_audio_mp3(zbuduj_zapowiedz_godzinowa(docelowa_godzina, faza="poczatek"), nazwa_pliku)
                    if sciezka and os.path.exists(sciezka):
                        sftp.put(sciezka, f"{DIR_JINGLES}/{nazwa_pliku}")
                        os.remove(sciezka)
                finally:
                    sftp.close()
                    transport.close()
                ostatnia_zapowiedziana_godzina = docelowa_godzina

            # Wstawki w połowie godziny (minuta 30)
            faza_klucz_srodek = f"{godzina_teraz}_30"
            if minuta_teraz == 30 and ostatnia_generowana_faza != faza_klucz_srodek:
                transport, sftp = polacz_sftp()
                try:
                    nazwa_pliku_srodek = f"srodek_{teraz.strftime('%Y%m%d_%H%M%S')}.mp3"
                    sciezka_srodek = generuj_audio_mp3(zbuduj_zapowiedz_godzinowa(godzina_teraz, faza="srodek"), nazwa_pliku_srodek)
                    if sciezka_srodek and os.path.exists(sciezka_srodek):
                        sftp.put(sciezka_srodek, f"{DIR_JINGLES}/{nazwa_pliku_srodek}")
                        os.remove(sciezka_srodek)
                finally:
                    sftp.close()
                    transport.close()
                ostatnia_generowana_faza = faza_klucz_srodek

            # Sprawdzanie audycji na życzenie (Koncert / Piosenka na życzenie) z zachowaniem odstępu
            dzien = teraz.weekday()
            godzina = teraz.hour

            if dzien in KONCERT_ZYCZEN_DNI and KONCERT_ZYCZEN_START <= godzina < KONCERT_ZYCZEN_KONIEC:
                aktywna_audycja = "koncert"
            elif dzien in PIOSENKA_NA_ZYCZENIE_DNI and PIOSENKA_NA_ZYCZENIE_START <= godzina < PIOSENKA_NA_ZYCZENIE_KONIEC:
                aktywna_audycja = "piosenka"
            else:
                aktywna_audycja = None

            if aktywna_audycja and (obecny_ts - ostatnia_e_timestamp >= ODSTEP_EMISJI_SEKUNDY):
                transport, sftp = polacz_sftp()
                try:
                    kolejka = wczytaj_kolejke_sftp(sftp)
                    paczka = next((el for el in kolejka if el.get("audycja") == aktywna_audycja), None)
                    if paczka:
                        nazwa_glos = os.path.basename(paczka.get("plik_glos"))
                        sftp.rename(paczka.get("plik_glos"), f"{DIR_JINGLES}/{nazwa_glos}")
                        if paczka.get("plik_piosenka"):
                            lokalny_temp_utwor = os.path.join(FOLDER_ROBOCZY, "emisja_utwor.mp3")
                            sftp.get(paczka.get("plik_piosenka"), lokalny_temp_utwor)
                            sftp.put(lokalny_temp_utwor, f"{DIR_JINGLES}/wiadomosc_utwor_{int(obecny_ts)}.mp3")
                            if os.path.exists(lokalny_temp_utwor):
                                os.remove(lokalny_temp_utwor)
                        kolejka.remove(paczka)
                        zapisz_kolejke_sftp(sftp, kolejka)
                        ostatnia_e_timestamp = obecny_ts
                finally:
                    sftp.close()
                    transport.close()

        except Exception as e:
            print(f"Błąd w pętli głównej zegara: {e}")
        
        time.sleep(15)


# AUTOMATYCZNY START WĄTKU (działa również poprawnie przy starcie aplikacji)
if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or os.environ.get("RENDER") or True:
    watek_tlo = threading.Thread(target=petla_zegara_i_emisji, daemon=True)
    watek_tlo.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
