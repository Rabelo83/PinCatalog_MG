# Project notes

Decisions, current state and open questions for **Pin Catalog Builder / Mairelys Personal Collection**.
For how to *use* the program, see `README.md`.

## Purpose and audience

- A catalog of **Mairelys's personal enamel-pin collection**. She is a teacher who loves and works with children, so the public website is deliberately warm and playful (pastels, rounded fonts, cards "pinned" to a board) while staying tidy.
- The person running the app is **not a programmer**. Instructions should be click-by-click.
- Public website: **https://rabelo83.github.io/PinCatalog_MG/** (repository https://github.com/Rabelo83/PinCatalog_MG, served from `docs/`; the root `index.html` forwards there).

## Key decisions

| Decision | Why |
| --- | --- |
| Crops are **square boxes** with the pin centred, not cut along the outline | Requested; looks consistent in a grid. Transparent PNGs are optional per pin. |
| **Neighbouring pins are painted over** in crop margins (`CLEAN_CROP_EDGES`) | Pins sit close together, so square margins showed parts of neighbours. The original photos are never changed. |
| **Classical computer vision** (OpenCV) for detection, with a human review step | Fast, runs anywhere (Windows/Mac), no downloads. The review screen fixes the rare mistakes. |
| Permanent codes come from a counter table that only goes up | Codes are never reused, even after rejection. |
| `data/` (photos, crops, database) is **never pushed** to GitHub | Privacy. Only the website in `docs/` is public. |
| Website hides purchase price and notes | It is public. Configurable in `config.toml`. |
| Titles are **not invented** by the program | Names come from the user, or from an AI that actually looks at the pin. AI suggestions are also stored in `pins.ai_suggestions`. |
| Duplicate check = perceptual hash + colour histogram, threshold 0.55 | Calibrated on the sample page: the same pin re-photographed scored ≥ 0.60, different pins ≤ 0.50. It only warns; the user decides. |

## Current state (26 September 2026)

- One photo imported (`pin_page_001.jpeg`): 27 pins detected, 0 empty slots or table picked up.
- PIN-000001 … PIN-000027 created and named.
- **PIN-000012 "Dachshund with a Bouquet"** was set back to "waiting" with **Undo** in the local app on 26 Sep at 8:23 pm, so it is currently **not** in the catalog or on the website. If that was accidental: Review → select it → Approve (it keeps PIN-000012) → Export Catalog → push.
- 51 automated tests pass (`python -m pytest`).

## Known limitation: photo resolution

The sample photo is only 1080 × 1440 pixels with no camera information, meaning it was shrunk by a messaging app or screenshot. Each pin is about 150 pixels wide, so pictures look soft when shown large. **Fix: use original photo files and photograph half a page at a time**, which gives about 8× more detail across each pin. See README → Photo tips.

## Open questions and ideas (not built yet)

1. **Automatic naming with a local AI (Ollama).** *Recommended.*
   - A vision model such as `qwen2.5vl` or `llama3.2-vision` would suggest a title and tags per pin.
   - Free, private, offline. Needs about 8 GB RAM and takes roughly 5–30 seconds per pin.
   - Plan:
     - a "Suggest name" button on each pin page, plus "Name all unnamed pins" as a background job;
     - suggestions fill **empty titles only** and are also stored in `ai_suggestions`;
     - the whole feature is optional and switched off when Ollama isn't installed.
   - *Waiting on:* which computer she'll use (Mac or Windows) and how much RAM it has.
2. **Better detection on new backgrounds and shapes.**
   - Chat-style models (Ollama) are **not** suitable here: imprecise, inconsistent boxes, no pixel outlines, slow.
   - If the OpenCV detector struggles on new pages, the right upgrade is:
     - **SAM (Segment Anything)**, running locally, or
     - a **small detector trained on her own approved boxes**. Every approval in Review is already saved as training data; a few hundred approved pins is enough.
3. **AI upscaling (Real-ESRGAN, local)** for pins that can't be re-photographed. It makes them look sharper but *invents* detail, so if added, use it only for website pictures and keep the real crops untouched. Not needed with full-size photos.
4. **Perspective correction** is a preview only. On the sample it could not separate the page from the marble table.
