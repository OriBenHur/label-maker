from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import click
from click.shell_completion import CompletionItem, get_completion_class

from .manual import man_page
from .model import (
    NAMED_COLORS,
    CellOverride,
    ComboSticker,
    ImageSticker,
    LabelError,
    SheetSpec,
    TextSticker,
    _combo_at,
    parse_color,
)
from .sheet import LabelSheet


class ColorType(click.ParamType):
    name = "color"

    def convert(self, value: Any, param: click.Parameter | None, ctx: click.Context | None):
        try:
            return parse_color(value)
        except LabelError as error:
            self.fail(str(error), param, ctx)

    def shell_complete(self, ctx: click.Context, param: click.Parameter, incomplete: str):
        needle = incomplete.lower()
        return [CompletionItem(name) for name in NAMED_COLORS if name.startswith(needle)]


class CellType(click.ParamType):
    name = "row,col,text[,color]"

    def convert(self, value: Any, param: click.Parameter | None, ctx: click.Context | None):
        try:
            row_text, column_text, content = str(value).split(",", 2)
            row = int(row_text)
            column = int(column_text)
            if row < 1 or column < 1:
                raise LabelError("cell row and column are 1-based")
            color = None
            tail = content.rsplit(",", 1)
            if len(tail) == 2 and (
                tail[1].startswith("#") or tail[1].lower() in NAMED_COLORS
            ):
                content, color_text = tail
                color = parse_color(color_text)
            if content.startswith("@") and "|" in content[1:]:
                sticker = _combo_at(content[1:], color)
            elif content.startswith("@"):
                sticker = ImageSticker(Path(content[1:]))
            else:
                sticker = TextSticker(content, color)
            return CellOverride(row, column, sticker)
        except (LabelError, ValueError) as error:
            self.fail(str(error) or "expected ROW,COL,TEXT[,COLOR]", param, ctx)


class OrderedContentCommand(click.Command):
    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        normalized = _normalize_combos(list(args))
        ctx.meta["sticker_kinds"] = self._sticker_kinds(normalized)
        return super().parse_args(ctx, normalized)

    @staticmethod
    def _sticker_kinds(args: list[str]) -> list[str]:
        kinds = []
        index = 0
        while index < len(args):
            arg = args[index]
            if arg == "--":
                break
            if arg in ("-T", "--text"):
                kinds.append("text")
                index += 2
                continue
            if arg in ("-I", "--image"):
                kinds.append("image")
                index += 2
                continue
            if arg == "--combo":
                kinds.append("combo")
                index += 2
                continue
            if arg.startswith("--combo="):
                kinds.append("combo")
                index += 1
                continue
            if arg.startswith("--text=") or arg.startswith("-T") and len(arg) > 2:
                kinds.append("text")
            elif arg.startswith("--image=") or arg.startswith("-I") and len(arg) > 2:
                kinds.append("image")
            index += 1
        return kinds


def _normalize_combos(args: list[str]) -> list[str]:
    output: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            output.extend(args[index:])
            break
        if arg == "--combo" and index + 1 < len(args):
            spec = args[index + 1]
            index += 2
            if "|" not in spec and index < len(args) and not args[index].startswith("-"):
                spec = f"{spec}|{args[index]}"
                index += 1
            output.extend(["--combo", spec])
            continue
        output.append(arg)
        index += 1
    return output


def _combo_spec(spec: str) -> ComboSticker:
    body = spec
    color = None
    tail = spec.rsplit(",", 1)
    if len(tail) == 2 and (tail[1].startswith("#") or tail[1].lower() in NAMED_COLORS):
        body, color_text = tail
        color = parse_color(color_text)
    return _combo_at(body, color)


def _show_manual(ctx: click.Context, param: click.Parameter, value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return
    text = man_page()
    if not sys.stdout.isatty():
        click.echo(text, nl=False)
        ctx.exit()
    descriptor, name = tempfile.mkstemp(prefix="make-labels-", suffix=".1")
    os.write(descriptor, text.encode())
    os.close(descriptor)
    try:
        subprocess.run(["man", name], check=False)
    finally:
        os.unlink(name)
    ctx.exit()


def _print_completion(ctx: click.Context, param: click.Parameter, value: str | None) -> None:
    if not value or ctx.resilient_parsing:
        return
    shell = get_completion_class(value)
    if shell is None:
        raise click.BadParameter(value, ctx=ctx, param=param)
    script = shell(ctx.command, {}, "make-labels", "_MAKE_LABELS_COMPLETE")
    click.echo(script.source())
    ctx.exit()


@click.command(
    cls=OrderedContentCommand,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option("-W", "--page-w", type=click.FloatRange(min=0, min_open=True), default=110, show_default=True, help="Paper width in millimetres.")
@click.option("-H", "--page-h", type=click.FloatRange(min=0, min_open=True), default=152, show_default=True, help="Paper height in millimetres.")
@click.option("-c", "--cols", type=click.IntRange(min=1), default=2, show_default=True, help="Stickers across the page.")
@click.option("-r", "--rows", type=click.IntRange(min=1), default=4, show_default=True, help="Stickers down the page.")
@click.option("-w", "--lw", type=click.FloatRange(min=0, min_open=True), default=52, show_default=True, help="Sticker width in millimetres.")
@click.option("-t", "--lh", type=click.FloatRange(min=0, min_open=True), default=34, show_default=True, help="Sticker height in millimetres.")
@click.option("-g", "--gap-x", type=float, default=2.7, show_default=True, help="Horizontal space between stickers, in millimetres.")
@click.option("-G", "--gap-y", type=float, default=4, show_default=True, help="Vertical space between stickers, in millimetres.")
@click.option("-m", "--margin-x", type=float, help="Left margin in millimetres. Centers the row when omitted.")
@click.option("-M", "--margin-y", type=float, help="Top margin in millimetres. Centers the column when omitted.")
@click.option("-x", "--offset-x", type=float, default=0, show_default=True, help="Extra shift to the right, in millimetres.")
@click.option("-y", "--offset-y", type=float, default=0, show_default=True, help="Extra shift down, in millimetres.")
@click.option(
    "-T",
    "--text",
    multiple=True,
    help="Text for one sticker. Use a real newline or the two characters \\n.",
)
@click.option(
    "-I",
    "--image",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="SVG, PNG, JPEG, GIF, WebP, BMP, or TIFF for one sticker.",
)
@click.option("--trace", is_flag=True, help="Outline flat raster artwork as vector paths.")
@click.option(
    "--combo",
    multiple=True,
    metavar="SPEC",
    help="PATH|TEXT, or PATH TEXT. Add |END, |LAYOUT, or ,COLOR the same way as --cell.",
)
@click.option(
    "--layout",
    type=click.Choice(("left", "right", "top")),
    default="left",
    show_default=True,
    help="Default layout when a combo or cell does not name left, right, or top.",
)
@click.option("-C", "--color", "colors", multiple=True, type=ColorType(), help="Colour for the next text or combo. A name or #rrggbb.")
@click.option("-e", "--cell", "cells", multiple=True, type=CellType(), help="One sticker: ROW,COL,TEXT[,COLOR].")
@click.option("-F", "--font-mm", type=click.FloatRange(min=0, min_open=True), help="Letter height in millimetres.")
@click.option("-R", "--rotate", is_flag=True, help="Turn sticker content from the bottom toward the top.")
@click.option("-n", "--limit", type=click.IntRange(min=0), help="How many stickers to print.")
@click.option("-L", "--row", type=click.IntRange(min=1), help="Print only this row.")
@click.option("-S", "--skip-row", "skip_rows", multiple=True, type=click.IntRange(min=1), help="Leave this row blank.")
@click.option("-s", "--skip-col", "skip_columns", multiple=True, type=click.IntRange(min=1), help="Leave this column blank.")
@click.option("-b", "--outline", is_flag=True, help="Draw alignment borders and a ruler only.")
@click.option("-p", "--proof", is_flag=True, help="Draw content with alignment borders and a ruler.")
@click.option("-f", "--force", is_flag=True, help="Write even when the grid overflows the page.")
@click.option("-o", "--out", type=click.Path(dir_okay=False, path_type=Path), help="PDF file to write.")
@click.option("--man", is_flag=True, is_eager=True, expose_value=False, callback=_show_manual, help="Open the manual and exit.")
@click.option(
    "--completion",
    type=click.Choice(("zsh", "bash", "fish")),
    is_eager=True,
    expose_value=False,
    callback=_print_completion,
    help="Print a shell completion script and exit.",
)
@click.pass_context
def main(
    ctx: click.Context,
    page_w: float,
    page_h: float,
    cols: int,
    rows: int,
    lw: float,
    lh: float,
    gap_x: float,
    gap_y: float,
    margin_x: float | None,
    margin_y: float | None,
    offset_x: float,
    offset_y: float,
    text: tuple[str, ...],
    image: tuple[Path, ...],
    trace: bool,
    combo: tuple[str, ...],
    layout: str,
    colors: tuple[tuple[float, float, float], ...],
    cells: tuple[CellOverride, ...],
    font_mm: float | None,
    rotate: bool,
    limit: int | None,
    row: int | None,
    skip_rows: tuple[int, ...],
    skip_columns: tuple[int, ...],
    outline: bool,
    proof: bool,
    force: bool,
    out: Path | None,
) -> None:
    output = out or Path("proof.pdf" if proof else "alignment.pdf" if outline else "labels.pdf")
    try:
        stickers = _ordered_stickers(ctx, text, image, combo, colors, layout)
        cells = tuple(_with_layout(cell, layout) for cell in cells)
        spec = SheetSpec(
            page_width_mm=page_w,
            page_height_mm=page_h,
            columns=cols,
            rows=rows,
            label_width_mm=lw,
            label_height_mm=lh,
            gap_x_mm=gap_x,
            gap_y_mm=gap_y,
            margin_x_mm=margin_x,
            margin_y_mm=margin_y,
            offset_x_mm=offset_x,
            offset_y_mm=offset_y,
            stickers=stickers,
            cells=cells,
            font_size_mm=font_mm,
            rotate=rotate,
            trace=trace,
            limit=limit,
            row=row,
            skip_rows=frozenset(skip_rows),
            skip_columns=frozenset(skip_columns),
            outline=outline,
            proof=proof,
            force=force,
        )
        sheet = LabelSheet(spec)
        data = sheet.render()
        output.write_bytes(data)
    except (LabelError, FileNotFoundError, OSError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(output)
    click.echo(sheet.summary())


def run() -> None:
    main(prog_name="make-labels", complete_var="_MAKE_LABELS_COMPLETE")


def _ordered_stickers(
    ctx: click.Context,
    texts: tuple[str, ...],
    images: tuple[Path, ...],
    combos: tuple[str, ...],
    colors: tuple[tuple[float, float, float], ...],
    layout: str,
) -> tuple[TextSticker | ImageSticker | ComboSticker, ...]:
    kinds = ctx.meta.get("sticker_kinds", [])
    if len(kinds) != len(texts) + len(images) + len(combos):
        kinds = ["text"] * len(texts) + ["image"] * len(images) + ["combo"] * len(combos)
    text_values = iter(texts)
    image_values = iter(images)
    combo_values = iter(combos)
    text_index = 0
    stickers = []
    for kind in kinds:
        if kind == "image":
            stickers.append(ImageSticker(next(image_values)))
            continue
        if kind == "combo":
            sticker = _combo_spec(next(combo_values))
            if sticker.color is None:
                color = colors[text_index] if text_index < len(colors) else None
                text_index += 1
                sticker = _with_color(sticker, color)
            stickers.append(_with_default_layout(sticker, layout))
            continue
        color = colors[text_index] if text_index < len(colors) else None
        text_index += 1
        stickers.append(TextSticker(next(text_values), color))
    return tuple(stickers)


def _with_color(sticker: ComboSticker, color: tuple[float, float, float] | None) -> ComboSticker:
    if color is None:
        return sticker
    return ComboSticker(
        sticker.path,
        sticker.text,
        color,
        sticker.layout,
        sticker.end,
        sticker.layout_set,
    )


def _with_default_layout(sticker: ComboSticker, layout: str) -> ComboSticker:
    if sticker.layout_set or sticker.end is not None or sticker.layout == "right":
        return sticker
    return ComboSticker(
        sticker.path,
        sticker.text,
        sticker.color,
        layout,
        sticker.end,
        False,
    )


def _with_layout(cell: CellOverride, layout: str) -> CellOverride:
    sticker = cell.sticker
    if not isinstance(sticker, ComboSticker):
        return cell
    styled = _with_default_layout(sticker, layout)
    if styled is sticker:
        return cell
    return CellOverride(cell.row, cell.column, styled)
