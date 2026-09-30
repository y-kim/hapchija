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
    """
    code = cp(spec["cp"])
    glyph = font.createChar(code)
    glyph.clear()
    for part in spec["parts"]:
        # 부품은 코드포인트로, 또는 글리프 이름으로 지정한다. 분수의 one.numr
        # 처럼 cmap 에 없는 부품 글리프를 쓸 때가 있다.
        src = font[part["glyph"]] if "glyph" in part else font[cp(part["cp"])]
        sx, sy = as_scale(part.get("scale", 100))
        # 부품은 자기 자면 중심을 기준으로 줄인다. 원점 기준이면 축소 비율이 다른
        # 부품끼리 자리가 어긋난다. 그 뒤 dx·dy 만큼 옮긴다.
        xmin, ymin, xmax, ymax = src.boundingBox()
        cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
        matrix = psMat.compose(psMat.translate(-cx, -cy), psMat.compose(psMat.scale(sx, sy), psMat.translate(cx + part.get("dx", 0), cy + part.get("dy", 0))))
        glyph.addReference(src.glyphname, matrix)
    glyph.unlinkRef()
    glyph.correctDirection()      # 음수 배율(뒤집기)로 뒤집힌 윤곽 방향을 바로잡는다
    if "width" in spec:
        glyph.width = ctx.width_value(spec["width"], source_half)
    else:
        first = spec["parts"][0]
        glyph.width = (font[first["glyph"]] if "glyph" in first else font[cp(first["cp"])]).width
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
