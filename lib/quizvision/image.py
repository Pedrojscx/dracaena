"""Leitura de imagens PNG e PPM usando apenas a biblioteca padrão.

As capturas do grim e as imagens geradas pelo ImageMagick chegam como PNG
(8 bits por canal, sem entrelaçamento). Tudo que a análise visual precisa é
acesso a pixels RGB, então mantemos um decodificador pequeno e explícito.
"""

from __future__ import annotations

import hashlib
import shutil
import struct
import subprocess
import zlib
from dataclasses import dataclass
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class ImageError(ValueError):
    """Imagem ausente, corrompida ou em formato não suportado."""


@dataclass
class Image:
    width: int
    height: int
    data: bytearray  # RGB, 3 bytes por pixel, linha a linha

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        i = (y * self.width + x) * 3
        d = self.data
        return d[i], d[i + 1], d[i + 2]

    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def crop(self, x: int, y: int, w: int, h: int) -> "Image":
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.width, x + w), min(self.height, y + h)
        if x1 <= x0 or y1 <= y0:
            return Image(0, 0, bytearray())
        out = bytearray()
        for row in range(y0, y1):
            start = (row * self.width + x0) * 3
            out += self.data[start:start + (x1 - x0) * 3]
        return Image(x1 - x0, y1 - y0, out)

    def luminance(self, x: int, y: int) -> int:
        r, g, b = self.pixel(x, y)
        return (299 * r + 587 * g + 114 * b) // 1000

    def gray_grid(self, cols: int, rows: int) -> list[list[float]]:
        """Média de luminância em uma grade cols x rows (para hashes)."""
        grid = []
        for gy in range(rows):
            y0 = gy * self.height // rows
            y1 = max(y0 + 1, (gy + 1) * self.height // rows)
            line = []
            for gx in range(cols):
                x0 = gx * self.width // cols
                x1 = max(x0 + 1, (gx + 1) * self.width // cols)
                total = 0
                count = 0
                stepy = max(1, (y1 - y0) // 6)
                stepx = max(1, (x1 - x0) // 6)
                for yy in range(y0, y1, stepy):
                    for xx in range(x0, x1, stepx):
                        total += self.luminance(xx, yy)
                        count += 1
                line.append(total / count if count else 0.0)
            grid.append(line)
        return grid

    def dhash(self, size: int = 16) -> str:
        """Hash de diferença: estável a ruído leve, muda quando o layout muda."""
        if self.width == 0 or self.height == 0:
            return "0" * (size * size // 4)
        grid = self.gray_grid(size + 1, size)
        bits = 0
        for row in grid:
            for a, b in zip(row, row[1:]):
                bits = (bits << 1) | (1 if a > b else 0)
        return f"{bits:0{size * size // 4}x}"

    def sha1(self) -> str:
        return hashlib.sha1(bytes(self.data)).hexdigest()


def hamming_hex(a: str, b: str) -> int:
    if len(a) != len(b):
        return max(len(a), len(b)) * 4
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def load(path: str | Path) -> Image:
    p = Path(path)
    try:
        raw = p.read_bytes()
    except OSError as exc:
        raise ImageError(f"não foi possível ler {p}: {exc}") from exc
    if raw.startswith(PNG_SIGNATURE):
        fast = _png_via_magick(p)
        return fast if fast is not None else decode_png(raw)
    if raw[:2] in (b"P6", b"P5"):
        return decode_pnm(raw)
    raise ImageError(f"formato não suportado: {p}")


def _png_via_magick(path: Path) -> "Image | None":
    """Decodifica com o ImageMagick (C) para PPM de 8 bits: ~30x mais rápido
    que o decodificador em Python puro, que fica como reserva."""
    magick = shutil.which("magick")
    if not magick:
        return None
    try:
        proc = subprocess.run([magick, str(path), "-alpha", "off", "-depth", "8", "ppm:-"],
                              capture_output=True, timeout=30, check=True)
        return decode_pnm(proc.stdout)
    except (OSError, subprocess.SubprocessError, ImageError):
        return None


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unpack_bits(line: bytearray, depth: int, width: int, scale_gray: bool) -> bytearray:
    """Expande amostras de 1, 2 ou 4 bits para um byte cada."""
    per_byte = 8 // depth
    mask = (1 << depth) - 1
    factor = 255 // mask if scale_gray else 1
    out = bytearray(width)
    for i in range(width):
        byte = line[i // per_byte]
        shift = 8 - depth * (i % per_byte + 1)
        out[i] = ((byte >> shift) & mask) * factor
    return out


def decode_png(raw: bytes) -> Image:
    pos = len(PNG_SIGNATURE)
    width = height = 0
    bit_depth = color_type = interlace = -1
    palette = b""
    idat = bytearray()
    while pos + 8 <= len(raw):
        (length,) = struct.unpack(">I", raw[pos:pos + 4])
        ctype = raw[pos + 4:pos + 8]
        body = raw[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, _c, _f, interlace = struct.unpack(">IIBBBBB", body)
        elif ctype == b"PLTE":
            palette = body
        elif ctype == b"IDAT":
            idat += body
        elif ctype == b"IEND":
            break
    if width <= 0 or height <= 0:
        raise ImageError("PNG sem IHDR válido")
    if interlace != 0:
        raise ImageError("PNG entrelaçado não suportado")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise ImageError(f"tipo de cor PNG não suportado: {color_type}")
    allowed = (1, 2, 4, 8) if color_type == 3 else (1, 2, 4, 8, 16) if color_type == 0 else (8, 16)
    if bit_depth not in allowed:
        raise ImageError(f"PNG não suportado (tipo {color_type}, {bit_depth} bits)")
    try:
        inflated = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise ImageError(f"PNG corrompido: {exc}") from exc

    bpp = max(1, channels * bit_depth // 8)       # bytes por pixel (mín. 1) para os filtros
    stride = (width * channels * bit_depth + 7) // 8
    if len(inflated) < height * (stride + 1):
        raise ImageError("PNG truncado")
    prev = bytearray(stride)
    rgb = bytearray(width * height * 3)
    o = 0
    for y in range(height):
        base = y * (stride + 1)
        ftype = inflated[base]
        line = bytearray(inflated[base + 1:base + 1 + stride])
        if ftype == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                upleft = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(left, prev[i], upleft)) & 0xFF
        elif ftype != 0:
            raise ImageError(f"filtro PNG inválido: {ftype}")
        prev = line
        if bit_depth < 8:
            line = _unpack_bits(line, bit_depth, width, scale_gray=color_type == 0)
        elif bit_depth == 16:
            line = bytearray(((line[i] << 8 | line[i + 1]) * 255 + 32767) // 65535 for i in range(0, len(line), 2))
        if color_type == 2:
            rgb[o:o + width * 3] = line
        elif color_type == 6:
            px = bytearray(width * 3)
            px[0::3] = line[0::4]
            px[1::3] = line[1::4]
            px[2::3] = line[2::4]
            rgb[o:o + width * 3] = px
        elif color_type == 0:
            px = bytearray(width * 3)
            px[0::3] = line
            px[1::3] = line
            px[2::3] = line
            rgb[o:o + width * 3] = px
        elif color_type == 4:
            gray = line[0::2]
            px = bytearray(width * 3)
            px[0::3] = gray
            px[1::3] = gray
            px[2::3] = gray
            rgb[o:o + width * 3] = px
        else:  # paleta
            px = bytearray(width * 3)
            for i, idx in enumerate(line):
                px[i * 3:i * 3 + 3] = palette[idx * 3:idx * 3 + 3]
            rgb[o:o + width * 3] = px
        o += width * 3
    return Image(width, height, rgb)


def decode_pnm(raw: bytes) -> Image:
    magic = raw[:2]
    fields: list[bytes] = []
    pos = 2
    while len(fields) < 3:
        while pos < len(raw) and raw[pos:pos + 1].isspace():
            pos += 1
        if raw[pos:pos + 1] == b"#":
            while pos < len(raw) and raw[pos:pos + 1] != b"\n":
                pos += 1
            continue
        start = pos
        while pos < len(raw) and not raw[pos:pos + 1].isspace():
            pos += 1
        fields.append(raw[start:pos])
    pos += 1
    try:
        width, height, maxval = (int(f) for f in fields)
    except ValueError as exc:
        raise ImageError("cabeçalho PNM inválido") from exc
    if not 0 < maxval <= 65535:
        raise ImageError("PNM com valor máximo inválido")
    channels = 3 if magic == b"P6" else 1
    width_bytes = 2 if maxval > 255 else 1
    count = width * height * channels
    body = raw[pos:pos + count * width_bytes]
    if len(body) < count * width_bytes:
        raise ImageError("PNM truncado")
    if width_bytes == 2:
        samples = bytearray((((body[i] << 8) | body[i + 1]) * 255 // maxval) for i in range(0, len(body), 2))
    elif maxval != 255:
        samples = bytearray(v * 255 // maxval for v in body)
    else:
        samples = bytearray(body)
    if channels == 3:
        return Image(width, height, samples)
    rgb = bytearray(width * height * 3)
    rgb[0::3] = samples
    rgb[1::3] = samples
    rgb[2::3] = samples
    return Image(width, height, rgb)
