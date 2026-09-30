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


def add_locl(rec, path):
    """GSUB 에 나라별 자형(locl)을 더한다 — 이미 있는 기능은 그대로 둔다.

    레시피의 locl 은 {언어 태그: 소스 id 또는 {from, within}} 이다. compose 가 소스마다
    `uniXXXX.소스` 글리프를 부품으로 실어 두었으므로, 코드포인트 XXXX 의 기본
    글리프(cmap)를 그 글리프로 바꾸는 단일 치환을 태그마다 하나씩 만들어 locl 로
    건다. `within` 이 있으면 그 인코딩에 드는 글자만 바꾼다.

    `default` 에 적은 태그(기본 글리프가 그 나라 자형)는 치환 없이 언어 시스템만
    등록한다. 언어 시스템은 `hani` 와 `DFLT` 두 스크립트에 둔다 — 한자 글자열은
    hani 로 모양을 잡는데, 그 스크립트가 없는 셰이퍼는 DFLT 로 간다. 새 언어
    시스템은 그 스크립트의 기본 언어 시스템이 가진 기능을 모두 물려받고 locl 을
    더한다 (언어 시스템이 생기면 기본 쪽 기능을 쓰지 않으므로).
    """
    from fontTools.ttLib.tables import otTables as ot

    spec = rec["locl"]
    langs = R.locl_langs(rec)
    default = spec.get("default")
    font = TTFont(path, recalcBBoxes=False, recalcTimestamp=False)
    order = set(font.getGlyphOrder())
    cmap = font.getBestCmap()
    # 태그마다 치환표 — 소스의 `uniXXXX.소스` 가운데 그 태그의 within 에 드는 것
    subs = {}
    for tag, (sid, enc) in sorted(langs.items()):
        tail = "." + sid
        m = {}
        for name in order:
            if not name.endswith(tail):
                continue
            head = name[:-len(tail)]
            code = int(head[3:], 16) if head.startswith("uni") else int(head[1:], 16)
            if not R.within_set(enc, [code]):
                continue
            base = cmap.get(code)
            if base and base != name:
                m[base] = name
        subs[tag] = m
    if len(order) > 65535:
        raise SystemExit("ERROR: 글리프가 %d 개로 TrueType 상한을 넘는다" % len(order))

    gsub = font["GSUB"].table
    lookups = gsub.LookupList.Lookup
    index = {}
    for tag, m in subs.items():
        st = ot.SingleSubst()
        st.mapping = m
        lk = ot.Lookup()
        lk.LookupType = 1
        lk.LookupFlag = 0
        lk.SubTable = [st]
        lk.SubTableCount = 1
        lookups.append(lk)
        index[tag] = len(lookups) - 1
    gsub.LookupList.LookupCount = len(lookups)

    feats = gsub.FeatureList.FeatureRecord
    feat_of = {}
    for tag in langs:
        fr = ot.FeatureRecord()
        fr.FeatureTag = "locl"
        fr.Feature = ot.Feature()
        fr.Feature.FeatureParams = None
        fr.Feature.LookupListIndex = [index[tag]]
        fr.Feature.LookupCount = 1
        feats.append(fr)
        feat_of[tag] = len(feats) - 1

    def ensure_script(tag):
        for sr in gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag == tag:
                return sr
        sr = ot.ScriptRecord()
        sr.ScriptTag = tag
        sr.Script = ot.Script()
        sr.Script.LangSysRecord = []
        sr.Script.LangSysCount = 0
        dflt = next((r for r in gsub.ScriptList.ScriptRecord if r.ScriptTag == "DFLT"), None)
        base = dflt.Script.DefaultLangSys if dflt and dflt.Script.DefaultLangSys else None
        ls = ot.LangSys()
        ls.LookupOrder = None
        ls.ReqFeatureIndex = base.ReqFeatureIndex if base else 0xFFFF
        ls.FeatureIndex = list(base.FeatureIndex) if base else []
        ls.FeatureCount = len(ls.FeatureIndex)
        sr.Script.DefaultLangSys = ls
        gsub.ScriptList.ScriptRecord.append(sr)
        return sr

    tags = ([default] if default else []) + sorted(langs)
    for script in ("DFLT", "hani"):
        sr = ensure_script(script)
        base = sr.Script.DefaultLangSys
        for tag in tags:
            key = "%-4s" % tag
            rec_ = next((r for r in sr.Script.LangSysRecord if r.LangSysTag == key), None)
            if rec_ is None:
                rec_ = ot.LangSysRecord()
                rec_.LangSysTag = key
                ls = ot.LangSys()
                ls.LookupOrder = None
                ls.ReqFeatureIndex = base.ReqFeatureIndex if base else 0xFFFF
                ls.FeatureIndex = list(base.FeatureIndex) if base else []
                rec_.LangSys = ls
                sr.Script.LangSysRecord.append(rec_)
            if tag in feat_of and feat_of[tag] not in rec_.LangSys.FeatureIndex:
                rec_.LangSys.FeatureIndex.append(feat_of[tag])
            rec_.LangSys.FeatureCount = len(rec_.LangSys.FeatureIndex)
        sr.Script.LangSysRecord.sort(key=lambda r: r.LangSysTag)
        sr.Script.LangSysCount = len(sr.Script.LangSysRecord)
    gsub.ScriptList.ScriptRecord.sort(key=lambda r: r.ScriptTag)
    gsub.ScriptList.ScriptCount = len(gsub.ScriptList.ScriptRecord)
    # 기능 목록은 태그 순이어야 한다 — 더한 locl 을 제자리로 옮기고 번호를 고쳐 준다
    order_ = sorted(range(len(feats)), key=lambda i: (feats[i].FeatureTag, i))
    remap = {old_i: new_i for new_i, old_i in enumerate(order_)}
    gsub.FeatureList.FeatureRecord = [feats[i] for i in order_]
    gsub.FeatureList.FeatureCount = len(feats)
    for sr in gsub.ScriptList.ScriptRecord:
        for ls in [sr.Script.DefaultLangSys] + [r.LangSys for r in sr.Script.LangSysRecord]:
            if ls is None:
                continue
            ls.FeatureIndex = sorted(remap[i] for i in ls.FeatureIndex)
            ls.FeatureCount = len(ls.FeatureIndex)
            if ls.ReqFeatureIndex != 0xFFFF:
                ls.ReqFeatureIndex = remap[ls.ReqFeatureIndex]
    font.save(path)
    font.close()
    print("  locl: " + " · ".join("%s→%s%s %d자" % (t, v[0], "(%s)" % v[1] if v[1] else "", len(subs[t]))
                                   for t, v in sorted(langs.items()))
          + (" · %s 기본" % default if default else "") + " · 글리프 %d" % len(order))


def run(rec, work_dir, variants, styles=None):
    """styles 는 합칠 스타일의 파일 이름 목록. 비면 전부."""
    suffix = R.variant_suffix(rec, variants)
    prefix = R.family_short(rec, suffix)
    styles = R.pick_styles(rec, styles)
    sources = R.active_sources(rec, variants)
    extra = [s for s in sources if s.get("role") != "base"]
    hinting = rec["finalize"].get("hinting", [])
    # 부품에서 떼어 낼 테이블. 레시피가 finalize.stripFromParts 로 바꿀 수 있다.
    strip_tags = tuple(rec["finalize"].get("stripFromParts", STRIP_FROM_PARTS))
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

        # 나라별 자형 부품 (compose 가 locl 이 있을 때만 만든다)
        for source in sources:
            part = os.path.join(parts_dir, "locl-%s-%s.ttf" % (source["id"], style["file"]))
            if os.path.exists(part):
                parts.append(part)

        if hinting:
            print("ttfautohint: " + name)
            hinted = os.path.join(work_dir, "hinted-" + name)
            subprocess.run(["ttfautohint"] + list(hinting) + ["-I", base, hinted],
                           check=True)
        else:
            hinted = base

        for part in parts:
            removed = strip_tables(part, strip_tags)
            if removed:
                print("strip %s: %s" % (os.path.basename(part), ", ".join(removed)))

        # 합칠 글리프 수를 먼저 센다. 넘으면 fontTools 가 합치다가 struct 오류로
        # 멈추는데, 무엇이 넘었는지 알 수 없다. 부품마다 .notdef 는 겹치므로 뺀다.
        total = 0
        for p in [hinted] + parts:
            f = TTFont(p, lazy=True)
            total += len(f.getGlyphOrder())
            f.close()
        total -= len(parts)
        if total > 65535:
            raise SystemExit("ERROR: %s 의 글리프가 %d 개로 TrueType 상한(65,535)을 %d 넘는다"
                             " — locl 을 줄이거나 within 으로 범위를 좁힌다"
                             % (name, total, total - 65535))

        print("merge: " + name)
        merge_parts(hinted, parts, base)
        if hinted != base:
            os.remove(hinted)

        print("fix tables: " + name)
        fix_tables(rec, base, style)
        if rec.get("locl"):
            add_locl(rec, base)

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
