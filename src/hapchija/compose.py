"""합성 단계. FontForge 가 필요하다.

    python3 -m hapchija.compose --recipe ... [--out DIR] [--styles Regular,Bold]
    fontforge -script .../compose.py --recipe ...   (바인딩이 없을 때)

레시피의 sources 는 우선순위 순서다. role=base 인 소스가 최종 글꼴의 뼈대가
되고, 나머지는 parts/ 에 따로 내보낸다. 힌팅을 넣은 뒤 finalize 가 합친다.
"""

from __future__ import annotations

import argparse
import json
import os

import fontforge
import psMat

from . import fits, ops, recipe as R


def range_set(pairs):
    out = set()
    for pair in pairs or []:
        out.update(R.cp_range(pair))
    return out


def merged_codepoints(ctx, source, styles):
    """mergeSfd 로 들어올 코드포인트.

    소스 파일에는 없고 병합으로 비로소 생기는 글리프가 있다. 박스 드로잉이
    그렇다. 반각으로 손질한 160 자가 Box_Drawing_half.sfd 에 있는데
    IBM Plex Sans KR 자신은 69 자만 갖는다. 배정 단계가 파일만 보면 나머지
    91 자는 어느 소스에도 배정되지 않고, 병합해 놓고도 잘라 낼 때 사라진다.
    """
    cps = set()
    for stage in ("preOps", "ops", "opsAfter"):
        for spec in source.get(stage) or []:
            if spec.get("op") != "mergeSfd":
                continue
            for style in styles:
                path = ctx.path(spec["from"], style)
                if not os.path.exists(path):
                    continue
                font = fontforge.open(path)
                cps |= ops.codepoints_of(font)
                font.close()
    return cps


def composed_codepoints(source):
    """이 소스의 ops 가 compose 로 새로 만드는 코드포인트. 소스 파일의 cmap 에는
    없지만 이 소스가 내놓는 것이므로 배정에 넣는다."""
    out = set()
    for key in ("preOps", "ops", "opsAfter"):
        for spec in source.get(key) or []:
            if spec.get("op") == "compose":
                out.add(R.cp(spec["cp"]))
    return out


def available_codepoints(ctx, source, styles):
    """이 소스가 내놓을 수 있는 코드포인트.

    keepRanges 가 있으면 그 범위로 제한하고, dropRanges 는 빼낸다.
    dropRanges 는 사용자 정의 영역(PUA)을 막는 데 쓴다. CJK 글꼴은 벤더 내부용
    글리프를 PUA 에 수천 개씩 넣어 두는데 (IBM Plex Sans TC 는 4,729 자),
    합성 결과에 노출될 이유가 없고 Nerd Fonts 영역과 정면으로 부딪친다.

    굵기 전체의 합집합을 본다. 한 굵기만 보면, 그 굵기에 없는 글자를 이
    소스가 못 내놓는 것으로 판정해 뒤 소스에게도 넘기지 않으므로, 한
    굵기의 결손이 열여섯 굵기 전부로 번진다. IBM Plex Sans KR 1.002 는
    Thin 에만 57 자(반각 한글 자모 등)가 없다. 배정만 합집합으로 하면
    되고, 실제로 그 글자가 없는 굵기는 잘라 낼 때 자연히 빠진다.
    """
    cps = set()
    for path in sorted({ctx.path(source["path"], s) for s in styles}):
        font = fontforge.open(path)
        cps |= ops.codepoints_of(font)
        font.close()
    cps |= merged_codepoints(ctx, source, styles)
    cps |= composed_codepoints(source)
    if source.get("keepRanges"):
        cps &= range_set(source["keepRanges"])
    if source.get("dropRanges"):
        cps -= range_set(source["dropRanges"])
    return cps


def assign_codepoints(ctx, sources, styles):
    """우선순위대로 코드포인트를 나눠 준다.

    앞선 소스가 이미 가진 코드포인트는 뒤 소스에서 뺀다. 이렇게 하지 않으면
    병합할 때 같은 글자의 글리프가 소스 수만큼 쌓여서, cmap 이 하나만 쓰는데도
    TrueType 의 글리프 수 상한(65,535)을 넘긴다.
    """
    assigned, claimed = {}, set()
    for source in sources:
        cps = available_codepoints(ctx, source, styles)
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
        # 기울이지 않을 범위를 빼고 선택한다.
        #
        # CJK 한자는 전통적으로 이탤릭이 없다. 기울이면 어색할 뿐 아니라,
        # FontForge 의 italicize 는 글리프마다 윤곽을 다시 계산하는 무거운
        # 연산이라 한자 2만 자에 돌리면 빌드 시간이 몇 배로 늘어난다.
        font.selection.all()
        for pair in source.get("italicExclude", []):
            try:
                font.selection.select(("less", "unicode", "ranges"),
                                      R.cp(pair[0]), R.cp(pair[1]))
            except ValueError:
                # 소스의 인코딩(예: BMP 만)을 넘는 범위. 그 범위에 글리프가
                # 있을 수 없으니 뺄 것도 없다.
                pass
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

    if source.get("role") != "base":
        narrow_to_half(ctx, font, ctx.recipe.get("narrowToHalf"))
    align_box(ctx, font, ctx.recipe.get("alignBox"))

    ops.run(ctx, font, source.get("opsAfter"), source_half)
    font.selection.none()
    return font


def narrow_to_half(ctx, font, spec):
    """레시피의 narrowToHalf 에 적힌 기호를 반각으로 만든다.

    CJK 소스는 기호를 전각으로 갖고 있는 것이 많은데, 터미널은 East Asian
    Width 가 A 나 N 인 글자를 1칸으로 세므로 전각이면 옆 칸을 침범한다.
    잉크 폭이 maxInk 를 넘으면 가로세로 같은 비율로 줄이고(원이 찌그러지지
    않도록), 반각 폭에 가운데 놓는다. 소스가 어느 것이든 결과 코드포인트 기준으로
    적용하므로 레시피 최상위에 한 번만 적는다. 뼈대(base)는 이미 반각이라 뺀다.
    """
    if not spec:
        return
    codes = set(ops.selected_codepoints(spec))
    max_ink = spec.get("maxInk", round(ctx.half_width * 0.89))
    done = shrunk = 0
    seen = set()                 # 한 글리프가 여러 코드포인트에 걸려도 한 번만 줄인다
    for code in sorted(codes):
        if code not in font:
            continue
        glyph = font[code]
        if not ops.worth(glyph) or glyph.glyphname in seen:
            continue
        seen.add(glyph.glyphname)
        xmin, _, xmax, _ = glyph.boundingBox()
        ink = xmax - xmin
        if ink > max_ink:
            ops.transform_about_center(glyph, psMat.scale(max_ink / ink))
            shrunk += 1
        glyph.width = ctx.half_width
        ops.center_in_width(glyph)
        done += 1
    if done:
        print("narrowToHalf: %d 자 반각으로 (그중 %d 자 축소)" % (done, shrunk))


def align_box(ctx, font, specs):
    """기호들을 같은 크기 상자에 넣고 세로 중심을 맞춘다.

    ⊕ ⊖ ⊗ ⊘ ⊙ ⊞ ⊠ 처럼 원이나 사각형으로 둘러싼 기호는 서로 크기와 높이가
    같아야 한다. 소스가 여러 글꼴로 갈리면 그것이 어긋난다. size 를 주면 잉크를
    그 크기에 맞추고, yCenter 로 세로 중심을 옮긴다. 폭(advance)은 건드리지 않는다.

    size 는 숫자 하나면 정사각형이고, [가로, 세로] 면 그 상자에 맞춘다. 둘러싼
    숫자 ① ❶ 처럼 원이 정원이 아닌 계열은 가로세로를 따로 주어야 한다.

    소스마다 가진 글자가 달라 한 계열이 여러 소스에 흩어지므로, 소스별 ops 가
    아니라 레시피 최상위에 적고 모든 소스에 같은 규칙을 적용한다.
    """
    for spec in specs or []:
        size = spec.get("size")
        y_center = spec.get("yCenter")
        done = 0
        for code in sorted(set(ops.selected_codepoints(spec))):
            if code not in font:
                continue
            glyph = font[code]
            if not ops.worth(glyph):
                continue
            xmin, ymin, xmax, ymax = glyph.boundingBox()
            if xmax - xmin <= 0 or ymax - ymin <= 0:
                continue
            width = glyph.width
            if size:
                sw, sh = (size, size) if isinstance(size, (int, float)) else size
                ops.transform_about_center(
                    glyph, psMat.scale(sw / (xmax - xmin), sh / (ymax - ymin)))
                xmin, ymin, xmax, ymax = glyph.boundingBox()
            if y_center is not None:
                glyph.transform(psMat.translate(0, y_center - (ymin + ymax) / 2))
            glyph.width = width
            ops.center_in_width(glyph)
            done += 1
        if done:
            print("alignBox: %d 자" % done)


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


def restore_altuni(src, dst):
    """mergeFonts 가 버리는 altuni 를 되살린다.

    FontForge 의 mergeFonts 는 글리프의 주 유니코드만 옮기고, 한 글리프가 추가로
    매핑된 코드포인트(altuni)는 버린다. Consolas 는 space 에 U+00A0, hyphen 에
    U+2010 과 U+00AD 를 이렇게 매핑해 두어서, 그대로 두면 NBSP 가 없는 글꼴이
    된다. IBM Plex Mono 에는 altuni 가 없어 Monoplex 에서는 드러나지 않았다.
    """
    restored = 0
    for glyph in src.glyphs():
        if not glyph.altuni or glyph.glyphname not in dst:
            continue
        seen, alts = set(), []
        for alt in glyph.altuni:
            if alt[0] is None or alt[0] < 0 or (alt[0], alt[1]) in seen:
                continue
            seen.add((alt[0], alt[1]))
            alts.append(alt)
        if alts:
            dst[glyph.glyphname].altuni = tuple(alts)
            restored += 1
    if restored:
        # 파이썬에서 altuni 를 넣어도 FontForge 는 인코딩 맵을 다시 만들지 않아서
        # generate 의 cmap 에 실리지 않는다. 인코딩을 재지정하면 다시 만든다.
        dst.encoding = "UnicodeFull"
        print("altuni 복원: %d 글리프" % restored)


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

    # 현지어 가족 이름. output.localizedFamilyName 에 {"Korean": "푸른모"} 처럼 적는다.
    # 키는 FontForge 의 언어 이름이다. 영문 이름에서 가족 부분만 바꿔 넣으므로
    # RIBBI 밖 두께("Pureunmo SemiBold")도 같은 규칙을 따른다.
    english = names["typo_family"]
    for lang, local in rec["output"].get("localizedFamilyName", {}).items():
        font.appendSFNTName(lang, "Family", names["familyname"].replace(english, local, 1))
        font.appendSFNTName(lang, "SubFamily", names["subfamily"])
        font.appendSFNTName(lang, "Fullname", names["fullname"].replace(english, local, 1))
        font.appendSFNTName(lang, "Preferred Family", local)
        font.appendSFNTName(lang, "Preferred Styles", names["typo_subfamily"])

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
    restore_altuni(base_font, font)

    # 윤곽만 비운다. cmap 에서 빼는 것은 finalize 가 한다.
    for code in [R.cp(c) for c in rec["finalize"].get("removeCodepoints", [])]:
        if code in font:
            font[code].clear()

    out = os.path.join(out_dir, "%s-%s.ttf" % (names["short"], style["file"]))
    print("Save " + os.path.basename(out))
    font.generate(out)
    font.close()
    return out


def run(rec, root, out_dir, variants,
        plan_path=None, only_styles=None, plan_only=False):
    suffix = R.variant_suffix(rec, variants)
    styles = R.pick_styles(rec, only_styles)
    if not styles:
        raise SystemExit("ERROR: 만들 스타일이 없습니다: %s" % only_styles)
    sources = R.active_sources(rec, variants)
    base_source = next(s for s in sources if s.get("role") == "base")

    parts_dir = os.path.join(out_dir, "parts")
    os.makedirs(parts_dir, exist_ok=True)
    ref_ctx = R.Context(rec, styles[0], root, variants)

    # 코드포인트 배분과 폭 분류는 두께와 무관하므로 한 번만 한다.
    # 병렬로 돌릴 때는 부모가 계산해 파일로 넘기고 자식들이 읽어 쓴다.
    if plan_path and os.path.exists(plan_path) and not plan_only:
        with open(plan_path, encoding="utf-8") as fp:
            plan = json.load(fp)
        assigned = {k: set(v) for k, v in plan["assigned"].items()}
        shared = {}
        if plan.get("widths"):
            shared["widths"] = tuple(set(x) for x in plan["widths"])
    else:
        print("=== 코드포인트 배분 ===")
        assigned = assign_codepoints(ref_ctx, sources, styles)
        shared = {}
        for source in sources:
            if source.get("fit", {}).get("mode") == "cjkClassify":
                others = set().union(*(v for k, v in assigned.items() if k != source["id"])) \
                    if len(assigned) > 1 else set()
                shared["widths"] = fits.classify_widths(
                    ref_ctx, source, styles[0], others - assigned[source["id"]])
        if plan_path:
            with open(plan_path, "w", encoding="utf-8") as fp:
                json.dump({"assigned": {k: sorted(v) for k, v in assigned.items()},
                           "widths": [sorted(x) for x in shared["widths"]]
                                     if "widths" in shared else None}, fp)
            print("배분 결과 저장: " + os.path.basename(plan_path))
    # 심볼 부품은 두께와 무관하므로 한 번만 만든다. 병렬로 돌 때는 부모가
    # 만들어 둔다. 워커들이 같은 경로에 동시에 쓰면 반쯤 쓰인 파일이 생긴다.
    is_worker = bool(plan_path) and not plan_only
    if not is_worker:
        for source in sources:
            if source.get("role") == "symbols":
                part = os.path.join(parts_dir, "%s.ttf" % source["id"])
                if os.path.exists(part):
                    continue
                font = build_source(ref_ctx, source, shared, assigned[source["id"]])
                print("Save " + os.path.basename(part))
                font.generate(part)
                font.close()
                subset_part(part, assigned[source["id"]])
    if plan_only:
        return

    base_cps = assigned[base_source["id"]]

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
    parser.add_argument("--plan", default=None,
                        help="코드포인트 배분 결과 (JSON). 없으면 직접 계산한다")
    parser.add_argument("--styles", default=None,
                        help="만들 스타일의 파일 이름들(Regular,BoldItalic ...), 쉼표로 구분. 없으면 전부")
    parser.add_argument("--plan-only", action="store_true",
                        help="배분만 계산해 --plan 에 쓰고 끝낸다")
    args = parser.parse_args(argv)

    rec = R.load(args.recipe)
    root = args.root or os.path.dirname(os.path.abspath(args.recipe)) or "."
    run(rec, root, args.out or root, {v: True for v in args.variant},
        plan_path=args.plan, only_styles=args.styles, plan_only=args.plan_only)


if __name__ == "__main__":
    main()
