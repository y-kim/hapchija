"""남의 힌팅 빌려 오기.

ttfautohint 를 마친 글꼴에서, 기증 글꼴과 윤곽이 점 하나까지 같은 글자의 글자
프로그램을 기증 글꼴 것으로 바꾼다. 세로로만 힌팅하는 프로그램이면 y 좌표만 같아도
된다 — 이탤릭처럼 옆으로 기울인 글자. 기증 글꼴의 fpgm·prep·CVT 는 ttfautohint 것
뒤에 붙이고, 함수 번호와 CVT 번호를 그만큼 민다.

ttfautohint 에는 한글 스크립트가 없어서 작은 크기에서 획이 뭉친다(12px 의 풀).
IBM Plex Sans KR 의 hinted 판은 FontLab 으로 힌팅한 뒤 크기별 DELTAP 로 손본
것이라, 그 글자들은 그대로 가져오는 것이 낫다.

번호를 옮기려면 밀어 넣은 값이 어디에 쓰이는지 알아야 한다. 그래서 스택을 따라가는
작은 흉내 기계를 쓰고, 모르는 명령이 나오면 멈춘다. 지금은 FontLab 이 만드는
글자 프로그램과 prep 만 안다.

레시피:

    "finalize": {
      "borrowHints": {
        "from": "IBM-Plex-Sans-KR/hinted/IBMPlexSansKR-{cjkSrc}.ttf",
        "within": ["AC00-D7A3"]
      }
    }

`within` 밖의 글자와, 기증 글꼴에 힌팅이 없는 글자는 ttfautohint 힌팅을 그대로 둔다.
"""

from __future__ import annotations

import array
import re

from fontTools.ttLib import TTFont
from fontTools.ttLib.tables import ttProgram

_OP = re.compile(r"^([A-Z0-9]+)\[([^\]]*)\]")

# FontLab fpgm 함수가 스택에서 꺼내는 인자(위에서부터)와 남기는 값의 수.
# prep 이 부르는 것만 적는다. 0 번(SCANCTRL·컷인·델타 설정)은 따로 다룬다.
#   2: CVT 를 차례로 반올림 (시작 번호, 개수)
#   7: CVT 를 둘씩 반올림 (시작 번호, 쌍 수) — 다음 번호를 남긴다
#   8: 크기별 줄기 폭 (CVT, 문턱 ppem 다섯, 0)
FONTLAB_CALLS = {2: (["n", "cvt"], 0), 7: (["n", "cvt"], 1), 8: (["p"] * 6 + ["cvt"], 0)}

# FontLab 의 0 번 함수가 prep 에서 정하는 값. 글자마다 앞에 붙여 그 글자 안에서만
# 쓴다. prep 에서 정하면 ttfautohint 글자까지 바뀐다.
FONTLAB_STATE = [["PUSH", "", [9, 3, 68]], ["SCVTCI", "", None], ["SDS", "", None], ["SDB", "", None]]


def _tokens(prog):
    """[명령, 플래그, 밀어 넣은 값]. PUSHB·NPUSHW 등은 모두 PUSH 로 묶는다."""
    out = []
    for a in prog.getAssembly():
        a = a.split("/*")[0].strip()
        if not a:
            continue
        m = _OP.match(a)
        if m:
            op = m.group(1)
            if op in ("PUSHB", "PUSHW", "NPUSHB", "NPUSHW"):
                out.append(["PUSH", "", []])
            else:
                out.append([op, m.group(2), None])
        else:
            out[-1][2].extend(int(v) for v in a.split())
    return out


def _assemble(toks):
    asm = []
    for op, flags, vals in toks:
        if op == "PUSH":
            if vals:
                asm.append("PUSH[ ]")
                asm.extend(str(v) for v in vals)
        else:
            asm.append("%s[%s]" % (op, flags))
    p = ttProgram.Program()
    p.fromAssembly(asm)
    p.getBytecode()
    return p


def _roles(toks, calls=None):
    """밀어 넣은 값마다 쓰임새(cvt · fn · pt …). 열쇠는 (토큰 번호, 값 번호)."""
    st, role, loop = [], {}, 1

    def pop(r=None):
        slot, v = st.pop()
        if r and slot is not None:
            if role.get(slot, r) != r:
                raise ValueError("한 값이 %s 와 %s 로 함께 쓰인다" % (role[slot], r))
            role[slot] = r
        return v

    for i, (op, _, vals) in enumerate(toks):
        if op == "PUSH":
            st.extend(((i, j), v) for j, v in enumerate(vals))
            continue
        if op in ("SVTCA", "IUP", "RTG", "RDTG", "RUTG", "RTHG"):
            pass
        elif op in ("MIAP", "MIRP"):
            pop("cvt"); pop("pt")
        elif op in ("MDAP", "MDRP", "SRP0", "SRP1", "SRP2"):
            pop("pt")
        elif op == "SLOOP":
            loop = pop("n")
            continue
        elif op in ("SHP", "IP"):
            for _ in range(loop):
                pop("pt")
        elif op.startswith("DELTAP"):
            for _ in range(pop("n")):
                pop("pt"); pop("arg")
        elif op.startswith("DELTAC"):
            for _ in range(pop("n")):
                pop("cvt"); pop("arg")
        elif op in ("SDS", "SDB", "SCVTCI"):
            pop("arg")
        elif op == "DUP":
            st.append(st[-1])
        elif op == "RCVT":
            pop("cvt"); st.append((None, None))
        elif op == "ROUND":
            pop(); st.append((None, None))
        elif op == "WCVTP":
            pop(); pop("cvt")
        elif op == "CALL" and calls is not None:
            fn = pop("fn")
            if fn not in calls:
                raise ValueError("모르는 함수 %d 를 부른다" % fn)
            args, ret = calls[fn]
            for r in args:
                pop(r)
            st.extend([(None, None)] * ret)
        else:
            raise ValueError("다룰 줄 모르는 명령 %s" % op)
        loop = 1
    return role


def _shift(toks, role, by):
    for (i, j), r in role.items():
        if r in by:
            toks[i][2][j] += by[r]


def _shift_fdefs(toks, by):
    """fpgm 안에서 FDEF · CALL · LOOPCALL 바로 앞에 밀어 넣은 맨 위 값이 함수 번호다."""
    for i, (op, _, _) in enumerate(toks):
        if op in ("FDEF", "CALL", "LOOPCALL"):
            prev = toks[i - 1]
            if prev[0] != "PUSH" or not prev[2]:
                raise ValueError("fpgm 의 함수 번호가 상수가 아니다")
            prev[2][-1] += by


def _parse_within(spec):
    out = []
    for item in spec:
        lo, _, hi = item.partition("-")
        out.append((int(lo, 16), int(hi or lo, 16)))
    return out


# 벡터를 바꾸는 명령. 글자 프로그램이 이것들 가운데 SVTCA[0](y 축)만 쓰면 세로로만
# 힌팅한다. IUP[1](x 축 보간)은 x 로 건드린 점이 없으면 아무 일도 하지 않는다.
_VECTOR_OPS = ("SVTCA", "SPVTCA", "SFVTCA", "SPVTL", "SFVTL", "SDPVTL", "SPVFS", "SFVFS", "SFVTPV")


def _y_only(toks):
    return all(op == "SVTCA" and flags == "0" for op, flags, _ in toks if op in _VECTOR_OPS)


def _same_outline(a, ga, b, gb, y_only=False):
    """점의 짜임이 같고 좌표가 같은가. y_only 면 y 좌표만 본다.

    세로로만 힌팅하는 프로그램은 x 좌표를 읽지 않으므로, 이탤릭처럼 옆으로 기울인
    글자에도 그대로 맞는다.
    """
    if a.isComposite() or b.isComposite():
        return False
    if list(a.endPtsOfContours) != list(b.endPtsOfContours):
        return False
    if [f & 1 for f in a.flags] != [f & 1 for f in b.flags]:
        return False
    ca, cb = a.getCoordinates(ga)[0], b.getCoordinates(gb)[0]
    if y_only:
        return [y for _, y in ca] == [y for _, y in cb]
    return list(ca) == list(cb)


def borrow(path, donor_path, within):
    """path 를 고쳐 쓴다. (옮긴 글자 수, 윤곽이 달라 못 옮긴 글자 수)."""
    font, donor = TTFont(path), TTFont(donor_path)
    for tag in ("fpgm", "prep", "cvt "):
        if tag not in font:
            raise SystemExit("ERROR: borrowHints 는 ttfautohint 를 마친 글꼴에만 쓴다 (%s 없음)" % tag)
    # IBM Plex Sans KR 의 Thin 처럼 hinted 판인데 힌팅이 없는 것도 있다
    if "fpgm" not in donor or "prep" not in donor:
        font.close()
        return 0, 0
    nfn = font["maxp"].maxFunctionDefs
    ncvt = len(font["cvt "].values)

    ft = _tokens(donor["fpgm"].program)
    _shift_fdefs(ft, nfn)

    pt = _tokens(donor["prep"].program)
    if not (pt[0][0] == "PUSH" and pt[0][2] == [0] and pt[1][0] == "CALL"):
        raise SystemExit("ERROR: %s 의 prep 이 FontLab 꼴(0 CALL 로 시작)이 아니다" % donor_path)
    pt = pt[2:]
    _shift(pt, _roles(pt, FONTLAB_CALLS), {"cvt": ncvt, "fn": nfn})
    # DELTAC 가 쓰는 델타 설정과, 반올림을 격자로 되돌리는 것만 앞에 둔다
    pt = [["PUSH", "", [9, 3]], ["SDS", "", None], ["SDB", "", None], ["RTG", "", None]] + pt

    ranges = _parse_within(within)
    fc, dc = font.getBestCmap(), donor.getBestCmap()
    fg, dg = font["glyf"], donor["glyf"]
    moved = differ = 0
    longest = 0
    for cp, name in sorted(fc.items()):
        if not any(lo <= cp <= hi for lo, hi in ranges) or cp not in dc:
            continue
        src = dg[dc[cp]]
        prog = getattr(src, "program", None)
        if not prog or not prog.getBytecode():
            continue
        dst = fg[name]
        gt = _tokens(prog)
        if not _same_outline(dst, fg, src, dg, _y_only(gt)):
            differ += 1
            continue
        try:
            _shift(gt, _roles(gt), {"cvt": ncvt})
        except ValueError as e:
            raise SystemExit("ERROR: %s U+%04X: %s" % (donor_path, cp, e))
        dst.program = _assemble(FONTLAB_STATE + gt)
        longest = max(longest, len(dst.program.getBytecode()))
        moved += 1

    for tag, extra in (("fpgm", ft), ("prep", pt)):
        p = ttProgram.Program()
        p.fromBytecode(font[tag].program.getBytecode() + _assemble(extra).getBytecode())
        font[tag].program = p
    font["cvt "].values = array.array("h", list(font["cvt "].values) + list(donor["cvt "].values))

    m, dm = font["maxp"], donor["maxp"]
    m.maxFunctionDefs = nfn + dm.maxFunctionDefs
    m.maxStackElements = max(m.maxStackElements, dm.maxStackElements + len(FONTLAB_STATE[0][2]))
    m.maxSizeOfInstructions = max(m.maxSizeOfInstructions, longest)
    m.maxStorage = max(m.maxStorage, dm.maxStorage)
    m.maxTwilightPoints = max(m.maxTwilightPoints, dm.maxTwilightPoints)
    m.maxZones = max(m.maxZones, dm.maxZones)
    font.save(path)
    font.close()
    return moved, differ
