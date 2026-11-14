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


def daj_gatunek_na_godzine(godzina):
    if 18 <= godzina < 20:
        return "Wielki Koncert Życzeń"
    elif 17 <= godzina < 18:
        return "Piosenka na Życzenie"
    elif 6 <= godzina < 14:
        return "najlepsze Disco Polo"
    elif 14 <= godzina < 22:
        return "Italo Disco i energetyczne Eurodance"
    else:
        return "klubowy miks muzyczny"


def zbuduj_zapowiedz_godzinowa(docelowa_godzina_24h, faza="poczatek"):
    wyswietlana_godzina = (
        24 if docelowa_godzina_24h == 0 else docelowa_godzina_24h
    )
    gatunek_muzyki = daj_gatunek_na_godzine(docelowa_godzina_24h)

    # Poprawiony zapis numeru telefonu – słownie, żeby lektorka przeczytała go poprawnie po kawałku
    nr_tel_slownie = "plus jeden, 812, 412, 29, 75"

    if faza == "srodek":
        pelny_tekst = (
            f"Radio Strefa Zero. Jesteśmy w połowie pasma! "
            f"Teraz grają dla Was {gatunek_muzyki}. "
            f"Piszcie darmowe SMS-y z pozdrowieniami na numer: {nr_tel_slownie}. Zostajcie z nami!"
        )
        return list(((GLOS_MEZCZYZNA, pelny_tekst),))

    elif faza == "koniec":
        pelny_tekst = (
            f"To już końcówka tego bloku w Radiu Strefa Zero! "
            f"Dziękujemy za wspólne chwile. "
            f"Już za chwilę kolejna porcja muzyki Dance i następna fala zabawy! "
            f"Bądźcie z nami!"
        )
        return list(((GLOS_KOBIETA, pelny_tekst),))

    else:
        pelny_tekst = (
            f"Radio Strefa Zero. Wybiła godzina {wyswietlana_godzina}. "
            f"Przez najbliższą godzinę królują {gatunek_muzyki}! "
            f"Przypominamy o darmowym numerze SMS: {nr_tel_slownie}. "
            f"Zamawiajcie utwory i pozdrawiajcie bliskich!"
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
                if lokalne_mp3 and os.path.exists(lokalny_mp3):
                    zdalna_piosenka = f"{DIR_POBRANE}/{bezpieczna_nazwa}.mp3"
                    sftp.put(lokalny_mp3, zdalna_piosenka)
                    sciezka_piosenki_na_dysku = zdalna_piosenka
                    os.remove(lokalny_mp3)

        poprawiona_tresc = inteligentna_korekta(czysta_tresc)

        if typ_audycji == "koncert":
            kwestie_audio = (
                (
                    GLOS_KOBIETA,
                    f"Marek, zobacz co nam przysłali! Mamy nową wiadomość do naszego Koncertu Życzeń od {imie_nadawcy}.",
                ),
                (
                    GLOS_MEZCZYZNA,
                    f"Już czytam treść: {poprawiona_tresc}.",
                ),
                (
                    GLOS_KOBIETA,
                    "Pozdrawiamy i gramy dalej w Radiu Strefa Zero!",
                ),
            )
        else:
            kwestie_audio = (
                (
                    GLOS_MEZCZYZNA,
                    f"Zofia, mamy nowe zgłoszenie w paśmie Piosenka na Życzenie od {imie_nadawcy}.",
                ),
                (
                    GLOS_KOBIETA,
                    f"Oto treść wiadomości: {poprawiona_tresc}.",
                ),
                (
                    GLOS_MEZCZYZNA,
                    "Świetny wybór, lecimy z muzyką!",
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
    ostatnia_generowana_faza = ""

    while True:
        try:
            teraz = datetime.now(STREFA_EUROPA)
            
            czas_przyszly = teraz + timedelta(minutes=10)
            docelowa_godzina = czas_przyszly.hour
            minuta_teraz = teraz.minute
            godzina_teraz = teraz.hour

            if czas_przyszly.minute <= 3 and docelowa_godzina != ostatnia_zapowiedziana_godzina:
                transport, sftp = polacz_sftp()
                try:
                    nazwa_pliku = f"godzina_{czas_przyszly.strftime('%Y%m%d_%H%M%S')}.mp3"
                    sciezka = generuj_audio_mp3(
                        zbuduj_zapowiedz_godzinowa(docelowa_godzina, faza="poczatek"), nazwa_pliku
                    )
                    if sciezka and os.path.exists(sciezka):
                        sftp.put(sciezka, f"{DIR_JINGLES}/{nazwa_pliku}")
                        os.remove(sciezka)
                        
                        for stary_plik in sftp.listdir(DIR_JINGLES):
                            if stary_plik.startswith("godzina_") and stary_plik != nazwa_pliku and stary_plik.endswith(".mp3"):
                                try:
                                    sftp.remove(f"{DIR_JINGLES}/{stary_plik}")
                                except Exception:
                                    pass
                finally:
                    sftp.close()
                    transport.close()
                ostatnia_zapowiedziana_godzina = docelowa_godzina

            faza_klucz_srodek = f"{godzina_teraz}_30"
            if minuta_teraz == 30 and ostatnia_generowana_faza != faza_klucz_srodek:
                transport, sftp = polacz_sftp()
                try:
                    nazwa_pliku_srodek = f"srodek_{teraz.strftime('%Y%m%d_%H%M%S')}.mp3"
                    sciezka_srodek = generuj_audio_mp3(
                        zbuduj_zapowiedz_godzinowa(godzina_teraz, faza="srodek"), nazwa_pliku_srodek
                    )
                    if sciezka_srodek and os.path.exists(sciezka_srodek):
                        sftp.put(sciezka_srodek, f"{DIR_JINGLES}/{nazwa_pliku_srodek}")
                        os.remove(sciezka_srodek)
                finally:
                    sftp.close()
                    transport.close()
                ostatnia_generowana_faza = faza_klucz_srodek

            faza_klucz_koniec = f"{godzina_teraz}_50"
            if minuta_teraz == 50 and ostatnia_generowana_faza != faza_klucz_koniec:
                transport, sftp = polacz_sftp()
                try:
                    nazwa_pliku_koniec = f"koniec_{teraz.strftime('%Y%m%d_%H%M%S')}.mp3"
                    sciezka_koniec = generuj_audio_mp3(
                        zbuduj_zapowiedz_godzinowa(godzina_teraz, faza="koniec"), nazwa_pliku_koniec
                    )
                    if sciezka_koniec and os.path.exists(sciezka_koniec):
                        sftp.put(sciezka_koniec, f"{DIR_JINGLES}/{nazwa_pliku_koniec}")
                        os.remove(sciezka_koniec)
                finally:
                    sftp.close()
                    transport.close()
                ostatnia_generowana_faza = faza_klucz_koniec

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
            zbuduj_zapowiedz_godzinowa(teraz.hour, faza="poczatek"), nazwa_pliku
        )
        if sciezka_pliku and os.path.exists(sciezka_pliku):
            transport, sftp = polacz_sftp()
            try:
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


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
