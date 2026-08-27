#!/usr/bin/env python3
"""Render a transparent PNG title card to overlay on the opening of the set.

ffmpeg's drawtext filter is not compiled into every build (Homebrew's is not,
as of ffmpeg 8.x), so text is rasterised here with Pillow and composited as an
image instead. That works on every ffmpeg.
"""
import argparse, os, sys

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def find_font(explicit=None):
    if explicit:
        return explicit
    for f in FONT_CANDIDATES:
        if os.path.exists(f):
            return f
    sys.exit("no usable font found; pass --font /path/to/font.ttf")


def main():
    from PIL import Image, ImageDraw, ImageFont
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--title", required=True)
    ap.add_argument("--artist", default="")
    ap.add_argument("--footer", default="", help="e.g. 'produced by NAME'")
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--font", default=None)
    a = ap.parse_args()

    font_path = find_font(a.font)
    W, H = a.width, a.height
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f1 = ImageFont.truetype(font_path, int(H * 0.115))
    f2 = ImageFont.truetype(font_path, int(H * 0.043))
    f3 = ImageFont.truetype(font_path, int(H * 0.023))

    def centre(text, font, y, fill):
        if not text:
            return
        box = d.textbbox((0, 0), text, font=font)
        d.text(((W - (box[2] - box[0])) // 2 - box[0], y), text, font=font, fill=fill)

    centre(a.title.upper(), f1, int(H * 0.36), (255, 255, 255, 255))
    d.rectangle([W // 2 - int(W * 0.10), H // 2 - 2,
                 W // 2 + int(W * 0.10), H // 2 + 1], fill=(120, 190, 255, 220))
    centre(a.artist.upper(), f2, int(H * 0.53), (232, 232, 255, 255))
    centre(a.footer, f3, int(H * 0.60), (159, 180, 216, 255))

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    img.save(a.out)
    print(f"{a.out}  {W}x{H}  font: {font_path}")


if __name__ == "__main__":
    main()
