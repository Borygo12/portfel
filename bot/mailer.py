"""Wysyłka wiadomości od użytkowników premium prosto na skrzynkę twórców.

Świadomie bez zewnętrznej paczki — `smtplib` jest w bibliotece standardowej, więc
nie dokłada zależności do i tak ciężkiego obrazu. Konfiguracja idzie przez
zmienne środowiskowe (ładowane z `keys/email.env`):

    SMTP_HOST   domyślnie smtp.gmail.com
    SMTP_PORT   domyślnie 587 (STARTTLS)
    SMTP_USER   konto nadawcze (np. adres Gmail)
    SMTP_PASS   hasło aplikacji (Gmail: „hasła do aplikacji", nie zwykłe hasło)
    CONTACT_TO  gdzie trafiają wiadomości — domyślnie borygoo45@gmail.com

Dopóki SMTP_USER/SMTP_PASS są puste, `send_contact` zwraca False i NIC nie wybucha
— wiadomość i tak jest zapisana lokalnie przez `store_feedback`, więc nie ginie.
Uzbrojenie skrzynki = wpisać dwa sekrety i tyle.
"""

from __future__ import annotations

import json
import os
import smtplib
import time
from email.message import EmailMessage
from email.utils import formataddr

import paths

CONTACT_TO = (os.environ.get("CONTACT_TO") or "borygoo45@gmail.com").strip()


def _cfg() -> dict:
    return {
        "host": (os.environ.get("SMTP_HOST") or "smtp.gmail.com").strip(),
        "port": int(os.environ.get("SMTP_PORT") or 587),
        "user": (os.environ.get("SMTP_USER") or "").strip(),
        "pass": (os.environ.get("SMTP_PASS") or "").strip(),
        "to": CONTACT_TO,
    }


def configured() -> bool:
    c = _cfg()
    return bool(c["user"] and c["pass"] and c["to"])


def store_feedback(user_id: str, email: str, topic: str, message: str) -> None:
    """Zapis kopii wiadomości do pliku — zabezpieczenie, gdyby e-mail nie wyszedł.

    Leży w katalogu danych (`paths.data_path`), więc przeżywa wdrożenie na Railway.
    """
    try:
        line = json.dumps({
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "user_id": user_id, "email": email,
            "topic": topic, "message": message,
        }, ensure_ascii=False)
        with open(paths.data_path("feedback.jsonl"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def send_contact(from_email: str, topic: str, message: str) -> bool:
    """Wysyła wiadomość na skrzynkę twórców. Zwraca True, gdy realnie poszła.

    `Reply-To` ustawiamy na adres użytkownika, żeby odpowiedź z Gmaila trafiła
    wprost do niego — bez przepisywania adresu ręcznie.
    """
    c = _cfg()
    if not (c["user"] and c["pass"] and c["to"]):
        return False

    msg = EmailMessage()
    subject_topic = f" — {topic}" if topic else ""
    msg["Subject"] = f"[Portevo] Wiadomość od użytkownika{subject_topic}"
    msg["From"] = formataddr(("Portevo — wiadomości", c["user"]))
    msg["To"] = c["to"]
    if from_email:
        msg["Reply-To"] = from_email
    msg.set_content(
        f"Nadawca: {from_email or 'nieznany'}\n"
        f"Temat: {topic or '(bez tematu)'}\n"
        f"{'-' * 40}\n\n{message}\n"
    )

    try:
        with smtplib.SMTP(c["host"], c["port"], timeout=15) as srv:
            srv.starttls()
            srv.login(c["user"], c["pass"])
            srv.send_message(msg)
        return True
    except Exception:
        # nie logujemy treści — to prywatna wiadomość; wystarczy, że zapis lokalny został
        return False
