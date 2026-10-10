"""Original Minutes walkthrough: reproducible Pillow artwork + FFmpeg encoding.

No reference video frames or third-party artwork are used. Three chapters have
exact eight-second boundaries so the site's accessible controls can seek them.
Requires Pillow and imageio-ffmpeg; run from any working directory.
"""

from __future__ import annotations

import argparse
import math
from functools import lru_cache
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "apps/web/public/media"
REVIEW = ROOT / ".video-work"
FONTS = ROOT / "apps/web/public/fonts"
W, H, FPS, DURATION = 1200, 900, 30, 24
INK = "#172239"
MUTED = "#69758B"
BLUE = "#3155ED"
PALE = "#EFF3FF"
BORDER = "#E2E7F1"


@lru_cache(maxsize=40)
def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / ("manrope-semibold.ttf" if bold else "manrope-regular.ttf")), size)


def ease(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return 1 - (1 - value) ** 3


def progress(t: float, start: float, duration: float = 0.6) -> float:
    return ease((t - start) / duration)


def text(draw: ImageDraw.ImageDraw, xy: tuple[float, float], value: str, size: int = 30,
         color: str = INK, bold: bool = False, spacing: int = 11) -> None:
    for index, line in enumerate(value.split("\n")):
        draw.text((xy[0], xy[1] + index * (size + spacing)), line,
                  font=font(size, bold), fill=color, stroke_width=0, anchor="lt")


def roundrect(draw: ImageDraw.ImageDraw, box: tuple, radius: int = 20,
              fill: str = "white", outline: str | None = None, width: int = 1) -> None:
    draw.rounded_rectangle(tuple(round(x) for x in box), radius, fill=fill, outline=outline, width=width)


@lru_cache(maxsize=25)
def panel(size: tuple[int, int], radius: int = 24) -> Image.Image:
    w, h = size
    image = Image.new("RGBA", (w + 100, h + 110))
    shadow = Image.new("RGBA", image.size)
    ImageDraw.Draw(shadow).rounded_rectangle((50, 57, w + 50, h + 57), radius,
                                             fill=(37, 64, 116, 22))
    image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(20)))
    ImageDraw.Draw(image).rounded_rectangle((50, 40, w + 50, h + 40), radius,
                                            fill="white", outline=BORDER, width=2)
    return image


def card(image: Image.Image, x: float, y: float, w: int, h: int,
         opacity: float = 1, radius: int = 24) -> None:
    surface = panel((w, h), radius)
    if opacity < 1:
        surface = surface.copy()
        surface.putalpha(surface.getchannel("A").point(lambda a: int(a * opacity)))
    image.alpha_composite(surface, (round(x - 50), round(y - 40)))


def add_layer(image: Image.Image, layer: Image.Image, opacity: float = 1,
              offset: tuple[int, int] = (0, 0)) -> None:
    if opacity <= 0:
        return
    if opacity < 1:
        layer = layer.copy()
        layer.putalpha(layer.getchannel("A").point(lambda a: int(a * opacity)))
    image.alpha_composite(layer, offset)


def icon(draw: ImageDraw.ImageDraw, kind: str, x: float, y: float, color: str = BLUE,
         scale: float = 1) -> None:
    def p(a: float, b: float) -> tuple[float, float]:
        return x + a * scale, y + b * scale
    width = max(2, round(2.5 * scale))
    if kind == "mail":
        draw.rounded_rectangle((*p(1, 4), *p(27, 23)), radius=4, outline=color, width=width)
        draw.line([p(2, 6), p(14, 15), p(26, 6)], fill=color, width=width, joint="curve")
    elif kind == "mic":
        draw.rounded_rectangle((*p(10, 1), *p(19, 18)), radius=5, outline=color, width=width)
        draw.arc((*p(5, 6), *p(24, 24)), 0, 180, fill=color, width=width)
        draw.line([p(14.5, 23), p(14.5, 28)], fill=color, width=width)
        draw.line([p(9, 28), p(20, 28)], fill=color, width=width)
    elif kind == "check":
        draw.line([p(3, 14), p(11, 22), p(26, 5)], fill=color, width=width + 1, joint="curve")
    elif kind == "arrow":
        draw.line([p(2, 14), p(26, 14)], fill=color, width=width)
        draw.line([p(17, 5), p(26, 14), p(17, 23)], fill=color, width=width, joint="curve")
    elif kind == "search":
        draw.ellipse((*p(1, 1), *p(21, 21)), outline=color, width=width)
        draw.line([p(18, 18), p(28, 28)], fill=color, width=width)
    elif kind == "history":
        draw.arc((*p(3, 3), *p(27, 27)), 200, 510, fill=color, width=width)
        draw.line([p(2, 3), p(2, 12), p(11, 12)], fill=color, width=width)
        draw.line([p(15, 8), p(15, 15), p(21, 18)], fill=color, width=width)
    elif kind == "link":
        for a, b in [(0, 8), (12, 0)]:
            draw.rounded_rectangle((*p(a, b), *p(a + 15, b + 18)), radius=6,
                                   outline=color, width=width)


def logo(draw: ImageDraw.ImageDraw, x: float, y: float, size: int = 42) -> None:
    roundrect(draw, (x, y, x + size, y + size), 12, BLUE)
    cell, gap = size * 0.14, size * 0.075
    for row in range(3):
        for col in range(3):
            alpha = "#FFFFFF" if (row + col) % 3 else "#AFC0FF"
            cx, cy = x + size * .21 + col * (cell + gap), y + size * .21 + row * (cell + gap)
            roundrect(draw, (cx, cy, cx + cell, cy + cell), 2, alpha)


def pill(draw: ImageDraw.ImageDraw, x: float, y: float, label: str, kind: str | None = None,
         fill: str = PALE, color: str = BLUE, size: int = 24) -> int:
    width = round(draw.textlength(label, font=font(size))) + (64 if kind else 36)
    roundrect(draw, (x, y, x + width, y + 48), 24, fill)
    if kind:
        icon(draw, kind, x + 16, y + 10, color, .85)
    text(draw, (x + (48 if kind else 18), y + 13), label, size, color)
    return width


def cursor(image: Image.Image, x: float, y: float, opacity: float = 1) -> None:
    layer = Image.new("RGBA", (W, H))
    draw = ImageDraw.Draw(layer)
    pts = [(x, y), (x + 6, y + 34), (x + 15, y + 24), (x + 29, y + 21)]
    draw.polygon(pts, fill=BLUE)
    draw.line(pts + [pts[0]], fill="white", width=3, joint="curve")
    add_layer(image, layer, opacity)


def base_background() -> Image.Image:
    image = Image.new("RGBA", (W, H), "#F8FAFF")
    ambient = Image.new("RGBA", (W, H))
    draw = ImageDraw.Draw(ambient)
    draw.ellipse((260, 290, 1530, 1190), fill=(114, 148, 244, 32))
    draw.ellipse((-320, 480, 720, 1210), fill=(132, 164, 255, 18))
    image.alpha_composite(ambient.filter(ImageFilter.GaussianBlur(105)))
    return image


BASE = base_background()


def background(t: float) -> Image.Image:
    image = BASE.copy()
    lines = Image.new("RGBA", (W, H))
    draw = ImageDraw.Draw(lines)
    for row in range(36):
        points = []
        for x in range(-10, W + 11, 12):
            y = 445 + row * 17 + math.sin(x / 280 + t * .095) * (52 + row * .9)
            y += math.sin(x / 640 - t * .06) * 70
            points.append((x, y))
        draw.line(points, fill=(93, 124, 199, 18), width=1)
    for col in range(58):
        points = []
        for row in range(36):
            x = col * 24 - 80 + row * 2.1
            y = 445 + row * 17 + math.sin(x / 280 + t * .095) * (52 + row * .9)
            y += math.sin(x / 640 - t * .06) * 70
            points.append((x, y))
        draw.line(points, fill=(93, 124, 199, 11), width=1)
    image.alpha_composite(lines)
    draw = ImageDraw.Draw(image)
    logo(draw, 67, 55, 40)
    text(draw, (120, 62), "minutes", 28, INK, True)
    text(draw, (67, 839), "Illustrative walkthrough", 21, MUTED)
    return image


def source_card(title: str, kind: str, quote: str, detail: str, size: tuple[int, int],
                typed: float = 1) -> Image.Image:
    w, h = size
    layer = Image.new("RGBA", (W, H))
    card(layer, 0, 0, w, h)
    draw = ImageDraw.Draw(layer)
    roundrect(draw, (30, 28, 82, 80), 14, PALE)
    icon(draw, kind, 42, 39)
    text(draw, (99, 31), title, 30, INK, True)
    text(draw, (99, 68), "Meeting" if kind == "mic" else "Email", 21, MUTED)
    typed_quote = quote[: max(0, round(len(quote) * typed))]
    text(draw, (32, 115), typed_quote, 35, INK, False, 12)
    if 0 < typed < 1:
        split = typed_quote.split("\n")
        cx = 32 + draw.textlength(split[-1], font=font(35)) + 4
        cy = 115 + (len(split) - 1) * 48
        draw.line((cx, cy, cx, cy + 34), fill=BLUE, width=2)
    draw.line((32, h - 62, w - 32, h - 62), fill=BORDER, width=1)
    text(draw, (32, h - 41), detail, 22, MUTED)
    return layer


def capture(t: float) -> Image.Image:
    layer = Image.new("RGBA", (W, H))
    intro = progress(t, 0, .6)
    first_y = 220 - 70 * progress(t, 2.8, .8)
    first = source_card("Product kickoff", "mic", "Let's target September 24\nfor the UPI launch.",
                        "Priya · Product team", (820, 300), max(.3, progress(t, .25, 2.2)))
    add_layer(layer, first, 1, (148, round(first_y + 9 * (1 - intro))))
    second_p = progress(t, 2.9, .8)
    if second_p:
        second = source_card("Payments follow-up", "mail", "Sandbox access is delayed.\nMove the launch to September 28.",
                             "Payments team · Follow-up email", (864, 300), progress(t, 3.3, 2.1))
        add_layer(layer, second, second_p, (207, round(452 + 38 * (1 - second_p))))
    status = Image.new("RGBA", (W, H))
    draw = ImageDraw.Draw(status)
    pill(draw, 758, 786, "2 sources captured", "check", fill="#E9EFFF", size=23)
    add_layer(layer, status, progress(t, 5.5))
    if .8 < t < 3.3:
        cp = progress(t, .8, 1.6)
        cursor(layer, 892 - cp * 98, 403 - cp * 11, min(progress(t, .8, .3), 1 - progress(t, 2.7, .6)))
    return layer


def source_chip(image: Image.Image, x: int, y: int, label: str, kind: str, width: int) -> None:
    card(image, x, y, width, 84, radius=18)
    draw = ImageDraw.Draw(image)
    icon(draw, kind, x + 24, y + 28)
    text(draw, (x + 67, y + 28), label, 26, INK, True)


def connect(t: float) -> Image.Image:
    layer = Image.new("RGBA", (W, H))
    draw = ImageDraw.Draw(layer)
    p = progress(t, .45, 1.15)
    for sx, ex in [(330, 460), (869, 744)]:
        points = []
        for i in range(round(60 * p) + 1):
            u = i / 60
            x = sx + (ex - sx) * (3 * u * u - 2 * u * u * u)
            y = 277 + u * 81
            points.append((x, y))
        if len(points) > 1:
            draw.line(points, fill="#ADC0FF", width=3)
            x, y = points[-1]
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=BLUE)
    source_chip(layer, 133, 180, "Product kickoff", "mic", 396)
    source_chip(layer, 659, 180, "Payments follow-up", "mail", 409)
    surface = Image.new("RGBA", (W, H))
    cy = round(355 + 23 * (1 - progress(t, .7, .6)))
    card(surface, 149, cy, 902, 399)
    sd = ImageDraw.Draw(surface)
    icon(sd, "link", 181, cy + 30)
    text(sd, (225, cy + 30), "UPI launch", 30, INK, True)
    pill(sd, 808, cy + 24, "Decision", fill="#F2F5FA", color=MUTED, size=23)
    sd.line((181, cy + 87, 1019, cy + 87), fill=BORDER, width=1)
    old_opacity = 1 - progress(t, 2.1, .45)
    if old_opacity > 0:
        old = Image.new("RGBA", (W, H))
        od = ImageDraw.Draw(old)
        text(od, (190, cy + 119), "Launch date", 24, MUTED)
        text(od, (185, cy + 166), "September 24", 70, INK, True)
        add_layer(surface, old, old_opacity)
    new = Image.new("RGBA", (W, H))
    nd = ImageDraw.Draw(new)
    text(nd, (191, cy + 117), "Current decision", 24, MUTED)
    text(nd, (185, cy + 162), "September 28", 70, BLUE, True)
    add_layer(surface, new, progress(t, 2.1, .5))
    history = Image.new("RGBA", (W, H))
    hd = ImageDraw.Draw(history)
    text(hd, (191, cy + 264), "Earlier decision", 23, MUTED)
    text(hd, (396, cy + 261), "September 24", 27, MUTED)
    icon(hd, "arrow", 599, cy + 259, "#98A7C4", .85)
    text(hd, (640, cy + 261), "September 28", 27, BLUE)
    hd.line((181, cy + 319, 1019, cy + 319), fill=BORDER, width=1)
    icon(hd, "history", 190, cy + 344, BLUE, .8)
    text(hd, (226, cy + 344), "2 sources · History preserved", 23, MUTED)
    add_layer(surface, history, progress(t, 3.0, .7))
    add_layer(layer, surface, progress(t, .7, .6))
    status = Image.new("RGBA", (W, H))
    pill(ImageDraw.Draw(status), 428, 786, "Context connected", "check", size=23)
    add_layer(layer, status, progress(t, 4.2))
    return layer


def recall(t: float) -> Image.Image:
    layer = Image.new("RGBA", (W, H))
    card(layer, 119, 166, 962, 159)
    draw = ImageDraw.Draw(layer)
    icon(draw, "search", 151, 198, BLUE, .85)
    text(draw, (192, 199), "Ask Minutes", 24, MUTED)
    question = "When are we launching UPI, and why?"
    q = question[:round(len(question) * progress(t, .15, 1.85))]
    text(draw, (153, 255), q, 34, INK, True)
    if .15 < t < 2:
        cx = 155 + draw.textlength(q, font=font(34, True))
        draw.line((cx, 253, cx, 289), fill=BLUE, width=2)
    p = progress(t, 2.0, .65)
    if p > 0:
        response = Image.new("RGBA", (W, H))
        y = round(352 + 24 * (1 - p))
        card(response, 119, y, 962, 379)
        rd = ImageDraw.Draw(response)
        logo(rd, 151, y + 30, 37)
        text(rd, (204, y + 35), "From your company memory", 24, MUTED)
        text(rd, (152, y + 97), "September 28.", 56, BLUE, True)
        text(rd, (154, y + 179), "Sandbox access was delayed,\nso the launch date moved.", 34, INK, spacing=12)
        chips = Image.new("RGBA", (W, H))
        cd = ImageDraw.Draw(chips)
        w1 = pill(cd, 154, y + 298, "1  Product kickoff", fill=PALE, size=24)
        pill(cd, 170 + w1, y + 298, "2  Payments follow-up", fill=PALE, size=24)
        add_layer(response, chips, progress(t, 3.7, .6))
        add_layer(layer, response, p)
    followup = Image.new("RGBA", (W, H))
    fd = ImageDraw.Draw(followup)
    roundrect(fd, (143, 754, 1057, 809), 16, "#EAF0FF")
    icon(fd, "history", 165, 768, BLUE, .8)
    text(fd, (204, 771), "Release handoff · Needs Rahul's review", 25, INK)
    add_layer(layer, followup, progress(t, 5.25, .65))
    return layer


SCENES = (capture, connect, recall)


def frame(t: float) -> Image.Image:
    image = background(t)
    chapter = min(2, int(t // 8))
    local = t - chapter * 8
    current = SCENES[chapter](local)
    if chapter and local < .45:
        add_layer(image, SCENES[chapter - 1](7.99), 1 - progress(local, 0, .45))
        add_layer(image, current, progress(local, 0, .45))
    else:
        add_layer(image, current)
    # The final 0.45s resets into Capture without a flash or black frame.
    if t > DURATION - .45:
        image = Image.blend(image, frame(0).convert("RGBA"), progress(t, DURATION - .45, .45))
    return image.convert("RGB")


def review_stills() -> None:
    MEDIA.mkdir(parents=True, exist_ok=True)
    REVIEW.mkdir(parents=True, exist_ok=True)
    samples = [("capture", 6.6), ("connect", 13.5), ("recall", 22.5)]
    sheet = Image.new("RGB", (1800, 500), "white")
    sd = ImageDraw.Draw(sheet)
    for index, (name, time) in enumerate(samples):
        still = frame(time)
        still.save(REVIEW / f"minutes-{name}.jpg", quality=94)
        sheet.paste(still.resize((600, 450), Image.Resampling.LANCZOS), (index * 600, 50))
        text(sd, (index * 600 + 24, 15), f"0{index + 1}  {name.capitalize()} · {time:g}s", 23, INK, True)
    sheet.save(REVIEW / "minutes-walkthrough-contact-sheet.jpg", quality=94)
    frame(6.6).save(MEDIA / "minutes-walkthrough-poster.jpg", quality=91, optimize=True)
    print(f"Review frames: {REVIEW}", flush=True)


def render() -> None:
    import imageio_ffmpeg
    target = MEDIA / "minutes-walkthrough.mp4"
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-f", "rawvideo", "-vcodec", "rawvideo",
               "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-an",
               "-c:v", "libx264", "-preset", "medium", "-crf", "24", "-pix_fmt", "yuv420p",
               "-movflags", "+faststart", "-g", "30", "-metadata",
               "title=Minutes - Capture, Connect, Recall", "-loglevel", "error", str(target)]
    proc = subprocess.Popen(command, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        for index in range(FPS * DURATION):
            proc.stdin.write(frame(index / FPS).tobytes())
            if index % (FPS * 4) == 0:
                print(f"Rendered {index // FPS}/{DURATION}s", flush=True)
    finally:
        proc.stdin.close()
    code = proc.wait()
    if code:
        raise RuntimeError(f"FFmpeg exited with status {code}")
    print(f"Export: {target} ({target.stat().st_size / 1024 / 1024:.2f} MiB)", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stills-only", action="store_true")
    args = parser.parse_args()
    review_stills()
    if not args.stills_only:
        render()
