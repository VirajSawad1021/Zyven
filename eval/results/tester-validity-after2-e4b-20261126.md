# Tester validity: after2-e4b (2026-11-26)

- **Model:** `gemma4:e4b@premier-patent-classes-victory.trycloudflare.com`
- **Code:** commit `4b5f81a`
- **Valid** means the reference program evaluates in the sandbox on its own case's arguments; whether it
  matches a tool is not measured. Specs are frozen (`eval/tester_specs/`), so only the Tester varies.
- Each cell is the mean over runs, with the range when runs differ.

| Library | Capability | Runs | (a) valid, Tester's answer | (b) valid, after re-ask | (c) tools with a valid case |
|---|---|---|---|---|---|
| packaging | version_specifiers | 3 | 98% (95% to 100%) | 99% (96% to 100%) | 3.0 of 3 |
| pyluach | jewish_holidays_and_fasts | 3 | 52% (33% to 77%) | 72% (61% to 86%) | 2.0 (1 to 3) of 4 |

## Tools left without a valid case

- pyluach run 1: get_festival_info, get_hebrew_date_from_gregorian, get_today_jewish_date. First problem: `AttributeError("'NoneType' object has no attribute 'festival_name'") running: pyluach.hebrewcal.festival(pyluach.dates.GregorianDate(2023, 4, 5), israel=False, hebrew=False, include_working_days=False, prefix_day=False).festival_name`
- pyluach run 2: get_today_jewish_date. First problem: `no case`
- pyluach run 3: get_hebrew_date_from_gregorian, get_today_jewish_date. First problem: `no case`
