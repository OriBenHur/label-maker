from __future__ import annotations

from typing import Any, Mapping

from .model import (
    CellOverride,
    ComboSticker,
    ImageSticker,
    LabelError,
    LayoutError,
    SheetSpec,
    TextSticker,
)
from .sheet import LabelSheet
from .to_svg import to_svg

__all__ = [
    "CellOverride",
    "ComboSticker",
    "ImageSticker",
    "LabelError",
    "LabelSheet",
    "LayoutError",
    "SheetSpec",
    "TextSticker",
    "render_pdf",
    "to_svg",
]


def render_pdf(spec: SheetSpec | Mapping[str, Any] | object) -> bytes:
    return LabelSheet(SheetSpec.from_value(spec)).render()
