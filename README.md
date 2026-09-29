# Label maker

Print text and pictures on a sheet of stickers.  
The default sheet is 110×152 mm, two columns and four rows of 52×34 mm labels.

Text and SVG drawings are vectors.  
Photos and other pictures are placed at 300 dpi.  
A picture with a flat margin is trimmed to the artwork.

`--help` prints the short option list.  
`--man` opens this manual.

## Install

pipx keeps the tool in its own environment and puts `make-labels` on your PATH.

From the project folder:

```bash
pipx install .
```

While you are changing the code, install it in place so edits apply immediately:

```bash
pipx install --force --editable .
```

After a normal install, pick up later changes with:

```bash
pipx reinstall label-maker
```

Python 3.10 or newer is required.  
pipx installs Click and Pillow for you.

You can also run it from this folder without installing.  
This creates `.venv` here:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python make-labels.py --help
```

`python3 make-labels.py` does the same thing when `.venv` already exists.  
It writes the PDF in the folder you ran it from.

## Sheets

With no arguments the sheet alternates MASTER (green) and SLAVE (red):

```bash
make-labels
```

That writes `labels.pdf`.  
`--proof` adds the alignment grid and a 100 mm ruler.  
`--outline` draws only the grid and the ruler.

```bash
make-labels --proof -o check.pdf
make-labels --outline -o alignment.pdf
```

Other sheets use millimetres.  
This is an A4 sheet of 63.5×33.9 mm labels:

```bash
make-labels --page-w 210 --page-h 297 --cols 3 --rows 8 \
  --lw 63.5 --lh 33.9 --gap-x 2.5 --gap-y 0
```

`--limit 4` prints only the first four stickers.  
`--row 2` prints one row.  
`--skip-row` and `--skip-col` leave a row or column blank.  
If the grid does not fit the page, nothing is written unless you pass `--force`.

## Printer calibration

Printers do not always place a sheet at exactly the expected origin.  
`--offset-x` and `--offset-y` correct that mechanical drift without changing the label size or spacing.  
A positive `--offset-x` moves the grid right.  
A positive `--offset-y` moves it down.  
Negative values move it left or up.

First print a proof on ordinary paper cut to the same dimensions as the sticker sheet:

```bash
make-labels --proof --out calibration.pdf
```

Place the print behind a sticker sheet and hold both against a light to compare the proof boxes with the stickers.  
Two stickers carry a millimetre scale.  
On a sheet of four or more rows they are the second row and the second-to-last row, at opposite ends.  
The first and last rows stay plain, because many printers cannot print the edge of the page.  
On a shorter sheet the ticks sit on the side of the sticker that faces the middle of the page.  
The shortest ticks mark half a millimetre.  
The longer ticks are numbered in millimetres.  
Read the number at the sticker edge.  
That number is the offset.  
If the boxes are 2 mm too far left and 1 mm too high, move them right and down:

```bash
make-labels --proof --offset-x 2 --offset-y 1 --out calibration.pdf
```

Print the adjusted proof and check it again.  
You can print the second test on the other side of the same ordinary sheet.  
Keep the paper orientation and feed direction the same for every test.

Use sticker sheets only when the printer supports their dimensions, material, and media type.  
Follow the printer and sticker-sheet instructions for the correct tray, printable side, and laser or inkjet compatibility.

## Print settings

The PDF page has the exact dimensions passed with `--page-w` and `--page-h`.  
Create or select a paper size in the printer settings with those same dimensions.  
For the default sheet, use 110×152 mm.  
Choose the orientation that matches the PDF.

Print at Actual Size or 100%.  
Turn off Fit, Shrink oversized pages, Scale to fit, and any automatic enlargement.  
Do not use borderless printing unless the printer can keep it at 100%, because many borderless modes enlarge and crop the page.

Select the tray and media type recommended for the sticker sheet.  
Labels, Heavy Paper, or Cardstock settings may change the feed speed and temperature.  
Turn off duplex printing and print only on the printable side of the sticker sheet.

Print a proof on ordinary paper before using a sticker sheet.  
Measure the printed 100 mm ruler with a physical ruler.  
If it is not exactly 100 mm, correct the printer scaling before changing either offset.  
Offsets fix position, not size.

Save the working paper size and printer options as a printer preset when the print dialog supports presets.  
Use the same preset, tray, orientation, and feed direction for the calibration proof and the sticker sheet.

## Text

Repeat `--text` once per sticker.  
A real newline or the two characters `\n` starts another line.  
Colors follow the text stickers in order.  
Names (`green`, `red`, `blue`, and the others listed under `--color`) and `#rrggbb` both work.  
Hebrew uses an embedded font.

```bash
make-labels --text 'MASTER\nSAW' --text 'SLAVE\nVAC' --color green --color red
make-labels --text 'מסור\nשואב' --color blue
```

`--rotate` turns the content from the bottom of the sticker toward the top.  
`--font-mm 8` sets the letter height.

## Pictures

SVG files are drawn as vectors.  
PNG, JPEG, GIF, WebP, BMP, TIFF, and AVIF are embedded at 300 dpi for the sticker.

```bash
make-labels --image logo.svg --image mark.png
```

`--trace` outlines a flat logo as vector paths.  
A photograph stays embedded, because tracing it would not stay sharp.

One sticker can hold a logo and text.  
`--combo` uses the same sticker text as `--cell`, without the row and column.  
`PATH|TEXT` puts the logo before the words.  
`PATH TEXT` as two words means the same thing.  
A third field of `left`, `right`, or `top` is the layout.  
Any other third field is a logo after the words.  
A fourth field is the layout.  
A colour name or `#rrggbb` after the last comma colours the words.  
`--layout` is the default when that text does not name a layout.  
One `--layout top` puts the logo above the words on every such combo.  
A combo that names an end logo keeps a logo on both sides.  
Both logos match the text height and share its vertical center.

`--layout left` puts the logo before the text.  
`--layout right` puts it after the text.  
`--layout top` puts it above the text.

```bash
make-labels --combo logo.svg 'MASTER\nSAW'
make-labels --combo 'logo.svg|SLAVE\nVAC' --layout right --color red
make-labels --combo 'logo.svg|MASTER|mark.png'
make-labels --combo 'logo.svg|FIRST|top' --combo 'mark.png|SECOND|right'
```

## Single cells

`--cell` fills one sticker and leaves the rest of the sheet blank.  
Rows and columns start at 1.  
`@path` is a picture.  
`@path|text` is a logo before the text.  
`@path|text|end` puts a logo on each side.  
`@|text|end` puts the logo after the text.  
`@path|text|top` puts that logo above the words.  
`@path|text|end|right` sets the end logo and the layout.  
`left`, `right`, and `top` in that position are layouts.  
A color after the last comma applies to the text.

```bash
make-labels --cell '1,1,@logo.svg|מסור,blue'
make-labels --cell 1,1,@logo.png --cell 1,2,N,black
```

## Switches

Sizes are millimetres.  
Pass a repeatable switch again for another sticker.  
The last column links each switch to its sheet in `examples/`.  
The sheets in `examples/` are drawn so the change is easy to see.  
`--help`, `--man`, and `--completion` print text, so `examples/` has no sheet for them.

| Switch | Default | What it does | Example |
| --- | --- | --- | --- |
| `-W`, `--page-w` | 110 | Width of the paper. | `make-labels --page-w 210`<br>[examples/page-w.pdf](examples/page-w.pdf) |
| `-H`, `--page-h` | 152 | Height of the paper. | `make-labels --page-h 297`<br>[examples/page-h.pdf](examples/page-h.pdf) |
| `-c`, `--cols` | 2 | How many stickers fit across the page. | `make-labels --cols 3`<br>[examples/cols.pdf](examples/cols.pdf) |
| `-r`, `--rows` | 4 | How many stickers fit down the page. | `make-labels --rows 8`<br>[examples/rows.pdf](examples/rows.pdf) |
| `-w`, `--lw` | 52 | Width of one sticker. | `make-labels --lw 63.5`<br>[examples/lw.pdf](examples/lw.pdf) |
| `-t`, `--lh` | 34 | Height of one sticker. | `make-labels --lh 33.9`<br>[examples/lh.pdf](examples/lh.pdf) |
| `-g`, `--gap-x` | 2.7 | Horizontal space between stickers.<br>When you leave `--margin-x` out, the leftover space is split into equal left and right margins. | `make-labels --gap-x 2.5`<br>[examples/gap-x.pdf](examples/gap-x.pdf) |
| `-G`, `--gap-y` | 4 | Vertical space between stickers.<br>When you leave `--margin-y` out, the leftover space is split into equal top and bottom margins. | `make-labels --gap-y 0`<br>[examples/gap-y.pdf](examples/gap-y.pdf) |
| `-m`, `--margin-x` | centered | Left margin.<br>The row of stickers sits in the middle of the page. | `make-labels --margin-x 5`<br>[examples/margin-x.pdf](examples/margin-x.pdf) |
| `-M`, `--margin-y` | centered | Top margin.<br>The column of stickers sits in the middle of the page.<br>`--offset-y` is applied after that. | `make-labels --margin-y 5`<br>[examples/margin-y.pdf](examples/margin-y.pdf) |
| `-x`, `--offset-x` | 0 | Extra shift to the right, after the margin. | `make-labels --offset-x 1`<br>[examples/offset-x.pdf](examples/offset-x.pdf) |
| `-y`, `--offset-y` | 0 | Extra shift down, after the margin.<br>A positive number moves the stickers down. | `make-labels --offset-y 10`<br>[examples/offset-y.pdf](examples/offset-y.pdf) |
| `-T`, `--text` | MASTER, SLAVE | Words for one sticker.<br>Repeat it for the next sticker.<br>A real line break, or the two characters `\n`, starts a new line.<br>With no stickers chosen, the sheet alternates those two words, green then red. | `make-labels --text 'MASTER\nSAW' --text 'SLAVE\nVAC'`<br>[examples/text.pdf](examples/text.pdf) |
| `-I`, `--image` | — | A picture for one sticker.<br>Repeat it for the next sticker.<br>SVG is drawn as vectors.<br>PNG, JPEG, GIF, WebP, BMP, TIFF, and AVIF are placed at 300 dpi. | `make-labels --image logo.svg`<br>[examples/image.pdf](examples/image.pdf) |
| `--trace` | off | Outline a flat logo as vector paths.<br>A photograph stays an embedded picture, because a trace of it would not stay sharp. | `make-labels --image logo.png --trace`<br>[examples/trace.pdf](examples/trace.pdf) |
| `--combo` `SPEC` | — | One sticker with a logo and words, using the same text as `--cell`.<br>`PATH\|TEXT` puts the logo before the words.<br>`PATH TEXT` as two words means the same thing.<br>A third field of `left`, `right`, or `top` is the layout.<br>Any other third field is a logo after the words.<br>A fourth field is the layout.<br>A colour after the last comma colours the words.<br>Repeat it for another sticker. | `make-labels --combo 'logo.svg\|MASTER\|mark.png\|top'`<br>[examples/combo.pdf](examples/combo.pdf) |
| `--layout` `CHOICE` | `left` | Default layout for every `--combo` and `--cell` that does not name its own.<br>`top` puts that logo above its words.<br>`left` puts that logo before its words.<br>`right` puts that logo after its words.<br>A sticker that names an end logo keeps a logo on both sides. | `make-labels --combo logo.svg MASTER --layout top`<br>[examples/layout.pdf](examples/layout.pdf) |
| `-C`, `--color` | green, red, blue, purple | Colour of the next text or combo sticker, in order.<br>Repeat it for the next one.<br>A picture-only sticker does not take a colour.<br>A `--combo` that names its own colour keeps the next `--color` for the next sticker.<br>Use a name or `#rrggbb`.<br>Names: black, white, red, green, blue, yellow, orange, purple, grey, gray, brown. | `make-labels --text MASTER --color green`<br>[examples/color.pdf](examples/color.pdf) |
| `-e`, `--cell` | — | Fill one sticker and leave the rest of the sheet blank.<br>Repeat it for another sticker.<br>The form is `ROW,COL,TEXT`.<br>Rows and columns start at 1.<br>`@path` is a picture.<br>`@path\|text` is a logo before the words.<br>`@path\|text\|end` puts a logo on each side.<br>`@\|text\|end` puts the logo after the text.<br>`@path\|text\|top` puts that logo above the words.<br>`@path\|text\|end\|right` sets the end logo and the layout.<br>`left`, `right`, and `top` in that position are layouts.<br>A colour name or `#rrggbb` after the last comma colours the words. | `make-labels --cell '1,1,@logo.svg\|MASTER\|top,blue'`<br>[examples/cell.pdf](examples/cell.pdf) |
| `-F`, `--font-mm` | fit | Letter height.<br>The letters grow until they fit the sticker. | `make-labels --font-mm 8`<br>[examples/font-mm.pdf](examples/font-mm.pdf) |
| `-R`, `--rotate` | off | Turn the sticker contents so they read from the bottom toward the top. | `make-labels --text MASTER --rotate`<br>[examples/rotate.pdf](examples/rotate.pdf) |
| `-n`, `--limit` | all | How many stickers to print, starting at the first.<br>The rest of the grid stays blank. | `make-labels --limit 4`<br>[examples/limit.pdf](examples/limit.pdf) |
| `-L`, `--row` | all | Which row to print.<br>Rows start at 1.<br>The other rows stay blank. | `make-labels --row 2`<br>[examples/row.pdf](examples/row.pdf) |
| `-S`, `--skip-row` | — | Leave this row blank.<br>Rows start at 1.<br>Repeat it for another row. | `make-labels --skip-row 3`<br>[examples/skip-row.pdf](examples/skip-row.pdf) |
| `-s`, `--skip-col` | — | Leave this column blank.<br>Columns start at 1.<br>Repeat it for another column. | `make-labels --skip-col 1`<br>[examples/skip-col.pdf](examples/skip-col.pdf) |
| `-b`, `--outline` | off | Draw the sticker borders and a 100 mm ruler, with no words or pictures.<br>The file is `alignment.pdf` when you leave `--out` out. | `make-labels --outline`<br>[examples/outline.pdf](examples/outline.pdf) |
| `-p`, `--proof` | off | Draw the words and pictures, and also the borders and the 100 mm ruler.<br>The file is `proof.pdf` when you leave `--out` out. | `make-labels --proof`<br>[examples/proof.pdf](examples/proof.pdf) |
| `-f`, `--force` | off | Write the PDF even when the stickers run off the page. | `make-labels --force`<br>[examples/force.pdf](examples/force.pdf) |
| `-o`, `--out` | `labels.pdf` | Where to write the PDF.<br>`--proof` writes `proof.pdf` and `--outline` writes `alignment.pdf` when this switch is left out. | `make-labels --out sheet.pdf`<br>[examples/sheet.pdf](examples/sheet.pdf) |
| `-h`, `--help` | — | Print the short option list and exit. | `make-labels --help` |
| `--man` | — | Open this manual and exit.<br>When the output is a pipe, the manual is the raw man page instead. | `make-labels --man` |
| `--completion` `SHELL` | — | Print a shell completion script and exit.<br>`SHELL` is `zsh`, `bash`, or `fish`. | `make-labels --completion zsh` |

## Shell completion

The completion script comes from Click.  
It completes switch names, `--layout` values, colour names, and file paths for pictures.

For the current terminal:

```bash
eval "$(make-labels --completion zsh)"
```

To keep it in zsh, save the script where `compinit` looks:

```bash
mkdir -p ~/.zfunc
make-labels --completion zsh > ~/.zfunc/_make-labels
```

Add this to `~/.zshrc` if tab does nothing, then open a new terminal:

```bash
fpath=(~/.zfunc $fpath)
autoload -Uz compinit && compinit
```

Bash:

```bash
make-labels --completion bash > ~/.make-labels-complete.bash
```

Add this line to `~/.bashrc`, then open a new terminal:

```bash
source ~/.make-labels-complete.bash
```

Fish:

```bash
mkdir -p ~/.config/fish/completions
make-labels --completion fish > ~/.config/fish/completions/make-labels.fish
```

## From Python

`render_pdf` returns the PDF bytes.  
A future UI can call the same function.

```python
from labels import SheetSpec, TextSticker, render_pdf

pdf = render_pdf(SheetSpec(
    stickers=(
        TextSticker("MASTER\nSAW", (0.00, 0.55, 0.22)),
        TextSticker("SLAVE\nVAC", (0.82, 0.08, 0.10)),
    ),
))
```

A plain dict with the old names (`page_w`, `cols`, `lw`, `text`, `color`, `cell`) still works.

## License

Copyright © 2026 Ori Ben-Hur.  
This project is available under the [MIT License](LICENSE).  
You may use, modify, and distribute it, but copies or substantial portions must keep the copyright and license notice.
