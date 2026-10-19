"""Deterministischer Parser für Datum und Uhrzeit aus dem /botc-Modal.

Datum:   heute, morgen, übermorgen · Samstag, Sa, nächsten Samstag · in 3 Tagen, in 2 Wochen
         24.10. · 24.10 · 24.10.26 · 24.10.2026 · 2026-10-24 · 24. Oktober · 24 okt 2026
Uhrzeit: 20 · 20:00 · 20.00 · 2000 · 830 · 20 Uhr · 20:30 Uhr · 20h

Ohne Jahr gilt das nächste Vorkommen ab heute. Ein Wochentag ohne „nächsten“ meint den
nächsten solchen Tag ab heute; ist das heute und die Uhrzeit schon vorbei, der in einer Woche.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from events.schema import BERLIN_TZ, MAX_DAYS_AHEAD


class ParseError(ValueError):
    """Eingabe nicht lesbar. Die Meldung ist deutsch und wird dem User gezeigt."""


WEEKDAYS = {
    "montag": 0, "mo": 0,
    "dienstag": 1, "di": 1,
    "mittwoch": 2, "mi": 2,
    "donnerstag": 3, "do": 3,
    "freitag": 4, "fr": 4,
    "samstag": 5, "sa": 5, "sonnabend": 5,
    "sonntag": 6, "so": 6,
}
WEEKDAY_NAMES = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

MONTHS = {
    "januar": 1, "jan": 1, "jänner": 1,
    "februar": 2, "feb": 2,
    "märz": 3, "maerz": 3, "mär": 3, "mrz": 3,
    "april": 4, "apr": 4,
    "mai": 5,
    "juni": 6, "jun": 6,
    "juli": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "oktober": 10, "okt": 10,
    "november": 11, "nov": 11,
    "dezember": 12, "dez": 12,
}

RELATIVE_DAYS = {"heute": 0, "morgen": 1, "übermorgen": 2, "uebermorgen": 2}
NEXT_WORDS = ("nächsten", "nächster", "nächste", "naechsten", "naechster", "naechste",
              "kommenden", "kommender", "kommende")

DATE_HINT = "Beispiele: „Sa“, „morgen“, „24.10.“ oder „24.10.2026“."
TIME_HINT = "Beispiele: „20“, „20:00“, „20.30“ oder „20 Uhr“."


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _resolve_year(day: int, month: int, today: date) -> date:
    """Datum ohne Jahr: dieses Jahr, wenn noch nicht vorbei, sonst nächstes Jahr."""
    for year in (today.year, today.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if d >= today:
            return d
    raise ParseError(f"Den {day}.{month}. gibt es nicht. {DATE_HINT}")


def _make_date(day: int, month: int, year: int | None, today: date) -> date:
    if year is None:
        return _resolve_year(day, month, today)
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        raise ParseError(f"Den {day}.{month}.{year} gibt es nicht. {DATE_HINT}") from None


def parse_date(text: str, today: date) -> tuple[date, bool]:
    """Liest ein Datum. Gibt (Datum, flexibel) zurück.

    `flexibel` ist True bei einem Wochentag ohne „nächsten“: Liegt die Uhrzeit heute schon
    in der Vergangenheit, darf `parse_start` eine Woche weiterspringen.
    """
    t = _clean(text)
    if not t:
        raise ParseError(f"Bitte gib ein Datum an. {DATE_HINT}")
    t = re.sub(r"^(am|den)\s+", "", t)

    if t in RELATIVE_DAYS:
        return today + timedelta(days=RELATIVE_DAYS[t]), False

    # nächsten Samstag / Samstag / Sa / Sa.
    m = re.fullmatch(r"(?:(\S+)\s+)?([a-zäöü]+)\.?", t)
    if m and m.group(2) in WEEKDAYS:
        prefix = m.group(1)
        if prefix is not None and prefix not in NEXT_WORDS:
            raise ParseError(f"„{text.strip()}“ verstehe ich nicht. {DATE_HINT}")
        delta = (WEEKDAYS[m.group(2)] - today.weekday()) % 7
        if prefix is not None and delta == 0:
            delta = 7
        return today + timedelta(days=delta), prefix is None

    # in 3 Tagen / in 2 Wochen / in einer Woche
    m = re.fullmatch(r"in (\d+|einem|einer) (tag|tagen|woche|wochen)", t)
    if m:
        n = 1 if m.group(1) in ("einem", "einer") else int(m.group(1))
        days = n * 7 if m.group(2).startswith("woche") else n
        return today + timedelta(days=days), False

    # 2026-10-24
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        return _make_date(int(m.group(3)), int(m.group(2)), int(m.group(1)), today), False

    # 24.10. / 24.10 / 24.10.26 / 24.10.2026 (auch mit / statt .)
    m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2}|\d{4})?)?", t)
    if m:
        year = int(m.group(3)) if m.group(3) else None
        return _make_date(int(m.group(1)), int(m.group(2)), year, today), False

    # 24. Oktober / 24 okt / 24. Okt. 2026
    m = re.fullmatch(r"(\d{1,2})\.? ?([a-zäöü]+)\.?(?: (\d{2}|\d{4}))?", t)
    if m and m.group(2) in MONTHS:
        year = int(m.group(3)) if m.group(3) else None
        return _make_date(int(m.group(1)), MONTHS[m.group(2)], year, today), False

    raise ParseError(f"„{text.strip()}“ verstehe ich nicht als Datum. {DATE_HINT}")


def parse_time(text: str) -> time:
    """Liest eine Uhrzeit (24-Stunden-Format)."""
    t = _clean(text)
    if not t:
        raise ParseError(f"Bitte gib eine Uhrzeit an. {TIME_HINT}")
    t = re.sub(r"\s*(uhr|h)$", "", t)

    m = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2}))?", t)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
    else:
        m = re.fullmatch(r"(\d{1,2})(\d{2})", t)  # 2000, 830
        if not m:
            raise ParseError(f"„{text.strip()}“ verstehe ich nicht als Uhrzeit. {TIME_HINT}")
        hour, minute = int(m.group(1)), int(m.group(2))

    if hour > 23 or minute > 59:
        raise ParseError(f"„{text.strip()}“ ist keine gültige Uhrzeit. {TIME_HINT}")
    return time(hour, minute)


def parse_start(date_text: str, time_text: str, now: datetime | None = None) -> datetime:
    """Datum + Uhrzeit → Zeitpunkt in Europe/Berlin. Muss in der Zukunft liegen."""
    now = now or datetime.now(BERLIN_TZ)
    today = now.astimezone(BERLIN_TZ).date()
    d, flexible = parse_date(date_text, today)
    t = parse_time(time_text)

    start = datetime.combine(d, t, tzinfo=BERLIN_TZ)
    if start <= now and flexible:
        start += timedelta(days=7)
    if start <= now:
        raise ParseError(f"{format_start(start)} liegt in der Vergangenheit.")
    if start > now + timedelta(days=MAX_DAYS_AHEAD):
        raise ParseError(f"{format_start(start)} liegt mehr als {MAX_DAYS_AHEAD} Tage in der Zukunft.")
    return start


def format_start(start: datetime, duration_minutes: int | None = None) -> str:
    """„Samstag, 24.10.2026, 20:00“ bzw. mit Dauer „Samstag, 24.10.2026, 20:00–22:30“."""
    s = start.astimezone(BERLIN_TZ)
    text = f"{WEEKDAY_NAMES[s.weekday()]}, {s:%d.%m.%Y}, {s:%H:%M}"
    if duration_minutes:
        end = s + timedelta(minutes=duration_minutes)
        text += f"–{end:%H:%M}"
    return text
