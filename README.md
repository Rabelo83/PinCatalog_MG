# Pin Catalog Builder

*Mairelys Personal Collection*

Take photos of pin display pages, and this program finds every pin, crops it neatly, gives it a permanent number (`PIN-000001`, `PIN-000002`, …) and builds a searchable catalog. It can also publish that catalog as a website.

Everything runs on your own computer. Your photos never leave it; only the website you choose to publish goes online.

---

## 1. Install (one time)

You need **Python 3.12 or newer**. Download it from <https://www.python.org/downloads/>.
On Windows, tick **"Add python.exe to PATH"** in the first installer screen.

Open a terminal in the project folder:

- **Windows:** open the folder in File Explorer, click the address bar, type `cmd` and press Enter.
- **Mac:** right-click the folder in Finder and choose **New Terminal at Folder**.

Then type these commands, pressing Enter after each one.

**Windows**

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**Mac**

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Start the program

Each time you want to use it, open a terminal in the project folder and type:

**Windows**

```
.venv\Scripts\activate
python run.py
```

**Mac**

```
source .venv/bin/activate
python run.py
```

Your browser opens at **http://127.0.0.1:8000**. If it doesn't, open that address yourself.
Leave the terminal window open while you work. To stop the program, press **Ctrl+C** in the terminal.

## 3. Add photos

Put your photos in this folder:

```
data/input/
```

JPG, PNG, WEBP, TIFF and iPhone HEIC photos all work.

### Photo tips (these matter most for sharp pictures)

The program can only be as sharp as the photo. Each pin's picture is cut from the photo, so small photos give small, blurry pins.

- **Use the original photo file.** Copy photos with AirDrop, a USB cable, iCloud Photos, Google Photos (original quality) or email with **"Actual Size"**. **Do not** send them through WhatsApp, Messages or Messenger: those shrink photos to about a quarter of the detail. (The first sample was only 1080 × 1440, so each pin was about 150 pixels wide.)
- **Get closer:** photograph **half a page at a time**. Pins come out about twice as big. Any number of photos per page is fine.
- Hold the phone straight above the page. Don't zoom; move closer instead, and tap on the pins to focus.
- Use soft, even light (daylight near a window works well). Avoid strong shadows and glare on the enamel.

On the **Dashboard**, click **Process New Images**. For each photo, the program:

1. makes a fingerprint (SHA-256) so the same photo is never imported twice,
2. moves the photo, unchanged, to `data/originals/` (it is **never** edited or deleted),
3. finds candidate pins and puts them on the review list.

If you add a photo that was already imported, the program says so and moves it to `data/input/already_imported/` instead of processing it again.

## 4. Review the detections

Click **Review Detections**. You'll see the photo with a box around each pin the program found:

| Colour | Meaning |
| --- | --- |
| 🟧 Orange | Waiting for review |
| 🟩 Green | Approved (the pin is in the catalog) |
| 🟥 Red | Rejected |
| 🟦 Blue | Selected |

Click a box to see a preview of its crop on the right. Then:

- **Approve** (key `A`): the pin gets its permanent number and joins the catalog.
- **Reject** (key `R`): not a pin (empty slot, shadow, …).
- **Undo** (key `U`): back to "waiting". Undo on an approved pin takes it out of the catalog, and out of the website at the next export. Approve it again to bring it back with the same number.
- **Move or resize**: drag the box, or drag its corners. You can also type exact numbers and click **Save box**.
- **Draw box** (key `D`): drag on the photo to add a pin the program missed.
- **Merge**: if one pin got two boxes, Shift+click both, then click **Merge**.
- **Split**: if one box covers two pins, click **Split (auto)**, or split it in half with ⎮ or ―.
- **Next / Previous** (keys `→` `←`): jump between boxes.
- **Zoom**: mouse wheel, or the `+` `−` **Fit** buttons. Drag the background to move around.
- **Approve all unflagged**: approves every waiting box that has no ⚠ warning.
- **Page name**: give the photo a friendly name like "Binder 1 – page 3".

**Same pin twice?** If a box looks like a pin that is already in the catalog, the panel shows **"Looks like a pin you already have"** with its picture. Click **Same pin: +1 to PIN-…** to add one to that pin's quantity instead of creating a new pin. (Undo reverses it.) You can also see all look-alike pins at **Catalog → Check for possible duplicates**.

A ⚠ next to a box means the program wants you to take a closer look, for example because the box touches the photo edge or is unusually small. Flagged boxes are never removed automatically.

**About permanent numbers:** a pin keeps its number forever. If you reject a pin later, its number is retired, never given to another pin. If you approve it again, it gets its old number back.

## 5. The catalog

Click **Catalog** to see all approved pins. You can search by PIN number, title, tag or notes, and filter by category, tag, colour or source photo.

Click a pin to open its page. There you can:

- add a **title, description, category, subcategory, tags, quantity, prices and notes** (prices are optional),
- see its **main colours** (measured automatically from the photo),
- click **Show on original page** to see exactly where the pin sits on the photo,
- click **Make transparent PNG** to get a version with the background removed. The normal photo crop is always kept too.

The program measures colours, sizes and dates by itself. It does **not** invent titles or descriptions. Names come from you, or from an AI that actually looks at the pin:

- The first 27 pins (sample page) were named, categorised and tagged by Claude after looking at each pin. Edit any of them freely.
- New pins start without a name. Type one on the pin's page. (Automatic naming with a free local AI, Ollama, is planned; see `PROJECT_NOTES.md`.)
- AI suggestions are also kept separately in the database (`ai_suggestions`), so they never overwrite what you type.

## 6. Export and publish the website

On the Dashboard, click **Export Catalog**. This creates:

| File | What it is |
| --- | --- |
| `data/exports/catalog.csv` | Spreadsheet (opens in Excel / Google Sheets) |
| `data/exports/catalog.json` | Full data for other programs |
| `data/exports/catalog/` | The website: open `index.html` to view it |
| `docs/` | A copy of the website, ready for GitHub Pages |

**Privacy:** the website shows titles, descriptions, categories, tags, colours, quantity and selling price. It does **not** show purchase prices or private notes. You can change this in `config.toml`.

### Put the website online (GitHub Pages)

The website lives at **https://rabelo83.github.io/PinCatalog_MG/**

First time only: on GitHub open **Settings → Pages** and choose **Deploy from a branch → `main`** (either `/ (root)` or `/docs` works — the root forwards to `docs/`) → **Save**.

After each export, upload the updated `docs/` folder:

- **With GitHub Desktop:** open the repository, type a short summary such as "Add new pins", click **Commit to main**, then **Push origin**.
- **With the terminal:**

  ```
  git add docs
  git commit -m "Update catalog"
  git push
  ```

The website updates about a minute later. Your photos, crops and database (`data/`) are never uploaded.

If the website still shows the old version, your browser is using a saved copy. Press **Cmd+Shift+R** (Mac) or **Ctrl+F5** (Windows) to reload it properly.

## 7. Settings

All settings live in **`config.toml`**, with an explanation next to each one. Restart the program after changing them.

Most useful settings:

| Setting | What it does |
| --- | --- |
| `PADDING_PERCENT` | Space around each pin in the crop (default 10%) |
| `SQUARE_CROPS` | Square crops with the pin centred (default on) |
| `CLEAN_CROP_EDGES` | Paint over bits of neighbouring pins in the crop margin (default on) |
| `SIMILARITY_THRESHOLD` | How alike two pins must be to be flagged as possibly the same pin (0–1) |
| `THUMBNAIL_SIZE` | Size of catalog thumbnails |
| `GENERATE_TRANSPARENT` | Automatically make transparent PNGs when approving |
| `BACKGROUND_DISTANCE_THRESHOLD` | Lower it if faint pins are missed; raise it if shadows get detected |
| `MIN_OBJECT_AREA` / `MAX_OBJECT_AREA` | Smallest / largest pin size, as a share of the photo |
| `DETECTION_MAX_DIMENSION` | Working size used for detection (crops always use full resolution) |
| `MORPH_KERNEL_SIZE` | Shape clean-up strength |
| `CATALOG_TITLE` / `CATALOG_SUBTITLE` | Title and subtitle of the website |
| `DEBUG_MODE` | Save step-by-step detection images |

After changing crop settings, rebuild the existing pins' images (their numbers stay the same):

```
python scripts/rebuild_thumbnails.py --all
```

## 8. Command-line tools (optional)

```
python scripts/process_folder.py            # process new photos without the browser
python scripts/process_folder.py --debug    # also save detection step images
python scripts/process_folder.py --redetect 3   # run detection again on photo #3
python scripts/rebuild_thumbnails.py        # rebuild thumbnails
```

Example output:

```
Processing page_001.jpg  (1/2)
Detected candidates: 27
Pending review: 27

Processing page_002.jpg  (2/2)
Detected candidates: 31
Pending review: 31

Complete.
58 candidates awaiting review.
```

**Debug images** are saved in `data/debug/<photo>/`. They show each step of detection:

```
001_original.jpg   002_normalized.jpg   003_background_mask.jpg   004_edges.jpg
005_foreground.jpg 006_contours.jpg     007_final_detections.jpg
```

In `006_contours.jpg`, green outlines are accepted pins. Red outlines were ignored, labelled with the reason (for example "empty slot").

## 9. Where things are stored

```
data/input/          ← put new photos here
data/originals/      imported photos, untouched
data/crops/          PIN-000001.jpg …  (full-resolution crops)
data/thumbnails/     PIN-000001_thumb.jpg …
data/transparent/    PIN-000001.png …  (optional)
data/rejected/       files of pins that were rejected after approval
data/exports/        CSV, JSON and the website
data/logs/           app.log (everything) and errors.log (problems, skipped photos)
data/catalog.db      the catalog database (SQLite)
docs/                the published website
```

**Backup tip:** copy the whole `data` folder now and then. It contains everything.

## 10. How detection works (and its limits)

The detector does not assume pins are rectangles:

1. It evens out colour and contrast on a smaller working copy of the photo.
2. It works out the felt/page colour: the most common colour, plus the colour around the photo's edges.
3. It marks everything that differs from the felt (colour, dark metal outlines, edges) and fills in enclosed areas, so white parts of a pin are kept.
4. It separates pins that touch, cutting along their dark metal outlines, then finds each shape. It ignores noise by size, shape and distance from the photo edge, and anything running along the edge of the photo (table, binder).
5. It ignores **empty mounting slots**, which are grey, low-detail and mostly felt-coloured inside.
6. It merges overlapping boxes, then maps every box back to the full-resolution photo.
7. When it cuts a crop, it paints over bits of **neighbouring** pins in the margin with the felt colour (`CLEAN_CROP_EDGES`). Pale parts of the pin itself, like a mint-green head, are kept.
8. It compares each new pin with the catalog (shape and colours) to warn about **possible duplicates**.

Known limitations:

- **Pins that heavily overlap** each other may come out as one box. Use **Split**.
- **Pins the same colour as the felt** (for example a cream pin on cream felt, with no dark outline) can be missed. Use **Draw box**.
- **All-grey or silver pins** can look like empty slots and be ignored. Draw them by hand, or lower `MIN_COLORFULNESS`.
- **Busy backgrounds** (patterned fabric, or a lot of table visible) produce extra boxes. Just reject them.
- **Strong shadows or glare** can merge a pin with its shadow, making the box a bit too big. Adjust the box.
- **Look-alike check** compares shape and colours. The same design in a different colour may be flagged as similar (you decide), and a pin photographed at a very different angle may not be.
- **Colour names** are approximate. Pastel enamel under soft light can read as a neighbouring colour.
- **Perspective correction** is a preview only (Review → **Perspective**). It needs clear page edges, and detection never depends on it.

## 11. Troubleshooting

| Problem | What to do |
| --- | --- |
| `address already in use` when starting | The program is already running in another window. Use that one, or close it (Ctrl+C) and start again. |
| The website shows "404 File not found" | GitHub **Settings → Pages** must be set to deploy from branch `main`. Wait a minute after saving. |
| The website shows old names or pictures | Press Cmd+Shift+R (Mac) or Ctrl+F5 (Windows). |
| A pin is missing from the website | Check it is **approved** in Review (green), then Export Catalog and push again. |
| A crop cuts off part of a pin | In Review, drag the box's corners to include the whole pin. The crop is remade with the same PIN number. |
| A photo was skipped | See `data/logs/errors.log`. Duplicates are moved to `data/input/already_imported/`. |

## For developers

- Python 3.12+, FastAPI, Jinja2, vanilla JS, OpenCV, NumPy, Pillow, SQLite (standard library `sqlite3`).
- Run the tests with `python -m pytest`.
- Code layout: `app/vision/` (pure image processing, no database), `app/services/` (ingestion, catalog, exports), `app/routes/` (web pages and JSON API, docs at `/api/docs`).
- Database paths are stored relative to `data/`, with `/` separators, so the folder can move between Windows and Mac.
- New database columns are added automatically at start-up (`app/database.py::_migrate`).
- `index.html` + `.nojekyll` at the repository root forward the site's main address to `docs/`. The export overwrites `docs/` completely (only if it contains the `.pin-catalog-export` marker), so never hand-edit files there.
- See **`PROJECT_NOTES.md`** for design decisions, current state and open questions, and **`CHANGELOG.md`** for the history.
