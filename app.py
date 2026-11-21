import asyncio
from datetime import datetime
import json
import logging
import os
import random
import re
import subprocess
import threading
import time
from urllib.parse import quote
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import edge_tts
import feedparser
from flask import Flask, jsonify, render_template_string, request
import paramiko
from pydub import AudioSegment, effects
from pydub.generators import Sine
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
PLIK_HISTORIA_TEKSTOW = os.path.join(FOLDER_ROBOCZY, "historia_teksty.json")
PLIK_HISTORIA_POBRANYCH = os.path.join(FOLDER_ROBOCZY, "historia_pobranych.json")
PLIK_HISTORIA_KAWALY = os.path.join(FOLDER_ROBOCZY, "historia_kawaly.json")
PLIK_RAPORT_TYGODNIOWY = os.path.join(FOLDER_ROBOCZY, "raport_tygodniowy.json")
PLIK_RAPORT_TYGODNIOWY_TXT = os.path.join(FOLDER_ROBOCZY, "raport_tygodniowy.txt")

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

# Stały głos ElevenLabs (wybierasz raz w panelu ElevenLabs i wklejasz VOICE_ID do env)
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
ELEVENLABS_VOICE_ID_LOW = os.environ.get("ELEVENLABS_VOICE_ID_LOW", "").strip()
ELEVENLABS_MODEL_ID = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2").strip()

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
DIR_CIEKAWOSTKI = "ciekawostki"
DIR_NOCNE_RADIO = "nocne_radio"
DIR_RADIO = "radio"
DIR_KAWALY = "kawaly"

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
    DIR_CIEKAWOSTKI,
    DIR_NOCNE_RADIO,
    DIR_RADIO,
    DIR_KAWALY,
) + tuple(FOLDERY_GATUNKOWE)

STREFA_EUROPA = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Warsaw"))

INFO_RMF_DNI = (0, 1, 2, 3, 4, 5, 6)
INFO_RMF_START = 7
INFO_RMF_KONIEC = 23

NUMER_TEL_TEKST = "plus jeden, 812, 412, 29, siedemdziesiąt pięć"

PULA_BOTOW = {
    "marek_standard": {"name": "Marek (Klasyczny)", "voice": "pl-PL-MarekNeural", "pitch": 0, "rate": 0},
    "marek_bas": {"name": "Marek (Spokojny / Niski)", "voice": "pl-PL-MarekNeural", "pitch": -3, "rate": -5},
    "marek_noc": {"name": "Marek (Nocny Klub)", "voice": "pl-PL-MarekNeural", "pitch": -4, "rate": 2},
    "zofia_standard": {"name": "Zofia (Prezenterka)", "voice": "pl-PL-ZofiaNeural", "pitch": 0, "rate": 0},
    "zofia_news": {"name": "Zofia (Newsy)", "voice": "pl-PL-ZofiaNeural", "pitch": 0, "rate": 4},
}

PORANNE_WSTAWKI = [
    "Dobrego poranka w Radiu Strefa Zero! Startujemy z muzyką, która budzi lepiej niż poranna kawa.",
    "Nowy dzień w Radiu Strefa Zero! Podkręcamy brzmienie i lecimy dalej z dobrą energią.",
    "Poranna zmiana w Radiu Strefa Zero! Włączamy dobry nastrój od samego rana.",
]

KACIK_WEEKENDOWY = [
    "Weekendowy start w Radiu Strefa Zero! Podkręcamy głośność, zbijamy zmęczenie tygodnia i wjeżdżamy w imprezowy klimat!",
    "Piątek, sobota, niedziela — kiedy inni zwalniają, u nas wchodzi pełna energia i taneczne uderzenie prosto na parkiet!",
    "Weekend w Radiu Strefa Zero to mocne bity, świetne kawałki na życzenie i zero zamulania!",
]

NOCNE_WEJSCIA_KLUBOWE = [
    "Tu nocna strefa klubowa Radia Strefa Zero. Głęboki bas, mocny bit i muzyka, która trzyma na nogach, gdy miasto śpi.",
    "Nocne Radio w Strefie Zero trwa. Wchodzimy w nocny klimat klubowy — zostań z nami do samego rana!",
    "Środek nocy w Radiu Strefa Zero. Podkręcamy nocną selekcję i lecimy dalej z dobrym brzmieniem.",
    "Nocna zmiana w Radiu Strefa Zero! Klubowe uderzenie, zero pośpiechu i pełen ogień na głośnikach.",
]

KAWAŁY_MASZTALSKI_I_BACA = [
    (
        "Przychodzi baca do lekarza i mówi: Panie doktorze, jak się rano budzę, to mnie wszystko boli. "
        "Lekarz bada, bada i pyta: A o której się baca kładzie? "
        "A baca na to: Ano tak koło drugiej w nocy, jak już w telewizji nie ma na co patrzeć!"
    ),
    (
        "Spotykają się dwaj górale na hali. Jeden pyta: Słuchaj, Jędrek, czemu ty tak głośno gadasz do tej owcy? "
        "A Jędrek na to: Bo mi wczoraj powiedziała, że w tym roku wełna będzie droższa!"
    ),
    (
        "Baca kupił sobie nowy zegarek, co pokazuje godziny, minuty, sekundy i fazy księżyca. "
        "Wraca do chałupy, patrzy na niego i mówi do gaździny: Zośka, patrz! Miesiąc pełny, a my jeszcze węgla nie przywieźli!"
    ),
    (
        "Idzie baca przez las i widzi leżącą piłę motorową. Podnosi, ogląda, szarpie za sznurek — nic. "
        "Zaczyna szarpać mocniej, aż w końcu piła odpaliła: WRRRRR! "
        "Baca się przeżegnał i mówi: O cholera... sama się włączyła!"
    ),
    (
        "Siedzi baca na przyzbie i pyta wnuczka: Wnuku, a co to jest ten cały internet? "
        "Wnuczek tłumaczy: Dziadku, to taka wielka sieć, gdzie wszystko można znaleźć. "
        "Baca pokiwał głową: Aha... to dlatego moja gaździna zawsze mówi, że w sieci to najlepiej ryby biorą!"
    ),
]

KAWAŁY_O_JASIU = [
    (
        "Pani w szkole pyta Jasia: Jasiu, wymień trzy zwierzęta, które żyją na pustyni. "
        "Jasio myśli, myśli i mówi: Wielbłąd... i dwa inne wielbłądy!"
    ),
    (
        "Mama mówi do Jasia: Jasiu, idź umyj ręce przed obiadem. "
        "Jasio stoi przy kranie przez minutę i wraca. "
        "Mama patrzy i pyta: Przecież są suche! "
        "A Jasio na to: Bo ja je w powietrzu wysuszyłem, żeby nie kapało na podłogę!"
    ),
    (
        "Tata pyta Jasia: Jasiu, dlaczego masz jedynkę z matematyki? "
        "Jasio: Bo pani zadała pytanie, na które nikt nie znał odpowiedzi. "
        "Tata: Jakie? "
        "Jasio: Ile to jest siedem razy osiem? Przecież to się co chwilę zmienia!"
    ),
    (
        "Jasio wraca ze szkoły i mówi: Tato, dzisiaj byłem taki odważny, że aż mnie podziwiali! "
        "Tata dumny: Brawo synku! A co takiego zrobiłeś? "
        "Jasio: Podłożyłem nogę największemu chłopakowi w klasie i uciekłem za szafę!"
    ),
    (
        "Jasio patrzy, jak tata naprawia samochód, i pyta: Tato, a po co ten mechanik włożył głowę pod maskę? "
        "Tata: Szuka usterki, synku. "
        "Jasio: A jak znajdzie, to ją pogłaszcze czy z nią porozmawia?"
    ),
]

ZRODLA_KAWALOW_URL = [
    "https://www.dowcipy.pl/losowy.php",
    "https://dowcipy.jeja.pl/",
    "https://kwejk.pl/kategoria/dowcipy",
]

SPOTY_REKLAMOWE_BAZA = [
    (
        "Szukasz stacji, która gra bez nudy od rana do nocy? Włącz Radio Strefa Zero! "
        "Mocne bity, klubowe klimaty i dobra energia na każdy dzień. Zostań z nami!"
    ),
    (
        "Masz ulubiony kawałek i chcesz pozdrowić znajomych albo rodzinę? "
        f"Wyślij darmowego SMS-a na numer {NUMER_TEL_TEKST} i zagraj w Radiu Strefa Zero!"
    ),
    (
        "Chcesz, aby Twoja firma albo wydarzenie zaistniało na antenie Radia Strefa Zero? "
        "Nasz blok reklamowy dociera do słuchaczy, którzy kochają dobrą muzykę i świetny klimat. "
        "Skontaktuj się z redakcją Radia Strefa Zero!"
    ),
    (
        "Włączasz muzykę dla poprawy humoru? W Radiu Strefa Zero codziennie czekają świeże utwory, "
        "kawały z przymrużeniem oka i najświeższe informacje. Słuchaj nas bez przerwy!"
    ),
    (
        "Przełącz na wyższe obroty razem z Radiem Strefa Zero! "
        f"Zamawiaj piosenki, wysyłaj życzenia i baw się razem z nami pod numerem {NUMER_TEL_TEKST}."
    ),
]

PULA_POBIERANIA_DZIENNEGO = {
    "muzyka klubowa": [
        "HUGEL Imael Angel Ultra Nate Movin To The Sun",
        "ANOTR 54 Ultra Talk To You",
        "Ian Asher Olly Alexander Desire",
        "Prospa Cloonee Free Your Mind",
        "Martin Garrix This Dream Of You",
        "Swedish House Mafia Lykke Li Happiness Is So Sad",
        "Kygo Ava Max Before You Know It",
        "Mau P Just A Little Bit More",
        "Dom Dolla Solomun Skepta Danger Danger",
        "HUGEL David Guetta Shine",
        "Bebe Rexha Faithless New Religion",
        "Oskar Med K Haley Joelle I Think Im Addicted",
        "Jennifer Lopez David Guetta Save Me Tonight",
        "Martin Garrix Ed Sheeran Repeat It",
        "Peggy Gou Back Again",
        "CamelPhat Elderbrook Sun Comes Up",
    ],
    "disco polo": [
        "Zenek Martyniuk Akcent Przekorny los",
        "Boys Marcin Miller Szalona",
        "Classic Jolka Jolka",
        "Milano Bara bara",
        "Defis Niespotykany kolor",
        "Piekni i Mlodzi Niewiara",
        "Skolim Wyscigowka",
        "Bayer Full Blondyneczka",
        "Topky Szklanka",
        "Mig Wymarzona",
        "Cliver Chodz ze mna",
        "Long and Junior Tanczyc chce",
        "Czadoman Ruda tanczy jak szalona",
        "Slawek Uniatowski disco polo mix",
    ],
    "radio": [
        "Dua Lipa Illusion",
        "Sabrina Carpenter Espresso",
        "Ava Max My Oh My",
        "Kylie Minogue Padam Padam",
        "David Guetta OneRepublic I Dont Wanna Wait",
        "Alok Bebe Rexha Deep In Your Love",
        "Tiesto Karol G Contigo",
        "Purple Disco Machine Sophie and the Giants In The Dark",
        "Meduza James Carter Bad Memories",
        "Calvin Harris Ellie Goulding Miracle",
        "Roksana Wegiel Napisze do ciebie",
        "Doda Melodia tanczy",
        "Tribbs Ballady",
        "Zalewski Zabawa",
    ],
    "italo disco": [
        "Fancy Flames of Love",
        "Savage Goodbye",
        "Scotch Disco Band",
        "Bad Boys Blue Youre a Woman",
        "C.C. Catch Cause You Are Young",
        "Ken Laszlo Tonight",
        "Silver Pozzoli Around My Dream",
        "Righetti Spanioli Marina",
        "Gazebo I Like Chopin",
        "Den Harrow Mad Desire",
        "Baltimora Tarzan Boy",
        "Modern Talking Cheri Cheri Lady",
        "Lian Ross Say Youll Never",
        "Mike Mareen Love Spy",
    ],
    "disco polo dance": [
        "Playboys Ile lat",
        "After Party Bujaj sie",
        "D-Bomb O ela ela",
        "Vivat Moja malutka",
        "Etna Rolnik",
        "Marek Gwiazdowski Bzyk Bzyk",
        "Camasutra Sam na sam",
        "Mejk Zawsze i wszedzie",
        "Extazy Balujemy dzisiaj",
        "MilyPan Królowa",
        "Gesek Niby nic",
        "Wez Nie Pytaj Czekolada",
        "Kordian Dziewczyna z gor",
        "Baciary Oczy zielone",
    ],
}

DOZWOLONE_SKROTY = {"DJ", "FM", "MP3", "SMS", "TV", "VIP", "AI", "URL", "API", "SFTP", "BPM", "RSS", "TTS", "HQ", "HD"}

SLOWNIK_POLSKICH_SLOW = {
    "zeby": "żeby", "zyczenia": "życzenia", "zyczenie": "życzenie", "zyczen": "życzeń",
    "zycze": "życzę", "zyczymy": "życzymy", "pozdrowienia": "pozdrowienia", "pozdro": "pozdrowienia",
    "pozdrawiam": "pozdrawiam", "pozdrawiamy": "pozdrawiamy", "dzien": "dzień", "dzisiaj": "dzisiaj",
    "dzis": "dziś", "jutro": "jutro", "wczoraj": "wczoraj", "wieczor": "wieczór",
    "wieczorem": "wieczorem", "noca": "nocą", "nocne": "nocne", "nocny": "nocny",
    "nocna": "nocna", "rano": "rano", "polnoc": "północ", "poludnie": "południe",
    "godzina": "godzina", "godzine": "godzinę", "godziny": "godziny", "muzyka": "muzyka",
    "muzyke": "muzykę", "muzyki": "muzyki", "muzyczka": "muzyczka", "klubowa": "klubowa",
    "klubowy": "klubowy", "klubowe": "klubowe", "piosenka": "piosenka", "piosenke": "piosenkę",
    "piosenki": "piosenki", "piosenek": "piosenek", "utwor": "utwór", "utworze": "utworze",
    "utwory": "utwory", "wykonawca": "wykonawca", "wykonawce": "wykonawcę", "wykonawcy": "wykonawcy",
    "tytul": "tytuł", "tytulu": "tytułu", "tytuly": "tytuły", "sluchacz": "słuchacz",
    "sluchacza": "słuchacza", "sluchacze": "słuchacze", "sluchaczy": "słuchaczy",
    "sluchasz": "słuchasz", "sluchaj": "słuchaj", "sluchajcie": "słuchajcie",
    "dziekuje": "dziękuję", "dziekujemy": "dziękujemy", "dzieki": "dzięki", "prosze": "proszę",
    "urodziny": "urodziny", "urodzin": "urodzin", "imieniny": "imieniny", "imienin": "imienin",
    "mozna": "można", "moze": "może", "moga": "mogą", "trzeba": "trzeba",
    "zrobic": "zrobić", "zrobione": "zrobione", "zagrac": "zagrać", "zagramy": "zagramy",
    "gramy": "gramy", "gralismy": "graliśmy", "gralamy": "grałyśmy", "puscic": "puścić",
    "puscimy": "puścimy", "leci": "leci", "lecialo": "leciało", "leciala": "leciała",
    "lecialy": "leciały", "bedzie": "będzie", "beda": "będą", "jestes": "jesteś",
    "jestescie": "jesteście", "ktos": "ktoś", "cos": "coś", "nic": "nic",
    "nigdzie": "nigdzie", "zawsze": "zawsze", "czasem": "czasem", "czesto": "często",
    "bardzo": "bardzo", "duzo": "dużo", "malo": "mało", "troche": "trochę",
    "fajnie": "fajnie", "swietnie": "świetnie", "wspanialego": "wspaniałego",
    "wspanialy": "wspaniały", "wspaniala": "wspaniała", "najlepszego": "najlepszego",
    "najlepsze": "najlepsze", "najlepszych": "najlepszych", "caluski": "całuski",
    "pozdrowionka": "pozdrowionka", "impreza": "impreza", "imprezie": "imprezie",
    "imprezowy": "imprezowy", "parkiet": "parkiet", "parkiecie": "parkiecie",
    "parkiety": "parkiety", "radiu": "radiu", "radia": "radia", "strefa": "strefa",
    "strefie": "strefie", "zero": "zero", "zerze": "zerze", "sie": "się", "ze": "że",
    "tez": "też", "wiecej": "więcej", "jesli": "jeśli", "jezeli": "jeżeli",
    "wogole": "w ogóle", "narazie": "na razie", "poprostu": "po prostu",
    "naprawde": "naprawdę", "napewno": "na pewno", "odrazu": "od razu",
    "wsumie": "w sumie", "niewiem": "nie wiem", "nwm": "nie wiem",
    "wszystko": "wszystko", "wszystkiego": "wszystkiego", "wszyscy": "wszyscy",
    "wszystkich": "wszystkich", "ktory": "który", "ktora": "która",
    "ktore": "które", "ktorych": "których", "ktorego": "którego",
    "darmowy": "darmowy", "darmowym": "darmowym", "numer": "numer",
    "numerem": "numerem", "wyslij": "wyślij", "wyslac": "wysłać",
    "zamawiaj": "zamawiaj", "zamawiajcie": "zamawiajcie", "zamow": "zamów",
    "zamowic": "zamówić", "energia": "energia", "energii": "energii",
    "klimat": "klimat", "klimacie": "klimacie", "przelot": "przelot",
    "zmiana": "zmiana", "zmiane": "zmianę",
}

ROZBIJANIE_SKLEJONYCH = {
    "dobranoc": "dobra noc",
    "dziendobry": "dzień dobry",
    "wogole": "w ogóle",
    "narazie": "na razie",
    "poprostu": "po prostu",
    "naprawde": "naprawdę",
    "napewno": "na pewno",
    "odrazu": "od razu",
    "wsumie": "w sumie",
    "niewiem": "nie wiem",
    "costam": "coś tam",
}

terminy_lock = threading.Lock()
historia_lock = threading.Lock()
kawaly_lock = threading.Lock()
pobrane_lock = threading.Lock()


def _odpal_w_tle(fn, *args, **kwargs):
    def _runner():
        try:
            fn(*args, **kwargs)
        except Exception as exc:
            logging.error(f"Błąd zadania w tle ({fn.__name__}): {exc}")

    threading.Thread(target=_runner, daemon=True).start()


def _format_pitch(pitch) -> str:
    if isinstance(pitch, int):
        return f"{pitch:+d}Hz"
    s = str(pitch).strip()
    if not s:
        return "+0Hz"
    if s.endswith("Hz"):
        return s if s.startswith(("+", "-")) else f"+{s}"
    try:
        return f"{int(s):+d}Hz"
    except ValueError:
        return "+0Hz"


def _format_rate(rate) -> str:
    if isinstance(rate, int):
        return f"{rate:+d}%"
    s = str(rate).strip()
    if not s:
        return "+0%"
    if s.endswith("%"):
        return s if s.startswith(("+", "-")) else f"+{s}"
    try:
        return f"{int(s):+d}%"
    except ValueError:
        return "+0%"


def _wybierz_bez_powtorek(kategoria: str, pula: list[str]) -> str:
    if not pula:
        return ""
    if len(pula) == 1:
        return pula[0]
    with historia_lock:
        historia = {}
        if os.path.exists(PLIK_HISTORIA_TEKSTOW):
            try:
                with open(PLIK_HISTORIA_TEKSTOW, "r", encoding="utf-8") as f:
                    historia = json.load(f)
            except Exception:
                historia = {}
        ostatnie = historia.get(kategoria, [])
        dostepne = [x for x in pula if x not in ostatnie[-3:]] or list(pula)
        wybrany = random.choice(dostepne)
        ostatnie.append(wybrany)
        historia[kategoria] = ostatnie[-5:]
        try:
            with open(PLIK_HISTORIA_TEKSTOW, "w", encoding="utf-8") as f:
                json.dump(historia, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return wybrany


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
    if not sklejone:
        return ""
    if sklejone.upper() in DOZWOLONE_SKROTY:
        return sklejone.upper()
    low = sklejone.lower()
    if low in ROZBIJANIE_SKLEJONYCH:
        return ROZBIJANIE_SKLEJONYCH[low]
    return SLOWNIK_POLSKICH_SLOW.get(low, low)


def inteligentna_korekta(tekst: str, czy_sms: bool = False) -> str:
    if not tekst:
        return ""
    t = str(tekst).strip()
    t = re.sub(r"https?://\S+|www\.\S+", " ", t, flags=re.IGNORECASE)
    t = re.sub(r"\b[A-Za-z0-9_-]+\.(?:pl|com|net|org|eu|info|tv|fm|mp3|wav)\b", " ", t, flags=re.IGNORECASE)
    if czy_sms:
        t = re.sub(r"([*#_~=\-+<>])\1{1,}", " ", t)

    t = re.sub(
        r"(?<!\w)(?:[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż][\s\-\.]+){2,}[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż](?!\w)",
        _sklej_rozstrzelone,
        t,
    )
    t = re.sub(r"([A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż])\1{2,}", r"\1", t)

    wynik_slowa = []
    for s in t.split():
        m = re.match(r"^([^\wĄĆĘŁŃÓŚŹŻąćęłńóśźż]*)([\wĄĆĘŁŃÓŚŹŻąćęłńóśźż]+)([^\wĄĆĘŁŃÓŚŹŻąćęłńóśźż]*)$", s)
        if not m:
            wynik_slowa.append(s)
            continue
        pref, rdzen, suf = m.group(1), m.group(2), m.group(3)
        if rdzen.upper() in DOZWOLONE_SKROTY:
            wynik_slowa.append(f"{pref}{rdzen.upper()}{suf}")
            continue
        low = rdzen.lower()
        if low in ROZBIJANIE_SKLEJONYCH:
            wynik_slowa.append(f"{pref}{ROZBIJANIE_SKLEJONYCH[low]}{suf}")
            continue
        if low in SLOWNIK_POLSKICH_SLOW:
            poprawiony = SLOWNIK_POLSKICH_SLOW[low]
            if rdzen[0].isupper():
                poprawiony = poprawiony.capitalize()
            wynik_slowa.append(f"{pref}{poprawiony}{suf}")
        else:
            wynik_slowa.append(f"{pref}{rdzen}{suf}")

    wynik = " ".join(wynik_slowa)
    wynik = re.sub(r"[^0-9A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż\s,.!?\-–—:;]", " ", wynik)
    wynik = re.sub(r"\s+([,.!?:;])", r"\1", wynik)
    wynik = re.sub(r"\s{2,}", " ", wynik).strip(" ,.-–—")
    if wynik and wynik[-1] not in ".!?":
        wynik += "."
    return wynik


def oczysc_tekst_do_tts(tekst: str, czy_sms: bool = False) -> str:
    return inteligentna_korekta(tekst, czy_sms=czy_sms)


def oczysc_wykonawce_i_tytul(raw_text: str) -> str:
    if not raw_text:
        return ""
    s = str(raw_text).strip()
    s = re.sub(r"\.(mp3|wav|ogg|m4a|flac|aac)$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"https?://\S+|www\.\S+", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:wbt3|wbr3|mp3skull|chomikuj|zippyshare|ytmp3|savetube)\.[a-z]{2,6}\b", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\b[a-z0-9-]+\.(?:pl|com|net|org|eu|info|tv|fm)\b", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"[\[\(][^\]\)]*(?:wbt|wbr|www|http|official|video|audio|lyrics|remix|mix|edit|extended|radio\s*edit|hd|hq|kbps|320|128|prod\.?|feat\.?|ft\.?)[^\]\)]*[\]\)]", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:official\s*(?:video|audio|music\s*video)|lyric\s*video|lyrics|prod\.?\s*by\s*\S+|320\s*kbps|128\s*kbps|hq|hd)\b", " ", s, flags=re.IGNORECASE)
    s = s.replace("_", " ")
    s = re.sub(r"^\s*\d{1,3}[\s._\-–—]+", "", s)
    s = re.sub(r"\s*[-–—]{2,}\s*", " - ", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" -–—.,")
    return inteligentna_korekta(s).rstrip(".")


def pobierz_oryginalny_tytul_z_sieci(wykonawca_lub_fraza: str, tytul: str = "") -> tuple[str, str]:
    w_clean = oczysc_wykonawce_i_tytul(wykonawca_lub_fraza)
    t_clean = oczysc_wykonawce_i_tytul(tytul)

    if not t_clean and " - " in w_clean:
        czesci = w_clean.split(" - ", 1)
        w_clean = czesci[0].strip()
        t_clean = czesci[1].strip()

    fraza_szukana = f"{w_clean} {t_clean}".strip() if (w_clean and t_clean) else (t_clean or w_clean)
    if len(fraza_szukana) < 3:
        return w_clean, t_clean

    try:
        url = f"https://itunes.apple.com/search?term={quote(fraza_szukana)}&media=music&limit=1"
        resp = requests.get(url, timeout=6)
        if resp.status_code == 200:
            results = (resp.json() or {}).get("results") or []
            if results:
                artist_api = oczysc_wykonawce_i_tytul(results[0].get("artistName") or "")
                track_api = oczysc_wykonawce_i_tytul(results[0].get("trackName") or "")
                if artist_api and track_api:
                    return artist_api, track_api
                if track_api and not t_clean:
                    return w_clean, track_api
    except Exception as e:
        logging.debug(f"iTunes lookup pominięty dla '{fraza_szukana}': {e}")

    return w_clean, t_clean


def _wybierz_voice_id_elevenlabs(glos: str = "", pitch: str = "+0Hz", rate: str = "+0%", gruby_glos: bool = False) -> str:
    p_str = _format_pitch(pitch)
    r_str = _format_rate(rate)
    czy_niski = gruby_glos or p_str.startswith("-") or r_str.startswith("-") or ("bas" in (glos or "").lower()) or ("noc" in (glos or "").lower())
    if czy_niski and ELEVENLABS_VOICE_ID_LOW:
        return ELEVENLABS_VOICE_ID_LOW
    return ELEVENLABS_VOICE_ID


def _elevenlabs_zapisz(tekst: str, sciezka_mp3: str, voice_id_override: str = "", gruby_glos: bool = False) -> bool:
    voice_id = (voice_id_override or "").strip() or _wybierz_voice_id_elevenlabs(gruby_glos=gruby_glos)
    if not ELEVENLABS_API_KEY or not voice_id:
        return False
    try:
        stability = 0.55 if gruby_glos else 0.45
        similarity = 0.85 if gruby_glos else 0.75
        resp = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            json={
                "text": tekst,
                "model_id": ELEVENLABS_MODEL_ID,
                "voice_settings": {
                    "stability": stability,
                    "similarity_boost": similarity,
                    "style": 0.15 if gruby_glos else 0.0,
                    "use_speaker_boost": True,
                },
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
        logging.warning(f"ElevenLabs zwrócił status {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logging.warning(f"Błąd ElevenLabs: {e}")
    return False


def _obrob_glos_radiowy(sciezka_wejsciowa: str, gruby_glos: bool = False) -> str:
    if not os.path.exists(sciezka_wejsciowa):
        return sciezka_wejsciowa

    podstawowe_podbicie = 3.5 if gruby_glos else 2.0
    kompresja_ratio = "4" if gruby_glos else "3"
    temp_out = f"{sciezka_wejsciowa}.proc.mp3"
    af_filter = (
        f"highpass=f=80,"
        f"equalizer=f=120:width_type=h:width=80:g={podstawowe_podbicie},"
        f"acompressor=threshold=-18dB:ratio={kompresja_ratio}:attack=12:release=140:makeup=2dB,"
        f"loudnorm=I=-16:TP=-1.5:LRA=9"
    )
    try:
        res = subprocess.run(
            ["ffmpeg", "-y", "-i", sciezka_wejsciowa, "-af", af_filter, "-codec:a", "libmp3lame", "-q:a", "2", temp_out],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=25,
        )
        if res.returncode == 0 and os.path.exists(temp_out) and os.path.getsize(temp_out) > 512:
            os.replace(temp_out, sciezka_wejsciowa)
            return sciezka_wejsciowa
    except Exception as e:
        logging.debug(f"FFmpeg voice EQ pominięty: {e}")
    finally:
        if os.path.exists(temp_out):
            try:
                os.remove(temp_out)
            except Exception:
                pass

    try:
        seg = AudioSegment.from_file(sciezka_wejsciowa)
        seg = seg.high_pass_filter(80)
        if gruby_glos:
            seg = seg.low_pass_filter(14500)
        seg = effects.normalize(seg)
        seg.export(sciezka_wejsciowa, format="mp3")
    except Exception:
        pass
    return sciezka_wejsciowa


async def async_generuj_edge_tts(
    tekst,
    sciezka_docelowa,
    glos="pl-PL-MarekNeural",
    pitch="+0Hz",
    rate="+0%",
    silnik="auto",
    gruby_glos=False,
):
    uzyj_eleven = (silnik == "elevenlabs") or (silnik == "auto" and bool(ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID))
    if uzyj_eleven:
        voice_id = _wybierz_voice_id_elevenlabs(glos=glos, pitch=pitch, rate=rate, gruby_glos=gruby_glos)
        if _elevenlabs_zapisz(tekst, sciezka_docelowa, voice_id_override=voice_id, gruby_glos=gruby_glos):
            _obrob_glos_radiowy(sciezka_docelowa, gruby_glos=gruby_glos)
            return
        if silnik == "elevenlabs":
            raise RuntimeError("Nie udało się wygenerować głosu w ElevenLabs (sprawdź ELEVENLABS_API_KEY i ELEVENLABS_VOICE_ID).")

    pitch_str = _format_pitch(pitch)
    rate_str = _format_rate(rate)
    warianty = [
        (glos, pitch_str, rate_str),
        (glos, "+0Hz", rate_str),
        (glos, "+0Hz", "+0%"),
        ("pl-PL-MarekNeural", "+0Hz", "+0%"),
    ]
    ostatni_blad = None
    for v_name, p_s, r_s in warianty:
        try:
            communicate = edge_tts.Communicate(tekst, v_name, pitch=p_s, rate=r_s)
            await communicate.save(sciezka_docelowa)
            if os.path.exists(sciezka_docelowa) and os.path.getsize(sciezka_docelowa) > 0:
                _obrob_glos_radiowy(sciezka_docelowa, gruby_glos=gruby_glos)
                return
        except Exception as e:
            ostatni_blad = e
            logging.warning(f"Edge-TTS próba ({v_name}, pitch={p_s}, rate={r_s}) nieudana: {e}")
            continue

    if ostatni_blad:
        raise ostatni_blad


def _generuj_pik_audio() -> AudioSegment:
    piki = AudioSegment.empty()
    krotki_pik = Sine(1000).to_audio_segment(duration=110).apply_gain(-12).fade_in(10).fade_out(15)
    dlugi_pik = Sine(1350).to_audio_segment(duration=260).apply_gain(-11).fade_in(10).fade_out(30)
    przerwa = AudioSegment.silent(duration=490)
    for _ in range(4):
        piki += krotki_pik + przerwa
    piki += dlugi_pik + AudioSegment.silent(duration=350)
    return piki


def generuj_audio_mp3(
    lista_kwestii,
    nazwa_pliku_koncowego,
    glos="pl-PL-MarekNeural",
    pitch="+0Hz",
    rate="+0%",
    czy_sms=False,
    liczba_pikow_na_poczatku=0,
    silnik="auto",
    gruby_glos=False,
):
    sciezka_koncowa = os.path.join(FOLDER_ROBOCZY, nazwa_pliku_koncowego)
    pliki_tymczasowe = []
    try:
        for idx, (_, tekst) in enumerate(lista_kwestii):
            oczyszczony = oczysc_tekst_do_tts(tekst or "", czy_sms=czy_sms)
            if not oczyszczony:
                continue
            temp_path = os.path.join(FOLDER_ROBOCZY, f"temp_{idx}_{nazwa_pliku_koncowego}")
            uruchom_async(
                async_generuj_edge_tts(
                    oczyszczony,
                    temp_path,
                    glos,
                    pitch=pitch,
                    rate=rate,
                    silnik=silnik,
                    gruby_glos=gruby_glos,
                )
            )
            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                pliki_tymczasowe.append(temp_path)

        if not pliki_tymczasowe:
            return None

        polaczony_segment = AudioSegment.empty()
        if liczba_pikow_na_poczatku >= 5:
            polaczony_segment += _generuj_pik_audio()

        cisza = AudioSegment.silent(duration=450)
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


def pobierz_swieze_naglowki_rmf(limit: int = 12) -> list[str]:
    teraz = datetime.now(STREFA_EUROPA)
    if teraz.weekday() not in INFO_RMF_DNI or not (INFO_RMF_START <= teraz.hour < INFO_RMF_KONIEC):
        return []
    try:
        cache_buster = int(time.time())
        url_rss = f"https://www.rmf24.pl/fakty/rss?v={cache_buster}"
        feed = feedparser.parse(url_rss, agent="Mozilla/5.0 RadioStrefaZeroBot/1.0")
        naglowki = []
        seen = set()
        if getattr(feed, "entries", None):
            for entry in feed.entries:
                tytul = oczysc_wykonawce_i_tytul((entry.get("title") or "").strip())
                opis = oczysc_wykonawce_i_tytul((entry.get("summary") or "").strip())
                wpis = tytul
                if opis and opis.lower() != tytul.lower() and len(opis) < 220:
                    wpis = f"{tytul}. {opis}"
                klucz = re.sub(r"\W+", "", tytul.lower())
                if tytul and klucz and klucz not in seen:
                    seen.add(klucz)
                    naglowki.append(wpis)
                if len(naglowki) >= limit:
                    break
        return naglowki
    except Exception as e:
        logging.error(f"Błąd pobierania świeżych newsów RMF: {e}")
        return []


def pobierz_aktualne_newsy_rmf():
    naglowki = pobierz_swieze_naglowki_rmf(limit=3)
    if naglowki:
        return "Najświeższe informacje z RMF FM: " + " ".join(naglowki)
    return ""


def wygeneruj_i_wyslij_news_5min(czas_trwania_sek: int = 150) -> str | None:
    teraz = datetime.now(STREFA_EUROPA)
    naglowki = pobierz_swieze_naglowki_rmf(limit=6)
    if not naglowki:
        logging.warning("Brak świeżych nagłówków RMF FM do wygenerowania serwisu news.")
        return None

    kwestie = [
        ("glos", f"Najnowsze wiadomości w Radiu Strefa Zero, godzina {teraz.strftime('%H:%M')}. Przegląd informacji z RMF FM."),
    ]
    laczna_dlugosc = len(kwestie[0][1])
    limit_znakow = max(900, int(czas_trwania_sek * 11.0))

    idx = 0
    while laczna_dlugosc < limit_znakow and idx < len(naglowki) * 2:
        bazowy = naglowki[idx % len(naglowki)]
        tekst = f"Kolejna informacja z RMF FM: {bazowy}" if idx < len(naglowki) else f"Przypominamy: {bazowy}"
        kwestie.append(("glos", tekst))
        laczna_dlugosc += len(tekst)
        idx += 1

    kwestie.append(("glos", f"To były informacje w Radiu Strefa Zero. Numer SMS: {NUMER_TEL_TEKST}."))

    nazwa_pliku = f"news_{teraz.strftime('%Y%m%d_%H%M%S')}.mp3"
    sciezka_n = generuj_audio_mp3(kwestie, nazwa_pliku, glos="pl-PL-ZofiaNeural", pitch="+0Hz", rate="+4%")
    if not sciezka_n or not os.path.exists(sciezka_n):
        return None

    transport = None
    sftp = None
    try:
        transport, sftp = polacz_sftp()
        zdalna_sciezka = f"{DIR_NEWS}/{nazwa_pliku}"
        wyslij_i_zsynchronizuj(sftp, sciezka_n, zdalna_sciezka)
        logging.info(f"Wysłano serwis news do '{zdalna_sciezka}'.")
        return zdalna_sciezka
    except Exception as e:
        logging.error(f"Błąd wysyłania serwisu news: {e}")
        return None
    finally:
        if os.path.exists(sciezka_n):
            try:
                os.remove(sciezka_n)
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


def wygeneruj_i_wyslij_blok_reklamowy_3min(czas_trwania_sek: int = 120) -> str | None:
    teraz = datetime.now(STREFA_EUROPA)
    pula_spotow = list(SPOTY_REKLAMOWE_BAZA)
    random.shuffle(pula_spotow)

    kwestie = [
        ("glos", "Blok reklamowy i ogłoszenia w Radiu Strefa Zero."),
    ]
    laczna_dlugosc = len(kwestie[0][1])
    limit_znakow = max(750, int(czas_trwania_sek * 11.0))

    ostatni_spot = ""
    nr = 1
    while laczna_dlugosc < limit_znakow and nr <= 6:
        kandydaci = [s for s in pula_spotow if s != ostatni_spot] or pula_spotow
        spot = random.choice(kandydaci)
        ostatni_spot = spot
        kwestie.append(("glos", f"Ogłoszenie {nr}. {spot}"))
        laczna_dlugosc += len(spot) + 20
        nr += 1

    kwestie.append(("glos", "Koniec bloku reklamowego w Radiu Strefa Zero."))

    nazwa_pliku = f"reklama_3min_{teraz.strftime('%Y%m%d_%H%M%S')}.mp3"
    sciezka_r = generuj_audio_mp3(kwestie, nazwa_pliku, glos="pl-PL-MarekNeural", pitch="-1Hz", rate="+2%", gruby_glos=True)
    if not sciezka_r or not os.path.exists(sciezka_r):
        return None

    transport = None
    sftp = None
    try:
        transport, sftp = polacz_sftp()
        zdalna_sciezka = f"{DIR_BLOK_REKLAMOWY}/{nazwa_pliku}"
        wyslij_i_zsynchronizuj(sftp, sciezka_r, zdalna_sciezka)
        logging.info(f"Wysłano blok reklamowy do '{zdalna_sciezka}'.")
        return zdalna_sciezka
    except Exception as e:
        logging.error(f"Błąd wysyłania bloku reklamowego: {e}")
        return None
    finally:
        if os.path.exists(sciezka_r):
            try:
                os.remove(sciezka_r)
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
    czyste = oczysc_wykonawce_i_tytul(zapytanie)
    slowa_kluczowe = [s.lower() for s in re.findall(r"\w+", czyste) if len(s) > 2]
    if not slowa_kluczowe:
        return None

    foldery_do_sprawdzenia = (
        tuple(FOLDERY_GATUNKOWE)
        + (DIR_RADIO, DIR_POBRANE, DIR_PIOSENKI_DLA_SLUCHACZY, DIR_KONCERT_ZYCZEN, DIR_PIOSENKA_NA_ZYCZENIE, DIR_JINGLES, ".")
    )
    for folder in foldery_do_sprawdzenia:
        try:
            pliki = sftp.listdir(folder)
            for plik in pliki:
                if plik.lower().endswith(".mp3"):
                    nazwa_oczyszczona = oczysc_wykonawce_i_tytul(plik).lower()
                    if all(slowo in nazwa_oczyszczona for slowo in slowa_kluczowe):
                        return f"{folder}/{plik}" if folder != "." else plik
        except Exception:
            continue
    return None


def _normalizuj_klucz_utworu(nazwa: str) -> str:
    czyste = oczysc_wykonawce_i_tytul(nazwa).lower()
    czyste = re.sub(r"\b(top_klub|auto_pobrane|202\d{5}|_\d{6})\b", " ", czyste)
    tokeny = [t for t in re.findall(r"[a-ząćęłńóśźż0-9]+", czyste) if len(t) > 1]
    return " ".join(sorted(set(tokeny)))


def _wczytaj_historie_pobranych() -> dict:
    with pobrane_lock:
        if not os.path.exists(PLIK_HISTORIA_POBRANYCH):
            return {}
        try:
            with open(PLIK_HISTORIA_POBRANYCH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


def _zapisz_historie_pobranych(dane: dict) -> None:
    with pobrane_lock:
        try:
            with open(PLIK_HISTORIA_POBRANYCH, "w", encoding="utf-8") as f:
                json.dump(dane, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Błąd zapisu historii pobranych: {e}")


def _dopisz_do_raportu_tygodniowego(folder: str, tytul: str) -> None:
    teraz = datetime.now(STREFA_EUROPA)
    with pobrane_lock:
        dane = {"wpisy": []}
        if os.path.exists(PLIK_RAPORT_TYGODNIOWY):
            try:
                with open(PLIK_RAPORT_TYGODNIOWY, "r", encoding="utf-8") as f:
                    dane = json.load(f) or {"wpisy": []}
            except Exception:
                dane = {"wpisy": []}

        dane.setdefault("wpisy", []).append({
            "data": teraz.strftime("%Y-%m-%d %H:%M"),
            "folder": folder,
            "tytul": tytul,
        })
        try:
            with open(PLIK_RAPORT_TYGODNIOWY, "w", encoding="utf-8") as f:
                json.dump(dane, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Błąd zapisu raportu tygodniowego JSON: {e}")


def generuj_i_zapisz_raport_tygodniowy() -> str:
    teraz = datetime.now(STREFA_EUROPA)
    with pobrane_lock:
        dane = {"wpisy": []}
        if os.path.exists(PLIK_RAPORT_TYGODNIOWY):
            try:
                with open(PLIK_RAPORT_TYGODNIOWY, "r", encoding="utf-8") as f:
                    dane = json.load(f) or {"wpisy": []}
            except Exception:
                dane = {"wpisy": []}

        wpisy = dane.get("wpisy") or []
        po_folderach = {}
        for item in wpisy:
            fld = item.get("folder", "inne")
            po_folderach.setdefault(fld, []).append(item)

        linie = [
            f"=== TYGODNIOWY RAPORT POBRANYCH UTWORÓW ({teraz.strftime('%Y-%m-%d %H:%M')}) ===",
            f"Łącznie pobrano w tym cyklu: {len(wpisy)} utworów.",
            "",
        ]
        for fld in ("muzyka klubowa", "disco polo", "radio", "italo disco", "disco polo dance"):
            lista_fld = po_folderach.get(fld, [])
            linie.append(f"[{fld}] ({len(lista_fld)}):")
            if not lista_fld:
                linie.append("  - brak nowych utworów w tym okresie")
            else:
                for idx, w in enumerate(lista_fld, start=1):
                    linie.append(f"  {idx}. {w.get('tytul')} ({w.get('data')})")
            linie.append("")

        tresc_raportu = "\n".join(linie).strip()
        try:
            with open(PLIK_RAPORT_TYGODNIOWY_TXT, "w", encoding="utf-8") as f:
                f.write(tresc_raportu + "\n")
        except Exception as e:
            logging.error(f"Błąd zapisu raportu tygodniowego TXT: {e}")

        logging.info("\n" + tresc_raportu)
        return tresc_raportu


def wyczysc_raport_tygodniowy_po_wyslaniu() -> None:
    with pobrane_lock:
        try:
            with open(PLIK_RAPORT_TYGODNIOWY, "w", encoding="utf-8") as f:
                json.dump({"wpisy": []}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


def pobierz_piosenke_z_sieci(zapytanie, nazwa_docelowa_bez_rozsz):
    czyste_zapytanie = oczysc_wykonawce_i_tytul(zapytanie) or zapytanie
    baza_nazwy = os.path.join(FOLDER_ROBOCZY, nazwa_docelowa_bez_rozsz)
    warianty_zapytan = [
        f"ytsearch1:{czyste_zapytanie} audio",
        f"scsearch1:{czyste_zapytanie}",
        f"ytsearch1:{czyste_zapytanie}",
    ]

    opcje_ytdlp = {
        "format": "bestaudio/best",
        "outtmpl": f"{baza_nazwy}.%(ext)s",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 12,
        "retries": 1,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "128",
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
            logging.warning(f"Pominięto źródło yt-dlp dla '{query}': {e}")
            continue
    return None


def pobierz_3_nowe_do_folderu(folder_docelowy: str, liczba_nowych: int = 2) -> list[str]:
    pula = list(PULA_POBIERANIA_DZIENNEGO.get(folder_docelowy) or [])
    if not pula:
        return []

    historia = _wczytaj_historie_pobranych()
    pobrane_klucze = set(historia.get(folder_docelowy) or [])

    transport = None
    sftp = None
    dodane_tytuly = []

    try:
        transport, sftp = polacz_sftp()
        try:
            pliki_w_folderze = [f for f in sftp.listdir(folder_docelowy) if f.lower().endswith(".mp3")]
        except Exception:
            pliki_w_folderze = []

        klucze_w_folderze = {_normalizuj_klucz_utworu(p) for p in pliki_w_folderze if _normalizuj_klucz_utworu(p)}
        wszystkie_zajete_klucze = pobrane_klucze | klucze_w_folderze

        random.shuffle(pula)
        znacznik = datetime.now(STREFA_EUROPA).strftime("%Y%m%d_%H%M%S")

        for idx, fraza in enumerate(pula):
            if len(dodane_tytuly) >= liczba_nowych:
                break

            w_orig, t_orig = pobierz_oryginalny_tytul_z_sieci(fraza)
            etykieta = f"{w_orig} — {t_orig}" if (w_orig and t_orig) else (t_orig or w_orig or fraza)
            klucz_kandydata = _normalizuj_klucz_utworu(etykieta)
            klucz_frazy = _normalizuj_klucz_utworu(fraza)

            if (klucz_kandydata and klucz_kandydata in wszystkie_zajete_klucze) or (
                klucz_frazy and klucz_frazy in wszystkie_zajete_klucze
            ):
                continue

            slug = re.sub(r"[^A-Za-z0-9]+", "_", etykieta).strip("_")[:42] or f"utwor_{idx}"
            nazwa_bez_rozsz = f"{slug}_{znacznik}_{idx}"
            lokalny_mp3 = pobierz_piosenke_z_sieci(etykieta or fraza, nazwa_bez_rozsz)

            if lokalny_mp3 and os.path.exists(lokalny_mp3):
                zdalna_sciezka = f"{folder_docelowy}/{nazwa_bez_rozsz}.mp3"
                sftp.put(lokalny_mp3, zdalna_sciezka)
                os.remove(lokalny_mp3)

                dodane_tytuly.append(etykieta)
                if klucz_kandydata:
                    wszystkie_zajete_klucze.add(klucz_kandydata)
                    pobrane_klucze.add(klucz_kandydata)
                if klucz_frazy:
                    wszystkie_zajete_klucze.add(klucz_frazy)
                    pobrane_klucze.add(klucz_frazy)

                _dopisz_do_raportu_tygodniowego(folder_docelowy, etykieta)
                logging.info(f"[AUTO-POBIERANIE] '{etykieta}' -> '{zdalna_sciezka}'")

        historia[folder_docelowy] = list(pobrane_klucze)[-500:]
        _zapisz_historie_pobranych(historia)

        if dodane_tytuly:
            zsynchronizuj_azuracast()

        return dodane_tytuly
    except Exception as e:
        logging.error(f"Błąd pobierania utworów do '{folder_docelowy}': {e}")
        return dodane_tytuly
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


def uruchom_codzienne_pobieranie_wszystkich_folderow(liczba_na_folder: int = 2) -> dict:
    foldery_docelowe = ["muzyka klubowa", "disco polo", "radio", "italo disco", "disco polo dance"]
    podsumowanie = {}
    for folder in foldery_docelowe:
        pobrane = pobierz_3_nowe_do_folderu(folder, liczba_nowych=liczba_na_folder)
        podsumowanie[folder] = pobrane
        logging.info(f"[DZIENNE POBIERANIE] Folder '{folder}': pobrano {len(pobrane)}/{liczba_na_folder} -> {pobrane}")
    return podsumowanie


def _generuj_smiech_i_brawa() -> AudioSegment:
    wlasny_plik = os.path.join(DIR_STATIC_MUSIC, "smiech_brawa.mp3")
    if os.path.exists(wlasny_plik) and os.path.getsize(wlasny_plik) > 1024:
        try:
            return effects.normalize(AudioSegment.from_file(wlasny_plik)[:2400]).fade_in(100).fade_out(250)
        except Exception:
            pass

    rng = random.Random(int(time.time() * 1000) % 100000)
    brawa = AudioSegment.silent(duration=0)
    for step in range(18):
        dl = rng.randint(35, 65)
        szum = AudioSegment.from_mono_audiosegments(
            Sine(rng.randint(420, 980)).to_audio_segment(duration=dl)
        ).high_pass_filter(500).low_pass_filter(3200)
        gain_step = -26 + min(12, step * 0.5) + rng.uniform(-2.5, 2.0)
        brawa += szum.apply_gain(gain_step).fade_in(5).fade_out(10) + AudioSegment.silent(duration=rng.randint(25, 60))

    smiech = AudioSegment.silent(duration=0)
    for _ in range(3):
        fala_seg = AudioSegment.silent(duration=0)
        base_freq = rng.randint(185, 255)
        for _ in range(rng.randint(3, 5)):
            sylaba = Sine(base_freq + rng.randint(-15, 15)).to_audio_segment(duration=100)
            sylaba = sylaba.low_pass_filter(1400).apply_gain(-16 + rng.uniform(-2.0, 2.0)).fade_in(15).fade_out(30)
            fala_seg += sylaba + AudioSegment.silent(duration=65)
        smiech += fala_seg + AudioSegment.silent(duration=120)

    polaczone = brawa.overlay(smiech, position=200)
    return effects.normalize(polaczone).fade_in(80).fade_out(200) - 4


def _klucz_kawalu(tekst: str) -> str:
    return re.sub(r"\s+", " ", (tekst or "").strip().lower())


def _wczytaj_historie_kawaly() -> list[str]:
    if not os.path.exists(PLIK_HISTORIA_KAWALY):
        return []
    try:
        with open(PLIK_HISTORIA_KAWALY, "r", encoding="utf-8") as f:
            dane = json.load(f)
            return [str(x) for x in dane] if isinstance(dane, list) else []
    except Exception:
        return []


def _zapisz_historie_kawaly(lista: list[str]) -> None:
    try:
        with open(PLIK_HISTORIA_KAWALY, "w", encoding="utf-8") as f:
            json.dump(lista[-1500:], f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Błąd zapisu historii kawałów: {e}")


def pobierz_kawaly_z_sieci(urls: list[str] | None = None, max_z_zrodla: int = 15) -> list[str]:
    zrodla = urls or ZRODLA_KAWALOW_URL
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }
    zebrane: list[str] = []
    widziane_w_pobraniu: set[str] = set()

    for url in zrodla:
        try:
            resp = requests.get(url, headers=headers, timeout=6)
            if resp.status_code != 200 or not resp.text:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
                tag.decompose()

            kandydaci: list[str] = []
            for el in soup.find_all(["p", "div", "article", "blockquote"]):
                oczyszczony = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
                if 55 <= len(oczyszczony) <= 800:
                    kandydaci.append(oczyszczony)

            random.shuffle(kandydaci)
            dodane_z_url = 0

            for tekst in kandydaci:
                klucz = _klucz_kawalu(tekst)
                if not klucz or klucz in widziane_w_pobraniu:
                    continue
                if any(
                    smiec in klucz
                    for smiec in (
                        "cookies",
                        "polityka prywatności",
                        "regulamin",
                        "zaloguj",
                        "zarejestruj",
                        "wszystkie prawa zastrzeżone",
                        "reklama",
                    )
                ):
                    continue

                widziane_w_pobraniu.add(klucz)
                zebrane.append(tekst)
                dodane_z_url += 1
                if dodane_z_url >= max_z_zrodla:
                    break

        except Exception as e:
            logging.warning(f"[KAWALY] Błąd pobierania z '{url}': {e}")

    return zebrane


def _filtruj_temat_kawaly(pula: list[str], rodzaj: str) -> list[str]:
    rodzaj_norm = (rodzaj or "").strip().lower()
    if rodzaj_norm in ("masztalski", "baca", "goral", "góral", "klub_masztalskiego"):
        slowa = ("baca", "góral", "goral", "masztalski", "halny", "owiecz", "bacówka", "ceper", "gaździn")
    elif rodzaj_norm in ("jas", "jasio", "kacik_jasia", "kącik_jasia"):
        slowa = ("jasio", "jasiu", "pani", "nauczyciel", "mama", "tata")
    else:
        slowa = ()

    if not slowa:
        return list(pula)

    pasujace = [k for k in pula if any(s in k.lower() for s in slowa)]
    if len(pasujace) < 3:
        reszta = [k for k in pula if k not in pasujace]
        random.shuffle(reszta)
        pasujace.extend(reszta)
    return pasujace


def wybierz_kawaly_bez_powtorek(rodzaj: str = "masztalski", ile_maks: int = 8) -> list[str]:
    with kawaly_lock:
        historia = _wczytaj_historie_kawaly()
        uzyte_w_historii = set(historia)
        uzyte_w_audycji: set[str] = set()
        wybrane: list[str] = []

        pobrane_z_sieci = pobierz_kawaly_z_sieci()
        zapas = list(KAWAŁY_O_JASIU) if (rodzaj or "").lower() in ("jas", "jasio") else list(KAWAŁY_MASZTALSKI_I_BACA)
        random.shuffle(zapas)

        pula_tematyczna = _filtruj_temat_kawaly(pobrane_z_sieci, rodzaj) + zapas
        pula_ogolna = list(pobrane_z_sieci) + list(KAWAŁY_MASZTALSKI_I_BACA) + list(KAWAŁY_O_JASIU)

        for k in pula_tematyczna:
            klucz = _klucz_kawalu(k)
            if not klucz or klucz in uzyte_w_audycji or klucz in uzyte_w_historii:
                continue
            wybrane.append(k)
            uzyte_w_audycji.add(klucz)
            if len(wybrane) >= ile_maks:
                break

        if len(wybrane) < ile_maks:
            for k in pula_ogolna:
                klucz = _klucz_kawalu(k)
                if not klucz or klucz in uzyte_w_audycji or klucz in uzyte_w_historii:
                    continue
                wybrane.append(k)
                uzyte_w_audycji.add(klucz)
                if len(wybrane) >= ile_maks:
                    break

        if len(wybrane) < min(4, ile_maks):
            uzyte_w_historii.clear()
            for k in pula_tematyczna + pula_ogolna:
                klucz = _klucz_kawalu(k)
                if not klucz or klucz in uzyte_w_audycji:
                    continue
                wybrane.append(k)
                uzyte_w_audycji.add(klucz)
                if len(wybrane) >= ile_maks:
                    break

        nowa_historia = list(historia)
        for k in wybrane:
            klucz = _klucz_kawalu(k)
            if klucz:
                nowa_historia.append(klucz)
        _zapisz_historie_kawaly(nowa_historia)

        logging.info(
            f"[KAWALY] Pobrano z sieci: {len(pobrane_z_sieci)}, wybrano unikalnych ({rodzaj}): {len(wybrane)}"
        )
        return wybrane


def zbuduj_audycje_kawaly(rodzaj: str = "masztalski", czas_trwania_sek: int = 120) -> list[tuple[str, str]]:
    if rodzaj == "jas":
        powitanie = "Witajcie w Kąciku Jasia w Radiu Strefa Zero!"
        pozegnanie = "To by było na tyle w Kąciku Jasia w Radiu Strefa Zero!"
    else:
        powitanie = "Witajcie w Klubie Masztalskiego w Radiu Strefa Zero!"
        pozegnanie = "Koniec audycji Klub Masztalskiego w Radiu Strefa Zero!"

    pula = wybierz_kawaly_bez_powtorek(rodzaj=rodzaj, ile_maks=6)
    kwestie = [("glos", powitanie)]
    laczna_dlugosc = len(powitanie)
    limit_znakow = max(650, int(czas_trwania_sek * 10.0))

    uzyte_klucze: set[str] = set()
    for kawal in pula:
        klucz = _klucz_kawalu(kawal)
        if not klucz or klucz in uzyte_klucze:
            continue
        uzyte_klucze.add(klucz)
        kwestie.append(("kawal", kawal))
        laczna_dlugosc += len(kawal)
        if laczna_dlugosc >= limit_znakow:
            break

    kwestie.append(("glos", pozegnanie))
    return kwestie


def wygeneruj_i_wyslij_audycje_kawaly(rodzaj: str = "masztalski", czas_trwania_sek: int = 120) -> str | None:
    kwestie = zbuduj_audycje_kawaly(rodzaj=rodzaj, czas_trwania_sek=czas_trwania_sek)
    znacznik = datetime.now(STREFA_EUROPA).strftime("%Y%m%d_%H%M%S")
    prefix = "klub_masztalskiego" if rodzaj != "jas" else "kacik_jasia"
    nazwa_pliku = f"{prefix}_{znacznik}.mp3"
    sciezka_koncowa = os.path.join(FOLDER_ROBOCZY, nazwa_pliku)

    profil = PULA_BOTOW["marek_bas"] if rodzaj != "jas" else PULA_BOTOW["marek_standard"]
    reakcja_pub = _generuj_smiech_i_brawa()
    cisza = AudioSegment.silent(duration=300)
    pliki_tymczasowe = []

    try:
        polaczony = AudioSegment.empty()
        for idx, (typ_kwestii, tekst) in enumerate(kwestie):
            oczyszczony = oczysc_tekst_do_tts(tekst, czy_sms=False)
            if not oczyszczony:
                continue
            temp_path = os.path.join(FOLDER_ROBOCZY, f"kaw_{idx}_{nazwa_pliku}")
            uruchom_async(
                async_generuj_edge_tts(
                    oczyszczony,
                    temp_path,
                    profil["voice"],
                    pitch=profil["pitch"],
                    rate=profil["rate"],
                    silnik="auto",
                    gruby_glos=(rodzaj != "jas"),
                )
            )
            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                pliki_tymczasowe.append(temp_path)
                seg = AudioSegment.from_file(temp_path)
                polaczony += seg + cisza
                if typ_kwestii == "kawal":
                    polaczony += reakcja_pub + cisza

        if len(polaczony) == 0:
            return None

        polaczony = effects.normalize(polaczony)
        polaczony.export(sciezka_koncowa, format="mp3", bitrate="128k")

        transport, sftp = polacz_sftp()
        try:
            zdalna_sciezka = f"{DIR_KAWALY}/{nazwa_pliku}"
            wyslij_i_zsynchronizuj(sftp, sciezka_koncowa, zdalna_sciezka)
            logging.info(f"Wysłano audycję '{prefix}' do '{zdalna_sciezka}'.")
            return zdalna_sciezka
        finally:
            sftp.close()
            transport.close()
    except Exception as e:
        logging.error(f"Błąd generowania audycji kawałów '{rodzaj}': {e}")
        return None
    finally:
        if os.path.exists(sciezka_koncowa):
            try:
                os.remove(sciezka_koncowa)
            except Exception:
                pass
        for f_tmp in pliki_tymczasowe:
            if os.path.exists(f_tmp):
                try:
                    os.remove(f_tmp)
                except Exception:
                    pass


def _godziny_kawaly_co_40_min() -> set[str]:
    terminy = {"06:05", "08:05"}
    start_min = 12 * 60 + 7
    koniec_min = 16 * 60 + 54
    m = start_min
    while m <= koniec_min:
        terminy.add(f"{m // 60:02d}:{m % 60:02d}")
        m += 40
    return terminy


GODZINY_KAWALY_CO_40_MIN = _godziny_kawaly_co_40_min()


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
    wstawka_poranna = _wybierz_bez_powtorek("poranek_wstawki", PORANNE_WSTAWKI)
    return [
        ("glos", "Witamy w porannym bloku Radia Strefa Zero! Życzymy Wam wspaniałego, pełnego energii dnia."),
        ("glos", wstawka_poranna),
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
    max_dlugosc_utworu_ms = 60000
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
            dj_seg = AudioSegment.from_file(dzingiel_na_przejsciu)[:5000].fade_in(200).fade_out(250)

        seg0 = _przytnij_cisze(AudioSegment.from_file(lokalne_pobrane[0])[:max_dlugosc_utworu_ms])
        mix_audio = seg0.fade_in(250).fade_out(250)
        del seg0

        for idx, sciezka_next in enumerate(lokalne_pobrane[1:], start=1):
            seg_n = _przytnij_cisze(AudioSegment.from_file(sciezka_next)[:max_dlugosc_utworu_ms])
            next_audio = seg_n.fade_in(250).fade_out(250)
            del seg_n

            if dj_seg is not None and idx % 2 == 1 and len(mix_audio) > len(dj_seg) + 1200:
                dl_dj = min(len(dj_seg), 4500)
                ogon = mix_audio[-dl_dj:] - abs(float(sciszenie_db))
                mix_audio = mix_audio[:-dl_dj] + ogon.overlay(dj_seg[:dl_dj])

            efektywny_xfade = min(int(crossfade_ms), len(mix_audio) // 3, len(next_audio) // 3)
            if efektywny_xfade > 500:
                mix_audio = mix_audio.append(next_audio, crossfade=efektywny_xfade)
            else:
                mix_audio = mix_audio + next_audio
            del next_audio

        znacznik = datetime.now(STREFA_EUROPA).strftime("%Y%m%d_%H%M%S")
        czysta_nazwa_folderu = re.sub(r"[^a-zA-Z0-9_-]", "_", folder_gatunkowy)
        nazwa_mixu = f"mix_{czysta_nazwa_folderu}_{znacznik}.mp3"
        sciezka_mixu = os.path.join(FOLDER_ROBOCZY, nazwa_mixu)
        mix_audio.export(sciezka_mixu, format="mp3", bitrate="128k")
        del mix_audio

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
        czysta_tresc = oczysc_wykonawce_i_tytul(czysta_tresc)

        imie_nadawcy = "Słuchacza"
        match_podpis = re.search(r"[-–—]\s*([A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż]{2,15})", czysta_tresc)
        if match_podpis:
            imie_nadawcy = oczysc_tekst_do_tts(match_podpis.group(1)).rstrip(".").capitalize()

        zapytanie_muzyczne = re.sub(r"[-–—]\s*[A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż]{2,15}", "", czysta_tresc).strip()
        w_orig, t_orig = pobierz_oryginalny_tytul_z_sieci(zapytanie_muzyczne)
        etykieta_muzyczna = f"{w_orig} — {t_orig}" if (w_orig and t_orig) else (t_orig or w_orig or zapytanie_muzyczne)

        pobrano_nowy_utwor = False
        if len(zapytanie_muzyczne) > 2:
            sciezka_istniejaca = szukaj_piosenki_na_dysku_sftp(sftp, etykieta_muzyczna or zapytanie_muzyczne)
            if not sciezka_istniejaca:
                bezpieczna_nazwa = re.sub(r"[^a-zA-Z0-9_-]", "", etykieta_muzyczna or zapytanie_muzyczne)[:40] + f"_{znacznik_czasu}"
                lokalne_mp3 = pobierz_piosenke_z_sieci(etykieta_muzyczna or zapytanie_muzyczne, bezpieczna_nazwa)
                if lokalne_mp3 and os.path.exists(lokalny_mp3):
                    folder_gatunek = okresl_folder_gatunkowy(etykieta_muzyczna or zapytanie_muzyczne)
                    zdalna_piosenka = f"{folder_gatunek}/{bezpieczna_nazwa}.mp3"
                    sftp.put(lokalny_mp3, zdalna_piosenka)
                    os.remove(lokalny_mp3)
                    pobrano_nowy_utwor = True
                    logging.info(f"Pobrano i wysłano utwór '{etykieta_muzyczna}' do '{zdalna_piosenka}'.")

        poprawiona_tresc = oczysc_tekst_do_tts(etykieta_muzyczna or czysta_tresc, czy_sms=True)

        if czy_noc:
            kwestie_audio = [
                ("glos", f"Nocne pozdrowienia w Strefie Zero od słuchacza {imie_nadawcy}."),
                ("glos", f"Nocny wybór: {poprawiona_tresc}."),
                ("glos", f"Nocny SMS na numer: {NUMER_TEL_TEKST}. Klubowa noc w Radiu Strefa Zero!"),
            ]
        elif typ_audycji == "koncert":
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
            gruby_glos=czy_noc,
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
        _odpal_w_tle(przetworz_sms_w_tle, tresc_sms, numer_nadawcy)
    return "<Response></Response>", 200


@app.route("/generuj-godzine", methods=["GET"])
def test_generuj_godzine():
    try:
        teraz = datetime.now(STREFA_EUROPA)
        docelowa_godzina = teraz.hour
        nazwa_pliku = f"godzina_{teraz.strftime('%Y%m%d_%H%M%S')}.mp3"
        sciezka = generuj_audio_mp3(
            zbuduj_tylko_godzine(docelowa_godzina),
            nazwa_pliku,
            liczba_pikow_na_poczatku=5,
        )

        if sciezka and os.path.exists(sciezka):
            transport, sftp = polacz_sftp()
            try:
                wyslij_i_zsynchronizuj(sftp, sciezka, f"{DIR_GODZINA}/{nazwa_pliku}")
            finally:
                sftp.close()
                transport.close()
            os.remove(sciezka)
            return f"Sukces! Wygenerowano zapowiedź godziny (z 5 pikami): {nazwa_pliku}", 200
        return "Błąd generowania pliku audio", 500
    except Exception as e:
        return f"Błąd endpointu: {e}", 500


@app.route("/test-news", methods=["GET"])
def endpoint_test_news():
    _odpal_w_tle(wygeneruj_i_wyslij_news_5min, 150)
    return jsonify({"status": "queued", "message": "Generowanie serwisu news ruszyło w tle. Sprawdź Logs lub SFTP za chwilę."}), 202


@app.route("/test-reklamy-3min", methods=["GET"])
def endpoint_test_reklamy_3min():
    _odpal_w_tle(wygeneruj_i_wyslij_blok_reklamowy_3min, 120)
    return jsonify({"status": "queued", "message": "Generowanie bloku reklamowego ruszyło w tle. Sprawdź Logs lub SFTP za chwilę."}), 202


@app.route("/pobierz-teraz", methods=["GET"])
def endpoint_pobierz_teraz():
    _odpal_w_tle(uruchom_codzienne_pobieranie_wszystkich_folderow, 2)
    return jsonify({"status": "queued", "message": "Pobieranie utworów ruszyło w tle. Sprawdź Logs po zakończeniu."}), 202


@app.route("/raport-tygodniowy", methods=["GET"])
def endpoint_raport_tygodniowy():
    tekst = generuj_i_zapisz_raport_tygodniowy()
    return f"<pre>{tekst}</pre>", 200


@app.route("/test-kawaly", methods=["GET"])
def endpoint_test_kawaly():
    rodzaj = (request.values.get("rodzaj") or "masztalski").strip().lower()
    if rodzaj not in ("masztalski", "jas"):
        rodzaj = "masztalski"
    _odpal_w_tle(wygeneruj_i_wyslij_audycje_kawaly, rodzaj, 120)
    return jsonify({"status": "queued", "rodzaj": rodzaj, "message": "Generowanie audycji z kawałami ruszyło w tle."}), 202


@app.route("/generuj-mix", methods=["GET", "POST"])
def endpoint_generuj_mix():
    folder_gatunek = request.values.get("folder", "muzyka klubowa")
    if folder_gatunek not in FOLDERY_GATUNKOWE:
        folder_gatunek = "muzyka klubowa"
    folder_docelowy = request.values.get("target_folder", DIR_MIXY)
    if folder_docelowy not in WSZYSTKIE_FOLDERY_SFTP:
        folder_docelowy = DIR_MIXY
    try:
        liczba = max(2, min(6, int(request.values.get("count", "3"))))
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

    _odpal_w_tle(
        wygeneruj_mix_z_folderu,
        folder_gatunkowy=folder_gatunkowy,
        liczba_utworow=liczba,
        crossfade_ms=crossfade_ms,
        folder_docelowy=folder_docelowy,
        dzingiel_na_przejsciu=dzingiel_kandydat,
        sciszenie_db=duck_db,
    )
    return jsonify({"status": "queued", "folder": folder_gatunek, "message": "Generowanie mixu ruszyło w tle."}), 202


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
        .checkbox-group { margin-bottom: 14px; display: flex; align-items: center; gap: 10px; }
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
            🎚️ Wybierz silnik (<b>ElevenLabs</b> dla grubszego, czystego głosu ze stałym <code>voice_id</code> lub <b>Edge-TTS</b>), folder docelowy i podkład. Bot automatycznie oczyści głos i wyśle plik na SFTP.
        </div>

        <div style="margin-bottom: 14px;">
            <span style="font-size: 13px; color: #aaa; display: block; margin-bottom: 6px;">Szybkie szablony zapowiedzi:</span>
            <button type="button" class="btn-preset" onclick="wstawSzablon('Wracamy do złotych hitów z lat osiemdziesiątych i dziewięćdziesiątych. Sprawdź, co z tamtych lat gra teraz w Radiu Strefa Zero!')">🕰️ Klasyki 80/90</button>
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

            <label>Silnik głosu:</label>
            <select name="engine" id="engine">
                <option value="auto" {% if elevenlabs_configured %}selected{% endif %}>Automatyczny (ElevenLabs jeśli skonfigurowany, inaczej Edge-TTS)</option>
                <option value="elevenlabs">ElevenLabs (Stały głos z ELEVENLABS_VOICE_ID)</option>
                <option value="edge" {% if not elevenlabs_configured %}selected{% endif %}>Edge-TTS (Darmowe głosy polskie)</option>
            </select>

            <label>Wybierz profil bota z puli:</label>
            <select id="bot_preset" onchange="zastosujProfilBota()">
                {% for k, cfg in bot_pool.items() %}
                    <option value="{{ k }}" data-voice="{{ cfg.voice }}" data-pitch="{{ cfg.pitch }}" data-rate="{{ cfg.rate }}">{{ cfg.name }}</option>
                {% endfor %}
            </select>

            <label>Wybierz głos lektora (dla Edge-TTS):</label>
            <select name="voice" id="voice_select">
                <optgroup label="Głosy Męskie">
                    <option value="pl-PL-MarekNeural">Marek (Klasyczny)</option>
                    <option value="pl-PL-AndrzejNeural">Andrzej (Dynamiczny)</option>
                    <option value="pl-PL-JacekNeural">Jacek (Wyrazisty)</option>
                    <option value="pl-PL-TomaszNeural">Tomasz (Spokojny)</option>
                </optgroup>
                <optgroup label="Głosy Żeńskie">
                    <option value="pl-PL-ZofiaNeural">Zofia (Naturalny / Czysty)</option>
                    <option value="pl-PL-AgnieszkaNeural">Agnieszka (Ciepły)</option>
                    <option value="pl-PL-EwaNeural">Ewa (Wyrazisty)</option>
                    <option value="pl-PL-MagdalenaNeural">Magdalena (Miękki)</option>
                </optgroup>
            </select>

            <div class="checkbox-group">
                <input type="checkbox" id="heavy_voice" name="heavy_voice" {% if elevenlabs_configured %}checked{% endif %}>
                <label for="heavy_voice">Gruby / dociążony głos radiowy (filtr 80 Hz + podbicie 120 Hz + kompresja)</label>
            </div>

            <div class="slider-label">
                <span>Wysokość tonu głosu (Pitch — Edge-TTS):</span>
                <span id="pitchVal">0Hz (Naturalny)</span>
            </div>
            <input type="range" name="pitch" id="pitch" min="-15" max="15" value="0" step="1" oninput="updatePitch(this.value)">

            <div class="slider-label">
                <span>Prędkość mowy (Rate — Edge-TTS):</span>
                <span id="rateVal">0% (Normalna)</span>
            </div>
            <input type="range" name="rate" id="rate" min="-25" max="25" value="0" step="5" oninput="updateRate(this.value)">

            <div class="checkbox-group">
                <input type="checkbox" id="add_music" name="add_music" onchange="toggleMusicSelect()">
                <label for="add_music">Dodaj podkład muzyczny w tle (z automatycznym ściszeniem)</label>
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

            <label>Liczba utworów (2 - 6):</label>
            <input type="number" id="mixCount" value="3" min="2" max="6">

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
            <h3>📊 Raport tygodniowy pobranych utworów (niedziela)</h3>
            <pre class="log-box">{{ weekly_report }}</pre>
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
            let opis = num < 0 ? '(Niższy)' : (num > 0 ? '(Wyższy)' : '(Naturalny)');
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
                if (data.status === 'success' || data.status === 'queued') {
                    mixStatus.style.color = '#2ed573';
                    mixStatus.innerText = '✅ ' + (data.remote_file || data.message);
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
        weekly_report=generuj_i_zapisz_raport_tygodniowy(),
        recent_logs=pobierz_ostatnie_logi(25),
        elevenlabs_configured=bool(ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID),
    )


@app.route("/generuj-jingle-ai", methods=["POST"])
def endpoint_generuj_jingle_ai():
    text = request.form.get("text", "").strip()
    selected_music = request.form.get("music")
    add_music = request.form.get("add_music") == "on"
    heavy_voice = request.form.get("heavy_voice") == "on"
    engine = request.form.get("engine", "auto").strip()
    if engine not in ("auto", "elevenlabs", "edge"):
        engine = "auto"

    selected_voice = request.form.get("voice", "pl-PL-MarekNeural")
    target_folder = request.form.get("target_folder", "jingles")
    expires_at_raw = request.form.get("expires_at", "").strip()

    zdalny_katalog = target_folder if target_folder in WSZYSTKIE_FOLDERY_SFTP else DIR_JINGLES

    try:
        p_val = max(-15, min(15, int(request.form.get("pitch", "0"))))
        pitch_str = f"{p_val:+d}Hz"
    except ValueError:
        pitch_str = "+0Hz"

    try:
        r_val = max(-25, min(25, int(request.form.get("rate", "0"))))
        rate_str = f"{r_val:+d}%"
    except ValueError:
        rate_str = "+0%"

    oczyszczony_tekst = oczysc_tekst_do_tts(text)
    if not oczyszczony_tekst:
        return jsonify({"status": "error", "message": "Tekst jest pusty!"}), 400

    znacznik = datetime.now(STREFA_EUROPA).strftime("%Y%m%d_%H%M%S")
    prefix = "reklama_" if zdalny_katalog == DIR_BLOK_REKLAMOWY else "item_"
    nazwa_pliku = f"{prefix}{znacznik}.mp3"

    speech_file = os.path.join(FOLDER_ROBOCZY, f"speech_{znacznik}.mp3")
    final_output = os.path.join(DIR_STATIC_OUTPUT, nazwa_pliku)

    try:
        uruchom_async(
            async_generuj_edge_tts(
                oczyszczony_tekst,
                speech_file,
                selected_voice,
                pitch=pitch_str,
                rate=rate_str,
                silnik=engine,
                gruby_glos=heavy_voice,
            )
        )

        if not os.path.exists(speech_file):
            return jsonify({"status": "error", "message": "Nie udało się wygenerować mowy."}), 500

        speech = effects.normalize(AudioSegment.from_file(speech_file))
        if add_music and selected_music:
            music_path = os.path.join(DIR_STATIC_MUSIC, selected_music)
            if os.path.exists(music_path):
                music = AudioSegment.from_file(music_path)
                target_duration = len(speech) + 2000
                while len(music) < target_duration:
                    music += music
                music = music[:target_duration] - 18
                combined = music.overlay(speech, position=500)
                combined.export(final_output, format="mp3")
            else:
                speech.export(final_output, format="mp3")
        else:
            speech.export(final_output, format="mp3")

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
    <p>Pełny system automatyzacji radia, zegara 24/7 z 5 sygnałami, świeżych newsów, reklam, kawałów, mixów i pobierania działa.</p>
    <ul>
        <li><a href="/jingles"><b>🎛️ Otwórz Generator Dżingli AI, Blok Reklamowy, Mikser, Raport i Logi</b></a></li>
        <li><a href="/generuj-godzine">Test generowania zapowiedzi godziny (5 pików)</a></li>
        <li><a href="/test-news">Test serwisu news (w tle)</a></li>
        <li><a href="/test-reklamy-3min">Test bloku reklamowego (w tle)</a></li>
        <li><a href="/pobierz-teraz">Wymuś teraz pobranie utworów (w tle)</a></li>
        <li><a href="/raport-tygodniowy">Podgląd raportu tygodniowego pobranych utworów</a></li>
        <li><a href="/test-kawaly?rodzaj=masztalski">Test audycji: Klub Masztalskiego (w tle + śmiech/brawa)</a></li>
        <li><a href="/test-kawaly?rodzaj=jas">Test audycji: Kącik Jasia (w tle + śmiech/brawa)</a></li>
        <li><a href="/generuj-mix?folder=muzyka%20klubowa&count=3">Test generowania mixu (w tle)</a></li>
    </ul>
    """


def _wykonaj_wstawke_i_wyslij(kwestie, folder_sftp, nazwa_pliku, bot_key="marek_standard"):
    profil = PULA_BOTOW.get(bot_key, PULA_BOTOW["marek_standard"])
    gruby = bot_key in ("marek_bas", "marek_noc")
    lokalny = generuj_audio_mp3(
        kwestie,
        nazwa_pliku,
        glos=profil["voice"],
        pitch=profil["pitch"],
        rate=profil["rate"],
        gruby_glos=gruby,
    )
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
    ostatni_dzien_pobierania = ""
    ostatni_raport_tydzien = ""
    licznik_audycji_kawaly = 0

    while True:
        try:
            teraz = datetime.now(STREFA_EUROPA)
            obecny_ts = time.time()
            hhmm = teraz.strftime("%H:%M")
            klucz_min = teraz.strftime("%Y-%m-%d %H:%M")
            dzis_str = teraz.strftime("%Y-%m-%d")
            czy_noc = teraz.hour >= 22 or teraz.hour < 6
            czy_weekend = teraz.weekday() in (4, 5, 6)

            if obecny_ts - ostatnie_czyszczenie_ts > 300:
                transport = None
                sftp = None
                try:
                    transport, sftp = polacz_sftp()
                    wyczysc_wygasle_reklamy(sftp)

                    usunieto_cos = False
                    # DIR_KAWALY celowo pominięty — pliki z kawałami zostają na później
                    foldery_do_czyszczenia = (
                        DIR_KONCERT_ZYCZEN,
                        DIR_PIOSENKA_NA_ZYCZENIE,
                        DIR_POBRANE,
                        DIR_PIOSENKI_DLA_SLUCHACZY,
                        DIR_GODZINA,
                        DIR_NEWS,
                        DIR_WSTAWKI_AI,
                        DIR_CIEKAWOSTKI,
                        DIR_NOCNE_RADIO,
                    )
                    for folder_t in foldery_do_czyszczenia:
                        try:
                            for plik in sftp.listdir(folder_t):
                                if plik.endswith(".mp3") and not plik.startswith("mix_"):
                                    sciezka_pliku = f"{folder_t}/{plik}"
                                    try:
                                        attr = sftp.stat(sciezka_pliku)
                                        if obecny_ts - attr.st_mtime > 2400:
                                            sftp.remove(sciezka_pliku)
                                            usunieto_cos = True
                                            logging.info(f"Usunięto plik po 40 min od wygenerowania: {sciezka_pliku}")
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

            if teraz.hour == 6 and teraz.minute == 0 and ostatni_dzien_pobierania != dzis_str:
                _odpal_w_tle(uruchom_codzienne_pobieranie_wszystkich_folderow, 2)
                ostatni_dzien_pobierania = dzis_str

            klucz_niedzieli = teraz.strftime("%Y-W%U")
            if teraz.weekday() == 6 and teraz.hour == 10 and teraz.minute == 0 and ostatni_raport_tydzien != klucz_niedzieli:
                generuj_i_zapisz_raport_tygodniowy()
                wyczysc_raport_tygodniowy_po_wyslaniu()
                ostatni_raport_tydzien = klucz_niedzieli

            if hhmm in GODZINY_KAWALY_CO_40_MIN and _raz_na_minute(f"kawaly_{klucz_min}"):
                rodzaj_audycji = "masztalski" if (licznik_audycji_kawaly % 2 == 0) else "jas"
                licznik_audycji_kawaly += 1
                _odpal_w_tle(wygeneruj_i_wyslij_audycje_kawaly, rodzaj_audycji, 120)

            if teraz.minute == 15 and teraz.hour % 2 == 0 and _raz_na_minute(f"reklamy3m_{klucz_min}"):
                _odpal_w_tle(wygeneruj_i_wyslij_blok_reklamowy_3min, 120)

            if teraz.minute == 40:
                docelowa_godzina = (teraz.hour + 1) % 24
                if docelowa_godzina != ostatnia_zapowiedziana_godzina:
                    transport = None
                    sftp = None
                    wyslano_cokolwiek = False
                    try:
                        transport, sftp = polacz_sftp()

                        nazwa_pliku_godzina = f"godzina_{teraz.strftime('%Y%m%d_%H%M%S')}.mp3"
                        sciezka_g = generuj_audio_mp3(
                            zbuduj_tylko_godzine(docelowa_godzina),
                            nazwa_pliku_godzina,
                            liczba_pikow_na_poczatku=5,
                        )
                        if sciezka_g and os.path.exists(sciezka_g):
                            sftp.put(sciezka_g, f"{DIR_GODZINA}/{nazwa_pliku_godzina}")
                            os.remove(sciezka_g)
                            wyslano_cokolwiek = True
                            logging.info(f"Wysłano plik godziny (24/7 + 5 pików) do '{DIR_GODZINA}': {nazwa_pliku_godzina}")

                        if INFO_RMF_START <= docelowa_godzina < INFO_RMF_KONIEC:
                            _odpal_w_tle(wygeneruj_i_wyslij_news_5min, 150)

                        if docelowa_godzina == 7:
                            kwestie_poranek = zbuduj_poranny_serwis()
                            nazwa_poranek = f"poranek_{teraz.strftime('%Y%m%d')}.mp3"
                            sciezka_por = generuj_audio_mp3(kwestie_poranek, nazwa_poranek, glos="pl-PL-ZofiaNeural", pitch="+0Hz", rate="+0%")
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
                            ostatnia_zapowiedziana_godzina = docelowa_godzina
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

            if czy_noc and teraz.minute == 1 and _raz_na_minute(f"noc_{klucz_min}"):
                tekst_noc = _wybierz_bez_powtorek("nocne_radio", NOCNE_WEJSCIA_KLUBOWE)
                nazwa_noc = f"noc_{teraz.strftime('%H%M')}.mp3"
                if _wykonaj_wstawke_i_wyslij([("glos", tekst_noc)], DIR_NOCNE_RADIO, nazwa_noc, bot_key="marek_noc"):
                    _wykonaj_wstawke_i_wyslij([("glos", tekst_noc)], DIR_WSTAWKI_AI, nazwa_noc, bot_key="marek_noc")
                    zsynchronizuj_azuracast()

            if czy_weekend and hhmm in ("18:10", "20:10") and _raz_na_minute(f"weekend_{klucz_min}"):
                tekst_wk = _wybierz_bez_powtorek("weekend", KACIK_WEEKENDOWY)
                if _wykonaj_wstawke_i_wyslij([("glos", tekst_wk)], DIR_WSTAWKI_AI, f"weekend_{teraz.strftime('%Y%m%d_%H%M')}.mp3", bot_key="marek_bas"):
                    zsynchronizuj_azuracast()

            if teraz.minute == 0 and teraz.hour % 4 == 0 and teraz.hour != ostatni_mix_godzina:
                folder_na_mix = "muzyka klubowa" if (teraz.hour >= 20 or teraz.hour < 6) else "disco polo dance"
                _odpal_w_tle(wygeneruj_mix_z_folderu, folder_gatunkowy=folder_na_mix, liczba_utworow=3, crossfade_ms=5000)
                ostatni_mix_godzina = teraz.hour

        except Exception as e:
            logging.error(f"Błąd w pętli głównej zegara: {e}")

        time.sleep(15)


watek_tlo = threading.Thread(target=petla_harmonogramu_w_tle, daemon=True)
watek_tlo.start()
logging.info(">>> Wątek automatyczny radia został uruchomiony! <<<")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
