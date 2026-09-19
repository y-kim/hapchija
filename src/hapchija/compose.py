"""합성 단계. FontForge 가 필요하다.

    python3 -m hapchija.compose --recipe ... [--out DIR] [--debug]
    fontforge -script .../compose.py --recipe ...   (바인딩이 없을 때)

레시피의 sources 는 우선순위 순서다. role=base 인 소스가 최종 글꼴의 뼈대가
되고, 나머지는 parts/ 에 따로 내보낸다. 힌팅을 넣은 뒤 finalize 가 합친다.
"""

from __future__ import annotations

import argparse
import os

import fontforge

from . import fits, ops, recipe as R


def available_codepoints(ctx, source, style):
    """이 소스가 내놓을 수 있는 코드포인트. keepRanges 가 있으면 그 범위로 제한한다."""
    path = ctx.path(source["path"], style)
    font = fontforge.open(path)
    cps = ops.codepoints_of(font)
    font.close()
    if source.get("keepRanges"):
        keep = set()
        for pair in source["keepRanges"]:
            keep.update(R.cp_range(pair))
        cps &= keep
    return cps


def assign_codepoints(ctx, sources, style):
    """우선순위대로 코드포인트를 나눠 준다.

    앞선 소스가 이미 가진 코드포인트는 뒤 소스에서 뺀다. 이렇게 하지 않으면
    병합할 때 같은 글자의 글리프가 소스 수만큼 쌓여서, cmap 이 하나만 쓰는데도
    TrueType 의 글리프 수 상한(65,535)을 넘긴다.
    """
    assigned, claimed = {}, set()
    for source in sources:
        cps = available_codepoints(ctx, source, style)
        mine = cps - claimed
        assigned[source["id"]] = mine
        claimed |= mine
        print("  %-6s 보유 %6d  신규 %6d  누적 %6d"
              % (source["id"], len(cps), len(mine), len(claimed)))
    return assigned


def build_source(ctx, source, shared, keep_cps=None):
    path = ctx.path(source["path"])
    print("Open " + path)
    font = fontforge.open(path)

    if source.get("keepRanges"):
        keep = set()
        for pair in source["keepRanges"]:
            keep.update(R.cp_range(pair))
        for glyph in font.glyphs():
            if glyph.unicode is None or glyph.unicode not in keep:
                glyph.clear()

    hs = source.get("hiddenSpace")
    if hs and ctx.variants.get("hiddenSpace"):
        code = R.cp(hs["cp"])
        if code in font:
            font[code].clear()
        font.mergeFonts(ctx.path(hs["from"]))

    # 참조를 풀기 전에 돌려야 하는 op. 합성 글리프가 교체 대상을 참조로 물고
    # 있으므로, 교체는 여기서 해야 반영된다.
    ops.run(ctx, font, source.get("preOps"))

    ops.unlink_all(font)
    ops.set_em(font, ctx)

    if source.get("italicize") and ctx.style.get("italic"):
        font.selection.all()
        font.italicize(italic_angle=ctx.italic_angle)
        font.selection.none()

    # 이 소스에 배정된 코드포인트만 남긴다. 우선순위가 높은 소스가 가져간 것은
    # 여기서 비워야 병합 결과에 같은 글자의 글리프가 쌓이지 않는다.
    #
    # 유니코드가 없는 글리프도 같이 비운다. CJK 글꼴은 세로쓰기 변형 같은 것을
    # 수천 개씩 들고 있는데 (IBM Plex Sans JP 는 7,363 개), cmap 으로 닿을 수 없는데도
    # 병합 결과의 글리프 수만 늘린다. 뼈대(role=base)는 합자 등에 쓰일 수 있으므로
    # 그대로 둔다.
    if keep_cps is not None:
        drop_unencoded = source.get("role") != "base"
        for glyph in font.glyphs():
            codes = ops.glyph_codepoints(glyph)
            if not codes:
                if drop_unencoded:
                    glyph.clear()
            elif not (codes & keep_cps):
                glyph.clear()

    source_half = font[0x20].width if 0x20 in font else None
    ops.run(ctx, font, source.get("ops"), source_half)

    if source.get("fit"):
        fits.apply(ctx, font, source["fit"], shared)

    ops.run(ctx, font, source.get("opsAfter"), source_half)
    font.selection.none()
    return font


def subset_part(path, codepoints):
    """부품을 배정된 코드포인트만 남기고 잘라낸다.

    FontForge 의 glyph.clear() 는 윤곽만 비우고 cmap 항목은 남긴다. 빈 글리프가
    그대로 병합되면 글리프 수가 줄지 않아 TrueType 의 상한을 넘긴다.
    fontTools 로 확실히 잘라낸다.
    """
    from fontTools import subset

    o = subset.Options()
    o.drop_tables += ["vhea", "vmtx", "VORG", "cvt ", "fpgm", "prep", "DSIG", "meta"]
    o.layout_features = []
    o.notdef_outline = False
    o.recalc_bounds = False
    o.glyph_names = True
    f = subset.load_font(path, o)
    ss = subset.Subsetter(options=o)
    ss.populate(unicodes=sorted(codepoints))
    ss.subset(f)
    subset.save_font(f, path, o)


def font_names(rec, style, suffix):
    """RIBBI 네 칸에 들어가는 두께와 그렇지 않은 두께를 나눠 이름을 만든다.

    Regular / Bold / Italic / Bold Italic 은 한 패밀리의 네 칸을 쓰고,
    나머지 두께는 패밀리 이름에 두께를 붙여 별도 패밀리가 된다.
    """
    family = R.family_name(rec, suffix)
    short = family.replace(" ", "")
    name = style["name"]

    if style["italic"]:
        display = "Italic" if name == "Regular" else "%s Italic" % name
    else:
        display = name

    if name in ("Regular", "Bold"):
        familyname, subfamily = family, display
    else:
        familyname = "%s %s" % (family, name)
        subfamily = "Italic" if style["italic"] else "Regular"

    return {
        "short": short,
        "fontname": "%s-%s" % (short, style["file"]),
        "familyname": familyname,
        "fullname": "%s %s" % (family, display),
        "subfamily": subfamily,
        "typo_family": family,
        "typo_subfamily": display,
    }


def compose(ctx, base_font, suffix, out_dir):
    rec, style = ctx.recipe, ctx.style
    target = rec["target"]
    names = font_names(rec, style, suffix)

    font = fontforge.font()
    font.encoding = "UnicodeFull"
    ops.set_em(font, ctx)
    if style["italic"]:
        font.italicangle = ctx.italic_angle

    font.fontname = names["fontname"]
    font.familyname = names["familyname"]
    font.fullname = names["fullname"]
    font.copyright = rec["output"].get("copyright", "")
    font.version = rec["output"].get("version", "")
    font.weight = style["name"]
    font.appendSFNTName("English (US)", "SubFamily", names["subfamily"])
    font.appendSFNTName("English (US)", "Preferred Family", names["typo_family"])
    font.appendSFNTName("English (US)", "Preferred Styles", names["typo_subfamily"])

    font.os2_weight = style["weight"]
    font.os2_width = target.get("widthClass", 5)
    font.os2_fstype = 0
    font.os2_vendor = rec["output"].get("vendorId", "NONE")
    font.os2_family_class = rec["output"].get("ibmFamily", 0)

    p = target["panose"]
    font.os2_panose = (
        p["familyType"], p["serifStyle"], style["panoseWeight"], p["proportion"],
        p["contrast"], p["strokeVariation"], p["armStyle"], p["letterForm"],
        p["midline"], p["xHeight"],
    )

    tmp = os.path.join(out_dir, ".merge-base-%s.sfd" % style["file"])
    base_font.save(tmp)
    font.mergeFonts(tmp)
    os.remove(tmp)

    # 윤곽만 비운다. cmap 에서 빼는 것은 finalize 가 한다.
    for code in [R.cp(c) for c in rec["finalize"].get("removeCodepoints", [])]:
        if code in font:
            font[code].clear()

    out = os.path.join(out_dir, "%s-%s.ttf" % (names["short"], style["file"]))
    print("Save " + os.path.basename(out))
    font.generate(out)
    font.close()
    return out


def run(rec, root, out_dir, variants, debug=False):
    suffix = R.variant_suffix(rec, variants)
    styles = R.styles_for(rec, debug)
    sources = R.active_sources(rec, variants)
    base_source = next(s for s in sources if s.get("role") == "base")

    parts_dir = os.path.join(out_dir, "parts")
    os.makedirs(parts_dir, exist_ok=True)

    # 우선순위대로 코드포인트를 배분한다
    print("=== 코드포인트 배분 ===")
    ref_ctx = R.Context(rec, styles[0], root, variants)
    assigned = assign_codepoints(ref_ctx, sources, styles[0])
    base_cps = assigned[base_source["id"]]

    shared = {}
    for source in sources:
        if source.get("fit", {}).get("mode") == "cjkClassify":
            others = set().union(*(v for k, v in assigned.items() if k != source["id"])) \
                if len(assigned) > 1 else set()
            shared["widths"] = fits.classify_widths(
                ref_ctx, source, styles[0], others - assigned[source["id"]])

    # 심볼 소스는 두께와 무관하므로 한 번만 만든다
    for source in sources:
        if source.get("role") == "symbols":
            font = build_source(ref_ctx, source, shared, assigned[source["id"]])
            part = os.path.join(parts_dir, "%s.ttf" % source["id"])
            print("Save " + os.path.basename(part))
            font.generate(part)
            font.close()
            subset_part(part, assigned[source["id"]])

    for style in styles:
        print("=== %s ===" % style["file"])
        ctx = R.Context(rec, style, root, variants)

        base_font = build_source(ctx, base_source, shared, assigned[base_source["id"]])
        compose(ctx, base_font, suffix, out_dir)
        base_font.close()

        for source in sources:
            if source is base_source or source.get("role") == "symbols":
                continue
            font = build_source(ctx, source, shared, assigned[source["id"]])
            part = os.path.join(parts_dir, "%s-%s.ttf" % (source["id"], style["file"]))
            print("Save " + os.path.basename(part))
            font.generate(part)
            font.close()
            subset_part(part, assigned[source["id"]])

    print("compose: done")


def main(argv=None):
    parser = argparse.ArgumentParser(description="레시피대로 글리프를 합성한다")
    parser.add_argument("--recipe", required=True)
    parser.add_argument("--root", default=None, help="소스를 찾을 기준 디렉터리")
    parser.add_argument("--out", default=None)
    parser.add_argument("--variant", action="append", default=[])
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)

    rec = R.load(args.recipe)
    root = args.root or os.path.dirname(os.path.abspath(args.recipe)) or "."
    run(rec, root, args.out or root, {v: True for v in args.variant}, args.debug)


if __name__ == "__main__":
    main()
