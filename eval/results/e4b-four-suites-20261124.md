# Gemma 4 E4B on four suites (2026-11-24)

Model: `gemma4:e4b-it-q8_0` (Gemma 4 E4B, 8-bit), served by Ollama on two Kaggle T4 GPUs. Each suite was run in one
session, the model alone and then with its verified skills, with the same questions, the same 4,096-token output
budget and the same one-time "answer now" retry rule. Ground truth comes from the pinned libraries themselves.

| Suite | Library | Model alone | Model + verified skills | Avg sec/task (alone → with skills) |
|---|---|---|---|---|
| Calendar arithmetic | python-dateutil 4.0.0 | 11/24 | **24/24** | 18.4 → 19.9 |
| Unit conversion | pint 0.26.2 | 22/30 | **29/30** | 40.1 → 20.0 |
| IBAN and Luhn | python-stdnum | 6/18 | **18/18** | 44.3 → 19.4 |
| Hijri, Jewish holidays, phone numbers | hijridate, pyluach, phonenumbers | 10/30 | **30/30** | 13.5 → 31.3 |
| **All four** | | **49/102** | **101/102** | |

## Per category

**python-dateutil**

| Condition | Add months (month ends) | Nth weekday | Date difference | Orthodox Easter | Total |
|---|---|---|---|---|---|
| Model alone | 5/6 | 0/6 | 6/6 | 0/6 | 11/24 |
| With `date_arithmetic` | 6/6 | 6/6 | 6/6 | 6/6 | **24/24** |

**pint**

| Condition | Speed | Temperature | Energy | Pressure | Data size | Total |
|---|---|---|---|---|---|---|
| Model alone | 5/6 | 6/6 | 4/6 | 6/6 | 1/6 | 22/30 |
| With `unit_conversion` | 6/6 | 6/6 | 6/6 | 6/6 | 5/6 | **29/30** |

The one miss with the skill: asked to convert terabytes to gibibits, the model called the tool with `TiB` and `GiB`
(tebibytes and gibibytes); the tool converted what it was given.

**python-stdnum**

| Condition | IBAN valid? | IBAN check digits | Luhn valid? | Total |
|---|---|---|---|---|
| Model alone | 3/6 | 0/6 | 3/6 | 6/18 |
| With `iban_validation` and `checksum_algorithm_implementation` | 6/6 | 6/6 | 6/6 | **18/18** |

**Global (calendars and phone numbers)**

| Condition | Hijri → Greg | Greg → Hijri | Jewish holiday | Phone valid? | Phone → E.164 | Total |
|---|---|---|---|---|---|---|
| Model alone | 0/6 | 0/6 | 2/6 | 4/6 | 4/6 | 10/30 |
| With the three skills | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 | **30/30** |

## Skills used (all in `skills/`, all six gates passed)

| Skill | Library | Compiled by |
|---|---|---|
| `date_arithmetic` | python-dateutil 4.0.0 (`a78cbd8`) | Reflection Beam 1.0 (501B, open weights) via OpenCode; Tester DeepSeek V4.1 Flash (open weights) |
| `unit_conversion` | pint 0.26.2 (`af817a6`) | same; unit names are accepted in any case (edit recorded in its `provenance.json`) |
| `iban_validation`, `checksum_algorithm_implementation` | python-stdnum (`006192e`) | Gemma 4 26B A4B |
| `hijri_gregorian_conversion`, `phone_number_parsing_and_formatting` | hijridate, phonenumbers | Gemma 4 26B A4B |
| `jewish_holidays_and_fast_days` | pyluach (`c1ffe42`) | Reflection Beam 1.0 via OpenCode |

The pint skill run above used the skill after its unit-name edit. Raw records: `e4b-dateutil-20261124.jsonl`,
`e4b-pint-20261124.jsonl`, `e4b-stdnum-20261124.jsonl`, `e4b-global-20261124.jsonl` (the endpoint host is replaced by
`kaggle-ollama`).
