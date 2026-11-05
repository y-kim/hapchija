"""자형을 손보는 op — 획을 옮겨 심고, 늘이고, 세우고, 벌린다.

글꼴에는 같은 부수를 다른 꼴로 그린 글자가 같이 들어 있는 일이 많다. 일본
표준은 상용한자에서만 부수를 약자로 바꾸고 나머지는 전통 자형으로 두기 때문
이다. 그래서 고칠 자형의 본보기를 **같은 글꼴 안에서** 찾을 수 있다. 부수
글리프(U+2EAC 등)를 눌러 넣는 것과 다르다. 그쪽은 방 너비에 맞추려 가로로
43% 까지 눌러야 해서 세로획이 가로획의 절반이 된다.

여기 op 들은 모두 `hapchija.outline` 의 연장으로 그 일을 한다. 자리와 크기를
손으로 적지 않는다 — 잴 것은 op 이 글리프를 보고 잰다. 굵기마다 획 두께가
다르니 손으로 적은 값은 한 굵기에서만 맞는다.

    copyGlyph    윤곽을 통째로 옮긴다 (한쪽 몸만 가져올 수도 있다)
    swapSide     변 또는 방 하나를 바꾼다 (벌려 넣을 수도 있다)
    carvePart    획 하나를 목에서 잘라 떼어 옮긴다
    swapRadical  변을 통째로 바꾼다 — 기준 자형으로 가르고, 온전한 변을 끼운다
"""

from __future__ import annotations

import math
import re

import fontforge
import psMat

from . import outline as O
from .ops import op, selected_glyphs, selected_codepoints
from .recipe import cp

HEX = re.compile(r"[0-9a-fA-F]{4,6}\Z")


_LENT = {}                       # 다른 글꼴에서 빌린 것 — 한 번만 연다


def donor_font(ctx, spec, font):
    """기증자가 든 글꼴. `fromFont` 를 적으면 **다른 소스 글꼴**을 열어 쓴다.

    같은 집안의 다른 글꼴에 원하는 자형이 있을 때가 있다. 極 의 又 는 Plex JP
    에서 삐침이 아래쪽에서 시작해 亟 의 세로획과 따로 노는데, SC 는 삐침이
    윗가로획에서 내려와 편수자료와 같다. 대안 자형을 통째로 쓰는 것이 아니라
    **又 의 꼴만** 빌리는 것이다.

        "fromFont": "IBM-Plex-Sans-SC/IBMPlexSansSC-{cjkSrc}.ttf"

    `{...}` 에는 레시피 styles 항목의 이름을 쓴다 — 굵기마다 같은 굵기의 파일이
    열리므로 획 두께가 저절로 맞는다. 한 번 연 글꼴은 그대로 들고 있는다.
    """
    tmpl = spec.get("fromFont")
    if not tmpl:
        return font
    path = ctx.path(tmpl)
    if path not in _LENT:
        _LENT[path] = fontforge.open(path)
    return _LENT[path]


def donor_glyph(font, spec, key="from"):
    """기증자 글리프. '9ed8' 같은 코드포인트도, 'uni98FE.vari2' 같은 이름도 받는다.

    한국 자형이 이체자 글리프에만 있는 부수가 있다. 飠 는 飢 飯 飽 飾 넷의
    `.vari2` 에만 곧게 내려오는 꼴로 들어 있고, 코드포인트가 달린 글자는 모두
    사선 꼴이다. 그런 기증자는 이름으로 적어야 한다.
    """
    name = spec.get(key)
    if name is None:
        return None
    if HEX.match(name):
        code = cp(name)
        return font[code] if code in font else None
    return font[name] if name in font else None


def relay(glyph, groups, merge=True):
    """윤곽 묶음 여럿을 한 글리프에 담는다 — 폭을 지키고 안팎 방향을 다시 잡는다.

    윤곽을 다시 담으면 감김 방향이 흐트러져 속공간이 메워진다. 그래서 담은 뒤
    `correctDirection` 을 부른다. 겹쳐 놓은 획은 `removeOverlap` 이 한 몸으로
    녹인다. transform 은 advance width 까지 옮기므로 폭은 따로 되돌려 놓는다.

    `merge` 를 끄면 둘 다 부르지 않는다. 먹을 더하지 않고 점만 옮긴 때에 쓴다 —
    Plex 의 윤곽은 본디 겹쳐 있어서, 볼 일 없는 곳까지 다시 짜이면 손대지 않은
    획의 점 수까지 달라진다.
    """
    width = glyph.width
    lay = fontforge.layer()
    lay.is_quadratic = glyph.foreground.is_quadratic
    for group in groups:
        for contour in group:
            lay += contour
    glyph.foreground = lay
    if merge:
        glyph.removeOverlap()
        glyph.correctDirection()
    glyph.width = width


# --------------------------------------------------------------------------
# 옮겨 심기
# --------------------------------------------------------------------------


@op("copyGlyph")
def op_copy_glyph(ctx, font, spec, source_half):
    """한 글자의 윤곽을 다른 글자에 통째로 옮긴다 — 크기도 자리도 건드리지 않는다.

    고칠 자형이 그 글꼴의 다른 코드포인트에 이미 온전히 들어 있을 때 쓴다.
    黙(U+9ED9)은 신자체 코드포인트라 黑 변의 상자 안이 2×2 격자(黒)인데, 같은
    글꼴의 구자체 默(U+9ED8)은 상자 안에 丷 두 점을 찍은 한국 자형이고 방까지
    같다. 그러면 옮겨 심을 것이 아니라 그 글리프가 곧 답이다.

        {"op": "copyGlyph", "from": "9ed8", "cps": ["9ed9"]}

    `side` 를 적으면 기증자의 **한쪽 몸만** 가져온다. 홀로 선 글자가 일본 자형
    이고 그것이 방으로 든 글자는 한국 자형인 일이 있다 — 益 은 일본 자형인데
    溢 隘 縊 은 모두 한국 자형이라, 溢 의 오른쪽 몸을 가져와 益 로 삼는다.

        {"op": "copyGlyph", "from": "6ea2", "side": "right",
         "fill": "cut", "cps": ["76ca"]}

    그런 몸은 변 옆에 들어가느라 좁다 (溢 의 益 은 230 쯤 좁다). `fill` 을 `"cut"`
    으로 적으면 **받는 글자 제 먹 상자**에 맞춘다 — 왼끝을 제 먹 왼끝에 대고,
    모자라는 폭만큼 가로획을 잘라 벌려 오른끝까지 채운다. 가로로 늘이지 않는다:
    1.32배 늘이면 皿 의 세로획이 72–77 에서 80–94 로 굵어진다. 벌린 몫은 굵기마다
    제 먹 상자에서 다시 재므로 (224–230) 적을 값이 없다.

    폭은 받는 쪽 제 것을 지킨다.

    `create` 를 참으로 적으면 이 소스에 없는 글자를 기증자 폭으로 새로 낸다.

        {"op": "copyGlyph", "from": "6372", "create": true, "cps": ["6dc3"]}
    """
    donor = donor_glyph(font, spec)
    if donor is None:
        return
    side = spec.get("side")
    src = list(donor.foreground)
    if side:
        src, how = O.part_side(src, donor.width, side)
        if src is None:
            print("copyGlyph: %s 에서 %s 을 못 가름 (%s)" % (donor.glyphname, side, how))
            return
    if spec.get("create"):
        # 이 소스에 없는 글자를 새로 낸다 — 淃 은 JP 에 없어 SC 가 채우던 것을 JP 捲 으로
        for code in selected_codepoints(spec):
            if code not in font:
                g = font.createChar(code, "uni%04X" % code)
                g.width = donor.width
    done = []
    for glyph in selected_glyphs(font, spec):
        if glyph.glyphname == donor.glyphname:
            continue
        own = O.bbox(list(glyph.foreground)) if len(glyph.foreground) else None
        part = O.dup(src)
        note = ""
        if spec.get("fill") == "cut" and own:
            pb = O.bbox(part)
            for contour in part:
                contour.transform(psMat.translate(own[0] - pb[0], 0))
            delta = (own[1] - own[0]) - (pb[1] - pb[0])
            if delta > 1:
                wide, info = O.widen_across(part, delta, anchor="left")
                if wide is None:
                    print("copyGlyph: %s 를 못 벌렸다 — %s" % (glyph.glyphname, info))
                    continue
                part, note = wide, " 벌림 %d" % round(delta)
        relay(glyph, [part])
        done.append(glyph.glyphname + note)
    if done:
        print("copyGlyph: %s <- %s%s"
              % (", ".join(done), donor.glyphname, " 의 " + side if side else ""))


def _split_side(ctx, one, spec, side, code=None):
    """기증자가 녹아붙어 윤곽대로 갈리지 않을 때 — 가는 굵기를 안내로 가른 `side` 쪽.

    `splitBoxes` 에 기증자 코드마다 **왼쪽 성분(변)** 을 고를 상자를 적는다. 상자로
    고른 윤곽 수가 가는 굵기와 다르면 `ops.isolate_part` 가 같은 글자의 가는 굵기를
    안내로 `outline.split_glyph` 로 가른다. `split` 은 안내로 쓸 소스 글꼴 틀이다.
    `code` 를 주면 그 글자의 가는 굵기를 안내로 삼는다 (복사해 온 글리프).
    """
    from .ops import isolate_part
    bxs = spec.get("splitBoxes", {})
    code = one.unicode if code is None else code
    key = next((k for k in bxs if int(k, 16) == code), None)
    if key is None or "split" not in spec or code < 0:
        return None
    em = ctx.em_ascent + ctx.em_descent
    got = isolate_part(ctx, one, code, bxs[key], spec["split"], em)
    if not got:
        return None
    return [c.dup() for c in (got[1] if side == "right" else got[0])]


@op("swapSide")
def op_swap_side(ctx, font, spec, source_half):
    """변 또는 방 하나를 다른 글자에서 떼어 와 바꾼다 — 제 좌표 그대로.

    같은 글꼴에서 짜임이 같은 (변+방) 글자를 찾으면, 그 방이 앉는 자리가 이미
    맞다. 贈 의 曾 은 신자체라 위가 «丷» 인데 譄(U+8B44) 의 曾 은 구자체 «八»
    이고, 둘 다 변이 하나에 방이 曾 이다. 譄 의 방을 제 좌표째 옮기면 된다.

        {"op": "swapSide", "from": "8b44", "side": "right", "cps": ["8d08"]}
        {"op": "swapSide", "from": "uni98FE.vari2", "side": "left", "cps": ["9928"]}

    `side` 는 **기증자에서 가져올 쪽**이다. 받는 쪽에서는 그 반대쪽만 남긴다.
    `fromSide` 를 적으면 기증자에서는 그쪽을 떼어 받는 쪽의 `side` 자리에 넣는다 —
    姬 의 방(臣) 자리에 巸 의 변(𦣝). 자리가 다르므로 `fit` 과 함께 쓴다:
    `"cut"` 은 늘이지 않고 왼끝을 대고 가로획을 잘라 벌려 본디 상자를 채운다.
    눌러 맞추거나 갈라 밀지 않는다 — 가로로 누르면 방의 세로획이, 갈라 밀면
    가로획이 저 혼자 얇아진다.

    `from` 에 기증자를 **여럿** 적으면 앞에서부터 되는 것을 쓴다 — 굵기마다
    윤곽이 갈리기도 하고 녹기도 하기 때문이다. `fit` 을 `"box"` 로 적으면 받는
    쪽이 본디 그 자리에 두었던 상자에 맞춘다.

        {"op": "swapSide", "from": ["55a9", "7498"], "side": "right",
         "fit": "box", "cps": ["8f38"]}                       輸 — 兪 ← 喩

    기증자가 굵은 굵기에서 변·방이 녹아붙어 윤곽대로 갈리지 않으면(`fit="box"` 의
    크기가 어긋남), `split` 과 `splitBoxes` 가 있을 때 같은 기증자를 가는 굵기를
    안내로 다시 갈라 본다 — 輸 Bold 는 喩 의 口 가 兪 에 녹아붙어 있다.
    받는 글자가 다른 글자를 복사해 온 것이면 (그 코드가 가는 굵기 글꼴에 없으면)
    `guideAs` 에 본디 글자의 코드를 적어 그 가는 굵기를 안내로 삼는다 — 淃 은 JP 에
    없어 捲 을 복사해 받고, 氵 는 港 에서 가져온다.
    받는 글자의 코드를 `splitBoxes` 에 적으면 받는 쪽도 늘 그렇게 가른다 — 諭
    Regular·Text 는 人 지붕이 言 의 첫 가로획과 녹아 한 윤곽이다.

        {"op": "swapSide", "from": ["55a9", "7498"], "side": "right", "fit": "box",
         "split": "IBM-Plex-Sans-JP/IBMPlexSansJP-{cjkSrc}.ttf",
         "splitBoxes": {"55a9": [[0, -0.15, 0.33, 0.9]]}, "cps": ["8f38"]}

    `spread` 를 적으면 옮겨 온 조각만 **가로획을 잘라 벌린다**. 僧 의 曾 은 增 의
    것이 亻 쪽으로 23 좁아, 왼쪽으로만 그만큼 벌려야 한다 (`anchor` 를 오른쪽에
    두면 그쪽 끝이 붙박이가 되어 반대쪽으로만 벌어진다). 벌린 몫은 굵기마다 같은
    값을 쓴다 — SemiBold 의 틈으로 정한 값이라 SemiBold 는 딱 붙고 Bold 는 저절로
    살짝 겹치며, 그 몫은 removeOverlap 이 한 몸으로 녹인다.

        {"op": "swapSide", "from": "589e", "side": "right",
         "spread": {"by": 23, "anchor": "right", "knives": "one"},
         "cps": ["50e7"]}

    가르는 자리는 `outline.part_side` 가 찾는다. 윤곽이 이미 변·방으로 갈려
    있으면 가장 넓은 틈에서 나누고, 한 윤곽으로 이어져 있으면 맞댄 세로 변에서
    자른다. 변·방이 세로로 겹치는 글자도 있으니 (館 의 飠 는 官 밑으로 -14 들어
    간다) 갈린 결과를 상자로 다시 재어 고르면 안 된다.
    """
    side = spec.get("side", "right")
    other = "left" if side == "right" else "right"
    from_side = spec.get("fromSide", side)      # 기증자에서 떼어 올 쪽 (姬 ← 巸 의 왼쪽 𦣝)
    spread = spec.get("spread")
    fit = spec.get("fit")
    cands = []
    for one in donor_list(font, spec):
        # 기증자 코드를 `splitBoxes` 에 적었으면 늘 가는 굵기를 안내로 가른다 —
        # 淃 에 줄 捲 의 卷 은 SemiBold 부터 扌 와 한 윤곽이다.
        alt = _split_side(ctx, one, spec, from_side) if any(
            int(k, 16) == one.unicode for k in spec.get("splitBoxes", {})) else None
        if alt is not None:
            cands.append((one, alt, "가는 굵기를 안내로 가름"))
            continue
        got, why = O.part_side(list(one.foreground), one.width, from_side)
        if got is None:
            print("swapSide: %s 에서 %s 을 못 가름 (%s)" % (one.glyphname, side, why))
            continue
        cands.append((one, got, why))
    if not cands:
        return
    done = []
    for glyph in selected_glyphs(font, spec):
        if glyph.glyphname in {one.glyphname for one, _, _ in cands}:
            continue                       # 기증자 제 글리프는 건드리지 않는다
        # 받는 쪽도 녹아붙었으면 (諭 Regular 는 人 지붕이 言 첫 가로획과 한 윤곽)
        # `splitBoxes` 에 제 코드를 적어 가는 굵기를 안내로 가른다.
        gcode = cp(spec["guideAs"]) if "guideAs" in spec else None
        guided = _split_side(ctx, glyph, spec, other, gcode)
        if guided is not None:
            kept, mine = guided, _split_side(ctx, glyph, spec, side, gcode)
        else:
            kept, how_k = O.part_side(list(glyph.foreground), glyph.width, other)
            if kept is None:
                print("swapSide: %s 에서 %s 을 못 가름 (%s)" % (glyph.glyphname, other, how_k))
                continue
            # 받는 쪽이 본디 그 자리에 두었던 상자를 먼저 잰다 — 기증자를 고르는
            # 잣대이자, fit="box" 일 때 맞출 자리다.
            mine, _ = O.part_side(list(glyph.foreground), glyph.width, side)
        box = O.bbox(mine) if mine else None
        donor, src, how = None, None, None
        for one, got, why in cands:
            # 크기로 거르는 것은 **제 자리에 맞춰 넣을 때(fit="box")** 만이다.
            # 제 좌표 그대로 옮길 때는 두 조각의 크기가 달라도 그것이 제대로다
            # (譄 의 曾 은 贈 제 것보다 21% 넓다 — 변이 貝 라 좁게 앉았던 것이다).
            if fit == "box" and box is not None and not _like(got, box):
                alt = _split_side(ctx, one, spec, side)
                if alt is not None and _like(alt, box):
                    donor, src, how = one, alt, "가는 굵기를 안내로 가름"
                    break
                print("swapSide: %s 의 %s 이 %s 의 자리와 크기가 어긋난다 (%s) — 다음 기증자로"
                      % (one.glyphname, side, glyph.glyphname,
                         " ".join("%d" % round(v) for v in O.bbox(got))))
                continue
            donor, src, how = one, got, why
            break
        if src is None:
            print("swapSide: %s 에 쓸 기증자가 없다 — 넘긴다" % glyph.glyphname)
            continue
        part, note = O.dup(src), ""
        if fit == "box":
            # 받는 쪽이 본디 두었던 상자에 맞춘다. 같은 짜임이 아니어서 방이 앉는
            # 자리가 조금 다를 때 쓴다 (輸 의 兪 는 喩 것보다 4% 넓고 3% 낮다).
            # 가로·세로를 따로 맞추므로 획 두께가 조금 달라진다 — 제 좌표 그대로
            # 놓을 수 있으면 그쪽이 낫다.
            if box is None:
                print("swapSide: %s 의 본디 %s 상자를 못 쟀다" % (glyph.glyphname, side))
                continue
            part, sx, sy = O.fit_box(part, box)
            note = " 맞춤 %.2f×%.2f" % (sx, sy)
        elif fit == "cut":
            # 늘이지 않고 잘라 벌린다 — 왼끝을 받는 쪽 본디 상자 왼끝에 대고, 모자라는
            # 폭만큼 가로획을 잘라 벌려 오른끝까지 채운다 (copyGlyph 의 fill="cut").
            # 姬 의 臣 자리에 巸 의 𦣝 (416 → 526) — 늘이면 세로획이 1.26배 굵어진다.
            if box is None:
                print("swapSide: %s 의 본디 %s 상자를 못 쟀다" % (glyph.glyphname, side))
                continue
            pb = O.bbox(part)
            for contour in part:
                contour.transform(psMat.translate(box[0] - pb[0], 0))
            delta = (box[1] - box[0]) - (pb[1] - pb[0])
            if delta > 1:
                wide, info = O.widen_across(part, delta, anchor="left")
                if wide is None:
                    print("swapSide: %s 를 못 벌렸다 — %s" % (glyph.glyphname, info))
                    continue
                part = wide
            note = " 벌림 %d" % round(delta)
        if spread:
            wide, info = O.widen_across(part, spread["by"],
                                        bands=_one_band(part, spread),
                                        anchor=spread.get("anchor", "center"),
                                        share=spread.get("share", "even"))
            if wide is None:
                print("swapSide: %s 를 못 벌렸다 — %s" % (glyph.glyphname, info))
                continue
            part = wide
        relay(glyph, [kept, part] if other == "left" else [part, kept])
        done.append(glyph.glyphname + note)
    if done:
        print("swapSide: %s <- %s 의 %s (%s)"
              % (", ".join(done), donor.glyphname, side, how))



# --------------------------------------------------------------------------
# 늘이기
# --------------------------------------------------------------------------


def _overlaps(b, r):
    """윤곽 상자 b 가 네모 r 에 걸치는가 — 둘 다 (x0, x1, y0, y1)."""
    return b[0] <= r[1] and r[0] <= b[1] and b[2] <= r[3] and r[2] <= b[3]


def _in_box(ctx, glyph, box):
    """비율로 적은 상자를 이 글리프의 단위로 — (x0, y0, x1, y1)."""
    em = ctx.em_ascent + ctx.em_descent
    width = glyph.width or em
    x0, y0, x1, y1 = box[:4]
    return x0 * width, y0 * em, x1 * width, y1 * em


def _rect(ctx, glyph, box):
    """같은 것을 `outline` 이 쓰는 차례로 — (x0, x1, y0, y1)."""
    x0, y0, x1, y1 = _in_box(ctx, glyph, box)
    return x0, x1, y0, y1


def _one_band(contours, spread):
    """`knives: "one"` 이면 **한 벌의 칼날**을 온 높이에 쓴다 — 그 띠 하나만 준다.

    높이마다 따로 칼날을 잡으면, 두 높이에 걸친 획이 서로 다르게 밀려 어긋난다
    (僧 의 曾 은 지붕·丷·네모·日 이 저마다 다른 칼날을 얻는다). 조각이 가장 많은
    띠 — 그 글자의 세로 구조가 가장 잘 드러난 높이 — 에서 칼날을 잡아 온 높이에
    쓰면 그런 일이 없다. `widen_across` 는 띠 밖의 점에 가장 가까운 띠의 계획을
    쓰므로, 띠 하나만 주면 그것이 곧 «전부에 쓴다» 가 된다.
    """
    if spread.get("knives") != "one":
        return None
    bands = O.knife_bands(contours)
    if not bands:
        return None
    return [max(bands, key=lambda b: len(O.slices(contours, band=b)[1]))]


def donor_list(font, spec):
    """기증자들. `from` 에 여럿 적으면 앞에서부터 되는 것을 쓴다.

    같은 부수를 가진 글자라도 굵기에 따라 윤곽이 갈리기도 하고 녹기도 한다.
    輸 의 兪 는 喩 에서 가져오는데 Bold 에서는 喩 의 口 와 兪 가 한 윤곽이라
    갈리지 않아 瑜 로 넘어간다. 굵기마다 다른 기증자를 손으로 적지 않아도
    되도록, 레시피에는 **고를 차례** 만 적는다.
    """
    want = spec.get("from")
    names = want if isinstance(want, list) else [want]
    for name in names:
        one = donor_glyph(font, {"from": name})
        if one is not None:
            yield one


def _like(part, box, slack=0.15):
    """가른 조각이 받을 자리와 비슷한 크기인가 — 아니면 제대로 갈리지 않은 것이다.

    맞댄 자리에서 자르면 늘 무언가 나오므로, 나온 것이 **그 몸 하나** 인지 따로
    봐야 한다. 같은 부수를 옮겨 심는 것이니 받을 자리와 크기가 비슷해야 한다.
    喩 Bold 의 兪 는 口 와 녹아 있어 잘라 보면 갓만 나오고(키가 받을 자리의 0.33),
    瑜 Bold 은 王 과 녹아 절반만 나온다(0.50).
    """
    x0, x1, y0, y1 = O.bbox(part)
    for got, want in ((x1 - x0, box[1] - box[0]), (y1 - y0, box[3] - box[2])):
        if want <= 0 or abs(got / want - 1.0) > slack:
            return False
    return True


def _weld(part, rest, spec):
    """조각의 가로획 끝을 **남은 몸 속으로 밀어 넣는다** — 맞댄 자리에 실낱이 없게.

    조각과 몸이 가까이 있어도 변끼리 떨어져 있으면 removeOverlap 이 한 몸으로
    녹이지 못한다. 그렇다고 조금만 겹치면 그 자리가 뾰족하게 남는다. 끝을 몸의
    **먹 구간 한복판** 까지 밀면 완전히 묻히므로, 얼마나 미는지가 결과를 바꾸지
    않는다 (極 의 又 는 윗바 왼끝을 亟 의 세로획 속으로 39–48 밀어 넣는다 —
    그 값이 굵기마다 다른 것은 세로획이 굵어지기 때문일 뿐이다).

    `{"row": 1, "side": "left"}` — 조각의 가로획을 위에서부터 세어 그 획의 끝.
    """
    row = spec.get("row", 1)
    side = spec.get("side", "left")
    bars = _bars(part, O.bbox(part), spec.get("share", 0.35))
    if len(bars) < row:
        return " 밀 가로획 없음"
    lo, hi, bx0, bx1 = bars[row - 1]
    was = O.snap_x(part, bx0 if side == "left" else bx1)
    m = O.part_mask(rest)
    y = int((lo + hi) / 2)
    got = O.runs(m[1000 - y]) if 0 <= 1000 - y < m.shape[0] else []
    near = ([r for r in got if r[1] < was] if side == "left"
            else [r for r in got if r[0] > was])
    if not near:
        return " 밀 몸이 없음"
    run = near[-1] if side == "left" else near[0]
    # 가까운 먹만 문다. 멀리 있는 다른 성분을 물면 조각이 글자를 가로지른다
    # (極 Bold 에서 亟 의 세로획 대신 木 변까지 갔다).
    far = spec.get("reach", 0.12) * 1000
    if (was - run[1] if side == "left" else run[0] - was) > far:
        return " 밀 몸이 멀다"
    now = round((run[0] + run[1]) / 2.0)
    for c in part:
        for p in c:
            if abs(p.x - was) <= 2 and lo - 2 <= p.y <= hi + 2:
                p.x = now
    return " 밀어넣음 %d→%d" % (was, now)


def clip_to(contours, boxes):
    """**남길 네모들만 오려 그 합집합** — 흰 칸이 섞인 자리를 지우는 길.

    감김이 반대인 네모를 얹어 도려내는 길은 네모가 먹 안에 온전히 들 때만 쓴다.
    밖으로 나가면 그 부분이 도리어 먹이 된다 (册 의 옛 다리 자리는 흰 칸이 섞여
    있어 통째로 검게 찼다). 그래서 **지울 것을 덮지 말고 남길 것을 덮는다.**
    네모마다 따로 오려 겹쳐 놓으면, 겹친 자리는 removeOverlap 이 한 몸으로 녹여
    맞댄 자국이 남지 않는다.

    곡선은 곡선인 채로 쪼갠다 (`outline.loop_clip`). 돌아오는 것은 윤곽 묶음이다.
    """
    out = []
    for x0, x1, y0, y1 in boxes:
        loops = O.arcs(contours[0]) and None                # 자리 채움 (아래에서 다시)
        got = None
        for a, b, c in ((-1.0, 0.0, x0), (1.0, 0.0, -x1),
                        (0.0, -1.0, y0), (0.0, 1.0, -y1)):
            got = O.clip_contours(contours, a, b, c) if got is None \
                else O.loops_clip(got, a, b, c)
            if not got:
                break
        for nodes in got or []:
            # 자르개가 남기는 **부스러기** 는 버린다. 경계가 먹의 모서리를 스치면
            # 넓이가 거의 없는 세모가 떨어져 나온다 (册 Bold 에서 448 — 버릴
            # 다리의 갈고리 끝이다). 가장 가는 획도 1000 을 넘는다.
            if len(nodes) >= 3 and abs(O.loop_area(nodes)) >= 600:
                out.append(O.loop_contour(nodes))
    kept, _ = O.tidy(out)
    return [c for c in kept if len(c) >= 3]


def _inside(b, r):
    """윤곽 상자 b 가 네모 r 안에 온전히 드는가 — 둘 다 (x0, x1, y0, y1)."""
    return r[0] <= b[0] and b[1] <= r[1] and r[2] <= b[2] and b[3] <= r[3]


def _fits(b, rect, slack):
    """상자 b 가 네모 rect 안에 드는가 — 둘 다 (x0, x1, y0, y1)."""
    return (rect[0] - slack <= b[0] and b[1] <= rect[1] + slack
            and rect[2] - slack <= b[2] and b[3] <= rect[3] + slack)


def _between_legs(contours, rect):
    """**두 흰 칸 사이에 낀 세로획** — [(x0, x1)] 하나.

    기둥이 흰 칸 둘 사이에 끼어 있으면 먹 줄기의 길이로는 못 찾는다. 옆의 벽도
    똑같이 길어 한 덩이로 걸리기 때문이다 (龜 의 배는 398..597 이 통째로 걸린다).
    칸의 가장자리로 재면 흔들리지 않는다 — 네모의 한가운데를 사이에 둔 두 칸을
    골라 그 안쪽 변을 기둥의 좌우로 삼는다.
    """
    if not contours:
        return []
    ink = O._turn(max(contours, key=lambda c: len(list(c))))
    mid = (rect[0] + rect[1]) / 2.0
    left = right = None
    for c in contours:
        if O._turn(c) == ink:
            continue
        b = O.box(c)
        if b[3] < rect[2] or b[2] > rect[3]:
            continue                       # 높이가 안 걸치면 남
        if b[1] <= mid and (left is None or b[1] > left):
            left = b[1]
        if b[0] >= mid and (right is None or b[0] < right):
            right = b[0]
    return [(left, right)] if left is not None and right is not None else []


def _walk_pieces(ctx, glyph, cs, rect, spec):
    """**가로 윗변에서 솟은 획들**의 테두리를 훑어 조각을 만든다 — 여럿을 한꺼번에.

    목을 찾지 않는다. 가지려는 조각을 말로 정한 것 — 「가로 윗변에서 솟았다
    되돌아오는 것」 — 을 그대로 걸어간다. 굵어져 끝이 위 가로획에 잘려 테두리가
    끊기면 같은 높이의 짝으로 건너뛰고(잘라내다), 이은 자리는 한 점으로 되돌린다
    (복원하다 · `outline.walk_above` · `to_piece` · `restore_seam`).

    `bar` 는 획이 솟는 가로획, `roof` 는 그 위를 막는 가로획을 가리키는 네모다.
    廉 은 삐침이 둘이라 둘 다 가져와 저마다 제 기둥에 세운다.
    """
    bars = _bars(cs, _rect(ctx, glyph, spec["bar"]), spec.get("share", 0.45))
    roofs = _bars(cs, _rect(ctx, glyph, spec["roof"]), spec.get("share", 0.45))
    if not bars or not roofs:
        return None, "가로획을 못 찾았다"
    ybar = O.snap_y(cs, bars[0][1])                  # 솟는 가로획의 윗변
    # 막는 가로획 = 그 윗변보다 **위에 있는 것 가운데 가장 낮은** 것
    up = [b for b in roofs if b[0] > ybar + 2]
    if not up:
        return None, "막는 가로획을 못 찾았다", None
    roof = O.snap_y(cs, min(up, key=lambda b: b[0])[0])
    runs = O.walk_above(cs, ybar, roof, rect[0], rect[1])
    out, how = [], []
    for run, seam, seam_at in runs:
        c = O.to_piece(run, ybar, spec.get("over", 0.0),
                       quad=glyph.foreground.is_quadratic)
        n0 = len(list(c))
        c, why = O.restore_seam(c, seam_at)
        out.append([c])
        how.append('%d점%s' % (len(list(c)), '' if n0 == len(list(c)) else '·되살림'))
    if not out:
        return None, "훑어 나온 조각이 없다", None
    return out, "윗변에서 훑음 (%s)" % " ".join(how), (ybar, roof)


def _stand_on_columns(ctx, glyph, pieces, spec, band=None):
    """조각들을 저마다 **제 기둥 위에** 세우고 글리프에 담는다.

    세로는 조각의 발이 받는 쪽 가로획의 윗변에 오도록, 가로는 발의 왼끝이 가장
    가까운 기둥의 왼끝에 오도록 옮긴다. 조각마다 따로 맞춘다 — 廉 의 왼쪽 삐침은
    왼기둥에, 오른쪽 삐침은 가운데기둥에 선다.
    """
    cs = list(glyph.foreground)
    bars = _bars(cs, _rect(ctx, glyph, spec["bar"]), spec.get("share", 0.45))
    if not bars:
        print("carvePart: %s 의 가로획을 못 찾았다" % glyph.glyphname)
        return None
    top = bars[0][1]
    em = ctx.em_ascent + ctx.em_descent
    # **띠의 키 비만큼만 세로로 누른다.** 띠는 획이 솟는 가로획의 윗변에서 그 위를
    # 막는 가로획의 밑변까지다. 주는 쪽과 받는 쪽의 띠 키가 굵기마다 달라(廉 은
    # 굵어질수록 짧다), 누르지 않으면 삐침 위의 틈이 굵기마다 달라진다.
    sy = 1.0
    if band:
        roofs = _bars(cs, _rect(ctx, glyph, spec["roof"]), spec.get("share", 0.45)) \
            if "roof" in spec else None
        up = [b for b in (roofs or []) if b[0] > top + 2]
        if up:
            here = O.snap_y(cs, min(up, key=lambda b: b[0])[0]) - top
            there = band[1] - band[0]
            if here > 0 and there > 0:
                sy = here / float(there)
    cols = [c for c in O.columns(cs) if c[1] - c[0] >= 0.02 * em]
    if not cols:
        print("carvePart: %s 에서 기둥을 못 찾았다" % glyph.glyphname)
        return None
    put, notes = [], []
    for part in pieces:
        pb = O.bbox(part)
        foot = [p.x for c in part for p in c if p.y <= pb[2] + 2]
        want = min(foot) if foot else pb[0]
        col = min(cols, key=lambda c: abs(O.snap_x(cs, c[0]) - want))
        dx = O.snap_x(cs, col[0]) - want
        dy = top - pb[2]
        moved = O.dup(part)
        for c in moved:
            c.transform(psMat.compose(
                psMat.translate(0, -pb[2]),
                psMat.compose(psMat.scale(1.0, sy),
                              psMat.translate(dx, pb[2] + dy))))
        # **발의 오른끝도 기둥의 오른끝에 맞춘다.** 조각은 주는 글자의 세로선 폭을
        # 그대로 가져오는데, 簾 의 兼 은 竹 아래 눌린 성분이라 굵기에 따라 廉 의
        # 기둥과 폭이 1~2 다르다. 왼끝만 맞추면 그 차이가 오른 옆선에 턱으로 남는다.
        # 발의 오른 옆선(발 오른끝과 같은 x 의 점들)만 옮기므로 획의 나머지는 그대로다.
        fr = max(foot) + dx if foot else None
        want_r = O.snap_x(cs, col[1] + 1)
        if fr is not None and abs(want_r - fr) > 0.5 and abs(want_r - fr) <= 4:
            n = 0
            for c in moved:
                for p in c:
                    if abs(p.x - fr) < 0.5:
                        p.x = want_r
                        n += 1
            notes.append('오른끝 %+d(%d점)' % (round(want_r - fr), n))
        put.append(moved)
        notes.append('%+d,%+d' % (round(dx), round(dy)))
    if abs(sy - 1.0) > 0.001:
        notes.append('누름 %.3f' % sy)
    relay(glyph, [cs] + put)
    return ' 옮김 ' + ' · '.join(notes)


def _counter_legs(contours):
    """네모의 왼·오른 세로획 — 흰 칸의 가장자리에서 잰다. [(x0, x1), (x0, x1)].

    가장 큰 윤곽을 몸으로 보고, 그 상자 안에 든 윤곽을 흰 칸으로 본다. 세로획은
    몸의 왼끝~맨 왼쪽 칸, 맨 오른쪽 칸~몸의 오른끝이다.
    """
    if not contours:
        return []
    host = max(contours, key=lambda c: (lambda b: (b[1] - b[0]) * (b[3] - b[2]))(O.box(c)))
    hb = O.box(host)
    holes = [O.box(c) for c in contours
             if c is not host and hb[0] <= O.box(c)[0] and O.box(c)[1] <= hb[1]
             and hb[2] <= O.box(c)[2] and O.box(c)[3] <= hb[3]]
    if not holes:
        return []
    left, right = min(h[0] for h in holes), max(h[1] for h in holes)
    return [(hb[0], left), (right, hb[1])]


def _weight_t(ctx):
    """이 굵기가 같은 기울기의 굵기들 가운데 어디쯤인지 (Thin 0 … Bold 1).

    weight 값은 Text 가 끼어 고르지 않아 차례로 센다.
    """
    me = ctx.style
    names = [st["name"] for st in sorted(
        (st for st in ctx.recipe["styles"] if st.get("italic", False) == me.get("italic", False)),
        key=lambda st: st["weight"])]
    return names.index(me["name"]) / float(len(names) - 1) if len(names) > 1 else 0.0


@op("stretchStroke")
def op_stretch_stroke(ctx, font, spec, source_half):
    """세로획을 더 뻗게 한다 — 먹을 한 조각 얹는 식으로.

    획을 새로 그리는 것이 아니다. 이미 선 세로획을 글리프에서 찾아 그 **폭 그대로**
    네모를 이어 붙인다. 그래서 획 두께가 굵기마다 저절로 맞는다.

        {"op": "stretchStroke", "at": [0.55, 0.42, 0.72, 0.60],
         "by": 0.0625, "over": 14, "cps": ["6d69"]}          浩 — 告 의 세로획

        {"op": "stretchStroke", "at": [0.55, -0.02, 1.0, 0.20],
         "toInk": true, "over": 12, "overTo": 12, "cps": ["6a80"]}   檀 — 日 의 두 세로획

    `at` 은 세로획을 찾을 자리다 ([x0, y0, x1, y1] · x 는 글자 폭, y 는 em 대비).
    세로선이 선 칸은 `outline.columns` 로 글리프 전체에서 찾아 가운데가 x 범위에
    드는 것만 고르고, y 범위는 그 칸의 **어느 획**을 말하는지 가린다 — 칸마다
    먹이 어디서 끊기는지 세로로 훑어, y 한복판을 품은 먹 줄기의 끝에서 뻗는다.

    `find` 를 `"row"` 로 적으면 `at` (과 `like`) 네모의 가운데 높이 줄에서 먹 토막을
    세로획으로 본다 — 굵은 굵기에서 칸이 이웃 획과 이어져 넓게 잡힐 때 (芚 Bold).

    `legs` 를 `"between"` 으로 적으면 **흰 칸 둘 사이에 낀 세로획** 으로 본다
    (龜 의 배 한가운데 기둥). `"counters"` 로 적으면 세로선을 래스터로 찾지 않고 **네모의 흰 칸**
    에서 잰다. 日 처럼 흰 칸이 든 성분은 굵은 굵기에서 칸이 낮아져, 먹 줄기의
    길이로는 네모 전체가 한 기둥으로 보인다 (檀 Bold 의 日 은 386..927 이 통째로
    걸린다). 흰 칸은 굵기가 달라져도 그대로 흰 칸이라 이쪽이 흔들리지 않는다.

    얼마나 뻗는지는 둘 중 하나로 적는다.

      `by`     먹 키에 대한 비율. 획 끝에서 그만큼 더 간다 (浩 은 6.25% = 57).
               [Thin, Bold] 두 값으로 적으면 굵기 차례대로 고르게 잇는다
               (凋 은 [0.06, 0.04] — 가는 쪽은 土 와 口 사이가 넓어 더 뻗는다).
      `toInk`  아래(위)에 따로 있는 먹까지. 그 획과 맞붙게 된다 (檀 의 맨 아래 一).
      `like`   다른 세로획을 고르는 네모. 그 획이 이 획의 끝보다 더 내려간 몫에
               `ratio` (기본 1) 를 곱한 만큼 뻗는다 — 芚 은 凵 오른 다리를 왼 다리가
               아래 가로획 밑으로 나온 길이의 2/3 만큼. `stopAtInk` 면 다리 폭 안에서
               아래로 처음 만나는 먹에 닿는 데서 멈춘다 (芚 SemiBold · Bold 의 乚).

    `over` 는 남기고 갈 획 속으로, `overTo` 는 가서 닿는 획 속으로 파고들 몫이다.
    변끼리 딱 맞대면 그 자리에 실낱 같은 흰 줄이 남으므로 반드시 겹쳐야 한다.
    """
    up = spec.get("dir", "down") == "up"
    by = spec.get("by")
    if isinstance(by, list):
        t = _weight_t(ctx)
        by = by[0] + (by[1] - by[0]) * t
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = list(glyph.foreground)
        if not cs:
            continue
        bx0, by0, bx1, by1 = _in_box(ctx, glyph, spec["at"])
        gx0, gx1, gy0, gy1 = O.bbox(cs)
        # `at` 에 걸치는 윤곽만 재고, 그 가운데 x 가 `at` 안에 드는 칸을 고른다.
        # 띠만 잘라 재면 자가 글리프 키라 띠보다 길어져 아무것도 안 걸리고
        # (浩 의 띠는 180, 자는 229), 글리프 전체를 재면 x 가 맞닿은 다른 세로획과
        # 한 칸으로 이어진다 (檀 의 日 과 回 는 380..449 로 붙는다).
        part = [c for c in cs if _overlaps(O.box(c), (bx0, bx1, by0, by1))]
        row_runs = lambda x0_, x1_, y_: [(a, b) for a, b in O.runs(O.part_mask(cs)[1000 - int(round(y_))])
                                          if x0_ <= (a + b) / 2 <= x1_]
        if spec.get("find") == "row":
            cols = row_runs(bx0, bx1, (by0 + by1) / 2)
        elif spec.get("legs") == "between":
            cols = _between_legs(cs, (bx0, bx1, by0, by1))
        elif spec.get("legs") == "counters":
            cols = _counter_legs(part or cs)
        else:
            cols = [(a, b) for a, b in O.columns(part or cs)
                    if bx0 <= (a + b) / 2 <= bx1]
        if not cols:
            continue
        mask = O.part_mask(cs)
        added = []
        for a, b in cols:
            spans = O.ink_spans(mask, a, b + 1, gy0, gy1)   # 위에서 아래로
            a, b = O.snap_x(cs, a), O.snap_x(cs, b)         # 획의 변에 꼭 맞춘다
            if up:
                spans = spans[::-1]
            here = next((s for s in spans if s[0] <= (by0 + by1) / 2 <= s[1]), None)
            if here is None:
                continue
            frm = here[1] if up else here[0]                # 이 획이 끝나는 자리
            if "by" in spec:
                to = frm + by * (gy1 - gy0) * (1 if up else -1)
            elif "like" in spec:
                lx0, ly0, lx1, ly1 = _in_box(ctx, glyph, spec["like"])
                ref = (row_runs(lx0, lx1, (ly0 + ly1) / 2) if spec.get("find") == "row" else
                       [(p, q) for p, q in O.columns(cs) if lx0 <= (p + q) / 2 <= lx1])
                if not ref:
                    print("stretchStroke: %s 에서 `like` 세로획을 못 찾았다" % glyph.glyphname)
                    continue
                rs = O.ink_spans(mask, ref[0][0], ref[0][1] + 1, gy0, gy1)
                rh = next((r for r in rs if r[0] <= (ly0 + ly1) / 2 <= r[1]), None)
                if rh is None:
                    continue
                rend = rh[1] if up else rh[0]
                to = frm + (rend - frm) * spec.get("ratio", 1.0)
                if spec.get("stopAtInk") and not up:
                    # 다리 폭 안에서 아래로 처음 만나는 먹 — 거기 닿으면 멈춘다 (딱 붙게)
                    hit = None
                    for x in range(int(math.ceil(a)) + 1, int(b)):
                        y = int(frm) - 2
                        while y > to and not mask[1000 - y, x]:
                            y -= 1
                        if y > to and (hit is None or y > hit):
                            hit = y
                    if hit is not None:
                        to = hit + 1
            else:
                nxt = spans[spans.index(here) + 1:]
                if not nxt:
                    continue
                to = nxt[0][0] if up else nxt[0][1]         # 가서 닿을 먹
            added.append(O.stretch(cs, a, b, O.snap_y(cs, frm), round(to),
                                   spec.get("over", 12), spec.get("overTo", 0)))
        if not added:
            continue
        relay(glyph, [cs, added])
        done.append("%s×%d" % (glyph.glyphname, len(added)))
    if done:
        print("stretchStroke: %s" % ", ".join(done))


def _bar_rows(mask, box):
    """네모의 왼끝과 오른끝을 **둘 다 덮는** 먹 줄이 지나는 줄들 — [(y, 왼끝, 오른끝)].

    가로획은 두 끝을 잇고, 세로획이나 흰 칸만 지나는 줄은 한쪽만 덮는다.
    """
    x0, y0, x1, y1 = box

    def row(y):
        return next(((y, a, b) for a, b in O.runs(mask[1000 - y]) if a <= x0 and x1 <= b), None)
    out = [r for r in (row(y) for y in range(int(math.ceil(y0)), int(y1) + 1)) if r]
    if not out:
        return out
    # 네모는 가로획을 고르는 자리일 뿐 — 두께는 네모 밖으로 이어지는 데까지 잰다.
    # 양 끝이 크게 달라지면 맞붙은 다른 획이다 (轄 의 丰 첫 가로획 위에 붙은 宀).
    def same(r, ref):
        return r and abs(r[1] - ref[1]) <= 3 and abs(r[2] - ref[2]) <= 3
    y = out[0][0] - 1
    while same(row(y), out[0]):
        out.insert(0, row(y))
        y -= 1
    y = out[-1][0] + 1
    while same(row(y), out[-1]):
        out.append(row(y))
        y += 1
    return out


@op("extendBar")
def op_extend_bar(ctx, font, spec, source_half):
    """가로획을 오른쪽으로 더 뻗게 한다 — 그 두께 그대로 먹을 한 조각 얹는다.

        {"op": "extendBar", "at": [0.70, 0.20, 0.82, 0.34],
         "to": [0.70, 0.42, 0.82, 0.55], "cps": ["8e60"]}     蹠 — 廿 의 아래 가로획

    `at`  늘일 가로획을 찾을 네모. 네모의 왼끝·오른끝을 둘 다 덮는 먹 줄을
          가로획으로 본다 — 왼끝은 흰 칸 안에, 오른끝은 가로획이 닿는 세로획 안에
          둔다. 그 줄들의 위아래가 획의 두께, 오른끝이 늘이기 시작할 자리다.
    `to`  가서 닿을 끝 — 같은 식으로 찾은 다른 가로획의 오른끝 (蹠 은 廿 의
          가운데 긴 가로획). 대신 `by` (글자 폭 대비) 로 늘일 몫을 바로 줄 수 있다.
    `over` 남기고 갈 획 속으로 파고들 몫 (기본 12) — 맞대면 실낱이 남는다.
    `side` `"left"` 면 왼끝을 왼쪽으로 늘인다.
    `toInk` 그쪽으로 처음 만나는 먹(같은 줄들)까지 가서 `overTo` (기본 12) 만큼
          파고든다 — 蹠 의 아래 가로획을 广 의 삐침에 붙인다.
    `stopAtInk` `to` 와 함께 — 가는 길에 다른 획이 있으면 닿기 바로 앞에서 멈춘다
          (憊 의 艹 가로획을 아래 긴 가로획 끝까지 늘이되 亻 삐침은 건드리지 않게).
    `nearest` `toInk` 와 함께 — 줄마다 만나는 먹 가운데 가장 가까운 것에서 멈춘다.
          `overTo` 를 음수로 주면 그만큼 띄운다 (廐 의 旡 두 가로획을 皀 앞 26 까지).

    `by` 가 음수면 **줄인다** — 끝의 점들을 그만큼 안으로 당긴다 (먹을 얹지 않는다).
    """
    left = spec.get("side", "right") == "left"
    sign = -1 if left else 1
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = list(glyph.foreground)
        if not cs:
            continue
        mask = O.part_mask(cs)
        rows = _bar_rows(mask, _in_box(ctx, glyph, spec["at"]))
        if not rows:
            print("extendBar: %s 에서 가로획을 못 찾았다" % glyph.glyphname)
            continue
        lo = O.snap_y(cs, min(r[0] for r in rows) - 0.5)
        hi = O.snap_y(cs, max(r[0] for r in rows) + 0.5)
        frm = O.snap_x(cs, min(r[1] for r in rows) if left else max(r[2] for r in rows))
        if spec.get("toInk"):
            ends = []
            for y, a, b in rows:
                nxt = [r for r in O.runs(mask[1000 - y]) if (r[1] < a if left else r[0] > b)]
                if nxt:
                    ends.append(max(r[1] for r in nxt) if left else min(r[0] for r in nxt))
            if not ends:
                print("extendBar: %s 에서 닿을 먹을 못 찾았다" % glyph.glyphname)
                continue
            # 비스듬한 획이면 줄마다 끝이 달라진다 — 가장 먼 끝까지 가야 다 닿는다.
            # `nearest` 면 가장 가까운 먹에서 멈춘다 — 廐 의 旡 윗 가로획은 위쪽 줄이
            # 皀 보다 높아 그 줄들의 먹은 저 멀리 广 이다.
            far = (max(ends) if left else min(ends)) if spec.get("nearest") else \
                  (min(ends) if left else max(ends))
            to = far + sign * spec.get("overTo", 12)
        elif "to" in spec:
            ref = _bar_rows(mask, _in_box(ctx, glyph, spec["to"]))
            if not ref:
                print("extendBar: %s 에서 닿을 가로획을 못 찾았다" % glyph.glyphname)
                continue
            to = O.snap_x(cs, min(r[1] for r in ref) if left else max(r[2] for r in ref))
            if spec.get("stopAtInk"):
                # 가는 길에 다른 획이 있으면 줄마다 그 변을 재어 가장 가까운 것 바로 앞에서 멈춘다
                # 가로획 두께 전체(lo..hi, 위아래 한 줄씩 더) — 기운 획은 모서리 줄에서 가장 가깝다
                for y in range(int(math.floor(lo)) - 1, int(math.ceil(hi)) + 2):
                    for r in O.runs(mask[1000 - y]):
                        if left and r[1] < frm and r[1] + 2 >= to:
                            to = r[1] + 2
                        elif not left and r[0] > frm and r[0] - 2 <= to:
                            to = r[0] - 2
        else:
            to = frm + sign * spec["by"] * glyph.width
        if (to - frm) * sign < 0:
            # 줄이기 — 그 끝(x == frm, lo..hi)에 선 점을 to 로 당긴다
            tol = 0.5
            k = 0
            for c in cs:
                for pt in c:
                    if abs(pt.x - frm) < 0.5 and lo - tol <= pt.y <= hi + tol:
                        pt.x = to
                        k += 1
            relay(glyph, [cs], merge=False)
            done.append("%s %d→%d (y %d..%d, 점 %d)" % (glyph.glyphname, frm, to, lo, hi, k))
            continue
        a = frm - sign * spec.get("over", 12)
        x0, x1 = min(a, to), max(a, to)
        piece = fontforge.contour()
        piece.is_quadratic = cs[0].is_quadratic
        for px, py in ((x0, hi), (x1, hi), (x1, lo), (x0, lo)):      # 시계방향 = 칠함
            piece += fontforge.point(px, py, True)
        piece.closed = True
        relay(glyph, [cs, [piece]])
        done.append("%s %d→%d (y %d..%d)" % (glyph.glyphname, frm, to, lo, hi))
    if done:
        print("extendBar: %s" % ", ".join(done))


@op("barLength")
def op_bar_length(ctx, font, spec, source_half):
    """가로획 길이를 다른 가로획의 몇 배로 — 양 끝을 같은 만큼 당긴다 (가운데는 그대로).

        {"op": "barLength", "at": [0.6, 0.42, 0.8, 0.47],
         "like": [0.6, 0.555, 0.8, 0.575], "ratio": 0.917, "cps": ["8f44"]}
                                    轄 — 害 의 가운데 가로획을 첫 가로획의 33/36 로

    `at`, `like`  고칠 가로획과 견줄 가로획을 찾을 네모 (`_bar_rows` — 네모의 왼끝·오른끝을
                  둘 다 덮는 먹 줄). 길이는 그 줄들의 가장 왼끝 ~ 가장 오른끝.
    `ratio`       새 길이 = `like` 길이 × ratio. 줄이기만 한다.
    `likeInk`     `like` 네모 안에 온전히 드는 먹의 왼끝 ~ 오른끝을 길이로 — 휘어 올라가는
                  획처럼 한 줄이 두 끝을 다 덮지 않는 획 (呈 檉 壬 의 첫 획).

    끝에 선 점(그 x, 가로획 두께 안)을 안으로 옮기므로 끝은 곧은 모서리 그대로다.
    """
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = list(glyph.foreground)
        mask = O.part_mask(cs)
        rows = _bar_rows(mask, _in_box(ctx, glyph, spec["at"]))
        if spec.get("likeInk"):
            lx0, ly0, lx1, ly1 = _in_box(ctx, glyph, spec["like"])
            ref = [(y, r[0], r[1]) for y in range(int(math.ceil(ly0)), int(ly1) + 1)
                   for r in O.runs(mask[1000 - y]) if lx0 <= r[0] and r[1] <= lx1]
        else:
            ref = _bar_rows(mask, _in_box(ctx, glyph, spec["like"]))
        if not rows or not ref:
            print("barLength: %s 에서 가로획을 못 찾았다" % glyph.glyphname)
            continue
        lo = O.snap_y(cs, min(r[0] for r in rows) - 0.5)
        hi = O.snap_y(cs, max(r[0] for r in rows) + 0.5)
        a = O.snap_x(cs, min(r[1] for r in rows))
        b = O.snap_x(cs, max(r[2] for r in rows))
        ra, rb = min(r[1] for r in ref), max(r[2] for r in ref)
        want = (rb - ra) * spec["ratio"]
        d = ((b - a) - want) / 2.0
        if d <= 0.5:
            continue
        k = 0
        for c in cs:
            for p in c:
                if lo - 0.5 <= p.y <= hi + 0.5:
                    if abs(p.x - a) < 0.5:
                        p.x = a + d
                        k += 1
                    elif abs(p.x - b) < 0.5:
                        p.x = b - d
                        k += 1
        relay(glyph, [cs], merge=False)
        done.append("%s %d→%d (견줄 %d, 점 %d)" % (glyph.glyphname, round(b - a), round(want), round(rb - ra), k))
    if done:
        print("barLength: %s" % ", ".join(done))


@op("evenBar")
def op_even_bar(ctx, font, spec, source_half):
    """세로획 둘을 가로지르는 가로획의 왼쪽 나온 길이를 오른쪽과 같게 — 왼끝을 잘라 낸다.

        {"op": "evenBar", "at": [0.70, 0.42, 0.82, 0.55], "cps": ["8e60"]}
                                                    蹠 — 廿 의 첫 가로획

    蹠 의 廿 첫 가로획은 왼끝이 广 의 삐침에 녹아 붙어 있다. 한국 자형은 왼쪽도
    오른쪽만큼만 나오고 广 에서 떨어진다.

    `at` 은 가로획을 찾을 네모 (`_bar_rows` — 왼끝은 흰 칸, 오른끝은 오른 세로획 안).
    가로획 바로 위아래 줄에 함께 걸친 먹이 가로획을 꿰는 세로획이고, 왼끝이 붙은
    획(삐침)은 그 가운데 가로획의 왼끝 자리에 선 것이다. 오른쪽 나온 길이는 가로획
    오른끝 − 오른 세로획 오른변. 왼쪽은 왼 세로획 왼변에서 그만큼만 남기고 그
    왼쪽을 떼어 낸다 — 점을 오리지 않고 윤곽의 이음만 바꾸므로 다른 점은 그대로다.
    """
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = list(glyph.foreground)
        if not cs:
            continue
        mask = O.part_mask(cs)
        rows = _bar_rows(mask, _in_box(ctx, glyph, spec["at"]))
        if not rows:
            print("evenBar: %s 에서 가로획을 못 찾았다" % glyph.glyphname)
            continue
        lo = O.snap_y(cs, min(r[0] for r in rows) - 0.5)
        hi = O.snap_y(cs, max(r[0] for r in rows) + 0.5)
        right_end = O.snap_x(cs, max(r[2] for r in rows))
        on = [p for c in cs for p in c if p.on_curve]
        # 붙은 획의 오른변 — 가로획 아랫변·윗변에 선 점 가운데 가장 왼쪽
        xb = min(p.x for p in on if abs(p.y - lo) < 0.5)
        xt = min(p.x for p in on if abs(p.y - hi) < 0.5)
        below = O.runs(mask[1000 - int(lo - 3)])
        above = O.runs(mask[1000 - int(hi + 3)])
        cols = [(max(a, c), min(b, d)) for a, b in below for c, d in above
                if a < d and c < b and min(b, d) > max(xb, xt) + 1]
        if len(cols) < 2:
            print("evenBar: %s 에서 세로획 둘을 못 찾았다" % glyph.glyphname)
            continue
        lv = O.snap_x(cs, min(c[0] for c in cols))
        rv = O.snap_x(cs, max(c[1] for c in cols))
        new_left = lv - (right_end - rv)
        if new_left <= max(xb, xt) + 1:
            continue
        # 가로획이 붙은 획에서 떠나는 두 모서리 — 윗변 P_t(다음 점 R 이 윗변을 따라
        # 오른쪽), 아랫변 P_b(앞 점 S 가 아랫변을 따라 오른쪽). 두 점을 빼고 그 자리에
        # 새 왼끝 모서리 둘을 넣어 잇는다. 붙은 획의 변은 앞뒤 점이 곧장 이어져 본디
        # 변으로 돌아간다. 아래가 흰 칸으로 막혀 있었으면 (두 모서리가 다른 윤곽)
        # 그 칸이 바깥과 이어져 두 윤곽이 하나가 되고, 같은 윤곽이면 둘로 갈린다.
        def corner(y, x, after):
            for ci, c in enumerate(cs):
                pts = list(c)
                n = len(pts)
                for i, p in enumerate(pts):
                    q = pts[(i + 1) % n] if after else pts[i - 1]
                    if (p.on_curve and q.on_curve and abs(p.y - y) < 0.5 and abs(p.x - x) < 0.5
                            and abs(q.y - y) < 0.5 and q.x > p.x + 1):
                        return ci, i
            return None
        top, bot = corner(hi, xt, True), corner(lo, xb, False)
        if top is None or bot is None:
            print("evenBar: %s 에서 가로획 왼끝 모서리를 못 찾았다" % glyph.glyphname)
            continue

        def pt(x, y):
            return fontforge.point(x, y, True)
        nb, nt = pt(new_left, lo), pt(new_left, hi)
        (cx, it), (cy, ib) = top, bot
        X, Y = list(cs[cx]), list(cs[cy])

        def contour(pts):
            o = fontforge.contour()
            o.is_quadratic = cs[0].is_quadratic
            for p in pts:
                o += fontforge.point(p.x, p.y, p.on_curve)
            o.closed = True
            return o
        if cx != cy:
            # X: … A, P_t, R …   Y: … S, P_b, T …   →   … A, T … S, 새 아래, 새 위, R …
            ys = Y[ib + 1:] + Y[:ib]                        # T … S
            joined = X[:it] + ys + [nb, nt] + X[it + 1:]
            rest = [c for k, c in enumerate(cs) if k not in (cx, cy)]
            made = [contour(joined)]
        else:
            n = len(X)
            arc1 = [X[(it + 1 + k) % n] for k in range((ib - it - 1) % n)]   # R … S
            arc2 = [X[(ib + 1 + k) % n] for k in range((it - ib - 1) % n)]   # T … A
            rest = [c for k, c in enumerate(cs) if k != cx]
            made = [contour(arc2), contour([nt] + arc1 + [nb])]
        made, _ = O.tidy(made)                  # 손댄 윤곽만 — 남의 점은 그대로 둔다
        relay(glyph, [rest, made], merge=False)
        done.append("%s 왼 %d→%d (오른 나옴 %d)" % (glyph.glyphname, round(xb), round(new_left), round(right_end - rv)))
    if done:
        print("evenBar: %s" % ", ".join(done))


def _col_runs(mask, x, base=1000):
    """세로 한 줄의 먹 구간 — [(y_lo, y_hi)]."""
    col = mask[:, int(round(x))]
    out, y = [], None
    for i, v in enumerate(col):
        if v and y is None:
            y = i
        elif not v and y is not None:
            out.append((base - (i - 1), base - y))
            y = None
    if y is not None:
        out.append((base - (len(col) - 1), base - y))
    return out


def _white_around(runs, v, lo, hi):
    """먹 구간들 사이에서 v 를 품은 흰 구간 (lo..hi 안)."""
    a, b = lo, hi
    for s, e in runs:
        if e < v:
            a = max(a, e)
        elif s > v:
            b = min(b, s)
    return a, b


@op("openBridge")
def op_open_bridge(ctx, font, spec, source_half):
    """두 획 사이에 걸친 획 한 토막을 빼 흰 칸을 연다 — 점은 오리지 않고 윤곽만 잇는다.

        {"op": "openBridge", "dir": "h", "at": [0.42, 0.46, 0.58, 0.52], "cps": ["8805"]}
                                    蠅 — 黽 왼쪽 둘째 칸의 윗가로 토막 (위로 연다)
        {"op": "openBridge", "dir": "v", "at": [0.62, 0.58, 0.70, 0.72], "cps": ["51de"]}
                                    凞 — 巳 의 왼쪽 세로 토막 (왼쪽으로 연다)

    `dir`  `"h"` 면 세로획 둘 사이의 가로 토막, `"v"` 면 가로획 둘 사이의 세로 토막.
    `at`   토막을 찾을 네모. 가운데가 토막 위에 오게 둔다. 토막의 두께는 네모
           가운데를 지나는 먹으로, 길이는 토막 양옆(위아래)의 흰 자리가 함께 열린
           폭으로 잰다 — 굵기마다 저절로 맞는다.

    토막의 두 변 위에 모서리 점이 없으면 (변이 곧게 지나가면) 그 자리에 점을 넣고,
    두 변을 잇던 윤곽을 서로 이어 붙인다. 두 변이 다른 윤곽이면 (흰 칸과 바깥)
    하나가 되고, 같은 윤곽이면 둘로 갈린다. 마치고 한 줄 위의 남는 점은 지운다.
    """
    horiz = spec.get("dir", "h") == "h"
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = list(glyph.foreground)
        if not cs:
            continue
        mask = O.part_mask(cs)
        x0, y0, x1, y1 = _in_box(ctx, glyph, spec["at"])
        xc, yc = (x0 + x1) / 2.0, (y0 + y1) / 2.0

        def near(v, horiz_axis):
            # 토막의 변은 토막 가운데를 곧게 지나는 선분이다 — 그 선분의 좌표를 쓴다.
            # 가까운 점으로 맞추면 이웃 획의 점에 붙거나 (夔 Bold), 변의 점이 멀리
            # 있어 못 맞춘다 (凞 Regular).
            ws = []
            for c in cs:
                pts = [q for q in c if q.on_curve]
                for i, p in enumerate(pts):
                    q = pts[(i + 1) % len(pts)]
                    if horiz_axis and abs(p.y - q.y) < 0.5 and min(p.x, q.x) <= xc <= max(p.x, q.x):
                        ws.append(p.y)
                    if not horiz_axis and abs(p.x - q.x) < 0.5 and min(p.y, q.y) <= yc <= max(p.y, q.y):
                        ws.append(p.x)
            ws = [w for w in ws if abs(w - v) <= 4]
            return min(ws, key=lambda w: abs(w - v)) if ws else round(v)
        if horiz:
            run = next((r for r in _col_runs(mask, xc) if r[0] <= yc <= r[1]), None)
            if run is None:
                print("openBridge: %s 에서 토막을 못 찾았다" % glyph.glyphname)
                continue
            lo, hi = near(run[0] - 0.5, True), near(run[1] + 0.5, True)
            ra = _white_around(O.runs(mask[1000 - int(hi + 3)]), xc, -1e9, 1e9)
            rb = _white_around(O.runs(mask[1000 - int(lo - 3)]), xc, -1e9, 1e9)
            sides = (("y", hi), ("y", lo))
            ea, eb = max(ra[0], rb[0]), min(ra[1], rb[1])
        else:
            run = next((r for r in O.runs(mask[1000 - int(yc)]) if r[0] <= xc <= r[1]), None)
            if run is None:
                print("openBridge: %s 에서 토막을 못 찾았다" % glyph.glyphname)
                continue
            lo, hi = near(run[0] - 0.5, False), near(run[1] + 0.5, False)
            ra = _white_around(_col_runs(mask, lo - 3), yc, -1e9, 1e9)
            rb = _white_around(_col_runs(mask, hi + 3), yc, -1e9, 1e9)
            sides = (("x", lo), ("x", hi))
            ea, eb = max(ra[0], rb[0]), min(ra[1], rb[1])
        # 끝은 토막의 두 변 위에 선 점에 맞춘다 — 이웃 획의 점에 붙으면 어긋난다
        axis0 = sides[0][0]
        on_sides = [(p.x if axis0 == "y" else p.y) for c in cs for p in c if p.on_curve
                    and any(abs((p.y if a == "y" else p.x) - v) < 0.5 for a, v in sides)]

        def snap(e):
            near = [w for w in on_sides if abs(w - e) <= 4]
            return min(near, key=lambda w: abs(w - e)) if near else round(e)
        ea, eb = snap(ea), snap(eb)

        def key(p, axis, v):
            return abs((p.y if axis == "y" else p.x) - v) < 0.5

        def along(p, axis):
            return p.x if axis == "y" else p.y

        def at(axis, v, e):
            return fontforge.point(e, v, True) if axis == "y" else fontforge.point(v, e, True)
        # 변이 곧게 지나가는 자리에 모서리 점을 넣는다
        lists = []
        for c in cs:
            pts = list(c)
            out = []
            n = len(pts)
            for i, p in enumerate(pts):
                out.append(p)
                q = pts[(i + 1) % n]
                for axis, v in sides:
                    if p.on_curve and q.on_curve and key(p, axis, v) and key(q, axis, v):
                        a, b = along(p, axis), along(q, axis)
                        for e in sorted((ea, eb), reverse=a > b):
                            if min(a, b) + 0.5 < e < max(a, b) - 0.5:
                                out.append(at(axis, v, e))
            lists.append(out)

        def pair(axis, v):
            for ci, pts in enumerate(lists):
                n = len(pts)
                for i, p in enumerate(pts):
                    q = pts[(i + 1) % n]
                    if (p.on_curve and q.on_curve and key(p, axis, v) and key(q, axis, v)
                            and {round(along(p, axis)), round(along(q, axis))} == {round(ea), round(eb)}):
                        return ci, i, (i + 1) % n, round(along(p, axis))
            return None
        P, Q = pair(*sides[0]), pair(*sides[1])
        if P is None or Q is None:
            print("openBridge: %s 에서 토막의 모서리를 못 찾았다" % glyph.glyphname)
            continue
        if P[3] == Q[3]:                     # P 의 첫 점은 Q 의 둘째 점과 끝을 같이 한다
            P, Q = Q, P
        (cp_, p1, p2, _), (cq, qa, qb, _) = P, Q

        def contour(pts):
            o = fontforge.contour()
            o.is_quadratic = cs[0].is_quadratic
            for p in pts:
                o += fontforge.point(p.x, p.y, p.on_curve)
            o.closed = True
            return o
        U = lists[cp_]
        if cp_ != cq:
            C = lists[cq]
            joined = U[:p1 + 1] + C[qb + 1:] + C[:qa] + U[p2:]
            made = [contour(joined)]
            rest = [contour(l) if k != cp_ else None for k, l in enumerate(lists) if k not in (cp_, cq)]
        else:
            n = len(U)
            l1 = [U[(qb + 1 + k) % n] for k in range((p1 - qb) % n)]        # Qb 다음 … P1
            l2 = [U[(p2 + k) % n] for k in range((qa - p2) % n)]            # P2 … Qa 앞
            made = [contour(l1), contour(l2)]
            rest = [contour(l) for k, l in enumerate(lists) if k != cp_]
        made, _ = O.tidy(made)
        relay(glyph, [[r for r in rest if r is not None], made], merge=False)
        done.append("%s %s %d..%d × %d..%d" % (glyph.glyphname, "가로" if horiz else "세로",
                                                round(ea), round(eb), round(lo), round(hi)))
    if done:
        print("openBridge: %s" % ", ".join(done))


@op("flipInner")
def op_flip_inner(ctx, font, spec, source_half):
    """네모 안의 흰 칸들을 좌우로 뒤집는다 — 안쪽 획이 반대편으로 간다.

        {"op": "flipInner", "at": [0.2, 0.33, 0.8, 0.6],
         "column": [0.4, 0.66, 0.52, 0.8], "cps": ["5368"]}     卨 — 위 口 안 작은 네모

    卨 의 위 口 안 작은 네모가 Plex 에서는 왼쪽에 있고, 한국 자형은 오른쪽에 있으며
    그 왼변이 위 卜 의 세로획과 한 줄로 선다.

    `at`      흰 칸들을 고를 네모 — 상자가 온전히 드는 윤곽(흰 칸)만 뒤집는다. 축은
              흰 칸들의 왼끝·오른끝 한가운데 (= 둘레 획의 안쪽 가운데) 다.
    `column`  있으면 뒤집은 뒤 안쪽 세로획의 두 변을 이 네모에서 찾은 세로획의 두
              변에 맞춘다 (안쪽 x 값이 꼭 둘일 때만).
    """
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = list(glyph.foreground)
        x0, x1, y0, y1 = _rect(ctx, glyph, spec["at"])
        holes = [i for i, c in enumerate(cs) if _inside(O.box(c), (x0, x1, y0, y1))]
        if not holes:
            print("flipInner: %s 에서 흰 칸을 못 찾았다" % glyph.glyphname)
            continue
        xs = [p.x for i in holes for p in cs[i]]
        L, R = min(xs), max(xs)
        for i in holes:
            c = cs[i]
            for p in c:
                p.x = L + R - p.x
            c.reverseDirection()                                     # 거울은 감김을 뒤집는다
        note = ""
        if "column" in spec:
            cx0, cy0, cx1, cy1 = _in_box(ctx, glyph, spec["column"])
            m = O.part_mask([c for k, c in enumerate(cs) if k not in holes])
            cols = [(a, b) for a, b in O.runs(m[1000 - int((cy0 + cy1) / 2)])
                    if cx0 <= (a + b) / 2 <= cx1]
            inner = sorted({round(p.x) for i in holes for p in cs[i] if p.on_curve} - {round(L), round(R)})
            if len(cols) == 1 and len(inner) == 2:
                ca, cb = O.snap_x(cs, cols[0][0]), O.snap_x(cs, cols[0][1])
                for i in holes:
                    for p in cs[i]:
                        if abs(p.x - inner[0]) < 0.5:
                            p.x = ca
                        elif abs(p.x - inner[1]) < 0.5:
                            p.x = cb
                note = " 세로획 %d..%d → %d..%d" % (inner[0], inner[1], ca, cb)
            else:
                print("flipInner: %s 맞출 세로획을 못 정했다 (기둥 %d, 안쪽 x %s)"
                      % (glyph.glyphname, len(cols), inner))
        relay(glyph, [cs], merge=False)
        done.append("%s 축 %d%s" % (glyph.glyphname, round((L + R) / 2), note))
    if done:
        print("flipInner: %s" % ", ".join(done))


@op("detachStem")
def op_detach_stem(ctx, font, spec, source_half):
    """가로획에 매달린 짧은 세로획을 떼어 그 사이에 틈을 둔다.

        {"op": "detachStem", "at": [0.45, 0.58, 0.95, 0.70],
         "like": "uni9E97.jp83", "likeAt": [0.2, 0.55, 0.35, 0.70], "cps": ["9a6a"]}
                                    驪 — 丽 두 冂 의 가운데 세로획 (麗.jp83 처럼)

    `at`      뗄 세로획들이 든 네모. 네모 가운데 높이에서 네모 안에 온전히 드는 먹
              토막이 세로획이고, 그 위끝(양옆 흰 칸의 위끝 = 가로획 아랫변)에서 뗀다.
    `like`    틈의 크기를 잴 글리프 (같은 굵기). `likeAt` 안에 홀로 선 세로획의
              위끝과 그 위 먹 사이가 틈이다. Plex 가 손수 뗀 자형을 따른다.
    `gap`     `like` 대신 틈을 단위로 바로 준다.

    `end`     `"bottom"` 이면 가로획 **위에 선** 세로획의 아래끝을 뗀다 (嶼 — 與 의
              가운데 세로획). 기본은 위끝.
    `corner`  두 가로획 사이 세로획 (네모의 한 변) 을 아래 가로획에서 뗀다 — 값은 안쪽
              흰 칸이 있는 쪽 (`"right"`, 凞 의 巳 위 네모 왼쪽 세로획). 위 가로획에
              매달린 꼬다리만 남고 아래끝은 아래 가로획 윗변에서 `gap` 떨어진다.
              `slant` (亏 의 사선 기울기, 0.24) 를 주면 꼬다리가 아래로 갈수록 바깥쪽으로
              기운다 (위끝은 그대로).

    세로획 두 변 사이, 가로획 아랫변에서 틈만큼 아래까지를 도려낸다 — 네모는 먹
    안에만 든다.
    """
    done = []
    sg = -1 if spec.get("end") == "bottom" else 1               # 가로획이 있는 쪽
    gap = spec.get("gap")
    if gap is None:
        donor = font[spec["like"]]
        dcs = list(donor.foreground)
        lx0, ly0, lx1, ly1 = _in_box(ctx, donor, spec["likeAt"])
        stems = [O.box(c) for c in dcs
                 if lx0 <= O.box(c)[0] and O.box(c)[1] <= lx1 and ly0 <= O.box(c)[2] and O.box(c)[3] <= ly1]
        if not stems:
            print("detachStem: %s 에서 홀로 선 세로획을 못 찾았다" % spec["like"])
            return
        sx0, sx1, sy0, sy1 = stems[0]
        above = [p.y for c in dcs if c is not None for p in c if p.on_curve and p.y > sy1 + 0.5
                 and any(O.box(c)[0] <= x <= O.box(c)[1] for x in (sx0, sx1)) and sx0 - 200 <= p.x <= sx1 + 200]
        gap = min(above) - sy1
    for glyph in selected_glyphs(font, spec):
        cs = list(glyph.foreground)
        if not cs:
            continue
        x0, y0, x1, y1 = _in_box(ctx, glyph, spec["at"])
        mask = O.part_mask(cs)
        ym = int(round((y0 + y1) / 2))
        stems = [(a, b) for a, b in O.runs(mask[1000 - ym]) if x0 <= a and b <= x1]
        cut = []
        def white_top(x):
            y = ym
            while 0 < y + sg < 1000 and not mask[1000 - (y + sg), x]:
                y += sg
            return y
        if spec.get("corner"):
            # 가로획 끝과 ㄱ 자로 만나는 모서리 (凞 의 巳 위 네모 왼쪽) — 한쪽만 안쪽 흰
            # 칸이다. 안쪽 흰 칸으로 가로획 아랫변을 찾고, 그 아래 틈만큼 세로획을
            # 잘라 낸다 (남길 것을 덮어 — keepOnly 와 같이). 가로획은 모서리까지 남는다.
            inner = spec["corner"]                  # 안쪽 흰 칸이 있는 쪽: "right" | "left"
            W = (glyph.width or 1000) + 100

            def carve(cs_, a_, b_, lo_, hi_):
                # 네모 (a_..b_, lo_..hi_) 와 겹치는 윤곽만 자른다 — 다른 획 (凞 의 冫 점)
                # 까지 잘랐다 붙이면 겹침 계산이 깨진다
                hit = [c for c in cs_ if O.box(c)[0] < b_ and O.box(c)[1] > a_
                       and O.box(c)[2] < hi_ and O.box(c)[3] > lo_]
                keep_ = [c for c in cs_ if c not in hit]
                return keep_ + clip_to(hit, [(-100, W, -400, lo_), (-100, W, hi_, 1400),
                                             (-100, a_, lo_, hi_), (b_, W, lo_, hi_)])
            for a, b in stems:
                xi = b + 3 if inner == "right" else a - 3
                # 안쪽 흰 칸을 위로 → 위 가로획 아랫변, 아래로 → 아래 가로획 윗변
                y = ym
                while y < 999 and not mask[1000 - (y + 1), int(xi)]:
                    y += 1
                bb = O.snap_y(cs, y + 0.5)
                y = ym
                while y > 1 and not mask[1000 - (y - 1), int(xi)]:
                    y -= 1
                mt = O.snap_y(cs, y - 0.5)
                a, b = O.snap_x(cs, a), O.snap_x(cs, b)
                # 위 네모의 왼 세로획을 통째로 떼어 내고, 위 가로획에 매달린 꼬다리를
                # 다시 그린다 — 아래끝은 아래 가로획에서 `gap` 떨어지고, 亏 처럼 아래로
                # 갈수록 바깥쪽으로 `slant` 만큼 기운다.
                cs = carve(cs, a, b, mt, bb)
                k = spec.get("slant", 0)
                d = -k if inner == "right" else k
                y0, y1 = mt + gap, bb + 12
                c = fontforge.contour()
                c.is_quadratic = cs[0].is_quadratic
                for px, py in ((a, y1), (b, y1), (b, y0), (a, y0)):
                    c += fontforge.point(px + d * (bb - min(py, bb)), py, True)
                c.closed = True
                if not c.isClockwise():
                    c.reverseDirection()
                cs = cs + [c]
                cut.append("%d..%d 꼬다리 y%d..%d 기울기 %.2f" % (a, b, y0, bb, k))
            if cut:
                relay(glyph, [cs])
                done.append("%s %s" % (glyph.glyphname, ", ".join(cut)))
            continue
        for a, b in stems:
            # 양옆 흰 칸을 위로 따라가 처음 먹을 만나는 자리 = 가로획 아랫변. 두 쪽이
            # 같은 가로획에 닿아야 매달린 세로획이다 — 冂 의 다리는 한쪽이 바깥이다.
            if mask[1000 - ym, a - 3] or mask[1000 - ym, b + 3]:
                continue
            yl, yr = white_top(a - 3), white_top(b + 3)
            if abs(yl - yr) > 2:
                continue
            top = O.snap_y(cs, yl + 0.5 * sg)
            a, b = O.snap_x(cs, a), O.snap_x(cs, b)
            # 가로획 아랫변 위의 두 모서리 (a, top) (b, top) 사이 호가 세로획이다.
            # 그 호를 떼어 따로 닫고 두 끝을 틈만큼 내린다. 남은 윤곽은 두 모서리를
            # 빼면 아랫변이 곧게 이어진다.
            hit = None
            for ci, c in enumerate(cs):
                pts = list(c)
                ia = [i for i, q in enumerate(pts) if q.on_curve and abs(q.x - a) < 0.5 and abs(q.y - top) < 0.5]
                ib = [i for i, q in enumerate(pts) if q.on_curve and abs(q.x - b) < 0.5 and abs(q.y - top) < 0.5]
                if ia and ib:
                    hit = (ci, pts, ia[0], ib[0])
                    break
            if hit is None:
                print("detachStem: %s %d..%d 의 모서리를 못 찾았다" % (glyph.glyphname, a, b))
                continue
            ci, pts, ia, ib = hit
            n = len(pts)
            # 세로획 쪽 호 — 두 모서리 사이에서 아래(top 보다 낮은 점)로 내려가는 쪽
            f1 = [(ia + k) % n for k in range((ib - ia) % n + 1)]
            f2 = [(ib + k) % n for k in range((ia - ib) % n + 1)]
            arc = f1 if all((pts[k].y - top) * sg <= 0.5 and a - 0.5 <= pts[k].x <= b + 0.5 for k in f1) else f2
            rest = [k for k in range(n) if k not in arc[1:-1] and k not in (arc[0], arc[-1])]
            stem = fontforge.contour()
            stem.is_quadratic = cs[ci].is_quadratic
            for k in arc:
                q = pts[k]
                y = top - sg * gap if k in (arc[0], arc[-1]) else q.y
                stem += fontforge.point(q.x, y, q.on_curve)
            stem.closed = True
            body = fontforge.contour()
            body.is_quadratic = cs[ci].is_quadratic
            for k in rest:
                body += fontforge.point(pts[k].x, pts[k].y, pts[k].on_curve)
            body.closed = True
            cs[ci] = body
            cs.append(stem)
            cut.append(stem)
            done.append("%s %d..%d 위끝 %d 틈 %d" % (glyph.glyphname, a, b, top, gap))
        if not cut:
            continue
        kept, _ = O.tidy(cs)
        relay(glyph, [kept], merge=False)
    for d in done:
        print("detachStem:", d)


@op("detachBar")
def op_detach_bar(ctx, font, spec, source_half):
    """두 세로획 사이에 걸친 가로획의 한끝을 세로획에서 떼어 틈을 둔다.

        {"op": "detachBar", "at": [0.20, 0.17, 0.40, 0.19], "gap": 26, "cps": ["9175"]}
                                    酵 — 酉 안쪽 一 을 오른쪽 세로획에서 (KS)

    `at`    뗄 가로획을 고르는 네모. 왼끝은 가로획 위 흰 칸 쪽, 오른끝은 가로획이
            닿는 세로획 안에 둔다 (`_bar_rows`). 그 줄들의 위아래가 획의 두께다.
    `gap`   틈 (단위).
    `side`  `"left"` 면 왼끝을 뗀다. 기본은 오른끝.

    가로획 위아래 속공간 두 윤곽이 세로획 안변에서 맞닿는 모서리 (x, 윗변) ·
    (x, 아랫변) 을 찾아, 두 윤곽을 그 자리에서 이어 한 속공간으로 만든다. 가로획
    끝면은 세로획 안변에서 `gap` 만큼 물러난 곧은 선이다. 네모로 오리지 않으니
    먹 밖을 건드릴 일이 없다.
    """
    left = spec.get("side", "right") == "left"
    gap = spec["gap"]
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = list(glyph.foreground)
        if not cs:
            continue
        mask = O.part_mask(cs)
        x0, y0, x1, y1 = _in_box(ctx, glyph, spec["at"])
        rows = _bar_rows(mask, (x0, y0, x1, y1))
        if not rows:
            print("detachBar: %s 에서 가로획을 못 찾았다" % glyph.glyphname)
            continue
        lo = O.snap_y(cs, min(r[0] for r in rows) - 0.5)
        hi = O.snap_y(cs, max(r[0] for r in rows) + 0.5)
        # 세로획 안변 — 가로획 바로 위 줄에서 네모 끝을 덮는 먹 토막의 안쪽 끝
        probe = x0 if left else x1
        yy = int(round(hi)) + 3
        run = next(((a, b) for a, b in O.runs(mask[1000 - yy]) if a <= probe <= b), None)
        if run is None:
            print("detachBar: %s 에서 세로획을 못 찾았다" % glyph.glyphname)
            continue
        sx = O.snap_x(cs, run[1] if left else run[0])
        ex = sx + gap if left else sx - gap

        def corner(y):
            # 위아래 속공간의 안변이 한두 단위 어긋난 굵기가 있다 (酵 Regular 129 · 130)
            near = [(abs(q.x - sx) + abs(q.y - y), ci, i) for ci, c in enumerate(cs)
                    for i, q in enumerate(c) if q.on_curve and abs(q.x - sx) < 2.5 and abs(q.y - y) < 1]
            return min(near)[1:] if near else None
        up, dn = corner(hi), corner(lo)
        if up is None or dn is None:
            print("detachBar: %s 에서 맞닿은 속공간 모서리를 못 찾았다 (%s %s)" % (glyph.glyphname, up, dn))
            continue
        P = lambda x, y: fontforge.point(x, y, True)
        if up[0] == dn[0]:
            # 다른 끝이 이미 떨어져 위아래 속공간이 한 윤곽이다 — 이 끝까지 떼면 가로획이
            # 섬이 된다. 두 모서리 사이 호 가운데 가로획을 도는 쪽을 떼어 섬으로 닫고,
            # 남은 호는 세로획 안변을 따라 곧게 닫는다.
            C = list(cs[up[0]])
            n = len(C)
            def arc(a, b):
                return [C[(a + t) % n] for t in range((b - a) % n + 1)]
            onbar = lambda seg: all(lo - 1 <= q.y <= hi + 1 for q in seg)
            a1, a2 = arc(up[1], dn[1]), arc(dn[1], up[1])
            bar, rest = (a1, a2) if onbar(a1) else (a2, a1)
            if not onbar(bar):
                print("detachBar: %s 에서 가로획을 도는 호를 못 찾았다" % glyph.glyphname)
                continue
            isl = [P(ex, q.y) for q in (bar[0], bar[-1])]
            isl = [isl[0]] + bar[1:-1] + [isl[1]]
            groups = []
            for seq in (isl, rest):
                k = fontforge.contour()
                k.is_quadratic = cs[up[0]].is_quadratic
                for q in seq:
                    k += q
                k.closed = True
                groups.append(k)
            others = [c for ci, c in enumerate(cs) if ci != up[0]]
            relay(glyph, [others, groups], merge=False)
            glyph.correctDirection()
            done.append("%s 끝 %d→%d (y %d..%d, 섬)" % (glyph.glyphname, sx, ex, lo, hi))
            continue
        U, D = list(cs[up[0]]), list(cs[dn[0]])
        i, j = up[1], dn[1]
        Dr = D[j + 1:] + D[:j + 1]                    # 아래 모서리 다음부터 돌아 모서리까지
        prev = U[i - 1]
        if abs(prev.y - hi) < 1 and (prev.x > sx if left else prev.x < sx):
            # 윗 속공간의 아랫변을 따라 모서리에 닿는다 → 끝면을 타고 내려가 아래 속공간을 돈다
            seq = U[:i] + [P(ex, hi), P(ex, lo)] + Dr + [P(sx, hi)] + U[i + 1:]
        else:
            # 반대 방향 — 세로획 안변을 타고 모서리에 닿는다
            seq = U[:i + 1] + [P(sx, lo)] + Dr[:-1] + [P(ex, lo), P(ex, hi)] + U[i + 1:]
        k = fontforge.contour()
        k.is_quadratic = cs[up[0]].is_quadratic
        for q in seq:
            k += q
        k.closed = True
        rest = [c for ci, c in enumerate(cs) if ci not in (up[0], dn[0])]
        relay(glyph, [rest, [k]], merge=False)
        glyph.correctDirection()
        done.append("%s 끝 %d→%d (y %d..%d)" % (glyph.glyphname, sx, ex, lo, hi))
    if done:
        print("detachBar: %s" % ", ".join(done))


@op("extendTip")
def op_extend_tip(ctx, font, spec, source_half):
    """세로획에 닿아 멈춘 획을 세로획 너머로 내민다 — 세로획 안은 제 곡선, 너머는 배운 끝.

        {"op": "extendTip", "like": "5561", "at": [0.50, 0.70, 0.70, 0.80],
         "cps": ["7dcb"]}           緋 — 非 왼쪽 셋째 획을 啡 처럼 세로획 너머로

    획의 두 변은 세로획 왼변에서 끝나는 곡선이다. 아랫변을 y = f(x) 포물선으로
    보고 세로획 오른변까지 늘인다. 윗변은 같은 포물선을 획 굵기 (두 변이 세로획에
    닿는 점의 차이) 만큼 올린 것이다. 오른변 너머는 `like` 의 내민 끝의 점과 곡선
    (이음점 → 변 → 끝면 → 변 → 이음점) 을 그대로 쓰고, 그 아래 이음점을 제 곡선이
    오른변과 만나는 점에 맞춰 옮긴다 — 나온 토막의 기울기와 끝면이 `like` 와 같다.

    `like`  같은 획이 세로획을 지나 나온 글자 (같은 소스, 같은 굵기).
    `at`    두 글자에서 그 세로획의 위쪽 곧은 부분을 고르는 네모. 왼변·오른변의
            기준이다.
    """
    like = donor_glyph(font, spec, "like")
    done = []

    def stem(glyph):
        x0, y0, x1, y1 = _in_box(ctx, glyph, spec["at"])
        mask = O.part_mask(list(glyph.foreground))
        ym = int(round((y0 + y1) / 2))
        r = [(a, b) for a, b in O.runs(mask[1000 - ym]) if x0 <= a and b <= x1]
        return (r[0][0], r[0][1]) if r else None

    def lerp(p, q, t):
        return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)

    def quad(P0, P1, P2, t):
        return lerp(lerp(P0, P1, t), lerp(P1, P2, t), t)

    for glyph in selected_glyphs(font, spec):
        a, b = stem(like), stem(glyph)
        if a is None or b is None:
            print("extendTip: %s 세로획을 못 찾았다" % glyph.glyphname)
            continue
        dx = b[1] - a[1]
        # 誹 의 끝 모서리 — 오른변에서 15 넘게 나간 on 점들
        corners = [(q.x, q.y) for c in like.foreground for q in c
                   if q.on_curve and a[1] + 15 < q.x < a[1] + 90 and 100 < q.y < 500]
        if len(corners) < 2:
            print("extendTip: %s 에서 끝 모서리를 못 찾았다" % like.glyphname)
            continue
        corners.sort(key=lambda q: q[1])
        lo_x, hi_x = corners[0][0] + dx, corners[-1][0] + dx
        ylo, yhi = corners[0][1] - 150, corners[-1][1] + 150
        # 緋 의 두 변 — 세로획 왼변에 닿는 on 점과, 왼쪽에서 오는 곡선
        edges = []
        for c in glyph.foreground:
            pts = list(c)
            n = len(pts)
            for i, q in enumerate(pts):
                if not q.on_curve or not -25 < q.x - b[0] < 8 or not ylo < q.y < yhi:
                    continue
                for d in (-1, 1):
                    r = pts[(i + d) % n]
                    # 왼쪽 아래에서 올라오는 곡선 (세로획 왼변의 곡선은 아래로 가파르다)
                    if r.x < q.x - 30 and 3 < q.y - r.y < 0.9 * (q.x - r.x):
                        if r.on_curve:
                            P0, P1 = (r.x, r.y), ((r.x + q.x) / 2, (r.y + q.y) / 2)
                        else:
                            s0 = pts[(i + 2 * d) % n]
                            P0, P1 = (s0.x, s0.y), (r.x, r.y)
                        edges.append((q.y, P0, P1, (q.x, q.y)))
        if len(edges) != 2:
            print("extendTip: %s 획의 두 변을 못 찾았다 %s" % (glyph.glyphname, [(e[1], e[3]) for e in edges]))
            continue
        edges.sort()
        # 아랫변을 y = f(x) 포물선으로 맞춰 x 로 늘린다 — 기울기가 같은 비율로 커지며
        # 오른쪽으로 간다 (t 로 늘리면 곡선이 서서 되돌아온다). 늘린 구간의 조절점은
        # 두 끝 접선이 만나는 자리 — 포물선을 그대로 나타낸다.
        (_, P0, P1, B2), (_, _, _, T2) = edges
        (x0, y0), (xm, ym), (x2, y2) = P0, quad(P0, P1, B2, 0.5), B2
        d1, d2 = (ym - y0) / (xm - x0), (y2 - ym) / (x2 - xm)
        qa = (d2 - d1) / (x2 - x0)
        f = lambda x: y2 + (x - x2) * (d2 + qa * (x - xm))
        df = lambda x: d2 + qa * (x - xm) + qa * (x - x2)
        Be = (lo_x, f(lo_x))
        h = (lo_x - x2) / 2
        Bc = (x2 + h, y2 + df(x2) * h)
        ox, oy = T2[0] - B2[0], T2[1] - B2[1]
        g = lambda x: f(x - ox) + oy
        dg = lambda x: df(x - ox)
        # 세로획 안은 제 곡선을 오른변까지 늘리고, 그 너머는 `like` 의 내민 끝 짜임을
        # 그대로 — 아래 이음점을 제 곡선이 오른변과 만나는 점에 맞춰 옮긴다.
        tip = None
        for cc in like.foreground:
            pts = list(cc)
            n = len(pts)
            far = set(i for i, q in enumerate(pts) if a[1] + 15 < q.x < a[1] + 90 and 100 < q.y < 500)
            if not far:
                continue
            st = next(i for i in far if (i - 1) % n not in far)
            run = [st]
            while (run[-1] + 1) % n in far:
                run.append((run[-1] + 1) % n)
            i0 = (run[0] - 1) % n
            while not pts[i0].on_curve:
                i0 = (i0 - 1) % n
            i1 = (run[-1] + 1) % n
            while not pts[i1].on_curve:
                i1 = (i1 + 1) % n
            tip = [(q.x, q.y, q.on_curve) for q in (pts[(i0 + t) % n] for t in range((i1 - i0) % n + 1))]
            break
        if tip is None:
            print("extendTip: %s 에서 내민 끝을 못 찾았다" % like.glyphname)
            continue
        if tip[0][1] > tip[-1][1]:
            tip = tip[::-1]                             # 아래 이음점부터
        rx = b[1]
        Bx = (rx, f(rx))
        Tx = (rx, g(rx))
        sx, sy = Bx[0] - tip[0][0], Bx[1] - tip[0][1]
        hb, ht = (rx - B2[0]) / 2, (rx - T2[0]) / 2
        Bc = (B2[0] + hb, B2[1] + df(B2[0]) * hb)
        Tc = (T2[0] + ht, T2[1] + dg(T2[0]) * ht)
        seq = [(B2[0], B2[1], True), (Bc[0], Bc[1], False), (Bx[0], Bx[1], True)]
        seq += [(x + sx, y + sy, on) for x, y, on in tip[1:-1]]
        seq += [(tip[-1][0] + sx, tip[-1][1] + sy, True)]
        if abs(tip[-1][1] + sy - Tx[1]) > 1:
            seq += [(Tx[0], Tx[1], True)]
        seq += [(Tc[0], Tc[1], False), (T2[0], T2[1], True)]
        Be, Te = (tip[1][0] + sx, tip[1][1] + sy), (tip[-2][0] + sx, tip[-2][1] + sy)
        piece = fontforge.contour()
        piece.is_quadratic = glyph.foreground.is_quadratic
        for x, y, on in seq:
            piece += fontforge.point(x, y, on)
        piece.closed = True
        if not piece.isClockwise():
            piece.reverseDirection()
        relay(glyph, [list(glyph.foreground), [piece]])
        done.append("%s 끝 (%d,%d) (%d,%d)" % (glyph.glyphname, Be[0], Be[1], Te[0], Te[1]))
    if done:
        print("extendTip: %s" % ", ".join(done))


@op("tailCorner")
def op_tail_corner(ctx, font, spec, source_half):
    """꺾이는 모서리에서 내려오던 획을 가로획 밑으로 조금 삐져나오게 한다.

        {"op": "tailCorner", "at": [0.05, 0.10, 0.25, 0.26], "by": 28, "cps": ["828e"]}
                                    芎 — 弓 의 넷째 꺾임 (KS 는 아래로 삐친다)

    `at`  모서리를 고르는 네모. 그 안에서 위에서 내려온 변이 오른쪽으로 꺾여 가로획이
          되는 on 점 둘을 찾는다 — 아래 것이 바깥 모서리 (가로획 아랫변), 위 것이 안쪽
          모서리 (가로획 윗변).
    `by`  가로획 아랫변 밑으로 나올 길이 (단위).
    `even` 나온 토막의 폭을 끝까지 같게 — 윗변을 아랫변 곡선을 옮긴 것으로 그린다.

    내려오던 두 변은 곡선이다. 변마다 x = f(y) 포물선으로 보고 같은 곡선으로 `by`
    만큼 아래까지 늘인다 — 위의 곡선과 같은 휨으로 이어진다. 늘인 구간의 조절점은
    두 끝 접선이 만나는 자리. 끝은 수평으로 자른다.
    """
    by = spec["by"]
    done = []

    def quad(P0, P1, P2, t):
        u = 1 - t
        return (u * u * P0[0] + 2 * u * t * P1[0] + t * t * P2[0],
                u * u * P0[1] + 2 * u * t * P1[1] + t * t * P2[1])

    for glyph in selected_glyphs(font, spec):
        x0, y0, x1, y1 = _in_box(ctx, glyph, spec["at"])
        found = []
        for c in glyph.foreground:
            pts = list(c)
            n = len(pts)
            for i, q in enumerate(pts):
                if not q.on_curve or not (x0 <= q.x <= x1 and y0 <= q.y <= y1):
                    continue
                for d in (-1, 1):
                    # 모서리에 붙어 선 군더더기 조절점은 건너뛴다 (鰐 Regular (572,207)·(573,208))
                    e = d
                    while math.hypot(pts[(i + e) % n].x - q.x, pts[(i + e) % n].y - q.y) < 3 and abs(e) < 3:
                        e += d
                    r = pts[(i + e) % n]
                    f_ = pts[(i - d) % n]
                    if (r.y > q.y + 8 and abs(r.x - q.x) < 3 * (r.y - q.y)
                            and abs(f_.y - q.y) < 2 and f_.x > q.x + 20):
                        if r.on_curve:
                            P0, P1 = (r.x, r.y), ((r.x + q.x) / 2, (r.y + q.y) / 2)
                        else:
                            s0 = pts[(i + e + d) % n]
                            P0, P1 = (s0.x, s0.y), (r.x, r.y)
                        found.append((q.y, P0, P1, (q.x, q.y)))
        if len(found) != 2:
            print("tailCorner: %s 모서리 %d 개 — %s" % (glyph.glyphname, len(found), [f[3] for f in found]))
            continue
        found.sort()
        yend = found[0][3][1] - by
        ends, fs = [], []
        for _, P0, P1, P2 in found:
            # x = f(y) 포물선 — 세 점 (시작, 가운데, 모서리) 을 지난다
            (ax, ay), (mx, my), (bx, bym) = P0, quad(P0, P1, P2, 0.5), P2
            d1, d2 = (mx - ax) / (my - ay), (bx - mx) / (bym - my)
            qa = (d2 - d1) / (bym - ay)
            f = lambda y, bx=bx, bym=bym, d2=d2, qa=qa, my=my: bx + (y - bym) * (d2 + qa * (y - my))
            df = lambda y, d2=d2, qa=qa, my=my, bym=bym: d2 + qa * (y - my) + qa * (y - bym)
            h = (yend - bym) / 2
            ends.append((P2, (bx + df(bym) * h, bym + h), (f(yend), yend)))
            fs.append((f, df))
        (O_, Oc, Oe), (I_, Ic, Ie) = ends
        if spec.get("even"):
            # 윗변을 아랫변 곡선을 옮긴 것으로 — 가로획 아랫변 높이의 폭 w 가 끝까지 같다.
            # 두 변을 따로 늘리면 휨이 달라 끝이 가늘어진다 (樗).
            (fo, dfo), (fi, _) = fs
            w = fi(O_[1]) - O_[0]
            h = (yend - I_[1]) / 2
            Ic = (I_[0] + dfo(I_[1]) * h, I_[1] + h)
            Ie = (fo(yend) + w, yend)
        piece = fontforge.contour()
        piece.is_quadratic = glyph.foreground.is_quadratic
        for (x, y), on in ((O_, True), (Oc, False), (Oe, True), (Ie, True), (Ic, False), (I_, True)):
            piece += fontforge.point(x, y, on)
        piece.closed = True
        if not piece.isClockwise():
            piece.reverseDirection()
        relay(glyph, [list(glyph.foreground), [piece]])
        done.append("%s (%d,%d)(%d,%d)→(%d,%d)(%d,%d)" % (glyph.glyphname, O_[0], O_[1], I_[0], I_[1],
                                                         Oe[0], Oe[1], Ie[0], Ie[1]))
    if done:
        print("tailCorner: %s" % ", ".join(done))


@op("headHook")
def op_head_hook(ctx, font, spec, source_half):
    """획 머리를 왼쪽 아래로 짧게 꺾는다 — ∧ 처럼 위에서 뾰족하게 만난다.

        {"op": "headHook", "at": [0.13, 0.75, 0.32, 0.81], "len": 120, "cps": ["4e42"]}
                                    乂 — KS 는 첫 획 머리가 왼쪽 아래로 꺾여 있다

    `at`   머리 끝을 고르는 네모. 그 안의 가장 높은 on 점 둘이 머리 끝 모서리 —
           왼쪽 A, 오른쪽 B.
    `len`  꺾인 획이 원래 획 왼쪽 변 밖으로 나온 길이 (아랫변을 따라, 단위) — 굵기가
           달라도 같은 만큼 나온다. 모든 굵기에 같은 값.
    `deg`  꺾인 획이 수평에서 내려가는 각 (기본 45).

    굵기는 머리 끝 |AB| 그대로. 꺾인 획의 윗변은 B 에서 출발하고, A 는 왼쪽 변을 따라
    그 윗변 위로 옮긴다 — 원래 머리는 남지 않는다. 끝은 꺾인 획에 수직으로 자른다.
    """
    L = spec["len"]
    th = math.radians(spec.get("deg", 45))
    hx, hy = -math.cos(th), -math.sin(th)          # 꺾인 획이 가는 쪽
    nx, ny = math.sin(th), -math.cos(th)           # 그 아래쪽 (획 안으로)

    def cross(P, d, Q, e):
        den = d[0] * e[1] - d[1] * e[0]
        s = ((Q[0] - P[0]) * e[1] - (Q[1] - P[1]) * e[0]) / den
        return s, (P[0] + s * d[0], P[1] + s * d[1])

    done = []
    for glyph in selected_glyphs(font, spec):
        x0, y0, x1, y1 = _in_box(ctx, glyph, spec["at"])
        cs = list(glyph.foreground)
        hit = None
        for c in cs:
            pts = list(c)
            n = len(pts)
            idx = sorted((i for i, q in enumerate(pts)
                          if q.on_curve and x0 <= q.x <= x1 and y0 <= q.y <= y1), key=lambda i: -pts[i].y)
            if len(idx) >= 2 and (idx[0] - idx[1]) % n in (1, n - 1):
                hit = (c, pts, n, idx[0], idx[1])
                break
        if not hit:
            print("headHook: %s 에서 머리 끝을 못 찾았다" % glyph.glyphname)
            continue
        c, pts, n, i, j = hit
        if pts[i].x > pts[j].x:
            i, j = j, i
        A, B = pts[i], pts[j]
        da = 1 if (j - i) % n == n - 1 else -1        # A 에서 B 반대쪽으로 가는 걸음
        An, Bn = pts[(i + da) % n], pts[(j - da) % n]
        dA = (An.x - A.x, An.y - A.y)
        dB = (Bn.x - B.x, Bn.y - B.y)
        t = math.hypot(B.x - A.x, B.y - A.y)
        s, Q = cross((A.x, A.y), dA, (B.x, B.y), (hx, hy))
        if not 0 < s < 1:
            print("headHook: %s 왼쪽 변이 짧다 (s=%.2f)" % (glyph.glyphname, s))
            continue
        # 꺾인 획 아랫변이 원래 획 왼쪽 변(A 에서 내려가는 곡선)을 벗어나는 곳 E — 거기서 `len`
        P = (B.x + t * nx, B.y + t * ny)
        if An.on_curve:
            C0, C1, C2 = (A.x, A.y), ((A.x + An.x) / 2, (A.y + An.y) / 2), (An.x, An.y)
        else:
            Nn = pts[(i + 2 * da) % n]
            C0, C1, C2 = (A.x, A.y), (An.x, An.y), (Nn.x, Nn.y)
        def side(u):
            v = 1 - u
            x = v * v * C0[0] + 2 * u * v * C1[0] + u * u * C2[0]
            y = v * v * C0[1] + 2 * u * v * C1[1] + u * u * C2[1]
            return (x - P[0]) * hy - (y - P[1]) * hx, (x, y)
        E = None
        prev = side(0)
        for k in range(1, 401):
            cur = side(k / 400.0)
            if (prev[0] > 0) != (cur[0] > 0):
                E = cur[1]
                break
            prev = cur
        if E is None:
            print("headHook: %s 아랫변이 왼쪽 변과 만나지 않는다" % glyph.glyphname)
            continue
        T2 = (E[0] + L * hx, E[1] + L * hy)
        T1 = (T2[0] - t * nx, T2[1] - t * ny)
        M = ((A.x + B.x) / 2, (A.y + B.y) / 2)
        _, R = cross(T2, (-hx, -hy), M, dB)            # 꺾인 획 아랫변이 원래 획 가운데에 닿는 곳
        A.x, A.y = Q
        c[i] = A
        piece = fontforge.contour()
        piece.is_quadratic = glyph.foreground.is_quadratic
        for x, y in ((B.x, B.y), T1, T2, R):
            piece += fontforge.point(x, y, True)
        piece.closed = True
        if not piece.isClockwise():
            piece.reverseDirection()
        relay(glyph, [cs, [piece]])
        done.append("%s 머리 (%d,%d)→끝 (%d,%d)(%d,%d) 굵기 %d 윗변 %d" % (
            glyph.glyphname, B.x, B.y, T1[0], T1[1], T2[0], T2[1], t, math.hypot(T1[0] - B.x, T1[1] - B.y)))
    if done:
        print("headHook: %s" % ", ".join(done))


def _stem_path(glyph, box):
    """네모 안에서 가로획 밑으로 내려가는 세로획 아랫도막 — (윤곽 번호, 점들, 오른 모서리→왼 모서리 점 번호들).

    네모 안 점 가운데 가장 높은 줄의 점들 중 x 가 큰 둘이 가로획 아랫변과 만나는 두 모서리다
    (그 줄의 더 왼쪽 점은 가로획 왼끝). 오른 모서리에서 네모 안 점을 따라 내려가 왼 모서리에
    닿는 길이 아랫도막이다.
    """
    x0, y0, x1, y1 = box
    for ci, c in enumerate(glyph.foreground):
        pts = list(c)
        n = len(pts)
        inn = [k for k, q in enumerate(pts) if x0 <= q.x <= x1 and y0 <= q.y <= y1]
        if len(inn) < 4:
            continue
        top = max(pts[k].y for k in inn if pts[k].on_curve)
        row = sorted((k for k in inn if pts[k].on_curve and pts[k].y >= top - 1), key=lambda k: -pts[k].x)
        if len(row) < 2:
            continue
        i, j = row[0], row[1]
        for d in (1, -1):
            path, k = [i], i
            while k != j:
                k = (k + d) % n
                if k not in inn:
                    break
                path.append(k)
            if path[-1] == j and len(path) > 2:
                return ci, pts, path
    return None


@op("likeStem")
def op_like_stem(ctx, font, spec, source_half):
    """세로획 아랫도막(가로획 밑)을 `like` 글자의 같은 획 짜임으로 다시 그린다.

        {"op": "likeStem", "like": "518c", "at": [0, -0.1, 0.3, 0.39],
         "likeAt": [0, -0.1, 0.3, 0.41], "cps": ["518a"]}
                    冊 — 첫 획이 KS 처럼 丿 로 휜다. 册 (같은 굵기) 의 첫 획을 배운다.

    `at`, `likeAt`  두 글자에서 아랫도막을 고르는 네모 (`_stem_path`). 위끝은 가로획
                    아랫변은 넣고 윗변은 빼게.

    `like` 의 아랫도막 점과 곡선 (on/off 그대로) 을 이 글자의 아랫도막에 옮긴다 — x 는 두
    모서리 (획 폭) 를, y 는 모서리 높이와 맨 아래를 맞춘다. 조각을 떼어 붙이지 않고 제
    윤곽의 점을 바꾼다.
    """
    done = []
    for glyph in selected_glyphs(font, spec):
        like = donor_glyph(font, spec, "like")
        if like is None:
            print("likeStem: like 글리프가 없다")
            return
        a = _stem_path(glyph, _in_box(ctx, glyph, spec["at"]))
        b = _stem_path(like, _in_box(ctx, like, spec.get("likeAt", spec["at"])))
        if not a or not b:
            print("likeStem: %s 에서 아랫도막을 못 찾았다 (%s %s)" % (glyph.glyphname, bool(a), bool(b)))
            continue
        ci, pts, path = a
        c = glyph.foreground[ci]
        _, lp, lpath = b
        R, Lf = pts[path[0]], pts[path[-1]]
        lR, lL = lp[lpath[0]], lp[lpath[-1]]
        bot = min(pts[k].y for k in path)
        lbot = min(lp[k].y for k in lpath)
        sx = (R.x - Lf.x) / (lR.x - lL.x)
        sy = (R.y - bot) / (lR.y - lbot)
        new = [(Lf.x + (lp[k].x - lL.x) * sx, R.y + (lp[k].y - lR.y) * sy, lp[k].on_curve) for k in lpath]
        keep = set(path)
        n = len(pts)
        out = fontforge.contour()
        out.is_quadratic = c.is_quadratic
        k = (path[-1] + (path[-1] - path[-2])) % n           # 왼 모서리 다음부터 한 바퀴
        step = path[-1] - path[-2]
        step = 1 if step in (1, -(n - 1)) else -1
        rest = []
        while k not in keep:
            rest.append(pts[k])
            k = (k + step) % n
        seq = [(q.x, q.y, q.on_curve) for q in rest] + new
        if step == -1:
            seq.reverse()
        for x, y, on in seq:
            out += fontforge.point(x, y, on)
        out.closed = True
        cs = [out if k == ci else cc for k, cc in enumerate(glyph.foreground)]
        relay(glyph, [cs], merge=False)
        done.append("%s 점 %d→%d (밑 %d→%d)" % (glyph.glyphname, len(path), len(new), bot,
                                                 min(y for _, y, _ in new)))
    if done:
        print("likeStem: %s" % ", ".join(done))


@op("shortLegs")
def op_short_legs(ctx, font, spec, source_half):
    """가운데 곧은 다리들의 아래끝을 `end` 높이에서 곧게 자른다.

        {"op": "shortLegs", "at": [0.2, -0.1, 0.465, 0.15], "end": 0.047, "cps": ["522a"]}
                    刪 — 가운데 두 다리를 册 (evenLegs, 끝 47) 처럼 짧게

    `at`   다리를 고르는 네모. 위끝 높이의 줄에서 네모 안에 온전히 드는 먹 구간이 다리다
           (휜 첫 획과 갈고리 벽은 네모 밖에 두도록).
    `end`  다리 끝 높이 (em 대비). 모든 굵기에 같은 값.

    점을 옮기지 않고 다리 폭 그대로 아래를 잘라 낸다 — 굵은 굵기에서 셋째 다리가 갈고리와
    맞붙어 있어도 다리는 곧게 끝난다 (점을 옮기면 사선이 남았다). 잘라 낸 뒤에도 다리 자리
    아래에 남은 먹 (갈고리) 이 `end` 보다 높이 올라오면 그 위 1 단위에서 끊는다 — 册 과 같다.
    """
    em = ctx.em_ascent + ctx.em_descent
    done = []
    for glyph in selected_glyphs(font, spec):
        x0, y0, x1, y1 = _in_box(ctx, glyph, spec["at"])
        cs = list(glyph.foreground)
        legs = [(O.snap_x(cs, a), O.snap_x(cs, b)) for a, b in _ink_runs(cs, y1) if x0 <= a and b <= x1]
        if not legs:
            print("shortLegs: %s 에서 다리를 못 찾았다" % glyph.glyphname)
            continue
        gx0, gx1, gy0, gy1 = O.bbox(cs)

        def cut(floor):
            # 세로 띠는 다리 변에서 1 단위 비켜 둔다 — 다리 변과 겹친 경계는 실낱이 되어
            # removeOverlap 이 길을 잃는다. 띠는 위아래로 끝까지 — 남길 몫과 넓게 겹쳐야 녹는다.
            edges = [gx0 - 50] + [v + d for a, b in legs for v, d in ((a, -1), (b, 1))] + [gx1 + 50]
            # 가로로 자르는 선은 다리 구간만 지나게 — 휜 첫 획을 가로지르면 곡선 자른 자리가
            # 실선으로 이어져 남는다 (刪 EL·Tx).
            boxes = [(edges[1], edges[-2], floor, gy1 + 50)]
            boxes += [(edges[k], edges[k + 1], gy0 - 50, gy1 + 50) for k in range(0, len(edges), 2)]
            return clip_to(cs, boxes)

        floor = spec["end"] * em
        keep = cut(floor)
        m = O.part_mask(keep)
        for a, b in legs:
            for lo, hi in O.ink_spans(m, a + 1, b - 1, gy0 - 10, floor - 2):
                floor = max(floor, hi + 1)
            # 다리 바로 오른쪽에 붙은 갈고리 (刪·柵 굵은 굵기) — 그 윗변보다 1 위에서 끊는다
            for lo, hi in O.ink_spans(m, b + 1, b + 4, gy0 - 10, floor + 4):
                if hi >= floor - 2:
                    floor = max(floor, hi + 1)
        if floor > spec["end"] * em:
            keep = cut(floor)
        relay(glyph, [keep])
        done.append("%s 다리 %s 끝 %d" % (glyph.glyphname, " ".join("%d..%d" % l for l in legs), floor))
    if done:
        print("shortLegs: %s" % ", ".join(done))


@op("enForm")
def op_en_form(ctx, font, spec, source_half):
    """月 을 円 으로 — 안 가로획 하나를 지우고, 冂 윗변에서 남은 가로획까지 가운데 세로획을 세운다.

        {"op": "enForm", "at": [0.40, 0.05, 0.95, 0.44], "drop": "both", "cps": ["9756"]}
                    靖 — 青 아래 月 → 円 (KS)

    `at`    月 을 덮는 네모. 아래끝 줄에서 네모 안 맨 바깥 먹 둘이 벽이고, 두 벽 한복판을
            세로로 훑어 네모 안의 먹 토막을 위에서부터 冂 윗변 · 가로획들로 본다.
    `drop`  지울 가로획 — `"lower"` (기본) · `"upper"`, 또는 `"both"` — 둘을 지우고 두 가로획
            한가운데에 같은 두께로 하나를 건다 (靖).

    가로획은 두 벽 안쪽 변 사이를 감김이 반대인 네모로 도려낸다. 세로획 폭은
    두 벽 굵기의 평균, 위아래 획 속으로 12 씩 파고든다.
    """
    done = []
    for glyph in selected_glyphs(font, spec):
        x0, y0, x1, y1 = _in_box(ctx, glyph, spec["at"])
        cs = list(glyph.foreground)
        m = O.part_mask(cs)
        runs = [r for r in O.runs(m[1000 - int(y0)]) if x0 <= r[0] and r[1] <= x1]
        if len(runs) < 2:
            print("enForm: %s 에서 벽을 못 찾았다" % glyph.glyphname)
            continue
        la, lb = O.snap_x(cs, runs[0][0]), O.snap_x(cs, runs[0][1])
        ra, rb = O.snap_x(cs, runs[-1][0]), O.snap_x(cs, runs[-1][1])
        mid = (lb + ra) / 2.0
        spans = O.ink_spans(m, mid - 2, mid + 2, y0, y1)        # 위에서 아래로
        if len(spans) < 3:
            print("enForm: %s 가운데 줄 먹 토막 %d" % (glyph.glyphname, len(spans)))
            continue
        top = O.snap_y(cs, spans[0][0])                         # 冂 윗변의 밑
        bars = [(O.snap_y(cs, lo), O.snap_y(cs, hi)) for lo, hi in spans[1:3]]
        keep_bar, drop_bar = (bars[0], bars[1]) if spec.get("drop", "lower") == "lower" else (bars[1], bars[0])
        gx0, gx1, gy0, gy1 = O.bbox(cs)
        lo, hi = drop_bar
        t = ((lb - la) + (rb - ra)) / 2.0
        ink = O._turn(max(cs, key=lambda c: len(list(c))))
        # 가로획 자리 (두 벽 안쪽 변 사이 · 가로획 두께) 에 감김이 반대인 네모를 얹어
        # removeOverlap 이 먹을 도려내게 한다 — 네모가 먹 안에 온전히 든다 (joinCounters 와 같다).
        holes, add = [_rect_contour(cs, lb, ra, lo, hi, -ink)], []
        if spec.get("drop") == "both":
            # 두 가로획을 다 지우고 그 한가운데에 같은 두께로 하나를 새로 건다
            holes.append(_rect_contour(cs, lb, ra, keep_bar[0], keep_bar[1], -ink))
            c = (bars[0][0] + bars[0][1] + bars[1][0] + bars[1][1]) / 4.0
            th = keep_bar[1] - keep_bar[0]
            keep_bar = (round(c - th / 2), round(c + th / 2))
            add.append(_rect_contour(cs, lb - 12, ra + 12, keep_bar[0], keep_bar[1], ink))
        stem = _rect_contour(cs, round(mid - t / 2), round(mid + t / 2), keep_bar[1] - 12, top + 12, ink)
        relay(glyph, [cs + holes, add + [stem]])
        done.append("%s 벽 %d..%d %d..%d 지움 %d..%d 세로 %d..%d" % (glyph.glyphname, la, lb, ra, rb,
                                                                 lo, hi, keep_bar[1], top))
    if done:
        print("enForm: %s" % ", ".join(done))


def _dot_keeping_y(cs, dcs, a, b, sy):
    """swapCounters 의 세로 옮김 — 점의 굵기를 SC 규칙대로 (가로획을 따라 굵어진다).

    굵은 쪽에선 점이 칸 높이를 거의 다 차지해, 칸을 sy 배로 줄이면 점이 그만큼
    가늘어진다. 그래서 짜임은 (이 글자 가로획 / 기증자 가로획) 배만 하여 칸 가운데에
    두고, 칸 위아래 끝 — 흰 칸의 가로 변 — 만 이 글자 칸 끝에 맞춘다 (넘치면 잘린다).
    """
    def bar(cl, c):                             # 칸 위 가로획 굵기 — 점이 닿는 줄은 몇 안 되니 가운데값
        m, w = O.part_mask(cl), (c[1] - c[0]) * 0.2
        ts = [hi - lo for x in range(int(c[0] + w), int(c[1] - w), 5)
              for lo, hi in O.ink_spans(m, x, x + 1, c[3] - 8, c[3] + 200)
              if c[3] - 8 <= lo <= c[3] + 3 and hi > c[3] + 3]
        return sorted(ts)[len(ts) // 2] if ts else None
    rb, db = bar(cs, a), bar(dcs, b)
    r = rb / db if rb and db else sy
    cb, ca = (b[2] + b[3]) / 2, (a[2] + a[3]) / 2

    # 이 글자 칸의 위아래 변 — 가로획이 살짝 기울 수 있으니 세로줄마다 재어 직선으로
    import numpy as np
    m = O.part_mask(cs)
    tops, bots = [], []
    for x in range(int(a[0]) + 3, int(a[1]) - 2, 4):
        for lo, hi in O.ink_spans(m, x, x + 1, a[2] - 30, a[3] + 30):
            if a[3] - 8 <= lo <= a[3] + 3:
                tops.append((x, lo - 1))
            if a[2] - 3 <= hi <= a[2] + 8:
                bots.append((x, hi + 1))

    def edge(pts, flat):
        if len(pts) < 5:
            return lambda x: flat
        k, c = np.polyfit(*zip(*pts), 1)
        return lambda x: k * x + c
    top, bot = edge(tops, a[3]), edge(bots, a[2])

    def ymap(x, y):
        if abs(y - b[3]) < 0.5:
            return top(x)
        if abs(y - b[2]) < 0.5:
            return bot(x)
        return min(top(x), max(bot(x), ca + (y - cb) * r))
    return ymap


@op("swapCounters")
def op_swap_counters(ctx, font, spec, source_half):
    """칸 속 짜임을 다른 소스 같은 글자 (같은 굵기) 의 것으로 — 칸 틀은 제 것 그대로.

        {"op": "swapCounters", "from": "IBM-Plex-Sans-SC/IBMPlexSansSC-{cjkSrc}.ttf",
         "cells": [[0.15, 0.495, 0.82, 0.57], [0.15, 0.415, 0.82, 0.49]], "cps": ["7e9b"]}
                    纛 — 毒 가운데 세로 사선 (毋) 을 점 둘 (母) 로. SC 纛 이 KS 꼴이다.

    `from` 대신 `like` 를 적으면 **같은 글꼴의 다른 글자**에서 가져온다 — 그 글자의 칸은
            `likeCells` 로 따로 적는다. `plain` 이면 세로도 상자에 맞춰 곧게 옮긴다.

        {"op": "swapCounters", "like": "6eab", "cells": [[0.43, 0.47, 0.85, 0.775]],
         "likeCells": [[0.385, 0.455, 0.835, 0.78]], "plain": true, "cps": ["7465"]}
                    瑥 — 昷 위 네모 속 日 을 溫 의 囚 로 (TC)

    `cells` 칸마다 네모 안에 온전히 드는 윤곽 (흰 칸과 그 안의 먹) 을 두 글자에서 고른다.
            기증자 것을 고른 것들의 상자에서 이 글자 상자로 옮겨 이 글자 것 자리에 넣는다.
            가로는 상자 폭에 맞추고, 세로는 점 굵기를 지키게 _dot_keeping_y 로.
            칸 벽은 상자의 끝이라 제 벽에 그대로 닿는다.
    """
    from .ops import _PRISTINE, _open_pristine
    donor_font = None
    if "from" in spec:
        path = ctx.path(spec["from"])
        donor_font = _PRISTINE.get(path)
        if donor_font is None:
            donor_font = _PRISTINE[path] = _open_pristine(path)
    done = []
    for glyph in selected_glyphs(font, spec):
        if donor_font is not None:
            if glyph.unicode not in donor_font:
                continue
            donor = donor_font[glyph.unicode]
        else:
            donor = donor_glyph(font, spec, "like")
            if donor is None:
                continue
        cs = list(glyph.foreground)
        dcs = list(donor.foreground)
        drop, add, notes = set(), [], []
        for n, cell in enumerate(spec["cells"]):
            x0, y0, x1, y1 = _in_box(ctx, glyph, cell)
            lx0, ly0, lx1, ly1 = _in_box(ctx, donor, spec.get("likeCells", spec["cells"])[n])

            def inside(c, x0=x0, y0=y0, x1=x1, y1=y1):
                bx0, bx1, by0, by1 = O.box(c)
                return x0 <= bx0 and bx1 <= x1 and y0 <= by0 and by1 <= y1
            mine = [k for k, c in enumerate(cs) if inside(c)]
            theirs = [c for c in dcs if inside(c, lx0, ly0, lx1, ly1)]
            if not mine or not theirs:
                notes.append("칸 %d/%d" % (len(mine), len(theirs)))
                continue
            def bbox(cl):
                bs = [O.box(c) for c in cl]
                return min(b[0] for b in bs), max(b[1] for b in bs), min(b[2] for b in bs), max(b[3] for b in bs)
            a = bbox([cs[k] for k in mine])
            b = bbox(theirs)
            sx = (a[1] - a[0]) / (b[1] - b[0])
            sy = (a[3] - a[2]) / (b[3] - b[2])
            if spec.get("plain"):
                ymap = lambda x, y, a=a, b=b, sy=sy: a[2] + (y - b[2]) * sy
            else:
                ymap = _dot_keeping_y(cs, dcs, a, b, sy)
            for c in theirs:
                n = fontforge.contour()
                n.is_quadratic = c.is_quadratic
                for q in c:
                    n += fontforge.point(a[0] + (q.x - b[0]) * sx, ymap(q.x, q.y), q.on_curve)
                n.closed = True
                add.append(n)
            drop.update(mine)
            notes.append("%d→%d" % (len(mine), len(theirs)))
        if not add:
            print("swapCounters: %s 칸을 못 맞췄다 (%s)" % (glyph.glyphname, " ".join(notes)))
            continue
        relay(glyph, [[c for k, c in enumerate(cs) if k not in drop] + add])
        done.append("%s %s" % (glyph.glyphname, " ".join(notes)))
    if done:
        print("swapCounters: %s" % ", ".join(done))


@op("squashY")
def op_squash_y(ctx, font, spec, source_half):
    """글자를 가로획 두께는 그대로 두고 납작하게 — 가로획 사이 흰 칸만 줄인다.

        {"op": "squashY", "ratio": 1.0, "cps": ["66f0"]}     曰 — 편수자료처럼 너비 = 높이

    `ratio`  먹 상자의 너비 / 높이를 이 값으로 맞춘다. 늘이지는 않는다.
    `like`   `ratio` 대신 그 글자 (日) 의 너비/높이에 `times` 를 곱한 값으로 — 굵기마다
             그 굵기의 글자로 잰다. 曰 은 日 × 1.16 (나눔고딕의 曰/日 비).
    `x`      흰 칸을 찾을 세로줄 (글자 폭 대비, 기본 0.5). 그 줄을 위에서 아래로 훑어
             처음 먹과 마지막 먹 사이의 흰 칸들만 같은 비율로 줄인다. 맨 위·맨 아래
             먹 밖(曰 의 아래로 나온 다리)은 줄이지 않는다.

    y 를 조각마다 곧게 옮기므로 가로획은 두께가 그대로고, 세로획은 짧아진다.
    먹 상자의 가운데 높이는 그대로 둔다.
    """
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = list(glyph.foreground)
        if not cs:
            continue
        x0, y0, x1, y1 = glyph.boundingBox()
        ratio = spec.get("ratio")
        if "like" in spec:
            # 다른 글자 (日) 의 너비/높이에 `times` 를 곱한 비율 — 굵기마다 그 굵기의 日 로
            lb = donor_glyph(font, spec, "like").boundingBox()
            ratio = spec.get("times", 1.0) * (lb[2] - lb[0]) / (lb[3] - lb[1])
        want = (x1 - x0) / float(ratio)
        cut = (y1 - y0) - want
        if cut <= 0:
            continue
        mask = O.part_mask(cs)
        xs = int(round(spec.get("x", 0.5) * glyph.width))
        ink = [y for y in range(int(math.ceil(y0)), int(y1) + 1) if 0 <= 1000 - y < len(mask)
               and any(a <= xs <= b for a, b in O.runs(mask[1000 - y]))]
        if not ink:
            continue
        gaps, run0 = [], ink[0]
        for a, b in zip(ink, ink[1:]):
            if b - a > 1:
                gaps.append((O.snap_y(cs, a + 0.5), O.snap_y(cs, b - 0.5)))
        white = sum(hi - lo for lo, hi in gaps)
        if white <= cut:
            print("squashY: %s 흰 칸 %d 로는 %d 를 줄일 수 없다" % (glyph.glyphname, white, cut))
            continue
        k = (white - cut) / float(white)

        def f(y):
            d = 0.0
            for lo, hi in gaps:
                d += max(0.0, min(y, hi) - lo) * (1 - k)
            return y - d
        shift = (y0 + y1) / 2.0 - (f(y0) + f(y1)) / 2.0
        lay = fontforge.layer()
        lay.is_quadratic = glyph.foreground.is_quadratic
        for c in cs:
            n = fontforge.contour()
            n.is_quadratic = c.is_quadratic
            for p in c:
                n += fontforge.point(p.x, round(f(p.y) + shift), p.on_curve)
            n.closed = c.closed
            lay += n
        glyph.foreground = lay
        done.append("%s 높이 %d→%d (흰 칸 %s ×%.3f)" % (glyph.glyphname, y1 - y0, want,
                                                    [(int(a), int(b)) for a, b in gaps], k))
    for d in done:
        print("squashY:", d)


@op("shiftStem")
def op_shift_stem(ctx, font, spec, source_half):
    """가로획에 매달린 세로획을 가로획은 두고 옆으로 옮긴다 — 가로획 끝이 밖으로 나오게.

        {"op": "shiftStem", "at": [0.25, 0.60, 0.50, 0.76],
         "to": [0.28, 0.40, 0.95, 0.62], "cps": ["701b"]}     瀛 — 亡 의 세로획

    瀛 의 亡 은 세로획이 윗가로획 왼끝에서 바로 내려간다. 한국 자형은 세로획이
    안으로 들어가 가로획 끝이 밖으로 나온다. 세로획을 아래 口 의 왼쪽 세로선에
    맞춰 옮긴다.

      `at`  옮길 점을 고를 네모 ([x0, y0, x1, y1] · x 는 글자 폭, y 는 em 대비).
            위끝은 가로획 아랫변과 윗변 사이에 둔다. 네모 안에 점이 가장 많은
            윤곽 하나만 손대고, 그 윤곽에서 네모 안의 점(곡선 조절점 포함)을 옮긴다.
            네모 안 점 가운데 가장 높은 것이 가로획 아랫변이다.
      `to`  맞출 세로선이 든 네모. 그 안에 온전히 드는 윤곽들의 왼끝에 세로획
            왼변을 맞춘다. 대신 `by` (글자 폭 대비) 로 옮길 몫을 바로 줄 수 있다.

    옮긴 점과 남은 점 사이의 세로 변이 가로획 아랫변을 지나면 그 높이에 점 둘을
    넣어 모서리를 만든다 (하나는 남고 하나는 따라간다). 그 밖의 윤곽은 그대로다.
    """
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = list(glyph.foreground)
        x0, y0, x1, y1 = _in_box(ctx, glyph, spec["at"])

        def inside(p):
            return x0 <= p.x <= x1 and y0 <= p.y <= y1
        k = max(range(len(cs)), key=lambda i: sum(1 for p in cs[i] if p.on_curve and inside(p)))
        c = cs[k]
        if not any(inside(p) for p in c):
            continue
        xv = min(p.x for p in c if p.on_curve and inside(p))
        # 다른 획이 세로획에 녹아 붙어 있으면 (瀛 Bold 의 氵 첫 점) 세로획 왼변에서
        # 갈라 떼고, 뗀 획의 잘린 끝은 두 변을 늘려 본디 꼭짓점으로 되살린다.
        # 그러지 않으면 세로획을 따라 그 획 끝이 늘어나 쐐기가 생긴다.
        loose = []
        if any(p.on_curve and p.x < xv - 0.5 and y0 <= p.y <= y1 for p in c):
            left = [O.loop_contour(l) for l in O.loop_clip(O.arcs(c), 1.0, 0.0, -xv)]
            right = [O.loop_contour(l) for l in O.loop_clip(O.arcs(c), -1.0, 0.0, xv)]
            body = max(right, key=lambda o: len(o)) if right else None
            if body is None:
                continue
            for o in left:
                on = [i for i, p in enumerate(o) if p.on_curve and abs(p.x - xv) < 0.5]
                loose.append(O.one_corner(o, on) or o)
            loose += [o for o in right if o is not body]
            c = O.tidy([body])[0][0]
        moved = [inside(p) for p in c]
        ybar = max(p.y for p, m in zip(c, moved) if m and p.on_curve)
        if "to" in spec:
            tx0, ty0, tx1, ty1 = _in_box(ctx, glyph, spec["to"])
            lefts = [O.box(o)[0] for o in cs
                     if tx0 <= O.box(o)[0] and O.box(o)[1] <= tx1
                     and ty0 <= O.box(o)[2] and O.box(o)[3] <= ty1]
            if not lefts:
                print("shiftStem: %s 에서 맞출 세로선을 못 찾았다" % glyph.glyphname)
                continue
            d = min(lefts) - xv
        else:
            d = spec["by"] * glyph.width
        pts = list(c)
        n = len(pts)
        out = fontforge.contour()
        out.is_quadratic = c.is_quadratic
        out.closed = c.closed
        for i in range(n):
            p, m = pts[i], moved[i]
            out += fontforge.point(p.x + (d if m else 0), p.y, p.on_curve)
            q, mq = pts[(i + 1) % n], moved[(i + 1) % n]
            # 옮긴 점과 남은 점을 잇는 세로 변이 가로획 아랫변을 지나면 모서리를 만든다
            if (m != mq and p.on_curve and q.on_curve and abs(p.x - q.x) < 0.5
                    and min(p.y, q.y) < ybar < max(p.y, q.y)):
                first, second = (d, 0) if m else (0, d)
                out += fontforge.point(p.x + first, ybar, True)
                out += fontforge.point(p.x + second, ybar, True)
        cs[k] = out
        relay(glyph, [cs, loose], merge=False)
        done.append("%s %+d" % (glyph.glyphname, round(d)))
    if done:
        print("shiftStem: %s" % ", ".join(done))


# --------------------------------------------------------------------------
# 세우기
# --------------------------------------------------------------------------


@op("straightenStroke")
def op_straighten_stroke(ctx, font, spec, source_half):
    """눕은 획을 곧게 세운다 — 점을 지우거나 더하지 않고 x 만 옮긴다.

    置 의 罒 과 目 을 잇는 짧은 획은 Plex 에서 아래 486 에서 위 540 으로 눕어
    있다. 편수자료는 곧은 세로획이다. 획이 눕은 만큼 되돌린 뒤 좌우 변을 각각
    한 줄로 펴면, 굵기도 위아래 이음매도 그대로 남는다.

        {"op": "straightenStroke", "at": [0.43, 0.44, 0.60, 0.64], "cps": ["7f6e"]}

    `at` 안에 든 점이 가장 많은 윤곽을 그 획이 든 윤곽으로 보고, 그 안의 든 점만
    옮긴다. 세운 획을 놓을 x 는 그 윤곽 상자의 한복판이다 (置 은 긴 가로획이 든
    윤곽이라 48..952 의 복판 500 — 罒 의 복판과 같다). `center` 로 글자 폭에 대한
    비율을 적어 달리 잡을 수 있다.

    먹을 더하지 않으므로 `removeOverlap` 을 부르지 않는다.
    """
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = list(glyph.foreground)
        bx0, by0, bx1, by1 = _in_box(ctx, glyph, spec["at"])
        best, pick = None, []
        for i, contour in enumerate(cs):
            got = [k for k, p in enumerate(contour)
                   if bx0 <= p.x <= bx1 and by0 <= p.y <= by1]
            if len(got) > len(pick):
                best, pick = i, got
        if best is None or len(pick) < 4:
            continue
        b = O.box(cs[best])
        if spec.get("center") == "base":
            center = None                   # 밑동(아래 끝) 가운데 — O.straighten 이 잰다
        elif "center" in spec:
            center = spec["center"] * (glyph.width or 1000)
        else:
            center = (b[0] + b[1]) / 2
        new, info = O.straighten(cs, best, pick, center)
        if "widthLike" in spec:
            # 굵기를 같은 글꼴의 곧은 꼭지에서 — 같은 상자 안 맨 위 on 점 둘의 x 차.
            # 제 점들의 평균은 상자에 붙으며 벌어진 밑동까지 넣어 굵어진다.
            like = donor_glyph(font, spec, "widthLike")
            lpts = [p for c in like.foreground for p in c
                    if p.on_curve and bx0 <= p.x <= bx1 and by0 <= p.y <= by1]
            lt = sorted(lpts, key=lambda p: -p.y)[:2]
            tw = abs(lt[0].x - lt[1].x)
            mid = (info[0] + info[1]) / 2
            L, R = round(mid - tw / 2), round(mid + tw / 2)
            pts = list(new[best])
            nc = fontforge.contour()
            nc.is_quadratic = new[best].is_quadratic
            for k, p in enumerate(pts):
                x = (L if p.x < mid else R) if k in pick else p.x
                nc += fontforge.point(x, p.y, p.on_curve)
            nc.closed = True
            new[best] = nc
            info = (L, R) + tuple(info[2:])
        if spec.get("flatTop"):
            # 세운 획의 끝면을 가로로 — 위 끝 두 점을 높은 쪽에 맞춘다 (F929 꼭지는
            # 비스듬히 잘려 있어 세우면 끝면이 기운다)
            pts = list(new[best])
            top = sorted((k for k in pick if pts[k].on_curve), key=lambda k: -pts[k].y)[:2]
            hy = max(pts[k].y for k in top)
            nc = fontforge.contour()
            nc.is_quadratic = new[best].is_quadratic
            for k, p in enumerate(pts):
                nc += fontforge.point(p.x, hy if k in top else p.y, p.on_curve)
            nc.closed = True
            new[best] = nc
        relay(glyph, [new], merge=False)
        done.append("%s 점%d → %d..%d" % (glyph.glyphname, len(pick), info[0], info[1]))
    if done:
        print("straightenStroke: %s" % "; ".join(done))


@op("straightenSlant")
def op_straighten_slant(ctx, font, spec, source_half):
    """살짝 굽은 사선을 곧은 사선으로 펴고, 끝을 위 획에 붙인다.

    廐 의 旡 은 가운데 가로획에서 올라가는 사선이 휘어 있고 윗 가로획 35 아래에서
    멈춘다. 편수자료는 곧은 획이 두 가로획을 잇는다. 기울기는 그대로 두고 휨만
    없앤다 — 두 변을 각각 아래 이음점과 끝점을 잇는 직선으로 보고, 조절점을 지운
    뒤 끝점을 그 직선을 따라 위 먹까지 올려 `over` (기본 12) 만큼 파고들게 한다.

        {"op": "straightenSlant", "at": [0.603, 0.30, 0.73, 0.60], "upright": true,
         "cps": ["5ed0"]}

    `upright` 를 주면 기울기도 없애 세로로 세운다 — 두 변의 x 는 위 끝점의 것
    그대로 (廐 은 위쪽을 기준으로 세운다). 아래 이음점 둘 가운데 높은 쪽(가로획
    윗변 위)은 그 x 로 옮긴다. 낮은 쪽(가로획 아랫변 위)은 가로획의 왼끝이라
    그대로 두고, 거기서 윗변 높이까지 세로로 세운 뒤 윗변을 따라 세운 획까지
    잇는다 — 가로획 길이는 원래대로, 왼끝은 사선 대신 세로 (x 는 가장 왼쪽).

    조절점은 끝점에서 이음점까지 윤곽을 따라가며 지나는 것을 모두 지운다 — `at`
    으로만 고르면 Thin·ExtraLight 의 왼변 조절점 (599, 449) 이 상자 왼끝 밖이라
    남아 곡선이 된다.

    `at` 안에 든 점이 가장 많은 윤곽을 그 획이 든 윤곽으로 본다. 그 안에서 y 가
    가장 높은 on 점 둘이 끝점, 윤곽을 따라 각 끝점에서 끝점 반대쪽으로 처음 만나는
    on 점이 그 변의 아래 이음점이다.
    """
    over = spec.get("over", 12)
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = list(glyph.foreground)
        bx0, by0, bx1, by1 = _in_box(ctx, glyph, spec["at"])
        best, pick = None, []
        for i, contour in enumerate(cs):
            got = [k for k, p in enumerate(contour)
                   if bx0 <= p.x <= bx1 and by0 <= p.y <= by1]
            if len(got) > len(pick):
                best, pick = i, got
        pts = list(cs[best]) if best is not None else []
        n = len(pts)
        ons = sorted((k for k in pick if pts[k].on_curve), key=lambda k: -pts[k].y)
        if len(ons) < 2:
            print("straightenSlant: %s 에서 획을 못 찾았다" % glyph.glyphname)
            continue
        tops = ons[:2]
        mask = O.part_mask(cs)
        tx = int(round(sum(pts[k].x for k in tops) / 2))
        ty = int(math.ceil(max(pts[k].y for k in tops))) + 1
        while ty < 1000 and not mask[1000 - ty][tx]:
            ty += 1
        goal = ty + over
        move, after, drop, ends = {}, {}, set(), {}
        for t in tops:
            other = tops[1] if t == tops[0] else tops[0]
            d = 1 if (t + 1) % n != other else -1
            k = (t + d) % n
            while not pts[k].on_curve:              # 지나는 조절점은 상자 밖이라도 지운다
                drop.add(k)
                k = (k + d) % n
            ends[t] = (k, d)
        for t, (k, d) in ends.items():
            a, b = pts[k], pts[t]
            if not spec.get("upright"):
                move[t] = (a.x + (b.x - a.x) * (goal - a.y) / (b.y - a.y), goal)
                continue
            move[t] = (b.x, goal)
            ko = [v[0] for u, v in ends.items() if u != t][0]
            if a.y < pts[ko].y:
                # 가로획 아랫변 위의 이음점 = 가로획 왼끝. 그대로 두고 윗변 높이까지
                # 세로로 세운 뒤, 윗변을 따라 세운 획까지 간다.
                hy = pts[ko].y
                if d == -1:                         # k → t 차례
                    after[k] = [(a.x, hy), (b.x, hy)]
                else:                               # t → k 차례
                    after[t] = [(b.x, hy), (a.x, hy)]
            else:
                move[k] = (b.x, a.y)
        nc = fontforge.contour()
        nc.is_quadratic = cs[best].is_quadratic
        for k, p in enumerate(pts):
            if k in drop:
                continue
            x, y = move.get(k, (p.x, p.y))
            nc += fontforge.point(x, y, p.on_curve)
            for x, y in after.get(k, []):
                nc += fontforge.point(x, y, True)
        nc.closed = True
        cs[best] = nc
        relay(glyph, [cs])
        done.append("%s 끝 %s → y %d" % (glyph.glyphname,
                    ["%d" % round(move[t][0]) for t in tops], goal))
    if done:
        print("straightenSlant: %s" % "; ".join(done))


def _col_runs(mask, x):
    """세로 한 줄 x 의 먹 토막 — [(아래 y, 위 y)], 아래부터."""
    col = mask[:, int(round(x))]
    out, start = [], None
    for i in range(len(col)):
        if col[i] and start is None:
            start = i
        elif not col[i] and start is not None:
            out.append((1000 - i + 1, 1000 - start))
            start = None
    return sorted(out)


def _roof_frame(mask, x, at):
    """食 머리 — (상자 윗변 위 y, 人 꼭대기 아랫변 y, 丶 의 줄들).

    상자 윗변은 세로줄 x 의 토막 가운데 그 바로 위 줄이 넓게(300 넘게) 가로지르는
    것, 人 꼭대기는 `at` 위끝에서 세로줄을 따라 올라가 처음 만나는 먹. 丶 은 `at`
    안의 줄들에서 양끝(人 다리) 을 뺀 가운데 토막들.
    """
    x0, y0, x1, y1 = at
    box = None
    for lo, hi in sorted(_col_runs(mask, x), key=lambda t: -t[0]):
        if hi > y1:
            continue
        r = next((t for t in O.runs(mask[1000 - (lo + 2)]) if t[0] <= x <= t[1]), None)
        if r and r[1] - r[0] > 300:
            top = lo + 2                                # 丶 이 붙어 있으면 세로줄 토막이 더
            while top < hi:                             # 길다 — 넓은 줄까지만
                r = next((t for t in O.runs(mask[1000 - (top + 1)]) if t[0] <= x <= t[1]), None)
                if not r or r[1] - r[0] <= 300:
                    break
                top += 1
            box = (lo, top)
            break
    roof = int(y1)
    while roof < 1000 and not mask[1000 - roof][int(x)]:
        roof += 1
    dot = []
    for y in range(int(y0), int(y1) + 1):
        rs = O.runs(mask[1000 - y])
        dot += [(y, a, b) for a, b in rs[1:-1] if x0 <= a and b <= x1]
    return box, roof, dot


@op("roofBar")
def op_roof_bar(ctx, font, spec, source_half):
    """食 머리의 丶 을 지우고 人 아래 一 을 그린다 — 다른 소스 食 의 몫을 배워.

    편수자료의 篒 은 竹 아래 食 의 머리가 人 + 一 이다. 이 글자는 SC 에만 있고 SC 는
    人 + 丶 이다. Plex TC 의 食 이 人 + 一 이라 거기서 잰다 — 一 의 가운데가 상자
    윗변 위에서 人 꼭대기 아랫변까지의 몇 몫인지, 一 의 굵기, 一 끝과 人 다리 사이
    틈 (가운데 줄에서). 받는 글자에는 그 몫의 높이에 제 상자 윗변 굵기로 一 을
    그리고, 양끝은 一 윗변 높이 (다리가 기울어 가장 좁은 줄) 의 人 다리 안변에서
    같은 틈만큼 띄운다.

        {"op": "roofBar", "from": "IBM-Plex-Sans-TC/IBMPlexSansTC-{cjkSrc}.ttf",
         "fromCp": "98df", "fromAt": [0.30, 0.56, 0.70, 0.78],
         "at": [0.40, 0.42, 0.60, 0.555], "x": 0.5, "cps": ["7bd2"]}

    `at`/`fromAt` 丶 (또는 一) 이 드는 네모 — 위끝은 人 꼭대기보다 아래.
    `gapLike` 틈만 다른 글자에서 잰다 — {"from": 글꼴, "glyph": 이름, "x": 세로줄 (飾 vari2 는 0.25)}.
              一 윗변 줄에서 人 다리 안변까지. 篒 은 飼 에 넣은 飾 vari2 의 飠 처럼
              一 을 다리 가까이까지 (Regular 2, 굵으면 붙는다).
    `overlap` 이 굵기들에선 一 끝을 갓(人 다리) 에 겹친다 — 끝의 위 절반만. 가운데
              줄에서 다리 안변에 끝이 닿게 한다 (다리가 기울어 위는 묻히고 아래는 뜬다).
    `floor`   {"font": 글꼴, "from": 몫을 잴 글꼴, "weights": [...]} — 이 굵기들에선 一
              너비가 `font` (겹치는 굵기, 篒 은 Medium — 몫도 TC Medium 에서) 의 一 너비보다 짧으면 가운데를 두고 그만큼 늘인다.
              가는 굵기의 一 이 굵은 굵기의 것보다 짧지 않게. 篒 은 Medium 부터 ("Medium", "SemiBold", "Bold").
    丶 은 `at` 안 가운데 토막들의 상자에 든 점을 윤곽에서 지워 없앤다 (상자 윗변에
    붙은 이음점도 함께 — 남은 이웃이 윗변을 곧게 잇는다).
    """
    from .ops import _PRISTINE, _open_pristine
    def pristine(tmpl):
        path = ctx.path(tmpl)
        f = _PRISTINE.get(path)
        if f is None:
            f = _PRISTINE[path] = _open_pristine(path)
        return f

    def share_of(donor):
        dg = donor[cp(spec["fromCp"])]
        dm = O.part_mask(list(dg.foreground))
        dw = dg.width or 1000
        dbox, droof, _ = _roof_frame(dm, spec["x"] * dw, _in_box(ctx, dg, spec["fromAt"]))
        bar = next(t for t in sorted(_col_runs(dm, spec["x"] * dw)) if dbox[1] < t[0] < droof)
        return ((bar[0] + bar[1]) / 2 - dbox[1]) / (droof - dbox[1]), dm, dg, bar

    share, dm, dg, bar = share_of(pristine(spec["from"]))
    dw = dg.width or 1000
    mid = int((bar[0] + bar[1]) / 2)
    rs = O.runs(dm[1000 - mid])
    k = next(i for i, t in enumerate(rs) if t[0] <= spec["x"] * dw <= t[1])
    gap = 0 if k in (0, len(rs) - 1) else ((rs[k][0] - rs[k - 1][1]) + (rs[k + 1][0] - rs[k][1])) / 2
    if "gapLike" in spec:
        # 틈만 다른 글자에서 — 一 윗변 줄에서 人 다리 안변까지 (붙었으면 0)
        gl = spec["gapLike"]
        gpath = ctx.path(gl["from"])
        gf = _PRISTINE.get(gpath)
        if gf is None:
            gf = _PRISTINE[gpath] = _open_pristine(gpath)
        gg = gf[gl["glyph"]]
        gm = O.part_mask(list(gg.foreground))
        gx = gl["x"] * (gg.width or 1000)
        gap = 0                                         # 떠 있는 一 이 없으면 다리에 붙었다
        for lo, hi in sorted(_col_runs(gm, gx), key=lambda t: -t[0])[1:2]:     # [0] 은 人 꼭대기, [1] 이 一
            rs = O.runs(gm[1000 - (hi - 1)])
            k = next(i for i, t in enumerate(rs) if t[0] <= gx <= t[1])
            if 0 < k < len(rs) - 1:
                gap = ((rs[k][0] - rs[k - 1][1]) + (rs[k + 1][0] - rs[k][1])) / 2
                break
    def plan(glyph, overlap, share):
        """丶 을 지운 윤곽과 一 자리 — (keep, 丶 상자, cy, t, left, right) 또는 None."""
        cs = list(glyph.foreground)
        w = glyph.width or 1000
        x = spec["x"] * w
        mask = O.part_mask(cs)
        box, roof, dot = _roof_frame(mask, x, _in_box(ctx, glyph, spec["at"]))
        if box is None or not dot:
            return None
        ax0 = min(a for _, a, _ in dot) - 2
        ax1 = max(b for _, _, b in dot) + 2
        ay0, ay1 = box[1] - 2, max(y for y, _, _ in dot) + 2
        keep = []
        for c in cs:
            nc = fontforge.contour()
            nc.is_quadratic = c.is_quadratic
            for p in c:
                if not (ax0 <= p.x <= ax1 and ay0 <= p.y <= ay1):
                    nc += fontforge.point(p.x, p.y, p.on_curve)
            if len(nc) >= 3:
                nc.closed = True
                keep.append(nc)
        t = box[1] - box[0]
        cy = box[1] + share * (roof - box[1])
        rest = O.part_mask(keep)
        if overlap:
            # 갓과 겹친다 — 一 끝의 위 절반만. 가운데 줄에서 다리 안변에 끝이 닿는다
            row = O.runs(rest[1000 - int(cy)])
            left = max(b for a, b in row if b < x)
            right = min(a for a, b in row if a > x)
        else:
            row = O.runs(rest[1000 - int(cy + t / 2)])  # 다리가 기울어 윗변 줄이 가장 좁다
            left = max(b for a, b in row if b < x) + gap
            right = min(a for a, b in row if a > x) - gap
        return keep, (ax0, ax1, ay0, ay1), cy, t, left, right

    # 가는 굵기의 一 이 굵은 굵기의 것보다 짧지 않게 — `floor` 굵기의 一 너비를 바닥으로
    floor = None
    fl = spec.get("floor")
    if fl and ctx.style["name"] in fl["weights"]:
        ff_ = pristine(fl["font"])
        fshare = share_of(pristine(fl["from"]))[0]          # 그 굵기의 몫으로
        for code in (cp(c) for c in spec["cps"]):
            got = plan(ff_[code], True, fshare) if code in ff_ else None
            if got:
                floor = got[5] - got[4]
    done = []
    for glyph in selected_glyphs(font, spec):
        got = plan(glyph, ctx.style["name"] in spec.get("overlap", []), share)
        if got is None:
            print("roofBar: %s 상자 윗변이나 丶 을 못 찾았다" % glyph.glyphname)
            continue
        keep, (ax0, ax1, ay0, ay1), cy, t, left, right = got
        if floor and right - left < floor:
            mid = (left + right) / 2
            left, right = mid - floor / 2, mid + floor / 2
        piece = _rect_contour(keep, round(left), round(right), round(cy - t / 2), round(cy - t / 2) + t, -1)   # 시계방향 = 칠함
        relay(glyph, [keep, [piece]])
        done.append("%s 丶 (%d..%d, %d..%d) 지움 · 一 y%d t%d x%d-%d (너비 %d)" % (
            glyph.glyphname, ax0, ax1, ay0, ay1, round(cy), t, left, right, right - left))
    print("roofBar: 몫 %.3f 틈 %d" % (share, gap))
    if done:
        print("roofBar: %s" % "; ".join(done))


@op("placeStem")
def op_place_stem(ctx, font, spec, source_half):
    """떠 있는 짧은 세로획 하나를 다시 놓는다 — x 는 기증자 안의 자리, 위아래는 옆 口.

    姬 의 방을 巸 의 𦣝 으로 바꾸고 잘라 벌리면 (swapSide fit="cut") 칼선이 안쪽
    세로획 왼쪽을 지나 획이 오른쪽으로 밀린다. 세로획을 기증자에서 바로 왼쪽 먹
    (𦣝 의 왼쪽 세로획) 의 왼끝에서 떨어진 거리에 `dx` 를 더해 놓고, 위아래 끝은
    오른쪽 口 의 바깥 높이에 맞춘다 — 세로획 오른쪽으로 가며 처음 만나는, 위아래
    가로획에 닿지 않는 긴 세로 토막 (口 의 오른 벽) 의 두 끝. 굵은 쪽은 口 의 벽이
    바깥 가로획과 붙어 벽 두께를 따로 잴 수 없어 이렇게 잰다.

        {"op": "placeStem", "at": [0.55, 0.15, 0.75, 0.65],
         "like": "5df8", "likeAt": [0.15, 0.15, 0.32, 0.65], "dx": 26, "cps": ["59ec"]}

    `at`/`likeAt` 세로획 윤곽을 고르는 네모 (온전히 드는 윤곽).
    `dx`       기증자 안의 자리에서 더 옮길 몫 (모든 굵기에 같게 — Regular 획 폭의 절반).
    `center`   참이면 x 를 왼쪽 세로획 오른변과 오른쪽 먹 (口 벽의 왼끝) 사이 긴 흰
               칸의 가운데로 — `like`·`dx` 는 쓰지 않는다.
    """
    def inside(g, box):
        x0, y0, x1, y1 = _in_box(ctx, g, box)
        return [k for k, c in enumerate(g.foreground)
                if x0 <= O.box(c)[0] and O.box(c)[1] <= x1 and y0 <= O.box(c)[2] and O.box(c)[3] <= y1]

    def frame_left(g, k):
        # 세로획 가운데 높이 줄에서 바로 왼쪽 먹 토막 (𦣝 의 왼쪽 세로획) 의 왼끝
        s = O.box(g.foreground[k])
        m = O.part_mask([c for i, c in enumerate(g.foreground) if i != k])
        row = O.runs(m[1000 - int((s[2] + s[3]) / 2)])
        return max((a for a, b in row if b < s[0]), default=None)

    like = donor_glyph(font, spec, "like")
    lk = inside(like, spec["likeAt"])
    if len(lk) != 1:
        print("placeStem: %s 에서 세로획 %d 개 — 건너뜀" % (like.glyphname, len(lk)))
        return
    off = O.box(like.foreground[lk[0]])[0] - frame_left(like, lk[0]) + spec.get("dx", 0)
    done = []
    for glyph in selected_glyphs(font, spec):
        k = inside(glyph, spec["at"])
        if len(k) != 1:
            print("placeStem: %s 세로획 %d 개 — 건너뜀" % (glyph.glyphname, len(k)))
            continue
        cs = list(glyph.foreground)
        s = O.box(cs[k[0]])
        rest = [c for i, c in enumerate(cs) if i != k[0]]
        m = O.part_mask(rest)
        top = max(O.box(c)[3] for c in rest)
        wall = None
        for x in range(int(s[1]) + 1, int(glyph.width or 1000)):
            wall = next(((lo, hi) for lo, hi in _col_runs(m, x)
                         if hi - lo > 150 and lo > s[2] - 120 and hi < top - 120), None)
            if wall:
                break
        if wall is None:
            print("placeStem: %s 口 의 오른 벽을 못 찾았다" % glyph.glyphname)
            continue
        w = s[1] - s[0]
        if spec.get("center"):
            # 왼쪽 세로획 오른변과 오른쪽 먹 (口 벽의 왼끝) 사이 긴 흰 칸의 가운데
            lefts, rights = [], []
            for y in range(wall[0], wall[1] + 1):
                row = O.runs(m[1000 - y])
                lefts += [b for a, b in row if b < s[0]][-1:]
                rights += [a for a, b in row if a > s[1]][:1]
            x0 = (max(lefts) + min(rights)) / 2 - w / 2
        else:
            x0 = frame_left(glyph, k[0]) + off
        bar = _rect_contour(cs, round(x0), round(x0 + w), wall[0], wall[1], O._turn(cs[k[0]]))
        relay(glyph, [rest + [bar]])
        done.append("%s x %d→%d y %d..%d" % (glyph.glyphname, s[0], x0, wall[0], wall[1]))
    if done:
        print("placeStem: %s" % "; ".join(done))


@op("dotsToStems")
def op_dots_to_stems(ctx, font, spec, source_half):
    """띠 안의 점들을 지우고, 점마다 그 가운데 x 에 위아래 획을 잇는 곧은 세로획을 긋는다.

    편수자료의 囍 는 喜 의 口 와 가로획 사이 丷 이 곧은 두 획이다. Plex 는 밖으로
    벌어진 점이고 굵기마다 위아래에 닿거나 떠 있다. 점은 `at` 띠 안의 먹 토막을
    x 로 이어 모은 덩이. 위아래 (가로획 윗변·口 아랫변) 는 가장 가까운 이웃 점과의
    사이 세로줄에서 잰다 — 굵으면 점 자리 세로줄은 셋을 한 토막으로 지난다. 그
    사이 띠에는 점뿐이라 띠 위·아래만 남겨 (clip_to) 점을 없앤다 (윤곽 점을 지우면
    가로획·口 와 한 윤곽인 굵기에서 남은 점이 엉뚱하게 이어진다).
    새 세로획은 굵기 = 띠 위 口 의 가장 가까운 세로벽 폭, 양끝은 `over` (12) 파고듦.

        {"op": "dotsToStems", "at": [0, 0.30, 1, 0.352], "single": true, "cps": ["56cd"]}

    `single` 이면 두 점마다 그 한가운데에 세로획 하나 — 가로획을 가로질러 위 口
    아랫변과 아래 口 윗변을 잇는다 (편수자료의 囍). `centerBar` 면 가로획을 두 口
    사이 한가운데로 옮긴다.

    `at` 의 위아래는 점만 지나고 가로획·口 는 지나지 않게 잡는다.
    """
    over = spec.get("over", 12)
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = list(glyph.foreground)
        x0, y0, x1, y1 = _in_box(ctx, glyph, spec["at"])
        mask = O.part_mask(cs)
        dots = []                                   # [x0, x1, y0, y1]
        for y in range(int(y0), int(y1) + 1):
            for a, b in O.runs(mask[1000 - y]):
                if not (x0 <= a and b <= x1):
                    continue
                d = next((d for d in dots if a <= d[1] + 3 and b >= d[0] - 3), None)
                if d:
                    d[0], d[1], d[2], d[3] = min(d[0], a), max(d[1], b), min(d[2], y), max(d[3], y)
                else:
                    dots.append([a, b, y, y])
        if not dots:
            print("dotsToStems: %s 점을 못 찾았다" % glyph.glyphname)
            continue
        # 점마다 위 (口 아랫변) 와 아래 (가로획 윗변) — 굵으면 점 자리 세로줄은 가로획·
        # 점·口 를 한 토막으로 지나므로, 가장 가까운 이웃 점과의 사이 세로줄에서 잰다
        dots.sort()
        ends = []
        for i, d in enumerate(dots):
            cx = (d[0] + d[1]) / 2
            nb = [e for j, e in enumerate(dots) if j != i]
            e = min(nb, key=lambda e: abs((e[0] + e[1]) / 2 - cx)) if nb else None
            rx = ((d[1] + e[0]) / 2 if e[0] > d[1] else (e[1] + d[0]) / 2) if e else cx
            runs = _col_runs(mask, rx)
            below = max((hi for lo, hi in runs if hi < y0), default=None)
            above = min((lo for lo, hi in runs if lo > y1), default=None)
            ends.append((cx, below, above, d))
        if any(lo is None or hi is None for _, lo, hi, _ in ends):
            print("dotsToStems: %s 위아래를 못 찾았다" % glyph.glyphname)
            continue
        # 가로획 윗변과 口 아랫변 사이 띠에는 점뿐이다 — 띠를 네모로 통째로 도려낸다.
        # 윤곽 점을 지우면 가로획·口 와 한 윤곽인 굵기에서 남은 점이 엉뚱하게 잇는다.
        blo = min(lo for _, lo, _, _ in ends) + 0.5
        bhi = max(hi for _, _, hi, _ in ends) - 0.5
        W = (glyph.width or 1000) + 100
        keep = clip_to(cs, [(-100, W, -400, blo), (-100, W, bhi, 1400)])   # keepOnly 와 같이 남길 것을 덮는다
        # 점이 붙던 이음매가 1 단위 턱으로 남는다 — 경계 근처 점을 그 윤곽에서 가장
        # 많이 쓰인 높이로 맞춘다
        from collections import Counter
        flat = []
        for c in keep:
            pts = list(c)
            for edge in (blo, bhi):
                ys = [round(p.y) for p in pts if abs(p.y - edge) <= 1.5]
                if len(ys) >= 2:
                    hy = Counter(ys).most_common(1)[0][0]
                    for p in pts:
                        if abs(p.y - edge) <= 1.5:
                            p.y = hy
            nc = fontforge.contour()
            nc.is_quadratic = c.is_quadratic
            for p in pts:
                nc += fontforge.point(p.x, p.y, p.on_curve)
            nc.closed = True
            flat.append(nc)
        keep = flat
        rest = O.part_mask(keep)
        if spec.get("single"):
            # 두 점마다 그 한가운데에 하나 — 가로획을 가로질러 아래 口 윗변까지
            pairs = [ends[i:i + 2] for i in range(0, len(ends) - 1, 2)]
            ends = []
            for (ax, alo, ahi, _), (bx, blo_, bhi_, _) in pairs:
                cx = (ax + bx) / 2
                runs = _col_runs(rest, cx)
                bar = max((r for r in runs if r[1] <= min(alo, blo_) + 1), key=lambda r: r[1], default=None)
                under = max((r for r in runs if bar and r[1] < bar[0]), key=lambda r: r[1], default=None)
                ends.append((cx, under[1] if under else None, min(ahi, bhi_), None))
            if spec.get("centerBar"):
                # 가로획을 위 口 아랫변과 아래 口 윗변 사이 한가운데로 — 점을 잘라 낸
                # 뒤엔 가로획이 따로 떨어진 윤곽이다
                moved = []
                for cx, lo, hi, _ in ends:
                    runs = _col_runs(rest, cx)
                    bar = max((r for r in runs if r[1] <= blo + 1), key=lambda r: r[1], default=None)
                    if bar is None or lo is None:
                        continue
                    dy = (lo + hi) / 2 - (bar[0] + bar[1]) / 2
                    for c in keep:
                        b0 = O.box(c)
                        if b0[0] <= cx <= b0[1] and bar[0] - 2 <= b0[2] and b0[3] <= bar[1] + 2 \
                                and id(c) not in moved:
                            c.transform(psMat.translate(0, dy))
                            moved.append(id(c))
                rest = O.part_mask(keep)
        new = []
        for cx, lo, hi, _ in ends:
            # 굵기 — 띠 위 口 에서 이 x 에 가장 가까운 세로벽. 口 아랫벽을 벗어나
            # 좁은 토막이 나오는 줄까지 올라가서 잰다 (굵으면 아랫벽이 두껍다)
            wall = None
            for y in range(int(hi) + 10, int(hi) + 200, 5):
                row = [t for t in O.runs(rest[1000 - y]) if t[1] - t[0] < 200]
                if row:
                    wall = min(row, key=lambda t: abs((t[0] + t[1]) / 2 - cx))
                    break
            if lo is None or hi is None or wall is None:
                print("dotsToStems: %s x%d 위아래를 못 찾았다" % (glyph.glyphname, cx))
                continue
            w = wall[1] - wall[0]
            new.append(_rect_contour(keep, round(cx - w / 2), round(cx + w / 2),
                                     round(lo - over), round(hi + over), -1))
        relay(glyph, [keep, new])
        done.append("%s 점 %d → %s" % (glyph.glyphname, len(dots),
                    " ".join("x%d" % e[0] for e in ends)))
    if done:
        print("dotsToStems: %s" % "; ".join(done))


@op("apexFlag")
def op_apex_flag(ctx, font, spec, source_half):
    """人 꼭대기에서 왼쪽으로 가로선을 단다 — 편수자료의 兪 머리 (入 처럼 꺾인 꼭대기).

    선의 윗변은 人 꼭대기 윗변, 굵기와 왼끝은 그 아래 一 의 것. 굵은 굵기에서는 一 이
    人 다리와 붙어 따로 고를 수 없으므로 꼭대기 아래 흰 세모 (구멍) 의 왼끝과, 그
    아래 세로줄에서 잰 一 의 두께를 쓴다.

        {"op": "apexFlag", "at": [0.45, 0.45, 0.80, 0.72], "cps": ["7652"]}

    `at` 人 (꼭대기·一·흰 세모) 이 드는 네모. 꼭대기는 그 안 가장 높은 먹.
    `like` 를 주면 길이를 그 글자 (愈) 의 꼭대기 선처럼 — 선 길이가 人 지붕 폭의 몇
         몫인지 (Regular 0.401) 재어 같은 몫으로 (JP 愈·兪·喩 는 꼭대기 선이 이미 있다).
    `gap` 을 주면 왼끝을 그 높이에서 왼쪽으로 처음 만나는 먹 바로 앞 `gap` 까지 늘린다
         (廐 의 旡 가로획과 같이 26 — Regular 획 굵기의 절반).
    """
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = list(glyph.foreground)
        x0, y0, x1, y1 = _in_box(ctx, glyph, spec["at"])
        mask = O.part_mask(cs)
        # 꼭대기 — 네모 안 가장 높은 먹 줄
        top = None
        for y in range(int(y1), int(y0), -1):
            r = [t for t in O.runs(mask[1000 - y]) if t[0] >= x0 and t[1] <= x1]
            if r:
                top, ax = y, (r[0][0] + r[0][1]) / 2
                break
        if top is None:
            print("apexFlag: %s 꼭대기를 못 찾았다" % glyph.glyphname)
            continue
        inside = [c for c in cs if x0 <= O.box(c)[0] and O.box(c)[1] <= x1
                  and y0 <= O.box(c)[2] and O.box(c)[3] <= top - 5]
        bars = [c for c in inside if c.isClockwise() and O.box(c)[1] - O.box(c)[0] > 150]
        holes = [c for c in inside if not c.isClockwise()]
        if bars:
            b = O.box(bars[0])
            left, t = b[0], b[3] - b[2]
        elif holes:
            h = O.box(holes[0])
            left = h[0]
            under = [r for r in _col_runs(mask, ax) if r[1] <= h[2] + 1]
            if not under:
                print("apexFlag: %s 一 을 못 쟀다" % glyph.glyphname)
                continue
            t = max(under, key=lambda r: r[1])
            t = t[1] - t[0]
        else:
            print("apexFlag: %s 一 을 못 찾았다" % glyph.glyphname)
            continue
        if "like" in spec:
            # 같은 글꼴 愈 의 人 꼭대기 선 — 선 길이가 人 지붕 폭의 몇 몫인가. 같은 몫으로
            # 이 글자 지붕 폭에 맞춰 꼭대기에서 왼쪽으로 긋는다.
            lg = donor_glyph(font, spec, "like")
            lcs = list(lg.foreground)
            roof_l = max(lcs, key=lambda c: (O.box(c)[3], O.box(c)[1] - O.box(c)[0]))
            rb = O.box(roof_l)
            row = O.runs(O.part_mask([roof_l])[1000 - int(rb[3] - 6)])
            share = (max(b for a, b in row) - min(a for a, b in row)) / (rb[1] - rb[0])
            mine = max((c for c in cs if O.box(c)[0] <= ax <= O.box(c)[1]
                        and O.box(c)[2] <= top <= O.box(c)[3] + 1 and O.box(c)[3] < top + 60),
                       key=lambda c: O.box(c)[1] - O.box(c)[0])
            mb = O.box(mine)
            left = ax - share * (mb[1] - mb[0])
        if "gap" in spec:
            # 廐 의 旡 가로획처럼 — 그 높이에서 왼쪽으로 처음 만나는 먹 바로 앞 `gap` 까지
            ends = []
            for y in range(int(top - t), int(top) + 1):
                ends += [b for a, b in O.runs(mask[1000 - y]) if b < left]
            if ends:
                left = max(ends) + spec["gap"]
        # 오른끝 — 선 아랫변 줄에서 人 안쪽 흰 칸이 시작하는 자리 (왼 다리 안변) 까지만.
        # 꼭대기 가운데까지 그으면 아래쪽이 人 안으로 삐져나온다.
        right = ax
        for y in range(int(top - t), int(top) + 1):
            row = O.runs(mask[1000 - y])
            lefts = [b for a, b in row if a <= ax <= b]
            if not lefts:                       # 이 줄은 꼭대기 아래 흰 칸을 지난다
                right = min(right, max((b for a, b in row if b < ax), default=right))
        piece = _rect_contour(cs, round(left), round(right), top - t, top, -1)
        relay(glyph, [cs, [piece]])
        done.append("%s 꼭대기 (%d,%d) %d..%d 굵기 %d" % (glyph.glyphname, ax, top, left, right, t))
    if done:
        print("apexFlag: %s" % "; ".join(done))


@op("placeDots")
def op_place_dots(ctx, font, spec, source_half):
    """빈 月 안에 다른 글자 (愈) 의 점 둘을 그 몫대로 놓는다 — 흰 칸 가운데에.

    月 안 흰 칸은 왼 다리 안변 ~ 오른 다리 안변, 윗 가로획 아랫변 ~ 갈고리 윗변이다
    (오른 다리 바로 왼쪽 세로줄에서 위아래를 잰다). 기증자 흰 칸 안에서 점들의 상자가
    차지하는 몫을 재어, 이 글자 흰 칸에 같은 몫의 자리 가운데에 넣는다. 굵히지 않는다
    — 가로세로 같은 비율로 줄여 그 자리에 들어갈 만큼만 (굵은 굵기에서 점을 획 굵기로
    키우면 칸을 메운다).

        {"op": "placeDots", "at": [0.30, 0.14, 0.66, 0.48], "like": "6108",
         "likeAt": [0.10, 0.17, 0.52, 0.57], "cps": ["7652"]}

    `at`/`likeAt` 月 이 드는 네모. 기증자에서는 그 안 흰 칸에 온전히 드는 윤곽이 점이다.
    `posLike` 점마다 가운데를 그 글자 (愈) 의 月 흰 칸 안 두 점 자리 몫에 놓는다
              (`posLikeAt` 은 그 月 네모) — 愈 처럼 위아래로 고르게 나뉜다.
    `dotsAt`  점을 고르는 네모 — `split` 과 함께 주면 점이 테두리에 붙은 굵기는 가는
              굵기를 안내로 가른다 (`likeGuide` 는 안내 글리프 이름, 癒 는 자기 jp78 의 점).
    """
    def inner(m, box):
        x0, y0, x1, y1 = box
        ym = int((y0 + y1) / 2)
        rs = [r for r in O.runs(m[1000 - ym]) if r[1] > x0 and r[0] < x1]
        if len(rs) < 2:
            return None
        il, ir = rs[0][1], rs[-1][0]
        col = sorted(_col_runs(m, ir - 3), key=lambda t: t[0])
        above = [t for t in col if t[0] > ym]
        below = [t for t in col if t[1] < ym]
        if not above or not below:
            return None
        return il, ir, below[-1][1], above[0][0]

    like = donor_glyph(font, spec, "like")
    lcs = list(like.foreground)
    lbox = _in_box(ctx, like, spec["likeAt"])
    if "dotsAt" in spec:
        # 점을 네모로 고르고, 테두리에 붙은 굵기는 가는 굵기를 안내로 목에서 가른다
        from .ops import isolate_part
        em = ctx.em_ascent + ctx.em_descent
        got = isolate_part(ctx, like, spec.get("likeGuide", like.unicode), spec["dotsAt"],
                           spec["split"], em)
        if not got:
            print("placeDots: %s 에서 점을 못 갈랐다" % like.glyphname)
            return
        dots, rest_ = [c.dup() for c in got[0]], [c.dup() for c in got[1]]
        lin = inner(O.part_mask(rest_), lbox)
    else:
        cand = [c for c in lcs if lbox[0] <= O.box(c)[0] and O.box(c)[1] <= lbox[2]
                and lbox[1] <= O.box(c)[2] and O.box(c)[3] <= lbox[3]]
        # 점을 뺀 채로 흰 칸을 잰다 (점이 흰 칸 가운데 줄에 걸린다) — 좁은 윤곽이 점
        m_frame = O.part_mask([c for c in lcs if c not in cand or O.box(c)[1] - O.box(c)[0] > 0.6 * (lbox[2] - lbox[0])])
        lin = inner(m_frame, lbox)
        dots = [c for c in cand if lin and lin[0] < O.box(c)[0] and O.box(c)[1] < lin[1]
                and lin[2] < O.box(c)[2] and O.box(c)[3] < lin[3]]
    if lin is None:
        print("placeDots: %s 月 흰 칸을 못 쟀다" % like.glyphname)
        return
    if not dots:
        print("placeDots: %s 에서 점을 못 찾았다" % like.glyphname)
        return
    db = O.bbox(dots)
    LW, LH = lin[1] - lin[0], lin[3] - lin[2]
    fr = ((db[0] - lin[0]) / LW, (db[1] - lin[0]) / LW, (db[2] - lin[2]) / LH, (db[3] - lin[2]) / LH)
    mt = O.part_mask([c.dup() for c in dots])
    ws = []
    for y in range(int(db[2]) + 10, int(db[3]) - 10, 6):
        ws += [b - a for a, b in O.runs(mt[1000 - y])]
    t = sorted(ws)[len(ws) // 2] if ws else 0
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = list(glyph.foreground)
        gin = inner(O.part_mask(cs), _in_box(ctx, glyph, spec["at"]))
        if gin is None:
            print("placeDots: %s 月 흰 칸을 못 쟀다" % glyph.glyphname)
            continue
        GW, GH = gin[1] - gin[0], gin[3] - gin[2]
        tx0, tx1 = gin[0] + fr[0] * GW, gin[0] + fr[1] * GW
        ty0, ty1 = gin[2] + fr[2] * GH, gin[2] + fr[3] * GH
        # 굵히지 않는다 — 가로세로 같은 몫으로 줄여 그 자리 가운데에 (빈 칸에 들어갈 만큼만)
        sx = sy = min((tx1 - tx0) / (db[1] - db[0]), (ty1 - ty0) / (db[3] - db[2]))
        out = []
        for c in dots:
            c = c.dup()
            c.transform(psMat.translate(-(db[0] + db[1]) / 2, -(db[2] + db[3]) / 2))
            c.transform(psMat.scale(sx, sy))
            c.transform(psMat.translate((tx0 + tx1) / 2, (ty0 + ty1) / 2))
            out.append(c)
        if "posLike" in spec and len(out) == 2:
            # 점마다 가운데를 그 글자 (愈) 의 月 흰 칸 안 두 점 자리 몫에 — 愈 처럼 고르게
            pl = donor_glyph(font, spec, "posLike")
            pcs = list(pl.foreground)
            pbox = _in_box(ctx, pl, spec["posLikeAt"])
            pc = [c for c in pcs if pbox[0] <= O.box(c)[0] and O.box(c)[1] <= pbox[2]
                  and pbox[1] <= O.box(c)[2] and O.box(c)[3] <= pbox[3]]
            narrow = [c for c in pc if O.box(c)[1] - O.box(c)[0] <= 0.6 * (pbox[2] - pbox[0])]
            pin = inner(O.part_mask([c for c in pcs if c not in narrow]), pbox)
            pd = sorted([c for c in narrow if pin and pin[0] < O.box(c)[0] and O.box(c)[1] < pin[1]
                         and pin[2] < O.box(c)[2] and O.box(c)[3] < pin[3]], key=lambda c: O.box(c)[2])
            if pin and len(pd) == 2:
                PW, PH = pin[1] - pin[0], pin[3] - pin[2]
                for mine_, ref in zip(sorted(out, key=lambda c: O.box(c)[2]), pd):
                    rb, mb = O.box(ref), O.box(mine_)
                    fx = ((rb[0] + rb[1]) / 2 - pin[0]) / PW
                    fy = ((rb[2] + rb[3]) / 2 - pin[2]) / PH
                    mine_.transform(psMat.translate(gin[0] + fx * GW - (mb[0] + mb[1]) / 2,
                                                    gin[2] + fy * GH - (mb[2] + mb[3]) / 2))
        relay(glyph, [cs, out])
        done.append("%s 점 %d..%d · %d..%d (×%.2f×%.2f)" % (glyph.glyphname, tx0, tx1, ty0, ty1, sx, sy))
    if done:
        print("placeDots: %s" % "; ".join(done))


@op("dropPart")
def op_drop_part(ctx, font, spec, source_half):
    """네모로 고른 성분을 지운다 — 붙은 굵기는 가는 굵기를 안내로 목에서 갈라.

    癒.jp78 의 月 안 점 둘은 Text 까지 따로 떨어진 윤곽이고 Medium·SemiBold 는 하나,
    Bold 는 둘 다 月 테두리에 붙는다. 네모로 오리지 않는다 — 네모는 고르는 자리일
    뿐이고, 떨어진 굵기는 그 윤곽을 지우며, 붙은 굵기는 `ops.isolate_part` 가 같은
    글리프의 가는 굵기를 안내로 목에서 가른 뒤 그 조각을 버린다.

        {"op": "dropPart", "at": [[0.37, 0.19, 0.56, 0.41]],
         "split": "IBM-Plex-Sans-JP/IBMPlexSansJP-{cjkSrc}.ttf",
         "guideAs": "uni7652.jp78", "cps": ["7652"]}
    """
    from .ops import isolate_part
    em = ctx.em_ascent + ctx.em_descent
    done = []
    for glyph in selected_glyphs(font, spec):
        guide = spec.get("guideAs", glyph.unicode)
        got = isolate_part(ctx, glyph, guide, spec["at"], spec["split"], em)
        if not got:
            print("dropPart: %s 에서 성분을 못 골랐다" % glyph.glyphname)
            continue
        part, rest = got[0], got[1]
        relay(glyph, [[c.dup() for c in rest]])
        done.append("%s 조각 %d 윤곽 지움" % (glyph.glyphname, len(part)))
    if done:
        print("dropPart: %s" % "; ".join(done))


@op("openFoot")
def op_open_foot(ctx, font, spec, source_half):
    """네모의 아랫변을 왼 기둥에서 떼어 卩 의 발처럼 연다.

    편수자료의 凞 는 巳 의 위 네모가 卩 처럼 생겼다 — 오른 세로획이 내려와 왼쪽으로
    짧게 꺾이고 (발), 그 끝이 왼 기둥에 닿지 않는다. 같은 글꼴 癤 의 卩 에서 굵기마다
    잰다: 발 끝과 기둥 사이 틈이 안쪽 폭 (기둥 오른변 ~ 오른 세로획 안변) 의 몇 몫인지,
    발 끝이 아래로 갈수록 오른쪽으로 비스듬히 잘린 몫 (발 두께 대비).

        {"op": "openFoot", "at": [0.60, 0.45, 0.95, 0.80], "like": "7664",
         "likeAt": [0.64, -0.08, 0.95, 0.45], "cps": ["51de"]}

    `at`/`likeAt` 네모 (기둥·발·오른 세로획) 가 드는 자리. 발은 그 안에서 기둥 오른쪽
    먹 토막이 넓어지는 줄들 (오른 세로획과 이어진 가로 토막) 이다.
    `barAt`   뗄 가로획을 고르는 네모 — detachBar (side left) 의 `at`. 떼기는 박스로
              오리지 않고 detachBar 가 모서리 점에서 윤곽을 잇는다.
    """
    def measure(m, box):
        x0, y0, x1, y1 = box
        rows = []
        for y in range(int(y0), int(y1)):
            rs = [r for r in O.runs(m[1000 - y]) if r[1] > x0 and r[0] < x1]
            rows.append((y, rs))
        # 기둥 + 오른 세로획 두 토막인 줄 → 기둥 오른변 sr, 오른 세로획 안변 ri
        two = [(y, rs) for y, rs in rows if len(rs) == 2]
        if not two:
            return None
        sw = min(rs[0][1] - rs[0][0] for y, rs in two)
        sr = sorted(rs[0][1] for y, rs in two)[len(two) // 2]
        ri = sorted(rs[1][0] for y, rs in two)[len(two) // 2]
        # 발 (또는 아직 붙은 가로획) — 기둥 오른쪽 토막이 안쪽 폭의 절반보다 넓은 줄
        foot = [(y, rs) for y, rs in rows if rs and any(
            r[0] < (sr + ri) / 2 and r[1] >= ri for r in rs)]
        if not foot:
            return None
        # 가장 아래에 이어진 줄 묶음만 — 위 가로획도 같은 꼴로 걸린다
        foot.sort()
        grp = [foot[0]]
        for f_ in foot[1:]:
            if f_[0] != grp[-1][0] + 1:
                break
            grp.append(f_)
        ys = [y for y, _ in grp]
        return sr, ri, min(ys), max(ys), grp

    like = donor_glyph(font, spec, "like")
    lm = O.part_mask(list(like.foreground))
    got = measure(lm, _in_box(ctx, like, spec["likeAt"]))
    if not got:
        print("openFoot: %s 에서 卩 를 못 쟀다" % like.glyphname)
        return
    sr, ri, flo, fhi, foot = got
    def foot_left(rs):
        return min(r[0] for r in rs if r[1] >= ri and r[0] > sr - 1)
    top_l = foot_left([rs for y, rs in foot if y == fhi][0])
    bot_l = foot_left([rs for y, rs in foot if y == flo][0])
    share = (top_l - sr) / (ri - sr)
    slant = (bot_l - top_l) / max(1, fhi - flo)
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = list(glyph.foreground)
        m = O.part_mask(cs)
        g = measure(m, _in_box(ctx, glyph, spec["at"]))
        if not g:
            print("openFoot: %s 네모를 못 쟀다" % glyph.glyphname)
            continue
        gsr, gri, lo, hi, _ = g
        fx = gsr + share * (gri - gsr)
        # 박스로 오리지 않는다 — 가로획이 기둥에 붙는 두 모서리 점에서 윤곽을 이어
        # 떼는 detachBar 를 그대로 쓴다 (점으로 자른다)
        before = {(round(p.x), round(p.y)) for c in glyph.foreground for p in c}
        op_detach_bar(ctx, font, {"at": spec["barAt"], "gap": round(fx - gsr), "side": "left",
                                  "cps": ["%04x" % glyph.unicode]}, source_half)
        # 발 끝을 卩 처럼 비스듬히 — 새로 생긴 아래 끝점만 오른쪽으로
        dx = slant * (hi - lo)
        ex = round(gsr) + round(fx - gsr)
        lay = fontforge.layer()
        lay.is_quadratic = glyph.foreground.is_quadratic
        for c in glyph.foreground:
            nc = fontforge.contour()
            nc.is_quadratic = c.is_quadratic
            for p in c:
                new_pt = (round(p.x), round(p.y)) not in before
                x = p.x + dx if new_pt and abs(p.x - ex) < 1.5 and p.y < (lo + hi) / 2 else p.x
                nc += fontforge.point(x, p.y, p.on_curve)
            nc.closed = True
            lay += nc
        w_ = glyph.width
        glyph.foreground = lay
        glyph.width = w_
        done.append("%s 발 %d..%d (틈 몫 %.2f) y%d..%d 비스듬 %d" % (
            glyph.glyphname, fx, gri, share, lo, hi, round(dx)))
    if done:
        print("openFoot: %s" % "; ".join(done))


@op("graftNarrow")
def op_graft_narrow(ctx, font, spec, source_half):
    """옆 성분을 가운데 잘라 좁히고, 비운 자리에 기증자의 성분을 붙인다.

    편수자료의 癒 는 兪 의 오른쪽이 刂 가 아니라 巜 다. 같은 글꼴 愈 의 巜 는 癒 의
    刂 자리보다 넓고 (365 · 221) 높다 (401 · 307). 刂 를 지우고 巜 를 오른끝·아래끝을
    刂 자리에 대어 붙이되, 높이는 세로로만 줄여 맞춘다 — 巜 두 획은 '<' 로 꺾여 곧은
    토막이 없어 잘라 줄일 수 없고, 거의 서 있어 세로로만 줄이면 가로 두께는 그대로다.
    그 왼쪽 月 은 가로획만 잘라 (narrow_across) 기증자에서의 틈만큼 비운다.

        {"op": "graftNarrow", "drop": [0.68, 0.14, 0.93, 0.48],
         "narrow": [0.30, 0.14, 0.63, 0.48], "like": "6108",
         "likeAt": [0.53, 0.15, 0.92, 0.59], "likeLeft": [0.12, 0.17, 0.52, 0.57],
         "cps": ["7652"]}

    `drop`    지울 성분 (네모에 온전히 드는 윤곽) — 그 상자가 붙일 자리.
    `narrow`  좁힐 성분 (네모에 온전히 드는 윤곽, 구멍 포함).
    `likeAt`  기증자에서 붙일 성분, `likeLeft` 그 왼쪽 성분 — 둘 사이 틈을 잰다.
    `split`   소스 글꼴 틀. 네모로 고른 윤곽 수가 가는 굵기와 다르면 (녹아붙었으면) 가는
              굵기를 안내로 가른다 — SemiBold 癒 의 月 은 心 의 점과, Bold 愈 의 巜 는
              心 의 점과 한 윤곽이다. 받는 글자가 이체자 복사본이면 `guideAs` 에 그
              이체자 이름 (uni7652.jp78) 을 적어 그 가는 굵기를 안내로 삼는다.
    `even`    두 성분의 너비를 같게. 붙일 성분이 획 둘 (巜) 이면 획마다 세로로만 줄이고
              두 획 사이 틈을 좁혀 폭을 맞춘다. 틈이 `clear` (27, Regular 획 굵기의 절반)
              보다 좁아져야 하면 그만큼 획의 꺾인 폭을 줄이고, 줄어든 가로 두께는
              changeWeight 로 굵혀 되돌린다.
    `knifeShare` 좁힐 성분 왼끝에서 이 몫 안에서만 칼선을 찾는다 (月 은 0.5 — 오른
              세로획 아래 갈고리가 왼쪽으로 꺾여 들어와 그 자리를 자르면 끊긴다).
    `knifeAt` [몫, 몫] — 칼선을 그 구간에서만 찾는다 (癒.jp78 의 月 은 점 둘이 왼 기둥에
              붙어 오른쪽, 오른 기둥 바로 안에서 자른다: 0.72–0.80).
    `forceKnife` 몫 또는 `"stem"` — 가로변만 지나는 칼선이 없으면 그 자리에서 그대로
              자른다 (칼선 오른쪽 점만 옮긴다; 곡선이 그만큼 줄어든다). `"stem"` 은 오른
              다리 안변 바로 왼쪽 — 다리를 통째로 옮겨 굵기를 지킨다.
    `tall`    칼선이 지나도 되는 가로획 두께 한도 (성분 높이 대비, 기본 0.15) — 굵은
              굵기의 月 은 윗 가로획이 이보다 두껍다.
    """
    def inside(g, box):
        x0, y0, x1, y1 = _in_box(ctx, g, box)
        return [k for k, c in enumerate(g.foreground)
                if x0 <= O.box(c)[0] and O.box(c)[1] <= x1 and y0 <= O.box(c)[2] and O.box(c)[3] <= y1]

    from .ops import isolate_part
    em = ctx.em_ascent + ctx.em_descent

    def take(g, box, code):
        """네모에 드는 성분과 나머지 — 녹아붙었으면 (`split`) 가는 굵기를 안내로 가른다."""
        if "split" in spec:
            got = isolate_part(ctx, g, code, [box], spec["split"], em)
            if got:
                return [c.dup() for c in got[0]], [c.dup() for c in got[1]]
        k = inside(g, box)
        return ([g.foreground[i].dup() for i in k],
                [c.dup() for i, c in enumerate(g.foreground) if i not in k])

    def holder(cs, width):
        tmp = font.createChar(-1, "_graftNarrow_part")
        lay = fontforge.layer()
        lay.is_quadratic = font[0x20].foreground.is_quadratic if 0x20 in font else True
        for c in cs:
            lay += c
        tmp.foreground = lay
        tmp.width = width
        return tmp

    like = donor_glyph(font, spec, "like")
    lparts, _ = take(like, spec["likeAt"], like.unicode)
    lleft, _ = take(like, spec["likeLeft"], like.unicode)
    if not lparts or not lleft:
        print("graftNarrow: %s 에서 성분을 못 골랐다" % like.glyphname)
        return
    lb = O.bbox(lparts)
    gap = lb[0] - O.bbox(lleft)[1]
    done = []
    for glyph in selected_glyphs(font, spec):
        guide = spec.get("guideAs", glyph.unicode)   # 복사해 온 이체자면 그 이름 (가는 굵기 안내)
        ncs, rest1 = take(glyph, spec["narrow"], guide)
        tmp = holder(rest1, glyph.width)
        tmp.unicode = -1
        dcs, rest = take(tmp, spec["drop"], guide)
        font.removeGlyph(tmp)
        if not dcs or not ncs:
            print("graftNarrow: %s 지울 %d · 좁힐 %d — 건너뜀" % (glyph.glyphname, len(dcs), len(ncs)))
            continue
        slot = O.bbox(dcs)
        nb = O.bbox(ncs)
        H = slot[3] - slot[2]
        lw, lh = lb[1] - lb[0], lb[3] - lb[2]
        # `even` 이면 좁힐 성분과 붙일 성분의 너비를 같게 — 둘이 나눠 가질 폭의 반
        E = (slot[1] - nb[0] - gap) / 2 if spec.get("even") else lw

        def thick(cs_):
            m = O.part_mask([c.dup() for c in cs_])
            b = O.bbox(cs_)
            ws = []
            for y in range(int(b[2]) + 20, int(b[3]) - 20, 10):
                ws += [r[1] - r[0] for r in O.runs(m[1000 - y])]
            return sorted(ws)[len(ws) // 2] if ws else 0

        def make(cs_, sx, sy, d):
            b = O.bbox(cs_)
            out = []
            for c in cs_:
                c = c.dup()
                c.transform(psMat.translate(-b[1], -b[2]))
                c.transform(psMat.scale(sx, sy))
                out.append(c)
            if d > 0.5:
                tmp = font.createChar(-1, "_graftNarrow_tmp")
                lay = fontforge.layer()
                lay.is_quadratic = glyph.foreground.is_quadratic
                for c in out:
                    lay += c
                tmp.foreground = lay
                tmp.changeWeight(d, "CJK")
                out = [c.dup() for c in tmp.foreground]
                font.removeGlyph(tmp)
            return out

        strokes = sorted(lparts, key=lambda c: O.box(c)[0]) if spec.get("even") else [lparts]
        if spec.get("even") and len(strokes) == 2:
            # 획마다 따로 — 세로로만 자리 높이에 맞추고, 두 획 사이 틈을 좁혀 폭을 맞춘다.
            # 틈이 `clear` 보다 좁아져야 하면 그만큼 획의 꺾인 폭을 줄이고 줄어든 가로
            # 두께는 굵혀 되돌린다 (굵은 굵기는 획이 두꺼워 틈만으로 모자란다).
            t = thick([strokes[0]])
            sw = O.box(strokes[0])[1] - O.box(strokes[0])[0]
            cw = sw - t                                  # 꺾인 폭 (가운데 선)
            c_min = spec.get("clear", 27)
            cw2 = min(cw, E - 2 * t - c_min)
            c2 = E - 2 * t - cw2
            sx = (cw2 + t) / sw
            built = []
            for st in strokes:
                gw = gh = 0
                for _ in range(3):
                    one = make([st], (sw * sx - gw) / sw, (H - gh) / lh, t * (1 - (cw2 / cw if cw else 1)))
                    ob = O.bbox(one)
                    gw += (ob[1] - ob[0]) - sw * sx
                    gh += (ob[3] - ob[2]) - H
                built.append(one)
            # 오른 획을 자리 오른끝에, 왼 획은 두 획 사이 실제 틈이 c2 가 되게
            for c in built[1]:
                b1 = O.bbox(built[1]); c.transform(psMat.translate(slot[1] - b1[1], slot[2] - b1[2]))
            b0 = O.bbox(built[0])
            for c in built[0]:
                c.transform(psMat.translate(slot[1] - b0[1], slot[2] - b0[2]))
            now = O.clearance(built[0], built[1]) or 0
            for c in built[0]:
                c.transform(psMat.translate(-(c2 - now), 0))
            now = O.clearance(built[0], built[1])
            part = built[0] + built[1]
        else:
            part = make(lparts, 1.0, H / lh, 0)
        pb = O.bbox(part)                       # 오른끝·아래끝을 자리에 댄다
        for c in part:
            c.transform(psMat.translate(slot[1] - pb[1], slot[2] - pb[2]))
        sy = H / lh
        pl = O.bbox(part)[0]
        delta = (pl - gap) - nb[1]
        # 칼선은 왼쪽 몫 안에서만 — 月 오른 세로획 아래 갈고리가 왼쪽으로 꺾여 들어온다
        lo_x = nb[0]
        hi_x = nb[0] + spec.get("knifeShare", 1.0) * (nb[1] - nb[0])
        if "knifeAt" in spec:                   # 칼선을 찾을 몫 구간 (점 둘 오른쪽 등)
            lo_x = nb[0] + spec["knifeAt"][0] * (nb[1] - nb[0])
            hi_x = nb[0] + spec["knifeAt"][1] * (nb[1] - nb[0])
        narrowed, knife = O.narrow_across(ncs, delta, lo_x, hi_x,
                                          tall=spec.get("tall", 0.15))
        if narrowed is None and "forceKnife" in spec:
            # 가로변만 지나는 칼선이 없을 때 (SemiBold·Bold 癒.jp78 — 갈고리 윗변이 곡선)
            # 그 몫 자리에서 그대로 자른다 — 칼선 오른쪽 점만 옮겨 갈고리 곡선이 그만큼 준다
            if spec["forceKnife"] == "stem":
                # 오른 다리 안변 바로 왼쪽 — 비율로 잡으면 다리 안을 지나 다리가 얇아진다
                # (Bold 癒.jp78: 0.74 → 552 가 다리 549..638 안)
                mm = O.part_mask(ncs)
                row = O.runs(mm[1000 - int((nb[2] + nb[3]) / 2)])
                knife = max(a for a, b in row) - 2
            else:
                knife = nb[0] + spec["forceKnife"] * (nb[1] - nb[0])
            narrowed = []
            for c in ncs:
                c = c.dup()
                for p in c:
                    if p.x > knife:
                        p.x += delta
                narrowed.append(c)
        if narrowed is None:
            print("graftNarrow: %s 좁힐 칼선이 없다" % glyph.glyphname)
            continue
        relay(glyph, [rest, narrowed, part])
        done.append("%s 巜 ×%.2f · 月 %+d (칼선 %d)" % (glyph.glyphname, sy, round(delta), knife))
    if done:
        print("graftNarrow: %s" % "; ".join(done))


@op("drawYa")
def op_draw_ya(ctx, font, spec, source_half):
    """皀 의 아래 匕 를 지우고 ㅑ 꼴로 새로 그린다 — 白 왼쪽 세로선을 내리고 가로획 둘.

    편수자료의 癤 은 節 의 皀 아래가 ㅑ 꼴이다 (白 의 왼쪽 세로선이 그대로 내려가고
    오른쪽으로 짧은 가로획 둘). Plex JP 의 旣 호환 자형 uniFA42 가 이 꼴이다. 조각을
    떼어 오지 않고 `like` 의 비율만 재어 제 획 굵기로 새로 그린다.

        {"op": "drawYa", "like": "uniFA42", "likeCol": 0.30,
         "drop": [0.29, -0.06, 0.63, 0.18], "col": 0.45,
         "bottomAt": [0.64, -0.12, 0.73, 0.0], "cps": ["7664"]}

    `drop`     지울 匕 — 이 네모 안에 점이 가장 많은 윤곽.
    `col`      白 안의 가로획들을 세로로 가로지르는 x (글자 폭 비율). 匕 를 지운 뒤
               가장 아래 토막이 白 의 아랫변, 그 높이가 가로획 굵기다.
    `bottomAt` 세로선 아래 끝을 맞출 획 (癤 은 卩 의 세로선) — 네모 안 점의 가장 낮은 y.
    `like`     비율을 잴 글자. `likeCol` 로 白 아랫변과 가로획 둘을 재고, 세로선
               아래 끝은 白 아랫변의 왼끝에서 잰다. 가로획 둘의 가운데 높이는 白 아랫변에서 세로선
               끝까지를 1 로 한 몫, 오른끝은 白 오른변에서 白 폭에 대한 몫만큼 나간다.
    """
    like = donor_glyph(font, spec, "like")
    if like is None:
        print("drawYa: %s 이 없다" % spec.get("like"))
        return
    lcs = list(like.foreground)
    lm = O.part_mask(lcs)
    lw = like.width or 1000
    runs = _col_runs(lm, spec["likeCol"] * lw)
    t2, t1, bar = runs[0], runs[1], runs[2]                 # 아래 가로획, 위 가로획, 白 아랫변
    lx = spec["likeCol"] * lw

    def hit(y, m, x):                                     # 줄 y 에서 x 를 덮는 토막
        return next(t for t in O.runs(m[1000 - int(y)]) if t[0] <= x <= t[1])
    bl, br = hit((bar[0] + bar[1]) / 2, lm, lx)
    lbot = _col_runs(lm, bl + 3)[0][0]                    # 세로선 — 白 아랫변 왼끝에서
    span = bar[0] - lbot
    share = [(bar[0] - (t[0] + t[1]) / 2) / span for t in (t1, t2)]
    over = (hit((t1[0] + t1[1]) / 2, lm, lx)[1] - br) / (br - bl)
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = list(glyph.foreground)
        bx0, by0, bx1, by1 = _in_box(ctx, glyph, spec["drop"])
        k = max(range(len(cs)), key=lambda i: sum(
            1 for p in cs[i] if bx0 <= p.x <= bx1 and by0 <= p.y <= by1))
        rest = cs[:k] + cs[k + 1:]
        mask = O.part_mask(rest)
        w = glyph.width or 1000
        r = [t for t in _col_runs(mask, spec["col"] * w) if t[1] > by0]
        if not r:
            print("drawYa: %s 白 아랫변을 못 찾았다" % glyph.glyphname)
            continue
        b = r[0]
        th = b[1] - b[0]
        L, R = hit((b[0] + b[1]) / 2, mask, spec["col"] * w)
        # 白 안 흰 칸 높이에서 L 을 덮는 토막 — 왼쪽 세로선
        sl, sr = hit(b[1] + 4, mask, L + 2)
        x0, y0, x1, y1 = _in_box(ctx, glyph, spec["bottomAt"])
        bottom = min(p.y for c in rest for p in c if x0 <= p.x <= x1 and y0 <= p.y <= y1)
        hspan = b[0] - bottom
        right = R + over * (R - L)
        pieces = [(sl, bottom, sr, b[0] + 12)]
        ys = []
        for s in share:
            cy = b[0] - s * hspan
            pieces.append((sl, cy - th / 2, right, cy + th / 2))
            ys.append(round(cy))
        new = []
        for px0, py0, px1, py1 in pieces:
            c = fontforge.contour()
            c.is_quadratic = cs[0].is_quadratic
            for x, y in ((px0, py1), (px1, py1), (px1, py0), (px0, py0)):
                c += fontforge.point(round(x), round(y), True)
            c.closed = True
            new.append(c)
        relay(glyph, [rest, new])
        done.append("%s 세로 %d..%d ↓%d · 가로 %s 굵기 %d → %d" % (
            glyph.glyphname, sl, sr, bottom, ys, th, round(right)))
    if done:
        print("drawYa: %s" % "; ".join(done))


# --------------------------------------------------------------------------
# 떼어 옮기기
# --------------------------------------------------------------------------


@op("carvePart")
def op_carve_part(ctx, font, spec, source_half):
    """획 하나를 떼어 다른 자리에 옮겨 놓는다 — 붙어 있으면 **목에서 잘라서**.

    네모로 오려 내지 않는다. 오리면 자형에 없던 직선·사선 단면이 남는다. 맞붙은
    자리의 점 쌍(목)을 찾아 그 점끼리 이어 고리를 가르고, 이은 두 점은 본디 한
    점이던 꼭짓점이 삼각형으로 잘린 꼴이므로 두 변을 늘려 만나는 자리로 한 점을
    되살린다(`outline.carve_out` · `one_corner`). 그래서 단면이 본디 있던 점과
    변으로만 이루어진다. 가는 굵기에서 그 획이 이미 따로 된 윤곽이면 그대로
    가져온다 — 여덟 굵기가 한 길로 다뤄진다.

        {"op": "carvePart", "take": [0.04, 0.10, 0.37, 0.39],
         "drop": [0.08, 0.42, 0.31, 0.66], "up": 0.34, "cps": ["7fbd"]}

    羽 의 위 획은 Plex 에서 오른쪽 아래로 흐르는 점획이고 한국 자형은 아래 획과
    같은 삐침이다. 그래서 **제 아래 삐침**을 떼어 크기도 기울기도 손대지 않고
    똑바로 위로만 올려 위 획으로 쓴다 — 두 삐침이 같은 획이 된다.

      `from`   기증자 (코드포인트나 글리프 이름). 없으면 **제 글리프**에서 뗀다.
      `fromFont`  기증자가 다른 소스 글꼴에 있을 때 그 경로 틀 (`donor_font`).
      `take`   뗄 조각을 고를 네모 [x0, y0, x1, y1] (x 는 글자 폭, y 는 em 대비).
      `walk`   목을 찾는 대신 **가로 윗변에서 테두리를 훑어** 조각을 만든다
               (`{"bar": 네모, "roof": 네모}` · `_walk_piece`).
      `at`     목을 찾을 네모. 조각과 목이 떨어져 있을 때만 따로 준다 — 네모가
               «어느 쪽을 가질지» 와 «어디를 자를지» 두 몫을 겸하면 엉뚱한 목을 문다.
      `drop`   받는 쪽에서 버릴 조각을 고를 네모. 없으면 버리지 않고 얹는다.
      `up`     올릴 몫. 먹 키에 대한 비율이다 (羽 는 34% = 286).
      `to`     `"column"` 이면 조각의 **발을 기둥 위에 세운다** — 세로는 `bar` 로
               가리킨 가로획의 윗변에, 가로는 가장 가까운 기둥의 왼끝에 맞춘다.
               "drop" 이면 버린 조각이 있던
               자리의 위끝과 좌우 복판에 맞춘다 (크기는 그대로 둔다).
      `side`   목이 두 윤곽에 걸쳐 있을 때 어느 쪽 변을 조각의 옆선으로 삼는지.
      `near`   목으로 볼 두 점의 거리 상한 (기본 60). 사선 획은 단면이 굵기보다 길다.
      `weld`   놓은 뒤 조각의 가로획 끝을 남은 몸 속으로 밀어 넣는다 (`_weld`).
      `slack`      뗀 조각이 네모를 넘쳐도 봐줄 몫 (em 대비 · 기본 1%).
      `sizeSlack`  `to:"drop"` 일 때 두 조각의 **키** 가 어긋나도 봐줄 몫 (기본 8%).
    """
    donor = (donor_glyph(donor_font(ctx, spec, font), spec)
             if spec.get("from") else None)
    take = spec["take"]
    side = spec.get("side", "right")
    done = []
    for glyph in selected_glyphs(font, spec):
        src = donor or glyph
        cs = list(src.foreground)
        ink = O.bbox(list(glyph.foreground))
        kw = {"side": side}
        if "at" in spec:
            kw["at"] = _in_box(ctx, src, spec["at"])
        if "near" in spec:
            kw["near"] = spec["near"]
        rect = _rect(ctx, src, take)
        if "walk" in spec:
            pieces, how, band = _walk_pieces(ctx, src, cs, rect, spec["walk"])
            if pieces is None:
                print("carvePart: %s 에서 조각을 못 뗐다 — %s" % (src.glyphname, how))
                continue
            note = _stand_on_columns(ctx, glyph, pieces, spec, band)
            if note is None:
                continue
            print("carvePart: %s %s%s" % (glyph.glyphname, how, note))
            done.append(glyph.glyphname)
            continue
        got, _, how = O.take_part(cs, rect, **kw)
        if got is None:
            print("carvePart: %s 에서 조각을 못 뗐다 — %s" % (src.glyphname, how))
            continue
        # 뗀 조각이 네모를 넘치면 아직 다 갈리지 않은 것이다. `carve_out` 은
        # 목을 만날 때마다 이으므로, 여기까지 넘친다면 경계가 아예 없는 자리가
        # 남은 것이다 (흰 슬릿조차 없이 이웃과 녹은 획). 그 굵기는 넘긴다.
        slack = spec.get("slack", 0.01) * (ctx.em_ascent + ctx.em_descent)
        bb = O.bbox(got)
        if not _fits(bb, rect, slack):
            print("carvePart: %s 에서 뗀 조각이 네모를 넘친다 (%s) — 넘긴다"
                  % (src.glyphname, " ".join("%d" % round(v) for v in bb)))
            continue
        rest = list(glyph.foreground)
        gone = None
        if "drop" in spec:
            rect = _rect(ctx, glyph, spec["drop"])
            # 자리를 맞출 것은 네모가 아니라 **버린 조각의 상자** 다. 네모는 어느
            # 조각을 고를지 가리키는 것일 뿐 그 조각과 크기가 다르다.
            loss, _, _ = O.take_part(rest, rect, side=side)
            rest, used, how_d = O.drop_part(rest, rect, side=side)
            if rest is None:
                print("carvePart: %s 에서 버릴 조각을 못 갈랐다 — %s" % (glyph.glyphname, how_d))
                continue
            gone = O.bbox(loss) if loss else None
        # 크기를 손대지 않고 놓는 것(`to:"drop"`)은 두 조각이 같은 크기라는 전제
        # 위에 선다. 어긋나면 뗀 것이 바라던 조각이 아니다 — 경계가 녹아 없어져
        # 이웃 획이 딸려 온 것이다. 그런 굵기는 손대지 않고 넘긴다.
        if gone and spec.get("to") == "drop":
            # **키** 로 잰다. 폭은 굵기가 굵어질수록 벌어지는 것이 제대로다
            # (殻 의 几 는 Medium 에서 480, 받을 자리는 447). 키가 어긋나면
            # 그것은 다른 조각이다.
            off = abs((bb[3] - bb[2]) / (gone[3] - gone[2]) - 1)
            if off > spec.get("sizeSlack", 0.08):
                print("carvePart: %s 의 조각이 받을 자리와 키가 %d%% 어긋난다 — 넘긴다"
                      % (src.glyphname, round(off * 100)))
                continue
        part = O.dup(got)
        pb = O.bbox(part)
        note = ""
        if "up" in spec:
            dx, dy = 0.0, round(spec["up"] * (ink[3] - ink[2]))
        elif spec.get("to") == "drop" and gone:
            dx = (gone[0] + gone[1]) / 2 - (pb[0] + pb[1]) / 2
            dy = gone[3] - pb[3]
        elif spec.get("to") == "column":
            # **조각의 발을 받는 쪽 기둥 위에 세운다.** 세로는 조각의 발이 받는
            # 쪽 가로획의 윗변에 오도록, 가로는 발의 왼끝이 기둥의 왼끝에 오도록
            # 옮긴다. 廉 의 두 삐침은 저마다 다른 기둥에 서므로 (왼쪽은 왼기둥,
            # 오른쪽은 가운데기둥) 조각마다 따로 맞춘다.
            foot = [p.x for c in part for p in c if p.y <= pb[2] + 2]
            bars = _bars(rest, _rect(ctx, glyph, spec["bar"]), spec.get("share", 0.45))
            if not foot or not bars:
                print("carvePart: %s 의 기둥이나 가로획을 못 찾았다" % glyph.glyphname)
                continue
            top = bars[0][1]                       # 가로획의 윗변
            dy = top - pb[2]
            cols = [c for c in O.columns(rest) if c[1] - c[0] >= 0.02 * (ctx.em_ascent + ctx.em_descent)]
            if not cols:
                print("carvePart: %s 에서 기둥을 못 찾았다" % glyph.glyphname)
                continue
            want = min(foot)
            col = min(cols, key=lambda c: abs(O.snap_x(rest, c[0]) - want))
            dx = O.snap_x(rest, col[0]) - want
        else:
            dx, dy = 0.0, 0.0
        for contour in part:
            contour.transform(psMat.translate(dx, dy))
        if "weld" in spec:
            note += _weld(part, rest, spec["weld"])
        relay(glyph, [rest, part])
        done.append("%s %s%s%s" % (glyph.glyphname, how,
                                   " 옮김 %+d,%+d" % (dx, dy) if dx or dy else "", note))
    if done:
        print("carvePart: %s" % "; ".join(done))


# --------------------------------------------------------------------------
# 끝 맞바꾸기
# --------------------------------------------------------------------------


def _bars(contours, rect, share=0.45, base=1000):
    """네모 안의 **가로획들** — 위에서 아래로 [(ylo, yhi, x0, x1), …].

    줄마다 먹이 **이어진 구간**을 보아, 가장 긴 구간이 네모 폭의 `share` 를 넘으면
    가로획으로 본다. 이어지는 줄은 한 획으로 묶고, 획의 좌우 끝은 그 획 **한복판
    줄** 에서 잰다 — 띠 전체의 최소·최대로 재면 획을 가로지르는 세로획이나 이웃
    성분까지 딸려 들어온다.
    """
    x0, x1, y0, y1 = rect
    m = O.part_mask(contours)
    want = share * (x1 - x0)
    rows = []
    for y in range(int(y1), int(y0) - 1, -1):
        r = base - y
        if not (0 <= r < m.shape[0]):
            continue
        got = O.runs(m[r, int(x0):int(x1)])
        if not got:
            continue
        a, b = max(got, key=lambda t: t[1] - t[0])
        if b - a >= want:
            rows.append((y, int(x0) + a, int(x0) + b))
    bands = []
    for y, a, b in rows:
        if bands and bands[-1][0] - y <= 1:
            bands[-1][0] = y
            bands[-1][2].append((y, a, b))
        else:
            bands.append([y, y, [(y, a, b)]])
    out = []
    for lo, hi, got in bands:
        y, a, b = got[len(got) // 2]                 # 한복판 줄에서 잰다
        out.append((lo, hi, a, b))
    return out


@op("swapStrokeEnds")
def op_swap_stroke_ends(ctx, font, spec, source_half):
    """가로획 두 개의 **오른쪽 끝을 맞바꾼다** — 획 굵기도 다른 획도 건드리지 않는다.

    程 의 발(壬)은 Plex 에서 둘째 가로획이 짧고 셋째가 길다. 편수자료와 한스 K 는
    반대다. 길이만 맞바꾸면 되므로 **가로획 오른쪽 끝의 점만 옮긴다**.

        {"op": "swapStrokeEnds", "at": [0.36, -0.05, 0.96, 0.47],
         "rows": [2, 3], "alignLeft": [3, 1], "cps": ["7a0b"]}

    `at` 안에서 가로획을 위에서부터 세어(1부터) `rows` 의 두 획의 오른끝을
    맞바꾼다. `alignLeft` 는 [옮길 획, 맞출 획] 으로, 앞 획의 왼끝을 뒤 획의
    왼끝에 맞춘다 — 程 의 셋째 획은 왼쪽이 禾 밑으로 뻗어 있던 것을 위 획에
    맞춰 거둬들인다. `share` 는 그 줄의 먹이 네모 폭의 얼마를 넘어야 가로획으로
    보는지다 (기본 0.45) — 가는 굵기에서 짧게 잡히는 획이 있으면 낮춘다.
    """
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = list(glyph.foreground)
        rect = _rect(ctx, glyph, spec["at"])
        # 래스터로 잰 끝은 한 단위씩 어긋난다 — 점이 실제로 선 자리에 붙인다.
        bars = [(lo, hi, O.snap_x(cs, a), O.snap_x(cs, b))
                for lo, hi, a, b in _bars(cs, rect, spec.get("share", 0.45))]
        need = max(max(spec.get("rows", [])), max(spec.get("alignLeft", [0])))
        if len(bars) < need:
            print("swapStrokeEnds: %s 에서 가로획을 %d 개만 찾았다 (%d 필요)"
                  % (glyph.glyphname, len(bars), need))
            continue
        moves = []                       # (띠, 옛 x, 새 x)
        if "rows" in spec:
            i, j = (n - 1 for n in spec["rows"])
            moves.append((bars[i], bars[i][3], bars[j][3]))
            moves.append((bars[j], bars[j][3], bars[i][3]))
        if "alignLeft" in spec:
            i, j = (n - 1 for n in spec["alignLeft"])
            moves.append((bars[i], bars[i][2], bars[j][2]))
        new = []
        hit = 0
        for c in cs:
            nc = fontforge.contour()
            nc.is_quadratic = c.is_quadratic
            for p in c:
                x = p.x
                for (lo, hi, _, _), was, now in moves:
                    if abs(p.x - was) <= 2 and lo - 2 <= p.y <= hi + 2:
                        x = now
                        hit += 1
                        break
                nc += fontforge.point(x, p.y, p.on_curve)
            nc.closed = c.closed
            new.append(nc)
        if not hit:
            print("swapStrokeEnds: %s 에서 옮길 점을 못 찾았다" % glyph.glyphname)
            continue
        relay(glyph, [new])
        done.append("%s 점%d" % (glyph.glyphname, hit))
    if done:
        print("swapStrokeEnds: %s" % ", ".join(done))


# --------------------------------------------------------------------------
# 칸 잇기
# --------------------------------------------------------------------------


@op("joinCounters")
def op_join_counters(ctx, font, spec, source_half):
    """세로로 포개진 흰 칸들을 **하나로 잇는다** — 사이의 가로획을 지운다.

    龜 의 배 안에는 흰 칸이 셋 포개져 있고 사이를 가로획 둘이 막는다. 편수자료는
    그 칸들이 한 줄기로 트여 있다. 칸과 칸 사이가 **칸보다 얇은 가로획** 이면
    이어야 할 자리로 본다.

        {"op": "joinCounters", "at": [0.44, 0.06, 0.56, 0.63],
         "maxBar": 0.06, "cps": ["9f9c"]}

    `reach` 로 어느 쪽으로 이을지 정한다 ("down" · "up" · 기본 "both"). 龜 는
    아래로만 잇는다 — 위쪽 가로획 너머에도 칸(머리의 흰 쐐기)이 있어 그냥 두면
    배 밖으로 트인다.

    `at` 은 칸이 선 세로 띠다 (x 는 글자 폭, y 는 em 대비). 그 안에 든 흰 칸의
    x 범위로 기둥 사이의 폭을 잡고, 위아래로 훑어 얇은 가로획으로만 막힌 칸들을
    모두 잇는다. 이을 자리에는 **감김이 반대인 네모** 를 얹어 removeOverlap 이
    먹을 도려내게 한다 — 먹을 지우는 것이지 칸을 그리는 것이 아니다.
    """
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = list(glyph.foreground)
        if not cs:
            continue
        bx0, by0, bx1, by1 = _in_box(ctx, glyph, spec["at"])
        ink = O._turn(max(cs, key=lambda c: len(list(c))))
        holes = [O.box(c) for c in cs if O._turn(c) != ink
                 and bx0 <= O.box(c)[0] and O.box(c)[1] <= bx1
                 and by0 <= O.box(c)[2] and O.box(c)[3] <= by1]
        if len(holes) < 2:
            print("joinCounters: %s 에서 이을 칸을 못 찾았다" % glyph.glyphname)
            continue
        x0, x1 = min(h[0] for h in holes), max(h[1] for h in holes)
        bar = spec.get("maxBar", 0.06) * (ctx.em_ascent + ctx.em_descent)
        lo = min(h[2] for h in holes)
        hi = max(h[3] for h in holes)
        # 이 기둥에 걸치는 **다른 흰 칸** 까지 잇는다. 단순히 먹이 얇다고 잇지
        # 않는다 — 가로획 너머가 먹이면 거기서 멈춰야 한다 (龜 의 위쪽 가로획을
        # 넘어가면 배 밖으로 트인다). 넘어간 자리에 칸이 있을 때만 잇는다.
        near = [O.box(c) for c in cs if O._turn(c) != ink
                and O.box(c)[0] <= x1 and x0 <= O.box(c)[1]]
        for _ in range(4):
            way = spec.get("reach", "both")
            down = ([h for h in near if h[3] < lo and lo - h[3] <= bar]
                    if way in ("both", "down") else [])
            up = ([h for h in near if h[2] > hi and h[2] - hi <= bar]
                  if way in ("both", "up") else [])
            if not down and not up:
                break
            if down:
                lo = max(h[3] for h in down)
            if up:
                hi = min(h[2] for h in up)
        cut = fontforge.contour()
        cut.is_quadratic = glyph.foreground.is_quadratic
        # 흰 칸과 **같은 쪽으로** 감아야 removeOverlap 이 먹을 도려낸다. 먹과
        # 같은 쪽으로 감으면 도리어 칸이 메워진다.
        for px, py in ((x0, lo), (x1, lo), (x1, hi), (x0, hi)):
            cut += fontforge.point(O.snap_x(cs, px), py, True)
        cut.closed = True
        # 이어 버릴 칸들은 **빼고** 얹는다. 그대로 두면 네모의 변과 칸의 변이
        # 겹쳐 removeOverlap 이 풀지 못하고, 옛 칸의 테두리를 되짚는 경로가 남는다.
        keep = [c for c in cs
                if not (O._turn(c) != ink
                        and x0 - 1 <= O.box(c)[0] and O.box(c)[1] <= x1 + 1
                        and lo - 1 <= O.box(c)[2] and O.box(c)[3] <= hi + 1)]
        relay(glyph, [keep, [cut]])
        done.append("%s %d..%d × %d..%d" % (glyph.glyphname, round(x0), round(x1),
                                            round(lo), round(hi)))
    if done:
        print("joinCounters: %s" % ", ".join(done))


# --------------------------------------------------------------------------
# 다리 고르게 세우기
# --------------------------------------------------------------------------


def _ink_runs(contours, y, base=1000):
    """그 높이에서 먹이 이어진 구간들 — [(x0, x1), …]."""
    m = O.part_mask(contours)
    r = base - int(y)
    return O.runs(m[r]) if 0 <= r < m.shape[0] else []


@op("evenLegs")
def op_even_legs(ctx, font, spec, source_half):
    """가운데 다리들을 **곧게, 고르게** 다시 세운다 — 흰 칸이 똑같아진다.

    Plex 의 册 은 冂 둘을 나란히 둔 꼴이라 윗변이 가운데서 끊기고 다리가 「굽은
    丿 · 갈고리 · 굽은 丿 · 갈고리」다. 편수자료는 윗변이 한 줄로 이어지고 맨
    왼쪽만 丿 로 굽는다. 그래서 바깥 두 세로획만 두고 사이를 다시 짠다.

        {"op": "evenLegs", "band": [0.45, 0.72], "end": 0.047,
         "bar": [0.376, 0.434], "cps": ["518c"]}

    `band` 은 **흰 칸이 선 높이** 다 (em 대비). 그 높이에서 먹 구간을 세어 맨
    바깥 둘을 벽으로 삼고, 벽의 안쪽 변 사이를 **흰 칸 셋이 똑같아지도록** 나눈다
    (다리 두께는 두 벽의 평균). 다리는 윗변 밑에서 `end` 까지 곧게 내려온다.
    윗변 밑과 가운뎃 가로획은 흰 칸에서 잰다 — 칸의 위가 곧 윗변의 밑이다.
    `keep` 을 적지 않으면 **재어서** 잡는다 — 왼쪽은 왼벽의 안쪽 변까지, 오른쪽은
    갈고리의 왼끝부터다. 슬랩의 경계가 먹을 가로지르면 그 자리가 잘린 자국으로
    남으므로, 비율로 적어 두면 굵기마다 어긋난다 (册 Bold 의 왼벽 안쪽 변은 217
    인데 Regular 은 193 이다).

    `keep` 은 **남길 네모들** 이다. 지울 자리에 흰 칸이 섞여 있어 네모로 도려낼
    수 없으므로, 지울 것을 덮지 말고 남길 것을 덮어 그 합집합만 오린다. 네모는
    서로 겹쳐도 된다 — 겹친 자리는 removeOverlap 이 녹인다.

    다리 끝(`end`)은 여덟 굵기가 같은 값을 쓰되, 남은 먹이 다리 자리에서 그보다
    높이 올라오면 그 위에서 끊는다 — 갈고리는 굵을수록 높이 쓸고 올라와, 그대로
    두면 다리와 한 덩이가 된다.
    """
    em = ctx.em_ascent + ctx.em_descent
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = list(glyph.foreground)
        blo, bhi = (v * em for v in spec["band"])
        runs = _ink_runs(cs, (blo + bhi) / 2)
        if len(runs) < 3:
            print("evenLegs: %s 에서 벽을 못 찾았다 (%d 구간)" % (glyph.glyphname, len(runs)))
            continue
        # 벽의 네 변을 모두 점에 붙인다 — 래스터 값은 한 단위씩 어긋나고, 그
        # 어긋남이 다리 두께와 자리에 그대로 실린다.
        la, lb = O.snap_x(cs, runs[0][0]), O.snap_x(cs, runs[0][1])
        ra, rb = O.snap_x(cs, runs[-1][0]), O.snap_x(cs, runs[-1][1])
        x0, x1 = lb, ra                               # 두 벽의 안쪽 변
        t = ((lb - la) + (rb - ra)) / 2.0
        n = spec.get("legs", 2)
        gap = (x1 - x0 - n * t) / (n + 1)
        # 윗변 밑과 가운뎃 가로획은 **흰 칸에서 잰다** — 칸의 위가 곧 윗변의 밑이고
        # 칸의 밑이 곧 가로획의 위다. 비율로 적으면 굵기마다 어긋난다.
        ink = O._turn(max(cs, key=lambda c: len(list(c))))
        holes = [O.box(c) for c in cs if O._turn(c) != ink
                 and O.box(c)[2] < bhi and O.box(c)[3] > blo]
        if not holes:
            print("evenLegs: %s 에서 흰 칸을 못 찾았다" % glyph.glyphname)
            continue
        top = max(h[3] for h in holes)
        bar_hi = min(h[2] for h in holes)
        end = spec["end"] * em
        # 가로획의 밑은 그 아래로 먹이 끊기는 자리다
        mid = (x0 + x1) / 2.0
        got = O.ink_spans(O.part_mask(cs), mid - 4, mid + 4, -0.2 * em, bar_hi - 1)
        bar_lo = O.snap_y(cs, got[0][0]) if got else bar_hi - 0.06 * em
        legs = []
        at = x0
        for _ in range(n):
            a = round(at + gap)
            b = round(a + t)
            legs.append((a, b))
            at = b                       # 다음 칸은 **반올림한 변** 에서 잰다
        # 갈고리가 다리 자리까지 쓸고 올라오면 그 위에서 끊는다
        # 남길 자리만 오려 낸다 (`clip_to`). 지울 자리에 흰 칸이 섞여 있으면
        # 네모로 도려낼 수 없다 — 그 흰 자리가 도리어 먹이 된다.
        #
        # 슬랩의 경계는 **먹을 가로질러선 안 된다.** 가로지르면 그 자리가 잘린
        # 자국으로 남는다(册 의 갈고리 끝이 깎였다). 그래서 비율로 적지 않고
        # 굵기마다 잰다 — 왼쪽은 왼벽의 안쪽 변, 오른쪽은 **갈고리의 왼끝** 이다.
        pad = spec.get("pad", 0.004) * em
        gx0, gx1, gy0, gy1 = O.bbox(cs)
        # 오른쪽 슬랩의 경계는 **셋째 다리와 갈고리 사이의 흰 길 한복판** 이다.
        # 아래로 훑으며 셋째 다리가 가장 오른쪽까지 간 자리와 갈고리가 가장
        # 왼쪽까지 온 자리를 재어 그 사이를 쓴다. 갈고리는 **오른쪽 끝에 닿는
        # 줄기** 로 가린다 — 맨 아래에서는 갈고리가 이미 끝나고 가운데 다리가
        # 가장 오른쪽이 되어, 그것을 물면 슬랩이 다리 자리까지 내려온다.
        # 슬랩의 경계는 **먹을 가로질러선 안 된다.** 가로지르면 그 자리가 잘린
        # 자국으로 남는다(册 의 갈고리 끝이 깎였다). 그래서 비율로 적지 않고
        # 굵기마다 잰다 — 왼쪽은 왼벽의 안쪽 변, 오른쪽은 갈고리의 왼끝이다.
        inner, outer, hook_top = gx0, gx1, gy0
        for y in range(int(bar_lo) - 6, int(gy0), -4):
            got = _ink_runs(cs, y)
            # 오른쪽 **벽의 바깥 변** 에 닿는 줄기라야 갈고리다. 글자의 오른끝
            # (gx1) 으로 재면 안 된다 — 가로획이 벽보다 더 튀어나와 있다.
            if len(got) < 2 or got[-1][1] < rb - 6:
                continue
            outer = min(outer, got[-1][0])
            inner = max(inner, got[-2][1])
            if got[-1][0] < ra - 2:                  # 벽보다 왼쪽으로 뻗은 자리
                hook_top = max(hook_top, y)
        if "keep" in spec:
            boxes = [_rect(ctx, glyph, b) for b in spec["keep"]]
        elif inner < outer:
            # 옛 다리와 갈고리 사이에 흰 길이 있다 — 그 한복판을 세로로 가른다.
            lane = min(max((inner + outer) / 2.0, legs[-1][1] + 2), outer - 1)
            boxes = [(gx0 - 50, x0 + pad, gy0 - 50, gy1 + 50),
                     (lane, gx1 + 50, gy0 - 50, gy1 + 50)]
        else:
            # 흰 길이 없다 (굵은 굵기에서 옛 다리가 갈고리 자리까지 넘어온다).
            # 갈고리는 **제 높이까지만** 덮어, 자르는 선이 먹을 가로지르지 않게 한다.
            boxes = [(gx0 - 50, x0 + pad, gy0 - 50, gy1 + 50),
                     (ra, gx1 + 50, gy0 - 50, gy1 + 50),
                     (outer - pad, gx1 + 50, gy0 - 50, hook_top + pad)]
        keep = clip_to(cs, boxes)
        # 다리 끝은 **남은 먹** 에서 잰다. 갈고리는 굵을수록 높이 쓸고 올라와,
        # 그대로 두면 다리와 한 덩이가 된다.
        floor = end
        for a, b in legs:
            # 다리의 오른쪽 변까지 센다 — 갈고리는 오른쪽으로 갈수록 높으므로
            # 한 칸을 빼면 그만큼 낮게 잡힌다 (册 Bold 에서 47 과 56 이 갈렸다).
            for lo2, hi2 in O.ink_spans(O.part_mask(keep), a, b + 1, -0.2 * em, bar_lo - 4):
                floor = max(floor, hi2 + 1)
        lay = [keep,
               [_rect_contour(cs, x0, x1, bar_lo, bar_hi, ink)],
               [_rect_contour(cs, x0, x1, top, O.bbox(cs)[3], ink)]]
        for a, b in legs:
            lay.append([_rect_contour(cs, a, b, floor, top, ink)])
        relay(glyph, lay)
        # 이어 붙인 자리에는 한 줄 위에 늘어선 점이 남는다 — 걷어낸다.
        gone = 0
        if spec.get("tidy", True):
            neat, gone = O.tidy(list(glyph.foreground))
            relay(glyph, [neat], merge=False)
        done.append("%s 다리 %s 끝 %d 걷은 점 %d"
                    % (glyph.glyphname, " ".join("%d..%d" % l for l in legs),
                       round(floor), gone))
    if done:
        print("evenLegs: %s" % ", ".join(done))


def _rect_contour(cs, x0, x1, y0, y1, turn):
    """네모 윤곽 하나 — `turn` 이 +면 반시계, -면 시계로 감는다."""
    c = fontforge.contour()
    c.is_quadratic = cs[0].is_quadratic if cs else True
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    if turn < 0:
        pts.reverse()
    for px, py in pts:
        c += fontforge.point(px, py, True)
    c.closed = True
    return c


def _hook_roof(glyph, rest, dot):
    """勹 의 아래 갈고리 위 변과 윗 가로획 아랫변 — 점 오른끝 너머 세로줄에서 (갈고리는 그쯤부터)."""
    m = O.part_mask(rest)
    x = dot[1] + 0.25 * (dot[1] - dot[0])
    spans = O.ink_spans(m, x, x + 1, -200, 1000)
    below = [sp for sp in spans if sp[1] < dot[2]]
    above = [sp for sp in spans if sp[0] > dot[3]]
    if not below or not above:
        return None, None
    return below[0][1], above[-1][0]


def _head_share(ctx, font, spec, key):
    """丿 머리 꼭대기와 갈고리 사이 가운데가 갈고리~윗 가로획 사이의 몇 몫인가."""
    g = donor_glyph(font, {"head": key}, "head")
    cs = list(g.foreground)
    x0, y0, x1, y1 = _in_box(ctx, g, spec["at"])
    dots = [k for k, c in enumerate(cs) if x0 <= O.box(c)[0] and O.box(c)[1] <= x1
            and y0 <= O.box(c)[2] and O.box(c)[3] <= y1]
    rest = [c for k, c in enumerate(cs) if k not in dots]
    if len(dots) != 1:
        return None
    hook, roof = _hook_roof(g, rest, O.box(cs[dots[0]]))
    if hook is None:
        return None
    head = max(O.box(c)[3] for c in rest)
    return ((head + hook) / 2 - hook) / (roof - hook)


@op("dotToBar")
def op_dot_to_bar(ctx, font, spec, source_half):
    """勹 안의 점을 가로획으로 — 같은 글꼴 匀 의 떠 있는 가로획을 배워 그린다.

        {"op": "dotToBar", "at": [0.2, 0.05, 0.65, 0.55], "like": "5300",
         "likeAt": [0.2, 0.38, 0.75, 0.55], "cps": ["52fa"]}      勺 — KS 는 勹 안이 一

    `at`     지울 점 — 이 네모 안에 온전히 드는 윤곽.
    `like`   가로획을 배울 글자, `likeAt` 그 가로획 (네모 안에 드는 윤곽).
             匀 의 가로획은 굵기마다 x 가 거의 같고 굵기는 勹 윗 가로획과 같다.
             그 x 범위와 굵기 그대로, 세로 가운데를 지운 점의 가운데에 둔다.
    `head`   세로 가운데를 丿 머리 꼭대기와 아래 갈고리 위 변 사이로 — 그 몫을 잴
             글자 (勺 는 제 것 "52fa"). 芍 는 丿 머리가 艹 에 묻혀 勺 의 몫을 빌린다:
             몫 = (가운데 − 갈고리) / (勹 윗 가로획 아랫변 − 갈고리).
    `share`  그 몫을 숫자로 바로 준다 (모든 굵기에 같게).
    """
    # 몫은 고치기 전에 잰다 — 勺 를 먼저 고치면 芍 차례엔 勺 에 점이 없다
    share = spec.get("share")
    if share is None and "head" in spec:
        share = _head_share(ctx, font, spec, spec["head"])
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = list(glyph.foreground)
        x0, y0, x1, y1 = _in_box(ctx, glyph, spec["at"])
        dots = [k for k, c in enumerate(cs) if x0 <= O.box(c)[0] and O.box(c)[1] <= x1
                and y0 <= O.box(c)[2] and O.box(c)[3] <= y1]
        like = donor_glyph(font, spec, "like")
        lx0, ly0, lx1, ly1 = _in_box(ctx, like, spec["likeAt"])
        bars = [O.box(c) for c in like.foreground if lx0 <= O.box(c)[0] and O.box(c)[1] <= lx1
                and ly0 <= O.box(c)[2] and O.box(c)[3] <= ly1]
        if len(dots) != 1 or len(bars) != 1:
            print("dotToBar: %s 점 %d 개, 가로획 %d 개 — 건너뜀" % (glyph.glyphname, len(dots), len(bars)))
            continue
        d, b = O.box(cs[dots[0]]), bars[0]
        mid, t = (d[2] + d[3]) / 2, b[3] - b[2]
        if share is not None:
            hook, roof = _hook_roof(glyph, [c for k, c in enumerate(cs) if k != dots[0]], d)
            if hook is not None:
                mid = hook + share * (roof - hook)
        bx0, bx1 = b[0], b[1]
        bar = _rect_contour(cs, bx0, bx1, round(mid - t / 2), round(mid - t / 2) + t, O._turn(cs[dots[0]]))
        relay(glyph, [[c for k, c in enumerate(cs) if k != dots[0]] + [bar]])
        done.append("%s y%d t%d x%d-%d" % (glyph.glyphname, round(mid), t, bx0, bx1))
    if done:
        print("dotToBar: %s" % ", ".join(done))


@op("keepOnly")
def op_keep_only(ctx, font, spec, source_half):
    """**남길 네모들만 오려 그 합집합**을 남긴다 — 흰 칸이 섞인 자리를 지우는 길.

    감김이 반대인 네모를 얹어 도려내는 길은 네모가 먹 안에 온전히 들 때만 쓴다.
    밖으로 나가면 그 부분이 도리어 먹이 된다. 그래서 지울 것을 덮지 말고 **남길
    것을 덮는다.** 네모는 서로 겹쳐도 된다 — 겹친 자리는 removeOverlap 이 녹인다.

        {"op": "keepOnly", "keep": [[-0.05, -0.10, 1.05, 0.60],
                                    [-0.05, -0.10, 0.33, 1.05],
                                    [-0.05, 0.71, 1.05, 1.05]], "cps": ["5ec9"]}

    廉 의 丷 은 «가로 윗변 위 · 广 의 가로획 밑 · 세로 칼선 오른쪽» 에만 있으므로,
    그 밖을 세 조각으로 덮으면 丷 만 빠진다.

    `below` 는 «그 가로획 밑을 다 남긴다», `above` 는 «그 위를 다 남긴다» 는 뜻이다 — 경계를 비율로 적으면 굵기마다
    그 획을 가로질러 잘라 버린다.

    **네모의 경계는 먹을 가로질러선 안 된다** — 가로지르면 그 자리가 잘린 자국으로
    남는다. 흰 자리를 지나게 잡는다.
    """
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = list(glyph.foreground)
        if not cs:
            continue
        boxes = [_rect(ctx, glyph, b) for b in spec.get("keep", [])]
        # 슬랩의 경계가 가로획을 가로지르면 그 획이 잘려 뒤에 재는 값이 어긋난다
        # (廉 에서 广 의 가로획이 잘려 띠를 11 단위 크게 쟀다). `above` 를 주면
        # 그 네모 안 가로획의 **밑변** 을 경계로 삼아 획을 온전히 남긴다.
        for one in spec.get("above", []):
            bars = _bars(cs, _rect(ctx, glyph, one["bar"]), one.get("share", 0.45))
            if not bars:
                print("keepOnly: %s 에서 가로획을 못 찾았다" % glyph.glyphname)
                continue
            lo = O.snap_y(cs, bars[-1][0])
            x0, x1, _, y1 = _rect(ctx, glyph, one.get("box", [-0.05, 0, 1.05, 1.05]))
            boxes.append((x0, x1, lo, y1))
        for one in spec.get("below", []):
            bars = _bars(cs, _rect(ctx, glyph, one["bar"]), one.get("share", 0.45))
            if not bars:
                print("keepOnly: %s 에서 가로획을 못 찾았다" % glyph.glyphname)
                continue
            hi = O.snap_y(cs, bars[0][1])                # 그 가로획의 **윗변**
            x0, x1, y0, _ = _rect(ctx, glyph, one.get("box", [-0.05, -0.15, 1.05, 1.05]))
            boxes.append((x0, x1, y0, hi))
        kept = clip_to(cs, boxes)
        if not kept:
            print("keepOnly: %s 에서 남는 것이 없다" % glyph.glyphname)
            continue
        relay(glyph, [kept])
        done.append("%s 윤곽 %d → %d" % (glyph.glyphname, len(cs), len(glyph.foreground)))
    if done:
        print("keepOnly: %s" % ", ".join(done))


def _lone_left(glyph, share=0.47):
    """왼쪽에 홀로 떨어진 윤곽 하나 — 변이 방과 아직 안 붙었으면 그것이 나온다."""
    cs = list(glyph.foreground)
    got = [c for c in cs if O.box(c)[1] < (glyph.width or 1000) * share]
    return got if len(got) == 1 else None


def _forms(font, spec, cps):
    """그 굵기에서 쓸 **기준 자형**들 — 변이 아직 홀로 떨어진 글자에서 거둔다.

    굵을수록 변이 방에 녹아붙지만, 열두 자가 한꺼번에 붙지는 않는다. Bold 에서도
    祝·祉·祐 의 礻 는 홀로 떨어져 있다. 그 굵기의 것을 써야 획 두께가 맞는다.
    """
    out = {}
    for c in spec.get("form") or cps:
        cpv = cp(c) if isinstance(c, str) else c
        if cpv not in font:
            continue
        got = _lone_left(font[cpv])
        if got:
            out[cpv] = got
    return out


@op("swapRadical")
def op_swap_radical(ctx, font, spec, source_half):
    """변을 통째로 바꾼다 — **기준 자형**으로 가르고, 온전한 변을 끼운다.

    2026-09-29 사용자가 정해 준 길이다. 어제까지는 변이 방에 녹아붙은 굵기를
    손대지 못해 겹친 채로 두었고, 상자나 흰 골로 어림해 자르려다 방의 끝을
    잘라먹었다. 기준 자형이 있으면 어림할 것이 없다.

      1. **기준 자형**을 거둔다 — 같은 굵기에서 변이 아직 홀로 떨어진 글자의 것
         (`form` 에 따로 적을 수 있다. 없으면 `cps` 에서 찾는다).
      2. 받는 글자에 기준 자형을 가로로 밀어 맞춰 보고, 가장 잘 덮는 것을 골라
         그 오른끝을 **가름선**으로 삼는다 (`outline.beside_form`).
      3. 그 선에서 가른다. 선이 지나는 자리에 점을 만들어 끊으므로 방의 끝이
         잘려 나가지 않고, 잘린 자리는 두 옆 변을 늘여 모서리로 되살린다.
      4. 끼울 변은 기증자에서 **통째로** 떼어 온다 — 기증자는 자르지 않는다.
         **오른끝이 받는 변보다 같거나 짧으면서 가장 넓은 것**을 고른다.
      5. 제 좌표 그대로 놓는다. 눌러 맞추지도, 옮기지도 않는다.

        {"op": "swapRadical", "form": ["795d", "7949", "7950"],
         "from": ["7940", "7946", ...], "cps": ["793e", "7948", ...]}
    """
    cps = [cp(c) for c in (spec.get("cps") or [])]
    forms = _forms(font, spec, spec.get("cps") or [])
    if not forms:
        print("swapRadical: 기준 자형이 없다 — 넘긴다")
        return
    pool = []
    for one in donor_list(font, spec):
        cs = list(one.foreground)
        best, rad = None, None
        for f in forms.values():
            got, how = O._fit_form(cs, f)
            if got is None:
                continue
            if best is None or how > best:
                left, _ = O.beside_form(cs, f)
                if left:
                    best, rad = how, left
        if rad is None:
            continue
        bb = O.bbox(rad)
        em = one.width or 1000
        if not (0.20 * em <= bb[1] - bb[0] <= 0.50 * em):
            continue
        if bb[3] - bb[2] < 0.40 * em:
            continue
        pool.append((one, rad, bb))
    if not pool:
        print("swapRadical: 기증자가 없다 — 넘긴다")
        return
    names = {one.glyphname for one, _, _ in pool}
    done, miss = [], []
    for glyph in selected_glyphs(font, spec):
        if glyph.glyphname in names:
            continue
        cs = list(glyph.foreground)
        pick, how = None, -1.0
        for f in forms.values():
            _, got = O._fit_form(cs, f)
            if got > how:
                pick, how = f, got
        left, body = (O.beside_form(cs, pick, crumb=0.2) if pick
                      else (None, None))
        if not left or not body:
            miss.append(glyph.glyphname)
            continue
        edge = O.bbox(left)[1]
        ok = [t for t in pool if t[2][1] <= edge + 1]
        one, src, bb = (max(ok, key=lambda t: t[2][1] - t[2][0]) if ok
                        else min(pool, key=lambda t: t[2][1]))
        layer = fontforge.layer()
        layer.is_quadratic = glyph.foreground.is_quadratic
        for c in body:
            layer += c
        for c in src:
            layer += c
        width = glyph.width
        glyph.foreground = layer
        glyph.correctDirection()
        glyph.width = width
        done.append("%s ← %s (%+d)" % (glyph.glyphname, one.glyphname,
                                       round(bb[1] - edge)))
    if done:
        print("swapRadical: " + " · ".join(done))
    if miss:
        print("swapRadical: 못 가른 것 " + " ".join(miss))


# --------------------------------------------------------------------------
# 성분 다시 짜기
# --------------------------------------------------------------------------


def _parents(cs):
    """윤곽마다 **바로 자기를 감싼** 윤곽의 번호 (없으면 None)."""
    def inside(pt, poly):
        x, y = pt
        got = False
        for k in range(len(poly)):
            (x1, y1), (x2, y2) = poly[k - 1], poly[k]
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                got = not got
        return got
    polys = [[(p.x, p.y) for p in O._flat_pts(c)] for c in cs]
    holds = {i: [j for j in range(len(cs)) if j != i and inside(polys[i][0], polys[j])]
             for i in range(len(cs))}
    return {i: (max(holds[i], key=lambda j: len(holds[j])) if holds[i] else None)
            for i in range(len(cs))}


def _pick_part(cs, em, want):
    """`want` 조건에 맞는 성분 — (성분 윤곽들, 나머지) 또는 None.

    want = {"minHeight": 키 하한, "left": [왼끝 하한, 상한], "maxWidth": 폭 상한} (em 비율).
    그 조건에 맞는 윤곽이 **꼭 하나** 여야 하고, 그 안의 구멍도 함께 가져간다.
    폭 상한은 녹아붙은 윤곽(다른 성분까지 품은 것)을 거르려는 것이다.
    """
    bs = [O.box(c) for c in cs]
    lo, hi = want.get("left", [0, 1])
    got = [i for i, b in enumerate(bs)
           if b[3] - b[2] > want.get("minHeight", 0) * em and lo * em < b[0] < hi * em
           and b[1] - b[0] < want.get("maxWidth", 1) * em]
    if len(got) != 1:
        return None
    k = got[0]
    par = _parents(cs)
    part = [k] + [h for h in range(len(cs)) if par[h] == k and O._turn(cs[h]) != O._turn(cs[k])]
    return [cs[i] for i in part], [c for i, c in enumerate(cs) if i not in part]


def _long_edge(part, right):
    """왼쪽(right=False) 또는 오른쪽 절반에서 가장 긴 곧은 세로 변 — (x, 위 끝 y)."""
    bb = O.bbox(part)
    mid = (bb[0] + bb[1]) / 2.0
    best = None
    for c in part:
        q = [(p.x, p.y) for p in c if p.on_curve]
        for i in range(len(q)):
            (x1, y1), (x2, y2) = q[i - 1], q[i]
            if abs(x1 - x2) < 0.5 and ((x1 > mid) if right else (x1 < mid)):
                if best is None or abs(y2 - y1) > best[0]:
                    best = (abs(y2 - y1), x1, max(y1, y2))
    return (best[1], best[2]) if best else ((bb[1] if right else bb[0]), bb[3])


def _part_at(ctx, font, name, em, want, split_tmpl):
    """이 굵기에서 글리프 `name` 의 성분과 나머지. 녹아붙었으면 가는 굵기를 안내로 가른다."""
    from . import ops as _ops
    g = donor_glyph(font, {"from": name})
    if g is None:
        return None
    cs = [c.dup() for c in g.foreground]
    got = _pick_part(cs, em, want)
    if got or not split_tmpl:
        return got
    me = ctx.style
    lighter = sorted((st for st in ctx.recipe["styles"]
                      if st.get("italic", False) == me.get("italic", False)
                      and st["weight"] < me["weight"]), key=lambda st: -st["weight"])
    for st in lighter:
        path = ctx.path(split_tmpl, st)
        f = _ops._PRISTINE.get(path)
        if f is None:
            f = _ops._PRISTINE[path] = _ops._open_pristine(path)
        gg = donor_glyph(f, {"from": name})
        if gg is None:
            continue
        guide = _pick_part([c.dup() for c in gg.foreground], em, want)
        if guide:
            part, rest = O.split_glyph(cs, guide[0], guide[1])
            return (part, rest) if part and rest else None
    return None


@op("rebuildPart")
def op_rebuild_part(ctx, font, spec, source_half):
    """받는 글리프에서 성분 하나를 지우고, 기증자의 같은 성분을 **세로선에 맞춰** 넣는다.

    慨 — 이체자 `uni6168.jp83` 의 旣 에서 변(皀)을 지우고, 漑 의 한국 자형 皀 를
    떼어 넣는다. 늘이거나 누르지 않는다.

      1. 성분은 `part` 조건(키·왼끝·폭, em 비율)으로 고른다. 녹아붙은 굵기는 `split`
         경로의 가는 굵기에서 고른 것을 안내로 outline.split_glyph 로 가른다.
      2. 기증자 성분을 가로로 옮겨 **왼쪽 세로선**을 지운 성분의 왼쪽 세로선에 맞춘다.
      3. **오른쪽 세로선**은 outline.narrow_across 로 맞춘다 — 두 세로선 사이에서 가로
         변만 지나는 칼선 하나를 찾아 칼선이 지나는 가로획만 줄인다(늘인다). 네모
         윗변(오른쪽 세로선의 위 끝) 위의 점은 옮기지 않는다 — 맨 위 삐침은 그대로.

        {"op": "rebuildPart", "base": "uni6168.jp83", "from": "6f11",
         "part": {"minHeight": 0.7, "left": [0.2, 0.45], "maxWidth": 0.45},
         "split": "IBM-Plex-Sans-JP/IBMPlexSansJP-{cjkSrc}.ttf", "cps": ["6168"]}
    """
    em = ctx.em_ascent + ctx.em_descent
    want = spec["part"]
    split_tmpl = spec.get("split")
    old = _part_at(ctx, font, spec["base"], em, want, split_tmpl)
    new = _part_at(ctx, font, spec["from"], em, want, split_tmpl)
    if not old or not new:
        print("rebuildPart: 성분을 못 뗌 (%s %s · %s %s)" % (spec["base"], bool(old), spec["from"], bool(new)))
        return
    old_part, rest = old
    new_part = new[0]
    dx = _long_edge(old_part, False)[0] - _long_edge(new_part, False)[0]
    moved = []
    for c in new_part:
        c = c.dup()
        c.transform(psMat.translate(dx, 0))
        moved.append(c)
    gl = _long_edge(moved, False)[0]
    gr, top = _long_edge(moved, True)
    want_r = _long_edge(old_part, True)[0]
    base = [p.x for c in moved for p in O._flat_pts(c) if top - 1 <= p.y <= top + 30]
    inner = [x for x in base if gl + 5 < x < gr - 5]
    avoid = [(min(inner) - 4, max(inner) + 4)] if inner else None
    fitted, knife = O.narrow_across(moved, want_r - gr, gl, gr, avoid=avoid, below=top)
    if fitted is None:
        fitted, knife = O.narrow_across(moved, want_r - gr, gl, gr, below=top)
    if fitted is None:
        print("rebuildPart: 오른쪽 세로선을 맞출 칼선이 없다 — 넘긴다")
        return
    done = []
    for glyph in selected_glyphs(font, spec):
        relay(glyph, [[c.dup() for c in rest], [c.dup() for c in fitted]])
        done.append(glyph.glyphname)
    print("rebuildPart: %s ← %s 의 성분 (옮김 %+d · 가로획 %+d)"
          % (", ".join(done), spec["from"], round(dx), round(want_r - gr)))


# --------------------------------------------------------------------------
# 발 가로획 고르기와 변 다리 줄이기
# --------------------------------------------------------------------------


def _pts(c):
    return [(p.x, p.y, p.on_curve) for p in c]


def _contour(pts, quad):
    c = fontforge.contour()
    c.is_quadratic = quad
    for x, y, on in pts:
        c += fontforge.point(x, y, on)
    c.closed = True
    return c


def _meet(p, d, q, e):
    """p + t·d 와 q + s·e 가 만나는 점."""
    den = d[0] * e[1] - d[1] * e[0]
    t = ((q[0] - p[0]) * e[1] - (q[1] - p[1]) * e[0]) / den
    return (p[0] + t * d[0], p[1] + t * d[1])


def _cross_bar(c):
    """변(禾 꼴)의 가로획과 가운데 다리 — (가로획 아랫변 y, 윗변 y, 다리 오른 옆선 x).

    가로획은 왼끝이 윤곽 왼끝 가까이에 있는 가로 변 둘(위·아래)이다. 다리의 오른
    옆선은 가로획 윗변 위로 올라가는 모서리 가운데 오른쪽 것이다.
    """
    x0 = O.box(c)[0]
    on = [p for p in c if p.on_curve]
    hs = []
    for n in range(len(on)):
        a, b = on[n - 1], on[n]
        if abs(a.y - b.y) < 0.5 and abs(a.x - b.x) > 60 and min(a.x, b.x) <= x0 + 30:
            hs.append(a.y)
    yb0, yb1 = min(hs), max(hs)
    left = min(p.x for p in c if yb0 - .5 <= p.y <= yb1 + .5)
    right = max(p.x for p in on if yb0 - .5 <= p.y <= yb1 + .5)
    xs = sorted(p.x for p in on if abs(p.y - yb1) < .5 and left + 1 < p.x < right - 1)
    return yb0, yb1, xs[-1]


def _unfuse_leg(c, sr, yb0, low):
    """변의 오른쪽 다리 끝이 방에 묻어 한 윤곽이면 방의 왼쪽 옆선에서 가른다.

    방은 다리 오른쪽(sr + 120 너머)에서 가로획 아랫변(yb0) 아래에 있는 점들과,
    `low` 보다 낮은 점들이다. 다리 쪽 끝 모서리는 다리의 끝변과 오른쪽 긴 변의 선이
    만나는 곳으로 되살린다. 방은 옆선 위의 두 점을 곧게 이어 닫는다.
    돌아오는 것은 (변, 방) 또는 붙어 있지 않으면 None.
    """
    P = _pts(c)
    n = len(P)
    if not any(y < low and x > sr + 50 for x, y, _ in P):
        return None
    xw = min(x for x, y, on in P if on and x > sr + 120)
    isw = [(x >= xw - 0.5 and y < yb0) or (y < low and x > sr + 50) for x, y, _ in P]
    outs = [i for i in range(n) if isw[i] and not isw[(i + 1) % n]]
    ins = [i for i in range(n) if not isw[i - 1] and isw[i]]
    if len(outs) != 1 or len(ins) != 1:
        return None
    a_w, h_first = outs[0], (outs[0] + 1) % n
    h_last, b_w = (ins[0] - 1) % n, ins[0]

    def run(i, j):
        out = [i]
        while i != j:
            i = (i + 1) % n
            out.append(i)
        return out
    A, C = P[h_first], P[a_w]
    Q, Q2 = P[h_last], P[b_w]
    br = _meet(A, (C[0] - A[0], C[1] - A[1]), Q, (Q2[0] - Q[0], Q2[1] - Q[1]))
    he = _contour([P[k] for k in run(h_first, h_last)] + [(br[0], br[1], True)], c.is_quadratic)
    bang = _contour([P[k] for k in run(b_w, a_w)], c.is_quadratic)
    return he, bang


def _leg_end(c, sr):
    """변 오른쪽 다리의 아래 끝 두 점, 축(아래 → 위), 다리 세로 길이.

    다리 세로 길이는 왼쪽 긴 변이 가운데 다리에서 떨어지는 점부터 아래 끝까지다.
    """
    P = _pts(c)
    n = len(P)
    lo = sorted((i for i in range(n) if P[i][2] and P[i][0] > sr + 0.5), key=lambda i: P[i][1])[:2]
    a, b = sorted(lo, key=lambda i: P[i][0])
    on = [i for i in range(n) if P[i][2]]

    def up(k, other):
        m = on.index(k)
        return [q for q in (on[m - 1], on[(m + 1) % len(on)]) if q != other][0]
    ua, ub = up(a, b), up(b, a)
    d1 = (P[ua][0] - P[a][0], P[ua][1] - P[a][1])
    d2 = (P[ub][0] - P[b][0], P[ub][1] - P[b][1])
    n1, n2 = math.hypot(*d1), math.hypot(*d2)
    u = (d1[0] / n1 + d2[0] / n2, d1[1] / n1 + d2[1] / n2)
    nu = math.hypot(*u)
    return a, b, (u[0] / nu, u[1] / nu), P[ua][1] - (P[a][1] + P[b][1]) / 2


def _even_bar(bang, row_min):
    """방의 가로획 하나의 왼팔을 오른팔 길이로 — 왼끝 옆선 위의 점을 모두 옮긴다.

    가로획은 방 윤곽의 왼끝 가까이(80 안)에 곧은 세로 옆선을 가진 것 가운데 윤곽
    바닥에서 `row_min` 보다 높은 첫 것이다. 옆선이 점 여럿으로 끊겨 있으면 같은 x
    로 이어진 점을 모두 옮겨서 모서리가 깎이지 않게 한다.
    돌아오는 것은 (고친 방, 옛 왼팔, 오른팔).
    """
    P = _pts(bang)
    n = len(P)
    on = [i for i in range(n) if P[i][2]]
    x0, _, y0, _ = O.box(bang)
    vert = []
    for m in range(len(on)):
        i, j = on[m - 1], on[m]
        if abs(P[i][0] - P[j][0]) < 0.5 and abs(P[i][1] - P[j][1]) > 5 \
                and P[i][0] < x0 + 80 and min(P[i][1], P[j][1]) > y0 + row_min:
            vert.append((min(P[i][1], P[j][1]), i, j))
    _, i, j = min(vert)
    xl = P[i][0]
    ends = {i, j}
    for k0, step in ((i, -1), (i, 1), (j, -1), (j, 1)):
        k = (k0 + step) % n
        while abs(P[k][0] - xl) < 0.5 and k not in ends:
            ends.add(k)
            k = (k + step) % n
    ys = [P[k][1] for k in ends]
    band = [P[k] for k in on if min(ys) - .5 <= P[k][1] <= max(ys) + .5]
    xr = max(p[0] for p in band)
    inner = sorted(p[0] for p in band if xl + 1 < p[0] < xr - 1)
    s1, s2 = inner[0], inner[-1]
    right = xr - s2
    out = bang.dup()
    for k in ends:
        out[k].x = s1 - right
    return out, s1 - xl, right


@op("evenBarTrimLeg")
def op_even_bar_trim_leg(ctx, font, spec, source_half):
    """방 발의 가로획 왼팔을 오른팔 길이로 늘이고, 변의 오른쪽 다리를 줄인다.

    程 은 Plex 에서 壬 가운데 가로획의 왼팔이 오른팔보다 짧다. 편수자료는 둘이 같다.
    왼팔을 늘이면 禾 의 오른쪽 다리가 그 위로 내려온다. 그래서 다리를 **다리 길이의
    `ratio` 만큼** 줄인다 — 아래 끝 두 점을 축을 따라 끌어올릴 뿐이라 굵기와 기울기는
    그대로다. 줄인 뒤에도 가로획에 닿으면 둘을 그대로 겹쳐 한 몸으로 합친다. 어느 쪽도
    잘라 내지 않는다.

        {"op": "evenBarTrimLeg", "ratio": 0.179, "cps": ["7a0b"]}

    굵은 체는 다리 끝이 방에 묻어 한 윤곽으로 오는데, 그때는 먼저 방의 옆선에서
    가른다(다리 끝 모서리는 제 두 변의 선을 이어 되살린다). 변은 가장 왼쪽 윤곽,
    방은 바닥이 0 아래로 내려가는 윤곽 가운데 가장 왼쪽 것이다.

      `ratio`    다리를 줄일 몫 — 다리 세로 길이 대비. 0.179 는 Thin 에서 −36 이다.
      `rowMin`   가운데 가로획을 고를 때 방 바닥에서 떨어진 최소 높이 (기본 80).
      `low`      방으로 칠 낮은 점의 높이 (기본 100) — 다리 끝보다 낮아야 한다.
    """
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = [c.dup() for c in glyph.foreground]
        k = min(range(len(cs)), key=lambda i: O.box(cs[i])[0])
        he = cs[k]
        yb0, yb1, sr = _cross_bar(he)
        others = [c for i, c in enumerate(cs) if i != k]
        split = _unfuse_leg(he, sr, yb0, spec.get("low", 100))
        if split is not None:
            he, bang = split
        else:
            cand = [i for i, c in enumerate(others) if O.box(c)[2] < 0 and O.box(c)[0] > sr]
            if not cand:
                print("evenBarTrimLeg: %s 에서 방을 못 찾았다" % glyph.glyphname)
                continue
            bang = others.pop(min(cand, key=lambda i: O.box(others[i])[0]))
        bang, was, arm = _even_bar(bang, spec.get("rowMin", 80))
        a, b, u, L = _leg_end(he, sr)
        cut = round(L * spec["ratio"])
        step = cut / u[1]
        for q in (a, b):
            he[q].x += u[0] * step
            he[q].y += u[1] * step
        from .ops import _hits, _polys
        touch = _hits(_polys([he])[0], _polys([bang]), 0.0)
        # 먹을 더하지 않은 것은 다시 짜지 않는다 — 닿을 때만 겹친 두 윤곽을 합친다
        relay(glyph, [others, [he, bang]], merge=touch)
        done.append("%s 왼팔 %d→%d · 다리 −%d%s%s" % (
            glyph.glyphname, round(was), round(arm), cut,
            " · 가름" if split is not None else "", " · 겹쳐 합침" if touch else ""))
    if done:
        print("evenBarTrimLeg: %s" % ", ".join(done))


@op("evenOverhang")
def op_even_overhang(ctx, font, spec, source_half):
    """맨 아래 가로선이 좌우로 빠져나온 길이를 같게 — 더 나온 쪽 끝만 안으로 옮긴다.

    益 의 皿 밑 가로선은 Plex 에서 왼쪽이 16~28 더 나와 있다. 가로선은 바닥이 가장
    낮은 윤곽의 아랫부분이고, 빠져나온 길이는 가로선 윗변에서 끝과 그 위로 올라가는
    옆선 사이를 잰다. 더 나온 쪽 끝의 점을 윗변·아랫변 모두 같은 x 로 옮기므로 끝은
    곧은 세로 모서리 그대로고 굵기도 그대로다.

        {"op": "evenOverhang", "cps": ["76ca"]}
    """
    done = []
    for glyph in selected_glyphs(font, spec):
        cs = [c.dup() for c in glyph.foreground]
        k = min(range(len(cs)), key=lambda i: O.box(cs[i])[2])
        c = cs[k]
        x0, x1, y0, _ = O.box(c)
        on = [p for p in c if p.on_curve]
        yt = min(p.y for p in on if p.y > y0 + 1)          # 가로선 윗변
        top = sorted(p.x for p in on if abs(p.y - yt) < .5)
        if len(top) < 4:
            print("evenOverhang: %s 에서 가로선 윗변을 못 찾았다" % glyph.glyphname)
            continue
        left, right = top[1] - top[0], top[-1] - top[-2]
        if abs(left - right) < 0.5:
            continue
        if left > right:
            end, to = top[0], top[1] - right
        else:
            end, to = top[-1], top[-2] + left
        for p in c:
            if abs(p.x - end) < .5 and p.y <= yt + .5:
                p.x = to
        relay(glyph, [cs], merge=False)
        done.append("%s %s %d→%d" % (glyph.glyphname, "왼" if left > right else "오른",
                                     round(max(left, right)), round(min(left, right))))
    if done:
        print("evenOverhang: %s" % ", ".join(done))


# --------------------------------------------------------------------------
# 없는 획을 제 획의 거울로
# --------------------------------------------------------------------------


def _pick_loop(loops, pt):
    """고리 여럿 가운데 `pt` 에 가장 가까운 점을 가진 것."""
    best = None
    for lp in loops:
        qs = [q for a, b, c in lp for q in ((a, c) if b is None else (a, b, c))]
        d = min((q[0] - pt[0]) ** 2 + (q[1] - pt[1]) ** 2 for q in qs)
        if best is None or d < best[0]:
            best = (d, lp)
    return best[1] if best else []


def _move_loop(nodes, mat):
    def T(p):
        return (mat[0] * p[0] + mat[2] * p[1] + mat[4], mat[1] * p[0] + mat[3] * p[1] + mat[5])
    return [(T(a), T(b) if b else None, T(c)) for a, b, c in nodes]


@op("mirrorStroke")
def op_mirror_stroke(ctx, font, spec, source_half):
    """乀 의 꼭짓점에서 왼쪽 아래로 갈라지는 삐침을 **제 乀 을 잘라 거울로 뒤집어** 더한다.

    丈 은 편수자료·맑은 고딕에서 乀 꼭짓점에서 짧은 삐침이 하나 더 갈라져 왼쪽
    아래로 뻗는다. Plex 어느 집안에도 이 획이 없어 남의 글자에서 가져올 수 없다.
    그래서 제 획을 쓴다 — 굵기가 저절로 여덟 굵기에 맞는다.

    1. 乀 의 꼭짓점(一 아래 왼쪽의 짧게 비스듬한 변의 왼끝)을 윤곽의 점으로 찾는다.
    2. 꼭짓점에서 乀 의 축(먹에서 잰다)을 따라 L 만큼, 축 둘레로 획 두께만큼의
       쐐기를 곡선 그대로 잘라 낸다 (`outline.loop_clip`).
    3. 꼭짓점을 지나는 세로축으로 거울 반전한다.
    4. 두 맨 위 꼭짓점이 k 만큼만 떨어지게 옮긴다. k = 둘째 꼭짓점 높이에서 그 획의
       두께다.
    5. 두 윤곽을 합치고(점으로만 닿으면 한 번에 안 합쳐져 두 번), 두 꼭짓점 사이의
       V 계곡 점을 **모두** 지워 편다.

    자리와 비율은 맑은 고딕에서 쟀다(먹 상자에 대한 몫).

        {"op": "mirrorStroke", "tip": [0.134, 0.433], "longer": 0.34,
         "rise": 1.0, "side": 2.0, "cps": ["4e08"]}

      `tip`     삐침 끝 복판 (먹 상자에 대한 몫 x, y)
      `longer`  굵을수록 길게 하는 몫 (Thin 0 → Bold `longer`, 굵기 차례로 고르게)
      `rise`    굵을수록 자리를 乀 윗머리 쪽으로 올리는 몫
      `side`    쐐기 옆선을 축에서 획 두께의 몇 배에 둘지 (기본 1.1). 축이 획 모서리
                에서 시작하고 乀 은 아래로 휘어 축에서 멀어지므로, 가는 굵기에서 작으면
                옆선이 먹을 깎아 삐침이 끝으로 갈수록 좁아진다 (丈 Thin 은 2.0 이 필요).
    """
    import numpy as np
    me = ctx.style
    same = sorted((st for st in ctx.recipe["styles"]
                   if st.get("italic", False) == me.get("italic", False)), key=lambda st: st["weight"])
    # 굵기 차례로 고르게 (Thin 0 … Bold 1) — weight 값은 Text 가 끼어 고르지 않다
    names = [st["name"] for st in same]
    tw = names.index(me["name"]) / float(len(names) - 1) if len(names) > 1 else 0.0
    t_mid = spec.get("tip", [0.134, 0.433])
    longer = spec.get("longer", 0.34)
    rise = spec.get("rise", 1.0)
    done = []
    for g in selected_glyphs(font, spec):
        wd = g.width
        cs = list(g.foreground)
        x0, x1, y0, y1 = O.bbox(cs)
        W, H = x1 - x0, y1 - y0
        m = O.part_mask(cs)

        def row(y):
            return O.runs(m[1000 - int(y)])
        # 一 의 아랫변
        ybar = None
        for y in range(int(y1), int(y0), -1):
            if any(t[1] - t[0] > 0.6 * W for t in row(y)):
                ybar = y
            elif ybar is not None:
                break
        # 乀 의 윗머리 — 一 아래 왼쪽의 짧게 비스듬한 변
        vtx = which = hi_y = None
        for c2 in cs:
            pts = [p for p in c2 if p.on_curve]
            for t in range(len(pts)):
                a2, b2 = pts[t], pts[(t + 1) % len(pts)]
                if not (y0 + 0.35 * H < a2.y < ybar - 2 and y0 + 0.35 * H < b2.y < ybar - 2):
                    continue
                if not (a2.x < x0 + 0.40 * W and b2.x < x0 + 0.40 * W):
                    continue
                lo, up = (a2, b2) if a2.x < b2.x else (b2, a2)
                dx, dy = abs(a2.x - b2.x), up.y - lo.y
                if not (0.015 * W < dx < 0.16 * W and -0.01 * H < dy < 0.10 * H):
                    continue
                if vtx is None or lo.y < vtx[1]:
                    vtx = (float(lo.x), float(lo.y))
                    hi_y = float(up.y)
                    which = (lo.x, lo.y, up.x, up.y)
        if vtx is None:
            print("mirrorStroke: %s 에서 乀 의 꼭짓점을 못 찾았다" % g.glyphname)
            continue
        vtx = (vtx[0], vtx[1] + rise * tw * (hi_y - vtx[1]))
        tx, ty = x0 + t_mid[0] * W, y0 + t_mid[1] * H
        ang = math.atan2(ty - vtx[1], tx - vtx[0])
        L = math.hypot(tx - vtx[0], ty - vtx[1]) * (1.0 + longer * tw)
        ty = vtx[1] + L * math.sin(ang)
        ym = (vtx[1] + ty) / 2.0
        em_ = [t for t in row(ym) if t[0] < x0 + 0.5 * W]
        thick = (em_[0][1] - em_[0][0]) if em_ else 0.08 * W
        # 乀 의 축 — 꼭짓점 아래 여러 높이에서 그 획의 한가운데
        cen = []
        for k in range(1, 9):
            yy = vtx[1] - L * k / 9.0
            rr = [t for t in row(yy) if t[0] < x0 + 0.6 * W]
            if rr:
                cen.append(((rr[0][0] + rr[0][1]) / 2.0, yy))
        if len(cen) < 3:
            print("mirrorStroke: %s 에서 乀 의 축을 못 쟀다" % g.glyphname)
            continue
        wx, wy = cen[-1][0] - vtx[0], cen[-1][1] - vtx[1]
        wl = math.hypot(wx, wy)
        wx, wy = wx / wl, wy / wl
        nxw, nyw = -wy, wx
        half = thick * spec.get("side", 1.1)
        wedge = []
        for c2 in cs:
            wedge.extend(O.arcs(c2))
        for A, B, C in ((wx, wy, -(wx * vtx[0] + wy * vtx[1] + L)),
                        (-wx, -wy, (wx * vtx[0] + wy * vtx[1])),
                        (nxw, nyw, -(nxw * vtx[0] + nyw * vtx[1] + half)),
                        (-nxw, -nyw, (nxw * vtx[0] + nyw * vtx[1] - half))):
            wedge = _pick_loop(O.loop_clip(wedge, A, B, C), vtx)
            if len(wedge) < 3:
                break
        if len(wedge) < 3:
            print("mirrorStroke: %s 의 乀 에서 쐐기를 못 잘라 냈다" % g.glyphname)
            continue
        mir = _move_loop(wedge, psMat.compose(psMat.translate(-vtx[0], 0.0),
                         psMat.compose(psMat.scale(-1.0, 1.0), psMat.translate(vtx[0], 0.0))))
        # k — 둘째 꼭짓점 높이에서 그 획의 두께
        y2 = which[1]
        rr = [t for t in row(y2) if t[0] <= which[0] + 2 <= t[1] + 2]
        if not rr:
            rr = [t for t in row(y2) if t[0] < x0 + 0.5 * W]
        k = (rr[0][1] - rr[0][0]) if rr else thick
        top_o = (float(which[2]), float(which[3]))
        top_m = (2 * vtx[0] - top_o[0], top_o[1])
        move_x = (top_o[0] - top_m[0]) - k
        mir = _move_loop(mir, psMat.translate(move_x, 0.0))
        lay = fontforge.layer()
        lay.is_quadratic = g.foreground.is_quadratic
        for c2 in cs:
            lay += c2.dup()
        lay += O.loop_contour(mir, g.foreground.is_quadratic)
        g.foreground = lay
        g.removeOverlap(); g.correctDirection()
        g.removeOverlap(); g.correctDirection()     # 점으로만 닿은 둘이 한 윤곽이 되게
        # V 계곡 — 두 꼭짓점 사이로 패인 점을 모두 지운다
        ax, bx = sorted((top_m[0] + move_x, top_o[0]))
        ytop = top_o[1]
        valley = None
        lay2 = fontforge.layer()
        lay2.is_quadratic = g.foreground.is_quadratic
        for c2 in g.foreground:
            pts = list(c2)
            n2 = len(pts)
            cand = [q for q in range(n2) if pts[q].on_curve and abs(pts[q].y - ytop) < 12
                    and ax - 25 < pts[q].x < bx + 25]
            ia = min(cand, key=lambda q: abs(pts[q].x - ax)) if cand else None
            ib = min(cand, key=lambda q: abs(pts[q].x - bx)) if cand else None
            if ia is not None and ia == ib:
                ib = None
            drop = set()
            if ia is not None and ib is not None:
                for st, en in ((ia, ib), (ib, ia)):
                    path = []
                    q = st
                    while True:
                        q = (q + 1) % n2
                        if q == en or len(path) > n2:
                            break
                        path.append(q)
                    if not path:
                        continue
                    lowest = min(pts[q].y for q in path)
                    if lowest < ytop - 1 and all(pts[q].y <= ytop + 1 for q in path) and len(path) < n2 // 2:
                        drop = set(path)
                        valley = len(path)
                        break
            nc = fontforge.contour()
            nc.is_quadratic = c2.is_quadratic
            for k2, p2 in enumerate(pts):
                if k2 not in drop:
                    nc += fontforge.point(p2.x, p2.y, p2.on_curve)
            nc.closed = c2.closed
            lay2 += nc
        g.foreground = lay2
        g.removeOverlap(); g.correctDirection()
        tidied, _ = O.tidy(list(g.foreground))
        lay3 = fontforge.layer()
        lay3.is_quadratic = g.foreground.is_quadratic
        for c2 in tidied:
            lay3 += c2
        g.foreground = lay3
        g.width = wd
        done.append("%s k %d · 계곡 %s점" % (g.glyphname, round(k), valley))
    if done:
        print("mirrorStroke: %s" % ", ".join(done))


# --------------------------------------------------------------------------
# 점 찍기
# --------------------------------------------------------------------------


@op("addDot")
def op_add_dot(ctx, font, spec, source_half):
    """者 계열의 耂 아래에 점을 하나 찍는다 — 같은 글꼴 灬 의 점을 떼어 눕혀 놓는다.

    편수자료의 者 는 耂 의 긴 가로획과 日 사이에 점이 있다(者 는 본디 이 점까지
    한 글자다). Plex JP 에는 없다. 점은 그리지 않고 點·黨 의 灬 에서 떼어 온다 —
    넷 가운데 기울기가 `angle` 에 가장 가까운 것을 골라 그 각으로 눕히고, 굵기는
    `thick`, 길이는 굵기마다 `length` 몫으로 줄인다. 셈은 `hapchija.dots` 에 있다.

    자리:
      * 세로 — 가로획 아랫변과 日 윗변 사이의 틈을 위 `topShare` : 아래로 나눈다.
        틈이 점보다 좁으면 아래로 묻어 위쪽에 `minTop` 만큼 흰 자리를 남긴다.
      * 가로 — 점의 축을 늘이면 가로획과 丿 이 만나는 모서리를 가리키게 한다.
        丿 은 가로획 오른끝에서 `rx` × 가로획 길이만큼 들어간 자리에서 찾는다
        (Source Han Sans K 에서 잰 몫).
      * 틈이 없는 굵기에서는 축을 따라 위로 올리되 위 획과 `clear` 만큼 띄운다.

        {"op": "addDot", "donors": "黨點", "angle": 50, "thick": 0.78,
         "length": {"Thin": 0.60, …, "Bold": 0.79}, "clear": 3,
         "at": {"者": {"win": [0, 1], "rx": 0.195}, …}, "cps": ["8005", …]}

    `at` 의 `win` 은 가로획을 찾을 가로 창(먹 폭 대비)이다 — 諸 渚 猪 는 변을 빼고,
    都 는 阝 를 뺀다. `dy` 는 글자마다 더 내리는 몫(틈 대비).
    """
    from fontTools.ttLib import TTFont
    from . import dots as D
    path = font.path
    C = dict(DONOR=spec.get("donors", "黨點"), ANGT=float(spec.get("angle", 50.0)),
             STH=float(spec.get("thick", 0.78)), LEN=float(spec.get("lengthDefault", 0.60)),
             LENW=spec.get("length", {}), TOPSHARE=float(spec.get("topShare", 0.70)),
             MINTOP=float(spec.get("minTop", 0.12)), SINK=float(spec.get("sink", 0.45)),
             WIN={k: tuple(v.get("win", [0, 1])) for k, v in spec["at"].items()},
             REF={k: {"rx": v["rx"]} for k, v in spec["at"].items()},
             DY={k: v["dy"] for k, v in spec["at"].items() if "dy" in v})
    size = float(spec.get("size", 1.0))
    clear = int(spec.get("clear", 3))
    tt = TTFont(path, lazy=True)
    dot = D.pick_dot(tt, C)
    if dot is None:
        print("addDot: 灬 에서 점을 못 골랐다")
        return
    a, dch, c, (x0, y0, x1, y1) = dot
    src = font[ord(dch)]
    di = None
    for i, k in enumerate(src.foreground):
        xs = [p.x for p in k]; ys = [p.y for p in k]
        if (abs(min(xs) - x0) < 1.5 and abs(min(ys) - y0) < 1.5
                and abs(max(xs) - x1) < 1.5 and abs(max(ys) - y1) < 1.5):
            di = i
            break
    if di is None:
        print("addDot: %s 에서 고른 점의 윤곽을 못 찾았다" % dch)
        return
    wname = ctx.style["name"]
    done = []
    for g in selected_glyphs(font, spec):
        ch = chr(g.unicode)
        if ch not in spec["at"]:
            continue
        b, gmask, _ = D.bar(path, ch, C)
        got = D.place(ch, b, gmask, dot, size, clear, wname, C)
        if not got:
            print("addDot: %s 에 놓을 자리를 못 찾았다" % g.glyphname)
            continue
        dx, dy, sl, st, cx, cy = got[:6]
        wd = g.width
        part = fontforge.layer()
        part.is_quadratic = src.foreground.is_quadratic
        part += src.foreground[di]
        part.transform(psMat.compose(
            psMat.translate(-(x0 + x1) / 2.0, -(y0 + y1) / 2.0),
            psMat.compose(psMat.rotate(math.radians(a)),
                          psMat.compose(psMat.scale(sl, st),
                                        psMat.compose(psMat.rotate(math.radians(-C["ANGT"])),
                                                      psMat.translate(cx + dx, cy + dy))))))
        new = fontforge.layer()
        new.is_quadratic = g.foreground.is_quadratic
        for k in g.foreground:
            new += k
        for k in part:
            new += k
        g.foreground = new
        g.removeOverlap(); g.correctDirection()
        g.width = wd
        done.append("%s(%s %.2f×%.2f @%d,%d)" % (ch, dch, sl, st, round(cx), round(cy)))
    if done:
        print("addDot: %s" % " ".join(done))
