"""Powiadomienia: news o Twojej spółce, wyniki dnia, przegląd tygodnia.

Trzy warstwy, celowo rozdzielone:

* `store`   — ustawienia, tokeny urządzeń, skrzynka. Wyłącznie baza.
* `push` / `mail` — kanały dostarczenia. Każdy umie zawieść i nie może
  wywrócić pozostałych.
* `engine`  — decyzja „komu i co", zapis do skrzynki, rozesłanie kanałami.

Reguła całości: **skrzynka w aplikacji jest zawsze**, kanały są dodatkiem.
Gdy Expo nie odpowiada albo SMTP nie jest skonfigurowany, powiadomienie i tak
czeka w aplikacji — nie ginie po drodze.
"""

from . import earnings, engine, jobs, mail, news, push, store   # noqa: F401
from .engine import powiadom                                   # noqa: F401
