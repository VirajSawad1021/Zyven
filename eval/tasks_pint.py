"""Unit-conversion task set: compound units, temperatures with offsets, energy and pressure, data sizes.

Ground truth is computed by pint itself (pinned in catalog/repos.json), never by a model. Values are random and the
units are ones whose factors people rarely know by heart (furlongs per fortnight, BTU, inches of mercury, mebibytes).
An answer counts when it is within 0.1% of pint's value, since the question asks for four significant figures.
"""

from __future__ import annotations

import random
import re

import pint

from eval.tasks import Task

SYSTEM_HINT = "Reply with only the number, to four significant figures, without the unit."

_U = pint.UnitRegistry()

_SPEED = [("furlong / fortnight", "furlongs per fortnight"), ("knot", "knots"), ("mile / hour", "miles per hour"),
          ("km / hour", "kilometres per hour"), ("foot / second", "feet per second"), ("m / s", "metres per second")]
_TEMP = [("degF", "degrees Fahrenheit"), ("degC", "degrees Celsius"), ("kelvin", "kelvin"), ("degR", "degrees Rankine")]
_ENERGY = [("kWh", "kilowatt-hours"), ("Btu", "British thermal units (ISO, 1 BTU = 1055.056 J)"), ("kcal", "kilocalories (thermochemical)"),
           ("MJ", "megajoules"), ("eV", "electronvolts"), ("erg", "ergs")]
_PRESSURE = [("psi", "pounds per square inch"), ("inHg", "inches of mercury (conventional)"), ("kPa", "kilopascals"),
             ("atm", "standard atmospheres"), ("torr", "torr"), ("bar", "bar")]
_DATA = [("MiB", "mebibytes"), ("MB", "megabytes"), ("Gibit", "gibibits"), ("Gbit", "gigabits"), ("KiB", "kibibytes"),
         ("TB", "terabytes")]


def _sig4(x: float) -> str:
    return f"{float(f'{x:.4g}'):g}" if abs(x) < 1e15 else f"{x:.4g}"


def _convert(rng, table, lo, hi):
    (src, src_name), (dst, dst_name) = rng.sample(table, 2)
    value = round(rng.uniform(lo, hi), rng.choice([1, 2]))
    result = _U.Quantity(value, src).to(dst).magnitude
    return (f"Convert {value} {src_name} to {dst_name}. Give the result to four significant figures.",
            repr(float(result)))


_MAKERS = {
    "speed": lambda r: _convert(r, _SPEED, 1, 500),
    "temperature": lambda r: _convert(r, _TEMP, -60, 900),
    "energy": lambda r: _convert(r, _ENERGY, 0.5, 5000),
    "pressure": lambda r: _convert(r, _PRESSURE, 0.2, 300),
    "data_size": lambda r: _convert(r, _DATA, 1, 9000),
}


def generate(per_category: int = 6, seed: int = 2028) -> list[Task]:
    rng = random.Random(seed)
    tasks: list[Task] = []
    for cat, make in _MAKERS.items():
        for i in range(per_category):
            q, expected = make(rng)
            tasks.append(Task(f"{cat}-{i}", cat, q, expected))
    return tasks


def score(task: Task, answer: str) -> bool:
    """One number, within 0.1% of pint's value (the question asks for four significant figures)."""
    nums = re.findall(r"-?\d[\d,]*\.?\d*(?:[eE][-+]?\d+)?", answer.replace("×10^", "e").replace("x10^", "e"))
    if len(nums) != 1:
        return False
    try:
        got = float(nums[0].replace(",", ""))
    except ValueError:
        return False
    want = float(task.expected)
    return abs(got - want) <= 1e-3 * max(abs(want), 1e-12)
