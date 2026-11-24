# convert-to-ascii

Converts every GIF and still image in your input folders into per-frame ASCII
art, using the converter at https://www.ascii-magic.com/tools/image-to-ascii.
It saves one JSON file per input for a separate tool to play back. A still image
produces the same JSON as a GIF, with a single frame.

The converter runs inside the web page, so the tool drives it with headless
Chromium (Playwright). It needs an internet connection to load the page.

## 1. Install

Requires Python 3.9+. Install straight from git (replace the URL with your repo):

```
pipx install "git+https://github.com/jjmorales/<repo>.git"
```

If the package lives in a subfolder of a larger repo (for example `cli-tools`):

```
pipx install "git+https://github.com/jjmorales/cli-tools.git#subdirectory=convert-to-ascii"
```

`pipx` puts the `convert-to-ascii` command on your PATH in its own isolated
environment. Plain `pip install "git+..."` works too. Pin a version with
`...git@v0.1.0`. Upgrade with `pipx upgrade convert-to-ascii`.

Then download the browser once (pip can't do this part):

```
convert-to-ascii install
```

## 2. Quick start

In any folder:

```
convert-to-ascii --init-config     # optional: writes convert-to-ascii.json with the defaults
mkdir gifs img                    # drop your files in these
convert-to-ascii
```

```
your-folder/
├── convert-to-ascii.json   <- settings (optional; defaults are used without it)
├── gifs/                  <- .gif files
│   └── cat.gif
└── img/                   <- .png .jpg .jpeg .webp .bmp (and .gif) files
    └── logo.png
```

After a run, each input folder gets its own `ascii_json/` folder:

```
gifs/ascii_json/cat.json
img/ascii_json/logo.json
```

Options:

```
convert-to-ascii ./gifs ./photos        # scan these folders instead of input_dirs
convert-to-ascii -r                     # also scan subfolders
convert-to-ascii --out ./ascii_json     # put all output in one folder
convert-to-ascii --force                # redo output that already exists
convert-to-ascii --headed               # show the browser (for debugging)
convert-to-ascii --indent 2             # pretty-print the JSON
convert-to-ascii --config other.json    # use a different config file
convert-to-ascii --width 80 --height 40 --ramp Blocks   # one-off overrides
```

`python -m convert_to_ascii` does the same as the command.

Two inputs in the same folder with the same name (`cat.gif` and `cat.png`) would
write the same output file, so the second is skipped with a warning.

## 3. Config

Settings live in `convert-to-ascii.json`. The tool looks for it in the **current
folder**; without one it uses the defaults below. `--config PATH` points at a
different file (which must exist), and `--init-config` writes a default one. Any
key you leave out uses its default. Unknown keys and bad values stop the run with
an error that lists the valid options. Command-line flags override the config for
that run only.

| Key | Flag | Default | Options |
|---|---|---|---|
| `width` | `--width` | 100 | columns; `null` to follow the height |
| `height` | `--height` | `null` | rows; `null` to follow the width |
| `ramp` | `--ramp` | Standard | Standard, Detailed, Blocks, Terminal, Minimal, Binary |
| `contrast` | `--contrast` | 120 | slider value |
| `brightness` | `--brightness` | 0 | slider value |
| `background` | `--background` | Black | Black, White (also sets the character polarity) |
| `invert` | `--invert` / `--no-invert` | false | true, false |
| `row_density` | `--row-density` | "1.2" | Auto, 1.0, 1.2, 1.4, 1.6, 1.8 |
| `input_dirs` | (folders) | ["gifs", "img"] | folders, relative to the config file's folder |
| `output_dir_name` | | "ascii_json" | name of the output folder inside each input folder |

**Width and height:** set one and the other follows the image's aspect ratio. Set
both and the image is stretched to exactly that many columns and rows. They can't
both be `null`. The page itself only has a width control, so for a height the
tool measures how many rows the page produces and adjusts the width (height
only) or resizes the image before upload (both).

## 4. Skipping and versions

Every output records a hash of the input file and of the generation settings
(width, height, ramp, contrast, brightness, background, invert, row density).
On each run:

- An input that already has output made from the **same file and settings** is
  skipped. `--force` regenerates that file in place instead.
- If the settings (or the input file) changed, the new output is saved as the
  next version and the earlier ones are kept:

```
cat.json        <- version 1 (first settings)
cat.v2.json     <- after editing the config
cat.v3.json     <- after editing it again
```

Changing back to settings that already have a version reuses that version.
Output made by the older `gif_to_ascii.py` has no hashes, so it never counts as a
match; the next run creates a new version beside it, and you can delete the old file.

## 5. Output format

```json
{
  "format": "ascii-animation/v1",
  "version": 1,
  "source": "cat.gif",
  "source_type": "gif",
  "source_hash": "…",
  "settings_hash": "…",
  "frame_count": 12,
  "loop": 0,
  "pixel_size": [320, 240],
  "ascii_size": {"cols": 100, "rows": 75},
  "settings": { "width": 100, "height": null, "ramp": "Standard", "...": "..." },
  "frames": [
    {"frame": 0, "label": "frame_0000", "duration_ms": 80, "ascii": "row1\nrow2\n..."}
  ]
}
```

`source_type` is `"gif"` or `"image"`. For a still image `frame_count` is 1,
`duration_ms` is 0 and `loop` is `null`.

To play it back, show each frame's `ascii` string in order and wait that frame's
`duration_ms` before showing the next. For a GIF, `loop` is its loop count (0
means forever, `null` means not set).

## Development

```
git clone https://github.com/jjmorales/cli-tools.git && cd cli-tools/convert-to-ascii
python -m venv .venv && .venv\Scripts\activate     # source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
convert-to-ascii install
pytest
```

Code is in `src/convert_to_ascii/`: `config.py` (settings), `versioning.py`
(skip/version decisions), `convert.py` (frames and the page), `cli.py`.
The tests don't need a browser. The tool depends on the website's page layout
rather than a stable API, so a site change can break it (see below).

## Troubleshooting

- **"Chromium is not installed":** run `convert-to-ascii install`.
- **`convert-to-ascii: command not found`:** use `pipx` (it sets up PATH), or run
  `python -m convert_to_ascii` instead.
- **Timed out waiting for a frame:** the page is slow or its layout changed. Try
  `--timeout-ms 40000`, or run with `--headed` to watch what happens.
- **Identical frames come out wrong or lag behind:** raise `--settle-ms`
  (default 500).
- **A control can't be found (error mentions a label like "Output width"):** the
  site changed its labels. Update `apply_settings` in `src/convert_to_ascii/convert.py`.
- **A "width != requested" or "height != requested" warning:** the page reported a
  different size than you asked for, for example a width beyond the page's slider
  range. Check the settings with `--headed`.
