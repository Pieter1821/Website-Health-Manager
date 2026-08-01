"""Build a multi-size Windows .ico from the WHM logo (shield-focused for desktop)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(__file__).resolve().parent / "logo-source.png"
OUT_ICO = Path(__file__).resolve().parent / "whm.ico"
WEB = ROOT / "src" / "whm" / "presentation" / "web"
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def is_bg(pixel: tuple[int, int, int, int]) -> bool:
    r, g, b, a = pixel
    if a < 10:
        return True
    return r > 245 and g > 245 and b > 245


def trim(img: Image.Image) -> Image.Image:
    px = img.load()
    w, h = img.size
    min_x, min_y, max_x, max_y = w, h, 0, 0
    found = False
    for y in range(h):
        for x in range(w):
            if not is_bg(px[x, y]):
                found = True
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    if not found:
        return img
    return img.crop((min_x, min_y, max_x + 1, max_y + 1))


def row_white_ratio(img: Image.Image, y: int) -> float:
    tw, _ = img.size
    step = max(1, tw // 80)
    row = [img.getpixel((x, y)) for x in range(0, tw, step)]
    return sum(1 for p in row if is_bg(p)) / len(row)


def find_text_separator(img: Image.Image) -> int:
    """Cut above the title — first sustained white band in the lower half."""
    _, th = img.size
    run_needed = max(8, th // 80)
    start = int(th * 0.55)
    y = start
    while y < int(th * 0.9):
        if row_white_ratio(img, y) < 0.96:
            y += 1
            continue
        end = y
        while end < th and row_white_ratio(img, end) >= 0.96:
            end += 1
        if end - y >= run_needed:
            return y
        y = end + 1
    return int(th * 0.72)


def with_white_bg(im: Image.Image) -> Image.Image:
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    bg.alpha_composite(im)
    return bg


def square_fit(im: Image.Image, fill: float = 0.94) -> Image.Image:
    """
    Place artwork on a square canvas so it fills most of the icon.

    Windows taskbar / Chrome app icons shrink tiny logos with heavy padding —
    keep only a thin margin (~3% each side at fill=0.94).
    """
    fill = min(0.98, max(0.7, fill))
    sw, sh = im.size
    # Scale so the longer side becomes `fill` of the final square.
    side = max(sw, sh)
    canvas_side = max(1, int(round(side / fill)))
    target = int(round(canvas_side * fill))
    scale = target / side
    nw, nh = max(1, int(round(sw * scale))), max(1, int(round(sh * scale)))
    scaled = im.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (canvas_side, canvas_side), (255, 255, 255, 0))
    canvas.paste(scaled, ((canvas_side - nw) // 2, (canvas_side - nh) // 2), scaled)
    return canvas


def main() -> None:
    img = Image.open(SRC).convert("RGBA")
    trimmed = trim(img)
    sep = find_text_separator(trimmed)
    tw, _ = trimmed.size
    shield = trim(trimmed.crop((0, 0, tw, sep)))
    # Slight extra trim after crop removes leftover white fringe.
    shield = trim(shield)
    # Fill almost the whole tile so taskbar / Chrome app icons read large.
    icon_master = with_white_bg(square_fit(shield, fill=0.97))

    # Normalize to 512² master so every ICO/PNG size scales cleanly.
    master_512 = icon_master.resize((512, 512), Image.Resampling.LANCZOS)
    master_256 = master_512.resize((256, 256), Image.Resampling.LANCZOS)
    master_256.save(OUT_ICO, format="ICO", sizes=SIZES)

    WEB.mkdir(parents=True, exist_ok=True)
    parent = Path(__file__).resolve().parent
    master_256.save(parent / "whm-icon-256.png")
    master_512.save(parent / "whm-icon-512.png")
    trimmed.save(parent / "logo-full.png")
    master_256.save(WEB / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
    master_512.resize((192, 192), Image.Resampling.LANCZOS).save(WEB / "icon-192.png")
    master_512.save(WEB / "icon-512.png")

    verify = Image.open(OUT_ICO)
    print(f"Wrote {OUT_ICO} ({OUT_ICO.stat().st_size} bytes)")
    print(f"Shield={shield.size} separator_y={sep} ico_entry={verify.size} sizes={verify.info.get('sizes')}")


if __name__ == "__main__":
    main()
