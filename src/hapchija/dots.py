# -*- coding: utf-8 -*-
"""者 계열에 점을 찍는 자리 잡기 — `forms.addDot` 이 쓴다.

2026-09-28 풀잎솜 graft 스크립트(dotadd2)를 그대로 옮긴 것이다. 리뷰에서 확정한
윤곽(graft/dot2)과 여덟 굵기 72 자리가 점 하나까지 같아야 하므로 셈을 바꾸지
않았다. 전역이던 값은 설정 `C` 로 받는다.

  C = dict(DONOR, WIN, REF, ANGT, STH, LEN, LENW, DY, TOPSHARE, MINTOP, SINK)

점은 그리지 않고 같은 글꼴 點·黨 의 灬 에서 떼어 온다. 넷 중 원하는 기울기에
가장 가까운 것을 골라 눕히고, 자리는 Source Han Sans K 에서 잰 몫(REF 의 rx)을
쓴다. 글자 모양은 FreeType 으로 그려서 잰다 (PIL · 크기 1000 · 기준선 800).
"""
import math

import numpy as np
from fontTools.pens.recordingPen import RecordingPen
from PIL import Image, ImageDraw, ImageFont

N = 1000
SZ = 1000
BASE = 800
R = 200                                  # 살펴보는 창 반지름


def flat(p0, pts, n=8):
    out=[]
    for i in range(1, n+1):
        t=i/n; u=1-t
        if len(pts)==3:
            a,b,c=pts
            out.append((u**3*p0[0]+3*u*u*t*a[0]+3*u*t*t*b[0]+t**3*c[0],
                        u**3*p0[1]+3*u*u*t*a[1]+3*u*t*t*b[1]+t**3*c[1]))
        elif len(pts)==2:
            a,b=pts
            out.append((u*u*p0[0]+2*u*t*a[0]+t*t*b[0], u*u*p0[1]+2*u*t*a[1]+t*t*b[1]))
        else:
            a=pts[-1]; out.append((u*p0[0]+t*a[0], u*p0[1]+t*a[1]))
    return out


def contours(gs, name):
    p=RecordingPen(); gs[name].draw(p); out=[]; cur=[]; cp=None
    for op,a in p.value:
        if op=='moveTo': cur=[a[0]]; cp=a[0]
        elif op=='lineTo': cur.append(a[0]); cp=a[0]
        elif op in ('curveTo','qCurveTo'): cur+=flat(cp, list(a)); cp=a[-1]
        elif op=='closePath':
            if cur: out.append(cur); cur=[]
    if cur: out.append(cur)
    return out


def bb(c):
    xs=[p[0] for p in c]; ys=[p[1] for p in c]
    return min(xs),min(ys),max(xs),max(ys)


def slant(c):
    ys=sorted(p[1] for p in c); lo=ys[len(ys)//5]; hi=ys[-len(ys)//5-1]
    top=[p for p in c if p[1]>=hi]; bot=[p for p in c if p[1]<=lo]
    tx=sum(p[0] for p in top)/len(top); ty=sum(p[1] for p in top)/len(top)
    bx=sum(p[0] for p in bot)/len(bot); by=sum(p[1] for p in bot)/len(bot)
    return math.degrees(math.atan2(ty-by, bx-tx))


def pick_dot(tt, C):
    """點·黨 의 灬 에서 오른쪽 아래로 흐르는 점 가운데 가장 눕는 것을 고른다."""
    cm=tt.getBestCmap(); gs=tt.getGlyphSet(); got=[]
    for ch in C['DONOR']:
        for c in contours(gs, cm[ord(ch)]):
            x0,y0,x1,y1=bb(c); w,h=x1-x0,y1-y0
            if not (40<w<320 and 40<h<320 and y0<200 and y1<420): continue
            a=slant(c)
            if not (20 < a < 88): continue
            got.append((abs(a-C['ANGT']), -w*h, a, ch, c, (x0,y0,x1,y1)))
    if not got: return None
    got.sort()
    d=got[0]
    return (d[2], d[3], d[4], d[5])


def bar(path, ch, C):
    f=ImageFont.truetype(path, SZ); im=Image.new('L',(N,N),255)
    ImageDraw.Draw(im).text((0,BASE), ch, 0, font=f, anchor='ls')
    m=np.array(im)<128
    ys,xs=np.nonzero(m); ix0,ix1=xs.min(),xs.max()
    w0,w1=C['WIN'][ch]; a=int(ix0+(ix1-ix0)*w0); b=int(ix0+(ix1-ix0)*w1)
    runs=[]
    for y in range(N):
        r=m[y,a:b+1]
        if not r.any(): runs.append((0,0,0)); continue
        L=0; bs=0; cs=0; cl=0
        for i,v in enumerate(r):
            if v:
                if cl==0: cs=i
                cl+=1
                if cl>L: L=cl; bs=cs
            else: cl=0
        runs.append((L, a+bs, a+bs+L-1))
    L=max(r[0] for r in runs)
    qual=[y for y,r in enumerate(runs) if r[0]>=0.97*L]
    bands=[]                                   # 이어진 줄끼리 묶는다
    for y in qual:
        if bands and y-bands[-1][-1]<=2: bands[-1].append(y)
        else: bands.append([y])
    band=bands[-1]                             # 가장 아래 띠 = 耂 의 긴 가로획 (艹 는 위)
    own=np.zeros_like(m)                       # 가로획 자신의 픽셀
    for y in band: own[y, runs[y][1]:runs[y][2]+1]=True
    return (dict(L=float(L), x1=float(max(runs[y][2] for y in band)),
                 ybot=float(BASE-max(band)), th=float(max(band)-min(band)+1)), m, own)


def dilate(a, r):
    b=a.copy()
    for dy in range(-r, r+1):
        for dx in range(-r, r+1): b |= np.roll(np.roll(a,dy,0),dx,1)
    return b


def axis_pts(c, a, mx, my):
    """점을 눕혀 축이 가로가 되게 돌려 놓은 좌표."""
    r=math.radians(a); co,si=math.cos(r), math.sin(r)
    return [((x-mx)*co-(y-my)*si, (x-mx)*si+(y-my)*co) for x,y in c]


def put(ap, sl, st, ang, ox, oy):
    r=math.radians(-ang); co,si=math.cos(r), math.sin(r)
    return [((x*sl)*co-(y*st)*si+ox, (x*sl)*si+(y*st)*co+oy) for x,y in ap]


def place(ch, b, gmask, dot, size, clear, wname, C):
    """점을 놓는다.

    세로 자리와 여백은 Source Han Sans K 에서 잰 비율을 쓴다.
    가로 자리는 점의 축을 늘였을 때 가로획과 丿 이 만나는 자리를 가리키도록 잡는다.
    굵기는 굵기대로 두므로, 굵은 체에서 다른 획과 겹치면 겹친 채로 둔다."""
    ref=C['REF'][ch]; L=b['L']
    a, dch, c, (x0,y0,x1,y1) = dot
    mx,my=(x0+x1)/2.0,(y0+y1)/2.0
    ap=axis_pts(c, a, mx, my)

    def longest(r):
        L_=0; bs=0; cl_=0; cs=0
        for k,v in enumerate(r):
            if v:
                if cl_==0: cs=k
                cl_+=1
                if cl_>L_: L_=cl_; bs=cs
            else: cl_=0
        return L_, bs, bs+L_-1
    ys_,xs_=np.nonzero(gmask); ix0,ix1=xs_.min(), xs_.max()
    w0,w1=C['WIN'][ch]
    wa=int(ix0+(ix1-ix0)*w0); wb=int(ix0+(ix1-ix0)*w1)
    ytop=None
    for row in range(int(BASE-b['ybot'])+int(0.4*b['th']), gmask.shape[0]):
        ln, r0, r1 = longest(gmask[row, wa:wb+1])
        if ln >= 0.42*L:
            ytop = float(BASE-row); break
    if ytop is None: return None
    free = b['ybot'] - ytop

    # 점의 크기: 굵기마다 그대로. 빈 칸에 맞추어 줄이지 않는다.
    ln = C['LENW'].get(wname, C['LEN'])
    q  = put(ap, ln*size, C['STH']*size, C['ANGT'], 0, 0)
    lo = min(v for u,v in q); hi = max(v for u,v in q)
    lft= min(u for u,v in q); rgt= max(u for u,v in q)

    # 세로: 남는 틈을 위쪽에 더 준다. 틈이 없으면 아래로 묻어 위쪽을 틔운다.
    dh = hi - lo
    room = free - dh
    top = C['TOPSHARE']*room if room > 0 else 0.0
    top = max(top, max(4.0, C['MINTOP']*dh))
    bot = b['ybot'] - top - dh + C['DY'].get(ch, 0.0)*free   # 점의 아래끝
    if room > 0: bot = max(bot, ytop - 0.20*dh)
    cy = bot - lo

    # 가로: 가로획 아래끝에서 丿 의 오른쪽 모서리를 찾아, 그 점을 가리키게 한다
    probe_x = int(b['x1'] - ref['rx']*L)
    pts=[]
    for t in (0.12, 0.18, 0.24, 0.30, 0.36):
        row = int(BASE - (b['ybot'] - t*free))
        if not (0 <= row < gmask.shape[0]): continue
        xx = probe_x
        while xx > wa and not gmask[row, xx]: xx -= 1
        if xx > wa: pts.append((b['ybot']-t*free, float(xx)))
    if len(pts) >= 2:                       # x = m*y + c 로 맞춰 가로획 아래끝까지 늘인다
        ys=[p[0] for p in pts]; xs=[p[1] for p in pts]
        n=len(pts); my_=sum(ys)/n; mx_=sum(xs)/n
        den=sum((y-my_)**2 for y in ys)
        m=(sum((ys[i]-my_)*(xs[i]-mx_) for i in range(n))/den) if den else 0.0
        Px = m*b['ybot'] + (mx_ - m*my_); Py = b['ybot']
    else:
        Px = b['x1'] - ref['rx']*L - (rgt-lft); Py = b['ybot']
    ccy = cy + (lo+hi)/2.0                                  # 점의 한가운데 높이
    ccx = Px + (Py - ccy)/math.tan(math.radians(C['ANGT']))      # 축이 그 점을 가리키게
    cx  = ccx - (lft+rgt)/2.0
    # 겹치는 굵기에서는 축을 따라 위로 최대한 올린다. 위 획에는 닿지 않게.
    tan=math.tan(math.radians(C['ANGT']))
    if room <= 0:
        row=int(BASE-ytop)
        belw=np.zeros_like(gmask)
        if 0 <= row < gmask.shape[0]:
            ln_, r0, r1 = longest(gmask[row, wa:wb+1])
            if ln_ > 0.25*L: belw[row:, wa+r0:wa+r1+1] = True
        forb = gmask & ~belw
        pad=np.pad(forb, R)
        im=Image.new('L',(2*R,2*R),0)
        ImageDraw.Draw(im).polygon([(u-lft+20, 2*R-(v-lo+20)) for u,v in q], fill=255)
        dm=np.array(im)>0
        best=(cx, cy)
        for up in range(2, int(0.9*free)+2, 2):
            ny = cy + up; nx = cx - up/tan
            if (b['ybot'] - (ny+hi)) < clear: break
            py0=int(ny+lo)-20; px0=int(nx+lft)-20
            win = pad[BASE-py0-2*R+R : BASE-py0+R, px0+R : px0+3*R]
            if win.shape != (2*R, 2*R): break
            if (dm & dilate(win, clear)).any(): break
            best=(nx, ny)
        cx, cy = best
    return 0, 0, ln*size, C['STH']*size, cx, cy, round(ytop), round(rgt-lft), round(hi-lo), round(Px), round(Py)


