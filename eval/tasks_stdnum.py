"""Standard-number task set (IBAN, Luhn). Ground truth is computed by python-stdnum itself."""

from __future__ import annotations

import random
import re

from stdnum import iban, luhn

from eval.tasks import Task

SYSTEM_HINT = ("For yes/no questions the value is 'yes' or 'no'. "
               "For check digits the value is exactly the two digits (e.g. 07).")

# Countries whose IBAN body (BBAN) is purely numeric and has no extra national checksum in stdnum.
_COUNTRIES = {"DE": 18, "AT": 16, "CH": 17, "PL": 24, "DK": 14}


def _valid_iban(rng: random.Random) -> str:
    while True:
        cc = rng.choice(sorted(_COUNTRIES))
        bban = "".join(str(rng.randrange(10)) for _ in range(_COUNTRIES[cc]))
        number = cc + iban.calc_check_digits(cc + "00" + bban) + bban
        if iban.is_valid(number):
            return iban.format(number)


def _corrupt(rng: random.Random, number: str, valid) -> str:
    digits = [i for i, ch in enumerate(number) if ch.isdigit() and i > 4]
    while True:
        i = rng.choice(digits)
        out = number[:i] + str((int(number[i]) + rng.randrange(1, 10)) % 10) + number[i + 1:]
        if not valid(out):
            return out


def _card(rng: random.Random) -> str:
    body = "4" + "".join(str(rng.randrange(10)) for _ in range(14))
    return body + luhn.calc_check_digit(body)


def generate(per_category: int = 6, seed: int = 97) -> list[Task]:
    rng = random.Random(seed)
    tasks: list[Task] = []
    for i in range(per_category):
        number = _valid_iban(rng)
        if i % 2:
            number = _corrupt(rng, number, iban.is_valid)
        tasks.append(Task(f"iban_valid-{i}", "iban_valid", f"Is {number} a valid IBAN?",
                          "yes" if iban.is_valid(number) else "no"))
    for i in range(per_category):
        cc = rng.choice(sorted(_COUNTRIES))
        bban = "".join(str(rng.randrange(10)) for _ in range(_COUNTRIES[cc]))
        tasks.append(Task(f"iban_check-{i}", "iban_check_digits",
                          f"What are the two IBAN check digits for country {cc} with account part (BBAN) {bban}?",
                          iban.calc_check_digits(cc + "00" + bban)))
    for i in range(per_category):
        card = _card(rng)
        if i % 2:
            card = _corrupt(rng, card, luhn.is_valid)
        spaced = " ".join(card[k:k + 4] for k in range(0, len(card), 4))
        tasks.append(Task(f"luhn-{i}", "luhn_valid", f"Does the card number {spaced} pass the Luhn checksum?",
                          "yes" if luhn.is_valid(card) else "no"))
    return tasks


def score(task: Task, answer: str) -> bool:
    a = answer.strip().lower()
    if task.category in ("iban_valid", "luhn_valid"):
        neg = re.search(r"\b(no|not|invalid|fails?)\b", a)
        pos = re.search(r"\b(yes|valid|passes?)\b", a)
        got = "no" if neg else ("yes" if pos else None)
        return got == task.expected
    if task.category == "iban_check_digits":
        m = re.search(r"\b(\d{2})\b", a)
        return bool(m) and m.group(1) == task.expected
    raise ValueError(task.category)
