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

    def pick(glyph, boxes):
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

    boxes = spec["boxes"]
    donor = font[donor_cp]
    taken = pick(donor, spec.get("donorBoxes", boxes))
    if taken is None:
        return
    d_idx, d_x0, d_x1 = taken

    done = 0
    for glyph in selected_glyphs(font, spec):
        got = pick(glyph, boxes)
        if got is None or len(got[0]) == len(glyph.foreground):
            continue                      # 방을 못 고르면 건드리지 않는다
        t_idx, t_x0, t_x1 = got
        kept = fontforge.layer()
        kept.is_quadratic = glyph.foreground.is_quadratic
        for i, contour in enumerate(glyph.foreground):
            if i not in t_idx:
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
            rest = [p.x for c in kept for p in c]
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
        for i in d_idx:
            part += donor.foreground[i]
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
        glyph.width = width
        done += 1
    if done:
        print("graftPart: %d 자 (기증자 U+%04X)" % (done, donor_cp))


# 자형을 손보는 op 은 따로 모아 두었다. 여기서 들여와 OPS 에 등록한다.
from . import forms       # noqa: E402,F401  (op 등록이 목적이다)
