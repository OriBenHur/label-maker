from __future__ import annotations

import re
import struct
import zlib

from .model import LabelError, RGB
from .svg_draw import Resources

MM = 72 / 25.4
HEBREW_RE = re.compile(r"[\u0590-\u05FF]")
TTF_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
LEADING = 1.15

W_BOLD = {
    "A": 722, "B": 722, "C": 722, "D": 722, "E": 667, "F": 611, "G": 778,
    "H": 722, "I": 278, "J": 556, "K": 722, "L": 611, "M": 833, "N": 722,
    "O": 778, "P": 667, "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722,
    "V": 667, "W": 944, "X": 667, "Y": 667, "Z": 611,
    "a": 556, "b": 611, "c": 556, "d": 611, "e": 556, "f": 333, "g": 611,
    "h": 611, "i": 278, "j": 278, "k": 556, "l": 278, "m": 889, "n": 611,
    "o": 611, "p": 611, "q": 611, "r": 389, "s": 556, "t": 333, "u": 611,
    "v": 556, "w": 778, "x": 667, "y": 556, "z": 500,
    "0": 556, "1": 556, "2": 556, "3": 556, "4": 556, "5": 556, "6": 556,
    "7": 556, "8": 556, "9": 556, " ": 278, "/": 278, "-": 333, ".": 278,
    "+": 584, "_": 556, ":": 333, "&": 722, "#": 556, "*": 389,
}


class Ttf:
    def __init__(self, path: str):
        with open(path, "rb") as file:
            self.data = file.read()
        self.tabs = self._tables()
        self.upem = self._u16("head", 18)
        hhea = self.tabs["hhea"][0]
        self.ascent = self._i16_at(hhea + 4)
        self.descent = self._i16_at(hhea + 6)
        self.n_hmtx = self._u16_at(hhea + 34)
        head = self.tabs["head"][0]
        self.bbox = tuple(self._i16_at(head + 36 + 2 * i) for i in range(4))
        self.n_glyphs = self._u16("maxp", 4)
        self.cmap = self._cmap()
        self.adv = self._hmtx()

    def _u16_at(self, offset: int) -> int:
        return struct.unpack_from(">H", self.data, offset)[0]

    def _i16_at(self, offset: int) -> int:
        return struct.unpack_from(">h", self.data, offset)[0]

    def _u32_at(self, offset: int) -> int:
        return struct.unpack_from(">I", self.data, offset)[0]

    def _u16(self, tag: str, relative: int) -> int:
        return self._u16_at(self.tabs[tag][0] + relative)

    def _tables(self) -> dict[str, tuple[int, int]]:
        count = self._u16_at(4)
        tables = {}
        for index in range(count):
            tag = self.data[12 + 16 * index:16 + 16 * index].decode("ascii")
            tables[tag] = (
                self._u32_at(20 + 16 * index),
                self._u32_at(24 + 16 * index),
            )
        return tables

    def _cmap(self) -> dict[int, int]:
        offset = self.tabs["cmap"][0]
        count = self._u16_at(offset + 2)
        record = None
        for index in range(count):
            platform = self._u16_at(offset + 4 + 8 * index)
            encoding = self._u16_at(offset + 6 + 8 * index)
            cmap_offset = self._u32_at(offset + 8 + 8 * index)
            fmt = self._u16_at(offset + cmap_offset)
            if fmt == 4 and (platform, encoding) in ((3, 1), (0, 3), (0, 4)):
                record = offset + cmap_offset
                if platform == 3:
                    break
        if record is None:
            raise LabelError("the Hebrew font has no supported character map")
        segments = self._u16_at(record + 6) // 2
        end = record + 14
        start = end + 2 * segments + 2
        delta = start + 2 * segments
        range_offset = delta + 2 * segments
        mapping = {}
        for segment in range(segments):
            first = self._u16_at(start + 2 * segment)
            last = self._u16_at(end + 2 * segment)
            shift = self._i16_at(delta + 2 * segment)
            relative = self._u16_at(range_offset + 2 * segment)
            for codepoint in range(first, last + 1):
                if relative == 0:
                    glyph = (codepoint + shift) & 0xFFFF
                else:
                    glyph = self._u16_at(
                        range_offset + 2 * segment + relative + 2 * (codepoint - first)
                    )
                    if glyph:
                        glyph = (glyph + shift) & 0xFFFF
                if glyph:
                    mapping[codepoint] = glyph
        return mapping

    def _hmtx(self) -> list[int]:
        offset = self.tabs["hmtx"][0]
        advances = [self._u16_at(offset + 4 * index) for index in range(self.n_hmtx)]
        advances.extend([advances[-1]] * (self.n_glyphs - self.n_hmtx))
        return advances

    def _glyph_bbox(self, glyph: int) -> tuple[int, int, int, int] | None:
        if not hasattr(self, "_loca"):
            fmt = self._i16_at(self.tabs["head"][0] + 50)
            offset = self.tabs["loca"][0]
            if fmt == 0:
                self._loca = [
                    self._u16_at(offset + 2 * index) * 2
                    for index in range(self.n_glyphs + 1)
                ]
            else:
                self._loca = [
                    self._u32_at(offset + 4 * index)
                    for index in range(self.n_glyphs + 1)
                ]
        if glyph + 1 >= len(self._loca) or self._loca[glyph] == self._loca[glyph + 1]:
            return None
        offset = self.tabs["glyf"][0] + self._loca[glyph]
        return tuple(self._i16_at(offset + 2 + 2 * index) for index in range(4))

    def ink_bbox(self, text: str) -> tuple[int, int, int, int]:
        pen = 0
        xs: list[int] = []
        ys: list[int] = []
        for glyph in self.gids(text):
            bbox = self._glyph_bbox(glyph)
            if bbox:
                xs += [pen + bbox[0], pen + bbox[2]]
                ys += [bbox[1], bbox[3]]
            pen += self.adv[glyph]
        if not xs:
            return 0, 0, pen, 0
        return min(xs), min(ys), max(xs), max(ys)

    def hebrew_height(self) -> int:
        if not hasattr(self, "_hebrew_height"):
            bbox = self._glyph_bbox(self.gids("ה")[0])
            self._hebrew_height = bbox[3] if bbox else int(self.upem * 0.52)
        return self._hebrew_height

    def gids(self, text: str) -> list[int]:
        glyphs = []
        for char in visual(text):
            glyph = self.cmap.get(ord(char), 0)
            if glyph == 0 and char != " ":
                raise LabelError(f"font missing {char!r} U+{ord(char):04X}")
            glyphs.append(glyph)
        return glyphs

    def width_1000(self, text: str) -> float:
        return sum(self.adv[glyph] for glyph in self.gids(text)) * 1000 / self.upem

    def pdf_objects(self, start: int) -> list[bytes]:
        scale = 1000 / self.upem
        bbox = " ".join(str(round(value * scale)) for value in self.bbox)
        used = sorted({glyph for glyph in self.cmap.values() if glyph})
        widths = [f"{glyph} [{round(self.adv[glyph] * scale)}]" for glyph in used]
        compressed = zlib.compress(self.data, 9)
        font_file = start + 3
        descriptor = start + 2
        cid = start + 1
        return [
            (
                f"<< /Type /Font /Subtype /Type0 /BaseFont /Arial-BoldMT "
                f"/Encoding /Identity-H /DescendantFonts [{cid} 0 R] >>"
            ).encode(),
            (
                f"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /Arial-BoldMT "
                f"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) "
                f"/Supplement 0 >> /FontDescriptor {descriptor} 0 R "
                f'/DW 500 /W [{" ".join(widths)}] /CIDToGIDMap /Identity >>'
            ).encode(),
            (
                f"<< /Type /FontDescriptor /FontName /Arial-BoldMT /Flags 4 "
                f"/FontBBox [{bbox}] /ItalicAngle 0 "
                f"/Ascent {round(self.ascent * scale)} "
                f"/Descent {round(self.descent * scale)} "
                f"/CapHeight {round(self.ascent * scale * 0.7)} /StemV 80 "
                f"/FontFile2 {font_file} 0 R >>"
            ).encode(),
            b"<< /Length %d /Length1 %d /Filter /FlateDecode >>\nstream\n"
            % (len(compressed), len(self.data))
            + compressed
            + b"\nendstream",
        ]


def visual(text: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(text):
        if HEBREW_RE.match(text[index]):
            end = index
            while end < len(text) and (
                HEBREW_RE.match(text[end]) or text[end] in " \u05be"
            ):
                end += 1
            output.append(text[index:end][::-1])
            index = end
        else:
            end = index
            while end < len(text) and not HEBREW_RE.match(text[end]):
                end += 1
            output.append(text[index:end])
            index = end
    return "".join(output)


class PdfBuilder:
    def __init__(self, page_width: float, page_height: float, resources: Resources | None = None):
        self.page_width = page_width
        self.page_height = page_height
        self.resources = resources or Resources()
        self._ttf: Ttf | None = None

    def font_size(
        self,
        label_width: float,
        label_height: float,
        rotate: bool,
        texts: list[str],
        override_mm: float | None,
    ) -> float:
        if override_mm:
            return override_mm * MM
        if rotate:
            label_width, label_height = label_height, label_width
        best = None
        for text in texts:
            lines = self.split_lines(text)
            widest = max((self.text_width(line, 1) for line in lines if line), default=1)
            count = len(lines)
            by_width = label_width * 0.82 / widest
            by_height = (
                label_height * 0.52
                if count <= 1
                else label_height * 0.82 / ((count - 1) * LEADING + 1)
            )
            size = min(by_width, by_height)
            best = size if best is None else min(best, size)
        return 12 if best is None else best

    def text_label(
        self,
        center_x: float,
        center_y: float,
        text: str,
        color: RGB,
        rotate: bool,
        size: float,
        align: str = "center",
        box_width: float | None = None,
    ) -> str:
        lines = self.split_lines(text)
        pitch = size * LEADING
        x_shift = 0.0
        if align == "left":
            x_shift = -((box_width or 0) / 2) + size * 0.15
        shows = [
            self._line(
                line,
                size,
                ((len(lines) - 1) / 2 - index) * pitch,
                align,
                x_shift,
            )
            for index, line in enumerate(lines)
            if line
        ]
        if not shows:
            return ""
        red, green, blue = color
        body = (
            f"{red:.3f} {green:.3f} {blue:.3f} rg\nBT "
            + " ".join(shows)
            + " ET\n"
        )
        matrix = (
            f"0 1 -1 0 {center_x:.2f} {center_y:.2f} cm"
            if rotate
            else f"1 0 0 1 {center_x:.2f} {center_y:.2f} cm"
        )
        return f"q {matrix}\n{body}Q\n"

    def build(self, content: str) -> bytes:
        fonts = " /F1 5 0 R"
        extra: list[bytes] = []
        if "/F2 " in content:
            extra = self.ttf.pdf_objects(6)
            fonts += " /F2 6 0 R"
        font = (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
            b"/Encoding /WinAnsiEncoding >>"
        )
        stream = content.encode("latin-1")
        contents = (
            b"<< /Length %d >>\nstream\n" % len(stream)
            + stream
            + b"\nendstream"
        )
        if not self.resources.images and not self.resources.states:
            page = (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
                f"{self.page_width:.2f} {self.page_height:.2f}] "
                f"/Resources << /Font <<{fonts} >> >> /Contents 4 0 R >>"
            ).encode()
            return self._pdf(
                [
                    b"<< /Type /Catalog /Pages 2 0 R >>",
                    b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                    page,
                    contents,
                    font,
                    *extra,
                ]
            )

        number = 6 + len(extra)
        state_references = []
        state_objects = []
        for name, fill_alpha, stroke_alpha in self.resources.states:
            state_references.append(f"/{name} {number} 0 R")
            state_objects.append(
                f"<< /Type /ExtGState /ca {fill_alpha:.3f} "
                f"/CA {stroke_alpha:.3f} >>".encode()
            )
            number += 1
        image_references = []
        image_objects = []
        for image in self.resources.images:
            soft_mask = None
            if image.alpha is not None:
                soft_mask = number
                number += 1
                image_objects.append(
                    self._flate(
                        f"/Type /XObject /Subtype /Image /Width {image.w} "
                        f"/Height {image.h} /ColorSpace /DeviceGray "
                        f"/BitsPerComponent 8",
                        image.alpha,
                    )
                )
            image_references.append(f"/{image.name} {number} 0 R")
            number += 1
            body = (
                f"/Type /XObject /Subtype /Image /Width {image.w} "
                f"/Height {image.h} /ColorSpace /DeviceRGB "
                f"/BitsPerComponent 8 /Interpolate false"
            )
            if soft_mask:
                body += f" /SMask {soft_mask} 0 R"
            image_objects.append(self._flate(body, image.rgb))
        resources = f"/Font <<{fonts} >>"
        if state_references:
            resources += " /ExtGState << " + " ".join(state_references) + " >>"
        if image_references:
            resources += " /XObject << " + " ".join(image_references) + " >>"
        group = ""
        if state_references or any(image.alpha is not None for image in self.resources.images):
            group = " /Group << /Type /Group /S /Transparency /CS /DeviceRGB >>"
        page = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
            f"{self.page_width:.2f} {self.page_height:.2f}] "
            f"/Resources << {resources} >>{group} /Contents 4 0 R >>"
        ).encode()
        return self._pdf(
            [
                b"<< /Type /Catalog /Pages 2 0 R >>",
                b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                page,
                contents,
                font,
                *extra,
                *state_objects,
                *image_objects,
            ]
        )

    @property
    def ttf(self) -> Ttf:
        if self._ttf is None:
            self._ttf = Ttf(TTF_PATH)
        return self._ttf

    @staticmethod
    def split_lines(text: str) -> list[str]:
        return text.replace("\\n", "\n").split("\n")

    def text_width(self, text: str, size: float) -> float:
        if HEBREW_RE.search(text):
            return self.ttf.width_1000(text) / 1000 * size
        return sum(W_BOLD.get(char, 600) for char in text) / 1000 * size

    def _line(
        self,
        text: str,
        size: float,
        y_shift: float,
        align: str = "center",
        x_shift: float = 0,
    ) -> str:
        if HEBREW_RE.search(text):
            x0, _, x1, _ = self.ttf.ink_bbox(text)
            scale = size / self.ttf.upem
            x = (
                x_shift - x0 * scale
                if align == "left"
                else -(x0 + x1) / 2 * scale
            )
            y = y_shift - self.ttf.hebrew_height() / 2 * scale
            glyphs = "".join(f"{glyph:04X}" for glyph in self.ttf.gids(text))
            return (
                f"/F2 {size:.2f} Tf 1 0 0 1 {x:.2f} {y:.2f} "
                f"Tm <{glyphs}> Tj"
            )
        x = x_shift if align == "left" else -self.text_width(text, size) / 2
        y = y_shift - size * 0.36
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        return (
            f"/F1 {size:.2f} Tf 1 0 0 1 {x:.2f} {y:.2f} "
            f"Tm ({escaped}) Tj"
        )

    @staticmethod
    def _pdf(objects: list[bytes]) -> bytes:
        output = bytearray(b"%PDF-1.4\n")
        offsets = []
        for number, body in enumerate(objects, start=1):
            offsets.append(len(output))
            output += b"%d 0 obj\n" % number + body + b"\nendobj\n"
        xref = len(output)
        output += b"xref\n0 %d\n" % (len(objects) + 1)
        output += b"0000000000 65535 f \n"
        for offset in offsets:
            output += b"%010d 00000 n \n" % offset
        output += (
            b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objects) + 1, xref)
        )
        return bytes(output)

    @staticmethod
    def _flate(dictionary: str, data: bytes) -> bytes:
        compressed = zlib.compress(data)
        header = (
            f"<< {dictionary} /Length {len(compressed)} "
            f"/Filter /FlateDecode >>\nstream\n"
        ).encode("ascii")
        return header + compressed + b"\nendstream"
