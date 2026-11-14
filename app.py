import os
import re
import json
import time
import asyncio
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request
import paramiko
import edge_tts
import feedparser
import yt_dlp

app = Flask(_name_)

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
    pliki_tymczasowe = list()
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        for idx, (glos, tekst) in enumerate(lista_kwestii):
            if not tekst or not tekst.strip():
                continue
            temp_path = os.path.join(
                FOLDER_ROBOCZY, f"temp_{idx}_{nazwa_pliku_koncowego}"
            )
            loop.run_until_complete(
                _generuj_segment_async(tekst, glos, temp_path)
            )
            if os.path.exists(temp_path):
                pliki_tymczasowe.append(temp_path)
        loop.close()

        if pliki_tymczasowe:
            with open(sciezka_koncowa, "wb") as outfile:
                for temp_f in pliki_tymczasowe:
                    with open(temp_f, "rb") as infile:
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
    slowa_kluczowe = list()
    for s in re.findall(r"\w+", zapytanie):
        if len(s) > 2:
            slowa_kluczowe.append(s.lower())
    if not slowa_kluczowe:
        return None

    foldery_do_sprawdzenia = (
        DIR_POBRANE,
        "radio",
        "italo disco",
        "disco polo",
        "muzyka mix",
        "muzyka klubowa",
        ".",
    )
    for folder in foldery_do_sprawdzenia:
        try:
            pliki = sftp.listdir(folder)
            for plik in pliki:
                if plik.lower().endswith(".mp3"):
                    nazwa_bez_rozsz = plik.lower()
                    if all(
                        slowo in nazwa_bez_rozsz for slowo in slowa_kluczowe
                    ):
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
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    }

    for query in warianty_zapytan:
        try:
            print(f"Próbuję pobrać za pomocą zapytania: {query}")
            with yt_dlp.YoutubeDL(opcje_ytdlp) as ydl:
                ydl.download([query])
                
            gotowy_plik = f"{sciezka_wyjsciowa}.mp3"
            if os.path.exists(gotowy_plik):
                print(f"Sukces! Pobrano: {gotowy_plik}")
                return gotowy_plik
        except Exception as e:
            print(f"Próba pobrania dla '{query}' nie powiodła się: {e}")
            continue
            
    return None


def zapisz_brakujacy_utwor_sftp(sftp, tresc_sms, numer_nadawcy, szukany_utwor):
    teraz = datetime.now(STREFA_EUROPA).strftime("%Y-%m-%d %H:%M:%S")
    wpis = f"[{teraz}] Od: {numer_nadawcy} | Szukano: {szukany_utwor} | Pelny SMS: {tresc_sms}\n"
    lokalny_txt = os.path.join(FOLDER_ROBOCZY, "temp_brakujace.txt")
    try:
        try:
            sftp.get(PLIK_BRAKUJACE_ZDALNY, lokalny_txt)
        except IOError:
            pass
        with open(lokalny_txt, "a", encoding="utf-8") as f:
            f.write(wpis)
        sftp.put(lokalny_txt, PLIK_BRAKUJACE_ZDALNY)
    except Exception as e:
        print(f"Blad zapisu brakujacych na SFTP: {e}")
    finally:
        if os.path.exists(lokalny_txt):
            os.remove(lokalny_txt)


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


def pobierz_wiadomosci_rss():
    url_rss = "https://rmf24.pl"
    try:
        feed = feedparser.parse(url_rss)
        if feed.entries:
            naglowki = list()
            for wpis in feed.entries[:2]:
                if wpis.title.strip():
                    naglowki.append(wpis.title.strip())
            if naglowki:
                tekst = "Skrót wiadomości: "
                for i, h in enumerate(naglowki, 1):
                    tekst += f"{h}. "
                return tekst
    except Exception as e:
        print(f"Blad RSS: {e}")
    return ""


def inteligentna_korekta(tekst):
    t = tekst.lower()
    slownik_poprawek = {
        "zeby": "żeby",
        "zyczenia": "życzenia",
        "zycze": "życzę",
        "zyczymy": "życzymy",
        "pozdrowienia": "pozdrowienia",
        "pozdro": "pozdrowienia",
        "pozdrawiam": "pozdrawiam",
        "dzien": "dzień",
        "urodziny": "urodziny",
        "urodzin": "urodzin",
        "dziekuje": "dziękuję",
        "dzieki": "dzięki",
        "sie": "się",
        "ze": "że",
        "dzis": "dziś",
        "tez": "też",
        "wogole": "w ogóle",
        "narazie": "na razie",
    }
    poprawione = list()
    for s in t.split():
        poprawione.append(slownik_poprawek.get(s.strip(".,!?"), s))
    return " ".join(poprawione)


def czy_wiadomosc_jest_zrozumiala_i_bezpieczna(tekst):
    if not tekst or len(tekst.strip()) < 3:
        return False
    return any(l in "aąeęioóuy" for l in tekst.lower())


def zbuduj_zapowiedz_godzinowa(docelowa_godzina_24h):
    wyswietlana_godzina = (
        24 if docelowa_godzina_24h == 0 else docelowa_godzina_24h
    )
    sekcja_wiadomosci = pobierz_wiadomosci_rss()
    if not sekcja_wiadomosci:
        sekcja_wiadomosci = "Gramy dla Was najlepszą muzykę bez przerwy."

    komunikat_sms = (
        "Przypominamy o darmowym numerze SMS plus 1 812 412 2975. "
        "Piosenka na życzenie od poniedziałku do piątku od siedemnastej do osiemnastej. "
        "Wielki Koncert Życzeń w piątki i soboty od osiemnastej do dwudziestej. "
        "Zamawiajcie utwory i pozdrawiajcie bliskich!"
    )
    pelny_tekst = (
        f"Radio Strefa Zero. Wybiła godzina {wyswietlana_godzina}. "
        f"{sekcja_wiadomosci} {komunikat_sms} Zostajcie z nami!"
    )
    return list(((GLOS_KOBIETA, pelny_tekst),))


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
            czysta_tresc = re.sub(
                r"(?i)^koncert\s*życzeń[:\-\s]|^koncert\s*zyczen[:\-\s]",
                "",
                tresc_sms,
            ).strip()
        elif "piosenka" in t_low or "muzyka" in t_low:
            typ_audycji = "piosenka"
            czysta_tresc = re.sub(
                r"(?i)^piosenka\s*na\s*życzenie[:\-\s]|^piosenka\s*na\s*zyczenie[:\-\s]",
                "",
                tresc_sms,
            ).strip()
        else:
            typ_audycji = "piosenka"
            czysta_tresc = tresc_sms.strip()

        imie_nadawcy = "Słuchacza"
        match_podpis = re.search(
            r"[-–—]\s*([A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż]{2,15})", czysta_tresc
        )
        if match_podpis:
            imie_nadawcy = match_podpis.group(1).capitalize()

        zapytanie_muzyczne = re.sub(
            r"[-–—]\s*[A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż]{2,15}", "", czysta_tresc
        ).strip()
        czy_zamowiono_piosenke = (
            (typ_audycji == "piosenka")
            or ("piosenk" in t_low)
            or ("zagraj" in t_low)
            or ("utwór" in t_low)
        )

        sciezka_piosenki_na_dysku = None
        if czy_zamowiono_piosenke and len(zapytanie_muzyczne) > 2:
            sciezka_piosenki_na_dysku = szukaj_piosenki_na_dysku_sftp(
                sftp, zapytanie_muzyczne
            )
            if not sciezka_piosenki_na_dysku:
                bezpieczna_nazwa = (
                    re.sub(r"[^a-zA-Z0-9_\-]", "_", zapytanie_muzyczne)[:40]
                    + f"_{znacznik_czasu}"
                )
                lokalne_mp3 = pobierz_piosenke_z_sieci(
                    zapytanie_muzyczne, bezpieczna_nazwa
                )
                if lokalne_mp3 and os.path.exists(lokalne_mp3):
                    zdalna_piosenka = f"{DIR_POBRANE}/{bezpieczna_nazwa}.mp3"
                    sftp.put(lokalne_mp3, zdalna_piosenka)
                    sciezka_piosenki_na_dysku = zdalna_piosenka
                    os.remove(lokalne_mp3)
                else:
                    zapisz_brakujacy_utwor_sftp(
                        sftp, tresc_sms, numer_nadawcy, zapytanie_muzyczne
                    )
                    return

        poprawiona_tresc = inteligentna_korekta(czysta_tresc)

        # Dialog botów (Zofia i Marek)
        if typ_audycji == "koncert":
            kwestie_audio = (
                (
                    GLOS_KOBIETA,
                    f"Marek, zobacz co nam przysłali! Mamy nową wiadomość do naszego Koncertu Życzeń od {imie_nadawcy}.",
                ),
                (
                    GLOS_MEZCZYZNA,
                    f"O, ciekaw jestem! Już czytam treść dla naszych słuchaczy: {poprawiona_tresc}.",
                ),
                (
                    GLOS_KOBIETA,
                    "Piękne słowa. Pozdrawiamy serdecznie i gramy dalej w Radiu Strefa Zero!",
                ),
            )
        else:
            kwestie_audio = (
                (
                    GLOS_MEZCZYZNA,
                    f"Zofia, wpłynęło nowe zgłoszenie w paśmie Piosenka na Życzenie od {imie_nadawcy}.",
                ),
                (
                    GLOS_KOBIETA,
                    f"Świetnie! Słuchamy co tam autor ma do przekazania: {poprawiona_tresc}.",
                ),
                (
                    GLOS_MEZCZYZNA,
                    "Dokładnie tak, lecimy z tym kawałkiem!",
                ),
            )

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
        print(f"Dodano do kolejki: {typ_audycji}")

    except Exception as e:
        print(f"Blad przetwarzania SMS w tle: {e}")
    finally:
        if sftp:
            sftp.close()
        if transport:
            transport.close()


def petla_zegara_i_emisji():
    ostatnia_zapowiedziana_godzina = -1
    ostatnia_e_timestamp = 0
    while True:
        try:
            teraz = datetime.now(STREFA_EUROPA)
            
            czas_przyszly = teraz + timedelta(minutes=10)
            docelowa_godzina = czas_przyszly.hour
            
            if czas_przyszly.minute <= 3 and docelowa_godzina != ostatnia_zapowiedziana_godzina:
                transport, sftp = polacz_sftp()
                try:
                    for stary_plik in sftp.listdir(DIR_JINGLES):
                        if stary_plik.startswith("godzina_") and stary_plik.endswith(".mp3"):
                            sftp.remove(f"{DIR_JINGLES}/{stary_plik}")
                    
                    nazwa_pliku = f"godzina_{czas_przyszly.strftime('%Y%m%d_%H%M%S')}.mp3"
                    sciezka = generuj_audio_mp3(
                        zbuduj_zapowiedz_godzinowa(docelowa_godzina), nazwa_pliku
                    )
                    if sciezka and os.path.exists(sciezka):
                        sftp.put(sciezka, f"{DIR_JINGLES}/{nazwa_pliku}")
                        os.remove(sciezka)
                finally:
                    sftp.close()
                    transport.close()
                ostatnia_zapowiedziana_godzina = docelowa_godzina

            dzien = teraz.weekday()
            godzina = teraz.hour
            obecny_ts = time.time()

            trwa_koncert = (
                dzien in KONCERT_ZYCZEN_DNI
                and KONCERT_ZYCZEN_START <= godzina < KONCERT_ZYCZEN_KONIEC
            )
            trwa_piosenka = (
                dzien in PIOSENKA_NA_ZYCZENIE_DNI
                and PIOSENKA_NA_ZYCZENIE_START
                <= godzina
                < PIOSENKA_NA_ZYCZENIE_KONIEC
            )

            aktywna_audycja = None
            if trwa_koncert:
                aktywna_audycja = "koncert"
            elif trwa_piosenka:
                aktywna_audycja = "piosenka"

            if aktywna_audycja and (
                obecny_ts - ostatnia_e_timestamp >= ODSTEP_EMISJI_SEKUNDY
            ):
                transport, sftp = polacz_sftp()
                try:
                    kolejka = wczytaj_kolejke_sftp(sftp)
                    paczka = next(
                        (
                            el
                            for el in kolejka
                            if el.get("audycja") == aktywna_audycja
                        ),
                        None,
                    )
                    if paczka:
                        for plik_j in sftp.listdir(DIR_JINGLES):
                            if plik_j.startswith("wiadomosc_") and plik_j.endswith(".mp3"):
                                sftp.remove(f"{DIR_JINGLES}/{plik_j}")
                        nazwa_glos = os.path.basename(paczka.get("plik_glos"))
                        sftp.rename(
                            paczka.get("plik_glos"),
                            f"{DIR_JINGLES}/{nazwa_glos}",
                        )
                        if paczka.get("plik_piosenka"):
                            lokalny_temp_utwor = os.path.join(
                                FOLDER_ROBOCZY, "emisja_utwor.mp3"
                            )
                            sftp.get(
                                paczka.get("plik_piosenka"), lokalny_temp_utwor
                            )
                            sftp.put(
                                lokalny_temp_utwor,
                                f"{DIR_JINGLES}/wiadomosc_utwor_{int(obecny_ts)}.mp3",
                            )
                            if os.path.exists(lokalny_temp_utwor):
                                os.remove(lokalny_temp_utwor)
                        kolejka.remove(paczka)
                        zapisz_kolejke_sftp(sftp, kolejka)
                        ostatnia_e_timestamp = obecny_ts
                finally:
                    sftp.close()
                    transport.close()
        except Exception as e:
            print(f"Blad petli glownej: {e}")
        time.sleep(15)


watek_glowny = threading.Thread(target=petla_zegara_i_emisji, daemon=True)
watek_glowny.start()


@app.route('/')
def strona_glowna():
    return "Radio Strefa Zero Bot działa poprawnie!", 200


@app.route("/generuj-godzine", methods=["GET", "POST"])
def endpoint_generuj_godzine():
    try:
        teraz = datetime.now(STREFA_EUROPA)
        wyswietlana_godzina = 24 if teraz.hour == 0 else teraz.hour
        nazwa_pliku = teraz.strftime("godzina_%Y%m%d_%H%M%S.mp3")
        sciezka_pliku = generuj_audio_mp3(
            zbuduj_zapowiedz_godzinowa(teraz.hour), nazwa_pliku
        )
        if sciezka_pliku and os.path.exists(sciezka_pliku):
            transport, sftp = polacz_sftp()
            try:
                for stary_plik in sftp.listdir(DIR_JINGLES):
                    if stary_plik.startswith("godzina_") and stary_plik.endswith(".mp3"):
                        sftp.remove(f"{DIR_JINGLES}/{stary_plik}")
                sftp.put(sciezka_pliku, f"{DIR_JINGLES}/{nazwa_pliku}")
            finally:
                sftp.close()
                transport.close()
            os.remove(sciezka_pliku)
            return {
                "status": "success",
                "message": f"Wygenerowano zapowiedz godzinowa dla godziny {wyswietlana_godzina}.",
            }, 200
        
        return {
            "status": "error",
            "message": "Nie udalo sie stworzyc pliku MP3"
        }, 500
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route("/sms", methods=["POST"])
def sms_reply():
    tresc = request.form.get("Body", "")
    nadawca = request.form.get("From", "")
    
    print(f"Odebrano SMS od {nadawca}: {tresc}")
    
    if czy_wiadomosc_jest_zrozumiala_i_bezpieczna(tresc):
        watek_sms = threading.Thread(
            target=przetworz_sms_w_tle, args=(tresc, nadawca), daemon=True
        )
        watek_sms.start()
    
    return "<Response></Response>", 200, {'Content-Type': 'application/xml'}
