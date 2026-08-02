#!/usr/bin/env python3
"""Generates icon_b_redaction_bar.png, the real shipped window/taskbar
icon (loaded at runtime by slate.py's _set_window_icon, and the source
image for branding/slate.ico) -- flat, minimal, suckless-fitting.
Run: python3 make_icons.py (uses Pillow, already a Slate dependency).
"""
from PIL import Image, ImageDraw

SIZE = 256
SLATE_GRAY_DARK = (52, 55, 60)
BLACK_BAR = (18, 18, 18)
PAPER = (250, 249, 246)


def icon_b_redaction_bar():
    """A page corner with a black redaction bar -- ties the icon
    directly to Slate's signature action."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
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


if __name__ == "__main__":
    icon_b_redaction_bar()
    print("wrote icon_b_redaction_bar.png")
