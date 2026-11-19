import asyncio
from datetime import datetime
import json
import logging
import os
import random
import re
import threading
import time
from zoneinfo import ZoneInfo

import edge_tts
import feedparser
from flask import Flask, jsonify, render_template_string, request
import paramiko
from pydub import AudioSegment, effects
from pydub.silence import detect_leading_silence
import requests
import yt_dlp

logging.basicConfig(
    filename="radio_bot.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

app = Flask(__name__)

FOLDER_ROBOCZY = "roboczy_radio"
DIR_STATIC_MUSIC = "static/music"
DIR_STATIC_OUTPUT = "static/output"
PLIK_TERMINY_REKLAM = os.path.join(FOLDER_ROBOCZY, "reklamy_terminy.json")
PLIK_GLOSOW_BITWY = os.path.join(FOLDER_ROBOCZY, "bitwa_glosy.json")

os.makedirs(FOLDER_ROBOCZY, exist_ok=True)
os.makedirs(DIR_STATIC_MUSIC, exist_ok=True)
os.makedirs(DIR_STATIC_OUTPUT, exist_ok=True)

SFTP_HOST = os.environ.get("SFTP_HOST", "65.108.225.39")
SFTP_PORT = int(os.environ.get("SFTP_PORT", 2022))
SFTP_USER = os.environ.get("SFTP_USER", "radio-bot")
SFTP_PASS = os.environ.get("SFTP_PASS", "")

AZURACAST_URL = os.environ.get("AZURACAST_URL", "https://a7.asurahosting.com").rstrip("/")
AZURACAST_API_KEY = os.environ.get("AZURACAST_API_KEY", "")
AZURACAST_STATION_ID = int(os.environ.get("AZURACAST_STATION_ID", 461))

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()

DIR_JINGLES = "jingles"
DIR_MAGAZYN = "magazyn_zyczen"
DIR_POBRANE = "pobrane_od_sluchaczy"
DIR_GODZINA = "godzina"
DIR_NEWS = "news"
DIR_KONCERT_ZYCZEN = "Koncert zyczen"
DIR_PIOSENKA_NA_ZYCZENIE = "piosenka na zyczenie"
DIR_PIOSENKI_DLA_SLUCHACZY = "piosenki dla sluchaczy"
DIR_BLOK_REKLAMOWY = "blok reklamowy"
DIR_MIXY = "mixy"
DIR_WSTAWKI_AI = "wstawki_ai"
DIR_AUDYCJE_SPECJALNE = "audycje_specjalne"

FOLDERY_GATUNKOWE = [
    "disco polo",
    "disco polo dance",
    "muzyka klubowa",
    "italo disco",
    "muzyka mix",
]

WSZYSTKIE_FOLDERY_SFTP = (
    DIR_JINGLES,
    DIR_MAGAZYN,
    DIR_POBRANE,
    DIR_GODZINA,
    DIR_NEWS,
    DIR_KONCERT_ZYCZEN,
    DIR_PIOSENKA_NA_ZYCZENIE,
    DIR_PIOSENKI_DLA_SLUCHACZY,
    DIR_BLOK_REKLAMOWY,
    DIR_MIXY,
    DIR_WSTAWKI_AI,
    DIR_AUDYCJE_SPECJALNE,
) + tuple(FOLDERY_GATUNKOWE)

STREFA_EUROPA = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Warsaw"))

INFO_RMF_DNI = (0, 1, 2, 3, 4, 5, 6)
INFO_RMF_START = 7
INFO_RMF_KONIEC = 23

NUMER_TEL_TEKST = "plus jeden, 812, 412, 29, siedemdziesiąt pięć"

PULA_BOTOW = {
    "marek_standard": {"name": "Marek (Klasyczny)", "voice": "pl-PL-MarekNeural", "pitch": -12, "rate": 0},
    "marek_bas": {"name": "Marek (Głęboki Bas)", "voice": "pl-PL-MarekNeural", "pitch": -18, "rate": -3},
    "marek_noc": {"name": "Marek (Nocny Klub)", "voice": "pl-PL-MarekNeural", "pitch": -16, "rate": 2},
    "zofia_standard": {"name": "Zofia (Prezenterka)", "voice": "pl-PL-ZofiaNeural", "pitch": -2, "rate": 0},
    "zofia_news": {"name": "Zofia (Newsy)", "voice": "pl-PL-ZofiaNeural", "pitch": 0, "rate": 4},
}

KACIK_NOSTALGII = [
    "Kącik nostalgii w Radiu Strefa Zero: niektóre melodie z lat osiemdziesiątych i dziewięćdziesiątych mają w sobie energię, której nie zastąpi żaden współczesny bit.",
    "Wracamy do złotych czasów parkietu! Italo disco i klubowa klasyka w Radiu Strefa Zero zawsze robią świetny klimat.",
]

KAWALY_TEKSTY = [
    "Przychodzi facet do lekarza i mówi: Panie doktorze, nikt mnie nie zauważa. Lekarz podnosi wzrok i mówi: Następny proszę!",
    "Dlaczego informatyk nie lubi chodzić na grzyby? Bo ma za dużo robaków i zero wsparcia technicznego.",
    "Rozmawiają dwa zegary na ścianie. Jeden mówi: Stary, strasznie szybko ten czas leci. Drugi odpowiada: Nie narzekaj, przynajmniej mamy wskazówki.",
]

KACIK_WEEKENDOWY = [
    "Weekendowy start w Radiu Strefa Zero! Podkręcamy głośność, zbijamy zmęczenie tygodnia i wjeżdżamy w imprezowy klimat!",
    "Piątek, sobota, niedziela — kiedy inni zwalniają, u nas wchodzi pełna energia i taneczne uderzenie prosto na parkiet!",
]

DOZWOLONE_SKROTY = {"DJ", "FM", "MP3", "SMS", "TV", "VIP", "AI", "URL", "API", "SFTP", "BPM"}

terminy_lock = threading.Lock()
glosy_lock = threading.Lock()


def zsynchronizuj_azuracast():
    if not AZURACAST_URL or not AZURACAST_API_KEY:
        return
    try:
        url = f"{AZURACAST_URL}/api/station/{AZURACAST_STATION_ID}/files/sync"
        headers = {"Authorization": f"Bearer {AZURACAST_API_KEY}"}
        resp = requests.post(url, headers=headers, timeout=15)
        if resp.status_code in (200, 202):
            logging.info(f"Wysłano Sync API do AzuraCast (stacja {AZURACAST_STATION_ID}).")
        else:
            logging.warning(f"Sync API AzuraCast zwrócił status {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logging.error(f"Błąd Sync API AzuraCast: {e}")


def wczytaj_terminy_reklam():
    with terminy_lock:
        if not os.path.exists(PLIK_TERMINY_REKLAM):
            return {}
        try:
            with open(PLIK_TERMINY_REKLAM, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Błąd odczytu terminów reklam: {e}")
            return {}


def zapisz_terminy_reklam(dane):
    with terminy_lock:
        try:
            with open(PLIK_TERMINY_REKLAM, "w", encoding="utf-8") as f:
                json.dump(dane, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Błąd zapisu terminów reklam: {e}")


def _wczytaj_glosy():
    with glosy_lock:
        if not os.path.exists(PLIK_GLOSOW_BITWY):
            return {"DYSKOTEKA": 0, "ITALO": 0}
        try:
            with open(PLIK_GLOSOW_BITWY, "r", encoding="utf-8") as f:
                d = json.load(f)
                return {"DYSKOTEKA": int(d.get("DYSKOTEKA", 0)), "ITALO": int(d.get("ITALO", 0))}
        except Exception:
            return {"DYSKOTEKA": 0, "ITALO": 0}


def _zapisz_glosy(dane):
    with glosy_lock:
        try:
            with open(PLIK_GLOSOW_BITWY, "w", encoding="utf-8") as f:
                json.dump(dane, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Błąd zapisu głosów bitwy: {e}")


def polacz_sftp():
    transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
    transport.connect(username=SFTP_USER, password=SFTP_PASS)
    sftp = paramiko.SFTPClient.from_transport(transport)
    for folder in WSZYSTKIE_FOLDERY_SFTP:
        try:
            sftp.stat(folder)
        except IOError:
            try:
                sftp.mkdir(folder)
            except Exception as e:
                logging.error(f"Nie udało się utworzyć folderu SFTP '{folder}': {e}")
    return transport, sftp


def wyslij_i_zsynchronizuj(sftp, lokalna_sciezka, zdalna_sciezka):
    sftp.put(lokalna_sciezka, zdalna_sciezka)
    logging.info(f"Wysłano plik przez SFTP: {zdalna_sciezka}")
    zsynchronizuj_azuracast()


def uruchom_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            nowa_petla = asyncio.new_event_loop()
            try:
                return nowa_petla.run_until_complete(coro)
            finally:
                nowa_petla.close()
        return loop.run_until_complete(coro)
    except RuntimeError:
        nowa_petla = asyncio.new_event_loop()
        try:
            return nowa_petla.run_until_complete(coro)
        finally:
            nowa_petla.close()


def _sklej_rozstrzelone(match: re.Match) -> str:
    litery = re.findall(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]", match.group(0))
    sklejone = "".join(litery)
    return sklejone.upper() if sklejone.upper() in DOZWOLONE_SKROTY else sklejone.lower()


def inteligentna_korekta(tekst: str, czy_sms: bool = False) -> str:
    if not tekst:
        return ""
    t = tekst.strip()
    if czy_sms:
        t = re.sub(r"https?://\S+|www\.\S+", "", t, flags=re.IGNORECASE)
        t = re.sub(r"([*#_~=\-+<>])\1{1,}", " ", t)

    t = re.sub(
        r"(?<!\w)(?:[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż][\s\-\.]+){2,}[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż](?!\w)",
        _sklej_rozstrzelone,
        t,
    )
    t = re.sub(r"([A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż])\1{2,}", r"\1", t)

    slownik_poprawek = {
        "zeby": "żeby", "zyczenia": "życzenia", "zycze": "życzę", "zyczymy": "życzymy",
        "pozdrowienia": "pozdrowienia", "pozdro": "pozdrowienia", "pozdrawiam": "pozdrawiam",
        "dzien": "dzień", "urodziny": "urodziny", "imieniny": "imieniny", "dziekuje": "dziękuję",
        "dzieki": "dzięki", "sie": "się", "ze": "że", "dzis": "dziś", "tez": "też",
        "wogole": "w ogóle", "narazie": "na razie", "najlepszego": "najlepszego",
        "caluski": "całuski", "pozdrowionka": "pozdrowionka", "muzyczka": "muzyczka",
        "mozna": "można", "wiecej": "więcej", "jesli": "jeśli", "ktos": "ktoś",
        "cos": "coś", "zrobic": "zrobić", "piosenke": "piosenkę", "nwm": "nie wiem",
    }

    poprawione = []
    for s in t.split():
        klucz = s.strip(".,!?").lower()
        poprawione.append(slownik_poprawek.get(klucz, s))

    wynik = " ".join(poprawione)
    wynik = re.sub(r"[^0-9A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż\s,.!?\-–—]", " ", wynik)
    return re.sub(r"\s{2,}", " ", wynik).strip(" ,.-–—")


def _elevenlabs_zapisz(tekst: str, sciezka_mp3: str) -> bool:
    if not ELEVENLABS_API_KEY or not ELEVENLABS_VOICE_ID:
        return False
    try:
        resp = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
            json={
                "text": tekst,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.45, "similarity_boost": 0.75},
            },
            headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            timeout=25,
        )
        if resp.status_code == 200 and resp.content:
            with open(sciezka_mp3, "wb") as f:
                f.write(resp.content)
            return True
    except Exception as e:
        logging.warning(f"Fallback ElevenLabs -> Edge-TTS: {e}")
    return False


async def async_generuj_edge_tts(tekst, sciezka_docelowa, glos="pl-PL-MarekNeural", pitch="-12Hz", rate="+0%"):
    pitch_str = f"{int(pitch):+d}Hz" if isinstance(pitch, int) else str(pitch)
    rate_str = f"{int(rate):+d}%" if isinstance(rate, int) else str(rate)
    if not _elevenlabs_zapisz(tekst, sciezka_docelowa):
        communicate = edge_tts.Communicate(tekst, glos, pitch=pitch_str, rate=rate_str)
        await communicate.save(sciezka_docelowa)


def generuj_audio_mp3(lista_kwestii, nazwa_pliku_koncowego, glos="pl-PL-MarekNeural", pitch="-12Hz", rate="+0%", czy_sms=False):
    sciezka_koncowa = os.path.join(FOLDER_ROBOCZY, nazwa_pliku_koncowego)
    pliki_tymczasowe = []
    try:
        for idx, (_, tekst) in enumerate(lista_kwestii):
            oczyszczony = inteligentna_korekta(tekst or "", czy_sms=czy_sms)
            if not oczyszczony:
                continue
            temp_path = os.path.join(FOLDER_ROBOCZY, f"temp_{idx}_{nazwa_pliku_koncowego}")
            uruchom_async(async_generuj_edge_tts(oczyszczony, temp_path, glos, pitch=pitch, rate=rate))
            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                pliki_tymczasowe.append(temp_path)

        if not pliki_tymczasowe:
            return None

        polaczony_segment = AudioSegment.empty()
        cisza = AudioSegment.silent(duration=500)
        for temp_f in pliki_tymczasowe:
            segment = AudioSegment.from_file(temp_f)
            polaczony_segment += segment + cisza

        polaczony_segment = effects.normalize(polaczony_segment)
        polaczony_segment.export(sciezka_koncowa, format="mp3")
        return sciezka_koncowa
    except Exception as e:
        logging.error(f"Błąd generatora TTS: {e}")
        return None
    finally:
        for temp_f in pliki_tymczasowe:
            if os.path.exists(temp_f):
                try:
                    os.remove(temp_f)
                except Exception:
                    pass


def pobierz_aktualne_newsy_rmf():
    teraz = datetime.now(STREFA_EUROPA)
    if teraz.weekday() in INFO_RMF_DNI and INFO_RMF_START <= teraz.hour < INFO_RMF_KONIEC:
        try:
            url_rss = "https://www.rmf24.pl/fakty/rss"
            feed = feedparser.parse(url_rss)
            newsy = []
            if getattr(feed, "entries", None):
                for entry in feed.entries[:2]:
                    tytul = entry.get("title", "").strip()
                    if tytul:
                        newsy.append(tytul)
            if newsy:
                return "Najświeższe informacje z RMF FM: " + ". ".join(newsy) + "."
        except Exception as e:
            logging.error(f"Błąd pobierania newsów RMF: {e}")
    return ""


def pobierz_nowplaying_dj():
    if not AZURACAST_URL:
        return ""
    try:
        resp = requests.get(f"{AZURACAST_URL}/api/nowplaying/{AZURACAST_STATION_ID}", timeout=10)
        if resp.status_code != 200:
            return ""
        song = (resp.json().get("now_playing") or {}).get("song") or {}
        tytul = (song.get("title") or "").strip()
        wykonawca = (song.get("artist") or "").strip()
        if wykonawca and tytul:
            return f"Przed chwilą w Radiu Strefa Zero graliśmy: {wykonawca} — {tytul}. Zostajemy w dobrym klimacie!"
        if tytul:
            return f"Przed chwilą w Radiu Strefa Zero poleciał utwór {tytul}. Lecimy dalej!"
    except Exception as e:
        logging.warning(f"Błąd nowplaying DJ: {e}")
    return ""


def okresl_folder_gatunkowy(zapytanie):
    t = zapytanie.lower()
    if any(k in t for k in ("club", "klub", "house", "techno", "edm")):
        return "muzyka klubowa"
    if any(k in t for k in ("italo", "retro", "80")):
        return "italo disco"
    if "dance" in t:
        return "disco polo dance"
    if any(k in t for k in ("disco", "polo", "akcent", "milano")):
        return "disco polo"
    return "muzyka mix"


def szukaj_piosenki_na_dysku_sftp(sftp, zapytanie):
    slowa_kluczowe = [s.lower() for s in re.findall(r"\w+", zapytanie) if len(s) > 2]
    if not slowa_kluczowe:
        return None

    foldery_do_sprawdzenia = (
        tuple(FOLDERY_GATUNKOWE)
        + (DIR_POBRANE, DIR_PIOSENKI_DLA_SLUCHACZY, DIR_KONCERT_ZYCZEN, DIR_PIOSENKA_NA_ZYCZENIE, DIR_JINGLES, ".")
    )
    for folder in foldery_do_sprawdzenia:
        try:
            pliki = sftp.listdir(folder)
            for plik in pliki:
                if plik.lower().endswith(".mp3"):
                    nazwa_low = plik.lower()
                    if all(slowo in nazwa_low for slowo in slowa_kluczowe):
                        return f"{folder}/{plik}" if folder != "." else plik
        except Exception:
            continue
    return None


def pobierz_piosenke_z_sieci(zapytanie, nazwa_docelowa_bez_rozsz):
    baza_nazwy = os.path.join(FOLDER_ROBOCZY, nazwa_docelowa_bez_rozsz)
    warianty_zapytan = [
        f"ytsearch1:{zapytanie} audio",
        f"ytsearch1:{zapytanie} hq",
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
            logging.error(f"Błąd pobierania yt-dlp dla '{query}': {e}")
            continue
    return None


def zbuduj_tylko_godzine(docelowa_godzina_24h):
    slownik_godzin = {
        0: "północ", 1: "pierwsza w nocy", 2: "druga w nocy", 3: "trzecia w nocy",
        4: "czwarta w nocy", 5: "piąta rano", 6: "szósta rano", 7: "siódma rano",
        8: "ósma rano", 9: "dziewiąta", 10: "dziesiąta", 11: "jedenasta",
        12: "dwunasta", 13: "trzynasta", 14: "czternasta", 15: "piętnasta",
        16: "szesnasta", 17: "siedemnasta", 18: "osiemnasta", 19: "dziewiętnasta",
        20: "dwudziesta", 21: "dwudziesta pierwsza", 22: "dwudziesta druga",
        23: "dwudziesta trzecia",
    }
    godzina_slownie = slownik_godzin.get(docelowa_godzina_24h, f"godzina {docelowa_godzina_24h}")
    return [("glos", f"Jest godzina {godzina_slownie}. Słuchasz Radia Strefa Zero.")]


def zbuduj_informacje_rmf():
    newsy_rmf = pobierz_aktualne_newsy_rmf()
    if not newsy_rmf:
        return None
    return [
        ("glos", "Serwis informacyjny Radia Strefa Zero."),
        ("glos", newsy_rmf),
        ("glos", f"Słuchaj Radia Strefa Zero. Przypominam darmowy numer SMS: {NUMER_TEL_TEKST}."),
    ]


def zbuduj_poranny_serwis():
    ciekawostki = [
        "Czy wiecie, że muzyka Italo Disco ma swoje korzenie we wczesnych latach osiemdziesiątych i do dziś porywa do tańca?",
        "Dobry humor to połowa sukcesu w każdym dniu. Słuchacie najlepszych hitów w Radiu Strefa Zero!",
        "Warto pamiętać, że pozytywna energia przyciąga dobre rzeczy. Miłego dnia życzy ekipa Radia Strefa Zero!",
        "Każdy poranek to nowa szansa na świetny bit. Zostawcie dobry nastrój i lećcie z nami przez cały dzień!",
    ]
    return [
        ("glos", "Witamy w porannym bloku Radia Strefa Zero! Życzymy Wam wspaniałego, pełnego energii dnia."),
        ("glos", random.choice(ciekawostki)),
        ("glos", f"Zostajcie z nami. Zamawiajcie piosenki darmowym SMS-em na numer: {NUMER_TEL_TEKST}."),
    ]


def _przytnij_cisze(seg: AudioSegment, prog_db: float = -45.0, max_ms: int = 3500) -> AudioSegment:
    if len(seg) <= 5000:
        return seg
    start_ms = min(detect_leading_silence(seg, silence_threshold=prog_db, chunk_size=50), max_ms)
    end_ms = min(detect_leading_silence(seg.reverse(), silence_threshold=prog_db, chunk_size=50), max_ms)
    end_idx = len(seg) - end_ms if end_ms > 0 else len(seg)
    return seg[start_ms:end_idx] if (end_idx - start_ms) >= 4000 else seg


def wygeneruj_mix_z_folderu(
    folder_gatunkowy="muzyka klubowa",
    liczba_utworow=3,
    crossfade_ms=5000,
    folder_docelowy=DIR_MIXY,
    dzingiel_na_przejsciu=None,
    sciszenie_db=12.0,
):
    transport = None
    sftp = None
    lokalne_pobrane = []
    try:
        transport, sftp = polacz_sftp()
        try:
            pliki = [
                f for f in sftp.listdir(folder_gatunkowy)
                if f.lower().endswith((".mp3", ".wav", ".ogg", ".m4a")) and not f.startswith("mix_")
            ]
        except Exception as e:
            logging.error(f"Nie można odczytać folderu '{folder_gatunkowy}' dla mixu: {e}")
            return None

        if len(pliki) < 2:
            logging.warning(f"Za mało utworów w folderze '{folder_gatunkowy}' ({len(pliki)}) do utworzenia mixu.")
            return None

        wybrane = random.sample(pliki, min(liczba_utworow, len(pliki)))
        for idx, nazwa_mp3 in enumerate(wybrane):
            lok_path = os.path.join(FOLDER_ROBOCZY, f"mix_src_{idx}_{re.sub(r'[^a-zA-Z0-9._-]', '_', nazwa_mp3)}")
            sftp.get(f"{folder_gatunkowy}/{nazwa_mp3}", lok_path)
            if os.path.exists(lok_path) and os.path.getsize(lok_path) > 1024:
                lokalne_pobrane.append(lok_path)

        if len(lokalne_pobrane) < 2:
            return None

        dj_seg = None
        if dzingiel_na_przejsciu and os.path.exists(dzingiel_na_przejsciu):
            dj_seg = effects.normalize(AudioSegment.from_file(dzingiel_na_przejsciu)).fade_in(200).fade_out(250)

        mix_audio = effects.normalize(_przytnij_cisze(AudioSegment.from_file(lokalne_pobrane[0]))).fade_in(250).fade_out(250)
        for idx, sciezka_next in enumerate(lokalne_pobrane[1:], start=1):
            next_audio = effects.normalize(_przytnij_cisze(AudioSegment.from_file(sciezka_next))).fade_in(250).fade_out(250)

            if dj_seg is not None and idx % 2 == 1 and len(mix_audio) > len(dj_seg) + 1200:
                dl_dj = min(len(dj_seg), 4500)
                ogon = mix_audio[-dl_dj:] - abs(float(sciszenie_db))
                mix_audio = mix_audio[:-dl_dj] + ogon.overlay(dj_seg[:dl_dj])

            efektywny_xfade = min(int(crossfade_ms), len(mix_audio) // 3, len(next_audio) // 3)
            if efektywny_xfade > 500:
                mix_audio = mix_audio.append(next_audio, crossfade=efektywny_xfade)
            else:
                mix_audio = mix_audio + next_audio

        mix_audio = effects.normalize(mix_audio)
        znacznik = datetime.now(STREFA_EUROPA).strftime("%Y%m%d_%H%M%S")
        czysta_nazwa_folderu = re.sub(r"[^a-zA-Z0-9_-]", "_", folder_gatunkowy)
        nazwa_mixu = f"mix_{czysta_nazwa_folderu}_{znacznik}.mp3"
        sciezka_mixu = os.path.join(FOLDER_ROBOCZY, nazwa_mixu)
        mix_audio.export(sciezka_mixu, format="mp3", bitrate="192k")

        cel_folder = folder_docelowy if folder_docelowy in WSZYSTKIE_FOLDERY_SFTP else DIR_MIXY
        zdalna_sciezka = f"{cel_folder}/{nazwa_mixu}"
        wyslij_i_zsynchronizuj(sftp, sciezka_mixu, zdalna_sciezka)
        if os.path.exists(sciezka_mixu):
            os.remove(sciezka_mixu)

        return zdalna_sciezka
    except Exception as e:
        logging.error(f"Błąd generowania mixu z '{folder_gatunkowy}': {e}")
        return None
    finally:
        for f_path in lokalne_pobrane:
            if os.path.exists(f_path):
                try:
                    os.remove(f_path)
                except Exception:
                    pass
        if sftp:
            try:
                sftp.close()
            except Exception:
                pass
        if transport:
            try:
                transport.close()
            except Exception:
                pass


def wyczysc_wygasle_reklamy(sftp):
    terminy = wczytaj_terminy_reklam()
    if not terminy:
        return
    teraz = datetime.now(STREFA_EUROPA)
    do_usuniecia = []
    for nazwa_pliku, data_waznosci_str in terminy.items():
        try:
            data_waznosci = datetime.fromisoformat(data_waznosci_str)
            if data_waznosci.tzinfo is None:
                data_waznosci = data_waznosci.replace(tzinfo=STREFA_EUROPA)
            if teraz >= data_waznosci:
                zdalna_reklama = f"{DIR_BLOK_REKLAMOWY}/{nazwa_pliku}"
                try:
                    sftp.remove(zdalna_reklama)
                    logging.info(f"Usunięto wygasłą reklamę z serwera: {zdalna_reklama}")
                except IOError:
                    logging.info(f"Reklama '{zdalna_reklama}' już nie istniała na serwerze, usuwam wpis z terminów.")
                do_usuniecia.append(nazwa_pliku)
        except Exception as e:
            logging.error(f"Błąd sprawdzania ważności reklamy '{nazwa_pliku}': {e}")

    if do_usuniecia:
        for k in do_usuniecia:
            terminy.pop(k, None)
        zapisz_terminy_reklam(terminy)
        zsynchronizuj_azuracast()


def przetworz_sms_w_tle(tresc_sms, numer_nadawcy):
    transport = None
    sftp = None
    try:
        transport, sftp = polacz_sftp()
        teraz = datetime.now(STREFA_EUROPA)
        znacznik_czasu = teraz.strftime("%Y%m%d_%H%M%S")
        czy_noc = teraz.hour >= 22 or teraz.hour < 6
        profil = PULA_BOTOW["marek_noc"] if czy_noc else PULA_BOTOW["marek_standard"]

        t_low = tresc_sms.lower()
        glosy = _wczytaj_glosy()
        if "dyskoteka" in t_low:
            glosy["DYSKOTEKA"] += 1
            _zapisz_glosy(glosy)
        elif "italo" in t_low:
            glosy["ITALO"] += 1
            _zapisz_glosy(glosy)

        if "koncert" in t_low:
            typ_audycji = "koncert"
            folder_docelowy = DIR_KONCERT_ZYCZEN
        else:
            typ_audycji = "piosenka"
            folder_docelowy = DIR_PIOSENKA_NA_ZYCZENIE

        czysta_tresc = tresc_sms
        wzorce_do_wyciecia = [
            r"(?i)^koncert\s*życzeń[:\-\s]*",
            r"(?i)^koncert\s*zyczen[:\-\s]*",
            r"(?i)^piosenka\s*na\s*życzenie[:\-\s]*",
            r"(?i)^piosenka\s*na\s*zyczenie[:\-\s]*",
            r"(?i)wyślij\s*sms[^\.\,\!]*[\.\,\!\s]*",
            r"(?i)zamów\s*piosenkę[^\.\,\!]*[\.\,\!\s]*",
            r"(?i)zamow\s*piosenke[^\.\,\!]*[\.\,\!\s]*",
        ]
        for wzorzec in wzorce_do_wyciecia:
            czysta_tresc = re.sub(wzorzec, "", czysta_tresc)
        czysta_tresc = czysta_tresc.strip()

        imie_nadawcy = "Słuchacza"
        match_podpis = re.search(r"[-–—]\s*([A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż]{2,15})", czysta_tresc)
        if match_podpis:
            imie_nadawcy = match_podpis.group(1).capitalize()

        zapytanie_muzyczne = re.sub(r"[-–—]\s*[A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż]{2,15}", "", czysta_tresc).strip()

        pobrano_nowy_utwor = False
        if len(zapytanie_muzyczne) > 2:
            sciezka_istniejaca = szukaj_piosenki_na_dysku_sftp(sftp, zapytanie_muzyczne)
            if not sciezka_istniejaca:
                bezpieczna_nazwa = re.sub(r"[^a-zA-Z0-9_-]", "", zapytanie_muzyczne)[:40] + f"_{znacznik_czasu}"
                lokalne_mp3 = pobierz_piosenke_z_sieci(zapytanie_muzyczne, bezpieczna_nazwa)
                if lokalne_mp3 and os.path.exists(lokalne_mp3):
                    folder_gatunek = okresl_folder_gatunkowy(zapytanie_muzyczne)
                    zdalna_piosenka = f"{folder_gatunek}/{bezpieczna_nazwa}.mp3"
                    sftp.put(lokalne_mp3, zdalna_piosenka)
                    os.remove(lokalne_mp3)
                    pobrano_nowy_utwor = True
                    logging.info(f"Pobrano i wysłano utwór '{zapytanie_muzyczne}' do '{zdalna_piosenka}'.")

        poprawiona_tresc = inteligentna_korekta(czysta_tresc, czy_sms=True)

        if typ_audycji == "koncert":
            kwestie_audio = [
                ("glos", f"Mamy zgłoszenie do Koncertu Życzeń od słuchacza: {imie_nadawcy}."),
                ("glos", f"Treść: {poprawiona_tresc}."),
                ("glos", f"Wyślij SMS na numer: {NUMER_TEL_TEKST}. Gramy w Radiu Strefa Zero!"),
            ]
        else:
            kwestie_audio = [
                ("glos", f"Piosenka na Życzenie od: {imie_nadawcy}."),
                ("glos", f"Pozdrowienia: {poprawiona_tresc}."),
                ("glos", f"Zamawiaj pod numerem: {NUMER_TEL_TEKST}. Radio Strefa Zero!"),
            ]

        nazwa_glosu = f"wiadomosc_{znacznik_czasu}.mp3"
        lokalny_glos = generuj_audio_mp3(
            kwestie_audio,
            nazwa_glosu,
            glos=profil["voice"],
            pitch=profil["pitch"],
            rate=profil["rate"],
            czy_sms=True,
        )

        if lokalny_glos and os.path.exists(lokalny_glos):
            zdalny_glos = f"{folder_docelowy}/{nazwa_glosu}"
            sftp.put(lokalny_glos, zdalny_glos)
            os.remove(lokalny_glos)
            pobrano_nowy_utwor = True

        if pobrano_nowy_utwor:
            zsynchronizuj_azuracast()

        logging.info(f"Przetworzono SMS od '{numer_nadawcy}' -> '{folder_docelowy}/{nazwa_glosu}'.")
    except Exception as e:
        logging.error(f"Błąd przetwarzania SMS w tle: {e}")
    finally:
        if sftp:
            try:
                sftp.close()
            except Exception:
                pass
        if transport:
            try:
                transport.close()
            except Exception:
                pass


@app.route("/sms", methods=["POST", "GET"])
def webhook_sms():
    tresc_sms = (request.values.get("Body") or request.values.get("text") or request.values.get("message") or "").strip()
    numer_nadawcy = (request.values.get("From") or request.values.get("sender") or "").strip()
    if tresc_sms:
        threading.Thread(target=przetworz_sms_w_tle, args=(tresc_sms, numer_nadawcy), daemon=True).start()
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
                wyslij_i_zsynchronizuj(sftp, sciezka, f"{DIR_GODZINA}/{nazwa_pliku}")
            finally:
                sftp.close()
                transport.close()
            os.remove(sciezka)
            return f"Sukces! Wygenerowano zapowiedź godziny: {nazwa_pliku}", 200
        return "Błąd generowania pliku audio", 500
    except Exception as e:
        return f"Błąd endpointu: {e}", 500


@app.route("/generuj-mix", methods=["GET", "POST"])
def endpoint_generuj_mix():
    folder_gatunek = request.values.get("folder", "muzyka klubowa")
    if folder_gatunek not in FOLDERY_GATUNKOWE:
        folder_gatunek = "muzyka klubowa"
    folder_docelowy = request.values.get("target_folder", DIR_MIXY)
    if folder_docelowy not in WSZYSTKIE_FOLDERY_SFTP:
        folder_docelowy = DIR_MIXY
    try:
        liczba = max(2, min(8, int(request.values.get("count", "3"))))
    except ValueError:
        liczba = 3
    try:
        crossfade_ms = max(500, min(10000, int(request.values.get("crossfade_ms", "5000"))))
    except ValueError:
        crossfade_ms = 5000
    try:
        duck_db = max(3.0, min(24.0, float(request.values.get("duck_db", "12"))))
    except ValueError:
        duck_db = 12.0

    dzingiel_kandydat = next(
        (
            os.path.join(DIR_STATIC_OUTPUT, n)
            for n in sorted(os.listdir(DIR_STATIC_OUTPUT), reverse=True)
            if n.endswith(".mp3")
        ),
        None,
    )

    zdalna = wygeneruj_mix_z_folderu(
        folder_gatunkowy=folder_gatunek,
        liczba_utworow=liczba,
        crossfade_ms=crossfade_ms,
        folder_docelowy=folder_docelowy,
        dzingiel_na_przejsciu=dzingiel_kandydat,
        sciszenie_db=duck_db,
    )
    if zdalna:
        return jsonify({"status": "success", "remote_file": zdalna, "folder": folder_gatunek}), 200
    return jsonify({"status": "error", "message": f"Nie udało się wygenerować mixu z '{folder_gatunek}'."}), 400


@app.route("/usun-reklame", methods=["POST"])
def usun_reklame_recznie():
    nazwa_pliku = (request.form.get("filename") or (request.get_json(silent=True) or {}).get("filename") or "").strip()
    if not nazwa_pliku or "/" in nazwa_pliku or "\\" in nazwa_pliku:
        return jsonify({"status": "error", "message": "Nieprawidłowa nazwa pliku."}), 400

    transport = None
    sftp = None
    try:
        transport, sftp = polacz_sftp()
        try:
            sftp.remove(f"{DIR_BLOK_REKLAMOWY}/{nazwa_pliku}")
        except IOError:
            pass
        terminy = wczytaj_terminy_reklam()
        terminy.pop(nazwa_pliku, None)
        zapisz_terminy_reklam(terminy)
        zsynchronizuj_azuracast()
        logging.info(f"Ręcznie usunięto reklamę: {nazwa_pliku}")
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logging.error(f"Błąd ręcznego usuwania reklamy '{nazwa_pliku}': {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if sftp:
            try:
                sftp.close()
            except Exception:
                pass
        if transport:
            try:
                transport.close()
            except Exception:
                pass


SZABLON_JINGLES = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <title>Radio Strefa Zero - Generator AI, Reklamy i Mixy</title>
    <style>
        body { font-family: Arial, sans-serif; background: #121212; color: #fff; padding: 30px; }
        .container { max-width: 740px; margin: auto; background: #1e1e1e; padding: 25px; border-radius: 10px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
        textarea, select, input[type=datetime-local], input[type=number] { width: 100%; padding: 10px; margin-top: 8px; margin-bottom: 16px; background: #2d2d2d; color: #fff; border: 1px solid #444; border-radius: 5px; box-sizing: border-box; }
        input[type=range] { width: 100%; margin-top: 5px; margin-bottom: 15px; background: #2d2d2d; }
        button { background: #ff4757; color: white; border: none; padding: 12px 20px; font-size: 16px; border-radius: 5px; cursor: pointer; width: 100%; font-weight: bold; }
        button:hover { background: #ff6b81; }
        .btn-mix { background: #8e44ad; margin-top: 10px; }
        .btn-mix:hover { background: #9b59b6; }
        .btn-preset { background: #2f3542; padding: 8px 12px; font-size: 13px; width: auto; margin-right: 6px; margin-bottom: 8px; }
        .btn-preset:hover { background: #57606f; }
        .btn-del { background: #e74c3c; padding: 5px 10px; font-size: 12px; width: auto; }
        .checkbox-group { margin-bottom: 18px; display: flex; align-items: center; gap: 10px; }
        audio { width: 100%; margin-top: 20px; }
        .hidden { display: none; }
        .back-link { display: inline-block; margin-bottom: 15px; color: #3498db; text-decoration: none; }
        .back-link:hover { text-decoration: underline; }
        .success-box { background: #2ed57322; border: 1px solid #2ed573; padding: 10px; border-radius: 5px; margin-top: 15px; color: #2ed573; }
        .info-box { background: #3498db22; border: 1px solid #3498db; padding: 10px; border-radius: 5px; margin-bottom: 15px; color: #3498db; font-size: 14px; }
        .slider-label { display: flex; justify-content: space-between; font-size: 14px; color: #ccc; }
        .box-section { border-top: 1px solid #333; margin-top: 25px; padding-top: 20px; }
        .ad-row { display: flex; justify-content: space-between; align-items: center; background: #262626; padding: 10px; border-radius: 6px; margin-bottom: 8px; font-size: 13px; }
        pre.log-box { background: #141414; border: 1px solid #333; padding: 12px; border-radius: 6px; font-size: 12px; color: #dcdde1; overflow-x: auto; max-height: 220px; white-space: pre-wrap; }
    </style>
</head>
<body>
    <div class="container">
        <a href="/" class="back-link">← Powrót do głównej / Status</a>
        <h2>🎛️ Radio Strefa Zero - Generator AI, Reklamy i Mixy</h2>
        
        <div class="info-box">
            🎚️ Wybierz folder docelowy (w tym <b>blok reklamowy</b> z terminem ważności), bota/głos, ustaw Pitch i Rate i wyślij plik na SFTP. Bot automatycznie poskłada rozstrzelone litery i poprawi literówki.
        </div>

        <div style="margin-bottom: 14px;">
            <span style="font-size: 13px; color: #aaa; display: block; margin-bottom: 6px;">Szybkie szablony zapowiedzi:</span>
            <button type="button" class="btn-preset" onclick="wstawSzablon('Cofamy się w czasie do złotych lat osiemdziesiątych i dziewięćdziesiątych. Posłuchajcie, co wtedy rozgrzewało parkiety w Radiu Strefa Zero!')">🕰️ Kapsuła Czasu</button>
            <button type="button" class="btn-preset" onclick="wstawSzablon('Starcie gatunków w Radiu Strefa Zero! Co wolisz na kolejnym bloku – energetyczne disco polo czy klasyczne italo disco?')">⚔️ Bitwa Gatunków</button>
            <button type="button" class="btn-preset" onclick="wstawSzablon('Nocne pasmo w Radiu Strefa Zero. Głęboki bit, zero pośpiechu i muzyka, która trzyma na nogach do rana.')">🌙 Nocny Klimat</button>
        </div>
        
        <form id="generatorForm">
            <label>Tekst zapowiedzi / dżingla / bloku reklamowego:</label>
            <textarea name="text" id="text" rows="4" placeholder="Np. Słuchasz Radio Strefa Zero albo m u l t l s c..."></textarea>
            
            <label>📂 Wybierz folder docelowy na serwerze (AzuraCast):</label>
            <select name="target_folder" id="target_folder" onchange="toggleExpireBox()">
                {% for f in all_folders %}
                    <option value="{{ f }}">{{ f }}</option>
                {% endfor %}
            </select>

            <div id="expireBox" class="hidden">
                <label>⏳ Termin ważności reklamy:</label>
                <input type="datetime-local" name="expires_at" id="expires_at">
            </div>

            <label>Wybierz profil bota z puli:</label>
            <select id="bot_preset" onchange="zastosujProfilBota()">
                {% for k, cfg in bot_pool.items() %}
                    <option value="{{ k }}" data-voice="{{ cfg.voice }}" data-pitch="{{ cfg.pitch }}" data-rate="{{ cfg.rate }}">{{ cfg.name }}</option>
                {% endfor %}
            </select>

            <label>Wybierz głos lektora:</label>
            <select name="voice" id="voice_select">
                <optgroup label="Głosy Męskie (Radiowe / Basowe)">
                    <option value="pl-PL-MarekNeural">Marek (Głęboki / Radiowy)</option>
                    <option value="pl-PL-AndrzejNeural">Andrzej (Dynamiczny / Młody)</option>
                    <option value="pl-PL-JacekNeural">Jacek (Mocny / Wyrazisty)</option>
                    <option value="pl-PL-TomaszNeural">Tomasz (Ciepły / Spokojny)</option>
                </optgroup>
                <optgroup label="Głosy Żeńskie">
                    <option value="pl-PL-ZofiaNeural">Zofia (Naturalny / Czysty)</option>
                    <option value="pl-PL-AgnieszkaNeural">Agnieszka (Ciepły radiowy)</option>
                    <option value="pl-PL-EwaNeural">Ewa (Wyrazisty)</option>
                    <option value="pl-PL-MagdalenaNeural">Magdalena (Miękki)</option>
                </optgroup>
            </select>

            <div class="slider-label">
                <span>Wysokość tonu głosu (Pitch):</span>
                <span id="pitchVal">-12Hz (Głęboki radiowy bas)</span>
            </div>
            <input type="range" name="pitch" id="pitch" min="-35" max="15" value="-12" step="1" oninput="updatePitch(this.value)">

            <div class="slider-label">
                <span>Prędkość mowy (Rate):</span>
                <span id="rateVal">0% (Normalna)</span>
            </div>
            <input type="range" name="rate" id="rate" min="-30" max="30" value="0" step="5" oninput="updateRate(this.value)">

            <div class="checkbox-group">
                <input type="checkbox" id="add_music" name="add_music" onchange="toggleMusicSelect()">
                <label for="add_music">Dodaj podkład muzyczny w tle</label>
            </div>
            
            <div id="musicSelectContainer" class="hidden">
                <label>Wybierz podkład muzyczny:</label>
                <select name="music">
                    {% for music in music_files %}
                        <option value="{{ music }}">{{ music }}</option>
                    {% endfor %}
                </select>
            </div>
            
            <button type="submit">Generuj i Wyślij na Serwer (SFTP) 🚀</button>
        </form>
        
        <div id="statusMsg" style="margin-top: 15px; font-weight: bold; text-align: center;"></div>

        <div id="result" class="hidden">
            <div class="success-box" id="successBoxText">Sukces! Plik został wygenerowany i wysłany na serwer.</div>
            <h3>Odsłuch podglądowy:</h3>
            <audio id="audioPlayer" controls></audio>
            <br><br>
            <a id="downloadBtn" href="#" download="audio.mp3"><button style="background: #2ed573;">Pobierz plik lokalnie 💾</button></a>
        </div>

        <div class="box-section">
            <h3>📢 Zaplanowane reklamy w folderze 'blok reklamowy'</h3>
            {% if active_ads %}
                {% for fname, exp in active_ads.items() %}
                    <div class="ad-row" id="ad-{{ fname }}">
                        <div>
                            <b>{{ fname }}</b><br>
                            <span style="color: #aaa;">Ważne do: {{ exp }}</span>
                        </div>
                        <button type="button" class="btn-del" onclick="usunReklame('{{ fname }}')">Usuń</button>
                    </div>
                {% endfor %}
            {% else %}
                <p style="color: #888; font-size: 13px;">Brak aktywnych reklam z terminem ważności.</p>
            {% endif %}
        </div>

        <div class="box-section">
            <h3>🎧 Automatyczny DJ – Szybki Mikser (Crossfade + Wstawka) -> SFTP</h3>
            <label>Wybierz folder gatunkowy do zmiksowania:</label>
            <select id="mixFolder">
                {% for folder in genre_folders %}
                    <option value="{{ folder }}">{{ folder }}</option>
                {% endfor %}
            </select>

            <label>Liczba utworów (2 - 8):</label>
            <input type="number" id="mixCount" value="3" min="2" max="8">

            <label>Crossfade (ms, np. 5000 = 5s):</label>
            <input type="number" id="mixCrossfade" value="5000" min="500" max="10000" step="250">

            <label>Folder docelowy SFTP:</label>
            <select id="mixTarget">
                <option value="mixy" selected>mixy</option>
                <option value="muzyka mix">muzyka mix</option>
            </select>

            <button type="button" class="btn-mix" onclick="generujMix()">Składaj Miks i Wyślij na SFTP 🎚️</button>
            <div id="mixStatus" style="margin-top: 12px; font-weight: bold; text-align: center;"></div>
        </div>

        <div class="box-section">
            <h3>📜 Ostatnie wpisy z dziennika (radio_bot.log)</h3>
            <pre class="log-box">{{ recent_logs }}</pre>
        </div>
    </div>

    <script>
        function wstawSzablon(txt) {
            document.getElementById('text').value = txt;
        }
        function zastosujProfilBota() {
            const sel = document.getElementById('bot_preset');
            const opt = sel.options[sel.selectedIndex];
            if (!opt) return;
            document.getElementById('voice_select').value = opt.dataset.voice;
            document.getElementById('pitch').value = opt.dataset.pitch;
            document.getElementById('rate').value = opt.dataset.rate;
            updatePitch(opt.dataset.pitch);
            updateRate(opt.dataset.rate);
        }
        function updatePitch(val) {
            let num = parseInt(val);
            let sign = num > 0 ? '+' : '';
            let opis = '';
            if (num <= -20) opis = '(Super gruby / potężny bas)';
            else if (num < 0) opis = '(Głęboki radiowy bas)';
            else if (num > 0) opis = '(Wysoki)';
            else opis = '(Normalny)';
            document.getElementById('pitchVal').innerText = sign + val + 'Hz ' + opis;
        }
        function updateRate(val) {
            let num = parseInt(val);
            let sign = num > 0 ? '+' : '';
            document.getElementById('rateVal').innerText = sign + val + '%';
        }
        function toggleMusicSelect() {
            const checkbox = document.getElementById('add_music');
            const container = document.getElementById('musicSelectContainer');
            if (checkbox.checked) container.classList.remove('hidden');
            else container.classList.add('hidden');
        }
        function toggleExpireBox() {
            const sel = document.getElementById('target_folder').value;
            const box = document.getElementById('expireBox');
            if (sel === 'blok reklamowy') box.classList.remove('hidden');
            else box.classList.add('hidden');
        }

        document.getElementById('generatorForm').onsubmit = async function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            const statusMsg = document.getElementById('statusMsg');
            statusMsg.style.color = '#fff';
            statusMsg.innerText = '⏳ Trwa generowanie głosu AI i miksowanie audio...';
            document.getElementById('result').classList.add('hidden');

            try {
                const response = await fetch('/generuj-jingle-ai', { method: 'POST', body: formData });
                const data = await response.json();
                if (data.status === 'success') {
                    statusMsg.innerText = '';
                    let extra = data.expires_at ? ' (ważny do: ' + data.expires_at + ')' : '';
                    document.getElementById('successBoxText').innerHTML = 'Sukces! Plik wysłany do folderu <b>' + data.folder + '</b>' + extra + '.';
                    const audioPlayer = document.getElementById('audioPlayer');
                    audioPlayer.src = data.file_url + '?' + new Date().getTime();
                    audioPlayer.load();
                    document.getElementById('downloadBtn').href = data.file_url;
                    document.getElementById('result').classList.remove('hidden');
                    if (data.expires_at) setTimeout(() => location.reload(), 1200);
                } else {
                    statusMsg.innerText = '❌ Błąd: ' + data.message;
                    statusMsg.style.color = '#ff4757';
                }
            } catch (err) {
                statusMsg.innerText = '❌ Błąd połączenia z serwerem.';
                statusMsg.style.color = '#ff4757';
            }
        };

        async function usunReklame(fname) {
            try {
                const res = await fetch('/usun-reklame', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ filename: fname })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    const el = document.getElementById('ad-' + fname);
                    if (el) el.remove();
                }
            } catch (e) {}
        }

        async function generujMix() {
            const folder = document.getElementById('mixFolder').value;
            const count = document.getElementById('mixCount').value;
            const crossfade_ms = document.getElementById('mixCrossfade').value;
            const target_folder = document.getElementById('mixTarget').value;
            const mixStatus = document.getElementById('mixStatus');
            mixStatus.style.color = '#fff';
            mixStatus.innerText = '⏳ Trwa miksowanie utworów z folderu ' + folder + '...';

            try {
                const params = new URLSearchParams({ folder, count, crossfade_ms, target_folder });
                const res = await fetch('/generuj-mix?' + params.toString());
                const data = await res.json();
                if (data.status === 'success') {
                    mixStatus.style.color = '#2ed573';
                    mixStatus.innerText = '✅ Gotowe! Wysłano na serwer: ' + data.remote_file;
                } else {
                    mixStatus.style.color = '#ff4757';
                    mixStatus.innerText = '❌ ' + data.message;
                }
            } catch (e) {
                mixStatus.style.color = '#ff4757';
                mixStatus.innerText = '❌ Błąd podczas generowania mixu.';
            }
        }
    </script>
</body>
</html>
"""


def sprawdz_i_pobierz_podklady():
    os.makedirs(DIR_STATIC_MUSIC, exist_ok=True)
    istniejace = [f for f in os.listdir(DIR_STATIC_MUSIC) if f.lower().endswith((".mp3", ".wav"))]
    if not istniejace:
        domyslne_bity = {
            "01_bit_klubowy_dance.mp3": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
            "02_bit_dyskotekowy_retro.mp3": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3",
            "03_bit_house_energetyczny.mp3": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-3.mp3",
            "04_bit_techno_mocny.mp3": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-4.mp3",
        }
        for nazwa, url in domyslne_bity.items():
            sciezka_docelowa = os.path.join(DIR_STATIC_MUSIC, nazwa)
            try:
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    with open(sciezka_docelowa, "wb") as f:
                        f.write(r.content)
            except Exception as e:
                logging.error(f"Nie udało się pobrać domyślnego bitu '{nazwa}': {e}")


def pobierz_ostatnie_logi(linii=25):
    if not os.path.exists("radio_bot.log"):
        return "Brak wpisów w radio_bot.log."
    try:
        with open("radio_bot.log", "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-linii:]) if lines else "Plik logu jest pusty."
    except Exception as e:
        return f"Błąd odczytu logów: {e}"


@app.route("/jingles", methods=["GET"])
def panel_jingles():
    sprawdz_i_pobierz_podklady()
    music_files = [f for f in os.listdir(DIR_STATIC_MUSIC) if f.lower().endswith((".mp3", ".wav"))]
    terminy = wczytaj_terminy_reklam()
    sformatowane_reklamy = {}
    for k, v in terminy.items():
        try:
            dt = datetime.fromisoformat(v)
            sformatowane_reklamy[k] = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            sformatowane_reklamy[k] = v

    return render_template_string(
        SZABLON_JINGLES,
        music_files=sorted(music_files),
        genre_folders=FOLDERY_GATUNKOWE,
        all_folders=WSZYSTKIE_FOLDERY_SFTP,
        bot_pool=PULA_BOTOW,
        active_ads=sformatowane_reklamy,
        recent_logs=pobierz_ostatnie_logi(25),
    )


@app.route("/generuj-jingle-ai", methods=["POST"])
def endpoint_generuj_jingle_ai():
    text = request.form.get("text", "").strip()
    selected_music = request.form.get("music")
    add_music = request.form.get("add_music") == "on"
    selected_voice = request.form.get("voice", "pl-PL-MarekNeural")
    target_folder = request.form.get("target_folder", "jingles")
    expires_at_raw = request.form.get("expires_at", "").strip()

    zdalny_katalog = target_folder if target_folder in WSZYSTKIE_FOLDERY_SFTP else DIR_JINGLES

    try:
        p_val = max(-35, min(15, int(request.form.get("pitch", "-12"))))
        pitch_str = f"{p_val:+d}Hz"
    except ValueError:
        pitch_str = "-12Hz"

    try:
        r_val = max(-30, min(30, int(request.form.get("rate", "0"))))
        rate_str = f"{r_val:+d}%"
    except ValueError:
        rate_str = "+0%"

    oczyszczony_tekst = inteligentna_korekta(text)
    if not oczyszczony_tekst:
        return jsonify({"status": "error", "message": "Tekst jest pusty!"}), 400

    znacznik = datetime.now(STREFA_EUROPA).strftime("%Y%m%d_%H%M%S")
    prefix = "reklama_" if zdalny_katalog == DIR_BLOK_REKLAMOWY else "item_"
    nazwa_pliku = f"{prefix}{znacznik}.mp3"

    speech_file = os.path.join(FOLDER_ROBOCZY, f"speech_{znacznik}.mp3")
    final_output = os.path.join(DIR_STATIC_OUTPUT, nazwa_pliku)

    try:
        uruchom_async(async_generuj_edge_tts(oczyszczony_tekst, speech_file, selected_voice, pitch=pitch_str, rate=rate_str))

        if not os.path.exists(speech_file):
            return jsonify({"status": "error", "message": "Nie udało się wygenerować mowy."}), 500

        if add_music and selected_music:
            music_path = os.path.join(DIR_STATIC_MUSIC, selected_music)
            if os.path.exists(music_path):
                speech = effects.normalize(AudioSegment.from_file(speech_file))
                music = AudioSegment.from_file(music_path)

                target_duration = len(speech) + 2000
                if len(music) > target_duration:
                    music = music[:target_duration]

                music = music - 18
                combined = music.overlay(speech, position=500)
                combined.export(final_output, format="mp3")
            else:
                effects.normalize(AudioSegment.from_file(speech_file)).export(final_output, format="mp3")
        else:
            effects.normalize(AudioSegment.from_file(speech_file)).export(final_output, format="mp3")

        if os.path.exists(speech_file):
            try:
                os.remove(speech_file)
            except Exception:
                pass

        transport, sftp = polacz_sftp()
        try:
            zdalna_sciezka = f"{zdalny_katalog}/{nazwa_pliku}"
            wyslij_i_zsynchronizuj(sftp, final_output, zdalna_sciezka)
        finally:
            sftp.close()
            transport.close()

        zapisany_termin = None
        if zdalny_katalog == DIR_BLOK_REKLAMOWY and expires_at_raw:
            try:
                dt_exp = datetime.fromisoformat(expires_at_raw)
                if dt_exp.tzinfo is None:
                    dt_exp = dt_exp.replace(tzinfo=STREFA_EUROPA)
                terminy = wczytaj_terminy_reklam()
                terminy[nazwa_pliku] = dt_exp.isoformat()
                zapisz_terminy_reklam(terminy)
                zapisany_termin = dt_exp.strftime("%Y-%m-%d %H:%M")
                logging.info(f"Ustawiono termin ważności reklamy '{nazwa_pliku}' na {zapisany_termin}.")
            except Exception as e:
                logging.error(f"Nieprawidłowy format daty ważności reklamy '{expires_at_raw}': {e}")

        return jsonify({
            "status": "success",
            "folder": zdalny_katalog,
            "expires_at": zapisany_termin,
            "file_url": f"/static/output/{nazwa_pliku}",
        })

    except Exception as e:
        logging.error(f"Błąd generatora: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/")
def index_glowna():
    return """
    <h2>Radio Strefa Zero - Bot Aktywny 🚀</h2>
    <p>Pełny system automatyzacji radia, zegara z wyprzedzeniem, reklam z terminem, puli botów i mixów działa.</p>
    <ul>
        <li><a href="/jingles"><b>🎛️ Otwórz Generator Dżingli AI, Blok Reklamowy, Mikser i Logi</b></a></li>
        <li><a href="/generuj-godzine">Test generowania zapowiedzi godziny</a></li>
        <li><a href="/generuj-mix?folder=muzyka%20klubowa&count=3">Test generowania mixu (muzyka klubowa)</a></li>
    </ul>
    """


def _wykonaj_wstawke_i_wyslij(kwestie, folder_sftp, nazwa_pliku, bot_key="marek_standard"):
    profil = PULA_BOTOW.get(bot_key, PULA_BOTOW["marek_standard"])
    lokalny = generuj_audio_mp3(kwestie, nazwa_pliku, glos=profil["voice"], pitch=profil["pitch"], rate=profil["rate"])
    if not lokalny or not os.path.exists(lokalny):
        return False
    transport = None
    sftp = None
    try:
        transport, sftp = polacz_sftp()
        sftp.put(lokalny, f"{folder_sftp}/{nazwa_pliku}")
        logging.info(f"Wysłano automatyczną wstawkę do '{folder_sftp}/{nazwa_pliku}'.")
        return True
    finally:
        if os.path.exists(lokalny):
            try:
                os.remove(lokalny)
            except Exception:
                pass
        if sftp:
            try:
                sftp.close()
            except Exception:
                pass
        if transport:
            try:
                transport.close()
            except Exception:
                pass


_klucze_minuty = set()


def _raz_na_minute(klucz: str) -> bool:
    if klucz in _klucze_minuty:
        return False
    _klucze_minuty.add(klucz)
    if len(_klucze_minuty) > 800:
        _klucze_minuty.clear()
    return True


def petla_harmonogramu_w_tle():
    ostatnia_zapowiedziana_godzina = -1
    ostatni_mix_godzina = -1
    ostatnie_czyszczenie_ts = 0

    while True:
        try:
            teraz = datetime.now(STREFA_EUROPA)
            obecny_ts = time.time()
            hhmm = teraz.strftime("%H:%M")
            klucz_min = teraz.strftime("%Y-%m-%d %H:%M")
            czy_noc = teraz.hour >= 22 or teraz.hour < 6
            czy_weekend = teraz.weekday() in (4, 5, 6)

            if obecny_ts - ostatnie_czyszczenie_ts > 300:
                transport = None
                sftp = None
                try:
                    transport, sftp = polacz_sftp()
                    wyczysc_wygasle_reklamy(sftp)

                    usunieto_cos = False
                    foldery_do_czyszczenia = (
                        DIR_KONCERT_ZYCZEN,
                        DIR_PIOSENKA_NA_ZYCZENIE,
                        DIR_POBRANE,
                        DIR_PIOSENKI_DLA_SLUCHACZY,
                        DIR_GODZINA,
                        DIR_NEWS,
                    )
                    for folder_t in foldery_do_czyszczenia:
                        try:
                            for plik in sftp.listdir(folder_t):
                                if plik.endswith(".mp3"):
                                    sciezka_pliku = f"{folder_t}/{plik}"
                                    try:
                                        attr = sftp.stat(sciezka_pliku)
                                        if obecny_ts - attr.st_mtime > 7200:
                                            sftp.remove(sciezka_pliku)
                                            usunieto_cos = True
                                            logging.info(f"Usunięto przestarzały plik z serwera: {sciezka_pliku}")
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                    if usunieto_cos:
                        zsynchronizuj_azuracast()
                except Exception as e:
                    logging.error(f"Błąd czyszczenia plików: {e}")
                finally:
                    if sftp:
                        try:
                            sftp.close()
                        except Exception:
                            pass
                    if transport:
                        try:
                            transport.close()
                        except Exception:
                            pass
                ostatnie_czyszczenie_ts = obecny_ts

            if teraz.minute == 40:
                docelowa_godzina = (teraz.hour + 1) % 24
                if docelowa_godzina != ostatnia_zapowiedziana_godzina:
                    transport = None
                    sftp = None
                    try:
                        transport, sftp = polacz_sftp()
                        wyslano_cokolwiek = False

                        nazwa_pliku_godzina = f"godzina_{teraz.strftime('%Y%m%d_%H%M%S')}.mp3"
                        sciezka_g = generuj_audio_mp3(zbuduj_tylko_godzine(docelowa_godzina), nazwa_pliku_godzina)
                        if sciezka_g and os.path.exists(sciezka_g):
                            sftp.put(sciezka_g, f"{DIR_GODZINA}/{nazwa_pliku_godzina}")
                            os.remove(sciezka_g)
                            wyslano_cokolwiek = True
                            logging.info(f"Wysłano plik godziny do '{DIR_GODZINA}': {nazwa_pliku_godzina}")

                        if INFO_RMF_START <= docelowa_godzina < INFO_RMF_KONIEC:
                            kwestie_info = zbuduj_informacje_rmf()
                            if kwestie_info:
                                nazwa_pliku_info = f"news_{teraz.strftime('%Y%m%d_%H%M%S')}.mp3"
                                sciezka_i = generuj_audio_mp3(kwestie_info, nazwa_pliku_info, glos="pl-PL-ZofiaNeural", pitch="+0Hz", rate="+4%")
                                if sciezka_i and os.path.exists(sciezka_i):
                                    sftp.put(sciezka_i, f"{DIR_NEWS}/{nazwa_pliku_info}")
                                    os.remove(sciezka_i)
                                    wyslano_cokolwiek = True
                                    logging.info(f"Wysłano plik info do '{DIR_NEWS}': {nazwa_pliku_info}")

                        if docelowa_godzina == 7:
                            kwestie_poranek = zbuduj_poranny_serwis()
                            nazwa_poranek = f"poranek_{teraz.strftime('%Y%m%d')}.mp3"
                            sciezka_por = generuj_audio_mp3(kwestie_poranek, nazwa_poranek, glos="pl-PL-ZofiaNeural", pitch="-2Hz", rate="+0%")
                            if sciezka_por and os.path.exists(sciezka_por):
                                sftp.put(sciezka_por, f"{DIR_JINGLES}/{nazwa_poranek}")
                                os.remove(sciezka_por)
                                wyslano_cokolwiek = True
                                logging.info("Wysłano poranny serwis do folderu jingles.")

                        if docelowa_godzina == 17:
                            kwestie_koncert = [
                                ("glos", "Trwa codzienne pasmo Koncertu Życzeń w Radiu Strefa Zero!"),
                                ("glos", f"Zamawiaj piosenki i wysyłaj pozdrowienia darmowym SMS-em na numer: {NUMER_TEL_TEKST}. Gramy dla Was!"),
                            ]
                            nazwa_pliku_k = f"koncert_zapowiedz_{teraz.strftime('%Y%m%d')}.mp3"
                            sciezka_k = generuj_audio_mp3(kwestie_koncert, nazwa_pliku_k)
                            if sciezka_k and os.path.exists(sciezka_k):
                                sftp.put(sciezka_k, f"{DIR_KONCERT_ZYCZEN}/{nazwa_pliku_k}")
                                os.remove(sciezka_k)
                                wyslano_cokolwiek = True
                                logging.info(f"Wysłano zapowiedź Koncertu Życzeń: {nazwa_pliku_k}")

                        if wyslano_cokolwiek:
                            zsynchronizuj_azuracast()
                    finally:
                        if sftp:
                            try:
                                sftp.close()
                            except Exception:
                                pass
                        if transport:
                            try:
                                transport.close()
                            except Exception:
                                pass

                    ostatnia_zapowiedziana_godzina = docelowa_godzina

            if czy_noc and teraz.minute == 15 and _raz_na_minute(f"noc_{klucz_min}"):
                if _wykonaj_wstawke_i_wyslij(
                    [("glos", "Nocne Radio w Strefie Zero! Klubowe bity trwają całą noc — bawimy się do rana!")],
                    DIR_WSTAWKI_AI,
                    f"noc_{teraz.strftime('%H%M')}.mp3",
                    bot_key="marek_noc",
                ):
                    zsynchronizuj_azuracast()

            if hhmm == "12:15" and _raz_na_minute(f"kapsula_{klucz_min}"):
                lata = [1984, 1986, 1988, 1990, 1993, 1996, 1999]
                rok = lata[teraz.day % len(lata)]
                if _wykonaj_wstawke_i_wyslij(
                    [("glos", f"Kapsuła Czasu w Radiu Strefa Zero! Cofamy się do roku {rok} — sprawdzamy, co wtedy królowało na parkietach!")],
                    DIR_AUDYCJE_SPECJALNE,
                    f"kapsula_{teraz.strftime('%Y%m%d')}.mp3",
                    bot_key="marek_bas",
                ):
                    zsynchronizuj_azuracast()

            if teraz.weekday() == 4 and hhmm == "15:30" and _raz_na_minute(f"bitwa_start_{klucz_min}"):
                if _wykonaj_wstawke_i_wyslij(
                    [("glos", "Bitwa Gatunków w Radiu Strefa Zero! DYSKOTEKA kontra ITALO DISCO — wyślij SMS DYSKOTEKA albo ITALO!")],
                    DIR_WSTAWKI_AI,
                    f"bitwa_start_{teraz.strftime('%Y%m%d')}.mp3",
                    bot_key="marek_standard",
                ):
                    zsynchronizuj_azuracast()

            if teraz.weekday() == 4 and hhmm == "16:30" and _raz_na_minute(f"bitwa_wynik_{klucz_min}"):
                glosy = _wczytaj_glosy()
                zwyciezca = (
                    "Italo Disco" if glosy["ITALO"] > glosy["DYSKOTEKA"]
                    else ("Disco Polo" if glosy["DYSKOTEKA"] > glosy["ITALO"] else "remis")
                )
                tekst_w = (
                    f"Wynik Bitwy Gatunków w Radiu Strefa Zero: DYSKOTEKA {glosy['DYSKOTEKA']}, "
                    f"ITALO {glosy['ITALO']}. Wygrywa: {zwyciezca}!"
                )
                _zapisz_glosy({"DYSKOTEKA": 0, "ITALO": 0})
                if _wykonaj_wstawke_i_wyslij([("glos", tekst_w)], DIR_AUDYCJE_SPECJALNE, f"bitwa_wynik_{teraz.strftime('%Y%m%d')}.mp3", bot_key="zofia_standard"):
                    zsynchronizuj_azuracast()

            if hhmm in ("10:30", "14:30", "19:30") and _raz_na_minute(f"nostalgia_{klucz_min}"):
                if _wykonaj_wstawke_i_wyslij([("glos", random.choice(KACIK_NOSTALGII))], DIR_WSTAWKI_AI, f"nostalgia_{teraz.strftime('%Y%m%d_%H%M')}.mp3", bot_key="zofia_standard"):
                    zsynchronizuj_azuracast()

            if hhmm in ("13:20", "17:40", "21:10") and _raz_na_minute(f"kawal_{klucz_min}"):
                if _wykonaj_wstawke_i_wyslij([("glos", random.choice(KAWALY_TEKSTY))], DIR_WSTAWKI_AI, f"kawal_{teraz.strftime('%Y%m%d_%H%M')}.mp3", bot_key="marek_standard"):
                    zsynchronizuj_azuracast()

            if czy_weekend and hhmm in ("18:10", "20:10") and _raz_na_minute(f"weekend_{klucz_min}"):
                if _wykonaj_wstawke_i_wyslij([("glos", random.choice(KACIK_WEEKENDOWY))], DIR_WSTAWKI_AI, f"weekend_{teraz.strftime('%Y%m%d_%H%M')}.mp3", bot_key="marek_bas"):
                    zsynchronizuj_azuracast()

            if teraz.minute in (5, 35) and _raz_na_minute(f"dj_{klucz_min}"):
                kom_dj = pobierz_nowplaying_dj()
                if kom_dj and _wykonaj_wstawke_i_wyslij(
                    [("glos", kom_dj)],
                    DIR_WSTAWKI_AI,
                    f"dj_{teraz.strftime('%Y%m%d_%H%M')}.mp3",
                    bot_key="marek_noc" if czy_noc else "marek_standard",
                ):
                    zsynchronizuj_azuracast()

            if teraz.minute == 0 and teraz.hour % 4 == 0 and teraz.hour != ostatni_mix_godzina:
                folder_na_mix = "muzyka klubowa" if (teraz.hour >= 20 or teraz.hour < 6) else "disco polo dance"
                wygeneruj_mix_z_folderu(folder_gatunkowy=folder_na_mix, liczba_utworow=3, crossfade_ms=5000)
                ostatni_mix_godzina = teraz.hour

        except Exception as e:
            logging.error(f"Błąd w pętli głównej zegara: {e}")

        time.sleep(15)


watek_tlo = threading.Thread(target=petla_harmonogramu_w_tle, daemon=True)
watek_tlo.start()
logging.info(">>> Wątek automatyczny radia został uruchomiony! <<<")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
