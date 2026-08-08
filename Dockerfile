# Serwer danych Portevo — obraz produkcyjny (Railway).
#
# Świadomie BEZ modułu /live (whisper, yt-dlp, ffmpeg): obraz schodzi z ~1,5 GB
# do ~250 MB, a transkrypcja na CPU byłaby najdroższą pozycją rachunku. Moduł
# wykrywa brak zależności sam i zgłasza to w aplikacji, reszta działa normalnie.
# Gdybyś kiedyś chciał go tu uruchomić: doinstaluj requirements-live.txt i ffmpeg.

FROM python:3.12-slim

# Nie buforuj stdout — inaczej logi w Railway pojawiają się z opóźnieniem
# i debugowanie wdrożenia staje się zgadywanką.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORTEVO_CLOUD=1 \
    PORTEVO_DATA_DIR=/data

WORKDIR /app

# Zależności osobną warstwą: zmiana kodu nie unieważnia wtedy cache pip-a
# i kolejne wdrożenia trwają sekundy zamiast minut.
COPY bot/requirements.txt bot/requirements.txt
RUN pip install --no-cache-dir -r bot/requirements.txt

COPY bot/ bot/

# Katalog na pliki robocze (parametry, feed analiz, token). W Railway podpina się
# tu dysk, żeby przeżyły wdrożenie. Bez dysku aplikacja też wstanie — po prostu
# ustawienia wrócą do domyślnych po każdym deployu.
RUN mkdir -p /data

# Aplikacja nie potrzebuje roota. Gdyby ktoś kiedyś wykorzystał lukę w bibliotece,
# nie dostanie od razu pełnych praw w kontenerze.
RUN useradd --create-home --uid 10001 portevo && chown -R portevo:portevo /app /data
USER portevo

EXPOSE 8080

# Nasłuch na "::" zamiast "0.0.0.0" — to nie jest kosmetyka.
# Sieć wewnętrzna Railway działa po IPv6, a gniazdo otwarte na 0.0.0.0 przyjmuje
# WYŁĄCZNIE IPv4. Aplikacja wtedy chodzi, tylko healthcheck i proxy nie mają jak
# się do niej dobić — deploy przechodzi, a zaraz po nim leci "Healthcheck failure".
# "::" w Linuksie nasłuchuje na obu rodzinach adresów naraz.
ENV PANEL_HOST=:: \
    PORT=8080

CMD ["python", "bot/dashboard.py", "--no-browser"]
