from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

RGB = tuple[float, float, float]

DEFAULT_COLORS: tuple[RGB, ...] = (
    (0.00, 0.55, 0.22),
    (0.82, 0.08, 0.10),
    (0.12, 0.28, 0.72),
    (0.45, 0.22, 0.70),
)

NAMED_COLORS: dict[str, RGB] = {
    "black": (0, 0, 0),
    "white": (1, 1, 1),
    "red": (0.82, 0.08, 0.10),
    "green": (0.00, 0.55, 0.22),
    "blue": (0.12, 0.28, 0.72),
    "yellow": (0.85, 0.70, 0.00),
    "orange": (0.90, 0.40, 0.00),
    "purple": (0.45, 0.22, 0.70),
    "grey": (0.40, 0.40, 0.40),
    "gray": (0.40, 0.40, 0.40),
    "brown": (0.45, 0.25, 0.10),
}


class LabelError(ValueError):
    pass


class LayoutError(LabelError):
    pass


def parse_color(value: str | Sequence[float] | RGB) -> RGB:
    if not isinstance(value, str):
        parts = tuple(float(component) for component in value)
        if len(parts) != 3:
            raise LabelError("a colour needs three components")
        if any(component > 1 for component in parts):
            parts = tuple(component / 255 for component in parts)
        if any(not math.isfinite(component) or component < 0 or component > 1 for component in parts):
            raise LabelError("colour components must be between 0 and 1, or 0 and 255")
        return parts

    text = value.strip()
    named = NAMED_COLORS.get(text.lower())
    if named is not None:
        return named
    if text.startswith("#"):
        digits = text[1:]
        if len(digits) == 3:
            digits = "".join(char * 2 for char in digits)
        if len(digits) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", digits):
            raise LabelError(f"invalid colour {value!r}")
        number = int(digits, 16)
        return (
            ((number >> 16) & 255) / 255,
            ((number >> 8) & 255) / 255,
            (number & 255) / 255,
        )

    try:
        parts = tuple(float(part) for part in re.split(r"[,\s]+", text) if part)
    except ValueError as error:
        raise LabelError(f"invalid colour {value!r}") from error
    return parse_color(parts)


@dataclass(frozen=True, slots=True)
class TextSticker:
    text: str
    color: RGB | None = None

    def __post_init__(self) -> None:
        if self.color is not None:
            object.__setattr__(self, "color", parse_color(self.color))


@dataclass(frozen=True, slots=True)
class ImageSticker:
    path: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path).expanduser())


@dataclass(frozen=True, slots=True)
class ComboSticker:
    path: Path
    text: str
    color: RGB | None = None
    layout: str = "left"
    end: Path | None = None
    layout_set: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path).expanduser())
        if self.end is not None:
            object.__setattr__(self, "end", Path(self.end).expanduser())
        if self.color is not None:
            object.__setattr__(self, "color", parse_color(self.color))
        if self.layout not in ("left", "right", "top"):
            raise LabelError("layout must be left, right, or top")
        if not str(self.text):
            raise LabelError("a combo needs text")


Sticker = TextSticker | ImageSticker | ComboSticker


@dataclass(frozen=True, slots=True)
class CellOverride:
    row: int
    column: int
    sticker: Sticker

    def __post_init__(self) -> None:
        if self.row < 1 or self.column < 1:
            raise LabelError("cell row and column are 1-based")


@dataclass(frozen=True, slots=True)
class SheetSpec:
    page_width_mm: float = 110
    page_height_mm: float = 152
    columns: int = 2
    rows: int = 4
    label_width_mm: float = 52
    label_height_mm: float = 34
    gap_x_mm: float | None = 2.7
    gap_y_mm: float | None = 4
    margin_x_mm: float | None = None
    margin_y_mm: float | None = None
    offset_x_mm: float = 0
    offset_y_mm: float = 0
    stickers: tuple[Sticker, ...] = ()
    cells: tuple[CellOverride, ...] = ()
    font_size_mm: float | None = None
    rotate: bool = False
    trace: bool = False
    limit: int | None = None
    row: int | None = None
    skip_rows: frozenset[int] = field(default_factory=frozenset)
    skip_columns: frozenset[int] = field(default_factory=frozenset)
    outline: bool = False
    proof: bool = False
    force: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "stickers", tuple(self.stickers))
        object.__setattr__(self, "cells", tuple(self.cells))
        object.__setattr__(self, "skip_rows", frozenset(self.skip_rows))
        object.__setattr__(self, "skip_columns", frozenset(self.skip_columns))
        positive = {
            "page width": self.page_width_mm,
            "page height": self.page_height_mm,
            "label width": self.label_width_mm,
            "label height": self.label_height_mm,
        }
        for name, value in positive.items():
            if not math.isfinite(value) or value <= 0:
                raise LabelError(f"{name} must be positive")
        if self.columns < 1 or self.rows < 1:
            raise LabelError("rows and columns must be positive")
        if self.font_size_mm is not None and self.font_size_mm <= 0:
            raise LabelError("font size must be positive")
        if self.limit is not None and self.limit < 0:
            raise LabelError("limit cannot be negative")
        if self.row is not None and self.row < 1:
            raise LabelError("row is 1-based")
        if any(value < 1 for value in self.skip_rows | self.skip_columns):
            raise LabelError("skipped rows and columns are 1-based")

    @classmethod
    def from_value(cls, value: SheetSpec | Mapping[str, Any] | object) -> SheetSpec:
        if isinstance(value, cls):
            return value
        source = dict(value) if isinstance(value, Mapping) else vars(value)
        aliases = {
            "page_w": "page_width_mm",
            "page_h": "page_height_mm",
            "cols": "columns",
            "lw": "label_width_mm",
            "lh": "label_height_mm",
            "gap_x": "gap_x_mm",
            "gap_y": "gap_y_mm",
            "margin_x": "margin_x_mm",
            "margin_y": "margin_y_mm",
            "offset_x": "offset_x_mm",
            "offset_y": "offset_y_mm",
            "font_mm": "font_size_mm",
            "skip_row": "skip_rows",
            "skip_col": "skip_columns",
        }
        data: dict[str, Any] = {}
        fields = cls.__dataclass_fields__
        for key, item in source.items():
            target = aliases.get(key, key)
            if target in fields:
                data[target] = item

        raw_stickers = source.get("stickers", ()) or ()
        if not raw_stickers and source.get("text"):
            raw_stickers = tuple(("text", text) for text in source["text"])
        colors = tuple(parse_color(color) for color in (source.get("color", ()) or ()))
        stickers: list[Sticker] = []
        text_index = 0
        for raw in raw_stickers:
            sticker = _coerce_sticker(raw)
            if isinstance(sticker, (TextSticker, ComboSticker)):
                color = sticker.color
                if color is None and text_index < len(colors):
                    color = colors[text_index]
                if isinstance(sticker, TextSticker):
                    sticker = TextSticker(sticker.text, color)
                else:
                    sticker = ComboSticker(
                        sticker.path,
                        sticker.text,
                        color,
                        sticker.layout,
                        sticker.end,
                        sticker.layout_set,
                    )
                text_index += 1
            stickers.append(sticker)
        data["stickers"] = tuple(stickers)

        raw_cells = source.get("cells", source.get("cell", ())) or ()
        data["cells"] = tuple(_coerce_cell(cell) for cell in raw_cells)
        data["skip_rows"] = frozenset(data.get("skip_rows") or ())
        data["skip_columns"] = frozenset(data.get("skip_columns") or ())
        return cls(**data)


_LAYOUTS = frozenset({"left", "right", "top"})


def _field_color(field: str) -> RGB | None:
    if field.startswith("#") or field.lower() in NAMED_COLORS:
        return parse_color(field)
    return None


def _combo_at(spec: str, color: RGB | str | None = None, layout: str = "left") -> ComboSticker:
    parts = spec.split("|")
    piped = _field_color(parts[-1]) if parts else None
    if piped is not None:
        if color is not None:
            raise LabelError("a combo names two colours")
        color = piped
        parts = parts[:-1]
    if len(parts) < 2 or not parts[1]:
        raise LabelError("a combo needs text")
    if len(parts) > 4:
        raise LabelError("a combo has too many fields")
    start, text = parts[0], parts[1]
    extra = parts[2:]
    end = ""
    chosen = layout
    layout_set = False
    if len(extra) == 1 and extra[0] in _LAYOUTS:
        chosen = extra[0]
        layout_set = True
    elif len(extra) == 1:
        end = extra[0]
    elif len(extra) == 2:
        end, chosen = extra
        if chosen not in _LAYOUTS:
            raise LabelError("layout must be left, right, or top")
        layout_set = True
    if not start and not end:
        raise LabelError("a combo needs a picture")
    if not start:
        if not layout_set:
            chosen = "right"
            layout_set = True
        return ComboSticker(Path(end), text, color, chosen, None, layout_set)
    return ComboSticker(
        Path(start),
        text,
        color,
        chosen,
        Path(end) if end else None,
        layout_set,
    )


def _coerce_sticker(value: Sticker | Sequence[Any] | Mapping[str, Any] | str) -> Sticker:
    if isinstance(value, (TextSticker, ImageSticker, ComboSticker)):
        return value
    if isinstance(value, str):
        if value.startswith("@") and "|" in value[1:]:
            return _combo_at(value[1:])
        if value.startswith("@"):
            return ImageSticker(Path(value[1:]))
        return TextSticker(value)
    if isinstance(value, Sequence) and not isinstance(value, str) and len(value) >= 3 and value[0] == "combo":
        color = value[3] if len(value) > 3 else None
        layout = value[4] if len(value) > 4 else "left"
        end = value[5] if len(value) > 5 else None
        return ComboSticker(Path(value[1]), str(value[2]), color, str(layout), Path(end) if end else None)
    if isinstance(value, Mapping):
        kind = value.get("kind", "text")
        raw = value.get("value", value.get("text", value.get("path")))
        color = value.get("color")
        if kind == "combo":
            path = value.get("path", raw)
            end = value.get("end")
            return ComboSticker(
                Path(path),
                str(value.get("text", "")),
                color,
                str(value.get("layout", "left")),
                Path(end) if end else None,
            )
    else:
        if len(value) < 2:
            raise LabelError("a sticker tuple needs a kind and value")
        kind, raw = value[0], value[1]
        color = value[2] if len(value) > 2 else None
    if kind == "image":
        return ImageSticker(Path(raw))
    if kind == "text":
        return TextSticker(str(raw), color)
    raise LabelError(f"unknown sticker kind {kind!r}")


def _coerce_cell(value: CellOverride | Sequence[Any] | Mapping[str, Any]) -> CellOverride:
    if isinstance(value, CellOverride):
        return value
    if isinstance(value, Mapping):
        row = int(value["row"])
        column = int(value.get("column", value.get("col")))
        sticker = _coerce_sticker(value["sticker"])
        return CellOverride(row, column, sticker)
    if len(value) == 3 and isinstance(value[2], (TextSticker, ImageSticker, ComboSticker)):
        return CellOverride(int(value[0]), int(value[1]), value[2])
    if len(value) < 3:
        raise LabelError("a cell needs a row, column, and sticker")
    row, column, raw = int(value[0]), int(value[1]), str(value[2])
    color = value[3] if len(value) > 3 else None
    if raw.startswith("@") and "|" in raw[1:]:
        sticker = _combo_at(raw[1:], color)
    elif raw.startswith("@"):
        sticker = ImageSticker(Path(raw[1:]))
    else:
        sticker = TextSticker(raw, color)
    return CellOverride(row, column, sticker)
