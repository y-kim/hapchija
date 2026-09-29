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

import re

import fontforge
import psMat

from . import outline as O
from .ops import op, selected_glyphs
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


@op("swapSide")
def op_swap_side(ctx, font, spec, source_half):
    """변 또는 방 하나를 다른 글자에서 떼어 와 바꾼다 — 제 좌표 그대로.

    같은 글꼴에서 짜임이 같은 (변+방) 글자를 찾으면, 그 방이 앉는 자리가 이미
    맞다. 贈 의 曾 은 신자체라 위가 «丷» 인데 譄(U+8B44) 의 曾 은 구자체 «八»
    이고, 둘 다 변이 하나에 방이 曾 이다. 譄 의 방을 제 좌표째 옮기면 된다.

        {"op": "swapSide", "from": "8b44", "side": "right", "cps": ["8d08"]}
        {"op": "swapSide", "from": "uni98FE.vari2", "side": "left", "cps": ["9928"]}

    `side` 는 **기증자에서 가져올 쪽**이다. 받는 쪽에서는 그 반대쪽만 남긴다.
    눌러 맞추거나 갈라 밀지 않는다 — 가로로 누르면 방의 세로획이, 갈라 밀면
    가로획이 저 혼자 얇아진다.

    `from` 에 기증자를 **여럿** 적으면 앞에서부터 되는 것을 쓴다 — 굵기마다
    윤곽이 갈리기도 하고 녹기도 하기 때문이다. `fit` 을 `"box"` 로 적으면 받는
    쪽이 본디 그 자리에 두었던 상자에 맞춘다.

        {"op": "swapSide", "from": ["55a9", "7498"], "side": "right",
         "fit": "box", "cps": ["8f38"]}                       輸 — 兪 ← 喩 (Bold 는 瑜)

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
    spread = spec.get("spread")
    fit = spec.get("fit")
    cands = []
    for one in donor_list(font, spec):
        got, why = O.part_side(list(one.foreground), one.width, side)
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

    `legs` 를 `"between"` 으로 적으면 **흰 칸 둘 사이에 낀 세로획** 으로 본다
    (龜 의 배 한가운데 기둥). `"counters"` 로 적으면 세로선을 래스터로 찾지 않고 **네모의 흰 칸**
    에서 잰다. 日 처럼 흰 칸이 든 성분은 굵은 굵기에서 칸이 낮아져, 먹 줄기의
    길이로는 네모 전체가 한 기둥으로 보인다 (檀 Bold 의 日 은 386..927 이 통째로
    걸린다). 흰 칸은 굵기가 달라져도 그대로 흰 칸이라 이쪽이 흔들리지 않는다.

    얼마나 뻗는지는 둘 중 하나로 적는다.

      `by`     먹 키에 대한 비율. 획 끝에서 그만큼 더 간다 (浩 은 6.25% = 57).
      `toInk`  아래(위)에 따로 있는 먹까지. 그 획과 맞붙게 된다 (檀 의 맨 아래 一).

    `over` 는 남기고 갈 획 속으로, `overTo` 는 가서 닿는 획 속으로 파고들 몫이다.
    변끼리 딱 맞대면 그 자리에 실낱 같은 흰 줄이 남으므로 반드시 겹쳐야 한다.
    """
    up = spec.get("dir", "down") == "up"
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
        if spec.get("legs") == "between":
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
                to = frm + spec["by"] * (gy1 - gy0) * (1 if up else -1)
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
        center = (spec["center"] * (glyph.width or 1000) if "center" in spec
                  else (b[0] + b[1]) / 2)
        new, info = O.straighten(cs, best, pick, center)
        relay(glyph, [new], merge=False)
        done.append("%s 점%d → %d..%d" % (glyph.glyphname, len(pick), info[0], info[1]))
    if done:
        print("straightenStroke: %s" % "; ".join(done))


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
