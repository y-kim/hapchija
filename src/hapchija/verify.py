"""빌드한 글꼴을 검증한다 — 불변 조건과 이전 판과의 비교.

    hapchija verify --recipe recipes/x.json                 # 불변 조건 + dist/ 의 마지막 릴리즈와 비교
    hapchija verify --recipe recipes/x.json --baseline P    # P 는 디렉터리나 릴리즈 zip
    hapchija verify --recipe recipes/x.json --no-baseline   # 불변 조건만

build 가 끝나면 저절로 돈다 (--no-verify 로 끈다).

① 불변 조건 — 하나라도 어기면 실패한다.
   scripts      GSUB · GPOS 의 모든 스크립트에 기본 언어 시스템이 있다.
                 없으면 그 스크립트 글자열에 기능이 하나도 걸리지 않는다.
   glyphs       글리프 수가 65,535 안이다. verify.minGlyphMargin 보다 적게 남으면 알린다.
   context      GSUB 기능이 바꾸는 공통 문자(숫자 · 기호)가 어느 문자 체계 옆에서든
                 똑같이 바뀐다. 기능 목록에서 시험을 뽑으므로 기대값을 따로 적지 않는다.
   positions    공통 문자의 자리(kern · mark)가 어느 문자 체계 옆에서든 같다.
   locl         레시피의 locl · locl.features 대로 언어와 기능이 글자를 바꾼다.
                 글꼴에 실린 `uniXXXX.소스` 글리프에서 표본을 뽑는다.
   canonical    KS X 1001 호환 한자(U+F900–FA0B)가 정준 한자와 같은 글리프다
                 (verify.canonicalRanges 로 바꾼다).
   monospace    finalize.os2.isFixedPitch 면 모든 폭이 0 · 반각 · 전각 가운데 하나다.
   hinting      힌팅을 넣는 레시피면 hinted 판에 fpgm 이 있고 unhinted 판에 없다.

알고 있는 문제는 레시피의 verify.known 에 {검사 이름: 까닭} 으로 적으면 보고만 하고
실패로 치지 않는다.

② 이전 판과 비교 — 보고만 한다. build/report/<가족>.md 에 적는다.
   코드포인트 추가 · 삭제, 윤곽이나 폭이 바뀐 글자(블록별), 스크립트 · 언어 · 기능
   목록, 주요 메트릭, 고정 문장의 셰이핑 결과.

셰이핑을 쓰는 검사(context · positions · locl · 셰이핑 비교)는 uharfbuzz 가 있어야
한다 (pip install 'hapchija[verify]'). 없으면 건너뛰고 알린다.
"""

from __future__ import annotations

import glob
import hashlib
import os
import sys
import unicodedata as ud
import zipfile
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

from . import recipe as R

try:
    import uharfbuzz as hb
except ImportError:  # 셰이핑 검사만 건너뛴다
    hb = None

# 문맥 — 이 글자 뒤에 시험할 글자를 놓고 그 문자 체계로 셰이핑한다
CONTEXTS = [("Zyyy", ""), ("Latn", "a"), ("Grek", "α"), ("Cyrl", "д"),
            ("Hang", "가"), ("Hani", "漢"), ("Kana", "か")]
# 문맥과 상관없는 기능 — 글자 하나를 바꾸지 않거나 문자 체계마다 달라야 하는 것
CONTEXT_SKIP = {"aalt", "locl", "ccmp", "liga", "dlig", "calt", "rlig", "rclt", "vert", "vrt2"}
POSITION_TEXT = "(17.4, 0/1) T. V, 7: 1% [A]"
# locl 언어 태그 → BCP 47
BCP47 = {"KOR": "ko", "JAN": "ja", "ZHT": "zh-TW", "ZHH": "zh-HK", "ZHTM": "zh-MO",
         "ZHS": "zh-CN"}
CORPUS = [
    "Hamburgefonstiv 0123456789 (a+b)=c",
    "다람쥐 헌 쳇바퀴에 타고파 2024년 1/2분기",
    "漢字 圖書館의設計者 社神者館兌 令和6年",
    "ひらがな カタカナ ぴょん ショッピング",
    "Ελληνικά Кириллица",
    "→ ← ≠ ≤ ■ ○ ★ ① ㈜ ‘인용’ “따옴”",
]
SAMPLES = 6


# --------------------------------------------------------------------------
# 글꼴 찾기
# --------------------------------------------------------------------------

def font_paths(build_dir, dir_name, prefix, styles, sub=""):
    return [(s["file"], os.path.join(build_dir, dir_name, sub, "%s-%s.ttf" % (prefix, s["file"])))
            for s in styles]


def find_baseline(root, baseline, prefix):
    """이전 판의 {스타일 파일 이름: (zip 또는 None, 경로)}. 힌팅을 뺀 판은 고르지 않는다.

    baseline 이 없으면 root/dist 에서 이 가족의 글꼴이 든 가장 새 zip 을 쓴다.
    """
    def pick(names):
        out = {}
        head = prefix + "-"
        for n in names:
            base = os.path.basename(n)
            if not (base.startswith(head) and base.endswith(".ttf")) or "unhinted" in n:
                continue
            style = base[len(head):-4]
            if "-" in style:          # MonoplexCJK- 가 MonoplexCJKNerdFont- 를 고르지 않게
                continue
            out.setdefault(style, n)
        return out

    candidates = [baseline] if baseline else sorted(
        glob.glob(os.path.join(root, "dist", "*.zip")), key=os.path.getmtime, reverse=True)
    for c in candidates:
        if c and os.path.isdir(c):
            got = pick(glob.glob(os.path.join(c, "**", "*.ttf"), recursive=True))
            if got:
                return c, {k: (None, v) for k, v in got.items()}
        elif c and zipfile.is_zipfile(c):
            with zipfile.ZipFile(c) as z:
                got = pick(z.namelist())
            if got:
                return c, {k: (c, v) for k, v in got.items()}
    return None, {}


def open_font(src):
    from fontTools.ttLib import TTFont
    zpath, path = src
    if zpath:
        import io
        with zipfile.ZipFile(zpath) as z:
            data = z.read(path)
        return TTFont(io.BytesIO(data)), data
    with open(path, "rb") as fp:
        data = fp.read()
    import io
    return TTFont(io.BytesIO(data)), data


# --------------------------------------------------------------------------
# 한 글꼴을 읽어 사실을 모은다 (프로세스마다 하나씩)
# --------------------------------------------------------------------------

def _layout(font, tag):
    if tag not in font or not font[tag].table.ScriptList:
        return [], set(), {}
    t = font[tag].table
    feats = t.FeatureList.FeatureRecord
    missing, triples, dflt = [], set(), {}
    for sr in t.ScriptList.ScriptRecord:
        if sr.Script.DefaultLangSys is None:
            missing.append(sr.ScriptTag)
        for lang, ls in [("dflt", sr.Script.DefaultLangSys)] + \
                [(r.LangSysTag.strip(), r.LangSys) for r in sr.Script.LangSysRecord]:
            if ls is None:
                continue
            for i in ls.FeatureIndex:
                triples.add((sr.ScriptTag, lang, feats[i].FeatureTag))
                if sr.ScriptTag == "DFLT" and lang == "dflt":
                    dflt.setdefault(feats[i].FeatureTag, []).extend(feats[i].Feature.LookupListIndex)
    return missing, triples, dflt


def _single_inputs(font, lookup_ids):
    """기능의 lookup 이 하나를 하나로 바꾸는 입력 글리프 (타입 1 · 3, 확장 포함)."""
    lookups = font["GSUB"].table.LookupList.Lookup
    out = set()
    for i in lookup_ids:
        lk = lookups[i]
        for st in lk.SubTable:
            if lk.LookupType == 7:
                st = st.ExtSubTable
            if hasattr(st, "mapping"):
                out |= set(st.mapping)
            elif hasattr(st, "alternates"):
                out |= set(st.alternates)
    return out


def _script_of(c):
    from fontTools import unicodedata as fud
    return fud.script(chr(c))


def _shape(hfont, names, text, script=None, lang=None, feats=None):
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    if script:
        buf.script = script
    if lang:
        buf.language = lang
    hb.shape(hfont, buf, feats or {})
    return ([names[i.codepoint] for i in buf.glyph_infos],
            [(p.x_advance, p.x_offset, p.y_offset) for p in buf.glyph_positions])


def analyze(job):
    """글꼴 하나의 사실. job = (열쇠, 소스, 검사 설정)."""
    key, src, cfg = job
    font, data = open_font(src)
    order = font.getGlyphOrder()
    cmap = font.getBestCmap()
    hmtx = font["hmtx"]
    glyf = font["glyf"] if "glyf" in font else None
    facts = {"key": key, "glyphs": len(order), "cmap": sorted(cmap),
             "fpgm": "fpgm" in font, "problems": [], "notes": []}

    # 윤곽과 폭 — 코드포인트마다 짧은 해시
    if cfg.get("hashes"):
        h = {}
        for c, n in cmap.items():
            if glyf is not None:
                co, ends, _ = glyf[n].getCoordinates(glyf)
                raw = repr((list(co), list(ends))).encode()
            else:
                raw = n.encode()
            h[c] = hashlib.blake2b(raw, digest_size=6).hexdigest() + ":%d" % hmtx[n][0]
        facts["hashes"] = h

    gsub_missing, gsub_triples, gsub_dflt = _layout(font, "GSUB")
    gpos_missing, gpos_triples, _ = _layout(font, "GPOS")
    facts["layout"] = sorted(("GSUB",) + t for t in gsub_triples) + \
        sorted(("GPOS",) + t for t in gpos_triples)
    for tag, miss in (("GSUB", gsub_missing), ("GPOS", gpos_missing)):
        if miss:
            facts["problems"].append(("scripts", "%s 의 기본 언어 시스템이 없는 스크립트: %s"
                                      % (tag, " ".join(miss))))

    facts["metrics"] = {
        "unitsPerEm": font["head"].unitsPerEm,
        "usWeightClass": font["OS/2"].usWeightClass,
        "xAvgCharWidth": font["OS/2"].xAvgCharWidth,
        "sTypoAscender": font["OS/2"].sTypoAscender,
        "sTypoDescender": font["OS/2"].sTypoDescender,
        "usWinAscent": font["OS/2"].usWinAscent,
        "usWinDescent": font["OS/2"].usWinDescent,
        "hhea.ascent": font["hhea"].ascent,
        "hhea.descent": font["hhea"].descent,
        "isFixedPitch": font["post"].isFixedPitch,
    }
    for nid in (1, 2, 4, 5, 6, 16, 17):
        rec = font["name"].getName(nid, 3, 1, 0x409)
        if rec:
            facts["metrics"]["name%d" % nid] = rec.toUnicode()

    # 글리프 수
    margin = 65535 - len(order)
    if margin < 0:
        facts["problems"].append(("glyphs", "글리프 %d 개로 상한을 넘는다" % len(order)))
    elif margin < cfg["minMargin"]:
        facts["notes"].append("글리프 %s 개, 상한까지 %s" % (format(len(order), ","), format(margin, ",")))

    # 호환 한자
    for lo, hi in cfg.get("canonical") or []:
        bad = []
        for c in range(lo, hi + 1):
            if c not in cmap:
                continue
            n = ud.normalize("NFC", chr(c))
            if len(n) == 1 and ord(n) != c and ord(n) in cmap and cmap[ord(n)] != cmap[c]:
                bad.append(chr(c))
        if bad:
            facts["problems"].append(("canonical", "호환 한자가 정준 한자와 다른 글리프: %d 자 (%s)"
                                      % (len(bad), " ".join("%s U+%04X" % (b, ord(b)) for b in bad[:20]))))

    # 고정폭
    if cfg.get("monospace"):
        unit = hmtx[cmap[ord("0")]][0]
        odd = sorted({(hmtx[n][0], c) for c, n in cmap.items()
                      if hmtx[n][0] % unit or hmtx[n][0] > 3 * unit})
        if odd:
            facts["problems"].append(("monospace", "폭이 칸(%d)의 0~3 배가 아닌 글자 %d 개: %s"
                                      % (unit, len(odd),
                                         " ".join("U+%04X(%d)" % (c, w) for w, c in odd[:12]))))

    # 힌팅
    want_fpgm = cfg.get("hinted")
    if want_fpgm is not None and facts["fpgm"] != want_fpgm:
        facts["problems"].append(("hinting", "힌팅 %s 판인데 fpgm 이 %s"
                                  % ("넣은" if want_fpgm else "뺀", "없다" if want_fpgm else "있다")))

    if hb is None or not cfg.get("shape"):
        font.close()
        return facts

    hfont = hb.Font(hb.Face(hb.Blob(data)))
    names = order

    # 문맥 — GSUB 기능이 공통 문자를 어느 문자 체계 옆에서든 똑같이 바꾸는가
    contexts = [(s, p) for s, p in CONTEXTS if not p or ord(p) in cmap]
    rev = defaultdict(list)
    for c, n in cmap.items():
        rev[n].append(c)
    for ftag, lks in sorted(gsub_dflt.items()):
        if ftag in CONTEXT_SKIP:
            continue
        cps = sorted(c for g in _single_inputs(font, lks) for c in rev.get(g, [])
                     if _script_of(c) in ("Zyyy", "Zinh"))
        if not cps:
            continue
        step = max(1, len(cps) // SAMPLES)
        for c in cps[::step][:SAMPLES]:
            got = {}
            for script, pre in contexts:
                g, _ = _shape(hfont, names, pre + chr(c), script, None, {ftag: True})
                got[script] = g[len(pre)] if len(g) > len(pre) else "?"
            if len(set(got.values())) > 1:
                facts["problems"].append(("context", "%s 로 %s(U+%04X) 가 문맥마다 다르게 바뀐다: %s"
                                          % (ftag, chr(c), c, ", ".join("%s→%s" % kv for kv in got.items()))))
                break

    # 자리 — 공통 문자의 커닝 · 결합 기호
    ref = None
    for script, pre in contexts:
        _, pos = _shape(hfont, names, pre + POSITION_TEXT, script)
        pos = pos[len(pre):]
        if ref is None:
            ref = (script, pos)
        elif pos != ref[1]:
            facts["problems"].append(("positions", "공통 문자의 자리가 %s 문맥과 %s 문맥에서 다르다"
                                      % (ref[0], script)))

    # locl · locl.features
    loc = cfg.get("locl")
    if loc:
        base_of = {}
        alt = defaultdict(dict)          # 소스 → {코드포인트: 대안 글리프}
        for n in order:
            head, dot, sid = n.rpartition(".")
            if dot and head.startswith(("uni", "u")) and sid in loc["sources"]:
                try:
                    c = int(head[3:] if head.startswith("uni") else head[1:], 16)
                except ValueError:
                    continue
                alt[sid][c] = n
        expect = []                      # (말, 언어, 기능, 코드포인트, 기대 글리프)
        for tag, (sid, enc) in sorted(loc["langs"].items()):
            cps = sorted(R.within_set(enc, alt[sid]))
            step = max(1, len(cps) // SAMPLES)
            pick = cps[::step][:SAMPLES]
            if not pick:
                facts["problems"].append(("locl", "%s 가 바꿀 %s 글리프가 하나도 없다" % (tag, sid)))
                continue
            for c in pick:
                expect.append((tag, BCP47.get(tag), None, c, alt[sid][c]))
                expect.append(("언어 없음", None, None, c, cmap[c]))
                if loc.get("default"):
                    expect.append((loc["default"], BCP47.get(loc["default"]), None, c, cmap[c]))
                for ftag, lang in loc["features"].items():
                    if lang == tag:
                        expect.append((ftag, None, ftag, c, alt[sid][c]))
        bad = []
        for what, lang, ftag, c, want in expect:
            g, _ = _shape(hfont, names, chr(c), None, lang, {ftag: True} if ftag else None)
            if g[0] != want:
                bad.append("%s %s→%s (기대 %s)" % (what, chr(c), g[0], want))
        if bad:
            facts["problems"].append(("locl", "%d 건: %s" % (len(bad), "; ".join(bad[:8]))))

    # 셰이핑 비교용 결과
    if cfg.get("corpus"):
        combos = [("", None, None)]
        combos += [(BCP47[t], BCP47[t], None) for t in loc["langs"] if t in BCP47] if loc else []
        combos += [(f, None, f) for f in sorted(gsub_dflt) if f not in ("aalt",)]
        combos += [(f, None, f) for f in (loc["features"] if loc else {}) if f not in gsub_dflt]
        res = {}
        for line in cfg["corpus"]:
            for label, lang, ftag in combos:
                g, pos = _shape(hfont, names, line, None, lang, {ftag: True} if ftag else None)
                res[(line, label)] = (" ".join(g), sum(p[0] for p in pos))
        facts["shaping"] = res
    font.close()
    return facts


# --------------------------------------------------------------------------
# 비교 · 보고
# --------------------------------------------------------------------------

def _block(c):
    from fontTools import unicodedata as fud
    return fud.block(chr(c))


def _chars(cps, limit=40):
    s = "".join(chr(c) if ud.category(chr(c))[0] not in "CZM" else "" for c in cps[:limit])
    more = " … 외 %d" % (len(cps) - limit) if len(cps) > limit else ""
    return (s or " ".join("U+%04X" % c for c in cps[:8])) + more


def diff(old, new):
    """두 글꼴 사실의 차이 — 보고서에 쓸 줄들."""
    lines = []
    if old["glyphs"] != new["glyphs"]:
        lines.append("글리프 수 %s → %s" % (format(old["glyphs"], ","), format(new["glyphs"], ",")))
    a, b = set(old["cmap"]), set(new["cmap"])
    for label, cps in (("더해진 코드포인트", sorted(b - a)), ("빠진 코드포인트", sorted(a - b))):
        if cps:
            by = defaultdict(list)
            for c in cps:
                by[_block(c)].append(c)
            lines.append("%s %d 개" % (label, len(cps)))
            lines += ["  - %s: %d — %s" % (k, len(v), _chars(v)) for k, v in sorted(by.items())]
    if "hashes" in old and "hashes" in new:
        changed = sorted(c for c in a & b if old["hashes"][c] != new["hashes"][c])
        width = [c for c in changed if old["hashes"][c].split(":")[1] != new["hashes"][c].split(":")[1]]
        if changed:
            by = defaultdict(list)
            for c in changed:
                by[_block(c)].append(c)
            lines.append("윤곽이나 폭이 바뀐 글자 %d 개 (그 가운데 폭이 바뀐 것 %d)" % (len(changed), len(width)))
            lines += ["  - %s: %d — %s" % (k, len(v), _chars(v)) for k, v in sorted(by.items())]
            if width:
                lines.append("  - 폭이 바뀐 글자: " + ", ".join(
                    "U+%04X %s→%s" % (c, old["hashes"][c].split(":")[1], new["hashes"][c].split(":")[1])
                    for c in width[:12]))
    la, lb = set(map(tuple, old["layout"])), set(map(tuple, new["layout"]))
    for label, s in (("기능이 새로 걸린 곳", lb - la), ("기능이 빠진 곳", la - lb)):
        if s:
            by = defaultdict(set)           # (표, 기능) → 스크립트/언어
            for t, sc, lang, f in s:
                by[(t, f)].add("%s/%s" % (sc, lang) if lang != "dflt" else sc)
            grouped = defaultdict(list)     # 같은 자리에 걸린 기능끼리 묶는다
            for (t, f), where in sorted(by.items()):
                grouped[(t, tuple(sorted(where)))].append(f)
            lines.append(label)
            lines += ["  - %s %s — %s" % (t, " ".join(fs), " ".join(where))
                      for (t, where), fs in sorted(grouped.items())]
    for k in sorted(set(old["metrics"]) | set(new["metrics"])):
        if old["metrics"].get(k) != new["metrics"].get(k):
            lines.append("%s: %r → %r" % (k, old["metrics"].get(k), new["metrics"].get(k)))
    if "shaping" in old and "shaping" in new:
        ch = [k for k in new["shaping"] if k in old["shaping"] and old["shaping"][k] != new["shaping"][k]]
        if ch:
            by = defaultdict(list)
            for line, label in ch:
                by[label or "기본"].append(line)
            lines.append("셰이핑 결과가 바뀐 경우 %d 개" % len(ch))
            for label, ls in sorted(by.items()):
                lines.append("  - %s: %s" % (label, " | ".join(l[:24] for l in ls)))
    return lines


def _group(items):
    """[(검사, 스타일, 말)] → [(검사, 말, 스타일들)] — 스타일만 다른 같은 문제를 묶는다."""
    by = defaultdict(list)
    for check, style, msg in items:
        by[(check, msg)].append(style)
    return [(c, m, ss) for (c, m), ss in sorted(by.items())]


def _styles(ss, total):
    return "모든 스타일" if len(ss) >= total else ", ".join(ss)


def _cfg(rec, variants, hinted, shape, hashes, corpus):
    rec = R.with_variant_locl(rec, variants)
    fin = rec.get("finalize", {})
    ver = rec.get("verify", {})
    loc = None
    if rec.get("locl"):
        langs = R.locl_langs(rec)
        loc = {"langs": langs, "default": rec["locl"].get("default"),
               "features": R.locl_features(rec), "sources": {v[0] for v in langs.values()}}
    # 호환 한자 가운데 정준 한자와 같아야 하는 범위. 기본은 KS X 1001 의 호환 한자다
    # (같은 한자의 다른 독음이라 자형이 같아야 한다). U+FA0C 이후의 JIS 호환 한자는
    # 일부러 다른 자형을 지키는 코드라 넣지 않는다.
    canon = [[int(a, 16), int(b, 16)] for a, b in
             ver.get("canonicalRanges", [["f900", "fa0b"]] if fin.get("mapCanonical") else [])]
    return {"minMargin": ver.get("minGlyphMargin", 1000),
            "canonical": canon,
            "monospace": bool(fin.get("os2", {}).get("isFixedPitch")),
            "hinted": hinted, "locl": loc, "shape": shape, "hashes": hashes,
            "corpus": (CORPUS + ver.get("corpus", [])) if corpus else None}


def run(rec, root, build_dir, families, styles, unhinted=None, baseline=None,
        compare=True, jobs=None, report_dir=None):
    """families = [(변종 이름, 접두어, 디렉터리 이름)]. 실패면 1."""
    if hb is None:
        print("verify: uharfbuzz 가 없어 셰이핑 검사(context · positions · locl · 셰이핑 비교)를"
              " 건너뛴다 — pip install uharfbuzz")
    hinting = bool(rec.get("finalize", {}).get("hinting"))
    report_dir = report_dir or os.path.join(build_dir, "report")
    jobs = jobs or max(1, min(8, (os.cpu_count() or 2) - 1))
    failed = 0
    for name, prefix, dir_name in families:
        variants = {} if name == "normal" else {name: True}
        cfg_main = _cfg(rec, variants, True if hinting else None, True, compare, compare)
        work = [(("new", s), (None, p), cfg_main) for s, p in font_paths(build_dir, dir_name, prefix, styles)]
        if unhinted:
            cfg_u = _cfg(rec, variants, False, False, False, False)
            work += [(("unhinted", s), (None, p), cfg_u)
                     for s, p in font_paths(build_dir, dir_name, prefix, styles, unhinted)]
        base_src, base = (None, {})
        if compare:
            base_src, base = find_baseline(root, baseline, prefix)
            want = {s["file"] for s in styles}
            work += [(("old", s), src, cfg_main) for s, src in base.items() if s in want]
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            facts = {f["key"]: f for f in ex.map(analyze, work)}

        # verify.known: {검사 이름: 까닭} — 알고 있는 문제는 보고만 하고 실패로 치지 않는다
        known = {k: v for k, v in rec.get("verify", {}).get("known", {}).items() if not k.startswith("$")}
        problems, knowns = [], []
        for (kind, style), f in sorted(facts.items()):
            if kind == "old":
                continue
            for check, msg in f["problems"]:
                item = (check, "%s%s" % (style, " (unhinted)" if kind == "unhinted" else ""), msg)
                (knowns if check in known else problems).append(item)
        notes = sorted({n for (kind, _), f in facts.items() if kind == "new" for n in f["notes"]})

        # 스타일끼리 커버리지
        sets = {s: set(f["cmap"]) for (kind, s), f in facts.items() if kind == "new"}
        cover = []
        if sets:
            union = set().union(*sets.values())
            for s, cs in sorted(sets.items()):
                if union - cs:
                    cover.append("%s 에 없는 글자 %d: %s" % (s, len(union - cs), _chars(sorted(union - cs), 20)))

        # 보고서
        os.makedirs(report_dir, exist_ok=True)
        out = ["# %s 검증" % dir_name, ""]
        out.append("## 불변 조건 — %s" % ("통과" if not problems else "실패 %d 가지" % len(_group(problems))))
        out.append("")
        total = len([k for k in facts if k[0] != "old"])
        out += ["- **%s** (%s) %s" % (c, _styles(ss, total), m) for c, m, ss in _group(problems)] \
            or ["- 어긴 것 없음"]
        if knowns:
            out += ["", "알려진 문제 (verify.known — 실패로 치지 않음):"]
            out += ["- **%s** (%s) %s — %s" % (c, _styles(ss, total), m, known[c])
                    for c, m, ss in _group(knowns)]
        if notes:
            out += ["", "알림:"] + ["- " + n for n in notes]
        if cover:
            out += ["", "스타일끼리 커버리지가 다른 곳:"] + ["- " + c for c in cover]
        out.append("")
        if compare:
            out.append("## 이전 판과 비교 — %s" % (os.path.relpath(base_src, root) if base_src else "이전 판 없음"))
            out.append("")
            summary = []
            for s in [st["file"] for st in styles]:
                if ("old", s) not in facts or ("new", s) not in facts:
                    continue
                d = diff(facts[("old", s)], facts[("new", s)])
                out.append("### %s" % s)
                out.append("")
                out += ["- " + l if not l.startswith("  ") else l for l in d] or ["- 바뀐 것 없음"]
                out.append("")
                head = [l for l in d if not l.startswith("  ")]
                summary.append((s, head))
        path = os.path.join(report_dir, "%s.md" % dir_name.replace(" ", ""))
        with open(path, "w", encoding="utf-8") as fp:
            fp.write("\n".join(out) + "\n")

        # 콘솔 요약
        print("verify %s: 불변 조건 %s · 보고서 %s" % (
            dir_name, "통과" if not problems else "실패 %d 가지" % len(_group(problems)),
            os.path.relpath(path, root)))
        for c, m, ss in _group(problems):
            print("  FAIL %s (%s) %s" % (c, _styles(ss, total), m[:160]))
        for c, m, ss in _group(knowns):
            print("  known %s (%s) %s" % (c, _styles(ss, total), known[c]))
        for n in notes:
            print("  note " + n)
        if compare and base_src:
            print("  이전 판 %s 과 비교:" % os.path.basename(base_src))
            by = defaultdict(list)
            for st, head in summary:
                for l in head or ["바뀐 것 없음"]:
                    by[l].append(st)
            for l, ss in sorted(by.items(), key=lambda kv: -len(kv[1])):
                print("    %s%s" % (l, "" if len(ss) == len(summary) else "  [%s]" % ", ".join(ss)))
        elif compare:
            print("  이전 판을 찾지 못해 비교하지 않았다")
        failed += bool(problems)
    return 1 if failed else 0
