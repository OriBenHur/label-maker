"""Turn a sticker graphic into SVG text.

An ``.svg`` file is returned unchanged. Any other picture Pillow can open
becomes an SVG: ``trace=True`` outlines a flat logo, and everything else is
wrapped as an embedded image. A later UI can call :func:`to_svg` on its own.
"""

import os
import subprocess
import sys
import tempfile
import warnings

from .model import LabelError

_VTRACER_OK = None
_TRACE_NOTE = False
PRINT_DPI = 300


def sticker_px(width_mm, height_mm, inset):
    """Pixel size of a sticker drawn at PRINT_DPI inside its inset."""
    scale = (1 - 2 * inset) / 25.4 * PRINT_DPI
    return max(1, round(width_mm * scale)), max(1, round(height_mm * scale))


def fit_box(src_w, src_h, box_w, box_h):
    scale = min(box_w / src_w, box_h / src_h)
    return max(1, round(src_w * scale)), max(1, round(src_h * scale))


def to_svg(path, trace=False, box=None):
    path = os.fspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f'no such image {path}')
    if _is_svg(path):
        return _read(path)
    im = open_image(path)
    photo = looks_like_photo(im)
    if trace and not photo:
        return _trace(im, box)
    if trace:
        warnings.warn(
            'photograph left as an embedded image; tracing would not stay sharp',
            stacklevel=2,
        )
    return _wrap(im, box, photo)


def open_image(path):
    with open(path, 'rb') as f:
        data = f.read()
    return open_raster(data)


def open_raster(data):
    try:
        from PIL import Image, ImageOps
    except ImportError as error:
        raise LabelError(
            'reading this picture needs Pillow: pip install pillow'
        ) from error
    from io import BytesIO
    try:
        im = ImageOps.exif_transpose(Image.open(BytesIO(data)))
        im.load()
    except OSError as error:
        raise LabelError('cannot read that picture') from error
    return im


def looks_like_photo(im):
    """True when six flat colours cannot describe the picture."""
    from PIL import Image
    small = im.convert('RGBA')
    small.thumbnail((48, 48))
    bg = Image.new('RGB', small.size, (128, 128, 128))
    bg.paste(small.convert('RGB'), mask=small.getchannel('A'))
    q = bg.quantize(colors=6, dither=Image.Dither.NONE)
    back = q.convert('RGB')
    err = 0
    n = 0
    for a, b in zip(bg.getdata(), back.getdata()):
        err += abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])
        n += 3
    return err / max(n, 1) > 12


def _is_svg(path):
    if path.lower().endswith('.svg'):
        return True
    with open(path, 'rb') as f:
        head = f.read(512).lstrip().lower()
    return head.startswith(b'<?xml') or head.startswith(b'<svg')


def _read(path):
    with open(path, 'rb') as file:
        data = file.read()
    for enc in ('utf-8-sig', 'utf-8', 'latin-1'):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode('latin-1')


def focus_artwork(svg):
    """Zoom an embedded picture in on its artwork, dropping a flat margin."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return svg
    image = next((elem for elem in root.iter() if elem.tag.rsplit("}", 1)[-1] == "image"), None)
    if image is None:
        return svg
    href = image.get("href") or image.get("{http://www.w3.org/1999/xlink}href") or ""
    if not href.startswith("data:"):
        return svg
    head, _, data = href.partition(",")
    if ";base64" not in head:
        return svg
    import base64
    box = _content_box(open_raster(base64.b64decode(data)))
    if box is None:
        return svg
    x, y, w, h = box
    root.set("viewBox", f"{x} {y} {w} {h}")
    root.set("width", str(w))
    root.set("height", str(h))
    return ET.tostring(root, encoding="unicode")


def _content_box(im):
    rgba = im.convert("RGBA")
    w, h = rgba.size
    if w < 2 or h < 2:
        return None
    px = rgba.load()
    bg = px[0, 0]
    corners = (px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1])
    if any(_far(sample, bg) for sample in corners):
        return None

    def ink(x, y):
        sample = px[x, y]
        return sample[3] > 16 and _far(sample, bg)

    min_x, min_y, max_x, max_y = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            if not ink(x, y):
                continue
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
    if max_x < 0:
        return None
    box_w, box_h = max_x - min_x + 1, max_y - min_y + 1
    if box_w > w * 0.92 and box_h > h * 0.92:
        return None
    return min_x, min_y, box_w, box_h


def _far(sample, bg):
    return sum(abs(a - b) for a, b in zip(sample, bg)) > 48


def _wrap(im, box, photo):
    import base64
    from io import BytesIO
    from PIL import Image
    rgba = im.convert('RGBA')
    if box:
        method = Image.Resampling.LANCZOS if photo else Image.Resampling.NEAREST
        rgba = _resample(rgba, box, method)
    buf = BytesIO()
    rgba.save(buf, format='PNG')
    b64 = base64.b64encode(buf.getvalue()).decode('ascii')
    w, h = rgba.size
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">'
        f'<image width="{w}" height="{h}" href="data:image/png;base64,{b64}"/>'
        f'</svg>'
    )


def _resample(im, box, method):
    w, h = im.size
    size = fit_box(w, h, box[0], box[1])
    if size == (w, h):
        return im
    return im.resize(size, method)


def _trace(im, box):
    svg = _vtracer(im)
    if svg:
        return svg
    _note_builtin()
    return _outline(im, box)


def _note_builtin():
    global _TRACE_NOTE
    if _TRACE_NOTE:
        return
    _TRACE_NOTE = True
    warnings.warn('traced with the built-in outliner', stacklevel=2)


def _vtracer(im):
    global _VTRACER_OK
    if _VTRACER_OK is False:
        return None
    try:
        import vtracer  # noqa: F401
    except ImportError:
        _VTRACER_OK = False
        return None
    try:
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, 'in.png')
            dst = os.path.join(d, 'out.svg')
            im.convert('RGBA').save(src, format='PNG')
            proc = subprocess.run(
                [sys.executable, '-c',
                 'import sys, vtracer\n'
                 'vtracer.convert_image_to_svg_py(sys.argv[1], sys.argv[2], '
                 'colormode="color", mode="spline", filter_speckle=4)\n',
                 src, dst],
                capture_output=True, timeout=30)
            if proc.returncode != 0 or not os.path.isfile(dst):
                _VTRACER_OK = False
                return None
            _VTRACER_OK = True
            return _read(dst)
    except (OSError, subprocess.TimeoutExpired):
        _VTRACER_OK = False
        return None


def _outline(im, box=None):
    """One even-odd path per flat colour. Loops are pixel edges."""
    from PIL import Image
    rgba = im.convert('RGBA')
    w, h = rgba.size
    limit = max(box) if box else 512
    scale = limit / max(w, h)
    if scale < 1:
        rgba = rgba.resize((max(1, round(w * scale)), max(1, round(h * scale))),
                           Image.Resampling.NEAREST)
        w, h = rgba.size
    rgb = Image.new('RGB', (w, h), (255, 255, 255))
    alpha = rgba.getchannel('A')
    solid = alpha.point(lambda a: 255 if a >= 128 else 0)
    rgb.paste(rgba.convert('RGB'), mask=solid)
    q = rgb.quantize(colors=8, dither=Image.Dither.NONE)
    pal = q.getpalette()
    idx = list(q.getdata())
    shown = list(solid.getdata())
    masks = {}
    for i, (color, on) in enumerate(zip(idx, shown)):
        if not on:
            continue
        mask = masks.get(color)
        if mask is None:
            mask = bytearray(w * h)
            masks[color] = mask
        mask[i] = 1
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">'
    ]
    for color, mask in sorted(masks.items(), key=lambda kv: -sum(kv[1])):
        loops = _loops(mask, w, h)
        if not loops:
            continue
        r, g, b = pal[3 * color:3 * color + 3]
        d = _path_d(loops)
        parts.append(
            f'<path fill="#{r:02x}{g:02x}{b:02x}" fill-rule="evenodd" d="{d}"/>')
    parts.append('</svg>')
    return ''.join(parts)


def _loops(mask, w, h):
    def on(x, y):
        return 0 <= x < w and 0 <= y < h and mask[y * w + x]

    edges = []
    for y in range(h):
        row = y * w
        for x in range(w):
            if not mask[row + x]:
                continue
            if not on(x, y - 1):
                edges.append(((x, y), (x + 1, y)))
            if not on(x + 1, y):
                edges.append(((x + 1, y), (x + 1, y + 1)))
            if not on(x, y + 1):
                edges.append(((x + 1, y + 1), (x, y + 1)))
            if not on(x - 1, y):
                edges.append(((x, y + 1), (x, y)))
    outgoing = {}
    for a, b in edges:
        outgoing.setdefault(a, []).append(b)
    used = set()
    loops = []
    for start in edges:
        if start in used:
            continue
        prev, cur = start
        loop = [prev]
        used.add(start)
        guard = 0
        while cur != start[0] and guard <= len(edges):
            loop.append(cur)
            nxts = [n for n in outgoing.get(cur, ()) if (cur, n) not in used]
            if not nxts:
                break
            nxt = _pick(prev, cur, nxts)
            used.add((cur, nxt))
            prev, cur = cur, nxt
            guard += 1
        if cur == start[0] and len(loop) >= 4:
            simple = _simplify(loop)
            if len(simple) >= 3:
                loops.append(simple)
    loops.sort(key=lambda lp: lp[0])
    return loops


# Counter-clockwise on a y-down page, so a corner shared by two pixels
# keeps each pixel on its own loop.
_CCW = ((1, 0), (0, -1), (-1, 0), (0, 1))


def _pick(prev, cur, nxts):
    back = (prev[0] - cur[0], prev[1] - cur[1])
    i0 = _CCW.index(back)
    have = set(nxts)
    for k in range(1, 4):
        dx, dy = _CCW[(i0 + k) % 4]
        cand = (cur[0] + dx, cur[1] + dy)
        if cand in have:
            return cand
    return nxts[0]


def _simplify(loop):
    keep = []
    n = len(loop)
    for i in range(n):
        a, b, c = loop[(i - 1) % n], loop[i], loop[(i + 1) % n]
        cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if cross == 0:
            continue
        keep.append(b)
    return keep


def _path_d(loops):
    parts = []
    for loop in loops:
        x, y = loop[0]
        parts.append(f'M {x} {y}')
        for x, y in loop[1:]:
            parts.append(f'L {x} {y}')
        parts.append('Z')
    return ' '.join(parts)
