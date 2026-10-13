"""Generate the Nepali task set. Ground truth is computed by py-nepali itself, never by a model."""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import asdict, dataclass

from nepali import phone_number
from nepali.date_converter import converter

OPERATOR_PREFIXES = {
    "Nepal Telecom": ["984", "985", "986", "974", "975", "976"],
    "Ncell": ["980", "981", "982"],
    "Smart Cell": ["961", "962", "988"],
}


@dataclass
class Task:
    id: str
    category: str  # ad_to_bs | bs_to_ad | bs_weekday | phone_operator
    question: str
    expected: str


def _random_ad(rng: random.Random, start: int = 1990, end: int = 2035) -> dt.date:
    first, last = dt.date(start, 1, 1), dt.date(end, 12, 31)
    return first + dt.timedelta(days=rng.randrange((last - first).days))


def _bs(ad: dt.date) -> str:
    y, m, d = converter.english_to_nepali(ad.year, ad.month, ad.day)
    return f"{y:04d}-{m:02d}-{d:02d}"


def generate(per_category: int = 10, seed: int = 2082) -> list[Task]:
    rng = random.Random(seed)
    tasks: list[Task] = []

    for i in range(per_category):
        ad = _random_ad(rng)
        tasks.append(Task(f"ad_to_bs-{i}", "ad_to_bs",
                          f"What is the Nepali Bikram Sambat (BS) date for the Gregorian date {ad.isoformat()}?",
                          _bs(ad)))
    for i in range(per_category):
        ad = _random_ad(rng)
        tasks.append(Task(f"bs_to_ad-{i}", "bs_to_ad",
                          f"Convert the Bikram Sambat date {_bs(ad)} BS to the Gregorian (AD) date.",
                          ad.isoformat()))
    for i in range(per_category):
        ad = _random_ad(rng)
        tasks.append(Task(f"bs_weekday-{i}", "bs_weekday",
                          f"What day of the week is (or was) the Bikram Sambat date {_bs(ad)} BS?",
                          ad.strftime("%A")))
    operators = list(OPERATOR_PREFIXES)
    for i in range(per_category):
        op = operators[i % len(operators)]
        number = rng.choice(OPERATOR_PREFIXES[op]) + "".join(str(rng.randrange(10)) for _ in range(7))
        info = phone_number.parse(number)
        assert info and str(info["operator"]) == op, (number, info)
        tasks.append(Task(f"phone_operator-{i}", "phone_operator",
                          f"Which mobile network operator does the Nepali phone number {number} belong to?",
                          op))
    return tasks


if __name__ == "__main__":
    import json

    print(json.dumps([asdict(t) for t in generate()], indent=2, ensure_ascii=False))
