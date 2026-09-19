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


def build_source(ctx, source, shared, base_cps=None):
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

    # 우선순위가 높은 소스가 이미 가진 코드포인트는 지운다
    if base_cps:
        for glyph in font.glyphs():
            if glyph.unicode is not None and glyph.unicode in base_cps:
                glyph.clear()

    source_half = font[0x20].width if 0x20 in font else None
    ops.run(ctx, font, source.get("ops"), source_half)

    if source.get("fit"):
        fits.apply(ctx, font, source["fit"], shared)

    ops.run(ctx, font, source.get("opsAfter"), source_half)
    font.selection.none()
    return font


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

    # 기준 소스가 가진 코드포인트를 미리 구한다. 뒤 소스에서 겹치는 것을 지우는 데 쓴다.
    print("=== 기준 소스 훑기 ===")
    ref_ctx = R.Context(rec, styles[0], root, variants)
    probe = build_source(ref_ctx, base_source, {})
    base_cps = ops.codepoints_of(probe)
    probe.close()

    shared = {}
    for source in sources:
        if source.get("fit", {}).get("mode") == "cjkClassify":
            shared["widths"] = fits.classify_widths(ref_ctx, source, styles[0], base_cps)

    # 심볼 소스는 두께와 무관하므로 한 번만 만든다
    for source in sources:
        if source.get("role") == "symbols":
            font = build_source(ref_ctx, source, shared, base_cps)
            part = os.path.join(parts_dir, "%s.ttf" % source["id"])
            print("Save " + os.path.basename(part))
            font.generate(part)
            font.close()

    for style in styles:
        print("=== %s ===" % style["file"])
        ctx = R.Context(rec, style, root, variants)

        base_font = build_source(ctx, base_source, shared)
        compose(ctx, base_font, suffix, out_dir)
        base_font.close()

        for source in sources:
            if source is base_source or source.get("role") == "symbols":
                continue
            font = build_source(ctx, source, shared, base_cps)
            part = os.path.join(parts_dir, "%s-%s.ttf" % (source["id"], style["file"]))
            print("Save " + os.path.basename(part))
            font.generate(part)
            font.close()

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
