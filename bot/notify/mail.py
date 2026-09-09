"""Powiadomienia e-mailem — kanał dla tych, którzy korzystają z przeglądarki.

`mailer.py` wysyła wiadomości OD użytkowników DO twórców. Tu jest odwrotnie,
więc adresy i nagłówki są inne, ale konfiguracja SMTP ta sama (SMTP_HOST/USER/
PASS ze zmiennych środowiskowych). Dopóki jej nie ma, `wyslij` zwraca False
i nic nie wybucha — powiadomienie zostaje w skrzynce w aplikacji.

Nagłówki, które nie są ozdobą:

* `List-Unsubscribe` — bez niego Gmail traktuje seryjną wysyłkę jak spam,
  a człowiek nie ma jak się wypisać poza wejściem do aplikacji;
* `Auto-Submitted: auto-generated` — mówi cudzemu autoresponderowi, żeby nie
  odpowiadał, bo po drugiej stronie nikt tego nie czyta.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

import mailer

log = logging.getLogger("notify.mail")

# Adres aplikacji — trafia do stopki i do nagłówka wypisania.
ADRES_APLIKACJI = (os.environ.get("PUBLIC_URL") or "https://www.portevo.pl").rstrip("/")


def skonfigurowany() -> bool:
    return mailer.configured()


def wyslij(adres: str, tytul: str, tresc: str, link: str = "") -> bool:
    """Jedna wiadomość do jednego odbiorcy. True, gdy realnie poszła."""
    adres = (adres or "").strip()
    if not adres or not skonfigurowany():
        return False

    c = mailer._cfg()
    msg = EmailMessage()
    msg["Subject"] = f"[Portevo] {tytul}"[:200]
    msg["From"] = formataddr(("Portevo", c["user"]))
    msg["To"] = adres
    msg["Auto-Submitted"] = "auto-generated"
    # Wypisanie prowadzi do ustawień powiadomień w aplikacji — jedno miejsce,
    # w którym da się to zmienić, więc nie ma osobnego mechanizmu do utrzymania.
    msg["List-Unsubscribe"] = f"<{ADRES_APLIKACJI}/powiadomienia>"

    cel = link or ADRES_APLIKACJI
    msg.set_content(
        f"{tresc}\n\n"
        f"Zobacz więcej w aplikacji: {cel}\n\n"
        f"{'-' * 52}\n"
        "Materiał informacyjny — to nie jest porada inwestycyjna ani rekomendacja.\n"
        f"Nie chcesz tych wiadomości? Wyłącz je w Portevo → Powiadomienia:\n"
        f"{ADRES_APLIKACJI}/powiadomienia\n"
    )

    try:
        with smtplib.SMTP(c["host"], c["port"], timeout=20) as srv:
            srv.starttls()
            srv.login(c["user"], c["pass"])
            srv.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001 — kanał nie może wywrócić powiadomienia
        log.warning("Nie wyszedł e-mail do %s: %s", adres, e)
        return False
