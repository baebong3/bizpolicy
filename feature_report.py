#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""월간 소상공인 정책 리포트 — 기획기사형 빌더 (단독 실행형)
  python feature_report.py 2026-09 --db news.db --out reports
editorial/<YYYY-MM>.json 편집 원고 필요 (editorial/_template.json 참조)"""
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



# ══════ 기획기사형 빌더 ══════
import json

CAT_COLOR = {"정치": NAVY, "경제": MID, "사회": "#5E9C2B", "오피니언": RED}

CSS = """
:root{--navy:%(NAVY)s;--lime:%(LIME)s;--mid:%(MID)s;--red:%(RED)s;--ink:%(INK)s;--muted:%(MUTED)s;--grid:%(GRID)s}
*{margin:0;padding:0;box-sizing:border-box}
%(FONT)s
body{font-family:%(KO)s;color:var(--ink);background:#FBFBF9;-webkit-text-size-adjust:100%%}
.num{font-family:'ChivoNum',%(KO)s;font-variant-numeric:tabular-nums}
.wrap{max-width:860px;margin:0 auto;padding:0 20px 52px}
header{background:var(--navy);color:#fff;padding:18px 0 16px}
.brand{font-size:11.5px;letter-spacing:.16em;color:var(--lime);font-weight:800}
.issue{font-size:13px;color:#C9D3E4;margin-top:4px}
.issue b{color:#fff}
.head{padding:34px 0 6px;border-bottom:3px solid var(--navy);margin-bottom:6px}
.hkick{font-size:13px;color:var(--lime);font-weight:800;letter-spacing:.06em;margin-bottom:8px}
.hkick::before{content:'■ ';color:var(--navy)}
h1{font-size:31px;line-height:1.32;font-weight:800;color:var(--navy);word-break:keep-all}
.lead{font-size:15.5px;line-height:1.8;color:#333;margin:16px 0 4px;word-break:keep-all}
.lead::first-letter{font-weight:700}
.strip{display:flex;gap:18px;align-items:center;background:#fff;border:1px solid #E6E4DC;border-left:5px solid var(--lime);border-radius:8px;padding:10px 16px;margin:18px 0 8px;flex-wrap:wrap}
.strip .st{font-size:12.5px;color:#444;line-height:1.6;flex:1;min-width:250px}
.strip .st b{color:var(--navy)}
.strip .sc{width:300px;max-width:100%%}
.sect{margin-top:34px}
.stag{display:inline-block;font-size:12px;font-weight:800;color:#fff;border-radius:3px;padding:3px 10px;letter-spacing:.08em}
.smeta{font-size:11.5px;color:var(--muted);margin-left:8px}
.sect h2{font-size:21px;color:var(--navy);margin:10px 0 2px;line-height:1.4;word-break:keep-all}
.sect h2::after{content:'';display:block;width:44px;height:3px;background:var(--lime);margin-top:8px}
.sect p{font-size:14.5px;line-height:1.86;margin-top:13px;color:#2A2A2A;text-align:justify;word-break:keep-all}
.sect p b{color:var(--navy)}
.qbox{background:#fff;border:1px solid #E6E4DC;border-radius:8px;margin-top:15px;padding:13px 17px}
.qbox .qt{font-size:11px;color:var(--muted);letter-spacing:.1em;font-weight:700;margin-bottom:7px}
.qbox li{list-style:none;font-size:13.5px;line-height:1.62;padding:6px 0 6px 20px;position:relative;color:#333;border-bottom:1px dashed var(--grid);word-break:keep-all}
.qbox li:last-child{border-bottom:none}
.qbox li::before{content:'“';position:absolute;left:2px;top:4px;color:var(--lime);font-size:19px;font-weight:800}
.qbox .qd{font-size:11px;color:var(--muted);margin-left:7px;white-space:nowrap}
.pull{border-left:4px solid var(--navy);background:#F4F6FA;padding:13px 17px;margin-top:15px;font-size:15px;line-height:1.7;color:var(--navy);font-weight:600;word-break:keep-all}
.pull .qd{font-size:11px;color:var(--muted);font-weight:400;display:block;margin-top:5px}
.cloudcard{background:#fff;border:1px solid #E6E4DC;border-radius:8px;margin-top:14px;padding:8px 8px 2px}
.outlook{background:var(--navy);color:#fff;border-radius:10px;padding:18px 20px;margin-top:34px}
.outlook h2{font-size:16px;color:var(--lime);margin-bottom:10px}
.outlook li{list-style:none;font-size:14px;line-height:1.75;padding:5px 0 5px 22px;position:relative;word-break:keep-all}
.outlook li::before{content:'▸';position:absolute;left:4px;color:var(--lime)}
footer{margin-top:30px;border-top:1px solid #E6E4DC;padding-top:12px;font-size:11px;color:var(--muted);line-height:1.75}
footer b{color:var(--navy)}
@media(max-width:640px){h1{font-size:24px}.strip{flex-direction:column;align-items:stretch}.strip .sc{width:100%%}}
""" 


def build(ym, db, outdir, font_b64):
    ed_path = os.path.join("editorial", f"{ym}.json")
    if not os.path.exists(ed_path):
        raise SystemExit(f"편집 원고가 없습니다: {ed_path}\n"
                         f"→ editorial 폴더에 {ym}.json을 작성한 뒤 다시 실행하세요 (기존 월 파일을 복사해 수정하면 됩니다)")
    ed = json.load(open(ed_path, encoding="utf-8"))
    D = load(db, ym)
    months, ML = D["months"], [month_label(m) for m in D["months"]]
    cur = {sc: D["mscope"].get((ym, sc), dict(n=0, pos=0, neu=0, neg=0)) for sc in ("중앙", "지자체")}
    c, l = cur["중앙"], cur["지자체"]
    nsi_c, nsi_l = nsi(c["pos"], c["neg"], c["n"]), nsi(l["pos"], l["neg"], l["n"])

    # 미니 NSI 추이
    if len(months) >= 2:
        nc = [nsi(*[D["mscope"][(m, '중앙')][k] for k in ('pos', 'neg', 'n')]) if (m, '중앙') in D["mscope"] else None for m in months]
        nl = [nsi(*[D["mscope"][(m, '지자체')][k] for k in ('pos', 'neg', 'n')]) if (m, '지자체') in D["mscope"] else None for m in months]
        mini = svg_lines(ML, [("중앙", NAVY, nc), ("지자체", LIME, nl)], width=300, height=132, label_mode="ends")
    else:
        mini = ""

    strip = (f"<div class='strip'><div class='st'>이달의 논조 — 순감성지수(NSI) 중앙 <b class='num'>{f1(nsi_c)}</b> · "
             f"지자체 <b class='num'>{f1(nsi_l)}</b>, 부정률 <b class='num'>{f1(negr(c['neg']+l['neg'], max(1,c['n']+l['n'])))}%</b> "
             f"<span style='color:var(--muted)'>(분석 표본 {fmt(c['n']+l['n'])}건)</span><br>{esc(ed.get('strip',''))}</div>"
             + (f"<div class='sc'>{mini}</div>" if mini else "") + "</div>")

    # 섹션
    sects = []
    for sc in ed["sections"]:
        cat = sc["cat"]; col = CAT_COLOR.get(cat, NAVY)
        meta = sc.get("meta", "")
        paras = "".join(f"<p>{p}</p>" for p in sc["paras"])
        pull = ""
        if sc.get("pull"):
            pull = f"<div class='pull'>“{esc(sc['pull']['t'])}”<span class='qd'>— {esc(sc['pull']['d'])} 보도 제목</span></div>"
        quotes = ""
        if sc.get("quotes"):
            lis = "".join(f"<li>{esc(q['t'])}<span class='qd num'>{esc(q['d'])}</span></li>" for q in sc["quotes"])
            quotes = f"<div class='qbox'><div class='qt'>{esc(sc.get('qtitle','주요 보도 제목'))}</div><ul>{lis}</ul></div>"
        sects.append(f"<div class='sect'><span class='stag' style='background:{col}'>{esc(cat)}</span>"
                     f"<span class='smeta'>{esc(meta)}</span><h2>{esc(sc['title'])}</h2>{paras}{pull}{quotes}</div>")

    cloud = svg_cloud(word_stats(D["all_arts"], k=26), width=820, height=230)
    dn = D.get("desc_n", 0)
    desc_note = (f"(키워드·이슈 집계에는 본문 요약 병용 — 당월 {fmt(dn)}건 확보)" if dn
                 else "(본문 미수집 — 이후 수집분부터 본문 요약 병용)")
    outlook = "".join(f"<li>{esc(o)}</li>" for o in ed["outlook"])

    font = (f"@font-face{{font-family:'ChivoNum';src:url(data:font/woff2;base64,{font_b64}) format('woff2');font-weight:400 800}}"
            if font_b64 else "")
    css = CSS % dict(NAVY=NAVY, LIME=LIME, MID=MID, RED=RED, INK=INK, MUTED=MUTED, GRID=GRID, KO=KO, FONT=font)

    html = f"""<!DOCTYPE html><html lang='ko'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>월간 소상공인 정책 리포트 · {ym}</title><style>{css}</style></head><body>
<header><div class='wrap' style='padding-bottom:0'>
 <div class='brand'>SOUTHERN POST R&amp;C · BIZPOLICY MONTHLY</div>
 <div class='issue'>월간 소상공인 정책 리포트 <b class='num'>{int(ym[:4])}년 {int(ym[5:7])}월호</b> · 기준기간 <span class='num'>{ym}</span></div>
</div></header>
<div class='wrap'>
 <div class='head'><div class='hkick'>{esc(ed['kicker'])}</div><h1>{esc(ed['headline'])}</h1>
 <p class='lead'>{ed['lead']}</p></div>
 {strip}
 {''.join(sects)}
 <div class='sect'><span class='stag' style='background:{STEEL}'>키워드</span>
 <h2>이달의 언급 지형</h2>
 <div class='cloudcard'>{cloud}</div>
 <p style='font-size:11.5px;color:var(--muted);margin-top:8px'>※ 당월 전체 기사 제목 기준 — 크기=언급량, 적색=부정 비중 22% 이상, 녹색=긍정 비중 55% 이상. 인물·정당명 및 일반 행정어 제외</p></div>
 <div class='outlook'><h2>다음 달 관전 포인트</h2><ul>{outlook}</ul></div>
 <footer>
 <b>작성 원칙</b> — 본 리포트는 bizpolicy 뉴스 아카이브(관측 개시 {OBS_START}, 지자체 {LOCAL_START_NOTE})의 수집 기사를 근거로 하며, 인용은 모두 기사·사설·칼럼의 <b>제목</b>에 한정함{desc_note}. 분야 구분(정치·경제·사회)은 제목 키워드 기반 자동 분류로 경계 사례에 오차가 있을 수 있음.<br>
 <b>논조 지표</b> — 순감성지수(NSI)=(긍정−부정)÷전체×100, 규칙 기반 자동 분류 결과이며 중앙·지자체 계열 간 수준 비교는 부적절함. 서술은 특정 정당·정파에 대한 평가가 아니라 보도 지형의 기록임.<br>
 <b>발행</b> — (주)서던포스트알앤씨 · 데이터 자동 산출 + 연구원 편집 원고 결합 생성
 </footer>
</div></body></html>"""
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f"월간_소상공인정책리포트_{ym}.html")
    open(path, "w", encoding="utf-8").write(html)
    print(f"생성: {path} ({os.path.getsize(path):,} bytes)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("month"); ap.add_argument("--db", default="news.db")
    ap.add_argument("--out", default="."); ap.add_argument("--font", default="chivonum.b64")
    a = ap.parse_args()
    assert re.fullmatch(r"\d{4}-\d{2}", a.month)
    fb = open(a.font).read().strip() if os.path.exists(a.font) else ""
    build(a.month, a.db, a.out, fb)
