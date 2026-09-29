"""윤곽을 재고, 가르고, 놓고, 자르는 연장.

한 글자의 획을 다른 글자에서 떼어 와 붙일 때 쓴다. 부수 글리프를 눌러 넣는
것과 달리 그 글꼴 자신의 획을 옮기므로 획 두께가 보존된다.

다루는 것은 **fontforge 윤곽 묶음** (`list(glyph.foreground)`) 이거나, 자를
때 쓰는 **도막 목록** (`arcs()` 가 만드는 고리) 이다. 함수 이름의 `loop_` 는
뒤쪽을 받는다는 뜻이다.

  재기    box bbox runs ink_spans part_mask clearance columns slices flat_cut
  가르기  outer point_runs split_parts split_seam split_apart
          necks carve_out one_corner take_part drop_part part_side loose_part
  놓기    dup fit_box slide stretch splice_detour
  넓히기  knife_bands widen_across
  세우기  straighten
  자르기  arcs loop_clip clip_contours loops_clip loop_* tidy

`part_mask` 를 거치는 것들 (`columns` `slices` `flat_cut` `knife_bands`
`clearance`) 은 윤곽을 판에 그려 보므로 numpy 와 Pillow 가 있어야 한다. 그
함수를 부르지 않으면 없어도 된다.

**Plex 의 윤곽은 겹쳐 있고 겹침이 지워져 있지 않다.** 윤곽을 나누는 방식도
굵기마다 다르다. 점을 따라 걸으려면 `removeOverlap()` 을 먼저 불러 위상을
한 가지로 만들어야 한다. 굵은 쪽에서만 어긋나는 일이 대개 이 때문이다.
"""

from __future__ import annotations

import math

import fontforge
import psMat


def box(contour):
    """윤곽 하나의 상자 — (x0, x1, y0, y1)."""
    xs = [p.x for p in contour]
    ys = [p.y for p in contour]
    return min(xs), max(xs), min(ys), max(ys)


def bbox(contours):
    """윤곽 묶음의 상자."""
    bs = [box(c) for c in contours]
    return (min(b[0] for b in bs), max(b[1] for b in bs),
            min(b[2] for b in bs), max(b[3] for b in bs))


def snap_x(contours, x, tol=4.0):
    """래스터로 잰 x 를 점이 실제로 선 자리에 붙인다.

    `columns` 나 `flat_cut` 이 돌려주는 값은 판에 그려 본 것이라 한 단위씩
    어긋난다. 그 자리에 이어 붙일 네모의 변은 획의 변과 **꼭 같아야** 한다 —
    한 단위 넘치면 획이 그만큼 굵어진 채로 남는다.
    """
    near = [p.x for c in contours for p in c if p.on_curve and abs(p.x - x) <= tol]
    return min(near, key=lambda v: (abs(v - x), v)) if near else x


def snap_y(contours, y, tol=4.0):
    """`snap_x` 의 세로 짝."""
    near = [p.y for c in contours for p in c if p.on_curve and abs(p.y - y) <= tol]
    return min(near, key=lambda v: (abs(v - y), v)) if near else y


def runs(row):
    """한 줄에서 먹이 이어진 구간들 — [(x0, x1), …]."""
    import numpy as np
    idx = np.nonzero(row)[0]
    if len(idx) == 0:
        return []
    out = []
    s = p = idx[0]
    for i in idx[1:]:
        if i == p + 1:
            p = i
            continue
        out.append((int(s), int(p)))
        s = p = i
    out.append((int(s), int(p)))
    return out


def ink_spans(mask, x0, x1, lo, hi, base=1000):
    """세로로 훑어 먹이 있는 구간들 — [(y_low, y_high), …], 위에서 아래로."""
    out = []
    cur = None
    for y in range(int(hi), int(lo) - 1, -1):
        r = base - y
        on = mask[r, int(x0):int(x1)].any() if 0 <= r < mask.shape[0] else False
        if on:
            cur = [y, y] if cur is None else [cur[0], y]
        elif cur:
            out.append((cur[1], cur[0]))
            cur = None
    if cur:
        out.append((cur[1], cur[0]))
    return out


def part_mask(contours, n=1200, base=1000):
    """윤곽 묶음만 따로 판에 그린다 — clearance() 가 쓴다."""
    import numpy as np
    from PIL import Image, ImageDraw
    acc = np.zeros((n, n), bool)
    for c in contours:
        im = Image.new('L', (n, n), 0)
        ImageDraw.Draw(im).polygon([(p.x, base - p.y) for p in c], fill=255)
        acc ^= (np.array(im) > 0)
    return acc


def clearance(left, right, n=1200, base=1000):
    """변과 방 사이의 **실제** 틈 — 높이마다 재어 가장 좁은 값. 음수면 겹친 것.

    상자끼리 견주면 안 된다. 貝 의 오른끝은 아래쪽 八 다리이고 曾 의 왼끝은
    위쪽 삐침 끝이라, 상자로는 겹쳐 보여도 높이가 달라 실제로는 안 닿는다.
    """
    import numpy as np
    A = part_mask(left, n, base)
    B = part_mask(right, n, base)
    worst = None
    for r in range(n):
        ax = np.nonzero(A[r])[0]
        bx = np.nonzero(B[r])[0]
        if len(ax) == 0 or len(bx) == 0:
            continue
        d = int(bx.min() - ax.max())
        if worst is None or d < worst:
            worst = d
    return worst



# ─── 가르기 ──────────────────────────────────────────────────────────────

def outer(contours):
    """바깥 윤곽의 번호 — 점이 가장 많은 것.

    한자 글리프에서 바깥 윤곽은 거의 언제나 점이 가장 많다. 상자로 고르면
    삐침이 바깥으로 뻗은 굵은 굵기에서 엉뚱한 것을 짚는다.
    """
    return max(range(len(contours)), key=lambda i: len(contours[i]))


def point_runs(contour, pick):
    """`pick(점)` 이 참인 점들의 **이어진 무리**들. 감아 도는 무리는 하나로 잇는다.

    다리·기둥처럼 한 윤곽 안에서 여러 갈래를 집을 때 쓴다. 돌아오는 것은
    점 번호의 목록들.
    """
    pts = list(contour)
    n = len(pts)
    hit = [i for i in range(n) if pick(pts[i])]
    if not hit:
        return []
    out = []
    cur = [hit[0]]
    for i in hit[1:]:
        if i == cur[-1] + 1:
            cur.append(i)
        else:
            out.append(cur)
            cur = [i]
    out.append(cur)
    if len(out) > 1 and out[0][0] == 0 and out[-1][-1] == n - 1:
        out[0] = out[-1] + out[0]
        out.pop()
    return out


def split_parts(contours, width, min_share=0.35):
    """윤곽을 왼쪽 끝으로 세워 가장 넓은 틈에서 변/방을 가른다.

    변의 획이 방 밑으로 뻗어도(土 의 가로획처럼) 윤곽만 따로면 갈라진다.
    갈리지 않으면 (None, None) — 그때는 split_run() 으로 점열을 가른다.
    """
    cs = list(contours)
    if not cs:
        return None, None
    # **흰 칸은 가르는 자리가 될 수 없다.** 칸은 저를 감싼 먹에 딸린 것이라,
    # 칸의 왼끝에서 가르면 그 몸이 두 동강 난다 (輸 Medium 에서 車 의 칸이
    # 방 쪽으로 넘어가 방 상자가 258 부터로 잡혔다). 감김 방향으로 가린다 —
    # 상자가 남의 상자 안에 들었는지로 보면 안 된다. 틀 안에 놓인 획도 그
    # 상자 안에 통째로 들어 있다 (羽 의 오른쪽 삐침).
    bs = [box(c) for c in cs]
    ink = _turn(max(cs, key=lambda c: len(list(c))))
    body = [i for i, c in enumerate(cs) if _turn(c) == ink]
    if len(body) < 2:
        return None, None
    holes = [i for i in range(len(cs)) if i not in set(body)]

    def host_of(h):
        """이 흰 칸을 감싼 몸 — 없으면 복판이 가장 가까운 몸."""
        got = [i for i in body
               if bs[i][0] <= bs[h][0] and bs[h][1] <= bs[i][1]
               and bs[i][2] <= bs[h][2] and bs[h][3] <= bs[i][3]]
        if got:
            return min(got, key=lambda i: (bs[i][1] - bs[i][0]) * (bs[i][3] - bs[i][2]))
        mid = (bs[h][0] + bs[h][1]) / 2.0
        return min(body, key=lambda i: abs((bs[i][0] + bs[i][1]) / 2.0 - mid))

    home = {h: host_of(h) for h in holes}      # 칸마다 딸릴 몸 — 하나도 빠뜨리지 않는다

    def share(idx):
        got = set(idx)
        return [cs[i] for i in range(len(cs))
                if i in got or (i in home and home[i] in got)]

    order = sorted(body, key=lambda i: bs[i][0])
    best = None
    for k in range(1, len(order)):
        left = share(order[:k])
        right = share(order[k:])
        # 잣대가 둘이다. **참된 틈**(왼 무리의 오른끝 ↔ 오른 무리의 왼끝)이 있으면
        # 그것으로 고른다 — 왼끝끼리의 거리만 보면 변 **안**에서 갈린다: 贈 Thin 의
        # 몸은 왼끝이 47·106·277·437·462·506 이라 왼끝 거리는 106→277 이 171 로
        # 가장 넓지만, 그 자리는 貝 의 오른쪽 아래 획(277..389)을 방으로 넘긴다.
        # 참된 틈으로 재면 거기는 -76(겹침)이고 437 자리가 +48 이다.
        #
        # 그러나 변과 방이 가로로 **겹쳐 앉는** 글자도 있다 (僧·益·輸·館 은 어느
        # 자리로 갈라도 참된 틈이 음수다). 그때까지 못 가른다고 하면 안 되므로,
        # 틈이 있는 자리가 하나도 없을 때만 옛 잣대(왼끝 거리)로 고른다.
        near = bs[order[k]][0] - max(bs[i][0] for i in order[:k])
        if near <= 0:
            continue
        x0, x1, _, _ = bbox(right)
        if x1 - x0 < min_share * width:
            continue
        if max(box(c)[1] for c in left) > x1:
            continue
        d = min(box(c)[0] for c in right) - max(box(c)[1] for c in left)
        rank = (1, d) if d > 0 else (0, near)
        if best is None or rank > best[0]:
            best = (rank, left, right)
    return (None, None) if best is None else (best[1], best[2])


def split_seam(contour, side='right', tol=2, min_points=6):
    """한 윤곽에 붙은 두 몸을 **맞댄 세로 변**에서 곧게 가른다 — (고리, 자른 x).

    removeOverlap 이 두 몸을 한 윤곽으로 합쳤는데 맞닿은 데가 점이 아니라 변인
    경우다(館 은 飠 의 人 오른쪽 끝과 官 의 宀 왼쪽 끝이 x=445 에서 맞닿는다).
    시작과 끝의 x 가 같고 그 사이 점이 모두 한쪽에만 있는 점열을 찾는다.
    그런 것이 여럿이면 가장 넓은 덩이를 고른다.
    """
    pts = list(contour)
    n = len(pts)
    best = None
    for i in range(n):
        for length in range(min_points, n - min_points + 1):
            j = (i + length) % n
            if not (pts[i].on_curve and pts[j].on_curve):
                continue
            if abs(pts[i].x - pts[j].x) > tol:
                continue
            t = (pts[i].x + pts[j].x) / 2.0
            run = [pts[(i + k) % n] for k in range(length + 1)]
            if side == 'right':
                if any(p.x < t - tol for p in run):
                    continue
            else:
                if any(p.x > t + tol for p in run):
                    continue
            w = max(p.x for p in run) - min(p.x for p in run)
            if best is None or w > best[0]:
                best = (w, run, t)
    if best is None:
        return None, None
    _, run, t = best
    nc = fontforge.contour()
    nc.is_quadratic = contour.is_quadratic
    for p in run:
        nc += fontforge.point(p.x, p.y, p.on_curve)
    nc.closed = True
    return nc, t


def split_apart(contour, side='left', min_points=6, weld=10.0):
    """맞댄 자리가 변이 아니라 비스듬할 때, 점열을 왼쪽 몸/오른쪽 몸으로 가른다.

    가져올 쪽이 글리프의 왼끝(또는 오른끝)을 품고 나머지 쪽이 반대 끝을 품는
    가름 가운데, **닫는 자리가 가장 짧은** 것을 고른다. 그 자리가 두 몸이 본디
    만나던 곳이다(飾 의 이체자는 人 의 오른팔이 방의 윗변 위로 비스듬히 걸친다).
    """
    pts = list(contour)
    n = len(pts)
    xs = [p.x for p in pts]
    imin = xs.index(min(xs))
    imax = xs.index(max(xs))
    want, other = (imin, imax) if side == 'left' else (imax, imin)
    best = None
    for i in range(n):
        for length in range(min_points, n - min_points + 1):
            j = (i + length) % n
            if not (pts[i].on_curve and pts[j].on_curve):
                continue
            idx = {(i + k) % n for k in range(length + 1)}
            if want not in idx or other in idx:
                continue
            d = ((pts[i].x - pts[j].x) ** 2 + (pts[i].y - pts[j].y) ** 2) ** 0.5
            if best is None or d < best[0]:
                best = (d, [pts[(i + k) % n] for k in range(length + 1)])
    if best is None:
        return None, None
    d, run = best
    nc = fontforge.contour()
    nc.is_quadratic = contour.is_quadratic
    if d < weld:
        nc += fontforge.point((run[0].x + run[-1].x) / 2, (run[0].y + run[-1].y) / 2, True)
        run = run[1:-1]
    for p in run:
        nc += fontforge.point(p.x, p.y, p.on_curve)
    nc.closed = True
    return nc, d


def necks(contours, near=60.0, apart=6):
    """맞붙은 자리 — 서로 가까우나 윤곽을 따라서는 먼 점 쌍을 모은다.

    획이 녹아 한 윤곽이 되면 목이 없어 보이지만, 맞붙은 자리에는 반드시 이런
    쌍이 남는다. 한 획의 가장자리와 다른 획(또는 흰 칸)의 가장자리가 거기서
    만나기 때문이다. 같은 윤곽 안의 쌍은 점열을 따라 `apart` 보다 멀어야
    한다 — 이웃한 점은 당연히 가깝지 목이 아니다.

    돌아오는 것은 (거리, 윤곽a, 점a, 윤곽b, 점b) 의 목록, 가까운 것부터.
    """
    out = []
    for a in range(len(contours)):
        pa = [p for p in contours[a] if p.on_curve]
        ia = [k for k, p in enumerate(contours[a]) if p.on_curve]
        for b in range(a, len(contours)):
            pb = [p for p in contours[b] if p.on_curve]
            ib = [k for k, p in enumerate(contours[b]) if p.on_curve]
            n = len(contours[b])
            for u, p in zip(ia, pa):
                for v, q in zip(ib, pb):
                    if a == b:
                        if v <= u:
                            continue
                        step = min(v - u, n - (v - u))
                        if step < apart:
                            continue
                    d = ((p.x - q.x) ** 2 + (p.y - q.y) ** 2) ** 0.5
                    if d <= near:
                        out.append((d, a, u, b, v))
    out.sort()
    return out



def carve_out(contours, rect, side='right', near=60.0, apart=6, min_points=6,
              restore=True, take='in', at=None, slack=20.0):
    """조각을 떼어 낸다 — 목을 **만날 때마다** 이어서.

    **몇 군데에서 붙었는지는 중요하지 않다.** 가지려는 조각의 테두리를 훑다 목을
    만나면 잇고, 갈린 것이 아직 네모를 넘치면 다시 만나 또 잇는다. 한 번 이어
    끝나는 것(붙은 자리가 하나)이나 두 번 이어야 하는 것(획 끝이 이웃에 닿아 그
    옆 흰 자리가 갇힌 것)이나 같은 일의 횟수 차이일 뿐이다. 그래서 여기서는
    `_carve_once` 를 조각이 네모 안에 들 때까지 되풀어 부른다 (`slack` 만큼은
    넘쳐도 봐준다). `take='out'` — 버리는 쪽 — 은 남는 고리가 여럿이 되므로
    한 번만 자른다.

    돌아오는 것은 (윤곽, 쓴 윤곽 번호 집합, 어떻게).
    """
    got, used, how = _carve_once(contours, rect, side, near, apart, min_points,
                                 restore, take, at)
    if got is None or take != 'in':
        return got, used, how
    hows = [how]

    def area(c):
        b = box(c)
        return (b[1] - b[0]) * (b[3] - b[2])

    for _ in range(4):
        b = box(got)
        if (rect[0] - slack <= b[0] and b[1] <= rect[1] + slack
                and rect[2] - slack <= b[2] and b[3] <= rect[3] + slack):
            break                       # 네모 안에 들었다 — 다 갈렸다
        # 아직 남은 윤곽도 함께 넘긴다. 다음에 만날 목은 조각과 **흰 칸** 사이일
        # 수 있고 (획 끝이 이웃에 닿아 그 옆이 갇힌 자리), 그때는 그 흰 칸의 변이
        # 조각의 옆선이 된다. 조각만 넘기면 그 길이 막힌다.
        rest = [(i, c) for i, c in enumerate(contours) if i not in used]
        nxt, u2, how2 = _carve_once([got] + [c for _, c in rest], rect, side,
                                    near, apart, min_points, restore, take, at)
        if nxt is None or area(nxt) >= area(got):
            break
        used = used | {rest[j - 1][0] for j in u2 if j >= 1}
        got, hows = nxt, hows + [how2]
    return got, used, ' + '.join(h for h in hows if h)


def _carve_once(contours, rect, side='right', near=60.0, apart=6, min_points=6,
                restore=True, take='in', at=None):
    """목 한 자리에서 고리를 가른다 — `carve_out` 이 되풀어 부른다.

    네모로 오려 내면 자형에 없던 직선·사선 단면이 남는다. 그러지 않고,
    맞붙은 자리의 점 쌍(목, `necks`)을 찾아 **그 점끼리 이어** 윤곽을 두 고리로
    가른 뒤 한 쪽만 가진다. 그래서 단면이 본디 있던 점과 변으로만 이루어진다.
    네모는 자르는 선이 아니라 **어느 쪽을 가질지 고르는 자리**일 뿐이다.

      · 목의 두 점이 **같은 윤곽**에 있으면 한 번 이으면 두 고리로 갈린다.
      · 두 점이 **서로 다른 윤곽**에 있으면 한 번 이어 봐야 두 윤곽이 하나로
        합쳐질 뿐이라 갈리지 않는다. 두 군데를 이어야 조각이 닫힌다.
        그런 윤곽은 획 끝이 이웃 획에 닿아 그 옆의 흰 자리가 갇힐 때 생긴다
        (갇히기 전에는 옆으로 트여 있어 윤곽이 없다). 둘째 윤곽의 변 가운데
        side 쪽(오른쪽이면 x 가 큰 쪽)이 조각의 옆선이 된다.

    네모가 두 몫을 겸하면 안 된다. `rect` 는 **어느 쪽을 가질지**, `at` 은
    **어디를 자를지** 다. 조각과 목이 떨어져 있을 때(획이 가로획 위에 앉은 것처럼)
    한 네모로 둘을 다 덮으려면 조각을 품을 만큼 넓혀야 하고, 그러면 엉뚱한 목을
    문다. `at` 을 주지 않으면 `rect` 를 쓴다.

    `restore` 면 이은 자리마다 `one_corner` 로 두 점을 한 점으로 되살린다.
    `take='out'` 이면 조각이 아니라 **남는 쪽**을 돌려준다 — 그 조각을 버리고
    몸통만 쓸 때 쓴다.

    돌아오는 것은 (윤곽, 쓴 윤곽 번호 집합, 어떻게).
    """
    x0, x1, y0, y1 = rect

    a0, a1, b0, b1 = at if at is not None else rect

    def inbox(p):
        return x0 <= p.x <= x1 and y0 <= p.y <= y1

    def atbox(p):
        return a0 <= p.x <= a1 and b0 <= p.y <= b1

    def arc(c, u, v, step):
        n = len(c)
        out = [u]
        k = u
        while k != v and len(out) <= n:
            k = (k + step) % n
            out.append(k)
        return out

    def score(c, path):
        pts = [c[k] for k in path if c[k].on_curve]
        return sum(1 for p in pts if inbox(p)) / float(len(pts) or 1)

    def build(pairs):
        nc = fontforge.contour()
        nc.is_quadratic = pairs[0][0].is_quadratic
        seams = []
        for c, path in pairs:
            if len(nc):
                seams.append((len(nc) - 1, len(nc)))
            for k in path:
                nc += fontforge.point(c[k].x, c[k].y, c[k].on_curve)
        nc.closed = True
        seams.append((len(nc) - 1, 0))
        if not restore:
            return nc, 0
        fixed = [0, 0]                      # 되살린 모서리 수, 되살린 곡선 수
        # 이은 자리를 **번호가 아니라 자리로** 적어 둔다 — 한 군데를 되살리면
        # 점이 하나 줄어 뒤 번호가 다 밀린다.
        marks = [((nc[u].x, nc[u].y), (nc[v].x, nc[v].y)) for u, v in seams]
        for pu, pv in marks:
            pts = list(nc)
            ku = next((k for k, q in enumerate(pts)
                       if abs(q.x - pu[0]) < .01 and abs(q.y - pu[1]) < .01), None)
            kv = next((k for k, q in enumerate(pts)
                       if abs(q.x - pv[0]) < .01 and abs(q.y - pv[1]) < .01), None)
            if ku is None or kv is None or (kv - ku) % len(pts) != 1:
                continue
            # 잘린 것이 곡선이면 곡선으로, 꼭짓점이면 꼭짓점으로 되살린다.
            got = one_curve(nc, [ku, kv])
            if got is not None:
                nc, fixed[1] = got, fixed[1] + 1
                continue
            got = one_corner(nc, [ku, kv])
            if got is not None:
                nc, fixed[0] = got, fixed[0] + 1
        return nc, fixed

    ns = necks(contours, near, apart)
    if at is not None:
        ns = [t for t in ns
              if atbox(contours[t[1]][t[2]]) and atbox(contours[t[3]][t[4]])]
    if not ns:
        return None, set(), None

    # ① 목의 두 점이 같은 윤곽에 있다 — 한 군데를 이으면 두 고리로 갈린다.
    #    가장 가까운 목부터 집으면 안 된다. 어디를 자를지 정하는 것은 거리가
    #    아니라 **고른 네모** 다 (殻 Bold 에서 가장 가까운 목은 几 와 殳 의 위쪽
    #    맞댄 자리인데, 그것을 이으면 殳 의 갈고리가 조각에 남는다). 같은 윤곽의
    #    목을 다 훑어 남는 쪽이 네모에 가장 잘 드는 것을 고른다.
    #    가질 쪽을 기준으로 고르고, 버리는 쪽(take='out')은 **그 반대 도막** 을
    #    돌려준다. 버리는 쪽을 점수로 따로 고르면 네모 밖 아무 부스러기나 고를
    #    수 있다 (極 Bold 에서 10점짜리 조각만 남고 몸통이 통째로 사라졌다).
    one = None
    for d, a, u, b, v in ns:
        if a != b:
            continue
        c = contours[a]
        ways = [w for w in (arc(c, u, v, 1), arc(c, v, u, 1)) if len(w) >= min_points]
        if not ways:
            continue
        w = max(ways, key=lambda t: score(c, t))
        sc = score(c, w)
        if one is None or sc > one[0]:
            other = min(ways, key=lambda t: score(c, t))
            one = (sc, d, a, w if take == 'in' else other)
    if one is not None and one[0] >= 0.5:
        _, d, a, w = one
        nc, fixed = build([(contours[a], w)])
        return nc, {a}, ('목 하나로 가름 (%d 단위 · %d점 · %s)'
                         % (round(d), len(nc), _fixed_says(fixed)))

    # ② 목의 두 점이 서로 다른 윤곽에 있다 — 두 군데를 이어야 조각이 닫힌다.
    #    첫 목 하나만 보고 짝을 못 찾으면 포기하면 안 된다. 가장 가까운 목이
    #    엉뚱한 데일 수 있다 (殻 의 几 를 뗄 때 맨 앞은 冖 과 殳 사이의 목이고,
    #    쓸 것은 几 의 윗변과 흰 슬릿 사이의 목 둘이다). 짝을 다 훑어 **고른
    #    네모에 가장 잘 드는** 조각을 낸다.
    def far(p, q):
        return ((p.x - q.x) ** 2 + (p.y - q.y) ** 2) ** 0.5 >= near

    def bridge(a, u1, u2, b, v1, v2):
        """윤곽 a 의 한 도막과 윤곽 b 의 변을 이어 고리를 만든다."""
        ca, cb = contours[a], contours[b]
        ways_a = [arc(ca, u1, u2, 1), arc(ca, u2, u1, 1)]
        pa = (max if take == 'in' else min)(ways_a, key=lambda t: score(ca, t))
        if pa[0] != u1:
            u1, u2, v1, v2 = u2, u1, v2, v1        # 잇는 차례를 맞춘다
        ways_b = [arc(cb, v2, v1, 1), arc(cb, v2, v1, -1)]
        key = (lambda t: sum(cb[k].x for k in t) / float(len(t)))
        big = (side == 'right') == (take == 'in')
        pb = max(ways_b, key=key) if big else min(ways_b, key=key)
        if len(pa) < min_points or len(pb) < 2:
            return None
        return build([(ca, pa), (cb, pb)]), len(pa), len(pb)

    best = None
    for t, (d1, a, u1, b, v1) in enumerate(ns):
        for d2, a2, u2, b2, v2 in ns[t + 1:]:
            if (a2, b2) != (a, b):
                continue
            if not (far(contours[a][u2], contours[a][u1]) and
                    far(contours[b][v2], contours[b][v1])):
                continue
            got = bridge(a, u1, u2, b, v1, v2)
            if got is None:
                continue
            (nc, fixed), na, nb = got
            pts = [p for p in nc if p.on_curve]
            sc = sum(1 for p in pts if inbox(p)) / float(len(pts) or 1)
            how = ('목 둘로 가름 (%d·%d 단위 · 획 %d점 + 칸 %d 의 변 %d점 → %d점 · '
                   '%s)' % (round(d1), round(d2), na, b, nb, len(nc),
                            _fixed_says(fixed)))
            if best is None or sc > best[0]:
                best = (sc, nc, {a, b}, how)
            break                      # 이 첫 목의 짝은 하나면 된다
    if best is None or best[0] < 0.5:
        return None, set(), None
    return best[1], best[2], best[3]


def intact(before, after, drop, moved=()):
    """복원 뒤 체커 — 남은 윤곽이 손상되지 않았는지 본다.

    복원은 이은 자리의 두 점을 꼭짓점 하나로 되돌리는 일이다. 그 밖의 점은
    **자리도 차례도 조종점 여부도** 그대로여야 한다. 하나라도 어긋나면 그
    복원은 버린다 — 자형이 조금이라도 달라지는 편보다 각이 진 채 두는 편이 낫다.

    `moved` 에 적은 점만 자리가 달라져도 된다. 곡선이 닿은 자리에서는 끝점이
    옮겨지므로 조종점을 다시 잡아야 본디 지나던 길을 그대로 지나기 때문이다.

    돌아오는 것은 (참·거짓, 까닭).
    """
    b, a = list(before), list(after)
    n = len(b)
    d = {i % n for i in drop}
    mv = {i % n for i in moved}
    if len(a) != n - len(d) + 1:
        return False, '점이 %d 이어야 하는데 %d' % (n - len(d) + 1, len(a))
    idx = [i for i in range(n) if i not in d]
    for s2 in range(len(a)):                     # 어느 점이 새 꼭짓점인지
        rest = a[s2 + 1:] + a[:s2]
        for r in range(len(idx)):                # 돌림 차례를 맞춰 본다
            order = idx[r:] + idx[:r]
            good = True
            for p, i in zip(rest, order):
                if p.on_curve != b[i].on_curve:
                    good = False
                    break
                if i in mv:
                    continue
                if abs(p.x - b[i].x) > .01 or abs(p.y - b[i].y) > .01:
                    good = False
                    break
            if good:
                why = '남은 %d점 그대로' % len(idx)
                if mv:
                    why += ' (조종점 %d개는 곡선을 늘리느라 다시 잡음)' % len(mv)
                return True, why
    return False, '남은 점의 자리나 차례가 달라졌다'


def _extend_quad(P0, P1, P2, C):
    """2차 곡선 (P0,P1,P2) 의 P0 쪽을 C 까지 늘렸을 때의 새 조종점.

    끝점만 옮기면 곡선이 통째로 달라진다. 곡선을 t<0 쪽으로 늘리면 본디 지나던
    길(t 0..1)은 그대로 지나고 앞쪽만 자란다. 늘린 몫 m 은 접선 방향으로 잰다.
    """
    tx, ty = P0[0] - P1[0], P0[1] - P1[1]                 # 접선(뒤로)
    kx, ky = P0[0] - 2 * P1[0] + P2[0], P0[1] - 2 * P1[1] + P2[1]
    tl = (tx * tx + ty * ty) ** 0.5
    if tl < 1e-9:
        return None
    ux, uy = tx / tl, ty / tl
    lam = (C[0] - P0[0]) * ux + (C[1] - P0[1]) * uy
    if lam <= 0:
        return None
    ku = kx * ux + ky * uy
    if abs(ku) < 1e-9:
        m = lam / (2 * tl)
    else:
        disc = 4 * tl * tl + 4 * ku * lam
        if disc < 0:
            return None
        m = (-2 * tl + disc ** 0.5) / (2 * ku)
    if not (0 < m < 4):
        return None
    return (C[0] + (1 + m) * ((1 + m) * (P1[0] - P0[0]) - m * (P2[0] - P1[0])),
            C[1] + (1 + m) * ((1 + m) * (P1[1] - P0[1]) - m * (P2[1] - P1[1])))


def one_corner(contour, drop, far=400.0, tol=1e-9):
    """잘린 자리를 도로 한 점으로 되살린다 — 점이 하나 준다.

    맞붙은 자리를 이어 가르면 그 자리에 점이 둘 생긴다. 본디는 두 변이 한
    점에서 만나던 것을, 겹친 만큼 **삼각형으로 잘라 낸** 꼴이다. 그 두 점에
    닿는 두 변을 그대로 늘려 만나는 자리를 구하면 잘려 나간 꼭짓점이 돌아온다.
    두 점이 한 점이 되니 점 수는 하나 줄어든다.

    `drop` 은 없앨 점의 번호(이어진 한 무리). 변의 방향은 무리 바로 바깥의
    점과 무리 끝점으로 잡는다 — 바깥 점이 조종점이면 그것이 곧 그 자리의
    접선이다.

    **남는 윤곽은 손대지 않는다.** 닿은 변이 곡선이면 끝점이 옮겨지는 만큼
    조종점을 다시 잡아 곡선을 늘린다(`_extend_quad`) — 본디 지나던 길은 그대로
    지난다. 마친 뒤 `intact` 로 확인하고, 어긋나면 손대지 않은 채 None.
    """
    pts = list(contour)
    n = len(pts)
    if n < 4 or not drop:
        return None
    d = sorted({i % n for i in drop})
    cuts = [k for k in range(len(d)) if d[k] != (d[k - 1] + 1) % n]
    if len(cuts) > 1:
        return None
    if cuts:
        d = d[cuts[0]:] + d[:cuts[0]]
    a, b = d[0], d[-1]
    A, B = pts[a], pts[b]
    if not (A.on_curve and B.on_curve):
        return None                            # 조종점을 없애면 곡선이 망가진다
    u1, v1 = pts[(a - 1) % n], pts[(b + 1) % n]
    dx1, dy1 = A.x - u1.x, A.y - u1.y
    dx2, dy2 = B.x - v1.x, B.y - v1.y
    den = dx1 * dy2 - dy1 * dx2
    if abs(den) < tol:
        return None
    t = ((B.x - A.x) * dy2 - (B.y - A.y) * dx2) / den
    cx, cy = A.x + t * dx1, A.y + t * dy1
    sgn = ((cx - B.x) * dx2 + (cy - B.y) * dy2) / (dx2 * dx2 + dy2 * dy2)
    if t <= 0 or sgn <= 0:
        return None
    if max(((cx - A.x) ** 2 + (cy - A.y) ** 2) ** 0.5,
           ((cx - B.x) ** 2 + (cy - B.y) ** 2) ** 0.5) > far:
        return None

    def on_at(k, step):
        """k 에서 step 쪽으로 가며 만나는 on-curve 자리 (2차 곡선의 암묵 점 포함)."""
        p, q = pts[k % n], pts[(k + step) % n]
        return (q.x, q.y) if q.on_curve else ((p.x + q.x) / 2.0, (p.y + q.y) / 2.0)

    new = {}                                    # 다시 잡을 조종점
    if not u1.on_curve:                         # A 에 닿은 변이 곡선
        got = _extend_quad((A.x, A.y), (u1.x, u1.y), on_at((a - 1) % n, -1), (cx, cy))
        if got is None:
            return None
        new[(a - 1) % n] = got
    if not v1.on_curve:                         # B 에 닿은 변이 곡선
        got = _extend_quad((B.x, B.y), (v1.x, v1.y), on_at((b + 1) % n, 1), (cx, cy))
        if got is None:
            return None
        new[(b + 1) % n] = got

    keep = []
    i = (b + 1) % n
    while True:
        keep.append(i)
        if i == (a - 1) % n:
            break
        i = (i + 1) % n
    nc = fontforge.contour()
    nc.is_quadratic = contour.is_quadratic
    nc += fontforge.point(cx, cy, True)
    for i in keep:
        x, y = new.get(i, (pts[i].x, pts[i].y))
        nc += fontforge.point(x, y, pts[i].on_curve)
    nc.closed = contour.closed
    ok, _ = intact(contour, nc, d, new.keys())   # 복원 뒤 체커
    return nc if ok else None


def _fixed_says(fixed):
    """되살린 자리를 말로 — (모서리 수, 곡선 수)."""
    bits = []
    if fixed[0]:
        bits.append('되살린 모서리 %d' % fixed[0])
    if fixed[1]:
        bits.append('되살린 곡선 %d' % fixed[1])
    return ' · '.join(bits) if bits else '되살린 것 없음'


def _meet(p, dp, q, dq):
    """두 직선 p+s·dp 와 q+t·dq 가 만나는 자리 — 나란하면 None."""
    den = dp[0] * dq[1] - dp[1] * dq[0]
    if abs(den) < 1e-9:
        return None
    s = ((q[0] - p[0]) * dq[1] - (q[1] - p[1]) * dq[0]) / den
    return (p[0] + s * dp[0], p[1] + s * dp[1])


def one_curve(contour, drop):
    """**곡선이 잘린 자리를 되살린다** — 두 접선이 만나는 자리를 조종점으로 삼는다.

    `one_corner` 의 곡선 짝이다. 그쪽은 두 변을 늘려 만나는 자리로 꼭짓점을
    되살리지만, 잘린 것이 둥근 모서리이면 그렇게 하면 모서리가 밖으로 부푼다.

    곡선은 다르게 잘린다. 이웃 획의 끝이 모서리를 파고들면 그 자리에 **남의
    끝점**이 하나 끼어들고, 모서리의 곡선은 그 점부터 시작하는 토막으로 줄어든다
    (殻 SemiBold 의 几 에서 殳 의 발끝 (475,1) 이 그렇다). 그 점을 버리는 것까지는
    쉬운데, 남은 토막의 조종점을 그대로 쓰면 안 된다 — 그것은 **토막의** 조종점
    이라 이어 붙이면 곡선이 어그러진다.

    되살리는 자리는 **두 접선이 만나는 곳**이다. 한쪽은 남은 획이 이 모서리로
    들어오는 접선(앞 조종점에서 이음매 점으로), 다른 쪽은 모서리가 빠져나가는
    접선(곡선의 끝점에서 그 다음 점으로)이다. 이것이 어림이 아니라는 것은 같은
    글자의 가벼운 굵기가 보여 준다 — 几 가 제 윤곽으로 따로 있는 Thin·Light·
    Regular·Text·Medium 다섯 굵기 모두, 갈고리의 조종점이 **정확히** 두 접선이
    만나는 자리다 (Regular 은 (479,12), 잰 것도 (479,12)).

    `drop` 은 이어 붙인 두 점 [ku, kv] 이고 **kv 가 버릴 쪽** — 떼어 낸 도막의
    첫 점, 곧 테두리가 조각으로 되돌아오는 자리다. 잘린 것이 곡선인지는 이음매
    **양쪽에 조종점이 붙어 있는지** 로 가린다. 하나라도 직선이면 꼭짓점이 잘린
    것이니 None 을 돌려주어 `one_corner` 에 넘긴다.

    **점이 하나 준다.**
    """
    pts = list(contour)
    n = len(pts)
    ku, kv = drop
    if n < 6 or (kv - ku) % n != 1:
        return None
    if not (pts[ku].on_curve and pts[kv].on_curve):
        return None
    kb, kc, ke = (ku - 1) % n, (kv + 1) % n, (kv + 2) % n
    if pts[kb].on_curve or pts[kc].on_curve or not pts[ke].on_curve:
        return None                      # (조종, 이음매, 이음매, 조종, 끝) 이어야 한다
    p = (pts[ku].x, pts[ku].y)
    dp = (p[0] - pts[kb].x, p[1] - pts[kb].y)          # 들어오는 접선
    q = (pts[ke].x, pts[ke].y)
    nx = pts[(ke + 1) % n]
    dq = (nx.x - q[0], nx.y - q[1])                    # 빠져나가는 접선
    c = _meet(p, dp, q, dq)
    if c is None:
        return None
    # 조종점은 두 끝점이 이루는 상자 안에 있어야 한다. 밖이면 접선이 거의 나란해
    # 만나는 자리가 멀리 달아난 것이고, 그런 곡선은 부푼다.
    pad = 0.35 * max(abs(q[0] - p[0]), abs(q[1] - p[1]), 1.0)
    if not (min(p[0], q[0]) - pad <= c[0] <= max(p[0], q[0]) + pad
            and min(p[1], q[1]) - pad <= c[1] <= max(p[1], q[1]) + pad):
        return None
    nc = fontforge.contour()
    nc.is_quadratic = contour.is_quadratic
    for k, pp in enumerate(pts):
        if k == kv:
            continue                     # 파고든 남의 끝점을 버린다
        if k == kc:
            nc += fontforge.point(round(c[0], 2), round(c[1], 2), False)
        else:
            nc += fontforge.point(pp.x, pp.y, pp.on_curve)
    nc.closed = contour.closed
    return nc


def _plate(contours, n=1000, off=150, em=1000.0):
    """윤곽을 판에 그린다 — 칸은 XOR 로 비운다. 재려고 쓰는 판이다.

    판이 `em` 보다 작으면 좌표도 그만큼 **줄여서** 그린다. 줄이지 않으면 글자의
    왼쪽 아래 귀퉁이만 판에 들어온다 — 2026-09-29 에 250 판으로 옆모습을 재면서
    그 탓에 祈 의 덮음이 0.35 로 나와 못 가르고 물러섰다.
    """
    import numpy as np
    from PIL import Image, ImageDraw
    k = n / float(em)
    acc = np.zeros((n, n), bool)
    for c in contours:
        pts = [(p.x, p.y) for p in c]
        if len(pts) < 3:
            continue
        im = Image.new('L', (n, n), 0)
        ImageDraw.Draw(im).polygon(
            [(x * k, n - (off + y) * k) for x, y in pts], fill=255)
        acc ^= (np.array(im) > 0)
    return acc


def valley_x(contours, lo=0.33, hi=0.52, n=1000, off=150):
    """변과 방 사이의 **가름선** — 세로로 가장 흰 줄의 x.

    세로 줄마다 먹의 키를 세어 가장 흰 줄을 고른다. 녹아붙은 굵기에서도 둘 사이
    에는 골이 남는다(붙은 목만 빼고). 가장 흰 줄이 여럿이면 **왼쪽 것**을 고른다
    — 굵은 굵기에서는 방 안의 틈이 더 희기도 하다 (祈 SemiBold 은 斤 안이 더
    희어 588 을 짚었다). 훑는 띠는 글자 폭의 3분의 1에서 절반까지다.
    """
    import numpy as np
    m = _plate(contours, n, off)
    if not m.any():
        return None
    col = m.sum(0)
    a, b = int(lo * n), int(hi * n)
    seg = col[a:b]
    return float(a + int(np.nonzero(seg <= seg.min() + 8)[0][0]))


def _arcs(contour):
    """윤곽을 (시작점, 조종점|None, 끝점) 토막으로 편다.

    2차 윤곽은 조종점이 잇달아 놓이면 그 사이에 점이 숨어 있다 — 꺼내 준다.
    """
    pts = [(p.x, p.y, p.on_curve) for p in contour]
    if not pts:
        return []
    out = []
    for i, (x, y, on) in enumerate(pts):
        nx, ny, non = pts[(i + 1) % len(pts)]
        if on:
            out.append((x, y, True))
        else:
            out.append((x, y, False))
            if not non:                      # 조종점 둘이 잇달으면 사이에 점이 있다
                out.append(((x + nx) / 2.0, (y + ny) / 2.0, True))
    if not out[0][2]:                        # 조종점으로 시작하면 돌려서 점부터
        k = next(i for i, p in enumerate(out) if p[2])
        out = out[k:] + out[:k]
    arcs, i = [], 0
    n = len(out)
    while i < n:
        a = out[i]
        j = (i + 1) % n
        if out[j][2]:
            arcs.append((a[:2], None, out[j][:2])); i += 1
        else:
            arcs.append((a[:2], out[j][:2], out[(j + 1) % n][:2])); i += 2
    return arcs


def _cross_x(arc, x):
    """토막이 세로선 x 를 지나는 자리들 — 매개변수 t 로."""
    (x0, _), c, (x2, _) = arc
    if c is None:
        if x0 == x2:
            return []
        t = (x - x0) / float(x2 - x0)
        return [t] if 0.0 < t < 1.0 else []
    x1 = c[0]
    a = x0 - 2 * x1 + x2
    b = 2 * (x1 - x0)
    cc = x0 - x
    if abs(a) < 1e-9:
        if abs(b) < 1e-9:
            return []
        ts = [-cc / b]
    else:
        d = b * b - 4 * a * cc
        if d < 0:
            return []
        r = math.sqrt(d)
        ts = [(-b + r) / (2 * a), (-b - r) / (2 * a)]
    return sorted(t for t in ts if 0.0 < t < 1.0)


def _at(arc, t):
    """토막 위의 한 점."""
    (x0, y0), c, (x2, y2) = arc
    if c is None:
        return (x0 + (x2 - x0) * t, y0 + (y2 - y0) * t)
    u = 1 - t
    return (u * u * x0 + 2 * u * t * c[0] + t * t * x2,
            u * u * y0 + 2 * u * t * c[1] + t * t * y2)


def _cut_arc(arc, t):
    """토막을 t 에서 둘로 쪼갠다 — 곡선은 de Casteljau 로."""
    (x0, y0), c, (x2, y2) = arc
    if c is None:
        m = _at(arc, t)
        return (( (x0, y0), None, m), (m, None, (x2, y2)))
    a = (x0 + (c[0] - x0) * t, y0 + (c[1] - y0) * t)
    b = (c[0] + (x2 - c[0]) * t, c[1] + (y2 - c[1]) * t)
    m = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    return (((x0, y0), a, m), (m, b, (x2, y2)))


def cut_beside(contour, x, tol=1e-6):
    """**세로선 하나로 윤곽을 가른다** — 선이 지나는 자리에 점을 만들어서.

    돌아오는 것은 (왼쪽 조각들, 오른쪽 조각들). 조각은 선을 따라 곧게 닫힌다.
    선을 몇 번 지나든 지날 때마다 갈린다.
    """
    arcs = _arcs(contour)
    if not arcs:
        return [], []
    cut = []
    for arc in arcs:
        ts = _cross_x(arc, x)
        rest = arc
        base = 0.0
        for t in ts:
            u = (t - base) / (1.0 - base)
            if not (tol < u < 1 - tol):
                continue
            a, rest = _cut_arc(rest, u)
            cut.append(a)
            base = t
        cut.append(rest)
    if len(cut) < 2:
        return ([contour], []) if _at(arcs[0], 0.5)[0] <= x else ([], [contour])

    def side(arc):
        return _at(arc, 0.5)[0] <= x

    runs = []
    for arc in cut:
        s = side(arc)
        if runs and runs[-1][0] == s:
            runs[-1][1].append(arc)
        else:
            runs.append((s, [arc]))
    if len(runs) > 1 and runs[0][0] == runs[-1][0]:
        runs[0] = (runs[0][0], runs[-1][1] + runs[0][1])
        runs.pop()
    if len(runs) == 1:
        return ([contour], []) if runs[0][0] else ([], [contour])

    def build(seq):
        c = contour.__class__()
        c.is_quadratic = contour.is_quadratic
        for a, ctrl, b in seq:
            c += fontforge.point(a[0], a[1], True)
            if ctrl is not None:
                c += fontforge.point(ctrl[0], ctrl[1], False)
        last = seq[-1][2]
        c += fontforge.point(last[0], last[1], True)
        c.closed = True
        return c

    left, right = [], []
    for s, seq in runs:
        (left if s else right).append(build(seq))
    return left, right


def beside(contours, x):
    """윤곽들을 세로선 x 에서 변(왼쪽)과 방(오른쪽)으로 가른다."""
    left, right = [], []
    for c in contours:
        b = box(c)
        if b[1] <= x:
            left.append(c)
        elif b[0] >= x:
            right.append(c)
        else:
            a, d = cut_beside(c, x)
            left += a
            right += d
    return left, right


def _cols(contours, n=250, off=150):
    """세로 줄마다 먹이 얼마나 있는지 — 맞춰 보는 데 쓰는 옆모습이다.

    판을 통째로 견주면 느리다(1000×1000 을 굵기마다 수백 번). 가로로만 미는
    일이라 줄마다의 먹 양만 견주어도 자리는 똑같이 잡힌다.
    """
    import numpy as np
    return _plate(contours, n, off).sum(0).astype(np.int32)


def _fit_form(contours, form, reach=30, n=250, off=150):
    """**기준 자형**을 글자의 왼쪽에 맞춰 놓는다 — 가로로 밀어 가장 잘 덮는 자리.

    돌아오는 것은 (밀 몫, 덮은 비율). 밀 몫은 글리프 좌표로 돌려준다. 기준
    자형은 그 굵기의 것이어야 한다 — 획 두께가 다르면 덮이지 않는다.
    """
    import numpy as np
    a = _cols(contours, n, off).astype(float)
    b = _cols(form, n, off).astype(float)
    # 옆모습을 살짝 뭉갠다. 가는 굵기는 획이 한두 줄이라 한 줄만 어긋나도 덮음이
    # 뚝 떨어진다 (祈 Thin 에서 0.37 까지 내려가 못 가르고 물러섰다). 12 유닛쯤
    # 뭉개면 자리는 그대로 잡히면서 그 날카로움이 없어진다.
    k = np.ones(3) / 3.0
    a = np.convolve(a, k, mode='same')
    b = np.convolve(b, k, mode='same')
    tot = float(b.sum())
    if not a.any() or tot <= 0:
        return None, 0.0
    best, how = 0, -1.0
    for d in range(-reach, reach + 1):
        sh = np.roll(b, d)
        if d > 0:
            sh[:d] = 0
        elif d < 0:
            sh[d:] = 0
        got = float(np.minimum(sh, a).sum()) / tot
        if got > how:
            best, how = d, got
    return best * (1000.0 / n), how


def beside_form(contours, form, reach=30, restore=True, least=0.80, crumb=0.0,
                guide=None, fat=3):
    """**변의 기준 자형이 주어졌을 때** 한자를 변과 방으로 가른다.

    변이 방과 녹아붙은 굵기에서도 갈린다. 골을 어림하지 않고 **기준 자형이 알려
    주는 자리**에서 가르므로, 굵기마다 자리를 다시 재지 않아도 된다.

      1. 기준 자형을 가로로 밀어 글자의 왼쪽을 가장 잘 덮는 자리를 찾는다.
         덮은 비율이 `least` 에 못 미치면 그 글자의 변이 아니다 — (None, None).
      2. 그 자리에서 기준 자형의 **오른끝**을 가름선으로 삼는다.
      3. 그 선에서 가른다 (`cut_beside`). 선이 지나는 자리에 점을 만들어 끊으므로
         방의 끝이 잘려 나가지 않는다.
      4. 선에 걸린 윤곽에서 갈린 조각은 **기준 자형을 자로 삼아** 어느 쪽인지
         가린다. 조각의 먹이 기준 자형 안에 `crumb` 넘게 들면 변이고, 아니면
         방이다. 선의 왼쪽이라고 다 변이 아니다 — 방의 가로획이 선을 넘어 왼쪽
         으로 뻗으면 그 토막도 왼쪽에 놓인다 (福 의 畐 윗가로획). 넓이로 가리면
         변의 뾰족한 끝(礻 의 점)까지 방으로 넘어간다.
      5. `restore` 면 **겹쳤던 자리를 되살린다** — 선 위에 곧게 남은 잘린 변을,
         그 양 옆 변을 늘여 만나는 자리의 모서리로 되돌린다.
      6. `guide` 로 (변, 방) 윤곽을 주면 — **같은 글자의 가는 굵기**에서 글자 자체로
         갈린 것 — 토막 주인을 기준 자형 대신 그것으로 가린다. 다른 글자의 변을
         자로 삼으면 방 가로획의 왼쪽 토막이 변으로 가기도 한다 (祖 Bold 의 且,
         祥 SemiBold 의 羊). 같은 글자면 획 자리가 몇 유닛 안에서 같다. 굵어진
         만큼은 `fat` 칸(250 판) 부풀려 받는다. 되살린 모서리도 가는 굵기의 그
         쪽 먹 안에 들 때만 받는다 (祖 SemiBold 에서 방 쪽 되살리기가 선 왼쪽으로
         큰 쐐기를 만들었다).

    돌아오는 것은 (변, 방) — 둘 다 윤곽 목록.
    """
    dx, got = _fit_form(contours, form, reach)
    if dx is None or got < least:
        return None, None
    x = bbox(form)[1] + dx
    mask = None
    if crumb > 0:
        put = dup(form)
        for c in put:
            c.transform(psMat.translate(dx, 0))
        mask = _plate(put, 250)
    gl = gr = None
    if guide is not None:
        gl, gr = _plate(guide[0], 250), _plate(guide[1], 250)
        for _ in range(fat):
            gl = _grow(gl)
            gr = _grow(gr)
    left, right = [], []
    cut_l, cut_r = [], []                 # 실제로 잘린 조각 — 되살리기는 이것에만
    for c in contours:
        b = box(c)
        if b[1] <= x:
            left.append(c)
        elif b[0] >= x:
            right.append(c)
        else:
            a, d = cut_beside(c, x)
            wl = wr = 0.0
            if gl is not None:
                side = []
                for piece in a + d:
                    m = _plate([piece], 250)
                    tot = float(m.sum())
                    if tot <= 0:
                        continue
                    L = float((m & gl).sum()) >= float((m & gr).sum())
                    side.append((piece, L))
                    if L:
                        wl += tot
                    else:
                        wr += tot
                a = [p for p, L in side if L]
                d = [p for p, L in side if not L]
            elif mask is not None:
                side = []
                for piece in a + d:
                    m = _plate([piece], 250)
                    tot = float(m.sum())
                    if tot <= 0:
                        continue
                    L = float((m & mask).sum()) / tot >= crumb
                    side.append((piece, L))
                    if L:
                        wl += tot
                    else:
                        wr += tot
                a = [p for p, L in side if L]
                d = [p for p, L in side if not L]
            else:
                wl = sum(area(p) for p in a)
                wr = sum(area(p) for p in d)
            # 한 윤곽이 **거의 다 한쪽**이면 자르지 않고 원래 윤곽을 통째로 그쪽에
            # 둔다. 변의 점 끝이 선을 살짝 넘거나(神 Thin), 방의 가로획이 선 왼쪽으로
            # 뻗었을 뿐인 것(社 Thin 의 土)을 끊으면, 떨어진 끝이 반대쪽으로 가거나
            # 이음매에 모서리가 삐죽 생긴다. 둘이 녹아붙은 윤곽이라야 참으로 가른다.
            tot = wl + wr
            if not d or (tot and wr < 0.1 * tot):
                left.append(c)
            elif not a or (tot and wl < 0.1 * tot):
                right.append(c)
            else:
                # 자르다 생긴 먼지(넓이 몇 유닛짜리)는 버린다 — 祈 SemiBold 에서 넓이 2
                cut_l += [p for p in a if area(p) >= 40]
                cut_r += [p for p in d if area(p) >= 40]
    if restore:
        def fix(c, inner, room):
            r = restore_at(c, x, inner=inner)
            if room is None or r is c:
                return r
            # 되살린 모서리가 가는 굵기의 그 쪽 먹 안에 들 때만 받는다
            m = _plate([r], 250) & ~_plate([c], 250)
            return r if not m.any() or float((m & room).sum()) >= 0.8 * float(m.sum()) else c
        cut_l = [fix(c, True, gl) for c in cut_l]
        cut_r = [fix(c, False, gr) for c in cut_r]
    return left + cut_l, right + cut_r


def restore_at(contour, x, inner=True, tol=0.75, far=600.0):
    """**가름선에 곧게 남은 잘린 자리를 되살린다** — 두 옆 변을 늘여 만나는 데까지.

    자르면 선 위에 세로 토막이 생긴다. 그 토막이 본디 있던 변이 아니라 자르며
    생긴 단면이면, 토막의 양 끝에서 이어지는 두 변을 늘여 만나는 자리에 점을
    하나 두고 토막을 지운다. 두 변이 나란하면 그대로 둔다 — 거기가 본디 곧은
    변이었다는 뜻이다.

    `inner` 가 참이면 선의 **왼쪽** 조각을 되살린다(모서리가 오른쪽으로 나간다).
    """
    pts = [(p.x, p.y, p.on_curve) for p in contour]
    n = len(pts)
    if n < 4:
        return contour
    on = [i for i in range(n) if pts[i][2]]
    for k in range(len(on)):
        i, j = on[k], on[(k + 1) % len(on)]
        if (j - i) % n != 1:
            continue                                  # 사이에 조종점이 있으면 곡선
        if abs(pts[i][0] - x) > tol or abs(pts[j][0] - x) > tol:
            continue                                  # 선 위의 세로 토막이 아니다
        a, b = (i - 1) % n, (j + 1) % n
        if not (pts[a][2] and pts[b][2]):
            continue                                  # 양 옆이 곡선이면 두지 않는다
        got = _meet((pts[i][0], pts[i][1]),
                    (pts[i][0] - pts[a][0], pts[i][1] - pts[a][1]),
                    (pts[j][0], pts[j][1]),
                    (pts[j][0] - pts[b][0], pts[j][1] - pts[b][1]))
        if got is None:
            continue                                  # 나란하다 — 본디 곧은 변
        if inner and got[0] <= x + tol:
            continue
        if not inner and got[0] >= x - tol:
            continue
        if math.hypot(got[0] - pts[i][0], got[1] - pts[i][1]) > far:
            continue                                  # 너무 멀면 되살릴 자리가 아니다
        keep = [pts[t] for t in range(n) if t not in (i, j)]
        at = i if i < j else j
        keep.insert(at, (got[0], got[1], True))
        c = contour.__class__()
        c.is_quadratic = contour.is_quadratic
        for px, py, o in keep:
            c += fontforge.point(px, py, o)
        c.closed = True
        return c
    return contour


def _lie(contours):
    """윤곽을 눕힌다 — x 와 y 를 맞바꾼다. 가로선으로 가르려고 쓴다."""
    out = []
    for c in contours:
        n = c.__class__()
        n.is_quadratic = c.is_quadratic
        for p in c:
            n += fontforge.point(p.y, p.x, p.on_curve)
        n.closed = True
        out.append(n)
    return out


def across(contours, y):
    """윤곽들을 가로선 y 에서 **발(아래)** 과 **머리(위)** 로 가른다.

    위아래로 짜인 글자에 쓴다. 좌표를 눕혀 `beside` 를 그대로 쓰므로, 선이
    지나는 자리에 점을 만들어 끊는 규칙이 똑같이 걸린다.
    """
    lo, hi = beside(_lie(contours), y)
    return _lie(lo), _lie(hi)


def across_form(contours, form, **kw):
    """**머리의 기준 자형**이 주어졌을 때 위아래로 짜인 글자를 가른다."""
    lo, hi = beside_form(_lie(contours), _lie(form), **kw)
    return (_lie(lo) if lo else None), (_lie(hi) if hi else None)


def area(contour):
    """윤곽이 두른 넓이 — 부스러기를 가려내려고 어림으로만 잰다."""
    pts = [(p.x, p.y) for p in contour]
    a = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % len(pts)]
        a += x0 * y1 - x1 * y0
    return abs(a) / 2.0


def minus_form(font, contours, form, reach=30, least=0.80, crumb=0.0):
    """**기준 자형을 빼낸다** — 변이 방을 감싸는 글자에 쓴다.

    辶·广·匚 처럼 변이 방을 감싸면 세로선 하나로 못 가른다. 그럴 때는 기준 자형을
    맞춰 놓고 그 먹을 **빼낸다**. 남는 것이 방이다.

      1. 기준 자형을 가로로 밀어 가장 잘 덮는 자리를 찾는다 (`_fit_form`).
      2. 그 자리에 놓은 기준 자형을 **거꾸로 감아** 함께 담고 removeOverlap 한다
         — 거꾸로 감긴 윤곽은 먹을 판다.
      3. 판 뒤에 남은 부스러기를 버린다 (`crumb`, 가장 큰 조각 대비 비율).

    돌아오는 것은 (빼낸 것, 남은 것) — 빼낸 것은 놓인 자리의 기준 자형이다.
    `font` 는 removeOverlap 을 굴릴 임시 글리프를 만들 자리로만 쓴다.

    기준 자형은 **글자 안에 든 크기**여야 한다. 홀로 선 부수 글리프(广 U+5E7F
    처럼)는 글자 안의 것보다 크게 그려져 있어 맞춰 놓아도 파이지 않는다 —
    2026-09-29 庁·店·府 에 U+5E7F 를 대 보니 거의 그대로 남았다. 같은 굵기에서
    그 변이 따로 떨어진 **다른 글자**의 것을 써야 한다.
    """
    dx, got = _fit_form(contours, form, reach)
    if dx is None or got < least:
        return None, None
    put = dup(form)
    for c in put:
        c.transform(psMat.translate(dx, 0))
    tmp = font.createChar(-1, "hapchija.minus")
    lay = fontforge.layer()
    lay.is_quadratic = contours[0].is_quadratic if contours else True
    for c in contours:
        lay += c
    for c in put:
        d = dup([c])[0]
        if _turn(d) > 0:              # 거꾸로 감아 먹을 판다
            d.reverseDirection()
        lay += d
    tmp.foreground = lay
    tmp.removeOverlap()
    rest = list(tmp.foreground)
    if crumb > 0 and rest:
        big = max(area(c) for c in rest)
        rest = [c for c in rest if area(c) >= crumb * big]
    rest = dup(rest)
    font.removeGlyph(tmp)
    return put, rest


def carve_form(font, contours, form, reach=30, least=0.80):
    """**기준 자형의 윤곽을 따라** 변과 방을 가른다 — 세로선이 아니라.

    변의 오른끝은 높이마다 다르다. 禎 Bold 에서 기준 礻 의 오른끝은 y 700 에서
    387, y 300 에서 400, y 100 에서 271 이다. 통짜 오른끝(441)으로 세로선을 그으면
    낮은 데서 방의 왼쪽 띠(271~441)가 변으로 딸려온다. 그래서 선을 긋지 않고
    **기준 자형이 덮는 만큼**을 변으로 가른다.

      · 방 = 글자의 먹에서 기준 자형을 **빼낸** 것
      · 변 = 글자의 먹에서 그 방을 다시 **빼낸** 것 (= 글자 ∩ 기준 자형)

    녹아붙었든 떨어졌든 한 길로 갈린다. 돌아오는 것은 (변, 방).
    `font` 는 removeOverlap 을 굴릴 임시 글리프를 둘 자리로만 쓴다.
    """
    dx, got = _fit_form(contours, form, reach)
    if dx is None or got < least:
        return None, None
    put = dup(form)
    for c in put:
        c.transform(psMat.translate(dx, 0))

    def minus(keep, cut):
        """keep 에서 cut 을 빼낸다 — cut 을 거꾸로 감아 함께 담고 녹인다."""
        # 임시 글리프는 하나만 두고 다시 쓴다 — 만들고 지우기를 되풀이하면
        # FontForge 가 죽는다 (2026-09-29, 굵기 여덟 × 열두 자를 돌리다 core dump)
        tmp = (font["hapchija.carve"] if "hapchija.carve" in font
               else font.createChar(-1, "hapchija.carve"))
        lay = fontforge.layer()
        lay.is_quadratic = keep[0].is_quadratic if keep else True
        ink = _turn(max(keep, key=lambda c: len(list(c))))
        for c in dup(keep):
            lay += c
        for c in dup(cut):
            # 빼낼 윤곽은 먹과 **반대로** 감아야 판다. 먹의 방향을 재어 맞춘다 —
            # 짐작으로 뒤집으면 거꾸로 되어 파이지 않고 합쳐진다 (2026-09-29).
            if _turn(c) == ink:
                c.reverseDirection()
            lay += c
        tmp.foreground = lay
        tmp.removeOverlap()
        out = dup(list(tmp.foreground))
        tmp.foreground = fontforge.layer()
        return out

    body = minus(contours, put)
    rad = minus(contours, body) if body else dup(contours)
    return rad, body


def _grow(m):
    """판을 한 칸 부풀린다."""
    import numpy as np
    out = m.copy()
    out[1:, :] |= m[:-1, :]
    out[:-1, :] |= m[1:, :]
    out[:, 1:] |= m[:, :-1]
    out[:, :-1] |= m[:, 1:]
    return out


def gap_curve(radical, body, n=250, off=150, em=1000.0, grow=0):
    """변과 방 사이 **흰 틈의 복판**을 높이마다 잰다 — 굽은 가름선.

    변·방이 글자 자체로 갈린 굵기의 두 조각을 주면, 줄마다 변의 먹 오른끝과 그
    오른쪽 방의 먹 왼끝 사이 복판을 돌려준다. 곧은 세로선은 변 밑동에 붙은 방의
    토막(且 의 밑가로획, 貞 의 다리)을 못 떼지만, 틈을 따라가면 떨어진다.

    돌아오는 것은 높이 → x 를 주는 함수. 틈이 없는 줄은 가까운 줄의 값을 쓴다.
    """
    import numpy as np
    k = n / em
    a, b = _plate(radical, n, off, em), _plate(body, n, off, em)
    # 굵어질 몫만큼 **사방으로** 부풀린 뒤 틈을 잰다. 옆으로만 보면 모자란다 —
    # 神 Medium 에서 礻 의 점이 아래로 굵어져, Regular 에서는 줄기만 있던 줄
    # (y 140~180) 까지 내려와 복판 348 을 넘었다. 부풀려 맞닿는 줄은 부풀리기
    # 전의 복판을 쓴다.
    a0, b0 = a, b
    for _ in range(grow):
        a, b = _grow(a), _grow(b)
    mid = np.full(n, np.nan)
    for r in range(n):
        for pa, pb in ((a, b), (a0, b0)):
            ra = np.nonzero(pa[r])[0]
            if not len(ra):
                break
            rb = np.nonzero(pb[r])[0]
            rb = rb[rb > ra.max()]
            if len(rb):
                mid[r] = (ra.max() + rb.min()) / 2.0
                break
    ok = np.nonzero(~np.isnan(mid))[0]
    if not len(ok):
        return None
    mid = np.interp(np.arange(n), ok, mid[ok])
    w = 3                                     # 줄 몇 개로 매끈하게
    mid = np.convolve(np.pad(mid, w, mode='edge'), np.ones(2 * w + 1) / (2 * w + 1),
                      mode='valid')
    # 매끈하게 한 뒤 줄마다 묶는다 — 선은 변 먹의 오른쪽, 그 오른쪽 방 먹의 왼쪽
    # 에만 설 수 있다. 틈이 없는 줄(변만 있거나 방만 있는 줄)을 이웃 값으로 메우면
    # 선이 먹을 뚫고 지나가 한 윤곽이 잘린다 (神 Thin 의 礻 점 끝, 社 Light).
    # `grow` — 안내 굵기보다 굵어질 몫(판 칸). 변만 있는 줄에서는 선을 변 오른끝에서
    # 그만큼 더 비켜 둔다. 바짝 붙여 두면 굵어진 만큼 변의 가장자리가 길게 깎여
    # 방에 딸려 간다 (神 Medium 의 礻 점 오른쪽 가장자리). 방만 있는 줄도 같다.
    for r in range(n):
        ra = np.nonzero(a[r])[0]
        rb = np.nonzero(b[r])[0]
        if len(ra):
            rb = rb[rb > ra.max()]
            if not len(rb) and len(np.nonzero(b0[r])[0]):
                ra = np.nonzero(a0[r])[0]              # 부풀린 둘이 맞닿은 줄
                rb = np.nonzero(b0[r])[0]
                rb = rb[rb > ra.max()] if len(ra) else rb
        lo = ra.max() + 1.0 + (grow if not len(rb) else 0) if len(ra) else -np.inf
        hi = rb.min() - 1.0 - (grow if not len(ra) else 0) if len(rb) else np.inf
        if lo <= hi:
            mid[r] = min(max(mid[r], lo), hi)
        elif len(ra):
            mid[r] = lo

    def at(y):
        r = int(round(n - (off + y) * k))
        r = min(max(r, 0), n - 1)
        return mid[r] / k
    return at


def cut_along(contours, at):
    """**굽은 가름선** x = at(y) 에서 윤곽들을 가른다 — (왼쪽, 오른쪽).

    줄마다 선을 빼 좌표를 곧게 펴고(x' = x − at(y)), 곧은 선 x' = 0 에서
    `cut_beside` 로 가른 뒤 되돌린다. 새로 생기는 점은 y 가 그대로이고 x' = 0
    이므로 되돌리면 꼭 가름선 위에 놓인다.
    """
    def warp(cs, sign):
        out = []
        for c in cs:
            n = c.__class__()
            n.is_quadratic = c.is_quadratic
            for p in c:
                n += fontforge.point(p.x + sign * at(p.y), p.y, p.on_curve)
            n.closed = True
            out.append(n)
        return out

    # 윤곽마다 먼저 선의 어느 쪽에 **거의 다** 있는지 본다. 거의 한쪽이면 자르지
    # 않고 통째로 그쪽에 둔다 — 변·방이 글자 자체로 갈린 굵기에서는 모든 윤곽이
    # 그러하므로 원래대로 갈린다. 양쪽에 크게 걸친 윤곽(녹아붙은 것)만 자른다.
    import numpy as np
    n, off, k = 250, 150, 0.25
    rows = np.arange(n)
    edge = np.array([at((n - r) / k - off) * k for r in rows])
    cols = np.arange(n)[None, :]
    lmask = cols < edge[:, None]
    left, right, both = [], [], []
    for c in contours:
        m = _plate([c], n, off)
        tot = float(m.sum())
        if not tot:
            continue
        lf = float((m & lmask).sum()) / tot
        if lf >= 0.9:
            left.append(c)
        elif lf <= 0.1:
            right.append(c)
        else:
            both.append(c)
    if both:
        lo, hi = beside(warp(both, -1), 0.0)
        left += warp([_dense_on_line(c) for c in lo], +1)
        right += warp([_dense_on_line(c) for c in hi], +1)
    return left, right


def _dense_on_line(contour, step=8.0, tol=1e-3):
    """x = 0 위에 놓인 곧은 변을 촘촘한 점으로 쪼갠다.

    굽은 선을 곧게 편 좌표에서 자르면, 잘린 조각을 닫는 변은 x' = 0 위의 곧은
    세로선이다. 양끝 두 점만 되돌리면 굽은 선을 따라가지 않고 **대각선 현**이
    되어 남의 몸을 가로지른다 (神 Medium 에서 방이 382 부터 잡혔다). 되돌리기
    전에 그 변에 점을 촘촘히 박아 두면 되돌린 뒤 굽은 선을 따라간다.
    """
    pts = [(p.x, p.y, p.on_curve) for p in contour]
    n = len(pts)
    out = []
    for i in range(n):
        x0, y0, on0 = pts[i]
        x1, y1, on1 = pts[(i + 1) % n]
        out.append((x0, y0, on0))
        if on0 and on1 and abs(x0) < tol and abs(x1) < tol and abs(y1 - y0) > step:
            k = int(abs(y1 - y0) // step)
            for j in range(1, k + 1):
                y = y0 + (y1 - y0) * j / (k + 1.0)
                out.append((0.0, y, True))
    c = contour.__class__()
    c.is_quadratic = contour.is_quadratic
    for x, y, on in out:
        c += fontforge.point(x, y, on)
    c.closed = True
    return c


def _ink(contours, n=1000, off=150):
    """먹 판 (1 유닛 = 1 칸) — 점이 먹 안인지 밖인지 보려고."""
    return _plate(contours, n, off)


def _ext(pts, end, far):
    """조각의 끝 `end`('a' 마지막 · 'b' 처음)에서 윤곽을 **제 모양대로** 늘인다.

    끝에 붙은 것이 곧은 변이면 곧게, 2차 곡선이면 그 곡선의 식을 t > 1 로 이어
    간다. 돌아오는 것은 (곡선인가, P0, P1, P2, 늘인 점열 [(t, x, y)]).
    곧은 변이면 P0 = 앞 점, P1 = None, P2 = 끝점, t 는 늘인 길이의 몫.
    P0 가 두 오프커브 사이의 숨은 온커브면 그 중점을 준다.
    """
    m = len(pts)
    if end == 'a':
        p2, p1, p0 = pts[-1], pts[-2], pts[-3]
    else:
        p2, p1, p0 = pts[0], pts[1], pts[2]
    out = []
    if p1[2]:                                   # 곧은 변
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        L = math.hypot(dx, dy) or 1.0
        for k in range(1, 801):
            s = far * k / 800.0
            out.append((s, p2[0] + dx / L * s, p2[1] + dy / L * s))
        return False, (p1[0], p1[1]), None, (p2[0], p2[1]), out
    q0 = (p0[0], p0[1]) if p0[2] else ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
    P1, P2 = (p1[0], p1[1]), (p2[0], p2[1])
    t, last = 1.0, P2
    while True:
        t += 0.002
        v = 1 - t
        x = v * v * q0[0] + 2 * t * v * P1[0] + t * t * P2[0]
        y = v * v * q0[1] + 2 * t * v * P1[1] + t * t * P2[1]
        out.append((t, x, y))
        if math.hypot(x - P2[0], y - P2[1]) > far or t > 6:
            break
    return True, q0, P1, P2, out


def _piece(pts, end, n=40):
    """조각 끝 `end` 에 붙은 마지막 곡선(또는 곧은 변) 토막을 촘촘히 짚은 점들."""
    if end == 'a':
        p2, p1, p0 = pts[-1], pts[-2], pts[-3]
    else:
        p2, p1, p0 = pts[0], pts[1], pts[2]
    if p1[2]:
        return [(p1[0] + (p2[0] - p1[0]) * k / n, p1[1] + (p2[1] - p1[1]) * k / n)
                for k in range(n + 1)]
    q0 = (p0[0], p0[1]) if p0[2] else ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
    out = []
    for k in range(n + 1):
        t = k / float(n); v = 1 - t
        out.append((v * v * q0[0] + 2 * t * v * p1[0] + t * t * p2[0],
                    v * v * q0[1] + 2 * t * v * p1[1] + t * t * p2[1]))
    return out


def _fit_ctl(s0, s1, sample, start):
    """s0 에서 s1 로 가는 2차 곡선의 조종점을, `sample` 점들이 곡선에서 가장 덜
    벗어나게(가장 먼 점의 거리가 가장 작게) 고른다. 정수 자리로 돌려준다."""
    ts = [k / 300.0 for k in range(301)]

    def worst(c):
        cur = [((1 - t) ** 2 * s0[0] + 2 * t * (1 - t) * c[0] + t * t * s1[0],
                (1 - t) ** 2 * s0[1] + 2 * t * (1 - t) * c[1] + t * t * s1[1]) for t in ts]
        return max(min((x - u) ** 2 + (y - v) ** 2 for u, v in cur) for x, y in sample)

    best, bv, step = (float(start[0]), float(start[1])), None, 16.0
    bv = worst(best)
    while step >= 0.25:
        moved = False
        for dx, dy in ((step, 0), (-step, 0), (0, step), (0, -step),
                       (step, step), (step, -step), (-step, step), (-step, -step)):
            c = (best[0] + dx, best[1] + dy)
            v = worst(c)
            if v < bv:
                best, bv, moved = c, v, True
        if not moved:
            step /= 2
    c = (round(best[0]), round(best[1]))
    return c if worst(c) <= bv + 0.5 else best


def _cross(pa, pb):
    """두 점열이 처음 엇갈리는 자리 — (i, j, x, y) 또는 None."""
    A = [(x, y) for _, x, y in pa]
    B = [(x, y) for _, x, y in pb]
    best = None
    for i in range(len(A) - 1):
        (x1, y1), (x2, y2) = A[i], A[i + 1]
        for j in range(len(B) - 1):
            (x3, y3), (x4, y4) = B[j], B[j + 1]
            d = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
            if d == 0:
                continue
            s = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / d
            u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / d
            if 0 <= s <= 1 and 0 <= u <= 1:
                if best is None or i + j < best[0] + best[1]:
                    best = (i, j, x1 + s * (x2 - x1), y1 + s * (y2 - y1))
        if best and i > best[0] + best[1]:
            break
    return best


def _near_ink(x, y, contours, tol):
    """(x, y) 가 윤곽들의 먹 안이거나 가장자리에서 `tol` 유닛 안인가."""
    inside = False
    best = 1e9
    for c in contours:
        q = [(p.x, p.y) for p in _flat_pts(c)]
        for k in range(len(q)):
            (x1, y1), (x2, y2) = q[k - 1], q[k]
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
            vx, vy = x2 - x1, y2 - y1
            L2 = vx * vx + vy * vy
            t = 0.0 if not L2 else max(0.0, min(1.0, ((x - x1) * vx + (y - y1) * vy) / L2))
            best = min(best, math.hypot(x - (x1 + t * vx), y - (y1 + t * vy)))
    return inside or best <= tol


def restore_cut(contour, original, near=0.5, flat=0.5, far=400.0, log=None, how=None,
                touched=None, keep_new=False, guide=None, reach=40.0):
    """**잘린 자리를 되살린다** — 동작은 두 가지다.

    2026-09-29 사용자가 정해 준 길. 가르기(`split_by_owner`)는 원래 점만 쓰고
    지우지 않는다. 잘린 조각은 마지막 점에서 첫 점으로 곧게 이어 닫혀 있다.

      · **내 쪽 윤곽이 멀쩡하면 — 불필요한 점을 지운다.** 닫는 변이 내 윤곽의 본디
        변 위에 그대로 놓인 경우다 (神 Medium 의 방 — 申 의 왼변은 본디 곧다).
        두 글리프가 만나며 생긴 점(48)이 한 줄 위에 서 있으니 지운다.
      · **내 쪽 윤곽이 잘렸으면 — 복원한다.** 내 윤곽이 남의 몸에 파묻혀 끝이
        잘려 나간 경우다 (神 Medium 의 변 — 礻 의 점 끝). 닫는 변 둘레의 안쪽
        두 변을 늘여 만나는 자리에 끝점을 되살리고, 그러면 한 줄 위에 서게 되는
        만난 점(12)을 지운다.

    멀쩡한지 잘렸는지는 닫는 변의 두 끝점 a(마지막)·b(처음)에서 안쪽 변을 늘여
    본다 — 끝점 자리에서 만나거나 나란하면 멀쩡하고, 두 끝점 **너머에서** 만나면
    잘린 것이다. 원래 글꼴에 없는 새 점이 있으면 먼저 걷어 낸다.

    `how` 에 리스트를 주면 '지움' 또는 '복원' 을 적는다. `touched` 에 리스트를
    주면 되살린 점은 ('add', x, y), 지운 점은 ('drop', x, y) 로 적는다 — 그림용.
    `log` 에 리스트를 주면 걸음마다 (이름, 점 목록, 표시) 를 남긴다.
    """
    orig = [(p.x, p.y) for c in original for p in c]

    def is_orig(pt):
        return any(abs(pt[0] - ox) <= near and abs(pt[1] - oy) <= near for ox, oy in orig)

    pts = [(p.x, p.y, p.on_curve) for p in contour]
    if log is not None:
        log.append(('가른 그대로', list(pts), ['orig' if is_orig(q) else 'new' for q in pts]))
    # 옛 가르기가 끼워 넣은 새 점을 걷어 낸다. 건너뛴 곳을 차례로 되살릴 때는
    # (restore_joints) 앞 복원이 만든 점 — 되살린 끝점, 다시 셈한 조종점 — 이 새 점이니
    # 걷어 내면 안 된다 (祚 SemiBold 의 丿 조종점이 다음 복원에서 지워져 곧은 선이 됐다).
    if not keep_new:
        pts = [q for q in pts if is_orig(q)]
    if len(pts) < 3:
        return contour
    a, pa = pts[-1], pts[-2]
    b, nb = pts[0], pts[1]
    curved = not (pa[2] and nb[2])

    def ang(u, v):
        la, lb = math.hypot(*u), math.hypot(*v)
        if not la or not lb:
            return 180.0
        c = max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / (la * lb)))
        return math.degrees(math.acos(c))

    ta = (a[0] - pa[0], a[1] - pa[1])            # a 로 들어오는 방향
    tb = (nb[0] - b[0], nb[1] - b[1])            # b 에서 나가는 방향
    # **곡선 복원에는 온커브 점을 만들지 않는다** (2026-09-29 사용자).
    # ㄱ. 한 곡선이 끊긴 것 (祚 SemiBold 의 丿 왼변 21 …23 | 31… 33) — a 로 들어오는
    #     방향, a→b, b 에서 나가는 방향이 한 흐름이다. a·b 를 지우고 둘레 두 온커브
    #     점(21·33) 사이의 오프커브만 두 끝 접선이 만나는 자리에 다시 셈한다.
    if curved and len(pts) > 5 and ang(ta, tb) < 20 and ang(ta, (b[0] - a[0], b[1] - a[1])) < 45:
        _, sa, _, _, _ = _ext(pts, 'a', far)
        _, sb, _, _, _ = _ext(pts, 'b', far)
        da = (pa[0] - sa[0], pa[1] - sa[1]) if not pa[2] else ta
        db = (nb[0] - sb[0], nb[1] - sb[1]) if not nb[2] else (b[0] - nb[0], b[1] - nb[1])
        got = _meet(sa, da, sb, (-db[0], -db[1]))
        if got is not None:
            # 조종점은 **남은 두 토막과 같은 곡선**이 되게 고른다 (2026-09-29 사용자
            # 「0.21 과 0.33 사이 오프 포인트를 다시 계산」). 접선 교점은 출발점일 뿐
            # — 겹침을 없애며 잘린 짧은 토막은 조종점이 정수로 반올림돼 접선이
            # 틀어진다 (祚 SemiBold 의 21 (22) 23: 교점 (511,627) 은 원래 곡선에서
            # 1.8 유닛, 토막에 맞춘 (512,637) 은 0.5 유닛).
            got = _fit_ctl(sa, sb, _piece(pts, 'a') + _piece(pts, 'b'), got)
            body = pts[2 if not nb[2] else 1:len(pts) - (2 if not pa[2] else 1)]
            # 숨은 온커브(두 오프 사이 중점)를 끝으로 쓰면 드러내 둔다 — 모양은 같다
            if not pa[2] and not pts[-3][2]:
                body = body + [(sa[0], sa[1], True)]
            if not nb[2] and not pts[2][2]:
                body = [(sb[0], sb[1], True)] + body
            pts = body + [(got[0], got[1], False)]
            if touched is not None:
                touched += [('drop', a[0], a[1]), ('drop', b[0], b[1]), ('off', got[0], got[1])]
            if how is not None:
                how.append('곡선 이음')
            if log is not None:
                log.append(('한 곡선 — 끝점 지우고 조종점 다시 셈', list(pts), ['orig'] * len(pts)))
            c = contour.__class__()
            c.is_quadratic = contour.is_quadratic
            for x, y, on in pts:
                c += fontforge.point(x, y, on)
            c.closed = True
            return c
    # ㄴ. 끝이 파묻혀 잘린 것 (祔 Bold 의 丿 끝 — 14 (13) 12 곡선과 7→8 곧은 변).
    #     두 끝을 **제 모양대로** 늘여(곡선은 제 식을 t > 1 로) 만나는 자리에 끝점을
    #     되살린다. 곡선 쪽은 끝점을 지우고 조종점을 늘인 곡선의 것으로 바꾼다 —
    #     곡선 위에 온커브 점이 남지 않는다.
    if curved and len(pts) > 4:
        ca, a0, a1, a2, ea = _ext(pts, 'a', far)
        cb, b0, b1, b2, eb = _ext(pts, 'b', far)
        hit = _cross([(0, a[0], a[1])] + ea, [(0, b[0], b[1])] + eb)
        if hit is not None and min(math.hypot(hit[2] - a[0], hit[3] - a[1]),
                                   math.hypot(hit[2] - b[0], hit[3] - b[1])) > near \
                and (guide is None or _near_ink(hit[2], hit[3], guide, reach)):
            X = (hit[2], hit[3], True)
            new = list(pts)
            # 뒤(a)부터 — 인덱스가 흔들리지 않게
            if ca:
                t = ea[max(hit[0] - 1, 0)][0]
                ctl = (a0[0] + t * (a1[0] - a0[0]), a0[1] + t * (a1[1] - a0[1]), False)
                tail = [ctl]
                if not new[-3][2]:
                    tail = [(a0[0], a0[1], True), ctl]
                new = new[:-2] + tail
            else:
                new = new[:-1]
            if cb:
                t = eb[max(hit[1] - 1, 0)][0]
                ctl = (b0[0] + t * (b1[0] - b0[0]), b0[1] + t * (b1[1] - b0[1]), False)
                head = [ctl]
                if not new[2][2]:
                    head = [ctl, (b0[0], b0[1], True)]
                new = head + new[2:]
            else:
                new = new[1:]
            pts = new + [X]
            if touched is not None:
                touched += [('drop', a[0], a[1]), ('drop', b[0], b[1]), ('add', X[0], X[1])]
            if how is not None:
                how.append('곡선 복원')
            if log is not None:
                log.append(('곡선 끝 — 제 모양대로 늘여 끝점 되살림', list(pts), ['orig'] * len(pts)))
            c = contour.__class__()
            c.is_quadratic = contour.is_quadratic
            for x, y, on in pts:
                c += fontforge.point(x, y, on)
            c.closed = True
            return c
    got = _meet((a[0], a[1]), (a[0] - pa[0], a[1] - pa[1]),
                (b[0], b[1]), (b[0] - nb[0], b[1] - nb[1]))
    cut = False
    if got is not None:
        ahead = all(((got[0] - q[0]) * (q[0] - r[0]) + (got[1] - q[1]) * (q[1] - r[1])) > -1e-6
                    for q, r in ((a, pa), (b, nb)))
        at_end = min(math.hypot(got[0] - a[0], got[1] - a[1]),
                     math.hypot(got[0] - b[0], got[1] - b[1])) <= near
        cut = ahead and not at_end and math.hypot(got[0] - a[0], got[1] - a[1]) <= far
        # 되살릴 끝점은 안내 굵기에서도 **같은 쪽 먹이 있는 자리**여야 한다. 두 변을 늘여
        # 만나기만 하면 되살리면, 잘리지 않은 곳에도 모서리가 선다 (禌 Bold 의 방이
        # 다리 오른변을 따라 곧게 닫히면 되는데 (330, 351) 에 모서리를 세워 다리 안으로
        # 쐐기가 들어갔다 — 안내 SemiBold 에서 그 자리는 다리다).
        if cut and guide is not None and not _near_ink(got[0], got[1], guide, reach):
            cut = False
    added = None
    if cut:
        # 잘렸다 — 복원한다: 늘인 두 변이 만나는 자리에 끝점을 되살린다
        added = (got[0], got[1], True)
        pts = pts + [added]
        if touched is not None:
            touched.append(('add', got[0], got[1]))
    if how is not None:
        how.append('복원' if cut else '지움')
    if log is not None:
        log.append(('잘림 — 끝점 되살림' if cut else '멀쩡 — 되살릴 끝 없음', list(pts),
                    ['add' if q == added else ('look' if q in (a, b) else 'orig') for q in pts]))
    # 두 경우 모두 — 닫는 자리 둘레에서 한 줄 위에 선 온커브 점을 하나씩 지운다
    look = [a, b] + ([added] if added else [])
    while look and len(pts) > 3:
        q = look.pop(0)
        if q not in pts:
            continue
        t = pts.index(q)
        u, v, w = pts[t - 1], pts[t], pts[(t + 1) % len(pts)]
        if not (u[2] and v[2] and w[2]):
            continue
        ux, uy = w[0] - u[0], w[1] - u[1]
        L = math.hypot(ux, uy)
        if L == 0:
            continue
        d = abs((v[0] - u[0]) * uy - (v[1] - u[1]) * ux) / L
        if d <= flat:
            pts = pts[:t] + pts[t + 1:]
            look += [u, w]
            if touched is not None:
                touched.append(('drop', v[0], v[1]))
            if log is not None:
                log.append(('한 줄 위의 점 (%g, %g) 지움' % (v[0], v[1]), list(pts),
                            ['orig'] * len(pts)))
    c = contour.__class__()
    c.is_quadratic = contour.is_quadratic
    for x, y, on in pts:
        c += fontforge.point(x, y, on)
    c.closed = True
    return c

def seam_ok(before, after, ink, off=150, tol=3):
    """`restore_cut` 이 이은 곧은 변이 **원래 먹의 가장자리 위**를 지나는가.

    새 점을 걷어 내고 두 점을 곧게 이었을 때, 그 선이 흰 칸을 가로지르거나
    않는다 (祥 SemiBold 에서 羊 의 가로획 사이를 가로지른 대각선). 선 위를 촘촘히
    짚어, 짚은 자리마다 `tol` 칸 안에 먹이 있으면 받는다. 먹 한가운데를 지나는
    것은 받는다 — 녹아붙은 자리에서는 방의 참된 왼변이 변의 먹에 덮여 있다.
    """
    old = {(round(p.x, 3), round(p.y, 3)) for p in before}
    pts = [(p.x, p.y) for p in after]
    n = ink.shape[0]
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L < 1:
            continue
        # 원래 조각에 있던 변이면 볼 것 없다 — 새로 이은 변만 본다
        if any(True for _ in [0]) and (round(a[0], 3), round(a[1], 3)) in old and \
                (round(b[0], 3), round(b[1], 3)) in old:
            ia = [k for k, p in enumerate(before) if abs(p.x - a[0]) < 1e-3 and abs(p.y - a[1]) < 1e-3]
            ib = [k for k, p in enumerate(before) if abs(p.x - b[0]) < 1e-3 and abs(p.y - b[1]) < 1e-3]
            m = len(before)
            if ia and ib and ((ia[0] + 1) % m == ib[0] or (ib[0] + 1) % m == ia[0]):
                continue
        for k in range(1, int(L // 4)):
            x = a[0] + (b[0] - a[0]) * k * 4 / L
            y = a[1] + (b[1] - a[1]) * k * 4 / L
            r, c = int(round(n - off - y)), int(round(x))
            win = ink[max(r - tol, 0):r + tol + 1, max(c - tol, 0):c + tol + 1]
            if not win.any():
                return False          # 흰 칸 한가운데를 지난다 — 받지 않는다
    return True


def _edge_side(x, y, ang, segs, far, tol):
    """점 (x, y) 에서 방향 `ang`(도) 로 달리는 변이 어느 쪽 안내 선분과 **같은 변**인가.

    `segs` 는 [(쪽, x1, y1, x2, y2, 방향°)] — 안내 윤곽을 곡선대로 펴서 자른 선분.
    쪽은 ('L' 또는 'R', 안내 윤곽 번호) 처럼 무엇이든 되고, 그대로 돌려준다.
    방향이 `tol` 도 안이고 점에서 `far` 유닛 안에 있는 선분 가운데 가장 가까운 것의
    쪽. 없으면 None. 윤곽이 도는 방향이 같으므로, 한 획의 맞은편 변(방향이 반대)은
    짝이 되지 않는다.
    """
    best = None
    for side, x1, y1, x2, y2, a in segs:
        d = abs(ang - a) % 360
        if min(d, 360 - d) > tol:
            continue
        vx, vy = x2 - x1, y2 - y1
        L2 = vx * vx + vy * vy
        t = 0.0 if not L2 else max(0.0, min(1.0, ((x - x1) * vx + (y - y1) * vy) / L2))
        dd = math.hypot(x - (x1 + t * vx), y - (y1 + t * vy))
        if dd <= far and (best is None or dd < best[0]):
            best = (dd, side)
    return None if best is None else best[1]


def split_by_owner(contour, guide_left, guide_right, n=1000, off=150, tol=15.0, far=80.0,
                   log=None):
    """**윤곽 위의 점으로만** 녹아붙은 윤곽을 변과 방으로 가른다 — 새 점 없이.

    2026-09-29 사용자 지적: 겹친 자리를 되살리려는 것이니 가르는 선을 윤곽 밖에서
    들여오면 안 된다. 원래 점만 쓴다.

      1. 원래 점마다 **주인**을 정한다 — 변 · 방 · **둘 다**. 온커브 점은 들어오는
         변과 나가는 변이 각각 안내(같은 글자의 가는 굵기)의 변·방 가운데 어느 쪽
         윤곽과 **같은 방향으로 나란히 달리는지** 본다. 두 변의 쪽이 다르면 둘 다
         (두 성분이 **만난 점**)다.
      2. 만난 점에서 끊는다. 두 만난 점 사이 토막은 속의 점들의 주인을 따른다.
      3. 토막의 **양 끝 만난 점 둘을 곧게 이어** 닫는다. 만난 점은 이웃 토막에도
         들어 있어 양쪽에 속한다.

    오프커브 점은 제 거리로 변·방을 매긴다 — 만난 점이 되지 않는다. 만난 점이
    없으면 가르지 않는다. 돌아오는 것은 (변 조각들, 방 조각들). `tol`·`far` 는 변을
    짝지을 때 방향(도)·거리(유닛) 한계, `log` 는 점마다 주인·거리·변의 쪽을 받는다.
    """
    import numpy as np
    pts = [(p.x, p.y, p.on_curve) for p in contour]

    def dist_map(cs):
        m = _plate(cs, n, off)
        ys, xs = np.nonzero(m)
        return xs, (n - off - ys)

    lx, ly = dist_map(guide_left)
    rx, ry = dist_map(guide_right)

    def near(xs, ys, x, y):
        if not len(xs):
            return 1e9
        k = np.abs(xs - x) + np.abs(ys - y) < 200
        if not k.any():
            return 1e9
        return float(np.min(np.hypot(xs[k] - x, ys[k] - y)))

    # 주인은 셋이다 — 변(L) · 방(R) · **둘 다(B)** (2026-09-29 사용자 「가르기를 한 점은
    # 당연히 양쪽에 속한다」). 둘 다는 두 성분이 녹아붙으며 **만난 점**이다 — 떨어진
    # 글리프라면 변에도 방에도 없는 교차점 (祔 Medium 의 13 (351,442) · 8 (351,422)).
    #
    # 만난 점은 **변의 짝**으로 가린다 (2026-09-29 사용자 「점들 사이에 서로 매핑을
    # 잡을 수 있을까?」). 같은 모서리는 굵기가 달라도 들어오고 나가는 변의 방향이
    # 같다. 만난 점은 들어오는 변이 한 성분, 나가는 변이 다른 성분의 것이다. 전에는
    # 두 먹까지의 거리가 어림으로 정한 닿음 거리(1.5 × 가운데 값 + 2) 안이면 둘 다로
    # 봤는데, 祿 Bold 에서 만난 점 8 은 0.7 유닛 차이로 빠지고 다리 모서리 4 가
    # 잡혀 윤곽이 통째로 방에 갔다. 성분 **안에서** 획끼리 녹아붙은 점(祿 Bold 의
    # 10·16 — 두 변이 다 방)은 둘 다가 아니다.
    dl = [near(lx, ly, x, y) for x, y, _ in pts]
    dr = [near(rx, ry, x, y) for x, y, _ in pts]
    m = len(pts)
    segs = []
    for side, cs in (('L', guide_left), ('R', guide_right)):
        for gi, c in enumerate(cs):
            q = [(p.x, p.y) for p in _flat_pts(c)]
            for k in range(len(q)):
                (x1, y1), (x2, y2) = q[k - 1], q[k]
                if (x1, y1) != (x2, y2):
                    segs.append(((side, gi), x1, y1, x2, y2,
                                 math.degrees(math.atan2(y2 - y1, x2 - x1))))
    owner, sides, gids = [], [], []
    for i, (x, y, on) in enumerate(pts):
        fallback = 'L' if dl[i] < dr[i] else 'R'
        if not on:
            owner.append(fallback)
            sides.append(None)
            gids.append(None)
            continue
        j = (i - 1) % m
        while (pts[j][0], pts[j][1]) == (x, y) and j != i:
            j = (j - 1) % m
        k = (i + 1) % m
        while (pts[k][0], pts[k][1]) == (x, y) and k != i:
            k = (k + 1) % m
        a_in = math.degrees(math.atan2(y - pts[j][1], x - pts[j][0]))
        a_out = math.degrees(math.atan2(pts[k][1] - y, pts[k][0] - x))
        g_in = _edge_side(x, y, a_in, segs, far, tol)
        g_out = _edge_side(x, y, a_out, segs, far, tol)
        s_in, s_out = (g_in[0] if g_in else None), (g_out[0] if g_out else None)
        sides.append((s_in, s_out))
        gids.append((g_in, g_out))
        if s_in and s_out and s_in != s_out:
            owner.append('B')
        else:
            owner.append(s_in or s_out or fallback)
    if log is not None:
        log.append({'owner': ''.join(owner), 'dl': dl, 'dr': dr, 'sides': sides, 'reach': 0.0})
    # 조각은 **외곽선의 선분을 따라가며** 짓는다 (2026-09-30 사용자). 선분(온커브 점
    # 사이)마다 어느 안내 윤곽의 선분인지 매기고, 같은 안내 윤곽의 선분들을 윤곽 차례로
    # 이어 한 조각으로 만든다. 만난 점에 이르면 같은 안내 윤곽의 **다음 선분**이 시작하는
    # 곳으로 건너뛴다 — 건너뛴 선은 다른 성분 밑에 숨었던 제 변이다.
    #   禝 Bold: 다리 오른변은 방의 두 획에 두 번 끊긴다. 다리 = 12…17 ⇢ 44→45 ⇢ 12,
    #   윗획 = 17…44 ⇢ 17, 아랫획 = 45…12 ⇢ 45. 전에는 44→45 를 주인 없는 토막으로
    #   버리고 두 획을 한 조각으로 이어, 복원하기가 다리를 가로지르는 먹을 만들었다.
    #   祚 SemiBold: 丿 왼변은 礻 가로획과 다리에 끊겨 두 토막이지만 안내에서 한 윤곽
    #   (乍)이니 한 조각으로 잇는다.
    # 같은 쪽의 서로 다른 안내 윤곽이 **곧바로 이어 붙은** 곳은 성분 안에서 획끼리 녹아
    # 붙은 것이다 (祿 Bold 의 录) — 한 조각으로 둔다.
    ons = [i for i in range(m) if pts[i][2]]
    if len(ons) < 3:
        return ([contour], []) if owner.count('L') >= owner.count('R') else ([], [contour])
    E = len(ons)
    lab = []                                        # 선분마다 (쪽, 안내 윤곽) 또는 None
    for k in range(E):
        i, j = ons[k], ons[(k + 1) % E]
        g = gids[i][1] or gids[j][0]
        lab.append(g)
    side = []
    for k in range(E):
        if lab[k]:
            side.append(lab[k][0])
            continue
        i, j = ons[k], ons[(k + 1) % E]
        o = [x for x in (owner[i], owner[j]) if x != 'B']
        side.append(o[0] if o else ('L' if dl[i] + dl[j] < dr[i] + dr[j] else 'R'))
    if len(set(side)) < 2:
        return ([contour], []) if side[0] == 'L' else ([], [contour])
    # 짝 없는 선분은 같은 쪽 이웃의 안내 윤곽을 물려받는다
    for _ in range(E):
        changed = False
        for k in range(E):
            if lab[k] is None:
                for nb in ((k - 1) % E, (k + 1) % E):
                    if lab[nb] and side[nb] == side[k]:
                        lab[k] = lab[nb]
                        changed = True
                        break
        if not changed:
            break
    for k in range(E):
        if lab[k] is None:
            lab[k] = (side[k], 'k%d' % k)
    # 같은 쪽 선분이 곧바로 이어지면 (안내 윤곽이 달라도) 한 무리
    par = {}

    def find(x):
        par.setdefault(x, x)
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    for k in range(E):
        nk = (k + 1) % E
        find(lab[k])
        if side[k] == side[nk]:
            par[find(lab[k])] = find(lab[nk])
    # 무리마다 선분을 윤곽 차례로 모아 점을 늘어놓는다 — 선분 하나는 시작 온커브 점과
    # 그 뒤 오프커브 점들, 무리의 토막이 끝나면 끝 온커브 점을 넣고 다음 토막으로 건너뛴다.
    start = next(k for k in range(E) if side[k] != side[(k - 1) % E])
    groups = {}
    for t in range(E):
        k = (start + t) % E
        groups.setdefault(find(lab[k]), []).append(k)

    def build(idx):
        c = contour.__class__()
        c.is_quadratic = contour.is_quadratic
        for i in idx:
            c += fontforge.point(pts[i][0], pts[i][1], pts[i][2])
        c.closed = True
        return c

    left, right = [], []
    for key, ks in groups.items():
        seq = []
        for n_, k in enumerate(ks):
            i, j = ons[k], ons[(k + 1) % E]
            run = [i] + [(i + d) % m for d in range(1, (j - i) % m)]
            seq += run
            nxt = ks[(n_ + 1) % len(ks)]
            if nxt != (k + 1) % E or len(ks) == 1:
                seq.append(j)                        # 토막 끝 — 여기서 건너뛴다
        out = []
        for i in seq:
            if not out or (pts[i][0], pts[i][1]) != (pts[out[-1]][0], pts[out[-1]][1]):
                out.append(i)
        if len(out) > 1 and (pts[out[0]][0], pts[out[0]][1]) == (pts[out[-1]][0], pts[out[-1]][1]):
            out.pop()
        if sum(1 for i in out if pts[i][2]) < 3:
            continue
        (left if side[ks[0]] == 'L' else right).append(build(out))
    return left, right


def restore_joints(contour, original, **kw):
    """조각 안의 **건너뛴 곳마다** `restore_cut` 을 건다.

    건너뛴 곳은 이웃한 두 온커브 점이 원래 윤곽에서는 이웃이 아닌 자리다 (외곽선을
    따라가다 다른 성분 밑으로 숨은 제 변을 곧게 이은 곳). 그 자리를 닫는 선으로
    돌려놓고 되살린다. 조각을 닫는 선도 그 가운데 하나다.
    """
    near = kw.get('near', 0.5)
    orig_pts = set()
    edges = set()
    for c in original:
        q = [(round(p.x, 3), round(p.y, 3), p.on_curve) for p in c]
        for k in range(len(q)):
            orig_pts.add(q[k][:2])
            a, b = q[k], q[(k + 1) % len(q)]
            if a[2] and b[2]:
                edges.add((a[:2], b[:2]))
    # 건너뛴 곳은 **조각을 만든 그대로에서 한 번만** 정한다. 복원하다 끝점을 지우면
    # (곡선 이음) 새로 이웃이 된 점 쌍이 생기는데, 그것은 건너뛴 곳이 아니다 —
    # 다시 복원하면 곡선이 엉뚱하게 늘어난다 (祚 Bold 의 丿 이 礻 안으로 뻗었다).
    q = [(round(p.x, 3), round(p.y, 3), p.on_curve) for p in contour]
    joints = []
    for k in range(len(q)):
        a_, b_ = q[k], q[(k + 1) % len(q)]
        if a_[2] and b_[2] and (a_[:2], b_[:2]) not in edges \
                and a_[:2] in orig_pts and b_[:2] in orig_pts:
            joints.append((a_[:2], b_[:2]))
    cur = contour
    for ja, jb in joints:
        q = [(round(p.x, 3), round(p.y, 3), p.on_curve) for p in cur]
        m = len(q)
        hit = next((k for k in range(m) if q[k][:2] == ja and q[(k + 1) % m][:2] == jb
                    and q[k][2] and q[(k + 1) % m][2]), None)
        if hit is None:                              # 앞 복원이 끝점을 지웠다
            continue
        pl = list(cur)
        rot = pl[hit + 1:] + pl[:hit + 1]           # 건너뛴 곳이 닫는 선이 되게
        c2 = cur.__class__()
        c2.is_quadratic = cur.is_quadratic
        for p in rot:
            c2 += fontforge.point(p.x, p.y, p.on_curve)
        c2.closed = True
        cur = restore_cut(c2, original, keep_new=True, **kw)
    return cur


def _ink_plate(contours, n=250, off=150, em=1000.0):
    """윤곽을 곡선대로 펴서 n×n 판에 그린다 (칸은 XOR 로 비운다)."""
    import numpy as np
    from PIL import Image, ImageDraw
    k = n / float(em)
    acc = np.zeros((n, n), bool)
    for c in contours:
        pts = [(p.x, p.y) for p in _flat_pts(c)]
        if len(pts) < 3:
            continue
        im = Image.new('L', (n, n), 0)
        ImageDraw.Draw(im).polygon([(x * k, n - (off + y) * k) for x, y in pts], fill=255)
        acc ^= (np.array(im) > 0)
    return acc


def _skeleton(m):
    """Zhang–Suen 세선화 — 획의 가운데 선만 남긴다."""
    import numpy as np
    img = np.pad(m.copy(), 1)
    while True:
        changed = False
        for step in (0, 1):
            P = img
            p2, p3, p4 = np.roll(P, 1, 0), np.roll(np.roll(P, 1, 0), -1, 1), np.roll(P, -1, 1)
            p5, p6 = np.roll(np.roll(P, -1, 0), -1, 1), np.roll(P, -1, 0)
            p7, p8, p9 = np.roll(np.roll(P, -1, 0), 1, 1), np.roll(P, 1, 1), np.roll(np.roll(P, 1, 0), 1, 1)
            nb = [p2, p3, p4, p5, p6, p7, p8, p9]
            B = sum(x.astype(int) for x in nb)
            seq = nb + [p2]
            A = sum(((~seq[i]) & seq[i + 1]).astype(int) for i in range(8))
            if step == 0:
                c1, c2 = ~(p2 & p4 & p6), ~(p4 & p6 & p8)
            else:
                c1, c2 = ~(p2 & p4 & p8), ~(p2 & p6 & p8)
            kill = P & (B >= 2) & (B <= 6) & (A == 1) & c1 & c2
            if kill.any():
                img = P & ~kill
                changed = True
        if not changed:
            return img[1:-1, 1:-1]


def _depth(m):
    """칸마다 먹 가장자리까지 깎여 나가기까지의 걸음 수 (8-이웃 침식)."""
    import numpy as np
    d = np.zeros(m.shape, int)
    cur = m.copy()
    k = 0
    while cur.any():
        k += 1
        d[cur] = k
        e = cur.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                e &= np.roll(np.roll(cur, dy, 0), dx, 1)
        cur = e
    return d


def _grow_by(m, r):
    import numpy as np
    out = m.copy()
    for _ in range(int(r)):
        g = out.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                g |= np.roll(np.roll(out, dy, 0), dx, 1)
        out = g
    return out


def _glyph_marks(contours, n):
    """판에 그린 먹 · 뼈대 · 획 반너비(뼈대 칸의 깊이 가운데 값)."""
    import numpy as np
    m = _ink_plate(contours, n)
    sk = _skeleton(m)
    d = _depth(m)
    return m, sk, (float(np.median(d[sk])) if sk.any() else 0.0)


def _longest(out):
    """8-이웃으로 이어진 칸 토막 가운데 가장 긴 것 — (칸 수, (행, 열))."""
    import numpy as np
    n0, n1 = out.shape
    seen, best = np.zeros_like(out), (0, None)
    ys, xs = np.nonzero(out)
    for y0, x0 in zip(ys, xs):
        if seen[y0, x0]:
            continue
        stack, size = [(y0, x0)], 0
        seen[y0, x0] = True
        while stack:
            y, x = stack.pop()
            size += 1
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < n0 and 0 <= xx < n1 and out[yy, xx] and not seen[yy, xx]:
                        seen[yy, xx] = True
                        stack.append((yy, xx))
        if size > best[0]:
            best = (size, (y0, x0))
    return best


def stray(a, b, n=250, tol=3, marks=None):
    """a 의 뼈대가 b 의 먹 밖으로 **이어져 나간 가장 긴 길이** (유닛)와 그 자리.

    b 의 먹은 (a 의 획 반너비 − b 의 획 반너비) + `tol` 칸만큼 넓혀 본다 — 굵기가
    달라 생기는 차이는 봐준다. 같은 획이면 0 에 가깝고, b 에 없는 획이면 그 획
    길이만큼 나온다. `marks` 에 {id: (먹, 뼈대, 반너비)} 사전을 주면 다시 그리지 않는다.
    """
    def get(x):
        if marks is None:
            return _glyph_marks(x, n)
        k = id(x)
        if k not in marks:
            marks[k] = _glyph_marks(x, n)
        return marks[k]
    ma, sa, wa = get(a)
    mb, sb, wb = get(b)
    size, at = _longest(sa & ~_grow_by(mb, max(0.0, wa - wb) + tol))
    k = 1000.0 / n
    return size * k, (None if at is None else (at[1] * k, (n - at[0]) * k - 150))


def same_hanzi(a, b, n=250, tol=3, least=10, log=None):
    """두 윤곽 묶음이 **같은 한자(또는 같은 성분)를 적은 것인가** — 0 같음 · 1 다름.

    같은 글자를 다른 굵기로 적은 것처럼 **같은 좌표틀에 놓인** 두 글리프를 견준다.
    굵기가 달라도 같은 한자면 획의 가운데 선(뼈대)이 서로의 먹 안에 든다. 한쪽에만
    있는 획은 그 뼈대가 다른 쪽 먹 밖으로 길게 나간다 (祚 Text 의 안내 방에 들어간
    礻 오른쪽 짧은 획 — Regular 의 방 乍 에는 그 자리에 먹이 없다).

      1. 두 묶음을 n×n 판에 곡선대로 그리고 뼈대를 뽑는다.
      2. A 의 뼈대 가운데 B 의 먹을 (두 획 반너비의 차 + `tol` 칸) 넓힌 것 밖에 있는
         칸을 모은다 (`stray`). B→A 도 같이.
      3. 밖에 나간 칸이 이어져 `least` 칸 넘게 이어진 토막이 있으면 1.

    판 한 칸은 1000/n 유닛 (n=250 이면 4 유닛). `log` 에 리스트를 주면 방향마다 가장 긴
    토막의 길이와 자리를 적는다.
    """
    marks = {}
    ab = stray(a, b, n, tol, marks)
    ba = stray(b, a, n, tol, marks)
    if log is not None:
        for name, (L, at) in (('A→B', ab), ('B→A', ba)):
            log.append({'dir': name, 'len': L, 'at': at})
    return 1 if max(ab[0], ba[0]) > least * 1000.0 / n else 0


def split_glyph(contours, guide_left, guide_right):
    """글리프를 변과 방으로 가르고 잘린 자리를 되살린다 — (변 윤곽들, 방 윤곽들).

    윤곽마다 `split_by_owner` 로 가르고, 참으로 둘로 갈린 윤곽만 건너뛴 곳마다
    `restore_joints` 로 되살린다. `guide_left`·`guide_right` 는 같은 글자에서 변·방이 떨어진 더 가는
    굵기의 변·방 윤곽이다. 풀잎솜 tests/test_split_golden.py 가 이 함수의 결과를
    기준 글리프와 대조한다.
    """
    original = list(contours)
    left, right = [], []
    for c in original:
        a, d = split_by_owner(c, guide_left, guide_right)
        if a and d:
            a = [restore_joints(x, original, guide=guide_left) for x in a]
            d = [restore_joints(x, original, guide=guide_right) for x in d]
        left += a
        right += d
    return left, right


def _turn(contour):
    """윤곽이 감긴 쪽 — 부호만 본다. 먹과 흰 칸을 가릴 때 쓴다."""
    pts = [p for p in contour if p.on_curve]
    s = 0.0
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        s += a.x * b.y - b.x * a.y
    return 1 if s > 0 else -1


def loose_part(contours, rect, min_points=10):
    """네모 안에 온전히 든 **따로 된 윤곽** — 이미 갈려 있으면 자를 것이 없다.

    가는 굵기에서는 방·변이 제 윤곽으로 따로 있고, 굵어지면 몸통과 한 윤곽으로
    녹는다. 그래서 떼어 내기 전에 이것부터 본다. 그 안에 든 흰 칸도 함께 돌려준다.

    거를 것은 흰 칸인데, **상자 안에 들었다고 거르면 안 된다** — 틀 안에 놓인
    획은 틀의 상자 안에 통째로 들어 있다(羽 의 오른쪽 삐침). 흰 칸은 감긴 쪽이
    먹과 반대인 것으로 가린다.

    돌아오는 것은 (윤곽 목록, 쓴 윤곽 번호 집합) 또는 (None, set()).
    """
    x0, x1, y0, y1 = rect
    bs = [box(c) for c in contours]
    if not contours:
        return None, set()
    ink = _turn(max(contours, key=lambda c: len(list(c))))

    def inside(b, B):
        return B[0] <= b[0] and b[1] <= B[1] and B[2] <= b[2] and b[3] <= B[3]

    free = [i for i, c in enumerate(contours)
            if len(c) >= min_points and inside(bs[i], (x0, x1, y0, y1))
            and _turn(c) == ink]
    if len(free) != 1:
        return None, set()
    i = free[0]
    holes = [j for j in range(len(contours)) if j != i and inside(bs[j], bs[i])]
    return [contours[i]] + [contours[j] for j in holes], {i} | set(holes)


def _holes_in(contours, bb, used):
    """상자 안에 온전히 든 남은 윤곽들 — 조각의 흰 칸이다."""
    out = []
    for i, c in enumerate(contours):
        if i in used:
            continue
        b = box(c)
        if bb[0] <= b[0] and b[1] <= bb[1] and bb[2] <= b[2] and b[3] <= bb[3]:
            out.append(i)
    return out


def take_part(contours, rect, side='right', **kw):
    """조각을 떼어 낸다 — 따로 된 윤곽이면 그대로, 붙어 있으면 목에서 가른다.

    `loose_part` 와 `carve_out` 을 한 자리에서 고른다. 여덟 굵기를 한 길로
    다루려면 이것을 쓴다. 조각 안에 든 흰 칸도 함께 딸려 온다.
    돌아오는 것은 (윤곽 목록, 쓴 윤곽 번호 집합, 어떻게).
    """
    got, used = loose_part(contours, rect)
    if got is not None:
        return got, used, '따로 된 윤곽'
    nc, used, how = carve_out(contours, rect, side=side, **kw)
    if nc is None:
        return None, set(), how
    hs = _holes_in(contours, box(nc), used)
    return [nc] + [contours[i] for i in hs], used | set(hs), how


def drop_part(contours, rect, side='right', **kw):
    """조각을 버리고 **남는 것들** — `take_part` 의 짝.

    기증자에게서 조각을 떼어 오는 만큼, 받는 쪽에서는 제 조각을 버려야 한다.
    붙어 있던 경우에는 남는 고리도 이은 자리를 되살려 돌려준다.
    """
    got, used = loose_part(contours, rect)
    if got is not None:
        return ([c for i, c in enumerate(contours) if i not in used],
                used, '따로 된 윤곽')
    nc, used, how = carve_out(contours, rect, side=side, take='out', **kw)
    if nc is None:
        return None, set(), how
    keep, kused, _ = carve_out(contours, rect, side=side, **kw)   # 조각의 흰 칸은 조각 쪽이다
    if keep is not None:
        used = used | set(_holes_in(contours, box(keep), kused))
    return ([c for i, c in enumerate(contours) if i not in used] + [nc], used, how)


def part_side(contours, width, side='right'):
    """글리프에서 변 또는 방을 떼어 낸다 — 윤곽대로 갈리면 그대로, 붙었으면 잘라서.

    돌아오는 것은 (윤곽 목록, 어떻게 갈랐는지).
    """
    byun, bang = split_parts(contours, width)
    if byun is not None:
        return (bang if side == 'right' else byun), '윤곽대로'
    cs = list(contours)
    k = max(range(len(cs)), key=lambda i: len(cs[i]))
    run, t = split_seam(cs[k], side)
    if run is not None:
        rest = [c for i, c in enumerate(cs) if i != k and
                (box(c)[0] >= t - 1 if side == 'right' else box(c)[1] <= t + 1)]
        return [run] + rest, '맞댄 변에서 가름 (x %d)' % round(t)
    run, d = split_apart(cs[k], side)
    if run is None:
        return None, None
    rb = box(run)
    rest = [c for i, c in enumerate(cs) if i != k and
            (box(c)[0] >= rb[0] - 1 if side == 'right' else box(c)[1] <= rb[1] + 1)]
    return [run] + rest, '비스듬히 가름 (닫는 자리 %d)' % round(d)




# ─── 걸어가며 만나기 ─────────────────────────────────────────────────────
# 목을 **찾지** 않고 가지려는 조각의 테두리를 **걸어가다 만난다.** 어디를 자를지는
# 조각을 말로 정한 데서 나온다 — 「가로 윗변에서 솟았다 되돌아오는 것」처럼.

def walk_above(cs, ybar, roof, lo, hi, tol=3.0, near=100.0):
    """가로 윗변에서 솟은 획의 테두리를 훑는다.

    가벼운 굵기에서는 한 윤곽 안에서 다녀오지만, 굵어지면 끝이 위 가로획에
    **잘려** 테두리가 거기서 끊긴다. 끊긴 자리에는 반대편 가장자리를 가진
    점이 같은 높이에 남아 있다 — 그것이 «목» 이다. 그 점끼리 이어 건너뛰고
    (잘라내다) 이어서 마저 훑는다. 이은 자리는 뒤에 one_corner 로 한 점으로
    되돌린다 (복원하다).

    돌아오는 것은 [(점 목록, 목 자리, 목의 점 번호)] — 점은 (x, y, on_curve).
    목의 두 점이 **같은 자리**에 겹칠 수 있으므로(끝이 가로획에 딱 닿을 때)
    자리가 아니라 번호로 돌려준다.
    """
    def at_bar(p):
        return abs(p.y - ybar) < tol and lo <= p.x <= hi

    def at_roof(p):
        return abs(p.y - roof) < tol and lo <= p.x <= hi

    out = []
    for a, c in enumerate(cs):
        pts = list(c); n = len(pts)
        for i in range(n):
            if not at_bar(pts[i]):
                continue
            j = (i + 1) % n
            if not (pts[j].y > ybar + tol):
                continue
            run = [(pts[i].x, pts[i].y, pts[i].on_curve)]
            seam = None; seam_at = None
            k, cur, m = j, c, n
            steps = 0
            ok = False
            while steps < 4 * m:
                p = cur[k]
                run.append((p.x, p.y, p.on_curve))
                if abs(p.y - ybar) < tol and len(run) > 2:
                    ok = True
                    break
                if seam is None and at_roof(p) and len(run) > 2:
                    # 끊긴 자리 — 같은 높이의 짝을 찾아 건너뛴다.
                    # 끝이 가로획에 딱 닿으면 짝은 **같은 자리**에 있다(거리 0).
                    best = None
                    for b, c2 in enumerate(cs):
                        m2 = len(list(c2))
                        for k2, q in enumerate(c2):
                            if not q.on_curve:
                                continue
                            if b == a and (k2 - k) % m2 <= 1 or b == a and (k - k2) % m2 <= 1:
                                continue
                            if abs(q.y - p.y) > tol:
                                continue
                            d = abs(q.x - p.x)
                            if d > near:
                                continue
                            if best is None or d < best[0]:
                                best = (d, b, k2)
                    if best is None:
                        k = (k + 1) % m      # 짝이 없으면 끊긴 것이 아니다 — 그냥 간다
                        steps += 1
                        continue
                    _, b, k2 = best
                    seam = ((p.x, p.y), (cs[b][k2].x, cs[b][k2].y))
                    seam_at = len(run) - 1
                    cur, m = cs[b], len(list(cs[b]))
                    # 아래로 내려가는 쪽으로 간다
                    fwd = cur[(k2 + 1) % m].y < cur[k2].y
                    k = k2
                    p2 = cur[k]
                    run.append((p2.x, p2.y, p2.on_curve))
                    step = 1 if fwd else -1
                    k = (k + step) % m
                    while steps < 4 * m:
                        q = cur[k]
                        run.append((q.x, q.y, q.on_curve))
                        if abs(q.y - ybar) < tol:
                            ok = True
                            break
                        k = (k + step) % m
                        steps += 1
                    break
                k = (k + 1) % m
                steps += 1
            if not (ok and len(run) >= 4):
                continue
            xs = [q[0] for q in run]; ys = [q[1] for q in run]
            if max(xs) - min(xs) > 0.55 * (hi - lo) or max(ys) > roof + tol:
                continue                     # 엉뚱한 데로 샌 것
            out.append((run, seam, seam_at))
    # 같은 조각을 두 번 잡지 않도록 왼쪽 끝으로 추린다
    seen = {}
    for item in out:
        run = item[0]
        key = round(min(p[0] for p in run)), round(max(p[0] for p in run))
        if key not in seen or len(run) < len(seen[key][0]):
            seen[key] = item
    return sorted(seen.values(), key=lambda t: min(p[0] for p in t[0]))


def to_piece(run, ybar, over=0.0, quad=True):
    """훑은 테두리를 닫힌 윤곽으로 — 밑변은 가로획 속으로 over 만큼 파고들게."""
    import fontforge
    c = fontforge.contour()
    c.is_quadratic = quad
    for i, (x, y, on) in enumerate(run):
        yy = y - over if (i == 0 or i == len(run) - 1) and abs(y - ybar) < 3 else y
        c += fontforge.point(x, yy, on)
    c.closed = True
    return c


def restore_seam(contour, seam_at):
    """이은 두 점을 한 점으로 되돌린다 — 잘린 삼각형을 되살린다. 점이 하나 준다.

    `seam_at` 은 `walk_above` 가 준 점 번호. 두 점이 같은 자리에 겹칠 수 있어
    좌표로 찾으면 같은 점을 두 번 짚는다.
    """
    import fontforge
    if seam_at is None:
        return contour, None
    pts = list(contour)
    n = len(pts)
    a, b = seam_at % n, (seam_at + 1) % n
    if (pts[a].x - pts[b].x) ** 2 + (pts[a].y - pts[b].y) ** 2 < 0.25:
        # 두 점이 **같은 자리** — 끝이 가로획에 점으로만 닿은 것이라 잘려 나간
        # 삼각형이 없다. 되살릴 것이 없으니 겹친 점 하나만 지운다.
        nc = fontforge.contour()
        nc.is_quadratic = contour.is_quadratic
        for k, q in enumerate(pts):
            if k != b:
                nc += fontforge.point(q.x, q.y, q.on_curve)
        nc.closed = True
        return nc, None
    pair = [a, b]
    got = one_corner(contour, pair)
    if got is None:
        return contour, '체커가 막음'
    return got, None


# ─── 놓기 ────────────────────────────────────────────────────────────────

def dup(contours):
    """윤곽 묶음을 베낀다. 같은 객체를 두 번 넣으면 변형이 겹쳐 쌓인다."""
    return [c.dup() for c in contours]


def fit_box(contours, target):
    """윤곽 묶음을 상자에 맞춰 옮긴다 — 가로·세로를 따로 늘린다.

    target 은 (x0, x1, y0, y1). 가로로 누르면 세로획이 그만큼 가늘어지므로,
    굵기를 지켜야 할 때는 widen() 을 쓴다.
    """
    x0, x1, y0, y1 = bbox(contours)
    tx0, tx1, ty0, ty1 = target
    sx = (tx1 - tx0) / (x1 - x0)
    sy = (ty1 - ty0) / (y1 - y0)
    m = psMat.compose(psMat.translate(-x0, -y0),
                      psMat.compose(psMat.scale(sx, sy), psMat.translate(tx0, ty0)))
    out = []
    for c in contours:
        nc = c.dup()
        nc.transform(m)
        out.append(nc)
    return out, sx, sy


def columns(contours, band=None, tall=0.25, min_width=3, n=1200, base=1000):
    """**1차 스캔** — 세로선이 선 자리들. 가로 확장은 이걸 먼저 알아야 한다.

    가로획은 어느 x 에서나 먹이 조금씩 있으므로 먹의 **양** 으로는 못 가른다.
    세로선은 그 칸에서 먹이 길게 이어진다. 그래서 칸마다 가장 긴 먹 줄기를 재어
    띠 높이의 `tall` 몫을 넘으면 세로선으로 본다.

    돌아오는 것은 (x0, x1) 의 목록, 왼쪽부터. `band` 는 볼 높이 (ylo, yhi).
    """
    import numpy as np
    m = part_mask(contours, n=n, base=base)
    x0, x1, y0, y1 = bbox(contours)
    ylo, yhi = band if band else (y0, y1)
    r0, r1 = max(0, int(base - yhi)), min(m.shape[0], int(base - ylo))
    if r1 <= r0:
        return []
    # 재는 자는 **글리프 키** 다. 띠 키로 재면 띠가 짧을 때(益 의 皿) 두꺼운
    # 가로획까지 세로선으로 잡히고, 띠가 길 때는 짧은 세로선을 놓친다.
    limit = tall * (y1 - y0)
    hit = []
    for x in range(max(0, int(x0)), min(m.shape[1], int(x1) + 1)):
        col = m[r0:r1, x]
        if not col.any():
            continue
        d = np.diff(np.concatenate(([0], col.astype(np.int8), [0])))
        st = np.where(d == 1)[0]
        en = np.where(d == -1)[0]
        if len(st) and (en - st).max() >= limit:
            hit.append(x)
    out = []
    for x in hit:
        if out and x == out[-1][1] + 1:
            out[-1][1] = x
        else:
            out.append([x, x])
    return [(a, b) for a, b in out if b - a + 1 >= min_width]


def slide(contours, cut, d):
    """`cut` 보다 오른쪽 점만 d 만큼 민다 — 그 자리를 지나는 가로획이 길어진다.

    자를 자리는 반드시 세로선 **사이의 틈** 이어야 한다. 세로선 한가운데를
    지나면 그 획이 d 만큼 굵어진다.
    """
    out = []
    for c in contours:
        nc = fontforge.contour()
        nc.is_quadratic = c.is_quadratic
        for p in c:
            nc += fontforge.point(p.x + (d if p.x > cut else 0), p.y, p.on_curve)
        nc.closed = c.closed
        out.append(nc)
    return out


class _P(object):
    __slots__ = ('x', 'y', 'on_curve')

    def __init__(self, x, y, on):
        self.x = x
        self.y = y
        self.on_curve = on


def _flat_pts(contour, n=8):
    """곡선을 펴서 점열로 — 자를 자리를 볼 때는 조종점만 보아서는 안 된다.

    조종점 두 개 사이를 곧게 이으면 곡선이 부풀어 나간 자리를 놓친다.
    益 의 쓸어내리는 획이 그 틈으로 잘려 굵기가 여섯 배가 되었다.
    """
    pts = list(contour)
    m = len(pts)
    if m == 0:
        return []
    st = next((k for k in range(m) if pts[k].on_curve), 0)
    q = pts[st:] + pts[:st]
    out = []
    for i, p in enumerate(q):
        if p.on_curve:
            out.append(_P(p.x, p.y, True))
            continue
        a = out[-1] if out else _P(p.x, p.y, True)
        nx = q[(i + 1) % m]
        b = (nx.x, nx.y) if nx.on_curve else ((p.x + nx.x) / 2.0, (p.y + nx.y) / 2.0)
        for k in range(1, n + 1):
            u = k / float(n)
            v = 1 - u
            out.append(_P(v * v * a.x + 2 * v * u * p.x + u * u * b[0],
                          v * v * a.y + 2 * v * u * p.y + u * u * b[1], False))
    return out


def flat_cut(contours, lo, hi, tall=0.15, band=None, prefer_ink=True, mid=None):
    """lo..hi 사이에서 **가로변만 지나는** x — 없으면 None.

    곡선이 걸리거나(제어점이 낀 변은 가로로 볼 수 없다) 세로 덩이를 지나면
    버린다. `band` 를 주면 그 높이 안의 변과 먹만 본다 — 益 처럼 위에 八 이
    있어 어느 x 로도 사선을 피할 수 없는 글자는 아래 皿 만 보아야 한다.

    **칼날은 점 위에 놓지 않는다.** 미는 기준이 `x > t` 라 칼날 위의 점은 왼쪽에
    남고 이웃은 오른쪽으로 가, 그 변이 갈라져 획이 찢긴다.

    `prefer_ink` 면 **먹을 가로지르는 자리** 를 먼저 고른다. 칼날은 가로획을
    완전히 가로질러야 그 획이 늘어난다. 먹이 없는 데를 자르면 아무것도 늘지
    않고 두 쪽이 그냥 벌어진다. 남는 것 가운데 가운데에 가까운 것을 고른다.
    """
    import numpy as np
    m = part_mask(contours)
    x0, x1, y0, y1 = bbox(contours)
    ylo, yhi = band if band else (y0, y1)
    limit = tall * (y1 - y0)
    r0, r1 = max(0, int(1000 - yhi)), min(m.shape[0], int(1000 - ylo))
    mid = (lo + hi) / 2.0 if mid is None else mid
    good = []
    for t in range(int(lo), int(hi) + 1):
        if t < 0 or t >= m.shape[1] or r1 <= r0:
            continue
        ok = True
        for c in contours:                      # 칼날은 점 위에 놓지 않는다
            for p in c:
                if abs(p.x - t) < 1 and ylo - 1 <= p.y <= yhi + 1:
                    ok = False
                    break
            if not ok:
                break
        if not ok:
            continue
        for c in contours:
            pts = _flat_pts(c)
            nn = len(pts)
            for i in range(nn):
                a, b = pts[i], pts[(i + 1) % nn]
                # 밀 때 갈리는 기준(x > t)이 두 끝에서 다르면 그 변은 갈라진다.
                # 곱으로 재면 끝점이 칼날 **위에** 놓인 변을 놓친다 — 益 의
                # 쓸어내리는 획이 그렇게 찢겨 삼각형이 생겼다.
                if (a.x > t) == (b.x > t):
                    continue
                # 띠 **속** 을 지나는 변만 본다. 경계에 끝점만 닿은 변(띠 위의
                # 사선이 내려와 멈춘 자리)까지 세면 자를 데가 없어진다.
                if min(a.y, b.y) >= yhi or max(a.y, b.y) <= ylo:
                    continue
                if abs(a.y - b.y) > 1 or not (a.on_curve and b.on_curve):
                    ok = False
                    break
            if not ok:
                break
        if not ok:
            continue
        col = m[r0:r1, t]
        has = 0
        if col.any():
            d = np.diff(np.concatenate(([0], col.astype(np.int8), [0])))
            st = np.where(d == 1)[0]
            en = np.where(d == -1)[0]
            run = int((en - st).max()) if len(st) else 0
            if run > limit:
                continue
            # 가로획을 **몇 개** 가로지르는지 센다. 옆(x±8)에서도 같은 높이에
            # 먹이 있어야 가로획이다 — 비스듬한 획은 옆으로 가면 높이가 밀린다.
            # 띠에 가로획이 둘 이상이면(益 의 위 띠는 一 이 둘) 그것들을 **모두**
            # 지나는 자리를 골라야 한다. 하나만 지나면 나머지 한 획은 안 늘고
            # 그 옆의 삐침만 밀려나 사이가 벌어진다.
            for a2, b2 in zip(st, en):
                seg = np.zeros_like(col)
                seg[a2:b2] = True
                good_seg = True
                for dx in (-8, 8):
                    x2 = t + dx
                    if not (0 <= x2 < m.shape[1]):
                        good_seg = False
                        break
                    if int(np.logical_and(seg, m[r0:r1, x2]).sum()) < 0.6 * (b2 - a2):
                        good_seg = False
                        break
                if good_seg:
                    has += 1
        good.append((t, has))
    if not good:
        return None
    top = max(h for _, h in good)
    pick = ([t for t, h in good if h == top] if (prefer_ink and top)
            else [t for t, _ in good])
    return min(pick, key=lambda t: abs(t - mid))


def slices(contours, band=None, base=1000):
    """**1차 스캔** — 가로줄 하나가 먹을 몇 조각으로 끊는지.

    그 수가 곧 **칼날 수 + 1** 이다. 가장 잘게 끊기는 줄들이 이어진 무리를 잡아
    그 줄들의 x 자취를 겹치면 조각들이 나온다. 조각과 조각 사이의 틈이 자를 자리다.

    세로선을 세는 것(`columns`)보다 이쪽이 맞다. 曾 의 네모 칸 안에 든 점처럼
    **짧은 획** 도 한 조각으로 세어야 하기 때문이다 — 그것도 자리를 지켜야 한다.

    돌아오는 것은 (조각 수, 조각들 [(x0,x1)…], 그 줄들의 높이 (ylo, yhi)).
    """
    m = part_mask(contours, base=base)
    x0, x1, y0, y1 = bbox(contours)
    ylo, yhi = band if band else (y0, y1)
    rs = [r for r in range(max(0, int(base - yhi)), min(m.shape[0], int(base - ylo)))]
    cnt = {r: len(runs(m[r])) for r in rs}
    if not cnt or max(cnt.values()) == 0:
        return 0, [], None
    top = max(cnt.values())
    ys = [r for r in rs if cnt[r] == top]
    grp = []
    cur = None
    for r in ys:
        if cur and r == cur[-1] + 1:
            cur.append(r)
        else:
            if cur:
                grp.append(cur)
            cur = [r]
    if cur:
        grp.append(cur)
    g = max(grp, key=len)
    prof = m[g].any(0)
    return top, runs(prof), (base - g[-1], base - g[0])


def knife_bands(contours, min_share=0.07, base=1000):
    """칼날 수가 달라지는 데서 높이를 나눈다 — **칼날 수는 y 마다 다르다**.

    줄마다 조각 수를 세어 같은 수가 이어지는 띠로 묶는다. 너무 얇은 띠(획이
    시작되고 끝나는 어름)는 이웃 가운데 조각이 더 많은 쪽에 붙인다.
    """
    m = part_mask(contours, base=base)
    x0, x1, y0, y1 = bbox(contours)
    r0, r1 = max(0, int(base - y1)), min(m.shape[0], int(base - y0))
    n = [len(runs(m[r])) for r in range(r0, r1)]
    segs = []
    for k, v in enumerate(n):
        if segs and segs[-1][2] == v:
            segs[-1][1] = k
        else:
            segs.append([k, k, v])
    least = max(4, int(min_share * (y1 - y0)))
    while len(segs) > 1:
        short = [i for i, sg in enumerate(segs) if sg[1] - sg[0] + 1 < least]
        if not short:
            break
        i = min(short, key=lambda i: segs[i][1] - segs[i][0])
        a = segs[i - 1] if i > 0 else None
        b = segs[i + 1] if i + 1 < len(segs) else None
        into = a if b is None else (b if a is None else (a if a[2] >= b[2] else b))
        into[0] = min(into[0], segs[i][0])
        into[1] = max(into[1], segs[i][1])
        segs.pop(i)
        out = []
        for sg in segs:                      # 같은 수끼리 다시 붙인다
            if out and out[-1][2] == sg[2]:
                out[-1][1] = sg[1]
            else:
                out.append(sg)
        segs = out
    return [(base - (r0 + b), base - (r0 + a)) for a, b, _ in segs][::-1]


def _widen_plan(contours, delta, band, cut_tall, merge, share='even'):
    """한 띠의 계획 — (조각들, 칼날 자리, 조각마다 옮길 몫).

    틈마다 자를 자리를 찾아보고, 못 찾으면(Bold 처럼 점과 벽이 거의 붙은 데)
    그 두 조각을 한 덩이로 묶는다. 그래서 칼날 수는 굵기에 따라도 달라진다.
    어느 띠든 맨 바깥 덩이는 ∓delta/2 라 띠끼리 바깥 벽이 어긋나지 않는다.
    """
    _, segs, _ = slices(contours, band=band)
    tight = []
    for a, b in segs:
        if tight and a - tight[-1][1] <= merge:
            tight[-1][1] = b
        else:
            tight.append([a, b])
    segs = [(a, b) for a, b in tight]
    x0, x1, _, _ = bbox(contours)
    if not segs:
        return [], None, None, '먹이 없다'
    groups = [[segs[0]]]
    cuts = []
    for i in range(1, len(segs)):
        # 흰 틈 안에서만 찾으면 가로획 옆을 비켜간다(曾 의 지붕 윗변). 두 조각의
        # 복판까지 넓혀 찾되, 고르는 기준은 틈의 한가운데다.
        lo = (segs[i - 1][0] + segs[i - 1][1]) / 2.0
        hi = (segs[i][0] + segs[i][1]) / 2.0
        # 칼날 하나로 가르는 띠는 **먹의 한가운데**, 여럿이면 저마다 틈의 한가운데.
        aim = ((segs[0][0] + segs[-1][1]) / 2.0 if len(segs) == 2
               else (segs[i - 1][1] + segs[i][0]) / 2.0)
        t = flat_cut(contours, lo, hi, tall=cut_tall, band=band, mid=aim)
        if t is None:
            groups[-1].append(segs[i])      # 못 자르면 앞 덩이에 붙인다
        else:
            cuts.append(t)
            groups.append([segs[i]])
    if len(groups) < 2:
        t = flat_cut(contours, x0 + 0.25 * (x1 - x0), x0 + 0.75 * (x1 - x0),
                     tall=cut_tall, band=band)
        if t is None:
            return segs, None, None, '가로변만 지나는 자리를 못 찾았다'
        return segs, [t], [-delta / 2.0, delta / 2.0], None
    # 벌리는 몫을 칼날마다 어떻게 나누는가.
    #   'even'  똑같이. 확정해 리뷰에 등록한 글자들이 이 규칙으로 되어 있다.
    #   'gap'   틈(흰 칸)의 너비에 비례해. 칸들이 본디 비율 그대로 넓어진다.
    # 조각의 **복판** 으로 나누는 길도 있었으나 버렸다 — 바깥 조각이 제 발(세리프)
    # 까지 품어 복판이 바깥으로 밀려 가운데 칸만 좁아졌다(益 Bold 144·114·137).
    gaps = [groups[i][0][0] - groups[i - 1][-1][1] for i in range(1, len(groups))]
    if share == 'even':
        gaps = [1.0] * len(gaps)
    total = float(sum(gaps))
    if total <= 0:
        return segs, None, None, '틈이 없다'
    # 여기서는 소수로 둔다. 반올림은 붙박이(anchor)를 정한 **뒤** 한 번만 한다 —
    # 먼저 반올림하면 붙박이 쪽으로 옮기며 오차가 한 단위 실린다(僧 의 셋째 조각이
    # -11 로 나와 日 의 칸이 한 단위 좁았다). 옮기는 몫은 끝에 가서 정수여야 한다.
    move = [0.0]
    acc = 0.0
    for g in gaps:
        acc += delta * g / total
        move.append(acc)
    c = (move[0] + move[-1]) / 2.0
    move = [v - c for v in move]
    return segs, cuts, move, None


def widen_across(contours, delta, bands=None, cut_tall=0.25, merge=4,
                 min_share=0.07, anchor='center', share='even'):
    """**가로 확장** — 가로획만 늘이고 세로선은 자리만 옮긴다. 확대가 아니다.

    가로로 늘이면 세로획까지 굵어진다(益 을 1.32배 늘이면 皿 의 세로획이
    72–77 에서 80–94 가 된다). 그래서 늘이는 것이 아니라 **가로획을 잘라
    벌린다**. 자른 자리를 지나는 변은 모두 가로라, 밀면 그 변만 길어진다.

      1. **자르는 칼날의 수는 y 마다 다르다.** 줄마다 먹이 몇 조각으로 끊기는지
         세어 높이를 띠로 나누고(`knife_bands`), 띠마다 따로 잰다. 曾 은 지붕이
         두 조각, 네모 칸 안에 점이 든 데는 다섯 조각(칼날 넷), 아래 日 은 두
         조각이다. 益 은 위 八 이 두 조각, 아래 皿 이 네 조각이다.
      2. 조각과 조각 **사이의 틈** 에서 가로변만 지나는 x 를 자를 자리로 삼는다.
      3. 조각들의 복판을 기준으로 **같은 비율** 이 되게 옮긴다. 한가운데 것은
         제자리에 있고 왼쪽은 왼쪽으로, 오른쪽은 오른쪽으로 벌어진다. 어느 띠든
         맨 바깥 조각은 ∓delta/2 라, 띠가 달라도 바깥 벽은 어긋나지 않는다.

    `share` 는 벌리는 몫을 칼날마다 **똑같이** 나눌지('even'), 틈의 너비에 **비례**
    해 나눌지('gap') 이다. 益 의 皿 은 칸이 96·96·101 이라 even 이면 172·171·177,
    gap 이면 170·171·179 가 된다.

    `bands` 에 높이 띠를 손수 줄 수도 있다. `anchor` 는 어디를 붙박이로 두느냐다
    — 'center' 면 좌우로 반씩, 'left'·'right' 면 그쪽 끝을 두고 반대쪽으로만
    벌린다(僧 의 방은 亻 쪽으로만 벌려야 해서 'right' 로 둔다).

    돌아오는 것은 (새 윤곽, 알림).
    """
    import numpy as np
    bs = sorted(bands) if bands else knife_bands(contours, min_share=min_share)
    m = part_mask(contours)

    def plan_of(b):
        segs, cuts, move, why = _widen_plan(contours, delta, b, cut_tall, merge, share)
        if cuts is None:
            return None, why
        if anchor == 'left':
            move = [v - move[0] for v in move]
        elif anchor == 'right':
            move = [v - move[-1] for v in move]
        return (b, cuts, [float(round(v)) for v in move], segs), None

    def at(plan, px):
        cuts, move = plan[1], plan[2]
        j = 0
        while j < len(cuts) and px > cuts[j]:
            j += 1
        return move[j]

    # 이어진 획이 두 띠에 걸쳐 **다르게** 움직이면 그 획이 어긋난다(曾 의 가운뎃벽이
    # 사선이 되었다). 스스로 나눈 띠는 그런 경우 하나로 합쳐 같은 칼날을 쓰게 한다.
    # 띠를 손수 준 경우에는 그대로 따른다 — 부르는 쪽이 아는 것이다.
    for _ in range(len(bs) + 2):
        plans = []
        for b in bs:
            pl, why = plan_of(b)
            if pl is None:
                if why == '먹이 없다':
                    continue
                return None, {'띠': [round(b[0]), round(b[1])], 'why': why}
            plans.append(pl)
        if not plans:
            return None, {'why': '어느 띠에서도 자를 자리를 못 찾았다'}
        cut_at = None
        for i in range(len(plans) - 1):
            y = (plans[i][0][1] + plans[i + 1][0][0]) / 2.0
            r = int(1000 - y)
            if not (1 <= r < m.shape[0] - 1):
                continue
            both = np.logical_and(m[r + 2] if r + 2 < m.shape[0] else m[r],
                                  m[r - 2] if r - 2 >= 0 else m[r])
            xs = np.nonzero(both)[0]
            if any(abs(at(plans[i], int(x)) - at(plans[i + 1], int(x))) > 0.5 for x in xs):
                cut_at = i
                break
        if cut_at is None or bands is not None:
            break                       # 띠를 손수 주었으면 그대로 따른다
        a, b2 = plans[cut_at][0], plans[cut_at + 1][0]
        merged = (min(a[0], b2[0]), max(a[1], b2[1]))
        bs = [x for x in bs if not (x[0] >= merged[0] and x[1] <= merged[1])]
        bs.append(merged)
        bs.sort()

    def shift(px, py):
        k = None
        for i, (b, _, _, _) in enumerate(plans):
            if b[0] <= py <= b[1]:
                k = i
                break
        if k is None:
            k = min(range(len(plans)),
                    key=lambda i: min(abs(py - plans[i][0][0]),
                                      abs(py - plans[i][0][1])))
        _, cuts, move, _ = plans[k]
        j = 0
        while j < len(cuts) and px > cuts[j]:
            j += 1
        return move[j]

    out = []
    for c in contours:
        nc = fontforge.contour()
        nc.is_quadratic = c.is_quadratic
        for p in c:
            nc += fontforge.point(p.x + shift(p.x, p.y), p.y, p.on_curve)
        nc.closed = c.closed
        out.append(nc)
    info = {'늘린 몫': round(delta, 1),
            '나눔': [{'띠': [round(b[0]), round(b[1])], '조각': len(sg),
                     '칼날': [round(t) for t in cuts],
                     '옮긴 몫': [round(v, 1) for v in mv]}
                    for b, cuts, mv, sg in plans]}
    return out, info


# ─── 흰 칸 ───────────────────────────────────────────────────────────────

def stretch(contours, x0, x1, frm, to, over=12.0, over_to=0.0):
    """x0..x1 에 있는 획을 `frm` 에서 `to` 까지 늘인다 — 먹을 한 조각 얹는 식.

    두 가지를 반드시 지켜야 한다.

      · **겹쳐야 한다.** 변끼리 딱 맞대면 그 자리에 실낱 같은 흰 줄이 남는다.
        `over` 만큼 `frm` 쪽 획 속으로 파고들게 넣는다. 반대쪽도 이미 있는
        획에 가 닿는 것이라면 `over_to` 로 마찬가지로 겹친다.
      · **시계방향으로 감아야 한다.** 반시계로 넣으면 removeOverlap 이 구멍으로
        보아 겹친 자리가 하얗게 뒤집힌다. correctDirection 은 그 뒤라 늦다.

    `to` 가 `frm` 보다 작으면 아래로, 크면 위로 늘인다. **얹을 윤곽 하나를
    돌려준다** — 글리프에 넣는 것은 부르는 쪽 몫이다.
    """
    down = to < frm
    a = frm + over if down else frm - over
    b = to - over_to if down else to + over_to
    hi, lo = max(a, b), min(a, b)
    c = fontforge.contour()
    c.is_quadratic = contours[0].is_quadratic if contours else True
    for px, py in ((x0, hi), (x1, hi), (x1, lo), (x0, lo)):   # 시계방향 = 칠함
        c += fontforge.point(px, py, True)
    c.closed = True
    return c


def stacked_counters(contours, width, mid=(0.38, 0.58), max_width=0.16, max_gap=100):
    """가운데에 세로로 포개진 좁은 흰 칸 두 개 — (위 칸 번호, 아래 칸 번호).

    가로획이 기둥을 끊어 흰 칸이 둘로 갈린 자리를 찾는다(龜 의 가운데 기둥).
    """
    wd = width
    rects = [(i, box(c)) for i, c in enumerate(contours) if len(c) == 4]
    found = None
    for i, bi in rects:
        for j, bj in rects:
            if i >= j:
                continue
            if abs(bi[0] - bj[0]) > 12 or abs(bi[1] - bj[1]) > 12:
                continue                                    # x 가 같고
            if not (mid[0] * wd < (bi[0] + bi[1]) / 2 < mid[1] * wd):
                continue                                    # 가운데이고
            if bi[1] - bi[0] > max_width * wd:
                continue                                    # 좁고
            up, lo = (i, j) if bi[2] > bj[2] else (j, i)
            if box(contours[up])[2] - box(contours[lo])[3] > max_gap:
                continue                                    # 맞닿아 있고
            found = (up, lo)
    return found


def flat_edge(contours, x0, x1, below, skip=(), slack=2):
    """기둥 폭에 꼭 맞는 가로 변을 윤곽 전부에서 훑는다 — (윤곽 번호, 점 번호, y).

    가는 굵기에서는 아래 흰 칸이 따로 된 칸이 아니라 바깥 윤곽에 붙은 만(灣)이다.
    칸을 찾는 대신 변을 찾으면 여덟 굵기가 한 길로 처리된다.
    """
    best = None
    for k, c in enumerate(contours):
        if k in skip:
            continue
        pts = list(c)
        n = len(pts)
        for a in range(n):
            p1, p2 = pts[a], pts[(a + 1) % n]
            if not (p1.on_curve and p2.on_curve):
                continue
            if abs(p1.y - p2.y) > 1 or p1.y >= below:
                continue
            lx, rx = sorted((p1.x, p2.x))
            if abs(lx - x0) > slack or abs(rx - x1) > slack:
                continue
            if best is None or p1.y > best[2]:
                best = (k, a, p1.y)
    return best


def splice_detour(contours, seam, detour, drop=()):
    """윤곽 하나가 지나는 길에 우회로를 끼워 넣는다.

    흰 칸 둘을 잇는 방법이다. 칸을 따로 둔 채 변끼리 맞대기만 하면 그 자리에
    실낱이 비치고, 겹치면 감김수가 -2 가 되어 도로 검게 찬다. 윤곽 하나로
    이으면 맞닿은 변 자체가 없어진다.

    seam    (윤곽 번호, 점 번호) — 그 점 다음에 끼워 넣는다
    detour  끼워 넣을 (x, y) 들
    drop    버릴 윤곽 번호들
    """
    sk, sa = seam
    new = []
    for k, c in enumerate(contours):
        if k in drop:
            continue
        nc = fontforge.contour()
        nc.is_quadratic = c.is_quadratic
        for a, p in enumerate(c):
            nc += fontforge.point(p.x, p.y, p.on_curve)
            if k == sk and a == sa:
                for x, y in detour:
                    nc += fontforge.point(x, y, True)
        nc.closed = c.closed
        new.append(nc)
    return new


# ─── 세우기 ──────────────────────────────────────────────────────────────

def straighten(contours, idx, pick, center):
    """눕은 획을 세운다 — 점을 지우거나 더하지 않고 x 만 옮긴다.

    획이 눕은 만큼 되돌린 뒤 좌우 변을 각각 한 줄로 편다. 굵기도, 위아래
    이음매도 그대로 남는다(置 의 罒 과 目 을 잇는 획).

    idx     그 획이 들어 있는 윤곽 번호
    pick    그 윤곽에서 획에 해당하는 점 번호들
    center  세운 획을 놓을 x
    """
    pts = list(contours[idx])
    ylo = min(pts[k].y for k in pick)
    yhi = max(pts[k].y for k in pick)
    xlo = [pts[k].x for k in pick if abs(pts[k].y - ylo) < 1]
    xhi = [pts[k].x for k in pick if abs(pts[k].y - yhi) < 1]
    clo = (min(xlo) + max(xlo)) / 2.0
    chi = (min(xhi) + max(xhi)) / 2.0

    def ctr(y):
        return clo + (y - ylo) * (chi - clo) / (yhi - ylo)

    off = [pts[k].x - ctr(pts[k].y) for k in pick]
    right = [o for o in off if o > 0]
    left = [o for o in off if o < 0]
    width = sum(right) / len(right) - sum(left) / len(left)
    L, R = round(center - width / 2), round(center + width / 2)

    new = []
    for i, c in enumerate(contours):
        nc = fontforge.contour()
        nc.is_quadratic = c.is_quadratic
        for k, p in enumerate(c):
            x = p.x
            if i == idx and k in pick:
                x = L if p.x < ctr(p.y) else R
            nc += fontforge.point(x, p.y, p.on_curve)
        nc.closed = c.closed
        new.append(nc)
    return new, (L, R, clo, chi)


# ─── 자르기 ──────────────────────────────────────────────────────────────

def arcs(contour):
    """윤곽을 도막 목록으로 — 도막 하나는 (시작, 조종점 또는 None, 끝).

    이차 베지에만 다룬다. 조종점이 잇달아 오면 그 사이의 중점이 원래 점이므로
    (TrueType 의 줄임법) 그 자리를 끝으로 삼아 끊는다.
    """
    pts = list(contour)
    n = len(pts)
    st = next(k for k in range(n) if pts[k].on_curve)
    q = [pts[(st + k) % n] for k in range(n)]
    out = []
    k = 0
    while k < n:
        a = q[k]
        nxt = q[(k + 1) % n]
        if nxt.on_curve:
            out.append(((a.x, a.y), None, (nxt.x, nxt.y)))
            k += 1
        else:
            after = q[(k + 2) % n]
            end = ((after.x, after.y) if after.on_curve
                   else ((nxt.x + after.x) / 2.0, (nxt.y + after.y) / 2.0))
            out.append(((a.x, a.y), (nxt.x, nxt.y), end))
            k += 2 if after.on_curve else 1
    return out


def _lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _split_quad(P0, P1, P2, t):
    """드 카스텔조 — 곡선을 t 에서 둘로 쪼갠다. 모양은 그대로다."""
    A = _lerp(P0, P1, t)
    B = _lerp(P1, P2, t)
    C = _lerp(A, B, t)
    return (P0, A, C), (C, B, P2)


def _quad_roots(y0, y1, y2, yc=0.0):
    a = y0 - 2 * y1 + y2
    b = 2 * (y1 - y0)
    c = y0 - yc
    out = []
    if abs(a) < 1e-9:
        if abs(b) > 1e-9:
            out = [-c / b]
    else:
        d = b * b - 4 * a * c
        if d >= 0:
            r = math.sqrt(d)
            out = [(-b - r) / (2 * a), (-b + r) / (2 * a)]
    return sorted(t for t in out if 1e-6 < t < 1 - 1e-6)


def loop_clip(nodes, a, b, c):
    """a·x + b·y + c <= 0 인 쪽만 남긴다 — **곡선을 곡선인 채로** 쪼갠다.

    돌아오는 것은 **고리 목록** 이다. 자른 뒤 조각이 여럿으로 갈릴 수 있으므로
    하나로 이어 붙이지 않고 저마다 닫는다. 억지로 이으면 자른 선을 가로지르는
    없는 꼬리가 생긴다(丈 에서 겪은 것).

    점열로 펴서 자르면 점이 수십 개로 불어난다. 그래서 펴지 않는다.
    가로로 자르려면 아래쪽을 남길 때 (0, 1, -y), 위쪽을 남길 때 (0, -1, y).
    """
    def fv(q):
        return a * q[0] + b * q[1] + c

    out = []
    for P0, P1, P2 in nodes:
        parts = [(P0, P1, P2)]
        if P1 is None:
            if (fv(P0) <= 0) != (fv(P2) <= 0):
                t = fv(P0) / float(fv(P0) - fv(P2))
                M = _lerp(P0, P2, t)
                parts = [(P0, None, M), (M, None, P2)]
        else:
            ts = _quad_roots(fv(P0), fv(P1), fv(P2), 0.0)
            if ts:
                parts = []
                cur = (P0, P1, P2)
                prev = 0.0
                for t in ts:
                    u = (t - prev) / (1.0 - prev)
                    left, right = _split_quad(cur[0], cur[1], cur[2], u)
                    parts.append(left)
                    cur = right
                    prev = t
                parts.append(cur)
        for q0, q1, q2 in parts:
            mid = q1 if q1 else _lerp(q0, q2, 0.5)
            if (fv(q0) + fv(q2) + fv(mid)) / 3.0 <= 0.01:
                out.append((q0, q1, q2))
    if not out:
        return []
    runs_ = []
    cur = [out[0]]
    for k in range(1, len(out)):
        prev = cur[-1]
        if (abs(prev[2][0] - out[k][0][0]) < 0.01
                and abs(prev[2][1] - out[k][0][1]) < 0.01):
            cur.append(out[k])
        else:
            runs_.append(cur)
            cur = [out[k]]
    runs_.append(cur)
    if len(runs_) > 1:
        a0 = runs_[0][0][0]
        z = runs_[-1][-1][2]
        if abs(a0[0] - z[0]) < 0.01 and abs(a0[1] - z[1]) < 0.01:
            runs_[0] = runs_[-1] + runs_[0]
            runs_.pop()
    loops = []
    for rr in runs_:
        first, last = rr[0][0], rr[-1][2]
        if abs(first[0] - last[0]) > 0.01 or abs(first[1] - last[1]) > 0.01:
            rr = rr + [(last, None, first)]
        if len(rr) >= 3:
            loops.append(rr)
    return loops


def clip_contours(contours, a, b, c):
    """윤곽 묶음을 한 직선으로 잘라 남는 고리들 — `loop_clip` 를 죽 돌린다."""
    out = []
    for ct in contours:
        out.extend(loop_clip(arcs(ct), a, b, c))
    return out



def loops_clip(loops, a, b, c):
    """이미 도막 목록이 된 고리들을 한 번 더 자른다 — 선 여럿으로 좁혀 갈 때.

    반평면을 하나씩 잇달아 먹이면 볼록한 어떤 테두리로도 좁힐 수 있다. 한꺼번에
    자르려 들면 닫는 선이 모서리를 가로질러 엉뚱한 고리가 생긴다.
    """
    out = []
    for l in loops:
        out.extend(loop_clip(l, a, b, c))
    return out


def loop_area(nodes):
    """고리의 부호 있는 넓이 — 감김 방향을 보려는 것이다.

    자르면 오목한 만(灣)이 제 고리로 닫히는데, 그 고리는 먹과 방향이 거꾸로다.
    먹인지 흰 칸인지는 이 부호로 가른다.
    """
    pts = [P0 for P0, P1, P2 in nodes]
    s = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % len(pts)]
        s += x0 * y1 - x1 * y0
    return s / 2.0

def loop_box(nodes):
    """고리 하나의 상자 — (x0, x1, y0, y1). 조종점은 상자 안에 있으므로 뺀다."""
    xs = [q[0] for P0, P1, P2 in nodes for q in (P0, P2)]
    ys = [q[1] for P0, P1, P2 in nodes for q in (P0, P2)]
    return (min(xs), max(xs), min(ys), max(ys))


def loop_move(nodes, dx, dy):
    """고리를 옮긴다 — 크기는 건드리지 않는다."""
    def T(p):
        return None if p is None else (p[0] + dx, p[1] + dy)
    return [(T(P0), T(P1), T(P2)) for P0, P1, P2 in nodes]



def loop_scale(nodes, x0=0.0, y0=0.0, sx=1.0, sy=1.0):
    """고리를 (x0, y0) 을 붙박아 늘이거나 줄인다."""
    def T(p):
        return None if p is None else (x0 + (p[0] - x0) * sx, y0 + (p[1] - y0) * sy)
    return [(T(P0), T(P1), T(P2)) for P0, P1, P2 in nodes]

def loop_edge_to(nodes, y, to, within=None):
    """고리에서 y 위에 놓인 점을 to 로 옮긴다 — 맞댄 자리를 겹치게 하려는 것.

    자른 자리는 곧은 변이라 두 끝점만 옮기면 된다. 실낱이 비치지 않게 이쪽을
    상대 속으로 조금 파고들게 한다. to 가 y 보다 크면 위로 올린다.
    `within` 을 주면 그 x 범위에 든 점만 옮긴다 — 자른 변 가운데 일부만
    이어야 할 때 쓴다.
    """
    def T(p):
        if p is None or abs(p[1] - y) >= 0.01:
            return p
        if within is not None and not (within[0] <= p[0] <= within[1]):
            return p
        return (p[0], to)
    return [(T(P0), T(P1), T(P2)) for P0, P1, P2 in nodes]


def loop_contour(nodes, quad=True):
    """도막 목록을 fontforge 윤곽으로."""
    c = fontforge.contour()
    c.is_quadratic = quad
    for P0, P1, P2 in nodes:
        c += fontforge.point(P0[0], P0[1], True)
        if P1 is not None:
            c += fontforge.point(P1[0], P1[1], False)
    c.closed = True
    return c


def tidy(contours, tol=0.6):
    """한 줄 위에 늘어선 쓸데없는 점을 없앤다 — 자르면 그런 점이 생긴다.

    (고친 윤곽 목록, 지운 점 수) 를 돌려준다.
    """
    lay = []
    gone = 0
    for c in contours:
        pts = list(c)
        n = len(pts)
        keep = [True] * n
        for k in range(n):
            a, b, d2 = pts[(k - 1) % n], pts[k], pts[(k + 1) % n]
            if not (a.on_curve and b.on_curve and d2.on_curve):
                continue
            cross = abs((b.x - a.x) * (d2.y - a.y) - (b.y - a.y) * (d2.x - a.x))
            ln = math.hypot(d2.x - a.x, d2.y - a.y)
            if (ln > 1 and cross / ln < tol
                    and min(a.x, d2.x) - tol <= b.x <= max(a.x, d2.x) + tol
                    and min(a.y, d2.y) - tol <= b.y <= max(a.y, d2.y) + tol):
                keep[k] = False
                gone += 1
        nc = fontforge.contour()
        nc.is_quadratic = c.is_quadratic
        for k, p2 in enumerate(pts):
            if keep[k]:
                nc += fontforge.point(p2.x, p2.y, p2.on_curve)
        nc.closed = c.closed
        lay.append(nc)
    return lay, gone


