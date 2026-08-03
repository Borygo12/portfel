"""Sekcja Earnings — kalendarz wyników spółek i wydarzeń ekonomicznych.

Trzy niezależne warstwy, każda z własnym źródłem i własnym cache:

  calendar.py — kto raportuje którego dnia (Nasdaq dla świata, Yahoo dla GPW),
  econ.py     — co się dzieje w makro (FXStreet: decyzje banków, dane, wystąpienia),
  report.py   — pojedyncza spółka przed publikacją (konsensus, historia zaskoczeń,
                marże kwartał po kwartale).

Warstwy nie wiedzą o sobie nawzajem — dashboard składa z nich odpowiedź.
"""

from . import calendar, econ, report  # noqa: F401
