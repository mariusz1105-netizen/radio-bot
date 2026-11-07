from gtts import gTTS
from datetime import datetime
from flask import Flask, request
import os
import re
import random
import threading
import time
import requests
import xml.etree.ElementTree as ET

app = Flask(__name__)

FOLDER_AUDIO = "nagrania_sms"
if not os.path.exists(FOLDER_AUDIO):
    os.makedirs(FOLDER_AUDIO)

# Plik do zapisywania brakujących piosenek od słuchaczy
PLIK_BRAKUJACE = "brakujace_piosenki.txt"

# --- CONFIG AZURACAST ---
# Klucz pobierany bezpiecznie ze zmiennej środowiskowej na Renderze, z Twoim kluczem jako domyślnym
KLUCZ_API = os.environ.get("AZURACAST_API_KEY", "c900964cef529524:b642499e3606b70f34191287ce1f83cb")
URL_API_FILES = "https://asurahosting.com"

def wyslij_do_azuracast(sciezka_pliku_mp3):
    """Automatycznie wysyła wygenerowany plik z życzeniami lub zegarem na serwer radiowy"""
    naglowki = {
        "Authorization": f"Bearer {KLUCZ_API}"
    }
    try:
        nazwa_pliku = os.path.basename(sciezka_pliku_mp3)
        with open(sciezka_pliku_mp3, 'rb') as f:
            pliki = {'file': (nazwa_pliku, f, 'audio/mpeg')}
            dane = {'path': 'jingles'} 
            
            response = requests.post(URL_API_FILES, headers=naglowki, files=pliki, data=dane)
            if response.status_code in:
                print(f"[AZURACAST] Sukces! Plik {nazwa_pliku} przesłany do chmury.")
                return True
            else:
                print(f"[AZURACAST BŁĄD] Serwer zwrócił kod: {response.status_code}")
    except Exception as e:
        print(f"[AZURACAST BŁĄD] Nie udało się wysłać pliku: {e}")
    return False

def zapisz_tekst_jako_mp3(tekst):
    """Generuje plik MP3 przy użyciu gTTS (Google Cloud) stabilnego dla Render.com"""
    try:
        nazwa_pliku = datetime.now().strftime("godzina_%Y%m%d_%H%M%S.mp3") if "godzina" in tekst.lower() else datetime.now().strftime("wiadomosc_%Y%m%d_%H%M%S.mp3")
        sciezka_pliku = os.path.join(FOLDER_AUDIO, nazwa_pliku)
        
        # Generowanie profesjonalnego polskiego lektora
        tts = gTTS(text=tekst, lang='pl', slow=False)
        tts.save(sciezka_pliku)
        
        print(f"[RADIO] Chmura wygenerowała plik audio: {sciezka_pliku}")
        
        # AUTOMATYCZNY UPLOAD NA SERWER RADIOWY
        wyslij_do_azuracast(sciezka_pliku)
        
        # Czyszczenie starego pliku z kontenera Render, aby nie przepełniać pamięci
        if os.path.exists(sciezka_pliku):
            os.remove(sciezka_pliku)
            
        return sciezka_pliku
    except Exception as e:
        print(f"[BŁĄD CHMURY TTS] Problem z generowaniem mowy: {e}")
        return None

def zapisz_brakujacy_utwor(tresc_sms, numer_nadawcy):
    try:
        czas_wpisu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        wpis = f"[{czas_wpisu}] Od: {numer_nadawcy} | Treść: {tresc_sms}\n"
        with open(PLIK_BRAKUJACE, "a", encoding="utf-8") as f:
            f.write(wpis)
    except Exception as e:
        print(f"[BŁ BŁĄD LOGÓW] {e}")

def inteligentna_korekta(tekst):
    t = tekst.lower()
    slownik_poprawek = {
        "zeby": "żeby", "zyczenia": "życzenia", "zycze": "życzę", "zyczymy": "żyčymy",
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
    godzina = datetime.now().hour
    if godzina >= 23 or godzina < 1:
        return "Techno / Hard Techno (Nocny Blok Klubowy)"
    elif 6 <= godzina < 17:
        return "House / EDM / 90s Eurodance (Pasmo Dzienne)"
    elif 17 <= godzina < 23:
        return "Disco Polo / Hands Up / Klubowe Remixy (Pasmo Wieczorne)"
    else:
        return "Deep House / Chillout (Nocna Selekcja)"

def pobierz_wiadomosci_polsat():
    """Pobiera najświeższe nagłówki z kanału RSS Polsat News"""
    url_rss = "https://polsatnews.pl"
    try:
        response = requests.get(url_rss, timeout=10)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            naglowki = [item.find('title').text for item in root.findall('.//item') if item.find('title') is not None][:4]
            if naglowki:
                serwis = "A teraz czas na skrót najświeższych wiadomości z kraju i ze świata. "
                for i, news in enumerate(naglowki, 1):
                    serwis += f"Fakt numer {i}: {news}. "
                serwis += "To były wiadomości z serwisu Polsat News. "
                return serwis
    except Exception as e:
        print(f"[BŁĄD RSS] {e}")
    return "Na antenie Radio Strefa Zero gramy dla Was najlepsze klubowe kawałki bez przerwy! "

def pętla_zegara_radiowego():
    ostatnia_zapowiedziana_godzina = -1
    while True:
        teraz = datetime.now()
        if teraz.minute == 0 and teraz.hour != ostatnia_zapowiedziana_godzina:
            wyswietlana_godzina = 24 if teraz.hour == 0 else teraz.hour
            tekst_wiadomosci = pobierz_wiadomosci_polsat()

            komunikat_godzinowy = (
                f"Radio Strefa Zero. Wybiła godzina {wyswietlana_godzina}. "
                f"{tekst_wiadomosci} "
                "Chcesz wziąć udział w Koncercie Życzeń, zamówić ulubioną piosenkę lub przesłać pozdrowienia dla bliskich? "
                "Napisz SMS na naszą linię pod numer: plus jeden, osiemset dwanaście, czterysta dwanaście, dwadzieścia dziewięć siedemdziesiąt pięć!"
            )
            zapisz_tekst_jako_mp3(komunikat_godzinowy)
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

    teraz = datetime.now()
    imie_nadawcy = "Słuchacz"
    match_podpis = re.search(r'[-–—]\s*([A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż]{2,15})', tresc_sms)
    if match_podpis:
        imie_nadawcy = match_podpis.group(1).capitalize()
    
    trwa_koncert_zyczeń = (teraz.weekday() in [4, 5] and 18 <= teraz.hour < 20)
    trwa_piosenka_na_zyczenie = (0 <= teraz.weekday() <= 4 and 17 <= teraz.hour < 18)
    
    if trwa_koncert_zyczeń:
        komunikat_dj = f"W studio Radio Strefa Zero trwa właśnie Koncert Życzeń! Mamy nową wiadomość od {imie_nadawcy}. Oto tekst: {poprawiona_tresc}."
    elif trwa_piosenka_na_zyczenie:
        komunikat_dj = f"Wasz wirtualny prezenter w pasmie Piosenka Na Życzenie. {imie_nadawcy} pisze do nas tak: {poprawiona_tresc}."
    else:
        gatunek = pobierz_aktualny_gatunek_muzyczny()
        komunikat_dj = f"Szybka przerwa w muzyce, w pasmie {gatunek}. Przesyłamy pozdrowienia od słuchacza o imieniu {imie_nadawcy}: {poprawiona_tresc}."

    zapisz_tekst_jako_mp3(komunikat_dj)
    return "OK", 200

if __name__ == '__main__':
    watek_zegara = threading.Thread(target=pętla_zegara_radiowego, daemon=True)
    watek_zegara.start()
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
AZURACAST_URL = "https://a7.asurahosting.com"  # Twój adres panelu
STATION_ID = 461  # ID Twojej stacji
API_KEY = os.environ.get("AZURACAST_API_KEY")

headers = {
    "Authorization": f"Bearer {API_KEY}"
}

def upload_audio_to_playlist(file_path, playlist_name):
    """
    Wysyła plik audio do AzuraCast i umieszcza go w folderze wybranej playlisty.
    """
    upload_url = f"{AZURACAST_URL}/api/station/{STATION_ID}/files"
    
    with open(file_path, "rb") as f:
        files = {"file": (os.path.basename(file_path), f, "audio/mpeg")}
        data = {"path": f"/{playlist_name}"}
        
        response = requests.post(upload_url, headers=headers, files=files, data=data)
        
    if response.status_code in [200, 201]:
        print(f"Plik pomyślnie wysłany do playlisty: {playlist_name}")
        return True
    else:
        print(f"Błąd wysyłania do {playlist_name}: {response.status_code} - {response.text}")
        return False

# Przykład użycia dla serwisu lub piosenki na życzenie:
# upload_audio_to_playlist("wiadomosci.mp3", "zapowiedzi i serwis")
# upload_audio_to_playlist("zyczenie.mp3", "Piosenka na Życzenie")
from gtts import gTTS

def generate_and_upload_clock():
    """
    Generuje plik z aktualną godziną i wysyła go do playlisty Zegar w AzuraCast.
    """
    now = datetime.now()
    # Tekst, który ma wypowiedzieć syntezator (np. "Jest godzina 14:00")
    text = f"Jest godzina {now.strftime('%H:%M')}"
    
    file_path = "zegar.mp3"
    
    # Tworzenie pliku audio w języku polskim
    tts = gTTS(text=text, lang='pl')
    tts.save(file_path)
    
    # Wysłanie pliku do playlisty o nazwie "Zegar"
    upload_audio_to_playlist(file_path, "Zegar")

# Opcjonalny przycisk testowy w przeglądarce:
@app.route('/test-clock')
def test_clock():
    generate_and_upload_clock()
    return "Test zegara wykonany! Sprawdź czy plik pojawił się w AzuraCast."
from flask import request
from twilio.twiml.messaging_response import MessagingResponse
import requests
import os

# Konfiguracja (jeśli nie masz jej jeszcze wyżej w pliku)
AZURACAST_URL = "https://a7.asurahosting.com"
STATION_ID = 461
API_KEY = os.environ.get("AZURACAST_API_KEY")

headers = {
    "Authorization": f"Bearer {API_KEY}"
}

@app.route('/sms', methods=['POST'])
def incoming_sms():
    """
    Odbiera przychodzący SMS z prośbą o piosenkę, wysyła zwrotne potwierdzenie
    i przekazuje informację dalej.
    """
    # Pobranie treści wiadomości oraz numeru telefonu nadawcy
    message_body = request.values.get('Body', '').strip()
    sender_phone = request.values.get('From', '')
    
    print(f"Otrzymano SMS od {sender_phone}: {message_body}")
    
    # Tutaj możesz przetworzyć zapytanie (np. wyszukać utwór w AzuraCast lub zapisać go)
    # Przykład wysłania zapytania do AzuraCast (jeśli dopasowujesz utwór do żądań)
    # process_song_request(message_body)
    
    # Tworzenie automatycznej odpowiedzi zwrotnej dla słuchacza przez SMS
    resp = MessagingResponse()
    resp.message(f"Dzięki! Twoja prośba o piosenkę '{message_body}' została przyjęta w Radiu Strefa 0. Pozdrawiamy!")
import yt_dlp
import threading

def download_and_upload_request(query):
    """
    Wyszukuje utwór na podstawie tekstu z SMS-a, pobiera go 
    i wgrywa bezpośrednio do playlisty 'Piosenka na Życzenie'.
    """
    output_template = "song_request"
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_template + '.%(ext)s',
        'default_search': 'ytsearch1:',
        'noplaylist': True,
    }
    
    try:
        print(f"Szukam i pobieram utwór: {query}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=True)
            downloaded_file = ydl.prepare_filename(info)
            
            if os.path.exists(downloaded_file):
                print(f"Pobrano plik: {downloaded_file}. Wysyłam do AzuraCast...")
                # Wysłanie pliku do playlisty Piosenka na Życzenie
                success = upload_audio_to_playlist(downloaded_file, "Piosenka na Życzenie")
                
                # Usunięcie pliku z dysku serwera po udanym przesłaniu
                os.remove(downloaded_file)
                if success:
                    print(f"Utwór '{query'}' został pomyślnie dodany do playlisty żądań!")
                else:
                    print("Błąd podczas wgrywania pliku do AzuraCasta.")
            else:
                print("Nie udało się odnaleźć pobranego pliku na dysku.")
    except Exception as e:
        print(f"Błąd w procesie pobierania/wysyłania utworu: {e}")

@app.route('/sms', methods=['POST'])
def incoming_sms():
    """
    Odbiera przychodzący SMS, wysyła potwierdzenie do słuchacza 
    i uruchamia pobieranie utworu w tle.
    """
    message_body = request.values.get('Body', '').strip()
    sender_phone = request.values.get('From', '')
    
    print(f"Otrzymano SMS od {sender_phone}: {message_body}")
    
    if message_body:
        # Uruchamiamy pobieranie w tle (wątek), żeby Twilio nie czekało zbyt długo na odpowiedź
        thread = threading.Thread(target=download_and_upload_request, args=(message_body,))
        thread.start()
    
    # Automatyczna odpowiedź zwrotna dla słuchacza
    resp = MessagingResponse()
    resp.message(f"Dzięki! Utwór '{message_body}' został przyjęty do realizacji i wkrótce trafi do Radia Strefa 0!")
    
    return str(resp)
