from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .model import (
    DEFAULT_COLORS,
    CellOverride,
    ComboSticker,
    ImageSticker,
    LayoutError,
    SheetSpec,
    Sticker,
    TextSticker,
)
from .pdf import LEADING, MM, PdfBuilder
from .svg_draw import INSET, Resources, paint_svg, parse_svg, view_box
from .to_svg import focus_artwork, sticker_px, to_svg


@dataclass(frozen=True, slots=True)
class Layout:
    page_width: float
    page_height: float
    label_width: float
    label_height: float
    margin_x: float
    margin_y: float
    gap_x: float
    gap_y: float


class LabelSheet:
    def __init__(self, spec: SheetSpec):
        self.spec = spec
        self.layout = self._layout()
        self.resources = Resources()
        self.pdf = PdfBuilder(
            self.layout.page_width,
            self.layout.page_height,
            self.resources,
        )
        self._artwork_cache: dict[tuple, tuple[str, str]] = {}

    def render(self) -> bytes:
        return self.pdf.build(self.content_stream())

    def summary(self) -> str:
        layout = self.layout
        return (
            f"  page {self.spec.page_width_mm:g}x{self.spec.page_height_mm:g} mm, "
            f"label {self.spec.label_width_mm:g}x{self.spec.label_height_mm:g}, "
            f"margins {layout.margin_x / MM:.1f} x {layout.margin_y / MM:.1f}, "
            f"gaps {layout.gap_x / MM:.1f} x {layout.gap_y / MM:.1f}"
        )

    def content_stream(self) -> str:
        spec = self.spec
        layout = self.layout
        stickers = self._stickers()
        overrides = {(cell.row, cell.column): cell for cell in spec.cells}
        texts = [
            sticker.text for sticker in stickers if isinstance(sticker, TextSticker)
        ]
        texts += [
            cell.sticker.text
            for cell in spec.cells
            if isinstance(cell.sticker, TextSticker)
        ]
        font_size = self.pdf.font_size(
            layout.label_width,
            layout.label_height,
            spec.rotate,
            texts,
            spec.font_size_mm,
        )
        grid = spec.outline or spec.proof
        draw_stickers = not spec.outline or spec.proof
        content = self._ruler() if grid else ""
        scales = self._scale_cells() if grid else ()
        index = 0
        for row in range(spec.rows):
            for column in range(spec.columns):
                x = (
                    layout.margin_x
                    + column * (layout.label_width + layout.gap_x)
                    + spec.offset_x_mm * MM
                )
                y = (
                    layout.page_height
                    - layout.margin_y
                    - row * (layout.label_height + layout.gap_y)
                    - layout.label_height
                    - spec.offset_y_mm * MM
                )
                if grid:
                    content += self._grid_cell(x, y)
                    if (row, column) in scales:
                        content += self._sticker_scale(row, column, x, y)
                selected_row = spec.row is None or row + 1 == spec.row
                skipped = (
                    row + 1 in spec.skip_rows
                    or column + 1 in spec.skip_columns
                )
                within_limit = spec.limit is None or index < spec.limit
                if draw_stickers and selected_row and not skipped and within_limit:
                    key = (row + 1, column + 1)
                    if key in overrides:
                        sticker = self._override(overrides[key], stickers[index % len(stickers)])
                    elif spec.cells and not spec.stickers:
                        index += 1
                        continue
                    else:
                        sticker = stickers[index % len(stickers)]
                    content += self._place(sticker, x, y, font_size)
                index += 1
        return content

    def _layout(self) -> Layout:
        spec = self.spec
        page_width = spec.page_width_mm * MM
        page_height = spec.page_height_mm * MM
        label_width = spec.label_width_mm * MM
        label_height = spec.label_height_mm * MM
        margin_x, gap_x = self._spacing(
            page_width,
            spec.columns,
            label_width,
            None if spec.gap_x_mm is None else spec.gap_x_mm * MM,
            None if spec.margin_x_mm is None else spec.margin_x_mm * MM,
        )
        margin_y, gap_y = self._spacing(
            page_height,
            spec.rows,
            label_height,
            None if spec.gap_y_mm is None else spec.gap_y_mm * MM,
            None if spec.margin_y_mm is None else spec.margin_y_mm * MM,
        )
        layout = Layout(
            page_width,
            page_height,
            label_width,
            label_height,
            margin_x,
            margin_y,
            gap_x,
            gap_y,
        )
        self._check_fit(layout)
        return layout

    @staticmethod
    def _spacing(
        page: float,
        count: int,
        size: float,
        gap: float | None,
        margin: float | None,
    ) -> tuple[float, float]:
        if gap is None and margin is None:
            spacing = (page - count * size) / (count + 1)
            return spacing, spacing
        if gap is None:
            gap = (page - 2 * margin - count * size) / max(count - 1, 1)
        elif margin is None:
            margin = (page - count * size - (count - 1) * gap) / 2
        return margin, gap

    def _check_fit(self, layout: Layout) -> None:
        spec = self.spec
        axes = (
            (
                "width",
                layout.margin_x,
                spec.columns * layout.label_width
                + (spec.columns - 1) * layout.gap_x,
                layout.page_width,
            ),
            (
                "height",
                layout.margin_y,
                spec.rows * layout.label_height
                + (spec.rows - 1) * layout.gap_y,
                layout.page_height,
            ),
        )
        errors = []
        for name, start, span, page in axes:
            overflow = max(-start, start + span - page)
            if overflow > 0.01 * MM:
                errors.append(
                    f"the grid overflows the sheet {name} by {overflow / MM:.1f} mm: "
                    f"{start / MM:.1f} to {(start + span) / MM:.1f} mm "
                    f"on a {page / MM:.1f} mm sheet"
                )
        if errors and not spec.force:
            errors.append(
                "nothing written. shrink the labels, drop a row or column, "
                "or pass --force"
            )
            raise LayoutError("\n".join(errors))

    def _stickers(self) -> tuple[Sticker, ...]:
        source = self.spec.stickers or (
            TextSticker("MASTER"),
            TextSticker("SLAVE"),
        )
        output: list[Sticker] = []
        text_index = 0
        for sticker in source:
            if isinstance(sticker, TextSticker):
                color = sticker.color or DEFAULT_COLORS[text_index % len(DEFAULT_COLORS)]
                output.append(TextSticker(sticker.text, color))
                text_index += 1
            elif isinstance(sticker, ComboSticker):
                color = sticker.color or DEFAULT_COLORS[text_index % len(DEFAULT_COLORS)]
                output.append(ComboSticker(
                    sticker.path,
                    sticker.text,
                    color,
                    sticker.layout,
                    sticker.end,
                    sticker.layout_set,
                ))
                text_index += 1
            else:
                output.append(sticker)
        return tuple(output)

    @staticmethod
    def _override(cell: CellOverride, fallback: Sticker) -> Sticker:
        sticker = cell.sticker
        if isinstance(sticker, ImageSticker) or sticker.color is not None:
            return sticker
        color = fallback.color if isinstance(fallback, (TextSticker, ComboSticker)) else DEFAULT_COLORS[0]
        if isinstance(sticker, ComboSticker):
            return ComboSticker(
                sticker.path,
                sticker.text,
                color,
                sticker.layout,
                sticker.end,
                sticker.layout_set,
            )
        return TextSticker(sticker.text, color)

    def _place(
        self,
        sticker: Sticker,
        x: float,
        y: float,
        font_size: float,
    ) -> str:
        layout = self.layout
        if isinstance(sticker, ComboSticker):
            return self._combo(sticker, x, y)
        if isinstance(sticker, ImageSticker):
            svg, base_directory = self._artwork(sticker.path)
            return paint_svg(
                svg,
                x,
                y,
                layout.label_width,
                layout.label_height,
                self.resources,
                self.spec.rotate,
                base_directory,
            )
        return self.pdf.text_label(
            x + layout.label_width / 2,
            y + layout.label_height / 2,
            sticker.text,
            sticker.color or DEFAULT_COLORS[0],
            self.spec.rotate,
            font_size,
        )

    def _combo(self, sticker: ComboSticker, x: float, y: float) -> str:
        width = self.layout.label_width
        height = self.layout.label_height
        lines = [line for line in self.pdf.split_lines(sticker.text) if line]
        if not lines:
            return ""
        start_path, end_path = self._logo_paths(sticker)
        logos = []
        for path in (start_path, end_path):
            if path is None:
                logos.append(None)
                continue
            svg, base_directory = self._artwork(path)
            svg = focus_artwork(svg)
            _, _, art_w, art_h = view_box(parse_svg(svg))
            logos.append((svg, base_directory, art_w / art_h))
        start, end = logos
        count = len(lines)
        denom = (count - 1) * LEADING + 1
        widest = max(self.pdf.text_width(line, 1) for line in lines) or 1
        gap = 1.5 * MM
        visible = 1 - 2 * INSET
        aspects = [logo[2] for logo in (start, end) if logo is not None]
        gaps = len(aspects)
        if self.spec.font_size_mm:
            size = self.spec.font_size_mm * MM
        else:
            height_cap = height * 0.52 if count == 1 else height * 0.82 / denom
            width_fit = (width - gap * gaps) * 0.82 / (
                widest + sum(aspects) * denom * 0.82 / visible
            )
            size = min(height_cap, width_fit)
        block = size * denom
        picture_h = min(height, block / visible)

        def fitted(logo):
            if logo is None:
                return None
            picture_w = min(width - gap, picture_h * logo[2])
            return picture_w, picture_w / logo[2]

        start_box = fitted(start)
        end_box = fitted(end)
        if sticker.layout == "top" and end is None and start is not None and start_box is not None:
            picture_w, top_h = start_box
            stack = top_h + gap + block
            bottom = y + (height - stack) / 2
            if picture_w <= 1 or top_h <= 1:
                raise LayoutError("the sticker is too small for a picture and text")
            image = self._paint(start, x + (width - picture_w) / 2, bottom + block + gap, picture_w, top_h)
            text = self._combo_text(
                sticker, x + width / 2, bottom + block / 2, width, size, "center"
            )
            return image + text
        text_span = max(self.pdf.text_width(line, size) for line in lines)
        pad = size * 0.15
        text_w = pad + text_span
        pieces = []
        if start_box:
            pieces.append(start_box[0])
        pieces.append(text_w)
        if end_box:
            pieces.append(end_box[0])
        group = sum(pieces) + gap * (len(pieces) - 1)
        if group > width and (start_box or end_box):
            extra = group - width
            logo_w = (start_box[0] if start_box else 0) + (end_box[0] if end_box else 0)
            if logo_w > extra:
                scale = (logo_w - extra) / logo_w
                if start_box:
                    start_box = (start_box[0] * scale, start_box[1] * scale)
                if end_box:
                    end_box = (end_box[0] * scale, end_box[1] * scale)
                pieces = []
                if start_box:
                    pieces.append(start_box[0])
                pieces.append(text_w)
                if end_box:
                    pieces.append(end_box[0])
                group = sum(pieces) + gap * (len(pieces) - 1)
        boxes = [box for box in (start_box, end_box) if box is not None]
        if boxes and any(box[0] <= 1 or box[1] <= 1 for box in boxes):
            raise LayoutError("the sticker is too small for a picture and text")
        group = min(group, width)
        left = x + max(0, (width - group) / 2)
        center_y = y + height / 2
        cursor = left
        drawn = ""
        if start is not None and start_box is not None:
            drawn += self._paint(
                start, cursor, center_y - start_box[1] / 2, start_box[0], start_box[1]
            )
            cursor += start_box[0] + gap
        drawn += self._combo_text(sticker, cursor + text_w / 2, center_y, text_w, size, "left")
        if end is not None and end_box is not None:
            cursor += text_w + gap
            drawn += self._paint(
                end, cursor, center_y - end_box[1] / 2, end_box[0], end_box[1]
            )
        return drawn

    def _logo_paths(self, sticker: ComboSticker) -> tuple[Path | None, Path | None]:
        if sticker.layout == "right" and sticker.end is None:
            return None, sticker.path
        if sticker.layout == "top" and sticker.end is None:
            return sticker.path, None
        return sticker.path, sticker.end

    def _paint(self, logo, x: float, y: float, width: float, height: float) -> str:
        svg, base_directory, _aspect = logo
        return paint_svg(
            svg,
            x,
            y,
            width,
            height,
            self.resources,
            self.spec.rotate,
            base_directory,
        )

    def _combo_text(
        self,
        sticker: ComboSticker,
        center_x: float,
        center_y: float,
        box_width: float,
        size: float,
        align: str,
    ) -> str:
        return self.pdf.text_label(
            center_x,
            center_y,
            sticker.text,
            sticker.color or DEFAULT_COLORS[0],
            self.spec.rotate,
            size,
            align,
            box_width,
        )

    def _pixel_box(self) -> tuple[int, int]:
        return sticker_px(
            self.spec.label_width_mm,
            self.spec.label_height_mm,
            INSET,
        )

    def _artwork(self, source: Path) -> tuple[str, str]:
        path = os.path.abspath(source)
        try:
            modified = os.stat(path).st_mtime_ns
        except FileNotFoundError as error:
            raise FileNotFoundError(f"no such image {source}") from error
        box = self._pixel_box()
        key = (path, modified, self.spec.trace, box)
        if key not in self._artwork_cache:
            self._artwork_cache[key] = (
                to_svg(path, trace=self.spec.trace, box=box),
                os.path.dirname(path),
            )
        return self._artwork_cache[key]

    def _scale_cells(self) -> tuple[tuple[int, int], ...]:
        rows = self.spec.rows
        cols = self.spec.columns
        if rows >= 4:
            return ((1, 0), (rows - 2, cols - 1))
        if rows == 3:
            cells = [(1, 0)]
            if cols > 1:
                cells.append((1, cols - 1))
            return tuple(cells)
        if rows == 2:
            return ((0, 0), (1, cols - 1))
        if cols > 1:
            return ((0, 0), (0, cols - 1))
        return ((0, 0),)

    def _sticker_scale(self, row: int, column: int, x: float, y: float) -> str:
        # Printers leave the outer edge of the page blank, so the ticks
        # sit on a side that faces the middle of the sheet.
        width = self.layout.label_width
        height = self.layout.label_height
        rows = self.spec.rows
        cols = self.spec.columns
        content = "q 0 G 0.4 w\n"
        if rows == 1:
            content += self._ticks(x, y + height - 5 * MM, width, True, -1)
        elif row == 0:
            content += self._ticks(x, y, width, True, 1)
        else:
            content += self._ticks(x, y + height, width, True, -1)
        if cols == 1:
            content += self._ticks(x + 5 * MM, y, height, False, 1)
        elif column == 0:
            content += self._ticks(x + width, y, height, False, -1)
        else:
            content += self._ticks(x, y, height, False, 1)
        return content + "Q\n"

    def _ticks(
        self,
        x0: float,
        y0: float,
        length: float,
        horizontal: bool,
        sign: int,
    ) -> str:
        lines = []
        steps = int(length / MM)
        for half in range(1, steps * 2):
            if half % 10 == 0:
                tick = 2.5 * MM
            elif half % 2 == 0:
                tick = 1.2 * MM
            else:
                tick = 0.6 * MM
            millimetres = half / 2
            if horizontal:
                x = x0 + millimetres * MM
                tip = y0 + sign * tick
                lines.append(f"{x:.2f} {y0:.2f} m {x:.2f} {tip:.2f} l S\n")
                if half % 10 == 0 and millimetres <= steps - 6:
                    lines.append(self._scale_number(str(int(millimetres)), x, tip, 0, sign))
            else:
                y = y0 + millimetres * MM
                tip = x0 + sign * tick
                lines.append(f"{x0:.2f} {y:.2f} m {tip:.2f} {y:.2f} l S\n")
                if half % 10 == 0 and millimetres <= steps - 6:
                    lines.append(self._scale_number(str(int(millimetres)), tip, y, sign, 0))
        return "".join(lines)

    def _scale_number(self, label: str, x: float, y: float, dx: int, dy: int) -> str:
        size = 6
        width = self.pdf.text_width(label, size)
        gap = 0.8
        if dy:
            text_x = x - width / 2
            text_y = y + gap if dy > 0 else y - size
        else:
            text_x = x + gap if dx > 0 else x - width - gap
            text_y = y - size * 0.35
        return (
            f"0 g BT /F1 {size} Tf 1 0 0 1 {text_x:.2f} {text_y:.2f} "
            f"Tm ({label}) Tj ET\n"
        )

    def _grid_cell(self, x: float, y: float) -> str:
        width = self.layout.label_width
        height = self.layout.label_height
        return (
            f"q 0 G 1.2 w {x:.2f} {y:.2f} {width:.2f} {height:.2f} re S\n"
            f"{x + width / 2:.2f} {y:.2f} m "
            f"{x + width / 2:.2f} {y + height:.2f} l S\n"
            f"{x:.2f} {y + height / 2:.2f} m "
            f"{x + width:.2f} {y + height / 2:.2f} l S Q\n"
        )

    def _ruler(self) -> str:
        page_width = self.layout.page_width
        page_height = self.layout.page_height
        content = "q 0 G 0.8 w\n"
        x0, y0 = 5 * MM, page_height / 2
        content += f"{x0:.2f} {y0:.2f} m {x0 + 100 * MM:.2f} {y0:.2f} l S\n"
        for index in range(11):
            x = x0 + index * 10 * MM
            height = 4 * MM if index % 5 == 0 else 2 * MM
            content += f"{x:.2f} {y0:.2f} m {x:.2f} {y0 + height:.2f} l S\n"
        content += (
            f"0 0 0 rg BT /F1 7 Tf 1 0 0 1 "
            f"{x0 + 34 * MM:.2f} {y0 + 6 * MM:.2f} Tm (100 mm) Tj ET\n"
        )
        x1, y1 = page_width / 2, 25 * MM
        content += f"{x1:.2f} {y1:.2f} m {x1:.2f} {y1 + 100 * MM:.2f} l S\n"
        for index in range(11):
            y = y1 + index * 10 * MM
            width = 4 * MM if index % 5 == 0 else 2 * MM
            content += f"{x1:.2f} {y:.2f} m {x1 + width:.2f} {y:.2f} l S\n"
        content += (
            f"BT /F1 7 Tf 0 1 -1 0 {x1 - 2 * MM:.2f} "
            f"{y1 + 34 * MM:.2f} Tm (100 mm) Tj ET Q\n"
        )
        return content
