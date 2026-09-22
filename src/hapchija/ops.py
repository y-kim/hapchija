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
