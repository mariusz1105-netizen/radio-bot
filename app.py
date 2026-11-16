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
import feedparser
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

# Koncert życzeń: Poniedziałek - Piątek, od 17:00 do 19:00
KONCERT_ZYCZEN_DNI = (0, 1, 2, 3, 4)
KONCERT_ZYCZEN_START = 17
KONCERT_ZYCZEN_KONIEC = 19

# Piosenka na życzenie: Piątek - Niedziela, od 17:00 do 21:00
PIOSENKA_NA_ZYCZENIE_DNI = (4, 5, 6)
PIOSENKA_NA_ZYCZENIE_START = 17
PIOSENKA_NA_ZYCZENIE_KONIEC = 21

# Serwis informacyjny z RMF FM: Każdy dzień (poniedziałek - niedziela), od 6:00 do 16:00
INFO_RMF_DNI = (0, 1, 2, 3, 4, 5, 6)
INFO_RMF_START = 6
INFO_RMF_KONIEC = 16

# Odstęp emisji dla piosenek na życzenie (co 1 godzinę / 3600 sekund)
ODSTEP_EMISJI_SEKUNDY = 3600

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


def pobierz_aktualne_newsy_rmf():
    teraz = datetime.now(STREFA_EUROPA)
    if teraz.weekday() in INFO_RMF_DNI and INFO_RMF_START <= teraz.hour < INFO_RMF_KONIEC:
        try:
            url_rss = "https://www.rmf24.pl/fakty/rss"
            feed = feedparser.parse(url_rss)
            newsy = []
            if feed.entries:
                for entry in feed.entries[:2]:
                    tytul = entry.get("title", "").strip()
                    if tytul:
                        newsy.append(tytul)
            if newsy:
                return "Najświeższe informacje z RMF FM: " + ". ".join(newsy) + "."
        except Exception as e:
            print(f"Błąd pobierania newsów RMF: {e}")
    return ""


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
    baza_nazwy = os.path.join(FOLDER_ROBOCZY, nazwa_docelowa_bez_rozsz)
    
    warianty_zapytan = [
        f"ytsearch1:{zapytanie} audio",
        f"ytsearch1:{zapytanie} piosenka",
        f"ytsearch1:{zapytanie}",
    ]
    
    opcje_ytdlp = {
        "format": "bestaudio/best",
        "outtmpl": f"{baza_nazwy}.%(ext)s",
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
            
            gotowy_plik = f"{baza_nazwy}.mp3"
            if os.path.exists(gotowy_plik) and os.path.getsize(gotowy_plik) > 10000:
                return gotowy_plik
        except Exception as e:
            print(f"Błąd pobierania yt-dlp dla zapytania '{query}': {e}")
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
        "pozdrowienia": "pozdrowienia", "pozdro": "pozdrowienia", "pozdrawiam": "pozdrawiam",
        "dzien": "dzień", "urodziny": "urodziny", "imieniny": "imieniny", "dziekuje": "dziękuję",
        "dzieki": "dzięki", "sie": "się", "ze": "że", "dzis": "dziś", "tez": "też",
        "wogole": "w ogóle", "narazie": "na razie", "najlepszego": "najlepszego",
        "caluski": "całuski", "pozdrowionka": "pozdrowionka", "muzyczka": "muzyczka",
        "piosenka": "piosenka", "utworek": "utworek", "graj": "graj", "zagraj": "zagraj"
    }
    poprawione = [slownik_poprawek.get(s.strip(".,!?"), s) for s in t.split()]
    return " ".join(poprawione)


def zbuduj_tylko_godzine(docelowa_godzina_24h):
    slownik_godzin = {
        0: "północ", 1: "pierwsza w nocy", 2: "druga w nocy", 3: "trzecia w nocy", 
        4: "czwarta w nocy", 5: "piąta rano", 6: "szósta rano", 7: "siódma rano", 
        8: "ósma rano", 9: "dziewiąta", 10: "dziesiąta", 11: "jedenasta",
        12: "dwunasta", 13: "trzynasta", 14: "czternasta", 15: "piętnasta", 
        16: "szesnasta", 17: "siedemnasta", 18: "osiemnasta", 19: "dziewiętnasta", 
        20: "dwudziesta", 21: "dwudziesta pierwsza", 22: "dwudziesta druga", 
        23: "dwudziesta trzecia"
    }
    godzina_slownie = slownik_godzin.get(docelowa_godzina_24h, f"godzina {docelowa_godzina_24h}")
    return [
        ("glos", f"Jest godzina {godzina_slownie}.")
    ]


def zbuduj_informacje_rmf():
    newsy_rmf = pobierz_aktualne_newsy_rmf()
    if not newsy_rmf:
        return None
    return [
        ("glos", "Serwis informacyjny Radia Strefa Zero."),
        ("glos", newsy_rmf),
        ("glos", f"Słuchaj Radia Strefa Zero. Przypominam darmowy numer SMS: {NUMER_TEL_TEKST}.")
    ]


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
        else:
            typ_audycji = "piosenka"

        # Czyszczenie ze zwrotów instrukcyjnych
        czysta_tresc = tresc_sms
        wzorce_do_wyciecia = [
            r"(?i)^koncert\s*życzeń[:\-\s]*",
            r"(?i)^koncert\s*zyczen[:\-\s]*",
            r"(?i)^piosenka\s*na\s*życzenie[:\-\s]*",
            r"(?i)^piosenka\s*na\s*zyczenie[:\-\s]*",
            r"(?i)wyślij\s*sms[^\.\,\!][\.\,\!\s]",
            r"(?i)zamów\s*piosenkę[^\.\,\!][\.\,\!\s]",
            r"(?i)zamow\s*piosenke[^\.\,\!][\.\,\!\s]"
        ]
        for wzorzec in wzorce_do_wyciecia:
            czysta_tresc = re.sub(wzorzec, "", czysta_tresc)
        
        czysta_tresc = czysta_tresc.strip()

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

        if typ_audycji == "koncert":
            kwestie_audio = [
                ("glos", f"Mamy nowe zgłoszenie do Koncertu Życzeń od słuchacza: {imie_nadawcy}."),
                ("glos", f"Treść wiadomości: {poprawiona_tresc}."),
                ("glos", f"Chcesz dołączyć do zabawy? Wyślij darmowy SMS na nasz numer: {NUMER_TEL_TEKST}. Gramy dalej w Radiu Strefa Zero!")
            ]
        else:
            kwestie_audio = [
                ("glos", f"Nowa Piosenka na Życzenie od: {imie_nadawcy}."),
                ("glos", f"Pozdrowienia: {poprawiona_tresc}."),
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


@app.route("/generuj-godzine", methods=["GET"])
def test_generuj_godzine():
    try:
        teraz = datetime.now(STREFA_EUROPA)
        docelowa_godzina = teraz.hour
        nazwa_pliku = f"godzina_{teraz.strftime('%Y%m%d_%H%M%S')}.mp3"
        
        sciezka = generuj_audio_mp3(zbuduj_tylko_godzine(docelowa_godzina), nazwa_pliku)
        
        if sciezka and os.path.exists(sciezka):
            transport, sftp = polacz_sftp()
            try:
                sftp.put(sciezka, f"{DIR_JINGLES}/{nazwa_pliku}")
            finally:
                sftp.close()
                transport.close()
            os.remove(sciezka)
            return f"Sukces! Wygenerowano i wysłano zapowiedź godziny: {nazwa_pliku}", 200
        return "Błąd generowania pliku audio przez Edge TTS", 500
    except Exception as e:
        return f"Błąd endpointu: {e}", 500


def petla_zegara_i_emisji():
    ostatnia_zapowiedziana_godzina = -1
    ostatnia_e_timestamp = 0
    ostatnie_czyszczenie_ts = 0

    while True:
        try:
            teraz = datetime.now(STREFA_EUROPA)
            obecny_ts = time.time()

            # Czyszczenie starych plików z jingles (starsze niż 2 godziny)
            if obecny_ts - ostatnie_czyszczenie_ts > 1800:
                transport, sftp = polacz_sftp()
                try:
                    for plik in sftp.listdir(DIR_JINGLES):
                        if plik.endswith(".mp3"):
                            sciezka_pliku = f"{DIR_JINGLES}/{plik}"
                            try:
                                attr = sftp.stat(sciezka_pliku)
                                if obecny_ts - attr.st_mtime > 7200:
                                    sftp.remove(sciezka_pliku)
                            except Exception:
                                pass
                except Exception as e:
                    print(f"Błąd czyszczenia starych plików: {e}")
                finally:
                    sftp.close()
                    transport.close()
                    ostatnie_czyszczenie_ts = obecny_ts

            # Generowanie zapowiedzi godziny oraz info z 20-minutowym wyprzedzeniem
            czas_przyszly = teraz + timedelta(minutes=20)
            docelowa_godzina = czas_przyszly.hour

            if czas_przyszly.minute <= 2 and docelowa_godzina != ostatnia_zapowiedziana_godzina:
                transport, sftp = polacz_sftp()
                try:
                    nazwa_pliku_godzina = f"godzina_{czas_przyszly.strftime('%Y%m%d_%H%M%S')}.mp3"
                    sciezka_g = generuj_audio_mp3(zbuduj_tylko_godzine(docelowa_godzina), nazwa_pliku_godzina)
                    if sciezka_g and os.path.exists(sciezka_g):
                        sftp.put(sciezka_g, f"{DIR_JINGLES}/{nazwa_pliku_godzina}")
                        os.remove(sciezka_g)
                        print(f"Wysłano plik godziny: {nazwa_pliku_godzina}")

                    if INFO_RMF_START <= docelowa_godzina < INFO_RMF_KONIEC:
                        kwestie_info = zbuduj_informacje_rmf()
                        if kwestie_info:
                            nazwa_pliku_info = f"info_{czas_przyszly.strftime('%Y%m%d_%H%M%S')}.mp3"
                            sciezka_i = generuj_audio_mp3(kwestie_info, nazwa_pliku_info)
                            if sciezka_i and os.path.exists(sciezka_i):
                                sftp.put(sciezka_i, f"{DIR_JINGLES}/{nazwa_pliku_info}")
                                os.remove(sciezka_i)
                                print(f"Wysłano plik info: {nazwa_pliku_info}")
                finally:
                    sftp.close()
                    transport.close()
                
                ostatnia_zapowiedziana_godzina = docelowa_godzina

            # Sprawdzanie audycji na życzenie według harmonogramu
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
                        lokalny_glos = os.path.join(FOLDER_ROBOCZY, "temp_glos.mp3")
                        lokalny_utwor = os.path.join(FOLDER_ROBOCZY, "temp_utwor.mp3")
                        lokalna_wspolna = os.path.join(FOLDER_ROBOCZY, f"emisja_razem_{int(obecny_ts)}.mp3")
                        
                        try:
                            # Pobieramy plik z głosem lektora z SFTP
                            sftp.get(paczka.get("plik_glos"), lokalny_glos)
                            audio_calosc = AudioSegment.from_file(lokalny_glos)
                            
                            # Sklejamy z piosenką (jeden nierozerwalny plik mp3)
                            if paczka.get("plik_piosenka"):
                                sftp.get(paczka.get("plik_piosenka"), lokalny_utwor)
                                audio_utwor = AudioSegment.from_file(lokalny_utwor)
                                audio_calosc += AudioSegment.silent(duration=500) + audio_utwor
                            
                            audio_calosc.export(lokalna_wspolna, format="mp3")
                            
                            # Wysyłamy jeden gotowy plik do jingles
                            nazwa_docelowa = f"duet_{int(obecny_ts)}.mp3"
                            sftp.put(lokalna_wspolna, f"{DIR_JINGLES}/{nazwa_docelowa}")
                            print(f"Wyemitowano połączony plik życzeń: {nazwa_docelowa}")
                            
                        except Exception as inner_e:
                            print(f"Błąd sklejania audio do emisji: {inner_e}")
                        finally:
                            for f_temp in [lokalny_glos, lokalny_utwor, lokalna_wspolna]:
                                if os.path.exists(f_temp):
                                    os.remove(f_temp)

                        kolejka.remove(paczka)
                        zapisz_kolejke_sftp(sftp, kolejka)
                        ostatnia_e_timestamp = obecny_ts
                finally:
                    sftp.close()
                    transport.close()

        except Exception as e:
            print(f"Błąd w pętli głównej zegara: {e}")
        
        time.sleep(15)


if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or os.environ.get("RENDER") or True:
    watek_tlo = threading.Thread(target=petla_zegara_i_emisji, daemon=True)
    watek_tlo.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
