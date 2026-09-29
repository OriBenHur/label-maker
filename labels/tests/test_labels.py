from __future__ import annotations

import hashlib
import importlib
import os
import re
import subprocess
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

from click.testing import CliRunner
from PIL import Image

from labels import (
    CellOverride,
    ComboSticker,
    ImageSticker,
    LabelError,
    LayoutError,
    SheetSpec,
    TextSticker,
    render_pdf,
    to_svg,
)
from labels.svg_draw import INSET
from labels.to_svg import PRINT_DPI, fit_box, sticker_px
from labels.cli import main
from labels.manual import man_page
from labels.pdf import MM, TTF_PATH


def content_stream(pdf: bytes) -> str:
    match = re.search(
        rb"4 0 obj\n<< /Length (\d+) >>\nstream\n",
        pdf,
    )
    if match is None:
        raise AssertionError("PDF content stream not found")
    length = int(match.group(1))
    return pdf[match.end():match.end() + length].decode("latin-1")


class LabelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_svg(self, name: str = "mark.svg") -> Path:
        path = self.directory / name
        path.write_text(
            '<svg viewBox="0 0 20 20">'
            '<rect width="20" height="20" fill="#111"/>'
            '<circle cx="10" cy="10" r="5" fill="#f00"/>'
            "</svg>"
        )
        return path

    def write_pixels(self, name: str = "mark.png", alpha: bool = False) -> Path:
        path = self.directory / name
        image = Image.new("RGBA", (12, 8), (255, 255, 255, 0 if alpha else 255))
        for y in range(2, 6):
            for x in range(3, 9):
                image.putpixel((x, y), (220, 20, 20, 255))
        image.save(path)
        return path

    def test_default_pdf_is_byte_compatible(self) -> None:
        pdf = render_pdf({})
        self.assertEqual(len(pdf), 1422)
        self.assertEqual(
            hashlib.sha256(pdf).hexdigest(),
            "f6929bc49cc8c7255c2953e86772838116df829db49f5e65d3d599f0f467e5d5",
        )

    def test_typed_spec_is_the_public_backend(self) -> None:
        spec = SheetSpec(
            rows=1,
            columns=2,
            page_height_mm=40,
            offset_y_mm=0,
            stickers=(
                TextSticker("SAW", (0, 0, 1)),
                TextSticker("VAC", (1, 0, 0)),
            ),
        )
        stream = content_stream(render_pdf(spec))
        self.assertLess(stream.index("(SAW)"), stream.index("(VAC)"))
        self.assertIn("0.000 0.000 1.000 rg", stream)

    def test_legacy_dict_input_remains_supported(self) -> None:
        pdf = render_pdf(
            {
                "rows": 1,
                "cols": 1,
                "text": ["OLD"],
                "color": ["blue"],
                "cell": None,
                "skip_row": None,
                "skip_col": None,
            }
        )
        stream = content_stream(pdf)
        self.assertIn("(OLD)", stream)
        self.assertIn("0.120 0.280 0.720 rg", stream)

    def test_multiline_text_accepts_real_and_escaped_newlines(self) -> None:
        spec = SheetSpec(
            rows=1,
            columns=2,
            page_height_mm=40,
            offset_y_mm=0,
            stickers=(
                TextSticker("TOP\nBOTTOM"),
                TextSticker("LEFT\\nRIGHT"),
            ),
        )
        stream = content_stream(render_pdf(spec))
        self.assertEqual(stream.count(" Tj"), 4)
        for word in ("TOP", "BOTTOM", "LEFT", "RIGHT"):
            self.assertIn(f"({word})", stream)

    @unittest.skipUnless(Path(TTF_PATH).is_file(), "Hebrew test font is unavailable")
    def test_multiline_hebrew_uses_embedded_font(self) -> None:
        pdf = render_pdf(
            SheetSpec(
                rows=1,
                columns=1,
                stickers=(TextSticker("מאסטר\\nמסור"),),
            )
        )
        self.assertEqual(content_stream(pdf).count("/F2 "), 2)
        self.assertIn(b"/FontFile2", pdf)

    def test_svg_stays_vector(self) -> None:
        path = self.write_svg()
        pdf = render_pdf(
            SheetSpec(rows=1, columns=1, stickers=(ImageSticker(path),))
        )
        stream = content_stream(pdf)
        self.assertIn(" re f", stream)
        self.assertGreaterEqual(stream.count(" c "), 4)
        self.assertNotIn(b"/Subtype /Image", pdf)

    def test_supported_raster_formats_become_pdf_images(self) -> None:
        formats = {
            "png": "PNG",
            "gif": "GIF",
            "jpg": "JPEG",
            "webp": "WEBP",
            "bmp": "BMP",
            "tif": "TIFF",
        }
        for extension, image_format in formats.items():
            with self.subTest(extension=extension):
                path = self.directory / f"swatch.{extension}"
                Image.new("RGB", (6, 4), (10, 20, 30)).save(
                    path,
                    format=image_format,
                )
                pdf = render_pdf(
                    SheetSpec(
                        rows=1,
                        columns=1,
                        stickers=(ImageSticker(path),),
                    )
                )
                self.assertIn(b"/Subtype /Image", pdf)
                self.assertIn("/Im0 Do", content_stream(pdf))

    def test_raster_keeps_the_top_of_the_picture_up(self) -> None:
        import zlib
        path = self.directory / "bars.png"
        image = Image.new("RGB", (4, 2), (0, 0, 255))
        for x in range(4):
            image.putpixel((x, 0), (255, 0, 0))
        image.save(path)
        pdf = render_pdf(SheetSpec(rows=1, columns=1, stickers=(ImageSticker(path),)))
        marker = b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Interpolate false"
        start = pdf.index(marker)
        length = int(re.search(rb"/Length (\d+)", pdf[start:start + 200]).group(1))
        stream_at = pdf.index(b"stream\n", start) + len(b"stream\n")
        raw = zlib.decompress(pdf[stream_at:stream_at + length])
        self.assertEqual(raw[:3], b"\xff\x00\x00")
        self.assertRegex(content_stream(pdf), r"0 0 -\d+(?:\.\d+)? \d+(?:\.\d+)? \d+(?:\.\d+)? cm /Im0 Do")

    def test_raster_transparency_uses_a_soft_mask(self) -> None:
        path = self.write_pixels(alpha=True)
        pdf = render_pdf(
            SheetSpec(rows=1, columns=1, stickers=(ImageSticker(path),))
        )
        self.assertIn(b"/SMask", pdf)
        self.assertEqual(pdf.count(b"/Subtype /Image"), 2)

    def test_trace_fallback_outputs_paths(self) -> None:
        path = self.write_pixels()
        conversion = importlib.import_module("labels.to_svg")

        previous = conversion._VTRACER_OK
        conversion._VTRACER_OK = False
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                svg = to_svg(path, trace=True)
                pdf = render_pdf(
                    SheetSpec(
                        rows=1,
                        columns=1,
                        stickers=(ImageSticker(path),),
                        trace=True,
                    )
                )
        finally:
            conversion._VTRACER_OK = previous
        self.assertIn("<path", svg)
        self.assertNotIn("<image", svg)
        self.assertNotIn(b"/Subtype /Image", pdf)

    def test_trace_leaves_a_photo_embedded(self) -> None:
        path = self.directory / "photo.png"
        image = Image.new("RGB", (48, 48))
        pixels = image.load()
        for y in range(48):
            for x in range(48):
                pixels[x, y] = (x * 5, y * 5, (x * y) % 256)
        image.save(path)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            svg = to_svg(path, trace=True)
        self.assertIn("<image", svg)
        self.assertTrue(any("photograph" in str(item.message) for item in caught))

    def test_cell_overrides_leave_other_cells_blank(self) -> None:
        image = self.write_svg()
        spec = SheetSpec(
            rows=1,
            columns=3,
            page_width_mm=180,
            cells=(
                CellOverride(1, 1, ImageSticker(image)),
                CellOverride(1, 2, TextSticker("N", (0, 0, 0))),
            ),
        )
        stream = content_stream(render_pdf(spec))
        self.assertIn(" re f", stream)
        self.assertEqual(stream.count("(N)"), 1)
        self.assertNotIn("(MASTER)", stream)

    def test_rotation_applies_to_text_and_images(self) -> None:
        image = self.write_svg()
        text_pdf = render_pdf(
            SheetSpec(
                rows=1,
                columns=1,
                rotate=True,
                stickers=(TextSticker("SIDE"),),
            )
        )
        image_pdf = render_pdf(
            SheetSpec(
                rows=1,
                columns=1,
                rotate=True,
                stickers=(ImageSticker(image),),
            )
        )
        self.assertRegex(content_stream(text_pdf), r"q 0 1 -1 0 [\d.]+ [\d.]+ cm")
        self.assertIn("0 1 -1 0 0 0 cm", content_stream(image_pdf))

    def test_overflow_requires_force(self) -> None:
        with self.assertRaisesRegex(LayoutError, "overflows"):
            render_pdf(SheetSpec(label_width_mm=200))
        pdf = render_pdf(SheetSpec(label_width_mm=200, force=True))
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))

    def test_proof_scale_avoids_the_outer_rows(self) -> None:
        proof = content_stream(render_pdf(SheetSpec(proof=True)))
        page = 152 * MM
        margin = 2 * MM
        label = 34 * MM
        gap = 4 * MM
        row1_top = page - margin - (label + gap) 
        self.assertIn(f"{row1_top:.2f} m", proof)
        self.assertIn(f"{(1.65 * MM + 0.5 * MM):.2f} {row1_top:.2f} m", proof)
        self.assertIn("(5)", proof)
        self.assertIn("(10)", proof)
        row0_top = page - margin
        self.assertNotIn(
            f"{(1.65 * MM + MM):.2f} {row0_top:.2f} m",
            proof,
        )
        short = content_stream(
            render_pdf(SheetSpec(rows=1, page_height_mm=50, proof=True))
        )
        sticker_top = 50 * MM - (50 * MM - 34 * MM) / 2
        self.assertNotIn(f"{sticker_top:.2f} m", short)
        self.assertIn(f"{(sticker_top - 5 * MM):.2f} m", short)

    def test_outline_and_proof_keep_the_old_behavior(self) -> None:
        outline = content_stream(render_pdf(SheetSpec(outline=True)))
        proof = content_stream(render_pdf(SheetSpec(proof=True)))
        self.assertIn("(100 mm)", outline)
        self.assertNotIn("(MASTER)", outline)
        self.assertIn("(100 mm)", proof)
        self.assertIn("(MASTER)", proof)

    def test_missing_and_invalid_images_fail_cleanly(self) -> None:
        missing = self.directory / "missing.png"
        with self.assertRaisesRegex(FileNotFoundError, "no such image"):
            render_pdf(
                SheetSpec(
                    rows=1,
                    columns=1,
                    stickers=(ImageSticker(missing),),
                )
            )
        invalid = self.directory / "invalid.png"
        invalid.write_text("not a picture")
        with self.assertRaisesRegex(LabelError, "cannot read"):
            to_svg(invalid)

    def test_click_preserves_mixed_sticker_order_and_text_colors(self) -> None:
        runner = CliRunner()
        image = self.write_svg()
        output = self.directory / "mix.pdf"
        result = runner.invoke(
            main,
            [
                "--text", "AAA",
                "--image", str(image),
                "--text", "BBB",
                "--color", "blue",
                "--page-w", "180",
                "--rows", "1",
                "--cols", "3",
                "--offset-y", "0",
                "--out", str(output),
            ],
        )
        self.assertEqual(result.exit_code, 0, result.output)
        stream = content_stream(output.read_bytes())
        self.assertLess(stream.index("(AAA)"), stream.index(" re f"))
        self.assertLess(stream.index(" re f"), stream.index("(BBB)"))
        self.assertIn("0.120 0.280 0.720 rg", stream)

    def test_click_reports_bad_input_without_a_traceback(self) -> None:
        result = CliRunner().invoke(main, ["--image", "missing.png"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("does not exist", result.output)
        self.assertNotIn("Traceback", result.output)

    def test_click_does_not_write_an_overflowing_sheet(self) -> None:
        output = self.directory / "overflow.pdf"
        result = CliRunner().invoke(
            main,
            ["--lw", "200", "--out", str(output)],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("overflows", result.output)
        self.assertFalse(output.exists())

    def test_legacy_script_path_still_runs(self) -> None:
        script = Path(__file__).parents[1] / "make_labels.py"
        output = self.directory / "legacy.pdf"
        environment = dict(os.environ)
        root = str(Path(__file__).parents[2])
        environment["PYTHONPATH"] = os.pathsep.join(
            part for part in (root, environment.get("PYTHONPATH", "")) if part
        )
        process = subprocess.run(
            [
                sys.executable,
                str(script),
                "--limit",
                "1",
                "--out",
                str(output),
            ],
            capture_output=True,
            text=True,
            env=environment,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(output.is_file())
        stream = content_stream(output.read_bytes())
        self.assertEqual(stream.count("(MASTER)"), 1)
        self.assertNotIn("(SLAVE)", stream)

    def test_project_launcher_runs_from_any_directory(self) -> None:
        script = Path(__file__).parents[2] / "make-labels.py"
        output = self.directory / "launched.pdf"
        process = subprocess.run(
            [sys.executable, str(script), "--limit", "1", "--out", str(output)],
            cwd=self.directory,
            capture_output=True,
            text=True,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(output.is_file())
        stream = content_stream(output.read_bytes())
        self.assertEqual(stream.count("(MASTER)"), 1)

    def test_raster_is_resampled_to_300_dpi(self) -> None:
        self.assertEqual(PRINT_DPI, 300)
        box = sticker_px(52, 34, INSET)
        small = self.directory / "small.png"
        Image.new("RGB", (6, 4), (10, 20, 30)).save(small)
        large = self.directory / "large.png"
        Image.new("RGB", (2000, 500), (10, 20, 30)).save(large)
        for path, source in ((small, (6, 4)), (large, (2000, 500))):
            with self.subTest(path=path.name):
                pdf = render_pdf(
                    SheetSpec(rows=1, columns=1, stickers=(ImageSticker(path),))
                )
                width, height = fit_box(*source, *box)
                self.assertNotEqual((width, height), source)
                self.assertIn(f"/Width {width}".encode(), pdf)
                self.assertIn(f"/Height {height}".encode(), pdf)
                self.assertIn(b"/Interpolate false", pdf)

    def test_trace_limit_follows_the_sticker_not_512(self) -> None:
        path = self.directory / "flat.png"
        Image.new("RGB", (800, 40), (220, 20, 20)).save(path)
        conversion = importlib.import_module("labels.to_svg")
        previous = conversion._VTRACER_OK
        conversion._VTRACER_OK = False
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                svg = to_svg(path, trace=True, box=(100, 80))
        finally:
            conversion._VTRACER_OK = previous
        self.assertIn('viewBox="0 0 100 5"', svg)
        self.assertNotIn('viewBox="0 0 512', svg)

    def test_combo_places_text_beside_or_under_the_picture(self) -> None:
        image = self.write_svg()
        for layout in ("left", "top"):
            with self.subTest(layout=layout):
                pdf = render_pdf(
                    SheetSpec(
                        rows=1,
                        columns=1,
                        stickers=(ComboSticker(image, "MASTER\nSAW", layout=layout),),
                    )
                )
                stream = content_stream(pdf)
                self.assertIn(" re f", stream)
                self.assertIn("(MASTER)", stream)
                self.assertIn("(SAW)", stream)
                self.assertLess(stream.index(" re f"), stream.index("(MASTER)"))
                if layout == "left":
                    picture = re.search(
                        r"([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) re W n",
                        stream,
                    )
                    text_at = re.search(
                        r"1 0 0 1 [\d.]+ ([\d.]+) cm\n[\d.]+ [\d.]+ [\d.]+ rg\nBT",
                        stream,
                    )
                    self.assertIsNotNone(picture)
                    self.assertIsNotNone(text_at)
                    picture_y = float(picture.group(2))
                    picture_h = float(picture.group(4))
                    label_h = 34 * 72 / 25.4
                    self.assertLess(picture_h, label_h * 0.8)
                    self.assertAlmostEqual(
                        picture_y + picture_h / 2,
                        float(text_at.group(1)),
                        delta=0.6,
                    )

    def test_combo_logo_can_follow_the_text_or_flank_it(self) -> None:
        image = self.write_svg()
        end = self.write_svg("end.svg")
        label_h = 34 * 72 / 25.4
        cases = {
            "right": ComboSticker(image, "MASTER", layout="right"),
            "both": ComboSticker(image, "MASTER", end=end),
        }
        for name, sticker in cases.items():
            with self.subTest(name=name):
                pdf = render_pdf(
                    SheetSpec(rows=1, columns=1, stickers=(sticker,))
                )
                stream = content_stream(pdf)
                rects = re.findall(
                    r"([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) re W n",
                    stream,
                )
                text_at = re.search(
                    r"1 0 0 1 ([\d.]+) ([\d.]+) cm\n[\d.]+ [\d.]+ [\d.]+ rg\nBT",
                    stream,
                )
                self.assertIsNotNone(text_at)
                text_x = float(text_at.group(1))
                text_y = float(text_at.group(2))
                if name == "right":
                    self.assertEqual(len(rects), 1)
                    self.assertLess(text_x, float(rects[0][0]))
                else:
                    self.assertEqual(len(rects), 2)
                    self.assertLess(float(rects[0][0]), text_x)
                    self.assertLess(text_x, float(rects[1][0]))
                for rect in rects:
                    picture_h = float(rect[3])
                    self.assertLess(picture_h, label_h * 0.8)
                    self.assertAlmostEqual(
                        float(rect[1]) + picture_h / 2,
                        text_y,
                        delta=0.6,
                    )

    def test_layout_top_puts_every_combo_logo_above_its_words(self) -> None:
        image = self.write_svg()
        output = self.directory / "tops.pdf"
        result = CliRunner().invoke(
            main,
            [
                "--combo", str(image), "FIRST",
                "--combo", str(image), "SECOND",
                "--layout", "top",
                "--rows", "1",
                "--cols", "2",
                "--page-w", "120",
                "--offset-y", "0",
                "--out", str(output),
            ],
        )
        self.assertEqual(result.exit_code, 0, result.output)
        stream = content_stream(output.read_bytes())
        rects = [
            tuple(float(part) for part in rect)
            for rect in re.findall(
                r"([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) re W n",
                stream,
            )
        ]
        self.assertEqual(len(rects), 2)
        for name in ("FIRST", "SECOND"):
            at = stream.index(f"({name})")
            text_y = float(re.findall(r"1 0 0 1 [\d.]+ ([\d.]+) cm", stream[:at])[-1])
            text_x = float(re.findall(r"1 0 0 1 ([\d.]+) [\d.]+ cm", stream[:at])[-1])
            picture = next(
                rect for rect in rects
                if rect[0] <= text_x <= rect[0] + rect[2]
            )
            self.assertGreater(picture[1], text_y)

    def test_combo_layout_overrides_one_sticker(self) -> None:
        image = self.write_svg()
        output = self.directory / "mixed.pdf"
        result = CliRunner().invoke(
            main,
            [
                "--combo", f"{image}|FIRST|top",
                "--combo", f"{image}|SECOND|right",
                "--layout", "left",
                "--rows", "1",
                "--cols", "2",
                "--page-w", "120",
                "--offset-y", "0",
                "--out", str(output),
            ],
        )
        self.assertEqual(result.exit_code, 0, result.output)
        stream = content_stream(output.read_bytes())
        rects = [
            tuple(float(part) for part in rect)
            for rect in re.findall(
                r"([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) re W n",
                stream,
            )
        ]
        self.assertEqual(len(rects), 2)
        places = {}
        for name in ("FIRST", "SECOND"):
            at = stream.index(f"({name})")
            text_y = float(re.findall(r"1 0 0 1 [\d.]+ ([\d.]+) cm", stream[:at])[-1])
            text_x = float(re.findall(r"1 0 0 1 ([\d.]+) [\d.]+ cm", stream[:at])[-1])
            picture = min(
                rects,
                key=lambda rect: abs((rect[0] + rect[2] / 2) - text_x),
            )
            places[name] = (text_x, text_y, picture)
        self.assertGreater(places["FIRST"][2][1], places["FIRST"][1])
        self.assertLess(places["SECOND"][0], places["SECOND"][2][0])
        cell = self.directory / "cell-top.pdf"
        cell_result = CliRunner().invoke(
            main,
            [
                "--layout", "left",
                "--cell", f"1,1,@{image}|FIRST|top",
                "--rows", "1",
                "--cols", "1",
                "--offset-y", "0",
                "--out", str(cell),
            ],
        )
        self.assertEqual(cell_result.exit_code, 0, cell_result.output)
        cell_stream = content_stream(cell.read_bytes())
        at = cell_stream.index("(FIRST)")
        text_y = float(re.findall(r"1 0 0 1 [\d.]+ ([\d.]+) cm", cell_stream[:at])[-1])
        picture_y = float(re.search(
            r"[\d.]+ ([\d.]+) [\d.]+ [\d.]+ re W n",
            cell_stream,
        ).group(1))
        self.assertGreater(picture_y, text_y)
        coloured = self.directory / "coloured.pdf"
        colour_result = CliRunner().invoke(
            main,
            [
                "--combo", f"{image}|FIRST,green",
                "--text", "SECOND",
                "--color", "red",
                "--rows", "1",
                "--cols", "2",
                "--page-w", "120",
                "--offset-y", "0",
                "--out", str(coloured),
            ],
        )
        self.assertEqual(colour_result.exit_code, 0, colour_result.output)
        coloured_stream = content_stream(coloured.read_bytes())
        first_at = coloured_stream.index("(FIRST)")
        second_at = coloured_stream.index("(SECOND)")
        self.assertIn("0.000 0.550 0.220 rg", coloured_stream[:first_at])
        self.assertIn("0.820 0.080 0.100 rg", coloured_stream[first_at:second_at])

    def test_combo_cell_keeps_hebrew_and_color(self) -> None:
        image = self.write_svg()
        pdf = render_pdf(
            SheetSpec(
                rows=1,
                columns=1,
                rotate=True,
                cells=(
                    CellOverride(
                        1,
                        1,
                        ComboSticker(image, "מסור", (0.12, 0.28, 0.72)),
                    ),
                ),
            )
        )
        stream = content_stream(pdf)
        self.assertIn(b"/F2", pdf)
        self.assertIn("0.120 0.280 0.720 rg", stream)
        self.assertIn("0 1 -1 0", stream)

    def test_click_combo_and_cell(self) -> None:
        image = self.write_svg()
        output = self.directory / "combo.pdf"
        result = CliRunner().invoke(
            main,
            [
                "--combo", str(image), "MASTER\nSAW",
                "--combo", str(image), "SLAVE\nVAC",
                "--color", "green",
                "--color", "red",
                "--layout", "top",
                "--cell", f"1,2,@{image}|מסור,blue",
                "--rows", "1",
                "--cols", "2",
                "--page-w", "120",
                "--offset-y", "0",
                "--out", str(output),
            ],
        )
        self.assertEqual(result.exit_code, 0, result.output)
        pdf = output.read_bytes()
        stream = content_stream(pdf)
        self.assertIn("(MASTER)", stream)
        self.assertIn("0.000 0.550 0.220 rg", stream)
        self.assertIn(b"/F2", pdf)
        self.assertIn("0.120 0.280 0.720 rg", stream)

    def test_click_end_logo_pairs_with_each_combo(self) -> None:
        image = self.write_svg()
        end = self.write_svg("end.svg")
        output = self.directory / "flank.pdf"
        result = CliRunner().invoke(
            main,
            [
                "--combo", f"{image}|MASTER|{end}",
                "--cell", f"1,2,@{image}|SAW|{end}",
                "--rows", "1",
                "--cols", "2",
                "--page-w", "120",
                "--offset-y", "0",
                "--out", str(output),
            ],
        )
        self.assertEqual(result.exit_code, 0, result.output)
        stream = content_stream(output.read_bytes())
        self.assertEqual(stream.count(" re W n"), 4)
        self.assertIn("(MASTER)", stream)
        self.assertIn("(SAW)", stream)

    def test_manual_lists_every_switch(self) -> None:
        root = Path(__file__).parents[2]
        readme = (root / "README.md").read_text()
        page = man_page(readme)
        self.assertEqual((root / "man" / "make-labels.1").read_text(), page)
        self.assertEqual((root / "labels" / "make-labels.1").read_text(), page)
        self.assertIn(".TH MAKE-LABELS", page)
        self.assertIn(".SH SWITCHES", page)
        self.assertIn(".SH EXAMPLES", page)
        self.assertIn(r"make\-labels \-\-page\-w 210", page)
        self.assertNotIn("examples/", page)
        self.assertNotIn("shields.io", page)
        self.assertNotIn("preview/", page)
        self.assertIn("labels/preview/combo.pdf.png", readme)
        self.assertIn(".SH QUICK START", page)
        for pdf in (root / "examples").glob("*.pdf"):
            self.assertIn(f"examples/{pdf.name}", readme)
        for param in main.params:
            for opt in param.opts:
                self.assertIn(opt, readme)
                self.assertIn(r"\fB" + opt.replace("-", r"\-") + r"\fR", page)

    def test_completion_offers_switches_layouts_and_colours(self) -> None:
        for shell in ("zsh", "bash", "fish"):
            with self.subTest(shell=shell):
                result = CliRunner().invoke(main, ["--completion", shell])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertIn("_MAKE_LABELS_COMPLETE", result.output)
                self.assertIn("make-labels", result.output)
        layout = CliRunner().invoke(
            main,
            [],
            prog_name="make-labels",
            env={
                "_MAKE_LABELS_COMPLETE": "zsh_complete",
                "COMP_WORDS": "make-labels --lay",
                "COMP_CWORD": "1",
            },
        )
        self.assertEqual(layout.exit_code, 0, layout.output)
        self.assertIn("--layout", layout.output)
        choice = CliRunner().invoke(
            main,
            [],
            prog_name="make-labels",
            env={
                "_MAKE_LABELS_COMPLETE": "zsh_complete",
                "COMP_WORDS": "make-labels --layout r",
                "COMP_CWORD": "2",
            },
        )
        self.assertEqual(choice.exit_code, 0, choice.output)
        self.assertIn("right", choice.output)
        colour = CliRunner().invoke(
            main,
            [],
            prog_name="make-labels",
            env={
                "_MAKE_LABELS_COMPLETE": "zsh_complete",
                "COMP_WORDS": "make-labels --color g",
                "COMP_CWORD": "2",
            },
        )
        self.assertEqual(colour.exit_code, 0, colour.output)
        self.assertIn("green", colour.output)
        self.assertIn("grey", colour.output)

    def test_man_prints_the_page_when_stdout_is_not_a_terminal(self) -> None:
        result = CliRunner().invoke(main, ["--man"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(result.output.startswith(".TH MAKE-LABELS"))
        self.assertIn(".SH SWITCHES", result.output)


if __name__ == "__main__":
    unittest.main()
