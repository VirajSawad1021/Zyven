"""Global task set: Islamic and Hebrew calendars, worldwide phone numbers.

Ground truth is computed by the source libraries themselves (hijridate, pyluach, phonenumbers), never by a model.
"""

from __future__ import annotations

import datetime as dt
import random
import re

import phonenumbers
from hijridate import Gregorian
from phonenumbers import PhoneNumberFormat, PhoneNumberType
from pyluach import dates, hebrewcal

from eval.tasks import Task

SYSTEM_HINT = ("Use YYYY-MM-DD for dates (Hijri dates too, e.g. 1445-09-15). For holidays give the holiday's name. "
               "For yes/no questions the value is 'yes' or 'no'. For phone numbers give E.164 format (e.g. +442079460958).")

# Regions with different national trunk-prefix rules (dropped 0, kept 0, none, ...).
_REGIONS = ["GB", "DE", "FR", "IT", "JP", "IN", "BR", "AU", "ZA", "MX", "EG", "KR", "NG", "ID", "TR", "AR"]

_HOLIDAY_ALIASES = {
    "pesach": ["pesach", "passover", "pesah"], "shavuos": ["shavuos", "shavuot", "shavuoth"],
    "sukkos": ["sukkos", "sukkot", "succot", "sukkoth", "tabernacles"], "rosh hashana": ["roshhashana", "roshhashanah"],
    "yom kippur": ["yomkippur"], "chanuka": ["chanuka", "chanukah", "hanukkah", "hanukah", "hanuka"],
    "purim": ["purim"], "shushan purim": ["shushanpurim"], "tu bishvat": ["tubishvat", "tubshvat", "tubeshvat"],
    "lag baomer": ["lagbaomer", "lagbomer"], "tisha bav": ["tishabav", "tishabeav"],
    "shmini atzeres": ["shminiatzeres", "sheminiatzeret", "sheminiatzeres", "shminiatzeret"],
    "simchas torah": ["simchastorah", "simchattorah"], "tu bav": ["tubav", "tubeav"],
    "yom haatzmaut": ["yomhaatzmaut"], "yom yerushalayim": ["yomyerushalayim"], "yom hashoah": ["yomhashoah"],
    "yom hazikaron": ["yomhazikaron"],
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


def _holiday_key(name: str) -> str | None:
    n = _norm(name)
    for key, aliases in _HOLIDAY_ALIASES.items():
        if any(n.startswith(a) for a in aliases):
            return key
    return None


def _random_day(rng: random.Random, start: dt.date, end: dt.date) -> dt.date:
    return start + dt.timedelta(days=rng.randrange((end - start).days))


def generate(per_category: int = 6, seed: int = 1447) -> list[Task]:
    rng = random.Random(seed)
    tasks: list[Task] = []

    for i in range(per_category):
        g = _random_day(rng, dt.date(1990, 1, 1), dt.date(2035, 12, 31))
        h = Gregorian(g.year, g.month, g.day).to_hijri()
        tasks.append(Task(f"hijri_to_greg-{i}", "hijri_to_greg",
                          f"Using the Umm al-Qura calendar, which Gregorian date is {h.day} {h.month_name()} "
                          f"{h.year} AH?", g.isoformat()))
    for i in range(per_category):
        g = _random_day(rng, dt.date(1990, 1, 1), dt.date(2035, 12, 31))
        h = Gregorian(g.year, g.month, g.day).to_hijri()
        tasks.append(Task(f"greg_to_hijri-{i}", "greg_to_hijri",
                          f"What is the Hijri (Umm al-Qura) date for the Gregorian date {g.isoformat()}?",
                          f"{h.year:04d}-{h.month:02d}-{h.day:02d}"))

    holidays: list[tuple[dt.date, str]] = []
    day = dt.date(2026, 1, 1)
    while day < dt.date(2031, 1, 1):
        name = hebrewcal.holiday(dates.GregorianDate(day.year, day.month, day.day))
        if name and _holiday_key(name):
            holidays.append((day, name))
        day += dt.timedelta(days=1)
    for i, (d, name) in enumerate(rng.sample(holidays, per_category)):
        tasks.append(Task(f"jewish_holiday-{i}", "jewish_holiday",
                          f"Which Jewish holiday falls on {d.isoformat()} (outside Israel)?", name))

    regions = rng.sample(_REGIONS, per_category * 2)
    for i in range(per_category):
        region = regions[i]
        num = phonenumbers.example_number_for_type(region, PhoneNumberType.MOBILE)
        text = phonenumbers.format_number(num, PhoneNumberFormat.INTERNATIONAL)
        if i % 2:  # make it invalid by changing one digit, confirmed by the library
            digits = list(text)
            for _ in range(200):
                k = rng.choice([j for j, ch in enumerate(digits) if ch.isdigit() and j > 4])
                trial = digits[:k] + [str((int(digits[k]) + rng.randrange(1, 10)) % 10)] + digits[k + 1:]
                cand = "".join(trial)
                if not phonenumbers.is_valid_number(phonenumbers.parse(cand)):
                    text = cand
                    break
        valid = phonenumbers.is_valid_number(phonenumbers.parse(text))
        tasks.append(Task(f"phone_valid-{i}", "phone_valid", f"Is {text} a valid phone number?",
                          "yes" if valid else "no"))
    for i in range(per_category):
        region = regions[per_category + i]
        num = phonenumbers.example_number_for_type(region, PhoneNumberType.FIXED_LINE)
        national = phonenumbers.format_number(num, PhoneNumberFormat.NATIONAL)
        tasks.append(Task(f"phone_e164-{i}", "phone_e164",
                          f"A phone number written in {region}'s national format is {national}. "
                          f"What is it in E.164 international format?",
                          phonenumbers.format_number(num, PhoneNumberFormat.E164)))
    return tasks


def score(task: Task, answer: str) -> bool:
    a = answer.strip()
    if task.category in ("hijri_to_greg", "greg_to_hijri"):
        m = re.search(r"(\d{4})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})", a)
        return bool(m) and "{:04d}-{:02d}-{:02d}".format(*map(int, m.groups())) == task.expected
    if task.category == "jewish_holiday":
        return _holiday_key(a) is not None and _holiday_key(a) == _holiday_key(task.expected)
    if task.category == "phone_valid":
        low = a.lower()
        neg = re.search(r"\b(no|not|invalid)\b", low)
        pos = re.search(r"\b(yes|valid)\b", low)
        return ("no" if neg else "yes" if pos else None) == task.expected
    if task.category == "phone_e164":
        got = "+" + re.sub(r"\D", "", a) if "+" in a else None
        return got == task.expected
    raise ValueError(task.category)
