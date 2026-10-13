"""Hand-written MCP server for opensource-nepal/py-nepali (baseline / ground truth).

This is the human-built reference that Zyven's compiler output is compared against.
Source: https://github.com/opensource-nepal/py-nepali @ 3ff19477150ea597d6ce2e9d3dce62e6cf0065e6 (MIT)

Run:  uv run python toolkit/py_nepali_manual/server.py
"""

from __future__ import annotations

import datetime as dt

from mcp.server.mcpserver import MCPServer
from nepali import phone_number
from nepali.date_converter import converter
from pydantic import BaseModel

server = MCPServer(
    name="py-nepali (manual)",
    instructions="Exact Nepali calendar (Bikram Sambat) conversion and Nepali phone number lookup.",
)

_DEVANAGARI = str.maketrans("0123456789", "०१२३४५६७८९")


class BSDate(BaseModel):
    bs_date: str  # YYYY-MM-DD
    bs_date_devanagari: str
    weekday: str  # English weekday name


class ADDate(BaseModel):
    ad_date: str  # YYYY-MM-DD
    weekday: str


class PhoneInfo(BaseModel):
    valid: bool
    type: str | None = None  # "Mobile" | "Landline"
    number: str | None = None
    operator: str | None = None  # mobile only
    areas: list[str] | None = None  # landline only: possible areas/districts
    area_code: str | None = None


def _parse_ymd(value: str) -> tuple[int, int, int]:
    parts = value.strip().replace("/", "-").split("-")
    if len(parts) != 3:
        raise ValueError(f"expected YYYY-MM-DD, got {value!r}")
    y, m, d = (int(p) for p in parts)
    return y, m, d


@server.tool()
def ad_to_bs(ad_date: str) -> BSDate:
    """Convert a Gregorian (AD) date to the Nepali Bikram Sambat (BS) date.

    ad_date: Gregorian date as YYYY-MM-DD (supported 1944-2042).
    Returns the BS date (YYYY-MM-DD and Devanagari) and the weekday.
    """
    y, m, d = _parse_ymd(ad_date)
    by, bm, bd = converter.english_to_nepali(y, m, d)
    bs = f"{by:04d}-{bm:02d}-{bd:02d}"
    return BSDate(bs_date=bs, bs_date_devanagari=bs.translate(_DEVANAGARI), weekday=dt.date(y, m, d).strftime("%A"))


@server.tool()
def bs_to_ad(bs_date: str) -> ADDate:
    """Convert a Nepali Bikram Sambat (BS) date to the Gregorian (AD) date.

    bs_date: BS date as YYYY-MM-DD (supported 2000-2099 BS).
    Returns the AD date (YYYY-MM-DD) and the weekday.
    """
    y, m, d = _parse_ymd(bs_date)
    ay, am, ad = converter.nepali_to_english(y, m, d)
    date = dt.date(ay, am, ad)
    return ADDate(ad_date=date.isoformat(), weekday=date.strftime("%A"))


@server.tool()
def parse_nepali_phone(number: str) -> PhoneInfo:
    """Identify a Nepali phone number: mobile or landline, telecom operator, or landline area.

    number: phone number, with or without +977 / dashes.
    """
    info = phone_number.parse(number.strip())
    if not info:
        return PhoneInfo(valid=False)
    areas = info.get("area")
    return PhoneInfo(
        valid=True,
        type=info.get("type"),
        number=info.get("number"),
        operator=str(info["operator"]) if info.get("operator") else None,
        areas=[str(a) for a in areas] if areas else None,
        area_code=str(info["area_code"]) if info.get("area_code") else None,
    )


if __name__ == "__main__":
    server.run("stdio")
