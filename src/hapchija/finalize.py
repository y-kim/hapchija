"""마무리 단계. FontForge 없이 fontTools 만 쓴다.

힌팅을 넣고, 부품을 합치고, 테이블을 바로잡는다.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import unicodedata

from fontTools.merge import Merger
from fontTools.ttLib import TTFont, newTable

from . import recipe as R

# 부품에 남아 있어도 합성 결과에는 의미가 없고, fontTools 병합을 깨뜨리기도 하는
# 테이블. 세로쓰기 메트릭과 소스 글꼴의 힌팅이다. 힌팅은 변형을 가한 뒤라
# 어차피 맞지 않는다.
STRIP_FROM_PARTS = ("vhea", "vmtx", "VORG", "cvt ", "fpgm", "prep")


def strip_tables(path, tags=STRIP_FROM_PARTS):
    font = TTFont(path, recalcBBoxes=False, recalcTimestamp=False)
    removed = [t for t in tags if t in font]
    if removed:
        for tag in removed:
            del font[tag]
        font.save(path)
    font.close()
    return removed


def merge_parts(base, parts, out):
    """base 를 우선으로 부품을 합친다.

    fontTools 의 merge 는 같은 코드포인트가 겹치면 앞선 폰트를 남긴다.
    레시피의 sources 순서가 그대로 우선순위가 된다.
    """
    merged = Merger().merge([base] + parts)
    merged.save(out)
    merged.close()


def fs_selection(bold, italic):
    """OS/2 fsSelection. bit 8 (WWS) 은 항상 켠다."""
    value = 1 << 8
    if italic:
        value |= 1 << 0
    if bold:
        value |= 1 << 5
    if not bold and not italic:
        value |= 1 << 6          # REGULAR
    return value


def mac_style(bold, italic):
    """head macStyle. fsSelection 과 같은 판단을 써야 한다.

    이 값이 어긋나면 일부 앱이 진짜 이탤릭 위에 가짜 기울임을 덧씌운다.
    """
    value = 0
    if bold:
        value |= 1 << 0
    if italic:
        value |= 1 << 1
    return value


def drop_codepoints(font, codepoints):
    """cmap 에서 코드포인트를 뺀다.

    윤곽만 비우면 cmap 항목이 남아서, OS 가 그 글리프를 쓸 수 있다고 보고
    대체 글꼴(이모지 등)로 넘어가지 않는다.
    """
    for table in font["cmap"].tables:
        for code in codepoints:
            table.cmap.pop(code, None)


def map_canonical(font, ranges):
    """정준 분해 대상이 있는 코드포인트를 같은 글리프에 연결한다.

    호환한자(U+F900-FAFF)는 같은 한자의 다른 독음을 유니코드가 따로 부호화한
    것이라 자형은 통합한자 쪽과 같다. 소스 글꼴이 이 영역을 안 갖고 있어도
    정준 분해 대상 글리프는 갖고 있으므로 cmap 만 연결해 주면 된다.

    KS X 1001 은 이 영역의 246 자를 포함하므로, 연결하지 않으면 한국어 표준
    한자 집합을 다 덮지 못한다.
    """
    cmap = font.getBestCmap()
    tables = [t for t in font["cmap"].tables if t.isUnicode()]
    added = 0
    for pair in ranges:
        for code in range(int(pair[0], 16), int(pair[1], 16) + 1):
            if code in cmap:
                continue
            dec = unicodedata.decomposition(chr(code))
            if not dec or " " in dec.strip():
                continue                     # 정준 단일 분해만 다룬다
            name = cmap.get(int(dec, 16))
            if not name:
                continue
            for t in tables:
                t.cmap[code] = name
            added += 1
    return added


def fix_tables(rec, path, style):
    fin = rec["finalize"]
    cfg = fin.get("os2", {})
    target = rec["target"]
    font = TTFont(path, recalcBBoxes=False, recalcTimestamp=False)

    drop_codepoints(font, [R.cp(c) for c in fin.get("removeCodepoints", [])])

    if fin.get("mapCanonical"):
        n = map_canonical(font, fin["mapCanonical"].get("ranges", []))
        if n:
            print("  정준 등가 연결: %d자" % n)

    os2 = font["OS/2"]
    if "xAvgCharWidth" in cfg:
        os2.xAvgCharWidth = cfg["xAvgCharWidth"]
    # compose 는 fsType 을 0 으로 두지만, fontTools 병합이 부품(예: 맑은 고딕)의
    # 제한 비트를 OR 로 합쳐 버린다. 여기서 확정한다.
    os2.fsType = cfg.get("fsType", 0)
    bold, italic = R.ribbi_flags(style)
    os2.fsSelection = fs_selection(bold, italic)
    font["head"].macStyle = mac_style(bold, italic)

    # 세로 메트릭은 FontForge 에서 넣어도 mergeFonts 와 generate 가 윤곽을 보고
    # 다시 계산해 버린다. 그래서 여기서 확정한다.
    if cfg.get("forceVerticalMetrics"):
        v, em = target["vertical"], target["em"]
        os2.usWinAscent = v["ascent"]
        os2.usWinDescent = v["descent"]
        os2.sTypoAscender = em["ascent"]
        os2.sTypoDescender = -em["descent"]
        os2.sTypoLineGap = v.get("typoLineGap", 0)
        hhea = font["hhea"]
        hhea.ascent = v["ascent"]
        hhea.descent = -v["descent"]
        hhea.lineGap = 0

    # 힌팅을 넣지 않는 글꼴의 gasp. FontForge 는 무힌팅 글꼴에 회색 안티앨리어싱(2)
    # 만 켜 두는데, 그러면 Windows 에서 대칭 스무딩이 빠진다. ttfautohint 를 돌리면
    # 그쪽이 모든 크기를 15 로 채우므로, 안 돌릴 때만 여기서 채운다.
    if not fin.get("hinting"):
        gasp = newTable("gasp")
        gasp.version = 1
        gasp.gaspRange = {0xFFFF: 15}
        font["gasp"] = gasp

    post = font["post"]
    if "isFixedPitch" in cfg:
        post.isFixedPitch = cfg["isFixedPitch"]
    if "underlinePosition" in cfg:
        post.underlinePosition = cfg["underlinePosition"]

    # VSCode 터미널 하단에서 디센더가 잘리는 문제 대비. 없으면 아무 일도 없다.
    if "BASE" in font:
        del font["BASE"]

    font.save(path)
    font.close()


def run(rec, work_dir, variants, styles=None):
    """styles 는 합칠 스타일의 파일 이름 목록. 비면 전부."""
    suffix = R.variant_suffix(rec, variants)
    prefix = R.family_short(rec, suffix)
    styles = R.pick_styles(rec, styles)
    sources = R.active_sources(rec, variants)
    extra = [s for s in sources if s.get("role") != "base"]
    hinting = rec["finalize"].get("hinting", [])
    parts_dir = os.path.join(work_dir, "parts")

    for style in styles:
        name = "%s-%s.ttf" % (prefix, style["file"])
        base = os.path.join(work_dir, name)
        if not os.path.exists(base):
            raise SystemExit("ERROR: %s 가 없습니다" % base)

        parts = []
        for source in extra:
            if source.get("role") == "symbols":
                part = os.path.join(parts_dir, "%s.ttf" % source["id"])
            else:
                part = os.path.join(parts_dir, "%s-%s.ttf" % (source["id"], style["file"]))
            if not os.path.exists(part):
                raise SystemExit("ERROR: %s 가 없습니다" % part)
            parts.append(part)

        if hinting:
            print("ttfautohint: " + name)
            hinted = os.path.join(work_dir, "hinted-" + name)
            subprocess.run(["ttfautohint"] + list(hinting) + ["-I", base, hinted],
                           check=True)
        else:
            hinted = base

        for part in parts:
            removed = strip_tables(part)
            if removed:
                print("strip %s: %s" % (os.path.basename(part), ", ".join(removed)))

        print("merge: " + name)
        merge_parts(hinted, parts, base)
        if hinted != base:
            os.remove(hinted)

        print("fix tables: " + name)
        fix_tables(rec, base, style)

    shutil.rmtree(parts_dir, ignore_errors=True)
    print("finalize: done")


def main(argv=None):
    parser = argparse.ArgumentParser(description="부품을 합치고 테이블을 바로잡는다")
    parser.add_argument("--recipe", required=True)
    parser.add_argument("--dir", default=".")
    parser.add_argument("--variant", action="append", default=[])
    parser.add_argument("--styles", default=None,
                        help="합칠 스타일의 파일 이름들, 쉼표로 구분. 없으면 전부")
    args = parser.parse_args(argv)
    run(R.load(args.recipe), args.dir, {v: True for v in args.variant}, args.styles)


if __name__ == "__main__":
    main()
