"""글리프 단위 조작.

레시피의 op 목록을 해석한다. FontForge 의 .pe 스크립트에서 옮겨 온 것이라
변환 의미를 맞춰 두었다.

    .pe Scale(s) / Rotate(a)    -> 글리프별 bounding box 중심 기준
    .pe Scale(sx, sy, 0, 0)     -> 원점 기준
    .pe CenterInWidth()         -> bbox 를 advance width 한가운데로

조용히 틀리기 쉬운 곳이 둘 있다.

- Scale 은 중심 인자를 생략하면 원점이 아니라 bbox 중심이 기준이다.
- FontForge 의 transform 은 advance width 도 같이 옮긴다. 폭을 지키려면
  변환 뒤에 되돌려 놓아야 한다.
"""

from __future__ import annotations

import math
import os

import fontforge
import psMat

from .recipe import cp, cp_range
from . import outline as O

_LENT = {}                  # 다른 굵기·다른 소스에서 빌려 연 글꼴 — 한 번만 연다

OPS = {}


def op(name):
    def deco(fn):
        OPS[name] = fn
        return fn
    return deco


# --------------------------------------------------------------------------
# 도우미
# --------------------------------------------------------------------------


def transform_about_center(glyph, matrix):
    """.pe 의 중심 인자 없는 Scale/Rotate. 글리프 bbox 중심이 기준이다."""
    xmin, ymin, xmax, ymax = glyph.boundingBox()
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    glyph.transform(
        psMat.compose(
            psMat.translate(-cx, -cy),
            psMat.compose(matrix, psMat.translate(cx, cy)),
        )
    )


def center_in_width(glyph):
    """.pe CenterInWidth(). transform 이 폭도 옮기므로 되돌려 놓는다."""
    width = glyph.width
    xmin, _, xmax, _ = glyph.boundingBox()
    glyph.transform(psMat.translate((width - (xmax - xmin)) / 2 - xmin, 0))
    glyph.width = width


def worth(glyph):
    """.pe WorthOutputting(). 윤곽이나 참조가 있는 글리프인지."""
    return glyph.isWorthOutputting()


def glyph_codepoints(glyph):
    """글리프가 닿는 모든 코드포인트.

    FontForge 는 주 유니코드 하나만 glyph.unicode 로 준다. CJK 글꼴에서는
    한 글리프가 강희부수와 통합한자 양쪽에 매핑된 경우가 흔한데, 이때 주
    유니코드가 부수 쪽(U+2F00 대)이고 정작 쓰이는 한자는 altuni 에 들어간다.
    IBM Plex Sans JP 에서 大(U+5927) 는 주 유니코드가 U+2F24 이고 U+5927 은
    altuni 다. altuni 를 보지 않으면 大 一 人 日 月 같은 기본 한자가 통째로
    빠진다.
    """
    out = set()
    if glyph.unicode is not None and glyph.unicode >= 0:
        out.add(glyph.unicode)
    for alt in (glyph.altuni or ()):
        if alt[0] is not None and alt[0] >= 0:
            out.add(alt[0])
    return out


def codepoints_of(font):
    out = set()
    for g in font.glyphs():
        if worth(g):
            out |= glyph_codepoints(g)
    return out


def set_em(font, ctx):
    """.pe ScaleToEm. upem 이 다른 소스도 여기서 목표 크기로 맞춰진다."""
    font.em = ctx.em_ascent + ctx.em_descent
    font.ascent = ctx.em_ascent
    font.descent = ctx.em_descent


def unlink_all(font):
    font.selection.all()
    font.unlinkReferences()
    font.selection.none()


def selected_codepoints(spec):
    """op 의 cp / cps / range / ranges 를 코드포인트 목록으로."""
    out = []
    if "cp" in spec:
        out.append(cp(spec["cp"]))
    out.extend(cp(v) for v in spec.get("cps", []))
    if "range" in spec:
        out.extend(cp_range(spec["range"]))
    for pair in spec.get("ranges", []):
        out.extend(cp_range(pair))
    return out


def selected_glyphs(font, spec):
    """op 이 건드릴 글리프. 한 글리프가 여러 코드포인트에 걸려 있어도 한 번만 내준다.

    CJK 글꼴은 한 글리프를 통합한자와 강희부수 양쪽에 매핑해 둔다. IBM Plex Sans JP
    는 258 자가 그렇고, 그중 여섯 자는 부수 보충까지 세 곳에 걸려 있다. 코드포인트
    단위로 돌면 그런 글리프는 변환을 두 번, 세 번 받는다. 평행이동이면 그만큼 더
    옮겨 가고 (한자를 -75 내리는 op 에서 行 言 金 車 見 食 馬 高 가 -150 내려갔다),
    배율이면 그만큼 더 줄어든다.
    """
    want_width = spec.get("ifWidth")
    seen = set()
    for code in selected_codepoints(spec):
        if code not in font:
            continue
        glyph = font[code]
        if glyph.glyphname in seen:
            continue
        # ifWidth 를 적으면 지금 그 폭인 글리프만 고른다. 폭으로 갈리는 무리를
        # 코드포인트로 일일이 적지 않아도 되고, 앞선 op 가 이미 폭을 바꾼
        # 글리프는 저절로 빠진다.
        if want_width is not None and glyph.width != want_width:
            continue
        seen.add(glyph.glyphname)
        yield glyph


def as_scale(value):
    """by: 145 또는 [109, 106] 을 (sx, sy) 배율로."""
    if isinstance(value, (int, float)):
        return value / 100, value / 100
    sx, sy = value
    return sx / 100, sy / 100


def _set_width(ctx, glyph, spec, source_half):
    name = spec.get("setWidth")
    if name:
        glyph.width = ctx.width_value(name, source_half)


# --------------------------------------------------------------------------
# op
# --------------------------------------------------------------------------


@op("scale")
def op_scale(ctx, font, spec, source_half):
    sx, sy = as_scale(spec["by"])
    for glyph in selected_glyphs(font, spec):
        transform_about_center(glyph, psMat.scale(sx, sy))
        _set_width(ctx, glyph, spec, source_half)


@op("scaleOrigin")
def op_scale_origin(ctx, font, spec, source_half):
    sx, sy = as_scale(spec["by"])
    for glyph in selected_glyphs(font, spec):
        glyph.transform(psMat.scale(sx, sy))
        _set_width(ctx, glyph, spec, source_half)


@op("rotate")
def op_rotate(ctx, font, spec, source_half):
    for glyph in selected_glyphs(font, spec):
        transform_about_center(glyph, psMat.rotate(math.radians(spec["deg"])))
        _set_width(ctx, glyph, spec, source_half)


@op("translate")
def op_translate(ctx, font, spec, source_half):
    dx, dy = spec.get("dx", 0), spec.get("dy", 0)
    for glyph in selected_glyphs(font, spec):
        width = glyph.width
        glyph.transform(psMat.translate(dx, dy))
        glyph.width = width
        _set_width(ctx, glyph, spec, source_half)


@op("setWidth")
def op_set_width(ctx, font, spec, source_half):
    for glyph in selected_glyphs(font, spec):
        glyph.width = ctx.width_value(spec["to"], source_half)
        if spec.get("center"):
            center_in_width(glyph)


@op("embolden")
def op_embolden(ctx, font, spec, source_half):
    """획을 굵힌다 — 세로획은 x 만큼, 가로획은 y 만큼 (폭과 높이는 그대로).

    x · y 는 숫자, 또는 {"of": 글리프, "scale": 배} (그 글리프 세로획 두께의 배) ·
    {"hOf": 글리프, "scale": 배} (가로획 두께의 배) 라 굵기마다 따라간다. 가로세로를
    다른 비율로 줄인 글자(Monoplex 의 latin 은 가로 0.88 · 세로 0.94)는 세로획이 더
    가늘어지는데, 그 둘을 따로 되돌리려고 세로로 x/y 배 늘린 자리에서 x 만큼 굵히고
    되돌린다 — 세로획은 x, 가로획은 y 만큼 는다. 늘린 자리에서 좁은 틈(y 의 갈래)이
    메워져 윤곽 수가 바뀌는 글리프는 늘리지 않고 x 만큼 고르게 굵힌다. 윤곽이 있는
    글리프는 cmap 밖의 것(조합 부품)까지 모두 — 참조로 짠 글리프는 부품을 따라간다.
    FontForge 는 작은 양수로 굵힐 때 "Invalid 2nd order spline" 을 찍는다 (_part_contours 참고).
    """
    gx, gy = _width(font, spec["x"]), _width(font, spec["y"])
    if gx <= 0 or gy <= 0:
        return
    k = gx / gy

    def grow(glyph, stretch):
        width = glyph.width
        glyph.transform(psMat.scale(1, stretch))
        glyph.changeWeight(gx, "LCG", 0, 0, "squish")
        glyph.transform(psMat.scale(1, 1 / stretch))
        glyph.removeOverlap()
        _straighten(glyph)
        glyph.correctDirection()
        glyph.round()
        glyph.width = width

    def fits(glyph, box, ex, ey):
        # 굵힌 만큼만 커졌는가 — 3차 곡선의 removeOverlap 은 가끔 윤곽 한쪽을 통째로
        # 잃는다 (Text 의 ⁸ 는 윗고리가 사라진다).
        if any(c.isClockwise() == -1 for c in glyph.foreground):
            return False             # 꼬여 방향을 못 잡는 윤곽 (Light 의 ѫ — 구멍이 메워진다)
        x0, y0, x1, y1 = glyph.boundingBox()
        tol = max(4.0, gx)
        return (abs(x0 - (box[0] - ex)) <= tol and abs(x1 - (box[2] + ex)) <= tol
                and abs(y0 - (box[1] - ey)) <= tol and abs(y1 - (box[3] + ey)) <= tol)

    def attempt(glyph, before):
        """늘린 자리에서, 안 되면 고르게. 윤곽 수와 먹 상자가 맞으면 True."""
        box = before.boundingBox()
        grow(glyph, k)
        if len(glyph.foreground) == len(before) and fits(glyph, box, gx / 2, gy / 2):
            return True, False
        glyph.foreground = before
        grow(glyph, 1)
        return len(glyph.foreground) == len(before) and fits(glyph, box, gx / 2, gx / 2), True

    # changeWeight 는 2차 곡선의 곧은 사선을 곡선으로 돌려준다. 조절점이 선 밖으로
    # 크게 벗어나 획이 휜다 (1.2.0 Regular 의 7 · Z, Thin 의 4 · N). 그래서 3차 곡선에서
    # 굵히고, 거의 곧은 곡선은 직선으로 편 뒤 (_straighten) 되돌린다.
    # 3차 곡선에서 망가지는 글자는 (윤곽 수나 먹 상자가 어긋남) 2차 곡선 그대로 굵힌다.
    fore = font.layers["Fore"]
    quadratic = fore.is_quadratic
    targets = [g for g in font.glyphs()
               if not g.glyphname.startswith("_compose") and len(g.foreground)]
    originals = {g.glyphname: g.foreground.dup() for g in targets}
    fore.is_quadratic = False

    plain = 0
    retry = []
    for glyph in targets:
        ok, flat = attempt(glyph, glyph.foreground.dup())
        plain += flat
        if not ok:
            retry.append(glyph)
    fore.is_quadratic = quadratic
    for glyph in targets:
        # 3차 곡선의 removeOverlap 은 가끔 꼬인 윤곽을 남겨 방향을 못 잡는다 (Light 의
        # ѫ 바깥 윤곽이 꼬여 구멍이 메워짐). 2차 곡선에서 한 번 더 풀고 방향을 잡는다.
        kept = glyph.foreground.dup()
        glyph.removeOverlap()
        if len(glyph.foreground) != len(kept):
            glyph.foreground = kept  # 좁은 틈을 닫으면 버린다 (Bold 의 ↔ 화살촉과 몸통 사이 4 단위)
        glyph.correctDirection()
        glyph.round()
        _straighten(glyph)           # 여기서 다시 생기는 크기 0 윤곽과 곧은 점에 붙은 조절점을 치운다
    for glyph in retry:                 # 1.2.0 과 똑같이 — 윤곽 수가 바뀔 때만 고르게
        before = originals[glyph.glyphname]
        glyph.foreground = before
        grow(glyph, k)
        if len(glyph.foreground) != len(before):
            glyph.foreground = before
            grow(glyph, 1)
    print("embolden: %d 자 (세로획 +%.1f, 가로획 +%.1f; 고르게 %d 자, 2차 곡선으로 %d 자 %s)"
          % (len(targets), gx, gy, plain, len(retry), " ".join(g.glyphname for g in retry[:12])))


def _straighten(glyph, tol=3.0):
    """거의 곧은 곡선을 직선으로 펴고, 모서리에 남은 실낱 윤곽을 버린다.

    곧은 점 사이의 조절점들이 현에서 `tol` 안이면서 현 길이의 3% 안이면 (Regular 7 의
    밑변에 남은 2 단위 혹) 직선으로 편다 — 작은 점의 둥근 곡선은 3% 를 넘어 남는다.
    조절점 하나가 곧은 점에 3 단위 안으로 붙어 있으면 (SemiBold ✓ 의 팔 끝) 그 곡선은
    출발 방향이 꺾여 다시 굵힐 때 가시가 솟으므로 버린다. 가로나 세로 2 단위 미만의
    윤곽은 changeWeight 가 모서리에 남긴 실낱이라 버린다 (반올림하면 퇴화해 FontForge 가
    죽는다). 곧은 점이 셋 미만인 윤곽(쉼표)은 펴지 않는다."""
    lay = glyph.foreground
    out = fontforge.layer()
    out.is_quadratic = lay.is_quadratic
    changed = False
    for c in lay:
        x0, y0, x1, y1 = c.boundingBox()
        if x1 - x0 < 2 or y1 - y0 < 2:
            changed = True
            continue
        pts = list(c)
        n = len(pts)
        ons = [i for i, p in enumerate(pts) if p.on_curve]
        if len(ons) < 3:
            out += c
            continue
        keep = [True] * n
        for k, i in enumerate(ons):
            j = ons[(k + 1) % len(ons)]
            mids = [(i + m) % n for m in range(1, (j - i) % n or n)]
            if not mids:
                continue
            a, b = pts[i], pts[j]
            dx, dy = b.x - a.x, b.y - a.y
            L = math.hypot(dx, dy)
            if L < 1:
                continue
            flat = all(abs((pts[m].x - a.x) * dy - (pts[m].y - a.y) * dx) / L <= min(tol, 0.03 * L)
                       for m in mids)
            stub = len(mids) == 1 and min(math.hypot(pts[mids[0]].x - q.x, pts[mids[0]].y - q.y)
                                          for q in (a, b)) <= 3
            if flat or stub:
                for m in mids:
                    keep[m] = False
                changed = True
        pts = [p for i, p in enumerate(pts) if keep[i]]
        # 직선 둘 사이의 곧은 점이 거의 한 줄 위에 있으면 지운다 — changeWeight 가 완만한
        # 곡선을 꺾은선으로 돌려주는데 (Bold ✓ 팔 끝의 자른 변), 다시 굵히면 그 꺾인
        # 자리마다 홈이 팬다 (✔).
        while True:
            n = len(pts)
            on = sum(1 for p in pts if p.on_curve)
            hit = None
            for i in range(n):
                a, p, b = pts[i - 1], pts[i], pts[(i + 1) % n]
                if not (a.on_curve and p.on_curve and b.on_curve) or on <= 3:
                    continue
                dx, dy = b.x - a.x, b.y - a.y
                L = math.hypot(dx, dy)
                if L >= 1 and abs((p.x - a.x) * dy - (p.y - a.y) * dx) / L <= min(tol, 0.03 * L):
                    hit = i
                    break
            if hit is None:
                break
            del pts[hit]
            changed = True
        nc = fontforge.contour()
        nc.is_quadratic = c.is_quadratic
        for p in pts:
            nc += fontforge.point(p.x, p.y, p.on_curve)
        nc.closed = c.closed
        out += nc
    if changed:
        glyph.foreground = out


@op("clear")
def op_clear(ctx, font, spec, source_half):
    for glyph in selected_glyphs(font, spec):
        glyph.clear()


@op("mergeSfd")
def op_merge_sfd(ctx, font, spec, source_half):
    """손질한 글리프를 담은 .sfd 를 합친다.

    합성 글리프가 교체 대상을 참조로 물고 있을 수 있으므로, 보통 참조를 풀기 전
    (preOps) 에 돌린다.
    """
    if spec.get("skipWhen") == "italic" and ctx.style.get("italic"):
        return
    path = ctx.path(spec["from"])
    if not os.path.exists(path):
        return
    for code in [cp(c) for c in spec.get("clearFirst", [])]:
        if code in font:
            font[code].clear()
    font.mergeFonts(path)


def _circle(cx, cy, rx, ry, clockwise=True):
    """타원(원) 윤곽 — 2차 곡선 8조각. clockwise 면 먹, 아니면 구멍."""
    c = fontforge.contour()
    c.is_quadratic = True
    k = 1 / math.cos(math.radians(22.5))
    steps = range(0, -360, -45) if clockwise else range(0, 360, 45)
    half = -22.5 if clockwise else 22.5
    for a in steps:
        t = math.radians(a)
        c += fontforge.point(cx + rx * math.cos(t), cy + ry * math.sin(t), True)
        t = math.radians(a + half)
        c += fontforge.point(cx + rx * k * math.cos(t), cy + ry * k * math.sin(t), False)
    c.closed = True
    return c


def _stem(font, code):
    """글리프의 세로 가운데에서 가로로 잰 먹의 폭 — 획 두께. 기울어진 | (이탤릭) 도 70 언저리로 잰다."""
    src = font[cp(code)]
    x0, y0, x1, y1 = src.boundingBox()
    ym = (y0 + y1) / 2
    tmp = font.createChar(-1, "_compose_stem")
    tmp.clear()
    tmp.addReference(src.glyphname)
    tmp.unlinkRef()
    tmp.removeOverlap()
    box = fontforge.contour()
    box.is_quadratic = tmp.foreground.is_quadratic
    for px, py in ((x0 - 10, ym - 1), (x0 - 10, ym + 1), (x1 + 10, ym + 1), (x1 + 10, ym - 1)):
        box += fontforge.point(px, py, True)
    box.closed = True
    lay = tmp.foreground
    lay += box
    tmp.foreground = lay
    tmp.intersect()
    bx0, _, bx1, _ = tmp.boundingBox() if tmp.foreground else (0, 0, x1 - x0, 0)
    font.removeGlyph(tmp)
    return bx1 - bx0


def _hstem(font, code):
    """글리프의 가로 가운데에서 세로로 잰 먹의 두께 — H 의 가로대처럼 가로획 두께."""
    src = font[cp(code)]
    x0, y0, x1, y1 = src.boundingBox()
    xm = (x0 + x1) / 2
    tmp = font.createChar(-1, "_compose_stem")
    tmp.clear()
    tmp.addReference(src.glyphname)
    tmp.unlinkRef()
    tmp.removeOverlap()
    box = fontforge.contour()
    box.is_quadratic = tmp.foreground.is_quadratic
    for px, py in ((xm - 1, y0 - 10), (xm - 1, y1 + 10), (xm + 1, y1 + 10), (xm + 1, y0 - 10)):
        box += fontforge.point(px, py, True)
    box.closed = True
    lay = tmp.foreground
    lay += box
    tmp.foreground = lay
    tmp.intersect()
    _, by0, _, by1 = tmp.boundingBox() if tmp.foreground else (0, 0, 0, y1 - y0)
    font.removeGlyph(tmp)
    return by1 - by0


def _frame_stroke(font, code):
    """네모 테두리 글리프(□)의 획 두께 — 바깥과 안 윤곽의 왼끝 차."""
    lefts = sorted(c.boundingBox()[0] for c in font[cp(code)].foreground)
    return lefts[1] - lefts[0] if len(lefts) > 1 else 0


def _width(font, spec):
    """숫자, 또는 {"of": 코드포인트, "scale": 배} — 기준 글리프의 획 두께 × 배 (굵기마다 따라간다)."""
    if isinstance(spec, dict):
        if "frameOf" in spec:
            return _frame_stroke(font, spec["frameOf"]) * spec.get("scale", 1)
        if "hOf" in spec:
            return _hstem(font, spec["hOf"]) * spec.get("scale", 1)
        return _stem(font, spec["of"]) * spec.get("scale", 1)
    return spec


def _stroke_line(pts, w, squash=(1, 1), closed=False):
    """굵기 w 의 꺾은선 — 꺾이는 자리는 두 변을 늘려 만나게(miter), 두 끝은 평평하게. 시계방향 윤곽."""
    def off(p0, p1, side):
        L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        nx = -(p1[1] - p0[1]) / L * side * w / 2 * squash[0]
        ny = (p1[0] - p0[0]) / L * side * w / 2 * squash[1]
        return (p0[0] + nx, p0[1] + ny), (p1[0] + nx, p1[1] + ny)

    def meet(a0, a1, b0, b1):
        d1 = (a1[0] - a0[0], a1[1] - a0[1]); d2 = (b1[0] - b0[0], b1[1] - b0[1])
        den = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(den) < 1e-9:
            return a1
        t = ((b0[0] - a0[0]) * d2[1] - (b0[1] - a0[1]) * d2[0]) / den
        return (a0[0] + t * d1[0], a0[1] + t * d1[1])
    sides = []
    for side in (1, -1):
        segs = [off(pts[i], pts[i + 1], side) for i in range(len(pts) - 1)]
        line = [segs[0][0]] + [meet(*segs[i], *segs[i + 1]) for i in range(len(segs) - 1)] + [segs[-1][1]]
        sides.append(line)
    ring = sides[0] + sides[1][::-1]
    c = fontforge.contour()
    c.is_quadratic = True
    for x, y in ring:
        c += fontforge.point(x, y, True)
    c.closed = True
    if not c.isClockwise():
        c.reverseDirection()
    return c


def _part_contours(font, src, matrix, reverse=False, weight=None, fill=False, clip=None, clip_center=False):
    """부품 하나를 변환해 윤곽으로 펼친다 — 임시 글리프에서 참조를 풀어 돌려준다.

    reverse 는 감김을 뒤집는다 (구멍으로 넣거나, 음수 배율로 뒤집힌 것을 되돌릴 때).
    weight 를 주면 그만큼 굵게(음수면 가늘게) 한 뒤 돌려준다.
    """
    tmp = font.createChar(-1, "_compose_part")
    tmp.clear()
    if clip:
        # 부품을 제 좌표에서 네모 [x0, y0, x1, y1] 로 오린 뒤 옮긴다 (✽ 의 세로 바퀴살만)
        tmp.addReference(src.glyphname)
        tmp.unlinkRef()
        tmp.removeOverlap()
        x0, y0, x1, y1 = clip
        if clip_center:
            bx0, by0, bx1, by1 = src.boundingBox()
            mx, my = (bx0 + bx1) / 2, (by0 + by1) / 2
            x0, y0, x1, y1 = mx + x0, my + y0, mx + x1, my + y1
        box = fontforge.contour()
        box.is_quadratic = tmp.foreground.is_quadratic
        for px, py in ((x0, y0), (x0, y1), (x1, y1), (x1, y0)):     # 시계방향
            box += fontforge.point(px, py, True)
        box.closed = True
        lay = tmp.foreground
        lay += box
        tmp.foreground = lay
        tmp.intersect()
        tmp.transform(matrix)
    else:
        tmp.addReference(src.glyphname, matrix)
        tmp.unlinkRef()
    if weight:
        # FontForge 의 changeWeight 는 작은 양수(+0.5 ~ +32)로 굵힐 때 "Invalid 2nd order
        # spline in SplineRefigure2" 를 찍는다 (3차 곡선으로 바꿔도 같다). 윤곽은 맞게 나온다.
        tmp.removeOverlap()
        tmp.changeWeight(weight)
    out = []
    for contour in tmp.foreground:
        if fill and not contour.isClockwise():
            continue                          # 구멍(반시계)을 버려 속을 채운다
        c = contour.dup()
        if reverse:
            c.reverseDirection()
        out.append(c)
    font.removeGlyph(tmp)
    return out


@op("compose")
def op_compose(ctx, font, spec, source_half):
    """같은 글꼴의 글리프를 옮기고 줄여 붙여서 새 글리프를 만든다.

        {"op": "compose", "cp": "203c", "width": "source-half",
         "parts": [{"cp": "0021", "dx": -110}, {"cp": "0021", "dx": 110}]}

    ‼ ⁇ ⁈ ⁉ 같은 겹문장부호를 CJK 소스의 전각 글리프를 통째로 줄여 넣으면
    크기가 제각각이고 너무 작아진다. 라틴 소스 자체의 ! 와 ? 를 두 개 붙이면
    높이가 본문 부호와 같다. part 의 scale 은 백분율 (75 또는 [75, 100]),
    dx·dy 는 이 글꼴의 유닛이다. 부품은 cp 대신 glyph 로 이름을 줘도 된다.
    결과는 참조를 풀어 윤곽으로 두고, width 를 준 뒤 가운데 놓는다.

    part 의 clip 은 [x0, y0, x1, y1] — 부품을 제 좌표에서 그 네모로 오려 쓴다 (clipFrom 이
    "center" 면 부품 상자 가운데 기준 — 굵기마다 자리가 달라도 맞는다).
    part 의 line · arc 는 굵기 width 의 선을 긋는다 — width 를 {"of": "007c", "scale": s} 로 주면
    굵기마다 | 의 획 두께를 따르고, 기울지 않아 이탤릭에서도 곧게 선다.
    part 의 fill 을 true 로 주면 부품의 구멍을 버려 속을 채운다 (▱ 에서 ▰).
    part 에 polygon([[x, y], ...] 시계방향 꼭짓점) 을 주면 다각형을 그린다 — outline 의
    wall·wallScale 로 속을 비운다 (⏎ 의 삼각형 머리 화살표).
    part 에 circle([가로, 세로] 지름) 과 at([x, y] 가운데) 를 주면 글리프 대신 원을
    그린다 — ring 을 함께 주면 고리 (ringScale 로 테두리를 기준 폭의 몇 배로). Plex 의 • ○ 는 모서리가 둥근 사각형이다.
    part 의 outline 은 {"grow": g, "wall": w} 로, 부품의 획을 g 만큼 굵힌 바깥과(양쪽으로
    g/2 씩 자란다 — FontForge 의 changeWeight) 그보다 w 안쪽의 구멍으로 속 빈 모양을 만든다 (⏎ 의 속 빈 Return 화살표). w 를 코드포인트로
    주면 그 글리프의 폭 — 벽이 굵기마다 본문 획 두께를 따른다. wallScale 로 그 몇 배인지.
    부품은 하나씩 펼쳐 감김을 바로잡고, 다 모은 뒤 겹침을 합친다.
    part 의 ring 은 기준 글리프의 코드포인트다. 그 부품을 고리로 만든다 — 테두리
    두께가 기준 글리프의 폭과 같다 (⌕ 의 렌즈는 • 를 키운 것에 | 폭의 테두리).
    part 의 rotate 는 도(반시계)이고, 줄인 뒤 부품 자신의 가운데를 축으로 돈다
    (⌕ 의 기운 손잡이). spec 의 embolden 은 다 붙인 뒤 획을 그만큼 굵게(음수면
    가늘게) 한다 — ✓ 에서 ✔ 를 만들 때다. {"of": 글리프, "scale": 배} 로 주면 그 글리프 획
    두께의 배, {"frameOf": "25a1", "scale": 배} 면 □ 테두리 두께의 배 (굵기마다 따라간다). center 를 false 로 주면 가운데 놓지
    않는다. 칸 안의 자리가 정해진 글자(점자의 한쪽 열만 찍힌 ⠇ ⠸)에 쓴다.
    """
    code = cp(spec["cp"])
    glyph = font.createChar(code)
    glyph.clear()
    lay = fontforge.layer()
    lay.is_quadratic = glyph.foreground.is_quadratic
    for part in spec["parts"]:
        if "line" in part or "arc" in part:
            # 선 — 꼭짓점 [[x, y], ...] 이나 호 [cx, cy, rx, ry, 시작각, 끝각] 을 굵기 width 로 긋는다.
            # width 가 {"of": "007c", "scale": s} 면 굵기마다 | 의 획 두께를 따른다. 기울지 않으므로
            # 이탤릭에서도 곧게 선다. squash 는 법선의 [가로, 세로] 배 (나중의 가로세로 맞춤 비가 다를 때).
            if "arc" in part:
                ax, ay, rx, ry, a0, a1 = part["arc"]
                n = max(8, int(abs(a1 - a0) / 4))
                pts = [(ax + rx * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
                        ay + ry * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]
            else:
                pts = [tuple(p) for p in part["line"]]
            lay += _stroke_line(pts, _width(font, part["width"]), tuple(part.get("squash", (1, 1))))
            continue
        if "polygon" in part:
            # 다각형 — 꼭짓점 [[x, y], ...] 를 시계방향으로. outline 을 함께 주면 속을 비운다.
            poly = fontforge.contour()
            poly.is_quadratic = True
            for x, y in part["polygon"]:
                poly += fontforge.point(x, y, True)
            poly.closed = True
            lay += poly
            if "outline" in part:
                o = part["outline"]
                wall = o["wall"]
                if isinstance(wall, str):
                    wall = _stem(font, wall)
                wall *= o.get("wallScale", 1)
                tmp = font.createChar(-1, "_compose_part")
                tmp.clear()
                tl = fontforge.layer()
                tl.is_quadratic = poly.is_quadratic
                tl += poly
                tmp.foreground = tl
                if o.get("erode"):
                    # 뾰족한 꼭지(✧)는 changeWeight 가 지나치게 깎거나 가는 굵기에서 구멍을 못 낸다 —
                    # 다각형을 wall 만큼 16 방향으로 옮긴 사본과 차례로 겹쳐(intersect) 남는 곳을 구멍으로.
                    for k in range(16):
                        a = 2 * math.pi * k / 16
                        sh = poly.dup()
                        sh.transform(psMat.translate(wall * math.cos(a), wall * math.sin(a)))
                        both = tmp.foreground
                        both += sh
                        tmp.foreground = both
                        tmp.intersect()
                else:
                    tmp.changeWeight(-2 * wall)        # 양쪽으로 wall 씩 안으로
                for contour in tmp.foreground:
                    c = contour.dup()
                    if c.isClockwise():                # changeWeight 의 감김은 일정하지 않다 — 구멍은 반시계로
                        c.reverseDirection()
                    lay += c
                font.removeGlyph(tmp)
            continue
        if "circle" in part:
            # 원 — 글리프가 아닌 도형. circle 은 [가로, 세로] 지름, at 은 가운데.
            # Plex 의 • ○ 는 모서리가 둥근 사각형이라 원이 필요하면 이것을 쓴다.
            if isinstance(part["circle"], dict):     # {"of": 글리프, "scale": 배, "aspect": 가로/세로} — 그 글리프 높이에서
                cs_ = part["circle"]
                _, gy0, _, gy1 = font[cp(cs_["of"])].boundingBox()
                h = (gy1 - gy0) * cs_.get("scale", 1)
                w = h * cs_.get("aspect", 1)
            else:
                w, h = part["circle"]
            x, y = part["at"]
            lay += _circle(x, y, w / 2, h / 2)
            if part.get("ring"):
                t = _stem(font, part["ring"]) * part.get("ringScale", 1)   # 테두리 = 기준 글리프의 획 두께 × ringScale
                lay += _circle(x, y, w / 2 - t, (h / 2) * (w / 2 - t) / (w / 2), clockwise=False)
            continue
        # 부품은 코드포인트로, 또는 글리프 이름으로 지정한다. 분수의 one.numr
        # 처럼 cmap 에 없는 부품 글리프를 쓸 때가 있다.
        src = font[part["glyph"]] if "glyph" in part else font[cp(part["cp"])]
        sc = part.get("scale", 100)
        if isinstance(sc, list):            # 배율 자리에 {"frameOf": ..., "scale": ...} — 굵기마다 재서 백분율로
            sc = [_width(font, v) if isinstance(v, dict) else v for v in sc]
        sx, sy = as_scale(sc)
        # 부품은 자기 자면 중심을 기준으로 줄인다. 원점 기준이면 축소 비율이 다른
        # 부품끼리 자리가 어긋난다. 그 뒤 dx·dy 만큼 옮긴다.
        xmin, ymin, xmax, ymax = src.boundingBox()
        cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
        dx, dy = part.get("dx", 0), part.get("dy", 0)

        def place(kx, ky):
            about = psMat.scale(kx, ky)
            if part.get("rotate"):
                about = psMat.compose(about, psMat.rotate(math.radians(part["rotate"])))
            return psMat.compose(psMat.translate(-cx, -cy), psMat.compose(about, psMat.translate(cx + dx, cy + dy)))
        # 부품마다 따로 펼쳐 감김을 그 자리에서 바로잡는다. 다 모은 뒤 한꺼번에
        # correctDirection 을 부르면 겹친 윤곽(⎿ 의 두 획이 만나는 모서리)을 구멍으로
        # 잘못 보아 그 자리가 하얗게 빠진다.
        flip = sx * sy < 0
        for contour in _part_contours(font, src, place(sx, sy), reverse=flip,
                                      weight=(part["outline"]["grow"] if "outline" in part else None),
                                      fill=part.get("fill", False), clip=part.get("clip"),
                                      clip_center=part.get("clipFrom") == "center"):
            lay += contour
        if part.get("ring"):
            # 고리 — 같은 부품을 지름이 기준 글리프 획 폭의 두 배만큼 작게 한 번 더,
            # 거꾸로 감아 구멍으로 넣는다. 획 폭을 굵기마다 그 글꼴의 획(| 의 폭)에서
            # 재므로 테두리가 본문 굵기를 따른다.
            ref = font[cp(part["ring"])]
            rx0, _, rx1, _ = ref.boundingBox()
            stroke = rx1 - rx0
            outer = (xmax - xmin) * abs(sx)
            k = max(outer - 2 * stroke, 1) / outer
            for contour in _part_contours(font, src, place(sx * k, sy * k), reverse=not flip):
                lay += contour
        if "outline" in part:
            # 속 빈 모양 — 부품을 grow 만큼 굵힌 것이 바깥, wall 만큼 안쪽이 구멍
            o = part["outline"]
            wall = o["wall"]
            if isinstance(wall, str):         # 기준 글리프의 획 두께 — 굵기마다 따라간다
                wall = _stem(font, wall)
            wall *= o.get("wallScale", 1)
            for contour in _part_contours(font, src, place(sx, sy), reverse=not flip,
                                          weight=o["grow"] - 2 * wall):
                lay += contour
    glyph.foreground = lay
    if spec.get("merge", True):
        # 겹친 부품을 한 몸으로 — 구멍(고리·속 빈 모양)은 그대로. 부품이 겹치지 않으면 merge: false 로
        # 건너뛴다: FontForge 는 기울어진 △ 의 구멍 안에 든 막대를 지우기도 한다 (⚠ 이탤릭).
        glyph.removeOverlap()
    # 오린 경계에서 떨어져 나온 부스러기(가로세로 몇 유닛)는 버린다
    kept = fontforge.layer()
    kept.is_quadratic = glyph.foreground.is_quadratic
    for contour in glyph.foreground:
        x0, y0, x1, y1 = contour.boundingBox()
        if x1 - x0 >= 8 or y1 - y0 >= 8:
            kept += contour
    glyph.foreground = kept
    if spec.get("embolden"):
        glyph.changeWeight(_width(font, spec["embolden"]))
        # 뾰족한 모서리에 먼지 윤곽이 남는다 (ExtraLightItalic ␤ 의 N 에 3×5 셋).
        # 조립 부품 가운데 가장 작은 점자 점도 40 이 넘는다.
        lay = glyph.foreground
        boxes = [c.boundingBox() for c in lay]
        if any(b[2] - b[0] < 8 and b[3] - b[1] < 8 for b in boxes):
            out = fontforge.layer()
            out.is_quadratic = lay.is_quadratic
            for c, b in zip(lay, boxes):
                if not (b[2] - b[0] < 8 and b[3] - b[1] < 8):
                    out += c
            glyph.foreground = out
    glyph.correctDirection()
    if "width" in spec:
        glyph.width = ctx.width_value(spec["width"], source_half)
    else:
        first = spec["parts"][0]
        glyph.width = (font[first["glyph"]] if "glyph" in first else font[cp(first["cp"])]).width
    if spec.get("center", True):
        center_in_width(glyph)


@op("round")
def op_round(ctx, font, spec, source_half):
    for glyph in font.glyphs():
        if worth(glyph):
            glyph.round()


@op("removeLookups")
def op_remove_lookups(ctx, font, spec, source_half):
    tags = tuple(spec["tags"])
    for lookup in font.gpos_lookups:
        if any(tag in lookup for tag in tags):
            font.removeLookup(lookup)


@op("fitLineBox")
def op_fit_line_box(ctx, font, spec, source_half):
    """글리프를 목표 행 박스(ascent + descent)에 맞춘다.

    Powerline 구분자용이다. 구분자는 행 박스 전체를 덮어야 세로로 이어 붙였을 때
    틈이 생기지 않는다. 소스가 다른 행 박스 기준으로 그려져 있고 fit 단계에서
    한 번 축소됐으므로 (undoScale) 그만큼 되돌려서 맞춘다.
    """
    vertical = ctx.recipe["target"]["vertical"]
    undo = spec.get("undoScale", 100) / 100
    src_em = spec["srcAscent"] + spec["srcDescent"]
    line_em = vertical["ascent"] + vertical["descent"]
    scale_y = line_em / (src_em * undo)
    move_y = spec["srcDescent"] * undo * scale_y - vertical["descent"]
    for glyph in selected_glyphs(font, spec):
        width = glyph.width
        glyph.transform(psMat.scale(1, scale_y))
        glyph.transform(psMat.translate(0, move_y))
        glyph.width = width


def run(ctx, font, ops, source_half=None):
    for spec in ops or []:
        handler = OPS.get(spec["op"])
        if handler is None:
            raise ValueError("알 수 없는 op: %r (쓸 수 있는 것: %s)"
                             % (spec["op"], ", ".join(sorted(OPS))))
        handler(ctx, font, spec, source_half)


def pick_boxes(glyph, boxes, em):
    """상자에 자면 상자가 온전히 드는 윤곽 — (번호들, 왼끝, 오른끝) 또는 None.

    boxes 는 [x0, y0, x1, y1(, 최소 가로 폭)] 이고 x 는 글자 폭, y 는 em 에 대한 비율.
    """
    width = glyph.width or em
    out = []
    for i, contour in enumerate(glyph.foreground):
        xs = [p.x for p in contour]
        ys = [p.y for p in contour]
        lo_x, hi_x = min(xs) / width, max(xs) / width
        lo_y, hi_y = min(ys) / em, max(ys) / em
        for b in boxes:
            x0, y0, x1, y1 = b[:4]
            span = b[4] if len(b) > 4 else 0      # 최소 가로 폭 (글자 폭 대비)
            if (x0 <= lo_x and hi_x <= x1 and y0 <= lo_y and hi_y <= y1
                    and hi_x - lo_x >= span):
                out.append(i)
                break
    if not out:
        return None
    xs = [p.x for i in out for p in glyph.foreground[i]]
    return out, min(xs), max(xs)


def lighter_glyphs(ctx, code, split_tmpl):
    """같은 글자의 가는 굵기 글리프들 — 가장 가는 것부터 지금 굵기 바로 앞까지."""
    if not split_tmpl:
        return []
    me = ctx.style
    same = [st for st in ctx.recipe["styles"]
            if st.get("italic", False) == me.get("italic", False)
            and st["weight"] < me["weight"]]
    out = []
    for st in sorted(same, key=lambda st: st["weight"]):
        path = ctx.path(split_tmpl, st)
        f = _PRISTINE.get(path)
        if f is None:
            f = _PRISTINE[path] = _open_pristine(path)
        if code in f:
            out.append(f[code])
    return out


_PRISTINE = {}                  # 안내로 빌려 연 **손대지 않은** 소스 글꼴


def _open_pristine(path):
    """소스 글꼴을 **따로** 연다 — 빌드가 열어 고치고 있는 글꼴과 섞이지 않게.

    FontForge 는 이미 열린 파일을 다시 열면 같은 글꼴 객체를 돌려준다. 그러면 앞
    굵기를 지으며 op 이 이미 고친 글리프를 안내로 쓰게 된다 (祈 ExtraLight 가 고쳐진
    Thin 의 祈 를 안내 삼아 礻 삐침을 남겼다). 그리고 빌드가 그 글꼴을 닫으면 여기
    들고 있던 것도 닫힌다. 그래서 임시 자리에 복사해 그것을 연다.
    """
    import shutil
    import tempfile
    d = tempfile.mkdtemp(prefix="hapchija-guide-")
    q = os.path.join(d, os.path.basename(path))
    shutil.copyfile(path, q)
    return fontforge.open(q)


def isolate_part(ctx, glyph, code, bxs, split_tmpl, em):
    """상자 자리의 성분(변)과 나머지(방)를 뗀다 — (조각 윤곽들, 남길 윤곽들, 왼끝, 오른끝).

    상자로 고른 윤곽 수가 가장 가는 굵기와 같으면 그대로 뗀다. 다르면 성분이 방과
    녹아붙은 것이다 — 같은 수가 골라지는 가장 굵은 가는 굵기를 안내로 삼아
    outline.split_glyph 로 가른다. 못 떼면 None.
    """
    got = pick_boxes(glyph, bxs, em)
    thin = lighter_glyphs(ctx, code, split_tmpl)
    base = pick_boxes(thin[0], bxs, em) if thin else None
    cs = list(glyph.foreground)
    if got is not None and (base is None or len(got[0]) == len(base[0])):
        part = [cs[i] for i in got[0]]
        rest = [c for i, c in enumerate(cs) if i not in got[0]]
        return part, rest, got[1], got[2]
    if base is None:
        return None
    guide = None
    for g in reversed(thin):               # 지금 굵기에 가장 가까운 떨어진 굵기
        gp = pick_boxes(g, bxs, em)
        if gp is not None and len(gp[0]) == len(base[0]):
            gcs = list(g.foreground)
            guide = ([gcs[i] for i in gp[0]], [c for i, c in enumerate(gcs) if i not in gp[0]])
            break
    if guide is None:
        return None
    part, rest = O.split_glyph(cs, guide[0], guide[1])
    if not part or not rest:
        return None
    xs = [p.x for c in part for p in c]
    return part, rest, min(xs), max(xs)


def _polys(contours):
    return [[(p.x, p.y) for p in O._flat_pts(c)] for c in contours]


def _hits(a, bs, room):
    """다각형 a 가 다각형들 bs 와 겹치거나 `room` 안으로 다가가는가 (변끼리의 거리로)."""
    def seg_d(p, q, r, s):
        def pd(x, y, u, v, w, z):
            dx, dy = w - u, z - v
            L2 = dx * dx + dy * dy
            t = 0.0 if not L2 else max(0.0, min(1.0, ((x - u) * dx + (y - v) * dy) / L2))
            return math.hypot(x - (u + t * dx), y - (v + t * dy))
        d1 = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        d2 = (q[0] - p[0]) * (s[1] - p[1]) - (q[1] - p[1]) * (s[0] - p[0])
        d3 = (s[0] - r[0]) * (p[1] - r[1]) - (s[1] - r[1]) * (p[0] - r[0])
        d4 = (s[0] - r[0]) * (q[1] - r[1]) - (s[1] - r[1]) * (q[0] - r[0])
        if (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0):
            return 0.0
        return min(pd(*p, *r, *s), pd(*q, *r, *s), pd(*r, *p, *q), pd(*s, *p, *q))

    def inside(pt, poly):
        x, y = pt
        got = False
        for k in range(len(poly)):
            (x1, y1), (x2, y2) = poly[k - 1], poly[k]
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                got = not got
        return got

    ax = [p[0] for p in a]; ay = [p[1] for p in a]
    for b in bs:
        bx = [p[0] for p in b]; by = [p[1] for p in b]
        if max(ax) + room < min(bx) or max(bx) + room < min(ax) or \
                max(ay) + room < min(by) or max(by) + room < min(ay):
            continue
        if inside(a[0], b) or inside(b[0], a):
            return True
        for i in range(len(a)):
            for j in range(len(b)):
                if seg_d(a[i - 1], a[i], b[j - 1], b[j]) <= room:
                    return True
    return False


def _clear_right(layer, body, room, step=2.0):
    """오른쪽 아래 획이 몸과 `room` 안으로 닿지 않을 때까지 `step` 유닛씩 줄인다."""
    cs = list(layer)
    k = _right_stroke(cs)
    if k is None:
        return layer
    bodies = _polys(list(body))
    h = O.box(cs[k])[3] - O.box(cs[k])[2]
    cut = 0.0
    cur = layer
    while _hits(_polys([list(cur)[k]])[0], bodies, room) and cut < 0.7 * h:
        cut += step
        cur = _shorten_right(layer, cut)
    return cur


def _style_ctx(ctx, style):
    import copy
    c = copy.copy(ctx)
    c.style = style
    return c


def _dot_length(ctx, style, code, bxs, split_tmpl, em):
    """그 굵기(style) 소스에서 글자 code 의 示 오른쪽 점 세로 길이."""
    path = ctx.path(split_tmpl, style)
    f = _PRISTINE.get(path)
    if f is None:
        f = _PRISTINE[path] = _open_pristine(path)
    if code not in f:
        return None
    iso = isolate_part(_style_ctx(ctx, style), f[code], code, bxs, split_tmpl, em)
    if not iso:
        return None
    k = _right_stroke(list(iso[0]))
    if k is None:
        return None
    b = O.box(list(iso[0])[k])
    return b[3] - b[2]


def _ramp_length(ctx, donor_code, ref_code, bxs, split_tmpl, em):
    me = ctx.style
    same = sorted((st for st in ctx.recipe["styles"]
                   if st.get("italic", False) == me.get("italic", False)),
                  key=lambda st: st["weight"])
    lo, hi = same[0], same[-1]
    a = _dot_length(ctx, lo, donor_code, bxs, split_tmpl, em)
    # ref 가 숫자면 가장 굵은 굵기의 길이(유닛) 그대로, 글자면 그 글자의 가장 굵은 굵기에서 잰다
    b = float(ref_code) if isinstance(ref_code, float) or (isinstance(ref_code, int) and ref_code < 0x3000) \
        else _dot_length(ctx, hi, ref_code, bxs, split_tmpl, em)
    if a is None or b is None or hi["weight"] == lo["weight"]:
        return None
    t = (me["weight"] - lo["weight"]) / float(hi["weight"] - lo["weight"])
    return a + (b - a) * t


def _right_stroke(cs):
    """조각 윤곽들 가운데 **오른쪽 아래 획**(示 의 오른쪽 점)의 번호 — 가장 넓은 윤곽(긴
    가로획)을 뺀 나머지 가운데 왼끝이 가장 오른쪽인 것."""
    if len(cs) < 2:
        return None
    boxes = [O.box(c) for c in cs]
    widest = max(range(len(cs)), key=lambda i: boxes[i][1] - boxes[i][0])
    rest = [i for i in range(len(cs)) if i != widest]
    return max(rest, key=lambda i: boxes[i][0])


def _shorten_right(layer, by):
    """조각에서 **오른쪽 아래 획**(示 의 오른쪽 점)을 `by` 유닛 줄인다 — 늘이거나 누르지 않고.

    가장 넓은 윤곽(긴 가로획)을 뺀 나머지 가운데 왼끝이 가장 오른쪽인 것이 그 획이다.
    획의 축(위쪽 복판 → 아래쪽 복판)을 재고, **아래 끝의 점들만** 축을 따라 `by` 만큼
    위로 끌어올린다. 굵기와 기울기는 그대로다.
    """
    cs = list(layer)
    k = _right_stroke(cs)
    if k is None or by == 0:
        return layer                                     # by < 0 이면 그만큼 늘인다 (축을 따라 내림)
    x0, x1, y0, y1 = O.box(cs[k])
    h = y1 - y0
    pts = [(p.x, p.y) for p in cs[k]]
    top = [p for p in pts if p[1] >= y1 - 0.2 * h]
    bot = [p for p in pts if p[1] <= y0 + 0.2 * h]
    tx, ty = sum(p[0] for p in top) / len(top), sum(p[1] for p in top) / len(top)
    bx, by_ = sum(p[0] for p in bot) / len(bot), sum(p[1] for p in bot) / len(bot)
    L = math.hypot(tx - bx, ty - by_) or 1.0
    ux, uy = (tx - bx) / L, (ty - by_) / L              # 아래 끝 → 위 끝
    cut = y0 + 0.35 * h                                  # 아래 끝으로 치는 점들
    step = by / uy if uy > 0.3 else by                    # 세로 길이로 by 만큼 줄도록
    c = cs[k].dup()
    for p in c:
        if p.y <= cut:
            p.x += ux * step
            p.y += uy * step
    out = fontforge.layer()
    out.is_quadratic = layer.is_quadratic
    for i, cc in enumerate(cs):
        out += c if i == k else cc
    return out


@op("graftPart")
def op_graft_part(ctx, font, spec, source_half):
    """한 글자의 일부를 떼고, 다른 글자의 같은 자리 조각을 옮겨 붙인다.

    일본 표준은 상용한자에서만 부수를 약자로 바꾸고 나머지는 전통 자형으로 둔다.
    그래서 한 글꼴 안에 두 모양이 다 들어 있다. 神 의 礻 를 떼고 祀 의 示 를
    옮겨 붙이면, 한국에서 쓰는 자형이 그 글꼴 자신의 획으로 나온다. 부수 글리프
    (U+2EAC 등)를 눌러 넣는 것과 다르다. 그쪽은 방 너비에 맞추려고 가로로 43%
    까지 눌러야 해서 세로획이 가로획의 절반이 된다.

        {"op": "graftPart", "from": "7940", "fit": "width",
         "boxes": [[0, -0.15, 0.45, 0.90]], "cps": ["793e", "795e"]}

    boxes 는 [x0, y0, x1, y1] 이고 x 는 글자 폭, y 는 em 에 대한 비율이다. 다섯째
    값을 주면 그 윤곽이 가져야 할 최소 가로 폭이다. 辶 의 쓸어내림처럼 글자 폭을
    가로지르는 조각은 상자도 넓어야 하는데, 그러면 오른쪽 성분의 속공간까지
    딸려 온다. 최소 폭을 걸어 그것을 막는다.
    윤곽의 자면 상자가 어느 box 안에 온전히 들어가면 그 윤곽을 조각으로 본다.
    기증자에서도 같은 box 로 고른다 (donorBoxes 로 따로 줄 수 있다).

    fit 이 "left" 면 크기를 건드리지 않고 **왼끝만 맞춰** 옮긴다. fit 이 "gap"
    이면 왼끝을 맞추고, 오른끝이 **남은 몸에서 `gap` 만큼 앞** 에 오도록 가로로만
    맞춘다 (`gap` 은 em 대비 비율 · 음수면 그만큼 파고든다).

        {"op": "graftPart", "from": "79ae", "fit": "gap", "gap": 0.012,
         "boxes": [[0, -0.15, 0.48, 0.90]], "cps": ["793e"]}      社 — 示 ← 禮

    示 는 礻 보다 좁은 것이 제 모양이라 잉크 폭("width")에 맞추면 1.25배까지
    늘어나 세로획이 굵어진다. 그렇다고 그대로 두면("left") 방과의 사이가 글자마다
    들쭉날쭉해진다. 그래서 방과의 틈을 정해 거기에 맞춘다.

    fit 이 "width" 면 떼어 낸 자리의 잉크 폭에 맞춰 가로로만 조절한다. 세로는
    건드리지 않는다. 같은 크기의 글자끼리라 배율이 1.0 근처로 나오고, 그래서
    획 두께가 보존된다. "none" 이면 그대로 옮긴다 (辶 처럼 글자 폭을 가로지르는
    조각은 자리가 이미 같다).
    """
    donor_cp = cp(spec["from"])
    if donor_cp not in font:
        return
    em = ctx.em_ascent + ctx.em_descent
    fit = spec.get("fit", "width")

    def pick(glyph, bxs):
        return pick_boxes(glyph, bxs, em)

    boxes = spec["boxes"]
    donor = font[donor_cp]
    d_boxes = spec.get("donorBoxes", boxes)

    # ── 녹아붙은 굵기 (split) ────────────────────────────────────────────────
    # 굵어지면 礻 의 세로획이 방과 한 윤곽으로 녹아 상자에 온전히 들지 않는다. 그러면
    # 상자로는 礻 를 못 고르고 그 굵기를 건너뛰었다 (示 변 12자 가운데 Medium 11 ·
    # SemiBold 6 · Bold 3 자만 바뀌었다). `split` 에 이 소스의 경로 틀을 주면, 상자로
    # 고른 윤곽 수가 **가장 가는 굵기와 같은 가장 굵은 가는 굵기**를 안내로 삼아
    # outline.split_glyph 로 변·방을 떼어 방을 남긴다 (기증자도 같다).
    #   "split": "IBM-Plex-Sans-JP/IBMPlexSansJP-{cjkSrc}.ttf"
    split_tmpl = spec.get("split")

    def isolate(glyph, code, bxs):
        return isolate_part(ctx, glyph, code, bxs, split_tmpl, em)

    got_d = isolate(donor, donor_cp, d_boxes)
    if got_d is None:
        return
    d_part, _, d_x0, d_x1 = got_d

    done = 0
    for glyph in selected_glyphs(font, spec):
        got = isolate(glyph, glyph.unicode, boxes)
        if got is None or not got[1]:
            continue                      # 방을 못 고르면 건드리지 않는다
        _, rest_cs, t_x0, t_x1 = got
        kept = fontforge.layer()
        kept.is_quadratic = glyph.foreground.is_quadratic
        for contour in rest_cs:
            kept += contour
        scale = 1.0
        if fit == "width" and d_x1 > d_x0:
            scale = (t_x1 - t_x0) / (d_x1 - d_x0)
        elif fit == "gap" and d_x1 > d_x0:
            # 한쪽 끝은 떼어 낸 자리 그대로 두고, 다른 끝은 **남은 몸에서 `gap`
            # 만큼 떨어지게** 둔다. 示 는 礻 보다 좁은 것이 제 모양이라 礻 의 잉크
            # 폭에 맞추면 1.25배까지 늘어나고, 그대로 두면 방과의 사이가 글자마다
            # 들쭉날쭉해진다 — 남길 몸에서 재어 맞춘다.
            #   gapFrom "right" (기본) 왼끝을 두고 오른끝을 남은 몸 왼쪽에 맞춘다 (示)
            #   gapFrom "left"        오른끝을 두고 왼끝을 남은 몸 오른쪽에 맞춘다 (慨 의 旣)
            # `gapAbove` 를 주면 방의 왼끝을 그 높이(em 대비 y) 위에서만 잰다. 방의 삐침이
            # 변 밑으로 뻗는 글자(祝 의 儿)는 맨 아래 다리 끝이 가장 왼쪽이라, 거기에 맞추면
            # 示 가 좁게 눌린다 — 示 의 가로획이 있는 높이에서 재야 한다.
            above = spec.get("gapAbove")
            if above is None:
                rest = [p.x for c in kept for p in c]
            else:
                rest = [p.x for c in kept for p in O._flat_pts(c) if p.y >= above * em]
            if not rest:
                continue
            if spec.get("gapFrom", "right") == "left":
                t_x0 = max(rest) + spec.get("gap", 0.0) * em
                want = t_x1 - t_x0
            else:
                want = (min(rest) - spec.get("gap", 0.0) * em) - t_x0
            if want <= 0:
                continue
            scale = want / (d_x1 - d_x0)
        if not 0.8 < scale < 1.25:
            continue
        part = fontforge.layer()
        part.is_quadratic = donor.foreground.is_quadratic
        for contour in d_part:
            part += contour.dup()
        if spec.get("shortenRight"):
            part = _shorten_right(part, spec["shortenRight"] * em)
        if spec.get("rightDotClear") is not None:
            # 오른쪽 점이 남은 몸과 겹치면, 겹치지 않을 만큼만 줄인다 (늘이지 않는다).
            # 값은 남길 틈(em 대비). 祉 — 示 의 오른쪽 점이 止 의 밑가로획에 닿는다.
            part = _clear_right(part, kept, spec["rightDotClear"] * em)
        if spec.get("rightDotRamp"):
            # 오른쪽 점 길이를 굵기 따라 **고르게** 바꾼다: 가장 가는 굵기는 기증자 제 길이,
            # 가장 굵은 굵기는 `rightDotRamp` 글자의 가장 굵은 굵기 길이, 그 사이는 굵기
            # 값(weight)에 비례한다. 祉 — Thin 은 祋 그대로, Bold 는 祖 와 같게.
            ramp = spec["rightDotRamp"]
            want = _ramp_length(ctx, donor_cp, ramp if isinstance(ramp, (int, float)) else cp(ramp),
                                d_boxes, split_tmpl, em)
            mk = _right_stroke(list(part))
            if want is not None and mk is not None:
                mb = O.box(list(part)[mk])
                part = _shorten_right(part, (mb[3] - mb[2]) - want)
        if spec.get("rightDotLike"):
            # 오른쪽 점을 다른 글자의 示 오른쪽 점 **세로 길이**에 맞춘다. 짧으면 아래 끝을
            # 제 축을 따라 내리고 길면 올린다 — 배율로 늘이지 않으니 굵기·기울기는 그대로다.
            # 굵기마다 그 글자의 같은 굵기에서 재므로 맞출 길이가 굵기 따라 맞는다.
            ref_cp = cp(spec["rightDotLike"])
            ref = isolate_part(ctx, font[ref_cp], ref_cp, d_boxes, split_tmpl, em) \
                if ref_cp in font else None
            if ref:
                rk, mk = _right_stroke(list(ref[0])), _right_stroke(list(part))
                if rk is not None and mk is not None:
                    rb, mb = O.box(list(ref[0])[rk]), O.box(list(part)[mk])
                    by = (mb[3] - mb[2]) - (rb[3] - rb[2])
                    if spec.get("rightDotGrow", True) or by > 0:   # false 면 줄이기만
                        part = _shorten_right(part, by)
        if fit == "left" and spec.get("gapTo") is not None:
            # 늘이지 않고 **옮기기만** 해서 방과의 간격을 `gapTo`(em 대비)로 맞춘다.
            # 한 기증자를 여덟 굵기에 쓰면 간격이 굵기 따라 줄지 않는다 — 굵기마다 값을 준다.
            rest_x = [p.x for c in kept for p in c]
            if rest_x:
                t_x0 = min(rest_x) - spec["gapTo"] * em - (d_x1 - d_x0)
        if fit in ("width", "left", "gap"):
            # "width" 는 떼어 낸 자리의 잉크 폭에 맞춰 가로로만 늘이고, "left" 는
            # 늘이지 않고 **왼끝만 맞춰 옮긴다**. 示 는 礻 보다 좁아서(341 ↔ 426)
            # 폭에 맞추면 1.25배가 되어 세로획이 굵어진다 — 한국 자형의 示 는
            # 본디 그 폭이므로 옮기기만 해야 한다.
            part.transform(psMat.compose(
                psMat.translate(-d_x0, 0),
                psMat.compose(psMat.scale(scale, 1.0), psMat.translate(t_x0, 0))))
        for contour in part:
            kept += contour
        width = glyph.width
        glyph.foreground = kept
        glyph.correctDirection()   # 윤곽을 다시 담으면 안팎 방향이 흐트러져 속공간이 메워진다
        if spec.get("merge"):
            # 옮겨 붙인 조각이 남은 몸과 겹치면 두 윤곽을 하나로 합친다 (祈 — 示 의
            # 오른쪽 점이 斤 의 丿 에 닿는 굵기). 겹친 채 두면 윤곽이 서로 파고든다.
            glyph.removeOverlap()
        glyph.width = width
        done += 1
    if done:
        print("graftPart: %d 자 (기증자 U+%04X)" % (done, donor_cp))


# 자형을 손보는 op 은 따로 모아 두었다. 여기서 들여와 OPS 에 등록한다.
from . import forms       # noqa: E402,F401  (op 등록이 목적이다)
