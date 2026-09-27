# Changelog

All dates are 2026.

## 26 September — later updates

- **Website pictures are no longer compressed twice.** Crops that are already small enough are copied to the website untouched; resized ones use JPEG quality 92.
- **Website always shows the latest data.** `catalog.js` is linked with a version code, so browsers don't keep showing an old catalog after an export.
- **Crops keep pale parts of the pin.** The clean-up step had painted over the sea turtle's mint-green head (PIN-000004), treating it as a neighbouring pin. Anything mostly inside the pin's own box is now always kept (regression test added).
- **Whole pins, clean margins.**
  - The detector is more sensitive to pale enamel (`BACKGROUND_DISTANCE_THRESHOLD` 18 → 11).
  - It cuts touching pins along their dark metal outlines instead of at the narrowest point, which could be a pin's own neck.
  - It ignores objects running along the photo edge, such as the table.
  - New `CLEAN_CROP_EDGES` setting paints over neighbouring pins in a crop's margin.
- **Possible-duplicate check.**
  - Each pin gets a visual fingerprint (shape hash plus colour mix).
  - New photos are compared with the catalog, and look-alikes are flagged in Review with a **"Same pin: +1"** button.
  - New **Catalog → Check for possible duplicates** page, and "Looks similar to" on each pin page.
  - Setting: `SIMILARITY_THRESHOLD`.
- **Names for the sample pins.** The 27 pins on the first page got titles, categories (Animals / Characters), subcategories and tags from Claude's visual review.
- **Website at the main address.** https://rabelo83.github.io/PinCatalog_MG/ now forwards to the gallery in `docs/`.
- README, test suite (51 tests) and `pytest.ini`.

## 26 September — first version

- Local web app (FastAPI):
  - Dashboard.
  - Detection review with zoom, pan, drawing, move/resize, merge, split and keyboard shortcuts.
  - Searchable catalog and editable pin pages.
- Pin detector for photos of display pages:
  - colour, dark-outline and edge foreground
  - watershed splitting of touching pins
  - empty-slot rejection
  - quality flags
  - debug images
- Permanent pin codes (`PIN-000001` …), never reused.
- Duplicate-photo protection (SHA-256). Originals are moved to `data/originals/` and never changed.
- Square padded crops, thumbnails, optional transparent PNGs, dominant colours.
- Exports: CSV, JSON and a static HTML gallery ("Mairelys Personal Collection"), published to GitHub Pages from `docs/`.
- Warm, child-friendly design: pastel colours, Fredoka/Nunito fonts, pinned-card look.
