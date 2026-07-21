#!/usr/bin/env python3
"""Generate a few icon concept drafts for review -- flat, minimal,
suckless-fitting. Not final art, just concrete shapes to react to.
Run: python3 make_icons.py (uses Pillow, already a Slate dependency).
"""
import math
from PIL import Image, ImageDraw

SIZE = 256
SLATE_GRAY = (74, 78, 84)  # a real stone-slate tone, not pure gray
SLATE_GRAY_DARK = (52, 55, 60)
CHALK = (240, 238, 232)
BLACK_BAR = (18, 18, 18)
PAPER = (250, 249, 246)


def new_canvas():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def rounded_rect(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def icon_a_chalk_line():
    """A slate tile with one confident chalk mark -- simplest possible,
    literally 'a slate'."""
    img, d = new_canvas()
    m = 18
    rounded_rect(d, (m, m, SIZE - m, SIZE - m), 28, SLATE_GRAY)
    # subtle top-left highlight for a little depth, still flat overall
    d.rounded_rectangle((m, m, SIZE - m, SIZE - m), radius=28, outline=SLATE_GRAY_DARK, width=3)
    # one confident chalk stroke, slightly imperfect (hand-drawn feel)
    d.line(
        [(70, 150), (110, 95), (150, 140), (190, 80)],
        fill=CHALK, width=14, joint="curve",
    )
    for pt in [(70, 150), (190, 80)]:
        d.ellipse((pt[0] - 7, pt[1] - 7, pt[0] + 7, pt[1] + 7), fill=CHALK)
    img.save("icon_a_chalk_line.png")


def icon_b_redaction_bar():
    """A page corner with a black redaction bar -- ties the icon
    directly to Slate's signature action. My pick."""
    img, d = new_canvas()
    m = 24
    page_box = (m + 20, m, SIZE - m, SIZE - m)
    fold = 46
    # page body with a folded corner (top-right)
    d.polygon(
        [
            (page_box[0], page_box[1]),
            (page_box[2] - fold, page_box[1]),
            (page_box[2], page_box[1] + fold),
            (page_box[2], page_box[3]),
            (page_box[0], page_box[3]),
        ],
        fill=PAPER,
    )
    d.polygon(
        [
            (page_box[2] - fold, page_box[1]),
            (page_box[2], page_box[1] + fold),
            (page_box[2] - fold, page_box[1] + fold),
        ],
        fill=(225, 222, 214),
    )
    d.line([(page_box[0], page_box[1]), (page_box[2] - fold, page_box[1])], fill=SLATE_GRAY_DARK, width=3)
    d.line([(page_box[2] - fold, page_box[1]), (page_box[2], page_box[1] + fold)], fill=SLATE_GRAY_DARK, width=3)
    d.line([(page_box[2], page_box[1] + fold), (page_box[2], page_box[3])], fill=SLATE_GRAY_DARK, width=3)
    d.line([(page_box[2], page_box[3]), (page_box[0], page_box[3])], fill=SLATE_GRAY_DARK, width=3)
    d.line([(page_box[0], page_box[3]), (page_box[0], page_box[1])], fill=SLATE_GRAY_DARK, width=3)
    # a couple of faint text lines above the redaction, for context
    for y in (108, 128):
        d.rounded_rectangle((page_box[0] + 22, y, page_box[2] - fold - 10, y + 10), 5, fill=(210, 207, 199))
    # the redaction bar itself -- the whole point
    d.rounded_rectangle((page_box[0] + 22, 152, page_box[2] - 30, 178), 4, fill=BLACK_BAR)
    img.save("icon_b_redaction_bar.png")


def icon_c_stone_hexagon():
    """A minimal flat stone/hexagon with a small page fold-corner cutout
    -- nods to Cairn's stone family without copying Cairn's own mark."""
    img, d = new_canvas()
    cx, cy, r = SIZE / 2, SIZE / 2, 108
    pts = []
    for i in range(6):
        angle = math.pi / 6 + i * math.pi / 3  # flat-top hexagon, rotated
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    d.polygon(pts, fill=SLATE_GRAY)
    d.polygon(pts, outline=SLATE_GRAY_DARK, width=3)
    # small page-fold cutout, bottom right, in chalk color
    fold_size = 46
    fx, fy = cx + 46, cy + 40
    d.polygon(
        [(fx, fy), (fx + fold_size, fy), (fx, fy + fold_size)],
        fill=CHALK,
    )
    img.save("icon_c_stone_hexagon.png")


if __name__ == "__main__":
    icon_a_chalk_line()
    icon_b_redaction_bar()
    icon_c_stone_hexagon()
    print("wrote icon_a_chalk_line.png, icon_b_redaction_bar.png, icon_c_stone_hexagon.png")
