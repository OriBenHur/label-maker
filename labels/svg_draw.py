"""Draw an SVG subset into a PDF content stream.

Paths, shapes, group transforms, flat fills and strokes, and embedded images.
Gradients, filters, and text inside the SVG are left out. Coordinates stay in
SVG space; one matrix maps that space onto the sticker, y down.
"""

import base64
import hashlib
import math
import os
import re
import urllib.parse
from xml.etree import ElementTree as ET

from .model import LabelError
from .to_svg import open_raster

INSET = 0.04

_COLORS = {
    'black': (0, 0, 0), 'silver': (0.753, 0.753, 0.753),
    'gray': (0.502, 0.502, 0.502), 'grey': (0.502, 0.502, 0.502),
    'white': (1, 1, 1), 'maroon': (0.502, 0, 0), 'red': (1, 0, 0),
    'purple': (0.502, 0, 0.502), 'fuchsia': (1, 0, 1), 'magenta': (1, 0, 1),
    'green': (0, 0.502, 0), 'lime': (0, 1, 0), 'olive': (0.502, 0.502, 0),
    'yellow': (1, 1, 0), 'navy': (0, 0, 0.502), 'blue': (0, 0, 1),
    'teal': (0, 0.502, 0.502), 'aqua': (0, 1, 1), 'cyan': (0, 1, 1),
    'orange': (1, 0.647, 0), 'brown': (0.647, 0.165, 0.165),
    'pink': (1, 0.753, 0.796),
}

_SKIP = {
    'defs', 'title', 'desc', 'metadata', 'style', 'script', 'symbol', 'use',
    'marker', 'clippath', 'mask', 'pattern', 'filter', 'lineargradient',
    'radialgradient', 'text', 'tspan', 'textpath', 'namedview', 'foreignobject',
}

_STYLE_KEYS = {
    'fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin',
    'stroke-miterlimit', 'stroke-dasharray', 'stroke-dashoffset', 'fill-rule',
    'fill-opacity', 'stroke-opacity', 'opacity', 'color', 'display', 'visibility',
}

_NUM = re.compile(r'[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?')
_TF = re.compile(r'(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)')
_KAPPA = 0.5522847498


def fmt(x):
    s = f'{x:.6f}'.rstrip('0').rstrip('.')
    if s in ('', '-0'):
        return '0'
    return s


class PdfImage:
    def __init__(self, name, w, h, rgb, alpha):
        self.name = name
        self.w = w
        self.h = h
        self.rgb = rgb
        self.alpha = alpha


class Resources:
    def __init__(self):
        self.images = []
        self.states = []
        self._img = {}
        self._gs = {}

    def extgstate(self, fill_a, stroke_a):
        fill_a = min(1.0, max(0.0, fill_a))
        stroke_a = min(1.0, max(0.0, stroke_a))
        if fill_a > 0.999 and stroke_a > 0.999:
            return None
        key = (round(fill_a, 3), round(stroke_a, 3))
        name = self._gs.get(key)
        if name is None:
            name = f'Gs{len(self.states)}'
            self.states.append((name, key[0], key[1]))
            self._gs[key] = name
        return name

    def image(self, im):
        im = im.convert('RGBA')
        w, h = im.size
        raw = im.tobytes()
        rgb_rows = []
        alpha_rows = []
        stride = w * 4
        for y in range(h):
            row = raw[y * stride:(y + 1) * stride]
            rgb = bytearray()
            alpha = bytearray()
            for i in range(0, len(row), 4):
                rgb += row[i:i + 3]
                alpha.append(row[i + 3])
            rgb_rows.append(bytes(rgb))
            alpha_rows.append(bytes(alpha))
        rgb = b''.join(rgb_rows)
        alpha = b''.join(alpha_rows)
        if all(p == 255 for p in alpha):
            alpha = None
        key = hashlib.sha1(rgb + (alpha or b'')).digest()
        name = self._img.get(key)
        if name is None:
            name = f'Im{len(self.images)}'
            self.images.append(PdfImage(name, w, h, rgb, alpha))
            self._img[key] = name
        return name


class Style:
    def __init__(self):
        self.fill = (0, 0, 0)
        self.stroke = None
        self.stroke_width = 1.0
        self.linecap = 'butt'
        self.linejoin = 'miter'
        self.miterlimit = 4.0
        self.dash = None
        self.dash_offset = 0.0
        self.fill_rule = 'nonzero'
        self.fill_opacity = 1.0
        self.stroke_opacity = 1.0
        self.opacity = 1.0
        self.color = (0, 0, 0)
        self.display = True

    def copy(self):
        other = Style()
        other.__dict__.update(self.__dict__)
        return other


def paint_svg(svg, x, y, w, h, resources, rotate=False, base_dir=None):
    """Draw ``svg`` into the sticker rectangle whose bottom-left is ``(x, y)``."""
    root = parse_svg(svg)
    vx, vy, vw, vh = view_box(root)
    bw, bh = (h, w) if rotate else (w, h)
    bw *= 1 - 2 * INSET
    bh *= 1 - 2 * INSET
    scale = min(bw / vw, bh / vh)
    dw, dh = vw * scale, vh * scale
    # +y in the SVG maps to -y in PDF, and the drawing sits on the sticker centre.
    a, d = scale, -scale
    e = -dw / 2 - vx * scale
    f = dh / 2 + vy * scale
    cx, cy = x + w / 2, y + h / 2
    out = [
        'q\n',
        f'{fmt(x)} {fmt(y)} {fmt(w)} {fmt(h)} re W n\n',
        f'1 0 0 1 {fmt(cx)} {fmt(cy)} cm\n',
    ]
    if rotate:
        out.append('0 1 -1 0 0 0 cm\n')
    out.append(f'{fmt(a)} 0 0 {fmt(d)} {fmt(e)} {fmt(f)} cm\n')
    Drawer(out, resources, base_dir).walk(root, Style())
    out.append('Q\n')
    return ''.join(out)


def parse_svg(text):
    text = text.lstrip('\ufeff')
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise LabelError(f'not an svg this tool can read ({e})') from e
    if local(root.tag) != 'svg':
        raise LabelError('the file is not an svg')
    return root


def view_box(elem):
    raw = elem.get('viewBox')
    if raw:
        p = [float(v) for v in re.split(r'[\s,]+', raw.strip()) if v]
        if len(p) != 4 or p[2] == 0 or p[3] == 0:
            raise LabelError('svg viewBox needs a width and a height')
        return tuple(p)
    w = length(elem.get('width'), None)
    h = length(elem.get('height'), None)
    if w and h:
        return 0, 0, w, h
    return 0, 0, 100, 100


def local(tag):
    if not isinstance(tag, str):
        return ''
    if '}' in tag:
        return tag.rsplit('}', 1)[1]
    return tag


def length(value, default=0.0):
    if value is None or str(value).strip() == '':
        return default
    m = re.fullmatch(
        r'([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)([a-z%]*)', str(value).strip())
    if not m:
        raise LabelError(f'bad svg length {value!r}')
    n = float(m.group(1))
    unit = m.group(2)
    if unit in ('', 'px'):
        return n
    if unit == '%':
        raise LabelError('svg sizes in percent are not supported')
    scale = {'in': 96.0, 'pt': 96.0 / 72.0, 'pc': 16.0,
             'mm': 96.0 / 25.4, 'cm': 96.0 / 2.54}
    if unit not in scale:
        raise LabelError(f'bad svg unit {unit!r}')
    return n * scale[unit]


class Drawer:
    def __init__(self, out, resources, base_dir):
        self.out = out
        self.resources = resources
        self.base_dir = base_dir

    def walk(self, elem, style):
        tag = local(elem.tag).lower()
        if not tag or tag in _SKIP:
            return
        style = derive(style, elem)
        if not style.display:
            return
        tr = elem.get('transform')
        if tr and _TF.search(tr):
            self.out.append('q ' + ' '.join(fmt(v) for v in parse_transform(tr)) + ' cm\n')
        if tag in ('svg', 'g', 'a', 'switch'):
            for child in list(elem):
                self.walk(child, style)
        elif tag == 'rect':
            self.rect(elem, style)
        elif tag == 'circle':
            self.ellipse(length(elem.get('cx'), 0), length(elem.get('cy'), 0),
                         length(elem.get('r'), 0), length(elem.get('r'), 0), style)
        elif tag == 'ellipse':
            self.ellipse(length(elem.get('cx'), 0), length(elem.get('cy'), 0),
                         length(elem.get('rx'), 0), length(elem.get('ry'), 0), style)
        elif tag == 'line':
            self.line(elem, style)
        elif tag == 'polyline':
            self.poly(elem, style, close=False)
        elif tag == 'polygon':
            self.poly(elem, style, close=True)
        elif tag == 'path':
            self.path(elem, style)
        elif tag == 'image':
            self.image(elem, style)
        else:
            for child in list(elem):
                self.walk(child, style)
        if tr and _TF.search(tr):
            self.out.append('Q\n')

    def rect(self, elem, style):
        x, y = length(elem.get('x'), 0), length(elem.get('y'), 0)
        w, h = length(elem.get('width'), 0), length(elem.get('height'), 0)
        if w <= 0 or h <= 0:
            return
        rx = length(elem.get('rx'), 0)
        ry = length(elem.get('ry'), 0)
        if elem.get('rx') is None and elem.get('ry') is not None:
            rx = ry
        elif elem.get('ry') is None and elem.get('rx') is not None:
            ry = rx
        rx, ry = min(rx, w / 2), min(ry, h / 2)
        if rx <= 0 or ry <= 0:
            self.emit(f'{fmt(x)} {fmt(y)} {fmt(w)} {fmt(h)} re', style)
            return
        k = _KAPPA
        p = Path()
        p.move(x + rx, y)
        p.line(x + w - rx, y)
        p.cubic(x + w - rx + k * rx, y, x + w, y + ry - k * ry, x + w, y + ry)
        p.line(x + w, y + h - ry)
        p.cubic(x + w, y + h - ry + k * ry, x + w - rx + k * rx, y + h, x + w - rx, y + h)
        p.line(x + rx, y + h)
        p.cubic(x + rx - k * rx, y + h, x, y + h - ry + k * ry, x, y + h - ry)
        p.line(x, y + ry)
        p.cubic(x, y + ry - k * ry, x + rx - k * rx, y, x + rx, y)
        p.close()
        self.emit(p.text(), style)

    def ellipse(self, cx, cy, rx, ry, style):
        if rx <= 0 or ry <= 0:
            return
        k = _KAPPA
        p = Path()
        p.move(cx + rx, cy)
        p.cubic(cx + rx, cy + k * ry, cx + k * rx, cy + ry, cx, cy + ry)
        p.cubic(cx - k * rx, cy + ry, cx - rx, cy + k * ry, cx - rx, cy)
        p.cubic(cx - rx, cy - k * ry, cx - k * rx, cy - ry, cx, cy - ry)
        p.cubic(cx + k * rx, cy - ry, cx + rx, cy - k * ry, cx + rx, cy)
        p.close()
        self.emit(p.text(), style)

    def line(self, elem, style):
        p = Path()
        p.move(length(elem.get('x1'), 0), length(elem.get('y1'), 0))
        p.line(length(elem.get('x2'), 0), length(elem.get('y2'), 0))
        drawn = style.copy()
        drawn.fill = None
        self.emit(p.text(), drawn)

    def poly(self, elem, style, close):
        pts = pairs(elem.get('points') or '')
        if len(pts) < 2:
            return
        p = Path()
        p.move(*pts[0])
        for pt in pts[1:]:
            p.line(*pt)
        if close:
            p.close()
        self.emit(p.text(), style)

    def path(self, elem, style):
        d = elem.get('d')
        if not d or not d.strip():
            return
        try:
            self.emit(compile_path(d).text(), style)
        except ValueError as e:
            raise LabelError(str(e)) from e

    def image(self, elem, style):
        href = elem.get('href') or elem.get('{http://www.w3.org/1999/xlink}href')
        data = href_bytes(href, self.base_dir)
        im = open_raster(data)
        iw, ih = im.size
        x, y = length(elem.get('x'), 0), length(elem.get('y'), 0)
        w = length(elem.get('width'), iw)
        h = length(elem.get('height'), ih)
        if w <= 0 or h <= 0:
            return
        name = self.resources.image(im)
        gs = self.resources.extgstate(style.opacity, style.opacity)
        fade = f'/{gs} gs ' if gs else ''
        # Samples are top-to-bottom. User space is y-down, so the flip
        # puts the first row at the top of the image box.
        self.out.append(
            f'q {fade}{fmt(w)} 0 0 {fmt(-h)} {fmt(x)} {fmt(y + h)} cm /{name} Do Q\n')

    def emit(self, path, style):
        if not path:
            return
        fill = style.fill
        stroke = None if style.stroke_width <= 0 else style.stroke
        if fill is None and stroke is None:
            return
        even = style.fill_rule == 'evenodd'
        if fill and stroke:
            op = 'B*' if even else 'B'
        elif fill:
            op = 'f*' if even else 'f'
        else:
            op = 'S'
        chunks = ['q']
        gs = self.resources.extgstate(
            style.fill_opacity * style.opacity, style.stroke_opacity * style.opacity)
        if gs:
            chunks.append(f'/{gs} gs')
        if fill:
            chunks.append(f'{fmt(fill[0])} {fmt(fill[1])} {fmt(fill[2])} rg')
        if stroke:
            chunks.append(f'{fmt(stroke[0])} {fmt(stroke[1])} {fmt(stroke[2])} RG')
            chunks.append(stroke_setup(style))
        chunks.append(path)
        chunks.append(op + ' Q\n')
        self.out.append(' '.join(chunks))


def stroke_setup(style):
    cap = {'butt': 0, 'round': 1, 'square': 2}.get(style.linecap, 0)
    join = {'miter': 0, 'round': 1, 'bevel': 2}.get(style.linejoin, 0)
    bits = [f'{fmt(style.stroke_width)} w {cap} J {join} j {fmt(style.miterlimit)} M']
    if style.dash:
        bits.append('[' + ' '.join(fmt(v) for v in style.dash) + f'] {fmt(style.dash_offset)} d')
    return ' '.join(bits)


def derive(parent, elem):
    style = parent.copy()
    group = parent.opacity
    style.opacity = 1.0
    attrs = {}
    for key, val in elem.attrib.items():
        key = local(key)
        if key in _STYLE_KEYS:
            attrs[key] = val
    raw = elem.get('style')
    if raw:
        for part in raw.split(';'):
            if ':' not in part:
                continue
            k, v = part.split(':', 1)
            attrs[k.strip()] = v.replace('!important', '').strip()
    if attrs.get('display', '').strip() == 'none' or attrs.get('visibility', '').strip() == 'hidden':
        style.display = False
        return style
    if 'color' in attrs:
        got = paint_value(attrs['color'], style)
        if got not in (None, _INHERIT) and got[0] is not None:
            style.color = got[0]
    if 'fill' in attrs:
        got = paint_value(attrs['fill'], style)
        if got is not _INHERIT:
            style.fill = got[0]
            if got[1] is not None:
                style.fill_opacity *= got[1]
    if 'stroke' in attrs:
        got = paint_value(attrs['stroke'], style)
        if got is not _INHERIT:
            style.stroke = got[0]
            if got[1] is not None:
                style.stroke_opacity *= got[1]
    if 'stroke-width' in attrs and attrs['stroke-width'].strip() != 'inherit':
        style.stroke_width = length(attrs['stroke-width'], style.stroke_width)
    if 'stroke-linecap' in attrs and attrs['stroke-linecap'].strip() != 'inherit':
        style.linecap = attrs['stroke-linecap'].strip()
    if 'stroke-linejoin' in attrs and attrs['stroke-linejoin'].strip() != 'inherit':
        style.linejoin = attrs['stroke-linejoin'].strip()
    if 'stroke-miterlimit' in attrs and attrs['stroke-miterlimit'].strip() != 'inherit':
        style.miterlimit = float(attrs['stroke-miterlimit'])
    if 'stroke-dasharray' in attrs and attrs['stroke-dasharray'].strip() not in ('inherit',):
        style.dash = dashes(attrs['stroke-dasharray'])
    if 'stroke-dashoffset' in attrs and attrs['stroke-dashoffset'].strip() != 'inherit':
        style.dash_offset = length(attrs['stroke-dashoffset'], 0)
    if 'fill-rule' in attrs and attrs['fill-rule'].strip() != 'inherit':
        style.fill_rule = attrs['fill-rule'].strip()
    if 'fill-opacity' in attrs and attrs['fill-opacity'].strip() != 'inherit':
        style.fill_opacity = unit(attrs['fill-opacity'])
    if 'stroke-opacity' in attrs and attrs['stroke-opacity'].strip() != 'inherit':
        style.stroke_opacity = unit(attrs['stroke-opacity'])
    if 'opacity' in attrs and attrs['opacity'].strip() != 'inherit':
        style.opacity = unit(attrs['opacity'])
    style.opacity *= group
    return style


_INHERIT = object()


def paint_value(value, style):
    value = value.strip()
    if value == 'inherit':
        return _INHERIT
    if value in ('none', 'transparent'):
        return None, None
    if value == 'currentColor':
        return style.color, None
    if value.startswith('url('):
        return (0, 0, 0), None
    return parse_color(value)


def parse_color(value):
    value = value.strip()
    named = _COLORS.get(value.lower())
    if named:
        return named, None
    if value.startswith('#'):
        h = value[1:]
        if len(h) in (3, 4):
            h = ''.join(c * 2 for c in h)
        if len(h) not in (6, 8):
            raise LabelError(f'svg colour {value!r} is not one this tool draws')
        n = int(h, 16)
        if len(h) == 8:
            rgb = ((n >> 24) & 255) / 255, ((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255
            return rgb, (n & 255) / 255
        rgb = ((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255
        return rgb, None
    m = re.fullmatch(r'rgba?\(\s*([^)]+)\)', value)
    if m:
        bits = [v for v in re.split(r'[\s,]+', m.group(1).strip()) if v]
        if len(bits) not in (3, 4):
            raise LabelError(f'svg colour {value!r} is not one this tool draws')
        rgb = []
        for v in bits[:3]:
            rgb.append(float(v[:-1]) / 100 if v.endswith('%') else float(v) / 255)
        alpha = unit(bits[3]) if len(bits) == 4 else None
        return tuple(rgb), alpha
    raise LabelError(f'svg colour {value!r} is not one this tool draws')


def unit(value):
    value = value.strip()
    if value.endswith('%'):
        return float(value[:-1]) / 100
    return float(value)


def dashes(value):
    if value.strip() == 'none':
        return None
    nums = [float(v) for v in _NUM.findall(value)]
    return nums or None


def pairs(text):
    nums = [float(v) for v in _NUM.findall(text)]
    return list(zip(nums[0::2], nums[1::2]))


def parse_transform(text):
    m = (1, 0, 0, 1, 0, 0)
    for name, args in _TF.findall(text):
        nums = [float(v) for v in _NUM.findall(args)]
        m = mul(m, transform(name, nums))
    return m


def transform(name, nums):
    if name == 'matrix' and len(nums) == 6:
        return tuple(nums)
    if name == 'translate':
        x = nums[0] if nums else 0
        y = nums[1] if len(nums) > 1 else 0
        return (1, 0, 0, 1, x, y)
    if name == 'scale':
        x = nums[0] if nums else 1
        y = nums[1] if len(nums) > 1 else x
        return (x, 0, 0, y, 0, 0)
    if name == 'rotate':
        ang = math.radians(nums[0] if nums else 0)
        cos, sin = math.cos(ang), math.sin(ang)
        rot = (cos, sin, -sin, cos, 0, 0)
        if len(nums) >= 3:
            return mul(mul((1, 0, 0, 1, nums[1], nums[2]), rot),
                       (1, 0, 0, 1, -nums[1], -nums[2]))
        return rot
    if name == 'skewX' and nums:
        return (1, 0, math.tan(math.radians(nums[0])), 1, 0, 0)
    if name == 'skewY' and nums:
        return (1, math.tan(math.radians(nums[0])), 0, 1, 0, 0)
    raise LabelError(f'svg transform {name} is not one this tool draws')


def mul(m1, m2):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


class Path:
    def __init__(self):
        self.ops = []

    def move(self, x, y):
        self.ops.append(f'{fmt(x)} {fmt(y)} m')

    def line(self, x, y):
        self.ops.append(f'{fmt(x)} {fmt(y)} l')

    def cubic(self, c1x, c1y, c2x, c2y, x, y):
        self.ops.append(
            f'{fmt(c1x)} {fmt(c1y)} {fmt(c2x)} {fmt(c2y)} {fmt(x)} {fmt(y)} c')

    def close(self):
        self.ops.append('h')

    def text(self):
        return ' '.join(self.ops)


def compile_path(d):
    tokens = lex_path(d)
    p = Path()
    i = 0
    cmd = None
    cx = cy = sx = sy = 0.0
    last_c = None
    last_q = None

    def take(n):
        nonlocal i
        got = []
        for _ in range(n):
            if i >= len(tokens) or isinstance(tokens[i], str):
                raise ValueError(f'path is short a number near {d[:48]!r}')
            got.append(tokens[i])
            i += 1
        return got

    while i < len(tokens):
        tok = tokens[i]
        if isinstance(tok, str):
            cmd = tok
            i += 1
        elif cmd is None:
            raise ValueError('path has no command')
        elif cmd in 'Zz':
            raise ValueError('path has a number after Z')
        elif cmd == 'M':
            cmd = 'L'
        elif cmd == 'm':
            cmd = 'l'

        if cmd in 'Zz':
            p.close()
            cx, cy = sx, sy
            last_c = last_q = None
            continue

        rel = cmd.islower()
        kind = cmd.upper()
        if kind == 'M':
            x, y = take(2)
            if rel:
                x, y = cx + x, cy + y
            p.move(x, y)
            cx = sx = x
            cy = sy = y
            last_c = last_q = None
        elif kind == 'L':
            x, y = take(2)
            if rel:
                x, y = cx + x, cy + y
            p.line(x, y)
            cx, cy = x, y
            last_c = last_q = None
        elif kind == 'H':
            (x,) = take(1)
            if rel:
                x += cx
            p.line(x, cy)
            cx = x
            last_c = last_q = None
        elif kind == 'V':
            (y,) = take(1)
            if rel:
                y += cy
            p.line(cx, y)
            cy = y
            last_c = last_q = None
        elif kind == 'C':
            x1, y1, x2, y2, x, y = take(6)
            if rel:
                x1, y1, x2, y2, x, y = cx + x1, cy + y1, cx + x2, cy + y2, cx + x, cy + y
            p.cubic(x1, y1, x2, y2, x, y)
            last_c = (x2, y2)
            last_q = None
            cx, cy = x, y
        elif kind == 'S':
            x2, y2, x, y = take(4)
            if rel:
                x2, y2, x, y = cx + x2, cy + y2, cx + x, cy + y
            if last_c is None:
                x1, y1 = cx, cy
            else:
                x1, y1 = 2 * cx - last_c[0], 2 * cy - last_c[1]
            p.cubic(x1, y1, x2, y2, x, y)
            last_c = (x2, y2)
            last_q = None
            cx, cy = x, y
        elif kind == 'Q':
            qx, qy, x, y = take(4)
            if rel:
                qx, qy, x, y = cx + qx, cy + qy, cx + x, cy + y
            p.cubic(cx + 2 / 3 * (qx - cx), cy + 2 / 3 * (qy - cy),
                    x + 2 / 3 * (qx - x), y + 2 / 3 * (qy - y), x, y)
            last_q = (qx, qy)
            last_c = None
            cx, cy = x, y
        elif kind == 'T':
            x, y = take(2)
            if rel:
                x, y = cx + x, cy + y
            if last_q is None:
                qx, qy = cx, cy
            else:
                qx, qy = 2 * cx - last_q[0], 2 * cy - last_q[1]
            p.cubic(cx + 2 / 3 * (qx - cx), cy + 2 / 3 * (qy - cy),
                    x + 2 / 3 * (qx - x), y + 2 / 3 * (qy - y), x, y)
            last_q = (qx, qy)
            last_c = None
            cx, cy = x, y
        elif kind == 'A':
            rx, ry, phi, fa, fs, x, y = take(7)
            if rel:
                x, y = cx + x, cy + y
            for cubic in arc_cubics(cx, cy, rx, ry, phi, fa, fs, x, y):
                if len(cubic) == 2:
                    p.line(*cubic)
                else:
                    p.cubic(*cubic)
            last_c = last_q = None
            cx, cy = x, y
        else:
            raise ValueError(f'path command {cmd} is not one this tool draws')
    return p


def lex_path(d):
    i, n = 0, len(d)
    out = []
    while i < n:
        c = d[i]
        if c in ' \t\r\n,':
            i += 1
            continue
        if c.isalpha():
            out.append(c)
            i += 1
            continue
        m = _NUM.match(d, i)
        if not m:
            raise ValueError(f'bad path data near {d[max(0, i - 2):i + 12]!r}')
        out.append(float(m.group()))
        i = m.end()
    return out


def arc_cubics(x1, y1, rx, ry, phi, fa, fs, x2, y2):
    if math.hypot(x2 - x1, y2 - y1) < 1e-9:
        return []
    if abs(rx) < 1e-9 or abs(ry) < 1e-9:
        return [(x2, y2)]
    phi = math.radians(phi % 360)
    rx, ry = abs(rx), abs(ry)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p = cos_p * dx + sin_p * dy
    y1p = -sin_p * dx + cos_p * dy
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx *= s
        ry *= s
    sign = 1 if bool(fa) != bool(fs) else -1
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = sign * math.sqrt(max(0.0, num) / den) if den else 0
    cxp = coef * rx * y1p / ry
    cyp = coef * -ry * x1p / rx
    cx = cos_p * cxp - sin_p * cyp + (x1 + x2) / 2
    cy = sin_p * cxp + cos_p * cyp + (y1 + y2) / 2

    def ang(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        nrm = math.hypot(ux, uy) * math.hypot(vx, vy)
        a = math.acos(max(-1.0, min(1.0, dot / nrm))) if nrm else 0
        if ux * vy - uy * vx < 0:
            a = -a
        return a

    theta = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    delta = ang((x1p - cxp) / rx, (y1p - cyp) / ry,
                (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    sweep = bool(fs)
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi
    nseg = max(1, int(math.ceil(abs(delta) / (math.pi / 2) - 1e-9)))
    step = delta / nseg

    def on_ellipse(xu, yu):
        return (cos_p * rx * xu - sin_p * ry * yu + cx,
                sin_p * rx * xu + cos_p * ry * yu + cy)

    cubics = []
    for i in range(nseg):
        t1 = theta + i * step
        t2 = t1 + step
        off = (4 / 3) * math.tan(step / 4)
        p0 = (math.cos(t1), math.sin(t1))
        p3 = (math.cos(t2), math.sin(t2))
        d0 = (-math.sin(t1), math.cos(t1))
        d3 = (-math.sin(t2), math.cos(t2))
        c1 = on_ellipse(p0[0] + d0[0] * off, p0[1] + d0[1] * off)
        c2 = on_ellipse(p3[0] - d3[0] * off, p3[1] - d3[1] * off)
        end = on_ellipse(*p3)
        cubics.append((*c1, *c2, *end))
    return cubics


def href_bytes(href, base_dir):
    if not href or not str(href).strip():
        raise LabelError('svg image has no href')
    href = str(href).strip()
    if href.startswith('data:'):
        head, _, data = href.partition(',')
        if ';base64' in head:
            return base64.b64decode(data)
        return urllib.parse.unquote_to_bytes(data)
    path = href if os.path.isabs(href) or not base_dir else os.path.join(base_dir, href)
    if not os.path.isfile(path):
        raise FileNotFoundError(f'svg image {href} was not found')
    with open(path, 'rb') as f:
        return f.read()
