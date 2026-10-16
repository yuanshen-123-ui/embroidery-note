# -*- coding: utf-8 -*-
"""
刺绣便签 Embroidery Note —— FastAPI 后端
- GET  /api/notes        便签文案列表（多套文案）
- GET  /api/notes/random 随机一条文案
- POST /api/render       用 Pillow 渲染刺绣便签图片，返回 PNG
- 静态托管 frontend/dist（若已构建）
"""
from __future__ import annotations

import hashlib
import io
import math
import random
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR.parent / "frontend" / "dist"

# ---------------------------------------------------------------- 文案数据（多套，可直接改这里）
NOTES: List[dict] = [
    {"id": 1, "title": "宝贝", "text": "这个世界破破烂烂，\n只有你治愈了我，\n我爱你，宝贝"},
    {"id": 2, "title": "晚安", "text": "今天也是想你的一天，\n晚安，做个好梦。"},
    {"id": 3, "title": "打气", "text": "慢慢来，别着急，\n你已经在很努力地发光了。"},
    {"id": 4, "title": "生日", "text": "祝你生日快乐，\n愿你被这个世界温柔以待。"},
    {"id": 5, "title": "感谢", "text": "谢谢你出现在我的生命里，\n像春天路过荒原。"},
]

# ---------------------------------------------------------------- 配色
PINK = (242, 199, 210)          # 背景粉
CARD = (247, 243, 234)          # 布面色
BLUE = (63, 95, 158)            # 刺绣蓝
PALETTE = [                     # 手写字多色盘
    (192, 80, 77),    # 红
    (79, 138, 84),    # 绿
    (63, 95, 158),    # 蓝
    (132, 85, 168),   # 紫
    (126, 161, 63),   # 黄绿
    (209, 106, 138),  # 粉红
]

# ---------------------------------------------------------------- 字体（优先项目 fonts/ 目录，其次系统楷体/行楷）
FONT_CANDIDATES = [
    BASE_DIR / "fonts" / "LXGWWenKai-Regular.ttf",
    BASE_DIR / "fonts" / "LXGWWenKaiMono-Regular.ttf",
    BASE_DIR / "fonts" / "手写体.ttf",
    Path(r"C:\Windows\Fonts\STXINGKA.TTF"),   # 华文行楷
    Path(r"C:\Windows\Fonts\STKAITI.TTF"),    # 华文楷体
    Path(r"C:\Windows\Fonts\simkai.ttf"),     # 楷体
    Path(r"C:\Windows\Fonts\msyh.ttc"),       # 微软雅黑（兜底）
]


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_CANDIDATES:
        try:
            if p.exists():
                return ImageFont.truetype(str(p), size)
        except Exception:
            continue
    return ImageFont.load_default()


# ---------------------------------------------------------------- 绘图小工具
def _cbez(p0, p1, p2, p3, n=36):
    """三次贝塞尔采样点"""
    pts = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        pts.append((
            mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0],
            mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1],
        ))
    return pts


def _stroke(draw, pts, color, width):
    draw.line(pts, fill=color, width=width, joint="curve")


def draw_wavy_rect(draw, x0, y0, x1, y1, wave_len, amp, color, width):
    """四条正弦波组成的波浪边框"""
    def wavy(p0, p1):
        length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        waves = max(1.0, length / wave_len)
        n = int(waves * 10)
        nx, ny = -(p1[1] - p0[1]) / length, (p1[0] - p0[0]) / length
        pts = []
        for i in range(n + 1):
            t = i / n
            off = amp * math.sin(t * math.pi * 2 * waves)
            pts.append((p0[0] + (p1[0] - p0[0]) * t + nx * off,
                        p0[1] + (p1[1] - p0[1]) * t + ny * off))
        return pts

    _stroke(draw, wavy((x0, y0), (x1, y0)), color, width)
    _stroke(draw, wavy((x1, y0), (x1, y1)), color, width)
    _stroke(draw, wavy((x1, y1), (x0, y1)), color, width)
    _stroke(draw, wavy((x0, y1), (x0, y0)), color, width)


def draw_dot_rect(draw, x0, y0, x1, y1, spacing, r, color):
    """四边圆点装饰"""
    def dots(p0, p1):
        length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        n = max(1, int(length / spacing))
        for i in range(n + 1):
            t = i / n
            x, y = p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t
            draw.ellipse([x - r, y - r, x + r, y + r], fill=color)

    dots((x0, y0), (x1, y0))
    dots((x1, y1), (x0, y1))
    dots((x0, y0), (x0, y1))
    dots((x1, y0), (x1, y1))


def draw_flower(draw, x, y, r, petal, center):
    """五瓣小花朵"""
    for k in range(5):
        a = math.radians(72 * k - 90)
        px, py = x + r * math.cos(a), y + r * math.sin(a)
        pr = r * 0.62
        draw.ellipse([px - pr, py - pr, px + pr, py + pr], fill=petal)
    cr = r * 0.45
    draw.ellipse([x - cr, y - cr, x + cr, y + cr], fill=center)


def draw_leaf(draw, x, y, r, angle, color):
    a = math.radians(angle)
    x2, y2 = x + r * math.cos(a), y + r * math.sin(a)
    mx, my = (x + x2) / 2, (y + y2) / 2
    nx, ny = -math.sin(a), math.cos(a)
    pts = _cbez((x, y), (mx + nx * r * 0.5, my + ny * r * 0.5),
                (mx + nx * r * 0.5, my + ny * r * 0.5), (x2, y2), 16)
    _stroke(draw, pts, color, 2)


def draw_ornament(draw, cx, cy, s, with_bow=True):
    """花藤装饰：卷草 + 小花 + 可选蝴蝶结（顶部）"""
    w = max(2, int(s * 0.055))
    light, dark = (105, 135, 195), BLUE

    # 左右两段藤蔓（拱形）
    _stroke(draw, _cbez((cx - 2.15 * s, cy + 0.12 * s), (cx - 1.3 * s, cy - 0.22 * s),
                        (cx - 0.7 * s, cy - 0.10 * s), (cx - 0.30 * s, cy - 0.02 * s)), BLUE, w)
    _stroke(draw, _cbez((cx + 2.15 * s, cy + 0.12 * s), (cx + 1.3 * s, cy - 0.22 * s),
                        (cx + 0.7 * s, cy - 0.10 * s), (cx + 0.30 * s, cy - 0.02 * s)), BLUE, w)

    # 两端小卷
    for sgn in (-1, 1):
        ex = cx + sgn * 2.15 * s
        r = 0.13 * s
        ey = cy + 0.12 * s
        bbox = [ex - 2 * r, ey - r, ex, ey + r] if sgn > 0 else [ex, ey - r, ex + 2 * r, ey + r]
        draw.arc(bbox, start=270, end=90 if sgn > 0 else 450, fill=BLUE, width=w)
        draw.arc([ex - sgn * r * 0.2 - r * 0.5, ey - r * 0.5,
                  ex - sgn * r * 0.2 + r * 0.5, ey + r * 0.5], start=90, end=330, fill=BLUE, width=max(2, w - 1))

    # 藤蔓上的小花 + 叶子
    for fx, fy, fr in [(-1.55, 0.02, 0.10), (-0.85, -0.10, 0.085), (0.85, -0.10, 0.085), (1.55, 0.02, 0.10)]:
        draw_flower(draw, cx + fx * s, cy + fy * s, fr * s, light, dark)
        draw_leaf(draw, cx + fx * s - 0.16 * s, cy + fy * s + 0.05 * s, 0.11 * s, 200, dark)
        draw_leaf(draw, cx + fx * s + 0.16 * s, cy + fy * s + 0.05 * s, 0.11 * s, -20, dark)

    if with_bow:
        # 蝴蝶结：两个环 + 结 + 飘带
        knot = (cx, cy + 0.02 * s)
        for sgn in (-1, 1):
            tip = (cx + sgn * 0.88 * s, cy - 0.10 * s)
            up = _cbez(knot, (cx + sgn * 0.32 * s, cy - 0.60 * s),
                       (cx + sgn * 0.92 * s, cy - 0.48 * s), tip)
            down = _cbez(tip, (cx + sgn * 0.55 * s, cy - 0.26 * s),
                         (cx + sgn * 0.25 * s, cy - 0.06 * s), knot)
            _stroke(draw, up + down + [up[0]], BLUE, w)
        kr = 0.075 * s
        draw.ellipse([knot[0] - kr, knot[1] - kr, knot[0] + kr, knot[1] + kr], fill=BLUE)
        # 飘带
        _stroke(draw, _cbez((cx - 0.05 * s, cy + 0.08 * s), (cx - 0.12 * s, cy + 0.30 * s),
                            (cx - 0.30 * s, cy + 0.34 * s), (cx - 0.42 * s, cy + 0.28 * s)), BLUE, w)
        _stroke(draw, _cbez((cx + 0.05 * s, cy + 0.08 * s), (cx + 0.12 * s, cy + 0.30 * s),
                            (cx + 0.30 * s, cy + 0.34 * s), (cx + 0.42 * s, cy + 0.28 * s)), BLUE, w)
    else:
        # 底部花藤：中段补一段，连成完整拱线
        _stroke(draw, _cbez((cx - 0.30 * s, cy - 0.02 * s), (cx - 0.1 * s, cy - 0.10 * s),
                            (cx + 0.1 * s, cy - 0.10 * s), (cx + 0.30 * s, cy - 0.02 * s)), BLUE, w)


def draw_text_block(img: Image.Image, text: str, box, font, font_size, rng: random.Random):
    """多色手写感文字：逐字上色 + 轻微旋转抖动 + 自动换行"""
    x0, y0, x1, y1 = box
    line_height = int(font_size * 1.7)

    # 换行
    PUNCT = "，。！？、；：）】」》!?,."
    lines: List[List[str]] = []
    for raw in text.splitlines() or [""]:
        cur, cur_w = [], 0.0
        for ch in raw:
            w = font.getlength(ch)
            # 标点不落行首：挤到上一行
            if ch in PUNCT and not cur and lines and lines[-1]:
                lines[-1].append(ch)
                continue
            if cur and cur_w + w > (x1 - x0):
                if ch in PUNCT:
                    # 行尾放不下的标点直接挂到上一行行尾
                    cur.append(ch)
                    lines.append(cur)
                    cur, cur_w = [], 0.0
                    continue
                lines.append(cur)
                cur, cur_w = [], 0.0
            cur.append(ch)
            cur_w += w
        lines.append(cur)

    pad = font_size * 2
    y = y0
    for line in lines:
        x = x0
        for ch in line:
            color = PALETTE[rng.randrange(len(PALETTE))]
            # 手写歪斜：±3–8° 旋转、±2–4px 上下错落
            rot = (3 + rng.random() * 5) * (1 if rng.random() < 0.5 else -1)
            dy = (2 + rng.random() * 2) * (1 if rng.random() < 0.5 else -1)
            tile = Image.new("RGBA", (int(pad), int(pad)), (0, 0, 0, 0))
            td = ImageDraw.Draw(tile)
            td.text((pad / 2, pad / 2), ch, font=font, fill=color)
            rot_img = tile.rotate(rot, resample=Image.BICUBIC)
            img.alpha_composite(rot_img, (int(x - pad / 2), int(y + dy - pad / 2)))
            x += font.getlength(ch)
        y += line_height
        if y > y1:
            break


# ---------------------------------------------------------------- 渲染主流程
def render_note_image(text: str, width: int = 1080, height: int = 1862,
                      seed: Optional[int] = None, font_size: int = 54) -> Image.Image:
    if not text.strip():
        text = NOTES[0]["text"]
    seed = seed if seed is not None else int(hashlib.md5(text.encode("utf-8")).hexdigest()[:8], 16)
    rng = random.Random(seed)

    W, H = max(400, width), max(400, height)
    img = Image.new("RGBA", (W, H), PINK + (255,))

    # 卡片几何
    card_w = int(W * 0.80)
    card_h = int(min(H * 0.52, card_w * 1.08))
    x0, y0 = (W - card_w) // 2, int(H * 0.47 - card_h / 2)
    x1, y1 = x0 + card_w, y0 + card_h

    # 投影
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle([x0 + 6, y0 + 18, x1 + 6, y1 + 18], radius=8, fill=(120, 60, 75, 80))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    img = Image.alpha_composite(img, shadow)

    # 卡片本体（布纹 = 噪声叠加）
    noise = Image.effect_noise((card_w, card_h), 22).convert("L")
    noise_rgb = Image.merge("RGB", (noise, noise, noise))
    card = Image.blend(Image.new("RGB", (card_w, card_h), CARD), noise_rgb, 0.055).convert("RGBA")
    img.alpha_composite(card, (x0, y0))

    draw = ImageDraw.Draw(img)

    # 波浪刺绣边框 + 圆点装饰
    m1 = int(card_w * 0.028)
    draw_wavy_rect(draw, x0 + m1, y0 + m1, x1 - m1, y1 - m1,
                   wave_len=int(card_w * 0.030), amp=card_w * 0.006, color=BLUE, width=3)
    m2 = int(card_w * 0.055)
    draw_dot_rect(draw, x0 + m2, y0 + m2, x1 - m2, y1 - m2,
                  spacing=card_w * 0.048, r=card_w * 0.0045, color=BLUE)

    # 顶部花藤蝴蝶结 / 底部花藤
    draw_ornament(draw, W / 2, y0 + card_h * 0.145, s=card_w * 0.145, with_bow=True)
    draw_ornament(draw, W / 2, y0 + card_h * 0.845, s=card_w * 0.125, with_bow=False)

    # 文字
    font = load_font(font_size)
    draw_text_block(img, text,
                    box=(x0 + card_w * 0.13, y0 + card_h * 0.24,
                         x0 + card_w * 0.87, y0 + card_h * 0.74),
                    font=font, font_size=font_size, rng=rng)

    return img.convert("RGB")


# ---------------------------------------------------------------- API
app = FastAPI(title="Embroidery Note API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/notes")
def list_notes():
    return {"notes": NOTES}


@app.get("/api/notes/random")
def random_note():
    import random as _r
    return _r.choice(NOTES)


@app.get("/api/notes/{note_id}")
def get_note(note_id: int):
    for n in NOTES:
        if n["id"] == note_id:
            return n
    raise HTTPException(status_code=404, detail="note not found")


class RenderRequest(BaseModel):
    text: str = ""
    width: int = Field(1080, ge=400, le=2400)
    height: int = Field(1862, ge=400, le=2400)
    seed: Optional[int] = None
    font_size: int = Field(54, ge=20, le=120)


@app.post("/api/render")
def render(req: RenderRequest, download: int = Query(0)):
    img = render_note_image(req.text, req.width, req.height, req.seed, req.font_size)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    disp = "attachment" if download else "inline"
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={"Content-Disposition": f'{disp}; filename="embroidery-note.png"'},
    )


# 汉字笔画数据（hanzi-writer-data，MIT；本地直供，避免前端走 CDN 失败）
# 注意：必须挂在 "/" 静态目录之前
HANZI_DIR = BASE_DIR / "hanzi-data"
if HANZI_DIR.exists():
    app.mount("/hanzi-data", StaticFiles(directory=str(HANZI_DIR)), name="hanzi-data")

# 静态托管前端构建产物（存在时）
if DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
