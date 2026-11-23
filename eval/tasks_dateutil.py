"""Date-arithmetic task set: calendar months, nth weekdays, date differences, Easter.

Ground truth is computed by python-dateutil itself (pinned in catalog/repos.json), never by a model. Dates are chosen
near month ends and across leap years, where adding "one month" or counting the difference by hand goes wrong.
"""

from __future__ import annotations

import datetime as dt
import random
import re

from dateutil.easter import EASTER_ORTHODOX, easter
from dateutil.relativedelta import FR, MO, SA, SU, TH, TU, WE, relativedelta

from eval.tasks import Task

SYSTEM_HINT = ("Use YYYY-MM-DD for dates. For a difference between two dates, answer as 'Y years, M months, D days' "
               "(calendar years and months first, then the remaining days).")

_DAYS = [("Monday", MO), ("Tuesday", TU), ("Wednesday", WE), ("Thursday", TH), ("Friday", FR), ("Saturday", SA),
         ("Sunday", SU)]
_ORD = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}


def _month_end(rng: random.Random) -> dt.date:
    year = rng.randint(1999, 2040)
    month = rng.randint(1, 12)
    nxt = dt.date(year + month // 12, month % 12 + 1, 1)
    return nxt - dt.timedelta(days=rng.randint(1, 3))  # the last three days of a month


def _add_months(rng):
    d = _month_end(rng)
    k = rng.choice([1, 1, 2, 3, 13, -1, -3, -12, 25])
    word = f"{k} month{'s' if abs(k) != 1 else ''}"
    q = (f"What is the date {word} {'after' if k > 0 else 'before'} {d.isoformat()}? "
         "If that month is shorter, use its last day.")
    return q, (d + relativedelta(months=k)).isoformat()


def _nth_weekday(rng):
    d = dt.date(rng.randint(2000, 2040), rng.randint(1, 12), rng.randint(1, 28))
    name, wd = rng.choice(_DAYS)
    n = rng.randint(2, 5)
    q = (f"What is the date of the {_ORD[n]} {name} on or after {d.isoformat()}? "
         f"(If {d.isoformat()} is itself a {name}, it counts as the first.)")
    return q, (d + relativedelta(weekday=wd(+n))).isoformat()


def _difference(rng):
    a = dt.date(rng.randint(1950, 2000), rng.randint(1, 12), rng.randint(1, 28))
    b = a + dt.timedelta(days=rng.randint(400, 20000))
    if rng.random() < 0.5:  # end on a month's last day, where the day count is easy to get wrong
        b = dt.date(b.year + b.month // 12, b.month % 12 + 1, 1) - dt.timedelta(days=1)
    r = relativedelta(b, a)
    q = f"How long is it from {a.isoformat()} to {b.isoformat()}, in calendar years, months and days?"
    return q, f"{r.years} years, {r.months} months, {r.days} days"


def _orthodox_easter(rng):
    y = rng.randint(1990, 2080)
    q = f"On which Gregorian-calendar date is Orthodox Easter in {y}?"
    return q, easter(y, EASTER_ORTHODOX).isoformat()


_MAKERS = {"add_months": _add_months, "nth_weekday": _nth_weekday, "date_difference": _difference,
           "orthodox_easter": _orthodox_easter}


def generate(per_category: int = 6, seed: int = 2027) -> list[Task]:
    rng = random.Random(seed)
    tasks: list[Task] = []
    for cat, make in _MAKERS.items():
        seen: set[str] = set()
        while len(seen) < per_category:
            q, expected = make(rng)
            if q in seen:
                continue
            seen.add(q)
            tasks.append(Task(f"{cat}-{len(seen) - 1}", cat, q, expected))
    return tasks


def score(task: Task, answer: str) -> bool:
    a = answer.strip()
    if task.category == "date_difference":
        got = re.findall(r"-?\d+", a)
        return got == re.findall(r"-?\d+", task.expected)
    m = re.fullmatch(r"[^\d]*(\d{4}-\d{2}-\d{2})[^\d]*", a)
    return bool(m) and m.group(1) == task.expected
