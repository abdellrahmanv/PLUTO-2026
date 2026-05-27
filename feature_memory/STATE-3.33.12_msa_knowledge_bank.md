# Feature Memory: MSA University Knowledge Bank

Status: implemented

Last updated: 2026-05-27

Last validated: 2026-05-27 local smoke test

Owner: Pluto systems engineering

## Requirement Trace

Implemented requirements:

```text
STATE-3.33
STATE-3.33.1
STATE-3.33.2
STATE-3.33.3
STATE-3.33.6
STATE-3.33.9
STATE-3.33.12
AUD-013
AUD-014
AUD-015
AUD-019
MEM-001
MEM-011
```

Verification tests:

```text
tools/welcome_talk_smoke.py
VER-TALK-003
VER-TALK-007
```

## Design Intent

Pluto should answer common visitor questions about MSA University without
internet access, API keys, or slow LLM calls. The bank is intentionally split
into many small facts because WELCOME_TALK v1 still requires answers at or
below nine words.

## Official Sources Used

Official MSA pages reviewed:

```text
https://msa.edu.eg/msauniversity/
https://msa.edu.eg/msauniversity/about-us/
https://msa.edu.eg/msauniversity/contact/
https://msa.edu.eg/msauniversity/faculties
https://msa.edu.eg/msauniversity/services/
https://msa.edu.eg/msauniversity/early-admission-academic-year-2026-2027/
```

The source facts were summarized; no full page text is copied into the runtime
bank.

## Implemented Knowledge Areas

MSA identity:

```text
full name
established year
founder
British education positioning
years of higher education
years of British partnership
```

Academic structure:

```text
faculty count
faculty-name fallback
Engineering
Computer Science
Pharmacy
Dentistry
Biotechnology
Physical Therapy
Arts and Design
Management Sciences
Mass Communication
Languages
Nutrition and Food Technology
```

Campus and numbers:

```text
50-acre campus
40 percent green area
800 security cameras
93 scientific laboratories
32000 graduates
6000 alumni job vacancies
700 computer labs and art studios
18 student activities
```

Partners and quality:

```text
University of Greenwich
University of Bedfordshire
Temple, Yunnan, and ACCA listed as partners
vision
mission
core values
research
```

Contact and admissions:

```text
address
hotline
landline
general email
admission email
working hours
services
application gateway
tuition and scholarships pointer
```

## Runtime Behavior

The MSA bank lives in:

```text
pluto_runtime/welcome_talk.py
```

It is not a separate runtime service. It uses the same deterministic
keyword/fuzzy matcher as the rest of WELCOME_TALK v1.

Example answers:

```text
what means msa -> October University for Modern Sciences and Arts.
who founded msa -> Dr. Nawal El Degwi established MSA.
how many faculties -> MSA has eleven faculties.
msa hotline -> MSA hotline is 16672.
```

## How To Run

Local validation:

```bash
python tools/welcome_talk_smoke.py
```

Live web validation:

```bash
python tools/welcome_talk_smoke.py --host 127.0.0.1 --port 8080 --external-server --hardware-flow
```

Manual API test:

```bash
curl -X POST http://127.0.0.1:8080/api/welcome/talk \
  -H "Content-Type: application/json" \
  -d '{"text":"how many faculties"}'
```

## How To Debug

Checklist:

1. Confirm `status.talk.intent_count` is at least 130.
2. Confirm every response is nine words or fewer.
3. If a broad MSA query steals a specific answer, move the specific rule above
   the general rule or remove the broad trigger.
4. If official facts change, update this memory and the smoke test together.

Bank audit:

```bash
python - <<'PY'
from pluto_runtime.welcome_talk import INTENT_RULES
for rule in INTENT_RULES:
    if rule.intent.startswith("msa"):
        print(rule.intent, "=>", rule.response)
PY
```

## Expected Evidence

```text
WELCOME_TALK_SMOKE PASS
intent_count >= 130
all responses <= 9 words
MSA fact questions match expected intents
```

## Verification Tests

| Test ID | Method | Expected Result | Last Result |
| --- | --- | --- | --- |
| VER-TALK-003 | Response bank audit | every response <= 9 words | local pass |
| VER-TALK-007 | MSA prompts | full name, founder, faculties, address, hotline match | local pass |

## Failure Modes

| Failure | Likely Cause | Diagnostic | Recovery |
| --- | --- | --- | --- |
| Wrong MSA answer | Broad trigger matched first | `talk.intent` in API response | Reorder or narrow trigger |
| Answer too long | New fact exceeds nine words | smoke test failure | Shorten response |
| Fact drift | University website changed | source review | Update bank and memory |
| Missing question | No trigger exists | fallback response | Add intent and test |

## Safety Notes

This feature is speech-only. It never sends motor, arm, or state-transition
commands.

## Open Questions

- Should Pluto later support Arabic MSA questions?
- Should a longer kiosk-style information mode allow answers over nine words?
- Should official facts be stored in a separate JSON file for easier editing?

## Change History

| Date | Change | Reason |
| --- | --- | --- |
| 2026-05-27 | Created MSA knowledge bank memory | Make university facts traceable and offline |
