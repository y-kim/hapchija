"""fit 전략: 소스 글꼴을 목표 폭에 맞춘다.

    halfScale    라틴 고정폭과 심볼용. 일정 비율로 줄이고 반각 폭에 맞춘다.
    cjkUniform   CJK 소스의 전각 폭이 한 가지로 통일된 경우.
    cjkClassify  글리프마다 폭이 제각각인 경우. 한 번 훑어 세 갈래로 나눈다.
"""

from __future__ import annotations

import os

import fontforge
import psMat

from . import ops
from .recipe import cp, cp_range


def fit_half_scale(ctx, font, spec, shared):
    sx, sy = ops.as_scale(spec["scale"])
    # selection.byGlyphs 가 아니라 glyphs() 로 돈다. byGlyphs 는 인코딩 슬롯마다
    # 글리프를 내주므로, 여러 코드포인트가 한 글리프를 공유하면(Consolas 의
    # space/U+00A0, hyphen/U+2010/U+00AD 등) 그 글리프가 두세 번 변환된다.
    # 스페이스 폭이 두 번 줄면 아래 sourceWidth 역산이 틀어져 라틴 전체가 옆으로
    # 밀리고, 공유 글리프 자체도 작아진다.
    for glyph in font.glyphs():
        glyph.transform(psMat.scale(sx, sy))

    ops.run(ctx, font, spec.get("opsBeforeWidth"))

    # 소스의 반각 폭. 안 적어 두면 스페이스에서 읽는다 (set_em 뒤 기준).
    source_width = spec.get("sourceWidth")
    if source_width is None and 0x20 in font:
        source_width = font[0x20].width / sx
    move_x = (ctx.half_width - source_width * sx) / 2 if source_width else 0

    for glyph in font.glyphs():
        # 폭 0 인 글리프(결합 문자 등)는 건드리지 않는다
        if not ops.worth(glyph) or glyph.width == 0:
            continue
        if move_x:
            glyph.transform(psMat.translate(move_x, 0))
        glyph.width = ctx.half_width


def fit_cjk_uniform(ctx, font, spec, shared):
    """set_em 이 이미 목표 em 으로 맞춰 놨으므로 지금 폭을 읽어서 판단한다."""
    threshold = spec.get("fullWidthThreshold", 1.5)
    for glyph in font.glyphs():
        if not ops.worth(glyph) or glyph.width <= 0:
            continue
        full = glyph.width > ctx.half_width * threshold
        target = ctx.full_width if full else ctx.half_width
        if spec.get("scaleToFit") and glyph.width != target:
            ops.transform_about_center(glyph, psMat.scale(target / glyph.width, 1))
        glyph.width = target
        ops.center_in_width(glyph)


def fit_cjk_classify(ctx, font, spec, shared):
    half_set, full_set, others_set = shared["widths"]
    source_full = spec["sourceFullWidth"]

    move_x = (ctx.full_width - source_full) / 2
    for code in sorted(full_set):
        if code not in font:
            continue
        glyph = font[code]
        glyph.transform(psMat.translate(move_x, 0))
        glyph.width = ctx.full_width

    # 너무 넓은 글리프는 가로로 눌러 준다.
    # .pe 가 정수 나눗셈이었으므로 배율 계산을 그대로 맞춘다.
    for code in sorted(others_set):
        if code not in font:
            continue
        glyph = font[code]
        if glyph.width > source_full:
            ops.transform_about_center(
                glyph, psMat.scale((source_full * 100 // glyph.width) / 100, 1)
            )

    force_full = {cp(c) for c in spec.get("forceFull", [])}
    full_exclude = {cp(c) for c in spec.get("fullExclude", [])}
    for glyph in font.glyphs():
        code = glyph.unicode
        if code is None or code < 0 or not ops.worth(glyph):
            continue
        selected = code not in half_set and code not in full_set
        if code in force_full:
            selected = True
        if code in full_exclude:
            selected = False
        if selected:
            glyph.width = ctx.full_width
            ops.center_in_width(glyph)

    half_exclude = set(force_full)
    he = spec.get("halfExclude", {})
    for pair in he.get("ranges", []):
        half_exclude.update(cp_range(pair))
    half_exclude.update(cp(c) for c in he.get("single", []))
    half_exclude.update(cp(c) for c in spec.get("halfExcludeMore", []))

    for code in sorted(half_set - half_exclude):
        if code not in font:
            continue
        glyph = font[code]
        glyph.width = ctx.half_width
        ops.center_in_width(glyph)


FITS = {
    "halfScale": fit_half_scale,
    "cjkUniform": fit_cjk_uniform,
    "cjkClassify": fit_cjk_classify,
}


def apply(ctx, font, spec, shared):
    mode = spec["mode"]
    if mode not in FITS:
        raise ValueError("알 수 없는 fit: %r (쓸 수 있는 것: %s)"
                         % (mode, ", ".join(sorted(FITS))))
    FITS[mode](ctx, font, spec, shared)


def classify_widths(ctx, source, style, base_cps):
    """CJK 소스의 글리프를 폭에 따라 세 갈래로 나눈다.

    한 두께로 한 번만 분류하고 모든 두께에 같은 결과를 쓴다. 두께마다 기호 폭이
    조금씩 달라서, 두께별로 분류하면 같은 글자가 두께에 따라 폭이 달라진다.
    """
    fit = source["fit"]
    path = ctx.path(source["path"], style)
    print("Width classify (%s)" % os.path.basename(path))
    font = fontforge.open(path)
    source_full = fit["sourceFullWidth"]
    half, full, others = set(), set(), set()
    for glyph in font.glyphs():
        code = glyph.unicode
        if code is None or code < 0 or not ops.worth(glyph) or glyph.width <= 0:
            continue
        if code in base_cps:
            continue
        if glyph.width < ctx.half_width:
            half.add(code)
        elif glyph.width == source_full:
            full.add(code)
        else:
            others.add(code)
    font.close()
    print("  half=%d full=%d others=%d" % (len(half), len(full), len(others)))
    return half, full, others
