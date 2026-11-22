"""Draw the Homeboard icon and logo (run with: python scripts/make_brand.py).

Needs Pillow (installed with Home Assistant). Output goes to
custom_components/homeboard/brand/, where Home Assistant 2026.3+ reads local brand images.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "custom_components" / "homeboard" / "brand"
SS = 4  # supersampling factor


def vertical_gradient(
    size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]
) -> Image.Image:
    base = Image.new("RGB", (size, size), top)
    px = base.load()
    for y in range(size):
        t = y / (size - 1)
        color = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        for x in range(size):
            px[x, y] = color
    return base


def card(
    draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float], radius: float, fill
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def draw_icon(size: int, dark: bool = False) -> Image.Image:
    s = size * SS
    top, bottom = (
        ((0x26, 0x32, 0x4A), (0x14, 0x1B, 0x2B))
        if dark
        else ((0x3A, 0x8D, 0xF5), (0x1C, 0x4F, 0xB3))
    )
    bg = vertical_gradient(s, top, bottom).convert("RGBA")
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=s * 0.22, fill=255)
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    img.paste(bg, (0, 0), mask)

    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))  # a separate layer so translucent fills blend
    d = ImageDraw.Draw(layer)
    pad, gap = s * 0.14, s * 0.045
    col_w = (s - 2 * pad - 2 * gap) / 3
    col_top, col_bottom = s * 0.2, s * 0.8
    for i in range(3):
        x0 = pad + i * (col_w + gap)
        card(d, (x0, col_top, x0 + col_w, col_bottom), s * 0.035, (255, 255, 255, 46))
    # cards in the columns: (column, row, height factor, accent)
    layout = [
        (0, 0, 1.0, False),
        (0, 1, 0.8, False),
        (0, 2, 1.0, False),
        (1, 0, 0.8, False),
        (2, 0, 1.0, True),
    ]
    inner = col_w * 0.12
    for col, row, factor, accent in layout:
        x0 = pad + col * (col_w + gap) + inner
        y0 = col_top + inner + row * s * 0.17
        h = s * 0.13 * factor
        fill = (255, 214, 102, 255) if accent else (255, 255, 255, 235)
        card(d, (x0, y0, x0 + col_w - 2 * inner, y0 + h), s * 0.022, fill)
        d.rounded_rectangle(
            (x0 + inner * 0.7, y0 + h * 0.3, x0 + col_w * 0.5, y0 + h * 0.3 + s * 0.016),
            radius=s,
            fill=(30, 70, 150, 120),
        )

    img = Image.alpha_composite(img, layer)

    # the card being dragged: lifted, tilted, with a soft shadow
    lift = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lift, "RGBA")
    cx, cy = pad + 1 * (col_w + gap) + col_w / 2, col_top + s * 0.27
    w, h = col_w * 0.98, s * 0.16
    ld.rounded_rectangle(
        (cx - w / 2, cy - h / 2 + s * 0.012, cx + w / 2, cy + h / 2 + s * 0.012),
        radius=s * 0.03,
        fill=(0, 0, 0, 90),
    )
    ld.rounded_rectangle(
        (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), radius=s * 0.03, fill=(255, 255, 255, 255)
    )
    ld.rounded_rectangle(
        (cx - w * 0.38, cy - h * 0.2, cx + w * 0.1, cy - h * 0.2 + s * 0.02),
        radius=s,
        fill=(28, 79, 179, 255),
    )
    ld.rounded_rectangle(
        (cx - w * 0.38, cy + h * 0.1, cx + w * 0.3, cy + h * 0.1 + s * 0.016),
        radius=s,
        fill=(28, 79, 179, 130),
    )
    lift = lift.rotate(-7, resample=Image.BICUBIC, center=(cx, cy))
    img = Image.alpha_composite(img, lift)
    return img.resize((size, size), Image.LANCZOS)


def draw_logo(height: int, dark: bool = False) -> Image.Image:
    icon = draw_icon(height, dark)
    font_path = next(
        (
            p
            for p in (
                "/System/Library/Fonts/HelveticaNeue.ttc",
                "/System/Library/Fonts/Helvetica.ttc",
                "/Library/Fonts/Arial.ttf",
            )
            if Path(p).exists()
        ),
        None,
    )
    font = (
        ImageFont.truetype(font_path, int(height * 0.5)) if font_path else ImageFont.load_default()
    )
    text = "Homeboard"
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    width = int(probe.textlength(text, font=font))
    out = Image.new(
        "RGBA", (height + int(height * 0.25) + width + int(height * 0.1), height), (0, 0, 0, 0)
    )
    out.paste(icon, (0, 0))
    ImageDraw.Draw(out).text(
        (height + height * 0.25, height / 2),
        text,
        font=font,
        anchor="lm",
        fill=(235, 240, 250, 255) if dark else (28, 50, 90, 255),
    )
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    draw_icon(256).save(OUT / "icon.png", optimize=True)
    draw_icon(512).save(OUT / "icon@2x.png", optimize=True)
    draw_icon(256, dark=True).save(OUT / "dark_icon.png", optimize=True)
    draw_icon(512, dark=True).save(OUT / "dark_icon@2x.png", optimize=True)
    draw_logo(128).save(OUT / "logo.png", optimize=True)
    draw_logo(256).save(OUT / "logo@2x.png", optimize=True)
    draw_logo(128, dark=True).save(OUT / "dark_logo.png", optimize=True)
    draw_logo(256, dark=True).save(OUT / "dark_logo@2x.png", optimize=True)
    print("wrote", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
