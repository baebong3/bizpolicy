#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
소상공인 정책 여론 브리프 — 월간 리포트 생성기 (정적 단일 HTML, JS 없음)

  python monthly_brief.py 2026-08 --db news.db --out reports/

news.db(news_db.py build 산출물)를 읽어 해당 월 기준의 지수·차트·표를
빌드타임 SVG로 렌더한 단일 HTML을 만든다. 관측 개시(2026-06) 이후
누적 월이 2개 이상이면 시계열 차트가 자동으로 포함된다.
"""
import argparse, base64, html, os, re, sqlite3
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP

# ── 하우스 팔레트 ──────────────────────────────────────────────
NAVY = "#1F3864"; LIME = "#8DC63F"; MID = "#4A6FA5"; PALE = "#BFD97A"
STEEL = "#6B7A8F"; RED = "#C0452B"; REDS = "#F7E5E1"
INK = "#16202C"; MUTED = "#8A93A0"; GRID = "#F1F3F6"; NAVYS = "#E7EAF0"
SERIES5 = [NAVY, LIME, MID, PALE, STEEL]
FIELD_COLOR = {"금융·자금": NAVY, "디지털·판로": LIME, "임대료·상가": MID,
               "전통시장·상권": PALE, "폐업·재기": "#B0713F", "고용·인력": "#9AA7B8",
               "정책·제도": STEEL}
def fcolor(name, i=0):
    return FIELD_COLOR.get(name, SERIES5[i % 5])

OBS_START = "2026-09"          # 관측 개시월(적재 시 DB 최소일자로 자동 갱신)
LOCAL_START_NOTE = "2026-09-01"  # 지자체 수집 개시일(동일)

# 쟁점어 집계 불용어 — 일반어 + 인물·정당명(정치적 중립 유지)
STOP_GENERIC = {"소상공인","자영업","자영업자","소공인","상인","상인회","점포","매장","정책","정부","지원","사업","위해","위한",
                "추진","확대","진행","운영","개최","마련","실시","모집","선정","발표","관련","대상","통해",
                "종합","단독","속보","오늘","기자","뉴스","영상","포토","전국","지역","한다","된다","있다",
                "모집","신청","접수","안내","성료","눈길","본격","나선다","나섰다","연다","열린다","함께","최대","시작",
                "방법","내용","됐다","했다","개시","실시","추진한다","밝혔다","진행한다"}
STOP_PERSON = {"오세훈","황희","이재명","김문수","한동훈","조국","이준석","민주당","국민의힘","개혁신당",
               "더불어민주당","조국혁신당","대통령","시장","의원","장관","총리","도지사","군수","구청장"}

KO = "'Pretendard','Apple SD Gothic Neo','Noto Sans KR','Malgun Gothic',sans-serif"


def f1(x):
    return str(Decimal(str(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))

def fmt(n):
    return f"{int(n):,}"

def esc(s):
    return html.escape(str(s), quote=True)

def month_label(ym):
    return f"{int(ym[5:7])}월"

def nsi(pos, neg, n):
    return 100.0 * (pos - neg) / n if n else 0.0

def negr(neg, n):
    return 100.0 * neg / n if n else 0.0


# ── 데이터 적재 ────────────────────────────────────────────────
def load(dbpath, ym):
    global OBS_START, LOCAL_START_NOTE
    con = sqlite3.connect(dbpath)
    mn = con.execute("SELECT MIN(date) FROM articles").fetchone()[0]
    if mn:
        OBS_START, LOCAL_START_NOTE = mn[:7], mn
    Q = lambda s, p=(): con.execute(s, p).fetchall()
    end = ym + "-31"
    D = {"ym": ym}

    D["months"] = [r[0] for r in Q(
        "SELECT DISTINCT substr(date,1,7) m FROM articles WHERE m>=? AND m<=? ORDER BY m",
        (OBS_START, ym))]

    # 월×스코프 집계 (관측 개시 이후)
    D["mscope"] = {}
    for m, sc, n, p, u, g in Q("""SELECT substr(date,1,7) m, scope, COUNT(*),
            SUM(sentiment='긍정'), SUM(sentiment='중립'), SUM(sentiment='부정')
            FROM articles WHERE substr(date,1,7)>=? AND substr(date,1,7)<=?
            GROUP BY m, scope""", (OBS_START, ym)):
        D["mscope"][(m, sc)] = dict(n=n, pos=p, neu=u, neg=g)

    # 당월 중앙 분야
    D["field"] = Q("""SELECT field, COUNT(*), SUM(sentiment='긍정'), SUM(sentiment='부정')
        FROM articles WHERE scope='중앙' AND field IS NOT NULL AND substr(date,1,7)=?
        GROUP BY field ORDER BY 2 DESC""", (ym,))

    # 중앙 분야 점유율 시계열
    D["field_ts"] = {}
    for m, f, n in Q("""SELECT substr(date,1,7) m, field, COUNT(*)
        FROM articles WHERE scope='중앙' AND field IS NOT NULL
          AND substr(date,1,7)>=? AND substr(date,1,7)<=? GROUP BY m, field""", (OBS_START, ym)):
        D["field_ts"].setdefault(m, {})[f] = n

    # 당월 중앙 부처별 부정
    D["dept_neg"] = Q("""SELECT dept, COUNT(*), SUM(sentiment='부정')
        FROM articles WHERE scope='중앙' AND dept IS NOT NULL AND dept<>'-' AND substr(date,1,7)=?
        GROUP BY dept HAVING SUM(sentiment='부정')>=1 ORDER BY 3 DESC, 2 DESC LIMIT 8""", (ym,))

    # 당월 지자체 시·도
    D["sido"] = Q("""SELECT sido, COUNT(*), SUM(sentiment='긍정'), SUM(sentiment='부정')
        FROM articles WHERE scope='지자체' AND sido IS NOT NULL AND substr(date,1,7)=?
        GROUP BY sido ORDER BY 2 DESC""", (ym,))

    # 당월 지자체 주제
    D["topic"] = Q("""SELECT t.topic, COUNT(*), SUM(a.sentiment='부정')
        FROM articles a JOIN article_topics t ON t.scope=a.scope AND t.id=a.id
        WHERE substr(a.date,1,7)=? GROUP BY t.topic ORDER BY 2 DESC""", (ym,))

    # 시·도 NSI 시계열 (당월 수집 상위 6개 시·도)
    top_sido = [r[0] for r in D["sido"][:6]]
    D["sido_ts"] = {}
    if top_sido:
        marks = ",".join("?" * len(top_sido))
        for m, sd, n, p, g in Q(f"""SELECT substr(date,1,7) m, sido, COUNT(*),
                SUM(sentiment='긍정'), SUM(sentiment='부정')
            FROM articles WHERE scope='지자체' AND sido IN ({marks})
              AND substr(date,1,7)>=? AND substr(date,1,7)<=? GROUP BY m, sido""",
                (*top_sido, OBS_START, ym)):
            D["sido_ts"].setdefault(sd, {})[m] = nsi(p, g, n)
    D["top_sido"] = top_sido

    # 당월 주차별 (스코프별)
    D["week"] = {}
    for wk, sc, n, p, g in Q("""SELECT strftime('%W', date) wk, scope, COUNT(*), SUM(sentiment='긍정'), SUM(sentiment='부정')
        FROM articles WHERE substr(date,1,7)=? GROUP BY wk, scope ORDER BY wk""", (ym,)):
        D["week"].setdefault(wk, {})[sc] = (n, p, g)

    # 당월 급증 구간 (지자체, 주차 n>=20 & 부정률>15%)
    D["surge"] = Q("""WITH w AS (SELECT strftime('%W',date) wk, MIN(date) d0, MAX(date) d1, sido,
            COUNT(*) n, SUM(sentiment='부정') g
        FROM articles WHERE scope='지자체' AND substr(date,1,7)=? GROUP BY wk, sido)
        SELECT wk, d0, d1, sido, n, g FROM w WHERE n>=20 AND 100.0*g/n>15
        ORDER BY 100.0*g/n DESC LIMIT 6""", (ym,))

    # 당월 전체 기사 (워드클라우드·핵심 이슈·대표기사) — 본문 요약이 있으면 병용
    D["all_arts"] = Q("""SELECT date, scope, COALESCE(sido, field, ''), sentiment,
            title || CASE WHEN description IS NOT NULL AND description<>''
                          THEN ' ' || substr(description,1,200) ELSE '' END
        FROM articles WHERE substr(date,1,7)=? ORDER BY date DESC""", (ym,))
    D["desc_n"] = Q("SELECT SUM(description IS NOT NULL AND description<>'') FROM articles WHERE substr(date,1,7)=?", (ym,))[0][0] or 0
    D["titles_only"] = Q("""SELECT date, scope, COALESCE(sido, field, ''), sentiment, title
        FROM articles WHERE substr(date,1,7)=? ORDER BY date DESC""", (ym,))
    D["neg_titles"] = [(d, sc, seg, t, '') for d, sc, seg, se, t in D["titles_only"] if se == '부정']

    # 워치리스트 (당월)
    D["watch"] = Q("SELECT date, name, dept, field, neg FROM watchlist WHERE substr(date,1,7)=? ORDER BY neg DESC", (ym,))
    con.close()
    return D


JOSA = ("에서","으로","이라","라는","에게","까지","부터","에는","에도",
        "은","는","이","가","을","를","의","도","로","에","와","과","만","라")

def _norm(w):
    for j in sorted(JOSA, key=len, reverse=True):
        if len(w) - len(j) >= 2 and w.endswith(j):
            return w[:-len(j)]
    return w

def _tokens(title):
    out = set()
    for w in re.findall(r"[가-힣]{2,}", title):
        w = _norm(w)
        if len(w) >= 2 and w not in STOP_GENERIC and w not in STOP_PERSON:
            out.add(w)
    return out

def word_stats(all_arts, k=34):
    """전체 기사 기준 (단어, 언급건수, 부정비중, 긍정비중)"""
    cnt, neg, pos = Counter(), Counter(), Counter()
    for _, _, _, se, t in all_arts:
        for w in _tokens(t):
            cnt[w] += 1
            if se == '부정': neg[w] += 1
            elif se == '긍정': pos[w] += 1
    return [(w, c, neg[w] / c, pos[w] / c) for w, c in cnt.most_common(k)]

def detect_issues(all_arts, top=3):
    """상위 키워드를 공출현 기준으로 병합하여 월간 핵심 이슈 도출"""
    kw_ids = {}
    for i, (_, _, _, _, t) in enumerate(all_arts):
        for w in _tokens(t):
            kw_ids.setdefault(w, set()).add(i)
    ranked = sorted(kw_ids.items(), key=lambda kv: -len(kv[1]))[:12]
    clusters = []
    for w, ids in ranked:
        placed = False
        for cl in clusters:
            inter = len(cl["ids"] & ids)
            if inter and inter / min(len(cl["ids"]), len(ids)) >= 0.35:
                cl["kws"].append(w); cl["ids"] |= ids; placed = True; break
        if not placed:
            clusters.append({"kws": [w], "ids": set(ids)})
    clusters.sort(key=lambda c: -len(c["ids"]))
    issues = []
    for cl in clusters[:top]:
        arts = [all_arts[i] for i in sorted(cl["ids"])]
        n = len(arts); g = sum(1 for a in arts if a[3] == '부정')
        segs = Counter(a[2] for a in arts if a[2])
        neg_arts = sorted([a for a in arts if a[3] == '부정'], key=lambda a: a[0], reverse=True)
        rep = (neg_arts[0] if neg_arts else arts[0])[4]
        issues.append(dict(name="·".join(cl["kws"][:2]), n=n, neg=g,
                           seg=(segs.most_common(1)[0][0] if segs else "-"), rep=rep))
    return issues
# ── SVG 차트 (빌드타임 렌더, 값축 생략·막대 끝 수치·라벨 회전 금지) ──

def svg_hbar(rows, width=560, color=None, unit="", sub=None, maxv=None, dec0=True):
    """rows: [(label, value)] — 가로 막대, 값은 막대 끝 표기, 값축 없음."""
    if not rows:
        return "<div class='empty'>해당 월 자료 없음</div>"
    n = len(rows)
    bh, gap, top = 22, 9, 4
    lw = 92                                 # 라벨 폭
    vw = 64                                 # 값 표기 여유
    H = top * 2 + n * (bh + gap) - gap
    mx = maxv or max(v for _, v in rows) or 1
    bw_max = width - lw - vw - 8
    out = [f"<svg viewBox='0 0 {width} {H}' width='100%' role='img'>"]
    for i, (lb, v) in enumerate(rows):
        y = top + i * (bh + gap)
        c = color(i, lb, v) if callable(color) else (color or NAVY)
        w = max(2, bw_max * v / mx)
        val = fmt(v) if dec0 else f1(v)
        out.append(f"<text x='{lw-6}' y='{y+bh-6}' text-anchor='end' font-size='12' fill='{INK}' font-family=\"{KO}\">{esc(lb)}</text>")
        out.append(f"<rect x='{lw}' y='{y}' width='{w:.1f}' height='{bh}' rx='3' fill='{c}'/>")
        out.append(f"<text x='{lw+w+6:.1f}' y='{y+bh-6}' font-size='12.5' fill='{INK}' class='num'>{val}{unit}</text>")
        if sub:
            out.append(f"<text x='{lw+w+6:.1f}' y='{y+bh-6}' font-size='0'> </text>")
    out.append("</svg>")
    return "".join(out)


def svg_grouped_bars(cats, series, width=560, unit=""):
    """cats: 월 라벨 / series: [(이름, 색, [값...])] — 세로 그룹 막대, 막대 위 수치."""
    ns, nc = len(series), len(cats)
    H, top, bot, side = 240, 30, 26, 12
    plot_h = H - top - bot
    mx = max(max(vals) for _, _, vals in series) or 1
    gw = (width - side * 2) / nc
    bw = min(44, (gw - 14) / ns)
    out = [f"<svg viewBox='0 0 {width} {H}' width='100%' role='img'>"]
    for gi, cat in enumerate(cats):
        x0 = side + gi * gw + (gw - bw * ns) / 2
        for si, (name, col, vals) in enumerate(series):
            v = vals[gi]
            h = plot_h * v / mx
            x = x0 + si * bw
            y = top + plot_h - h
            out.append(f"<rect x='{x:.1f}' y='{y:.1f}' width='{bw-3:.1f}' height='{h:.1f}' rx='3' fill='{col}'/>")
            out.append(f"<text x='{x+(bw-3)/2:.1f}' y='{y-5:.1f}' text-anchor='middle' font-size='11.5' fill='{INK}' class='num'>{fmt(v)}</text>")
        out.append(f"<text x='{side+gi*gw+gw/2:.1f}' y='{H-8}' text-anchor='middle' font-size='12' fill='{STEEL}' font-family=\"{KO}\">{esc(cat)}</text>")
    lx = side
    for name, col, _ in series:
        out.append(f"<rect x='{lx}' y='6' width='10' height='10' rx='2' fill='{col}'/>")
        out.append(f"<text x='{lx+14}' y='15' font-size='11.5' fill='{STEEL}' font-family=\"{KO}\">{esc(name)}</text>")
        lx += 14 + 11 * len(name) + 18
    out.append("</svg>")
    return "".join(out)


def svg_lines(cats, series, width=560, unit="", ymin=None, ymax=None, height=250, label_mode="all"):
    """cats × series[(이름,색,[값])] — 선형. label_mode: all=전 점 수치 / ends=시작·끝만.
    모든 수치 라벨은 열 단위로 y 간격(13px)을 강제하여 겹침을 제거."""
    top, bot, side, rlab = 16, 26, 46, 118
    H = height
    plot_w = width - side - rlab
    plot_h = H - top - bot
    allv = [v for _, _, vs in series for v in vs if v is not None]
    lo = ymin if ymin is not None else min(allv)
    hi = ymax if ymax is not None else max(allv)
    if hi - lo < 1e-9: hi, lo = hi + 1, lo - 1
    pad = (hi - lo) * 0.20
    lo, hi = lo - pad, hi + pad
    X = lambda i: side + (plot_w * i / max(1, len(cats) - 1) if len(cats) > 1 else plot_w / 2)
    Y = lambda v: top + plot_h * (1 - (v - lo) / (hi - lo))
    out = [f"<svg viewBox='0 0 {width} {H}' width='100%' role='img'>"]
    for gy in (0.0, 0.5, 1.0):
        yy = top + plot_h * gy
        out.append(f"<line x1='{side}' y1='{yy:.1f}' x2='{side+plot_w}' y2='{yy:.1f}' stroke='{GRID}'/>")
    for i, ct in enumerate(cats):
        out.append(f"<text x='{X(i):.1f}' y='{H-8}' text-anchor='middle' font-size='12' fill='{STEEL}' font-family=\"{KO}\">{esc(ct)}</text>")
    labels = []   # (col_index, x, y_pref, text, color, anchor)
    for name, col, vals in series:
        pts = [(i, X(i), Y(v), v) for i, v in enumerate(vals) if v is not None]
        if len(pts) > 1:
            path = "M" + " L".join(f"{x:.1f},{y:.1f}" for _, x, y, _ in pts)
            out.append(f"<path d='{path}' fill='none' stroke='{col}' stroke-width='2.4'/>")
        for i, x, y, v in pts:
            out.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='3.3' fill='{col}'/>")
        pick = pts if label_mode == "all" else ([pts[0]] if pts else [])
        for i, x, y, v in pick:
            labels.append([i, x, y - 9, f1(v), col, "middle"])
    # 우측: 계열명 + 최종값 (별도 열로 충돌 회피)
    ends = []
    for name, col, vals in series:
        vv = [(i, v) for i, v in enumerate(vals) if v is not None]
        if vv:
            i, v = vv[-1]
            txt = f"{f1(v)} {name}" if label_mode == "ends" else name
            ends.append([Y(v), txt, col, (f1(v) if label_mode == "ends" else None)])
    ends.sort()
    for k in range(1, len(ends)):
        if ends[k][0] - ends[k-1][0] < 14:
            ends[k][0] = ends[k-1][0] + 14
    for y, txt, col, _ in ends:
        yy = min(max(y, top + 8), H - bot - 4)
        out.append(f"<text x='{side+plot_w+8:.1f}' y='{yy+4:.1f}' font-size='11.5' fill='{col}' font-family=\"{KO}\"><tspan class='num'>{esc(txt.split(' ')[0]) if ' ' in txt else ''}</tspan> {esc(txt.split(' ',1)[1]) if ' ' in txt else esc(txt)}</text>")
    if label_mode == "ends":
        # 'ends' 모드에서 마지막 점 수치는 우측 라벨에 포함되므로 시작 점만 좌측 표기
        for L in labels:
            L[5] = "end"; L[1] -= 8; L[2] += 12
    # 열 단위 충돌 회피
    from collections import defaultdict
    cols = defaultdict(list)
    for L in labels:
        cols[(L[0], L[5])].append(L)
    for grp in cols.values():
        grp.sort(key=lambda L: L[2])
        for k in range(1, len(grp)):
            if grp[k][2] - grp[k-1][2] < 13:
                grp[k][2] = grp[k-1][2] + 13
    for i, x, y, txt, col, anch in labels:
        yy = min(max(y, top + 6), H - bot - 6)
        out.append(f"<text x='{x:.1f}' y='{yy:.1f}' text-anchor='{anch}' font-size='11' fill='{col}' class='num'>{txt}</text>")
    out.append("</svg>")
    return "".join(out)


def svg_stack100(rows, width=560):
    """rows: (라벨, 긍, 중, 부, NSI) — 100% 가로 스택바. 긍정률 좌측·부정률 우측 표기."""
    if not rows:
        return "<div class='empty'>자료 없음</div>"
    n = len(rows)
    bh, gap, top, lw, rw = 24, 10, 6, 96, 118
    H = top * 2 + n * (bh + gap) - gap
    bw = width - lw - rw
    out = [f"<svg viewBox='0 0 {width} {H}' width='100%' role='img'>"]
    for i, (lb, p, u, g, nsiv) in enumerate(rows):
        tot = (p + u + g) or 1
        y = top + i * (bh + gap)
        pw, gw = bw * p / tot, bw * g / tot
        uw = bw - pw - gw
        out.append(f"<text x='{lw-6}' y='{y+bh-7}' text-anchor='end' font-size='12' fill='{INK}' font-family=\"{KO}\">{esc(lb)}</text>")
        out.append(f"<rect x='{lw}' y='{y}' width='{pw:.1f}' height='{bh}' fill='{LIME}'/>")
        out.append(f"<rect x='{lw+pw:.1f}' y='{y}' width='{uw:.1f}' height='{bh}' fill='#E9EDF3'/>")
        out.append(f"<rect x='{lw+pw+uw:.1f}' y='{y}' width='{gw:.1f}' height='{bh}' fill='{RED}'/>")
        ptxt = f1(100.0*p/tot)
        if pw >= 44:
            out.append(f"<text x='{lw+6}' y='{y+bh-7}' font-size='11' fill='#243312' class='num'>{ptxt}%</text>")
        else:
            out.append(f"<text x='{lw+pw+uw+gw+6:.1f}' y='{y+bh-7}' font-size='0'></text>")
        out.append(f"<text x='{lw+bw+6:.1f}' y='{y+bh-7}' font-size='11.5' class='num' fill='{RED if g else MUTED}'>부정 {f1(100.0*g/tot)}%</text>")
    lx = lw
    for nm, cc in (("긍정", LIME), ("중립", "#E9EDF3"), ("부정", RED)):
        out.append(f"<rect x='{lx}' y='{H-2}' width='0' height='0' fill='{cc}'/>")
    out.append("</svg>")
    return "".join(out)


def svg_cloud(stats, width=1080, height=300):
    """정적 SVG 워드클라우드 — 나선 배치, 직사각 충돌 검사, 감성 색."""
    import math
    if not stats:
        return "<div class='empty'>자료 없음</div>"
    mx = stats[0][1]
    cx, cy = width / 2, height / 2
    placed = []
    out = [f"<svg viewBox='0 0 {width} {height}' width='100%' role='img'>"]
    def estw(t, fs):
        return sum((fs if ord(ch) > 0x3000 else fs * 0.58) for ch in t)
    for rank, (w, c, ns, ps) in enumerate(stats):
        fs = 13 + 27 * (c / mx) ** 0.5
        tw, th = estw(w, fs), fs * 1.12
        col = RED if ns >= 0.22 else ("#5E9C2B" if ps >= 0.55 else (NAVY if rank % 3 == 0 else (MID if rank % 3 == 1 else STEEL)))
        wt = 800 if c / mx > 0.5 else 600
        t = 0.0; pos = None
        while t < 220:
            r = 3.4 * t
            x = cx + r * math.cos(t) * 1.55
            y = cy + r * math.sin(t)
            box = (x - tw/2 - 4, y - th/2 - 2, x + tw/2 + 4, y + th/2 + 2)
            if box[0] > 4 and box[2] < width - 4 and box[1] > 2 and box[3] < height - 2 \
               and all(box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3] for b in placed):
                pos = (x, y); placed.append(box); break
            t += 0.35
        if not pos:
            continue
        out.append(f"<text x='{pos[0]:.1f}' y='{pos[1]+fs*0.34:.1f}' text-anchor='middle' font-size='{fs:.0f}' "
                   f"font-weight='{wt}' fill='{col}' font-family=\"{KO}\">{esc(w)}</text>")
    out.append("</svg>")
    return "".join(out)


def chip_cloud(pairs):
    if not pairs:
        return "<div class='empty'>해당 월 부정 기사 없음</div>"
    mx = pairs[0][1]
    out = ["<div class='cloud'>"]
    for w, c in pairs:
        sz = 12 + 12 * (c / mx)
        wt = 700 if c / mx > 0.55 else 500
        col = NAVY if c / mx > 0.55 else STEEL
        out.append(f"<span style='font-size:{sz:.0f}px;font-weight:{wt};color:{col}'>{esc(w)}<i class='num'>{c}</i></span>")
    out.append("</div>")
    return "".join(out)
# ── HTML 조립 ─────────────────────────────────────────────────

CSS_T = """
:root{--navy:%(NAVY)s;--lime:%(LIME)s;--mid:%(MID)s;--red:%(RED)s;--ink:%(INK)s;--muted:%(MUTED)s;--grid:%(GRID)s;--navys:%(NAVYS)s}
*{margin:0;padding:0;box-sizing:border-box}
%(FONTFACE)s
body{font-family:%(KO)s;color:var(--ink);background:#F7F8FA;-webkit-text-size-adjust:100%%}
.num,td.n,th.n{font-family:'ChivoNum',%(KO)s;font-variant-numeric:tabular-nums}
.wrap{max-width:1120px;margin:0 auto;padding:0 16px 44px}
header{background:var(--navy);color:#fff;padding:20px 0 18px;margin-bottom:18px}
header .wrap{padding-bottom:0}
.brand{font-size:12px;letter-spacing:.14em;color:var(--lime);font-weight:700}
h1{font-size:25px;margin-top:5px;font-weight:800}
.hsub{margin-top:7px;font-size:12.5px;color:#C9D3E4;display:flex;gap:8px;flex-wrap:wrap}
.chip{background:rgba(255,255,255,.12);border-radius:20px;padding:3px 11px}
.chip b{color:var(--lime)}
.sum{background:#fff;border:1.5px solid var(--navy);border-left:6px solid var(--lime);border-radius:10px;padding:15px 18px;margin-bottom:16px}
.sum h2{font-size:14.5px;color:var(--navy);margin-bottom:8px}
.sum h2::before{content:'◈ '}
.sum li{list-style:none;font-size:13.5px;line-height:1.62;padding-left:14px;position:relative}
.sum li::before{content:'ㅇ';position:absolute;left:0;color:var(--mid);font-size:11px;top:2px}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:18px}
.kpi{background:#fff;border:1px solid #E3E7EE;border-top:3px solid var(--navy);border-radius:10px;padding:12px 14px}
.kpi.lm{border-top-color:var(--lime)}.kpi.rd{border-top-color:var(--red)}
.kpi .l{font-size:11.5px;color:var(--muted);font-weight:600}
.kpi .v{font-size:24px;font-weight:700;margin:3px 0 2px;color:var(--navy)}
.kpi .s{font-size:11.5px;color:var(--muted)}
.kpi .up{color:#2E7D32;font-weight:700}.kpi .dn{color:var(--red);font-weight:700}
.sect{margin:26px 0 10px;border-bottom:2.5px solid var(--navy);padding-bottom:7px;display:flex;align-items:baseline;gap:10px}
.sect h2{font-size:17px;color:var(--navy)}
.sect .tag{font-size:11px;color:#fff;background:var(--navy);border-radius:4px;padding:2px 8px}
.sect .tag.lm{background:var(--lime);color:#243312}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.card{background:#fff;border:1px solid #E3E7EE;border-radius:10px;padding:14px 16px 12px}
.card.full{grid-column:1/-1}
.eyebrow{font-size:10.5px;letter-spacing:.12em;color:var(--lime);font-weight:800}
.ctitle{font-size:15px;font-weight:700;color:var(--navy);margin:2px 0 1px}
.csub{font-size:11.5px;color:var(--muted);margin-bottom:9px}
.note{font-size:11px;color:var(--muted);margin-top:7px;line-height:1.55}
.note::before{content:'※ '}
.empty{color:var(--muted);font-size:12.5px;padding:18px 0;text-align:center}
table.ttab{width:100%%;border-collapse:collapse;table-layout:fixed;margin-top:8px}
.ttab th{background:var(--navy);color:#fff;font-size:11.5px;padding:6px 4px;font-weight:600;word-break:keep-all}
.ttab td{font-size:12px;padding:5.5px 4px;border-bottom:1px solid var(--grid);text-align:center}
.ttab td:first-child{text-align:left;padding-left:8px;word-break:keep-all}
.ttab tr:nth-child(even) td{background:#FAFBFD}
.ttab tr.tot td{background:#FFF9EA;font-weight:700}
.ttab td.neg{color:var(--red);font-weight:600}
.ttab td.n{text-align:right;padding-right:10px}
.cloud{display:flex;flex-wrap:wrap;gap:9px 14px;align-items:baseline;padding:8px 2px}
.cloud i{font-style:normal;font-size:10px;color:var(--muted);margin-left:2px}
.news li{list-style:none;font-size:12.5px;line-height:1.6;padding:5px 0 5px 14px;border-bottom:1px dashed var(--grid);position:relative}
.news li::before{content:'-';position:absolute;left:2px;color:var(--muted)}
.news .d{color:var(--muted);font-size:11px}.news .g{color:var(--mid);font-size:11px;font-weight:600}
footer{margin-top:26px;border-top:1px solid #E3E7EE;padding-top:12px;font-size:11px;color:var(--muted);line-height:1.7}
footer b{color:var(--navy)}
@media(max-width:760px){.kpis{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}h1{font-size:20px}}
"""


def card(eyebrow, title, sub, body, note="", full=False):
    cls = "card full" if full else "card"
    nn = f"<div class='note'>{esc(note)}</div>" if note else ""
    return (f"<div class='{cls}'><div class='eyebrow'>{esc(eyebrow)}</div>"
            f"<div class='ctitle'>{esc(title)}</div><div class='csub'>{esc(sub)}</div>{body}{nn}</div>")


def build_html(D, font_b64):
    ym = D["ym"]; months = D["months"]; multi = len(months) >= 2
    ML = [month_label(m) for m in months]
    cur = {sc: D["mscope"].get((ym, sc), dict(n=0, pos=0, neu=0, neg=0)) for sc in ("중앙", "지자체")}
    prev_m = months[-2] if multi else None
    prev = {sc: D["mscope"].get((prev_m, sc)) for sc in ("중앙", "지자체")} if prev_m else {}

    c, l = cur["중앙"], cur["지자체"]
    tot_n = c["n"] + l["n"]; tot_neg = c["neg"] + l["neg"]; tot_pos = c["pos"] + l["pos"]
    nsi_c, nsi_l = nsi(c["pos"], c["neg"], c["n"]), nsi(l["pos"], l["neg"], l["n"])

    def dtxt(now, base, unit="p"):
        if base is None:
            return ""
        d = now - base
        cls, ar = ("up", "▲") if d >= 0 else ("dn", "▼")
        return f"전월 대비 <span class='{cls} num'>{ar}{f1(abs(d))}{unit}</span>"

    p_nsi_c = nsi(prev['중앙']['pos'], prev['중앙']['neg'], prev['중앙']['n']) if prev.get('중앙') else None
    p_nsi_l = nsi(prev['지자체']['pos'], prev['지자체']['neg'], prev['지자체']['n']) if prev.get('지자체') else None
    p_tot = (prev.get('중앙') or {'n':0,'pos':0,'neg':0}); p_tot2 = (prev.get('지자체') or {'n':0,'pos':0,'neg':0})
    p_n = p_tot['n'] + p_tot2['n']
    p_negr = negr(p_tot['neg'] + p_tot2['neg'], p_n) if p_n else None
    p_posr = 100.0 * (p_tot['pos'] + p_tot2['pos']) / p_n if p_n else None

    top_field = D["field"][0] if D["field"] else None
    hi_neg_topic = max(D["topic"], key=lambda r: negr(r[2], r[1])) if D["topic"] else None
    issues = detect_issues(D["all_arts"])
    wstats = word_stats(D["all_arts"])

    # ── 헤드: 이달의 핵심 이슈 ──
    circ = "①②③④⑤"
    ilis = []
    for i, it in enumerate(issues):
        ilis.append(
            f"<li><b>{circ[i]} {esc(it['name'])}</b>"
            f"<span class='is'>언급 <i class='num'>{fmt(it['n'])}</i>건 · 부정률 <i class='num'>{f1(100.0*it['neg']/it['n'])}</i>% · {esc(it['seg'])} 중심</span>"
            f"<span class='rep'>“{esc(it['rep'][:52])}”</span></li>")
    hero = (f"<div class='hero'><div class='ht'>이달의 핵심 이슈</div><ul>{''.join(ilis)}</ul>"
            f"<div class='hn'>※ 당월 기사 제목의 핵심어 공출현 군집으로 자동 도출 — 인물·정당명 제외</div></div>")

    # ── 요약 ──
    S = []
    line = f"순감성지수(NSI)는 중앙 <b class='num'>{f1(nsi_c)}</b>, 지자체 <b class='num'>{f1(nsi_l)}</b>"
    if p_nsi_c is not None:
        line += (f" — 전월 대비 각각 {'▲' if nsi_c>=p_nsi_c else '▼'}{f1(abs(nsi_c-p_nsi_c))}p, "
                 f"{'▲' if nsi_l>=p_nsi_l else '▼'}{f1(abs(nsi_l-p_nsi_l))}p")
    S.append(line)
    if top_field:
        share = 100.0 * top_field[1] / max(1, sum(r[1] for r in D["field"]))
        S.append(f"중앙 뉴스 최다 의제는 <b>{esc(top_field[0])}</b>({f1(share)}%), "
                 f"주제별 부정률 최고는 <b>{esc(hi_neg_topic[0]) if hi_neg_topic else '-'}</b>"
                 f"({f1(negr(hi_neg_topic[2], hi_neg_topic[1])) if hi_neg_topic else '0.0'}%)임")
    S.append(f"부정 급증 구간(주간 20건 이상·부정률 15% 초과)은 <b class='num'>{len(D['surge'])}</b>건 탐지됨"
             if D["surge"] else "부정 급증 구간(주간 20건 이상·부정률 15% 초과)은 탐지되지 않음")

    # ── KPI (지수·비율 중심) ──
    kpis = f"""
    <div class='kpis'>
      <div class='kpi'><div class='l'>중앙 순감성지수</div><div class='v num'>{f1(nsi_c)}</div><div class='s'>{dtxt(nsi_c, p_nsi_c) or '(긍정−부정)÷전체×100'}</div></div>
      <div class='kpi lm'><div class='l'>지자체 순감성지수</div><div class='v num'>{f1(nsi_l)}</div><div class='s'>{dtxt(nsi_l, p_nsi_l) or '(긍정−부정)÷전체×100'}</div></div>
      <div class='kpi lm'><div class='l'>긍정 비율</div><div class='v num'>{f1(100.0*tot_pos/max(1,tot_n))}%</div><div class='s'>{dtxt(100.0*tot_pos/max(1,tot_n), p_posr, 'p') or '중앙+지자체'}</div></div>
      <div class='kpi rd'><div class='l'>부정 비율</div><div class='v num'>{f1(negr(tot_neg, tot_n))}%</div><div class='s'>{dtxt(negr(tot_neg, tot_n), p_negr, 'p') or '중앙+지자체'}</div></div>
      <div class='kpi'><div class='l'>최다 의제(중앙)</div><div class='v' style='font-size:19px'>{esc(top_field[0]) if top_field else '-'}</div><div class='s'>점유율 <span class='num'>{f1(100.0*top_field[1]/max(1,sum(r[1] for r in D['field']))) if top_field else '0.0'}</span>%</div></div>
    </div>"""

    # ── NSI 추이 (전면 카드) ──
    if multi:
        nsic = [nsi(D["mscope"][(m,'중앙')]['pos'], D["mscope"][(m,'중앙')]['neg'], D["mscope"][(m,'중앙')]['n']) if (m,'중앙') in D["mscope"] else None for m in months]
        nsil = [nsi(D["mscope"][(m,'지자체')]['pos'], D["mscope"][(m,'지자체')]['neg'], D["mscope"][(m,'지자체')]['n']) if (m,'지자체') in D["mscope"] else None for m in months]
        nsi_card = card("INDEX · TREND", "월별 순감성지수 추이", "관측 개시 이후 · 계열 내 변화로만 해석",
                        svg_lines(ML, [("중앙", NAVY, nsic), ("지자체", LIME, nsil)], width=1080, height=250),
                        note="두 계열은 수집·분류 규칙이 달라 수준의 직접 비교는 부적절함 — 각 계열의 방향과 폭으로만 읽을 것", full=True)
    else:
        wk = sorted(D["week"].items())
        wlab = [f"{i+1}주차" for i in range(len(wk))]
        wc = [nsi(d.get('중앙',(0,0,0))[1], d.get('중앙',(0,0,0))[2], d.get('중앙',(0,0,0))[0]) if d.get('중앙',(0,))[0] else None for _, d in wk]
        wl = [nsi(d.get('지자체',(0,0,0))[1], d.get('지자체',(0,0,0))[2], d.get('지자체',(0,0,0))[0]) if d.get('지자체',(0,0,0))[0] else None for _, d in wk]
        nsi_card = card("INDEX · WEEKLY", f"{month_label(ym)} 주차별 순감성지수", "관측 1개월차 — 다음 호부터 월별 추이 자동 포함",
                        svg_lines(wlab, [("중앙", NAVY, wc), ("지자체", LIME, wl)], width=1080, height=250), full=True)

    # ── 중앙 파트 ──
    fsum = sum(r[1] for r in D["field"]) or 1
    frows = [(f, p, n - p - g, g, nsi(p, g, n)) for f, n, p, g in D["field"]]
    ftab = ["<table class='ttab'><colgroup><col style='width:96px'><col><col><col><col></colgroup>",
            "<tr><th>분야</th><th>긍정률</th><th>부정률</th><th>NSI</th><th>점유율</th></tr>"]
    for f, n, p, g in D["field"]:
        ftab.append(f"<tr><td>{esc(f)}</td><td class='num'>{f1(100.0*p/n)}%</td><td class='num neg'>{f1(negr(g,n))}%</td>"
                    f"<td class='num'>{f1(nsi(p,g,n))}</td><td class='num'>{f1(100.0*n/fsum)}%</td></tr>")
    ftab.append(f"<tr class='tot'><td>계</td><td class='num'>{f1(100.0*c['pos']/max(1,c['n']))}%</td>"
                f"<td class='num neg'>{f1(negr(c['neg'],c['n']))}%</td><td class='num'>{f1(nsi_c)}</td><td class='num'>100.0%</td></tr></table>")

    central_cards = [
        card("CENTRAL · SENTIMENT", f"분야별 논조 구성 — {month_label(ym)}", "긍정·중립·부정 구성비 (100% 기준)",
             svg_stack100(frows) + "".join(ftab), note=f"표본 중앙 {fmt(c['n'])}건 — 구성비·지수 산출 기반"),
        card("CENTRAL · WATCH", f"부처별 부정 기사 상위 — {month_label(ym)}", "부정 건수 기준 상위 부처",
             svg_hbar([(d, g) for d, n, g in D["dept_neg"]], color=RED) if D["dept_neg"]
             else "<div class='empty'>부정 기사 발생 부처 없음</div>",
             note="부정 분류는 규칙 기반 자동 판별 결과로, 부처 평가가 아니라 점검 우선순위 참고용임"),
    ]
    if multi:
        fields = [f for f, *_ in D["field"]][:5]
        fseries = []
        for i, f in enumerate(fields):
            vals = []
            for m in months:
                mm = D["field_ts"].get(m, {}); tot = sum(mm.values()) or 1
                vals.append(100.0 * mm.get(f, 0) / tot)
            fseries.append((f, fcolor(f, i), vals))
        central_cards.append(card("CENTRAL · AGENDA", "의제 점유율 추이", "중앙 수집 기사 중 분야 비중 · 단위 %",
                                  svg_lines(ML, fseries, width=1080, height=280, label_mode="ends"), full=True))

    # ── 지자체 파트 ──
    srows = sorted([(sd, n, p, g, nsi(p, g, n)) for sd, n, p, g in D["sido"]], key=lambda r: r[4])
    sbar = svg_hbar([(sd, round(v, 1)) for sd, n, p, g, v in srows],
                    color=lambda i, lb, v: RED if v < 20 else (MID if v < 30 else NAVY),
                    unit="", dec0=False)
    stab = ["<table class='ttab'><colgroup><col style='width:68px'><col><col><col><col></colgroup>",
            "<tr><th>시·도</th><th>NSI</th><th>긍정률</th><th>부정률</th><th>표본</th></tr>"]
    for sd, n, p, g, v in srows:
        stab.append(f"<tr><td>{esc(sd)}</td><td class='num'>{f1(v)}</td><td class='num'>{f1(100.0*p/n)}%</td>"
                    f"<td class='num neg'>{f1(negr(g,n))}%</td><td class='num' style='color:{MUTED}'>{fmt(n)}</td></tr>")
    stab.append(f"<tr class='tot'><td>계</td><td class='num'>{f1(nsi_l)}</td><td class='num'>{f1(100.0*l['pos']/max(1,l['n']))}%</td>"
                f"<td class='num neg'>{f1(negr(l['neg'],l['n']))}%</td><td class='num'>{fmt(l['n'])}</td></tr></table>")

    tbar = svg_hbar([(t, round(negr(g, n), 1)) for t, n, g in sorted(D["topic"], key=lambda r: -negr(r[2], r[1]))],
                    color=lambda i, lb, v: RED if v >= 8 else (MID if v >= 4 else STEEL), unit="%", dec0=False)

    local_cards = [
        card("LOCAL · INDEX", f"시·도별 순감성지수 — {month_label(ym)}", "낮을수록 부정 논조 우세 (오름차순 정렬)",
             sbar + "".join(stab),
             note="표본은 지수 산출 기반 참고치. 지자체 수집은 " + LOCAL_START_NOTE + " 개시"
                  + (" — 6월은 부분월 자료임" if ym == "2026-06" else "")),
        card("LOCAL · TOPIC", f"주제별 부정률 — {month_label(ym)}", "7개 정책 주제 · 다중 분류", tbar),
    ]
    if multi and D["top_sido"]:
        sseries = []
        pal6 = [NAVY, LIME, MID, PALE, STEEL, "#9AA7B8"]
        for i, sd in enumerate(D["top_sido"]):
            vals = [D["sido_ts"].get(sd, {}).get(m) for m in months]
            sseries.append((sd, pal6[i % 6], vals))
        local_cards.append(card("LOCAL · TREND", "시·도별 순감성지수 추이", "당월 표본 상위 6개 시·도",
                                svg_lines(ML, sseries, width=1080, height=290, label_mode="ends"),
                                note="표본이 작은 시·도는 월간 변동 폭이 커질 수 있어 방향 위주로 해석", full=True))

    # ── 쟁점 파트 ──
    surge_rows = ""
    if D["surge"]:
        rows = "".join(f"<tr><td>{esc(sd)}</td><td class='num'>{esc(d0[5:])}~{esc(d1[5:])}</td>"
                       f"<td class='num neg'>{f1(100.0*g/n)}%</td><td class='n num' style='color:{MUTED}'>{fmt(n)}</td></tr>"
                       for wkk, d0, d1, sd, n, g in D["surge"])
        surge_rows = ("<table class='ttab'><colgroup><col style='width:68px'><col><col><col></colgroup>"
                      "<tr><th>시·도</th><th>주간</th><th>부정률</th><th>표본</th></tr>" + rows + "</table>")
    else:
        surge_rows = "<div class='empty'>임계 기준(주간 표본 20건 이상 · 부정률 15% 초과)을 넘은 구간 없음</div>"

    seen, picked = set(), []
    for d, sc, seg, t, u in D["neg_titles"]:
        key = re.sub(r"\s+", "", t)[:22]
        if key in seen: continue
        seen.add(key); picked.append((d, sc, seg, t))
        if len(picked) == 6: break
    news_li = "".join(f"<li><span class='d num'>{esc(d[5:])}</span> <span class='g'>[{esc(sc)}·{esc(seg)}]</span> {esc(t[:56])}</li>"
                      for d, sc, seg, t in picked)

    issue_cards = [
        card("ISSUE · WORDCLOUD", f"이달의 언급 키워드 — {month_label(ym)}",
             "전체 기사 제목 기준 · 크기=언급량 · 적색=부정 비중 22% 이상, 녹색=긍정 비중 55% 이상",
             svg_cloud(wstats), note="인물·정당명 및 일반 행정어는 제외 — 이슈 중심 관측 원칙", full=True),
        card("ISSUE · SURGE", f"부정 급증 구간 탐지 — {month_label(ym)}", "지자체 · 주간 표본 20건 이상 & 부정률 15% 초과",
             surge_rows),
        card("ISSUE · NEGATIVE", f"대표 부정 기사 — {month_label(ym)}", "당월 최근 순 · 유사 제목 중복 제거",
             f"<ul class='news'>{news_li}</ul>" if news_li else "<div class='empty'>해당 없음</div>"),
    ]

    watch_html = ""
    if D["watch"]:
        wr = "".join(f"<tr><td>{esc(nm)}</td><td>{esc(dp)}</td><td>{esc(fd)}</td><td class='num neg'>{fmt(gg)}</td></tr>"
                     for _, nm, dp, fd, gg in D["watch"])
        watch_html = card("ISSUE · WATCHLIST", "정책과제 워치리스트", "부정 보도가 연결된 정책과제",
                          "<table class='ttab'><tr><th>과제</th><th>소관</th><th>분야</th><th>부정</th></tr>" + wr + "</table>", full=True)

    fontface = ""
    if font_b64:
        fontface = ("@font-face{font-family:'ChivoNum';src:url(data:font/woff2;base64,"
                    + font_b64 + ") format('woff2');font-weight:400 800}")
    css = CSS_T % dict(NAVY=NAVY, LIME=LIME, MID=MID, RED=RED, INK=INK, MUTED=MUTED,
                       GRID=GRID, NAVYS=NAVYS, KO=KO, FONTFACE=fontface)
    css += """
.hero{background:#fff;border:1.5px solid %s;border-radius:10px;padding:15px 18px;margin-bottom:14px;box-shadow:0 2px 8px rgba(31,56,100,.07)}
.hero .ht{font-size:14.5px;color:%s;font-weight:800;margin-bottom:9px}
.hero .ht::before{content:'★ ';color:%s}
.hero li{list-style:none;padding:7px 0;border-bottom:1px dashed %s;font-size:13.5px;line-height:1.55}
.hero li:last-child{border-bottom:none}
.hero b{color:%s;font-size:14.5px;margin-right:8px}
.hero .is{color:#4A5568;margin-right:8px}
.hero .is i{font-style:normal;font-weight:700;color:%s}
.hero .rep{display:block;color:%s;font-size:12px;margin-top:2px}
.hero .hn{font-size:10.5px;color:%s;margin-top:8px}
""" % (NAVY, NAVY, LIME, GRID, NAVY, NAVY, MUTED, MUTED)

    period = f"{ym}-01 ~ {ym}-31"
    return f"""<!DOCTYPE html><html lang='ko'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>소상공인 정책 여론 브리프 · {ym}</title><style>{css}</style></head><body>
<header><div class='wrap'>
  <div class='brand'>SOUTHERN POST R&amp;C · BIZPOLICY RADAR</div>
  <h1>소상공인 정책 여론 브리프 <span class='num'>{int(ym[:4])}</span>년 <span class='num'>{int(ym[5:7])}</span>월호</h1>
  <div class='hsub'><span class='chip'>기준기간 <b class='num'>{period}</b></span>
  <span class='chip'>분석 표본 <b class='num'>{fmt(tot_n)}</b>건 (중앙 {fmt(c['n'])} · 지자체 {fmt(l['n'])})</span>
  <span class='chip'>지표 <b>순감성지수(NSI)</b> · <b>긍정률·부정률</b></span></div>
</div></header>
<div class='wrap'>
  {hero}
  <div class='sum'><h2>지표 요약</h2><ul>{''.join(f'<li>{x}</li>' for x in S)}</ul></div>
  {kpis}
  {nsi_card}
  <div class='sect'><h2>중앙행정기관</h2><span class='tag'>CENTRAL</span></div>
  <div class='grid'>{''.join(central_cards)}</div>
  <div class='sect'><h2>지방자치단체</h2><span class='tag lm'>LOCAL</span></div>
  <div class='grid'>{''.join(local_cards)}</div>
  <div class='sect'><h2>이달의 쟁점</h2><span class='tag' style='background:{RED}'>ISSUE</span></div>
  <div class='grid'>{''.join(issue_cards)}{watch_html}</div>
  <footer>
    <b>지표 정의</b> — 순감성지수(NSI)=(긍정−부정)÷전체×100(높을수록 우호적 논조), 긍정률·부정률=각 감성÷전체×100. 모든 지수는 소수 첫째 자리(사사오입)로 통일.<br>
    <b>해석 유의</b> — 감성 라벨은 규칙 기반 자동 분류 결과이며, 중앙·지자체는 수집·분류 규칙이 서로 달라 두 계열 간 수준의 직접 비교는 부적절함(각 계열의 시계열 변화로만 해석). 관측 개시는 {OBS_START}(지자체 {LOCAL_START_NOTE}). 핵심 이슈·키워드 집계에서 인물·정당명은 제외함.<br>
    <b>생성</b> — bizpolicy 뉴스 아카이브(news.db) 기반 자동 생성 · (주)서던포스트알앤씨
  </footer>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("month", help="YYYY-MM")
    ap.add_argument("--db", default="news.db")
    ap.add_argument("--out", default=".")
    ap.add_argument("--font", default="chivonum.b64")
    a = ap.parse_args()
    assert re.fullmatch(r"\d{4}-\d{2}", a.month), "month는 YYYY-MM 형식"
    font_b64 = open(a.font).read().strip() if os.path.exists(a.font) else ""
    D = load(a.db, a.month)
    if not D["mscope"].get((a.month, "중앙")) and not D["mscope"].get((a.month, "지자체")):
        raise SystemExit(f"{a.month} 자료가 DB에 없습니다")
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, f"소상공인_정책_여론브리프_{a.month}.html")
    open(path, "w", encoding="utf-8").write(build_html(D, font_b64))
    print(f"생성: {path}  ({os.path.getsize(path):,} bytes)")


if __name__ == "__main__":
    main()
