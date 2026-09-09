#!/bin/sh
# Uruchomienie serwera z katalogiem danych, w którym DA SIĘ pisać.
#
# Dysk w Railway podpina się pod /data dopiero po zbudowaniu obrazu i należy do
# roota — `chown` z Dockerfile'a dotyczy katalogu, który zaraz zostanie przykryty
# montowaniem. Serwer chodzi jako uid 10001, więc czytać może, a pisać nie:
# ustawienia bota i feed analiz cicho lądowały w katalogu tymczasowym.
#
# Dlatego kontener startuje jako root, poprawia właściciela katalogu danych
# i DOPIERO POTEM schodzi na zwykłe konto. Root zostaje w tym skrypcie i nie
# wchodzi do procesu aplikacji.
set -e

KATALOG="${PORTEVO_DATA_DIR:-/data}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$KATALOG" 2>/dev/null || true
    chown -R portevo:portevo "$KATALOG" 2>/dev/null \
        || echo "entrypoint: nie udalo sie przejac $KATALOG — serwer zejdzie na katalog tymczasowy"

    # setpriv jest w util-linux, czyli w obrazie bazowym Debiana. `su` to zapasowa
    # droga na wypadek, gdyby kiedyś zniknął. Gdy nie ma żadnego z nich, wolimy
    # uruchomić serwer jako root niż nie uruchomić go wcale — apka ma działać.
    if command -v setpriv >/dev/null 2>&1; then
        exec setpriv --reuid=10001 --regid=10001 --init-groups "$@"
    fi
    if command -v su >/dev/null 2>&1; then
        exec su portevo -s /bin/sh -c 'exec "$0" "$@"' -- "$@"
    fi
    echo "entrypoint: brak setpriv i su — uruchamiam jako root"
fi

exec "$@"
