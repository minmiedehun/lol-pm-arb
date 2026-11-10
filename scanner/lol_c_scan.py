#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lol_c_scan.py v2 · LoL 同平台组合套利扫描器（Polymarket，只读，不下单）

原理
  一场 BO3/BO5 的全部比分走势（BO5 共 20 条），加上“整场取消、全部 50-50”，构成结果空间。
  每个盘口的每个选项在每种结果下的结算值由规则确定（未打的局按 50-50）。对当前卖单解线性规划：
      最大化  t − Σ(价格 + 吃单费) × 数量
      约束    每种结果下组合回款 ≥ t；每档买入量 ≤ 该档挂单量
  最优值 > 0 就是“无论比赛怎么走都赚”的买入组合，最优值本身是当前深度下能锁定的总利润。

  “开赛后中途终止”另算（如一方中途弃权）：已完成的局照常结算，其余单局 50-50，让局与总局数 50-50，
  系列赛胜负判给获胜方或 50-50。默认只报告这种情形下的最差盈亏；加 --strict 则把它也作为约束。

子命令
  live        实时轮询盘口并扫描
  replay      回放 pm_recorder.py 的录制目录
  meta        把一场比赛的盘口清单存成 JSON，供离线回放或核对识别
  cs-inspect  查看 CryptoStruct 数据文件：头部、事件统计、断点、与盘口的对应关系
  cs-replay   回放 CryptoStruct 历史数据

示例
  python3 lol_c_scan.py live --event-slug lol-blg-gen-2026-11-14 --show-map --once
  python3 lol_c_scan.py meta --event-slug lol-blg-gen-2026-11-14 --out blg-gen.json
  python3 lol_c_scan.py cs-inspect lol-tl2-los-2026-10-30-game2.txt.zst
  python3 lol_c_scan.py cs-replay cs_数据目录/ --event-slug lol-ig1-gen-2026-11-07

依赖：python3 -m pip install scipy numpy zstandard
"""
from __future__ import annotations

import argparse
import csv
import gzip
import heapq
import io
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

try:
    import numpy as np
    from scipy.optimize import linprog
except ImportError:  # pragma: no cover
    sys.exit("缺少依赖：请先运行  python3 -m pip install scipy numpy")

VERSION = "2.0"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
UA = "Mozilla/5.0 (read-only research scanner)"
INT64_MAX = 9223372036854775807
OTHER = {"A": "B", "B": "A"}


# ============================================================ 结果空间

def series_paths(best_of: int) -> list[tuple[str, ...]]:
    """正常打完的全部比分走势。"""
    need = best_of // 2 + 1
    out: list[tuple[str, ...]] = []

    def rec(seq, a, b):
        if a == need or b == need:
            out.append(tuple(seq))
            return
        rec(seq + ["A"], a + 1, b)
        rec(seq + ["B"], a, b + 1)

    rec([], 0, 0)
    return out


def open_prefixes(best_of: int) -> list[tuple[str, ...]]:
    """尚未分出胜负的比分前缀，含一局都没打完的空前缀。"""
    need = best_of // 2 + 1
    out: list[tuple[str, ...]] = []

    def rec(seq, a, b):
        out.append(tuple(seq))
        for w in "AB":
            na, nb = a + (w == "A"), b + (w == "B")
            if na < need and nb < need:
                rec(seq + [w], na, nb)

    rec([], 0, 0)
    return out


@dataclass(frozen=True)
class Scenario:
    kind: str        # path：正常打完；void：整场取消；abandon：开赛后中途终止
    games: tuple     # 已完成各局的胜者（'A' / 'B'）
    ml: object       # 系列赛胜负怎么结算：'A' | 'B' | 0.5


def build_scenarios(best_of: int, void: bool = True, abandon: bool = False) -> list[Scenario]:
    need = best_of // 2 + 1
    out = [Scenario("path", p, "A" if p.count("A") == need else "B") for p in series_paths(best_of)]
    if void:
        out.append(Scenario("void", (), 0.5))
    if abandon:
        for pre in open_prefixes(best_of):
            for ml in ("A", "B", 0.5):
                if not pre and ml == 0.5 and void:
                    continue
                out.append(Scenario("abandon", pre, ml))
    return out


# ============================================================ 盘口

@dataclass
class Leg:
    """一个二元盘口。value(s) 是 token0 在情景 s 下的结算值，token1 = 1 − value。"""
    kind: str                 # ml | game | total | hcap
    question: str
    tokens: tuple
    labels: tuple
    param: float = 0.0        # game：第几局；total / hcap：盘口线
    t0_is: str = "A"          # ml/game：token0 是哪队（A/B）；total：O/U；hcap：F 让分方 / D 受让方
    fav: str = "A"            # hcap：让分方是 A 还是 B
    fee: bool = True
    condition_id: str = ""
    slug: str = ""
    via: str = "题目"

    def value(self, s: Scenario) -> float:
        if self.kind == "ml":
            return 0.5 if s.ml == 0.5 else (1.0 if s.ml == self.t0_is else 0.0)
        if self.kind == "game":
            k = int(self.param)
            if k > len(s.games):
                return 0.5                                   # 这一局没有打完：50-50
            return 1.0 if s.games[k - 1] == self.t0_is else 0.0
        if s.kind != "path":
            return 0.5                                       # 系列赛没有正常打完：让局、总局数 50-50
        n, a, b = len(s.games), s.games.count("A"), s.games.count("B")
        if self.kind == "total":
            over = 1.0 if n > self.param else 0.0
            return over if self.t0_is == "O" else 1.0 - over
        if self.kind == "hcap":
            margin = (a - b) if self.fav == "A" else (b - a)
            cover = 1.0 if margin > self.param else 0.0
            return cover if self.t0_is == "F" else 1.0 - cover
        raise ValueError(self.kind)


@dataclass
class Match:
    slug: str
    title: str
    team_a: str
    team_b: str
    best_of: int
    legs: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


# ============================================================ 盘口识别

_P = r"(?:LoL|League of Legends)\s*:\s*"
RE_ML = re.compile(r"^" + _P + r"(.+?)\s+vs\.?\s+(.+?)\s*\(\s*BO\s*(\d)\s*\)", re.I)
RE_PAIR = re.compile(r"^" + _P + r"(.+?)\s+vs\.?\s+(.+?)\s*-\s*Game\s*\d", re.I)
RE_GAME = re.compile(r"\bGame\s*(\d)\s*Winner\b", re.I)
RE_PROP = re.compile(r"\bGame\s*\d\s*:", re.I)
RE_TOTAL = re.compile(r"(?:Games?\s+Total|Total\s+Games?)\s*:?\s*O/U\s*(\d+(?:\.\d+)?)|\bO/U\s*(\d+(?:\.\d+)?)\s*Games?\b", re.I)
RE_HCAP = re.compile(r"^(?:Game|Map)\s+Handicap\s*:\s*(.+?)\s*\(\s*-\s*(\d+(?:\.\d+)?)\s*\)\s+vs\.?\s+(.+?)\s*\(\s*\+\s*(\d+(?:\.\d+)?)\s*\)", re.I)
RE_SL_GAME = re.compile(r"-game(\d)$")
RE_SL_TOTAL = re.compile(r"-total-games-(\d+)pt(\d+)$")
RE_SL_HCAP = re.compile(r"-game-handicap-(?:home|away)-(\d+)pt(\d+)$")
RE_LINE_SUFFIX = re.compile(r"\s*[+-]\s*\d+(?:\.\d+)?\s*$")


_FOLD = str.maketrans({"ø": "o", "æ": "ae", "œ": "oe", "ß": "ss", "đ": "d", "ł": "l", "þ": "th", "ı": "i"})


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower().translate(_FOLD))
    return re.sub(r"[^a-z0-9]", "", "".join(ch for ch in s if not unicodedata.combining(ch)))


def _subseq(short: str, long: str) -> bool:
    it = iter(long)
    return all(ch in it for ch in short)


def team_side(name: str, A: str, B: str) -> str | None:
    """把一个队名或简称对应到 A / B。依次试：完全相同、互相包含、简称按字母顺序出现（如 BLG→Bilibili Gaming）。
    只有恰好对上一队才返回，否则返回 None。"""
    n, na, nb = _norm(name), _norm(A), _norm(B)
    if not n or not na or not nb or na == nb:
        return None
    tests = (lambda x: n == x, lambda x: n in x or x in n, lambda x: len(n) <= 5 and _subseq(n, x))
    for test in tests:
        ta, tb = test(na), test(nb)
        if ta != tb:
            return "A" if ta else "B"
        if ta and tb:
            return None
    return None


def q_kind(q: str):
    q = (q or "").strip()
    if RE_ML.match(q):
        return ("ml", 0.0)
    m = RE_HCAP.match(q)
    if m:
        return ("hcap", float(m.group(2)))
    m = RE_GAME.search(q)
    if m and not RE_PROP.search(q):
        return ("game", float(m.group(1)))
    m = RE_TOTAL.search(q)
    if m:
        return ("total", float(m.group(1) or m.group(2)))
    return None


def slug_kind(slug: str):
    s = (slug or "").lower()
    m = RE_SL_GAME.search(s)
    if m:
        return ("game", float(m.group(1)))
    m = RE_SL_TOTAL.search(s)
    if m:
        return ("total", float(f"{m.group(1)}.{m.group(2)}"))
    m = RE_SL_HCAP.search(s)
    if m:
        return ("hcap", float(f"{m.group(1)}.{m.group(2)}"))
    return None


def _jl(v) -> list:
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            x = json.loads(v)
            return x if isinstance(x, list) else []
        except Exception:
            return []
    return []


def norm_market(m: dict) -> dict:
    """Gamma 盘口对象或 pm_recorder 的 meta 行 → 统一格式。"""
    return dict(
        question=m.get("question"), slug=m.get("slug"), conditionId=m.get("conditionId"),
        outcomes=[str(o) for o in _jl(m.get("outcomes"))],
        token_ids=[str(t) for t in _jl(m.get("clobTokenIds") if m.get("clobTokenIds") is not None else m.get("token_ids"))],
        closed=bool(m.get("closed", False)), feesEnabled=m.get("feesEnabled"),
        sportsMarketType=m.get("sportsMarketType"), groupItemTitle=m.get("groupItemTitle"),
        line=m.get("line"), gameStartTime=m.get("gameStartTime"),
    )


def build_match(slug: str, title: str, markets: list[dict], include_closed: bool = False) -> Match | None:
    markets = [norm_market(m) for m in markets]
    ml_m = next((m for m in markets if RE_ML.match((m.get("question") or "").strip())), None)
    if not ml_m:
        return None
    g = RE_ML.match(ml_m["question"].strip())
    A, B, bo = g.group(1).strip(), g.group(2).strip(), int(g.group(3))
    if bo not in (1, 3, 5):
        return None
    mt = Match(slug=slug, title=title or ml_m["question"], team_a=A, team_b=B, best_of=bo)
    seen: dict = {}

    for m in markets:
        q = (m.get("question") or "").strip()
        outs, toks, mslug = m["outcomes"], m["token_ids"], str(m.get("slug") or "")
        name = q or mslug
        qk, sk = q_kind(q), slug_kind(mslug)
        if qk is None and sk is None:
            mt.skipped.append(f"{name}（非赛果类盘口，不参与）")
            continue
        if len(outs) != 2 or len(toks) != 2:
            mt.skipped.append(f"{name}（不是二元盘口）")
            continue
        if m.get("closed") and not include_closed:
            mt.skipped.append(f"{name}（已关闭）")
            continue
        if qk and sk and (qk[0] != sk[0] or abs(qk[1] - sk[1]) > 1e-9):
            mt.skipped.append(f"{name}（题目识别为 {qk[0]} {qk[1]:g}，slug {mslug} 识别为 {sk[0]} {sk[1]:g}，两者不一致）")
            continue
        kind, param = qk or sk
        fee = m.get("feesEnabled")
        base = dict(question=name, tokens=(toks[0], toks[1]), labels=(outs[0], outs[1]),
                    fee=True if fee is None else bool(fee), condition_id=str(m.get("conditionId") or ""),
                    slug=mslug, via="题目" if qk else "slug")

        if kind in ("ml", "game"):
            if kind == "game":
                if int(param) > bo:
                    mt.skipped.append(f"{name}（第 {int(param)} 局超出 BO{bo}）")
                    continue
                pair = RE_PAIR.match(q)
                if pair and {team_side(pair.group(1), A, B), team_side(pair.group(2), A, B)} != {"A", "B"}:
                    mt.skipped.append(f"{name}（题目里的队名与系列赛 {A} / {B} 对不上）")
                    continue
            s0, s1 = team_side(outs[0], A, B), team_side(outs[1], A, B)
            if s0 and s1 and s0 == s1:
                mt.skipped.append(f"{name}（两个选项 {outs} 都对应到同一队）")
                continue
            t0 = s0 or (OTHER[s1] if s1 else None)
            if t0 is None:
                mt.skipped.append(f"{name}（选项 {outs} 对不上队名 {A} / {B}）")
                continue
            leg = Leg(kind=kind, param=param, t0_is=t0, **base)

        elif kind == "total":
            o0 = outs[0].strip().lower()
            if not (o0.startswith("over") or o0.startswith("under")):
                mt.skipped.append(f"{name}（选项 {outs} 不是 Over/Under）")
                continue
            if not (0 < param < bo) or abs((param % 1) - 0.5) > 1e-9:
                mt.skipped.append(f"{name}（盘口线 {param:g} 不是 BO{bo} 内的半局线）")
                continue
            leg = Leg(kind="total", param=param, t0_is="O" if o0.startswith("over") else "U", **base)

        else:  # hcap
            gh = RE_HCAP.match(q)
            if not gh:
                mt.skipped.append(f"{name}（让局题目无法解析，slug 不足以判断谁让分）")
                continue
            fav_txt, l1, dog_txt, l2 = gh.group(1), float(gh.group(2)), gh.group(3), float(gh.group(4))
            if abs(l1 - l2) > 1e-9:
                mt.skipped.append(f"{name}（两边让分线不相等）")
                continue
            fs, ds = team_side(fav_txt, A, B), team_side(dog_txt, A, B)
            if fs and ds and fs == ds:
                mt.skipped.append(f"{name}（让分方和受让方都对应到同一队）")
                continue
            fav = OTHER[ds] if ds else fs
            if fav is None:
                mt.skipped.append(f"{name}（{fav_txt} / {dog_txt} 对不上队名 {A} / {B}）")
                continue
            o = [team_side(RE_LINE_SUFFIX.sub("", x), A, B) for x in outs]
            if o[0] and o[1] and o[0] == o[1]:
                mt.skipped.append(f"{name}（两个选项 {outs} 都对应到同一队）")
                continue
            if o[0]:
                t0 = "F" if o[0] == fav else "D"
            elif o[1]:
                t0 = "D" if o[1] == fav else "F"
            else:
                mt.skipped.append(f"{name}（选项 {outs} 对不上队名，分不清哪个是让分方）")
                continue
            if not (0 < l1 < bo // 2 + 1) or abs((l1 % 1) - 0.5) > 1e-9:
                mt.skipped.append(f"{name}（让分线 {l1:g} 超出 BO{bo} 的范围）")
                continue
            leg = Leg(kind="hcap", param=l1, fav=fav, t0_is=t0, **base)

        key = (leg.kind, leg.param, leg.fav if leg.kind == "hcap" else "")
        if key in seen:
            mt.warnings.append(f"重复盘口：「{name}」与「{seen[key]}」结算相同，两者都参与计算")
        seen[key] = name
        mt.legs.append(leg)

    need = bo // 2 + 1
    have = {(l.kind, l.param) for l in mt.legs}
    missing = [] if ("ml", 0.0) in have else ["系列赛胜负"]
    missing += [f"第 {k} 局胜负" for k in range(1, bo + 1) if ("game", float(k)) not in have]
    missing += [f"总局数 {x + 0.5:g}" for x in range(need, bo) if ("total", x + 0.5) not in have]
    missing += [f"让局 {x + 0.5:g}" for x in range(1, need) if ("hcap", x + 0.5) not in have]
    if missing:
        mt.warnings.append("缺少：" + "、".join(missing) + "（可能尚未上架，或题目格式没认出来）")
    return mt if mt.legs else None


def describe(mt: Match) -> str:
    name = {"ml": "系列赛胜负", "game": "单局胜负", "total": "总局数", "hcap": "让局"}
    team = {"A": mt.team_a, "B": mt.team_b}
    lines = [f"{mt.title}\n  A = {mt.team_a}，B = {mt.team_b}，BO{mt.best_of}，纳入 {len(mt.legs)} 个盘口"]
    order = {"ml": 0, "game": 1, "total": 2, "hcap": 3}
    for l in sorted(mt.legs, key=lambda z: (order[z.kind], z.param)):
        if l.kind in ("ml", "game"):
            extra = f"第 {int(l.param)} 局，" if l.kind == "game" else ""
            det = f"{extra}token0「{l.labels[0]}」= {team[l.t0_is]} 胜"
        elif l.kind == "total":
            det = f"线 {l.param:g}，token0「{l.labels[0]}」= {'大' if l.t0_is == 'O' else '小'}"
        else:
            det = f"{team[l.fav]} 让 {l.param:g}，token0「{l.labels[0]}」= {'让分方' if l.t0_is == 'F' else '受让方'}"
        flags = ("" if l.fee else "，免手续费") + ("，仅凭 slug 识别" if l.via == "slug" else "")
        lines.append(f"  [{name[l.kind]}] {l.question}\n      → {det}{flags}")
    for w in mt.warnings:
        lines.append(f"  [注意] {w}")
    for s in mt.skipped:
        lines.append(f"  [跳过] {s}")
    return "\n".join(lines)


def scenario_label(s: Scenario, mt: Match) -> str:
    A, B = mt.team_a, mt.team_b
    if s.kind == "path":
        seq = "-".join(A if g == "A" else B for g in s.games)
        return f"{A} {s.games.count('A')}:{s.games.count('B')} {B}（{seq}）"
    if s.kind == "void":
        return "整场取消，全部 50-50"
    when = f"{s.games.count('A')}:{s.games.count('B')} 时中止" if s.games else "第 1 局打完前中止"
    who = {"A": f"胜负判给 {A}", "B": f"胜负判给 {B}", 0.5: "胜负 50-50"}[s.ml]
    return f"{when}，{who}"


# ============================================================ 线性规划

def consistent(s: Scenario, known: dict) -> bool:
    """known = {局号: 'A'/'B'}：已经打完并正式结算的单局。打完了第 k 局，情景里就必须至少有 k 局且第 k 局胜者相同；
    因此“整场取消”和比第 k 局更早中止的情景都被排除。"""
    return all(len(s.games) >= k and s.games[k - 1] == w for k, w in known.items())


class Model:
    """一场比赛的结算矩阵：每个 token 在每个情景下的回款。
    known 给出已正式结算的单局结果时，只保留与之相符的情景（赛中用；排除不可能的情景不会产生假机会）。"""

    def __init__(self, mt: Match, void: bool = True, strict: bool = False, known: dict | None = None):
        bo = mt.best_of
        self.mt = mt
        self.known = dict(known or {})
        self.main = build_scenarios(bo, void=void, abandon=strict)
        self.tail = [] if strict else [s for s in build_scenarios(bo, void=False, abandon=True) if s.kind == "abandon"]
        if self.known:
            main = [s for s in self.main if consistent(s, self.known)]
            if main:                       # 已知结果自相矛盾（不应发生）时不做条件化
                self.main = main
                self.tail = [s for s in self.tail if consistent(s, self.known)]
            else:
                self.known = {}
        self.tail_labels = [scenario_label(s, mt) for s in self.tail]
        self.tok: dict = {}
        for leg in mt.legs:
            vm = np.array([leg.value(s) for s in self.main])
            vt = np.array([leg.value(s) for s in self.tail]) if self.tail else None
            self.tok[leg.tokens[0]] = (leg, 0, vm, vt)
            self.tok[leg.tokens[1]] = (leg, 1, 1.0 - vm, None if vt is None else 1.0 - vt)

    def tokens(self) -> list[str]:
        return list(self.tok)


@dataclass
class Result:
    profit: float              # 当前深度下可锁定的总利润（美元）
    cost: float                # 投入（含手续费）
    floor: float               # 主情景中最差的回款
    unit_cost: float           # 只用各选项最优一档、锁定 $1 回款的最低成本；< 1 才有套利
    orders: list               # [{question, label, token, price, shares, fee}]
    small_legs: int            # 买入量低于最小下单量的选项数
    tail_pnl: float | None = None   # 中途终止情形下的最差盈亏（未开 --strict 时）
    tail_label: str = ""


def fee_per_share(p: float, rate: float) -> float:
    return rate * p * (1.0 - p)


def solve(model: Model, books: dict, fee_rate: float, min_shares: float = 5.0,
          max_levels: int = 8, exclude=(), max_cost: float | None = None) -> Result | None:
    """books: token → 卖单 [(价格, 数量)]，按价格从低到高。exclude: 不可信（如数据断档）的 token。
    max_cost: 投入上限（美元，含手续费）；给定时求“这笔资金内能锁定的最大利润”，不给则吃满深度。"""
    cols = []   # (token, leg, ti, price, size, unit_cost_with_fee, is_best)
    for tok, (leg, ti, _, _) in model.tok.items():
        if tok in exclude:
            continue
        k = 0
        for price, size in books.get(tok) or []:
            if not (0.0 < price < 1.0) or size <= 0:
                continue
            c = price + (fee_per_share(price, fee_rate) if leg.fee else 0.0)
            cols.append((tok, leg, ti, price, size, c, k == 0))
            k += 1
            if k >= max_levels:
                break
    if not cols:
        return None
    P = np.column_stack([model.tok[c[0]][2] for c in cols])
    m, n = P.shape
    cost = np.array([c[5] for c in cols])
    size = np.array([c[4] for c in cols])

    # 先用各选项最优一档、不限数量判断是否存在套利；不存在就不必解完整问题（更深的档只会更贵）
    best = [j for j, c in enumerate(cols) if c[6]]
    r1 = linprog(cost[best], A_ub=-P[:, best], b_ub=-np.ones(m), bounds=[(0, None)] * len(best), method="highs")
    unit = float(r1.fun) if r1.status == 0 else float("inf")
    if unit >= 1.0 - 1e-9:
        return Result(0.0, 0.0, 0.0, unit, [], 0)

    A_ub, b_ub = np.hstack([-P, np.ones((m, 1))]), np.zeros(m)
    if max_cost is not None and max_cost > 0:
        A_ub = np.vstack([A_ub, np.concatenate([cost, [0.0]])])
        b_ub = np.concatenate([b_ub, [max_cost]])
    res = linprog(np.concatenate([cost, [-1.0]]), A_ub=A_ub, b_ub=b_ub,
                  bounds=[(0, float(s)) for s in size] + [(0, None)], method="highs")
    if res.status != 0:
        return Result(0.0, 0.0, 0.0, unit, [], 0)
    x = np.where(res.x[:n] > 1e-7, res.x[:n], 0.0)
    if not x.any():
        return Result(0.0, 0.0, 0.0, unit, [], 0)
    floor = float((P @ x).min())
    spent = float(cost @ x)
    agg: dict = {}
    for j in np.nonzero(x)[0]:
        tok, leg, ti, price, _, c, _ = cols[j]
        o = agg.setdefault((tok, price), dict(question=leg.question, label=leg.labels[ti], token=tok,
                                              price=price, shares=0.0, fee=0.0))
        o["shares"] += float(x[j])
        o["fee"] += (c - price) * float(x[j])
    orders = [dict(o, shares=round(o["shares"], 2), fee=round(o["fee"], 4)) for o in agg.values()]
    per_token: dict = {}
    for o in orders:
        per_token[o["token"]] = per_token.get(o["token"], 0.0) + o["shares"]
    tail_pnl, tail_label = None, ""
    if model.tail:
        T = np.column_stack([model.tok[c[0]][3] for c in cols])
        v = T @ x
        i = int(np.argmin(v))
        tail_pnl, tail_label = float(v[i]) - spent, model.tail_labels[i]
    return Result(floor - spent, spent, floor, unit, orders,
                  sum(1 for v in per_token.values() if v < min_shares), tail_pnl, tail_label)


def fmt_result(mt: Match, r: Result, min_shares: float) -> str:
    roi = r.profit / r.cost * 100 if r.cost else 0.0
    lines = [f"{mt.title}：可锁定利润 ${r.profit:.2f}，投入 ${r.cost:.2f}，最差回款 ${r.floor:.2f}，收益率 {roi:.2f}%"]
    for o in sorted(r.orders, key=lambda z: (z["question"], z["price"])):
        lines.append(f"    买 {o['shares']:>9.2f} 股 @ {o['price']:.3f}  「{o['label']}」 {o['question']}")
    if r.tail_pnl is not None:
        lines.append(f"    若开赛后中途终止：最差情形「{r.tail_label}」盈亏 ${r.tail_pnl:+.2f}")
    if r.small_legs:
        lines.append(f"    注意：{r.small_legs} 个选项的买入量不足最小下单量 {min_shares:g} 股，实际未必能成交")
    return "\n".join(lines)


# ============================================================ 机会段统计

class Episodes:
    def __init__(self, min_profit: float):
        self.min_profit = min_profit
        self.items: list = []
        self.cur: dict | None = None
        self.n_eval = 0
        self.min_unit = float("inf")
        self.last_unit = float("inf")

    def update(self, ts_ms: int, r: Result | None) -> None:
        self.n_eval += 1
        if r is None:
            self.last_unit = float("inf")
            self.close(ts_ms)
            return
        self.last_unit = r.unit_cost
        self.min_unit = min(self.min_unit, r.unit_cost)
        if r.profit >= self.min_profit:
            if self.cur is None:
                self.cur = dict(start_ms=ts_ms, n=0, unit_min=r.unit_cost)
            c = self.cur
            c["n"] += 1
            c["unit_min"] = min(c["unit_min"], r.unit_cost)
            if r.profit > c.get("max_profit", -1):
                c.update(max_profit=r.profit, cost=r.cost, orders=r.orders, small=r.small_legs,
                         tail=r.tail_pnl, tail_label=r.tail_label)
        else:
            self.close(ts_ms)

    def close(self, ts_ms: int) -> None:
        if self.cur:
            self.cur["end_ms"] = ts_ms
            self.cur["duration_s"] = round((ts_ms - self.cur["start_ms"]) / 1000, 3)
            self.items.append(self.cur)
            self.cur = None

    def write_csv(self, path: str) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["start_utc", "start_ms", "end_ms", "duration_s", "max_profit_usd", "cost_usd", "roi_pct",
                        "orders_n", "small_legs", "unit_cost_min", "abandon_worst_pnl_usd", "abandon_worst_case", "orders"])
            for e in self.items:
                w.writerow([utc(e["start_ms"]), e["start_ms"], e["end_ms"], e["duration_s"], round(e["max_profit"], 4),
                            round(e["cost"], 2), round(e["max_profit"] / e["cost"] * 100, 3) if e["cost"] else 0,
                            len(e["orders"]), e["small"], round(e["unit_min"], 5),
                            "" if e["tail"] is None else round(e["tail"], 4), e["tail_label"],
                            " | ".join(f"{o['shares']}@{o['price']} {o['label']} / {o['question']}" for o in e["orders"])])

    def summary(self) -> str:
        if not self.items:
            return f"没有达到 ${self.min_profit:g} 门槛的机会。"
        d = sorted(e["duration_s"] for e in self.items)
        tails = [e["tail"] for e in self.items if e["tail"] is not None]
        s = (f"机会 {len(self.items)} 段 · 持续时间中位数 {d[len(d) // 2]:.2f}s、最长 {d[-1]:.2f}s · "
             f"各段最大利润合计 ${sum(e['max_profit'] for e in self.items):.2f}、单段最大 ${max(e['max_profit'] for e in self.items):.2f}")
        if tails:
            s += f" · 其中 {sum(1 for t in tails if t < 0)} 段在中途终止情形下会亏"
        return s


def utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


# ============================================================ 取数（Gamma / CLOB）

def http_json(url: str, timeout: float = 10.0):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _as_list(data) -> list:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [x for x in (data.get("data") or data.get("events") or data.get("markets") or []) if isinstance(x, dict)]
    return []


def gamma_event(gamma: str, slug: str) -> tuple[dict, list[dict]]:
    """赛事 slug（也接受单个盘口 slug）→ (赛事信息, 盘口列表)。已结束的赛事也能取。"""
    q = urllib.parse.quote(slug)
    for url in (f"{gamma}/events?slug={q}", f"{gamma}/events?slug={q}&closed=true"):
        evs = _as_list(http_json(url))
        if evs and evs[0].get("markets"):
            ev = evs[0]
            info = {k: ev.get(k) for k in ("id", "slug", "title", "startDate", "endDate", "closed") if k in ev}
            return info, [norm_market(m) for m in ev["markets"]]
    for url in (f"{gamma}/markets?slug={q}", f"{gamma}/markets?slug={q}&closed=true"):
        ms = _as_list(http_json(url))
        if ms:
            return {"slug": slug, "note": "按盘口 slug 取得"}, [norm_market(m) for m in ms]
    raise SystemExit(f"Gamma 没找到 {slug!r}。请从 Polymarket 赛事页网址复制 /event/ 后面那一段。")


def load_match(args, include_closed: bool) -> Match | None:
    if getattr(args, "meta", None):
        meta = json.load(open(args.meta, encoding="utf-8"))
        ev = meta.get("event") or {}
        return build_match(ev.get("slug") or "", ev.get("title") or "", meta.get("markets") or [], include_closed)
    if getattr(args, "event_slug", None):
        info, markets = gamma_event(args.gamma, args.event_slug[0] if isinstance(args.event_slug, list) else args.event_slug)
        return build_match(info.get("slug") or "", info.get("title") or "", markets, include_closed)
    return None


def discover(gamma: str, tag: str, pages: int = 5) -> list[Match]:
    out = []
    for i in range(pages):
        evs = _as_list(http_json(f"{gamma}/events?closed=false&active=true&tag_slug={urllib.parse.quote(tag)}"
                                 f"&limit=100&offset={i * 100}"))
        if not evs:
            break
        for e in evs:
            if str(e.get("title") or "").lower().startswith("lol:"):
                mt = build_match(e.get("slug") or "", e.get("title") or "", e.get("markets") or [])
                if mt:
                    out.append(mt)
        if len(evs) < 100:
            break
    return out


def fetch_asks(clob: str, token: str) -> tuple[str, list[tuple[float, float]]]:
    try:
        d = http_json(f"{clob}/book?token_id={token}", timeout=6.0)
        return token, sorted(((float(a["price"]), float(a["size"])) for a in d.get("asks") or []), key=lambda z: z[0])
    except Exception:
        return token, []


# ============================================================ 子命令：live / meta

def cmd_live(args) -> int:
    matches: list[Match] = []
    for s in args.event_slug or []:
        info, markets = gamma_event(args.gamma, s)
        mt = build_match(info.get("slug") or s, info.get("title") or "", markets)
        if mt:
            matches.append(mt)
        else:
            print(f"[{s}] 没识别出 LoL 系列赛盘口", file=sys.stderr)
    if args.discover:
        try:
            matches += discover(args.gamma, args.tag)
        except Exception as e:
            print(f"自动发现失败：{e!r}；请改用 --event-slug", file=sys.stderr)
    if not matches:
        print("没有可扫描的比赛。", file=sys.stderr)
        return 2
    models = [Model(mt, void=not args.no_void, strict=args.strict) for mt in matches]
    if args.show_map:
        for mt in matches:
            print(describe(mt), "\n")
    out = open(args.out, "a", encoding="utf-8") if args.out else None
    print(f"扫描 {len(matches)} 场，吃单费率 {args.fee_rate}，利润门槛 ${args.min_profit:g}，"
          f"{'严格模式（中途终止也不亏）' if args.strict else '中途终止情形单独报告'}；Ctrl+C 停止")
    pool = ThreadPoolExecutor(max_workers=16)
    try:
        while True:
            t0 = time.time()
            for mt, model in zip(matches, models):
                books = dict(pool.map(lambda tk: fetch_asks(args.clob, tk), model.tokens()))
                r = solve(model, books, args.fee_rate, args.min_shares, max_cost=args.max_cost)
                ts = datetime.now().strftime("%H:%M:%S")
                if r is None:
                    print(f"[{ts}] {mt.title}：没有卖单")
                elif r.profit >= args.min_profit:
                    print(f"[{ts}] 发现组合机会 · " + fmt_result(mt, r, args.min_shares))
                    if out:
                        out.write(json.dumps(dict(ts_ms=int(time.time() * 1000), slug=mt.slug, profit=r.profit, cost=r.cost,
                                                  floor=r.floor, unit_cost=r.unit_cost, tail_pnl=r.tail_pnl,
                                                  tail_label=r.tail_label, orders=r.orders), ensure_ascii=False) + "\n")
                        out.flush()
                else:
                    print(f"[{ts}] {mt.title}：无机会 · 锁定 $1 的最低成本 {r.unit_cost:.4f}（低于 1 才有套利）")
            if args.once:
                break
            time.sleep(max(0.2, args.interval - (time.time() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        pool.shutdown(wait=False)
        if out:
            out.close()
    return 0


def cmd_meta(args) -> int:
    info, markets = gamma_event(args.gamma, args.event_slug)
    out = args.out or f"meta_{info.get('slug') or args.event_slug}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"event": info, "markets": markets, "saved_utc": utc(int(time.time() * 1000)), "scanner": VERSION},
                  f, ensure_ascii=False, indent=2)
    mt = build_match(info.get("slug") or "", info.get("title") or "", markets, include_closed=True)
    print(describe(mt) if mt else "没识别出 LoL 系列赛盘口。")
    print(f"\n已保存：{os.path.abspath(out)}（{len(markets)} 个盘口）")
    return 0


# ============================================================ 盘口状态（两种回放共用）

class Books:
    """每个 token 的买卖盘。某个 token 没有自己的盘口数据时，用另一个选项的买单换算：
    买 token1 @ q 等价于与 token0 的买单 @ 1−q 撮合（Polymarket 两个选项共用一个订单簿）。"""

    def __init__(self):
        self.bids: dict = {}
        self.asks: dict = {}
        self.suspect: set = set()

    def lp_books(self, model: Model) -> dict:
        out = {}
        for leg in model.mt.legs:
            for i, tok in enumerate(leg.tokens):
                comp = leg.tokens[1 - i]
                if tok in self.asks and tok not in self.suspect:
                    out[tok] = sorted(self.asks[tok].items())
                elif comp in self.bids and comp not in self.suspect:
                    out[tok] = sorted((round(1.0 - p, 6), s) for p, s in self.bids[comp].items())
        return out


def _same_levels(a: dict, b: dict) -> bool:
    ka = {round(p, 6): s for p, s in a.items() if s > 0}
    kb = {round(p, 6): s for p, s in b.items() if s > 0}
    return ka.keys() == kb.keys() and all(abs(ka[p] - kb[p]) <= 1e-6 * max(1.0, abs(kb[p])) for p in ka)


class PmBooks(Books):
    """pm_recorder 录下的 Polymarket WebSocket 消息 → 盘口。顺带检验“增量重建”是否与下一份完整快照一致。"""

    def __init__(self):
        super().__init__()
        self.snap_ok = 0
        self.snap_bad = 0

    def apply(self, msg) -> bool:
        changed = False
        for m in (msg if isinstance(msg, list) else [msg]):
            if not isinstance(m, dict):
                continue
            et = m.get("event_type")
            if et == "book":
                a = str(m.get("asset_id"))
                asks = {float(x["price"]): float(x["size"]) for x in m.get("asks") or [] if float(x["size"]) > 0}
                bids = {float(x["price"]): float(x["size"]) for x in m.get("bids") or [] if float(x["size"]) > 0}
                if a in self.asks or a in self.bids:
                    if _same_levels(self.asks.get(a, {}), asks) and _same_levels(self.bids.get(a, {}), bids):
                        self.snap_ok += 1
                    else:
                        self.snap_bad += 1
                self.asks[a], self.bids[a] = asks, bids
                changed = True
            elif et == "price_change":
                for c in m.get("price_changes") or m.get("changes") or []:
                    a = str(c.get("asset_id") or m.get("asset_id"))
                    side = str(c.get("side", "")).upper()
                    book = self.asks if side == "SELL" else self.bids if side == "BUY" else None
                    if book is None:
                        continue
                    lv = book.setdefault(a, {})
                    p, s = float(c["price"]), float(c["size"])
                    if s <= 0:
                        lv.pop(p, None)
                    else:
                        lv[p] = s
                    changed = True
        return changed


def scan_stream(model: Model, books: Books, events, args, label: str) -> Episodes:
    """events: 依时间顺序产出 (ts_ms, changed: bool)。只在卖一价格变化、或上一次仍有套利时重算。"""
    ep = Episodes(args.min_profit)
    last_sig, last_ts = None, None
    toks = model.tokens()
    for ts_ms, changed in events:
        if not changed:
            continue
        if args.step_ms and last_ts is not None and ts_ms - last_ts < args.step_ms and ep.cur is None:
            continue
        lb = books.lp_books(model)
        sig = tuple((lb[t][0][0] if lb.get(t) else None) for t in toks) + tuple(sorted(books.suspect))
        if sig == last_sig and ep.last_unit >= 1.0 - 1e-9 and ep.cur is None:
            continue
        last_sig, last_ts = sig, ts_ms
        ep.update(ts_ms, solve(model, lb, args.fee_rate, args.min_shares, exclude=books.suspect, max_cost=args.max_cost))
    if last_ts is not None:
        ep.close(last_ts)
    return ep


def cmd_replay(args) -> int:
    meta = json.load(open(os.path.join(args.dir, "meta_start.json"), encoding="utf-8"))
    ev = meta.get("event") or {}
    mt = build_match(ev.get("slug") or "", ev.get("title") or "", meta.get("markets") or [], include_closed=True)
    if not mt:
        print("这个录制目录里没识别出 LoL 系列赛盘口。", file=sys.stderr)
        return 2
    print(describe(mt), "\n")
    model = Model(mt, void=not args.no_void, strict=args.strict)
    books = PmBooks()

    def events():
        with open(os.path.join(args.dir, "pm_market.jsonl"), encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    msg = json.loads(rec["raw"])
                except Exception:
                    continue
                yield int(rec["recv_ms"]), books.apply(msg)

    ep = scan_stream(model, books, events(), args, mt.title)
    path = os.path.join(args.dir, "c_scan_episodes.csv")
    ep.write_csv(path)
    print(f"评估 {ep.n_eval} 次盘口状态；全程锁定 $1 的最低成本最小值 {ep.min_unit:.4f}")
    if books.snap_ok + books.snap_bad:
        tot = books.snap_ok + books.snap_bad
        print(f"增量重建与随后完整快照一致：{books.snap_ok}/{tot}" +
              ("（一致率偏低：price_change 的含义可能与假设不符，回放结果先别用）" if books.snap_bad > 0.05 * tot else ""))
    print(ep.summary())
    print(f"明细：{path}")
    return 0


# ============================================================ CryptoStruct

def open_text(path: str):
    low = path.lower()
    if low.endswith(".zst") or low.endswith(".zstd"):
        try:
            import zstandard
            fh = open(path, "rb")
            try:
                reader = zstandard.ZstdDecompressor().stream_reader(fh, read_across_frames=True)
            except TypeError:
                reader = zstandard.ZstdDecompressor().stream_reader(fh)
            return io.TextIOWrapper(reader, encoding="utf-8")
        except ImportError:
            pass
        try:
            from compression import zstd as _zstd  # Python 3.14+
            return _zstd.open(path, "rt", encoding="utf-8")
        except ImportError:
            pass
        try:
            p = subprocess.Popen(["zstd", "-dc", path], stdout=subprocess.PIPE)
            return io.TextIOWrapper(p.stdout, encoding="utf-8")
        except FileNotFoundError:
            raise SystemExit("读取 .zst 需要解压支持：python3 -m pip install zstandard")
    if low.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, encoding="utf-8")


def _eid(v):
    if v is None:
        return None
    s = str(v)
    return None if s in ("", "0", str(INT64_MAX)) else s


class CsFile:
    """一个 CryptoStruct 日文件：第 1 行是 JSON 头部，之后每行一个事件数组
    [类型, 品种ID, 上一事件ID, 事件ID, 接收时间ns, 交易所时间ns, 数据, ...]。"""

    def __init__(self, path: str):
        self.path = path
        f = open_text(path)
        try:
            first = f.readline()
        finally:
            f.close()
        self.header = json.loads(first)
        inst = self.header.get("instrument", self.header)
        self.inst = inst if isinstance(inst, dict) else {}
        self.bad_lines = 0

    def candidates(self) -> list[str]:
        vals = [str(v) for v in self.inst.values() if isinstance(v, (str, int)) and not isinstance(v, bool)]
        return vals + [os.path.basename(self.path)]

    def raw_lines(self, n: int) -> list[str]:
        out = []
        f = open_text(self.path)
        try:
            f.readline()
            for line in f:
                out.append(line.rstrip("\n"))
                if len(out) >= n:
                    break
        finally:
            f.close()
        return out

    def events(self):
        """产出 (接收时间ns, 类型, 上一事件ID, 事件ID, 数据)。类型 5（状态）的数据是 (state, message)。"""
        f = open_text(self.path)
        try:
            f.readline()
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    m = json.loads(line)
                except Exception:
                    self.bad_lines += 1
                    continue
                if not isinstance(m, list) or len(m) < 3:
                    self.bad_lines += 1
                    continue
                t = m[0]
                if t == 5:
                    yield int(m[2]), 5, None, None, (m[3] if len(m) > 3 else None, m[4] if len(m) > 4 else None)
                elif len(m) >= 7:
                    yield int(m[4]), t, _eid(m[2]), _eid(m[3]), m[6]
                else:
                    self.bad_lines += 1
        finally:
            f.close()


def expand_paths(paths: list[str]) -> list[str]:
    exts = (".zst", ".zstd", ".jsonl", ".txt", ".gz")
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                # 跳过 CryptoStruct 区间下载自带的清单（MANIFEST.txt、RANGE_MANIFEST.txt），它们不是数据文件
                out += [os.path.join(root, x) for x in files
                        if x.lower().endswith(exts) and "manifest" not in x.lower()]
        elif os.path.exists(p):
            out.append(p)
        else:
            print(f"找不到：{p}", file=sys.stderr)
    return sorted(set(out))


def load_cs_files(paths: list[str]) -> list[CsFile]:
    """读取文件头；读不了的（不是 CryptoStruct 文件、损坏）跳过并提示，不中断整次回放。"""
    out = []
    for p in expand_paths(paths):
        try:
            out.append(CsFile(p))
        except Exception as e:  # noqa: BLE001
            print(f"  跳过无法读取的文件：{p}（{type(e).__name__}: {str(e)[:80]}）", file=sys.stderr)
    return out


def map_cs_files(files: list[CsFile], mt: Match, side_mode: str):
    """CryptoStruct 文件 → (盘口, token 序号, 依据)。依据顺序：token id > condition id > 盘口 slug。"""
    tok = {t: (leg, i) for leg in mt.legs for i, t in enumerate(leg.tokens)}
    by_cond = {leg.condition_id: leg for leg in mt.legs if leg.condition_id}
    by_slug = {leg.slug: leg for leg in mt.legs if leg.slug}
    mapped, unmapped = [], []
    for f in files:
        cands = f.candidates()
        hit = None
        # native_code 为 {"referenceOutcome": 选项名, 选项名: token id, ...}（11/10 用免费样本核实：
        # lol-tl2-los-2026-10-30-game2 的价格对应 referenceOutcome「team liquid」，与 CLOB prices-history 一致）
        nc = f.inst.get("native_code")
        if isinstance(nc, str) and nc.startswith("{"):
            try:
                nc = json.loads(nc)
            except ValueError:
                nc = None
        if isinstance(nc, dict) and nc.get("referenceOutcome") is not None:
            rt = nc.get(nc["referenceOutcome"])
            if rt is not None and str(rt) in tok:
                hit = (tok[str(rt)][0], tok[str(rt)][1], f"native_code.referenceOutcome「{nc['referenceOutcome']}」的 token id 精确匹配")
        if hit is None:
            hit = next(((tok[c][0], tok[c][1], "token id 精确匹配") for c in cands if c in tok), None)
        if hit is None:
            hit = next(((by_cond[c], None, "condition id 匹配") for c in cands if c in by_cond), None)
        if hit is None:
            best = None
            for s, leg in by_slug.items():
                pat = re.compile(re.escape(s) + r"(?![A-Za-z0-9]|-[A-Za-z])")
                suf = re.compile(re.escape(s) + r"-([A-Za-z0-9-]+?)(?=$|[._ ])")
                found = None
                for c in cands:
                    if c == s or pat.search(c):
                        found = (leg, None, "slug 匹配")
                        break
                    m = suf.search(c)
                    if m:
                        w = _norm(m.group(1))
                        side = {_norm(leg.labels[0]): 0, _norm(leg.labels[1]): 1}.get(w)
                        if side is None and w in ("yes", "no"):
                            side = 0 if w == "yes" else 1
                        if side is not None:
                            found = (leg, side, f"slug 加选项后缀「{m.group(1)}」匹配")
                            break
                if found and (best is None or len(s) > len(best[0].slug)):
                    best = found
            hit = best
        if hit is None:
            unmapped.append(f)
            continue
        leg, ti, how = hit
        if ti is None:
            ti = 1 if side_mode == "second" else 0
            how += "；价格按" + ("第二个选项" if ti else "第一个选项") + ("理解（--cs-side 指定）" if side_mode != "auto" else "理解（假设，待用样本核实）")
        mapped.append((f, leg, ti, how))
    return mapped, unmapped


def _print_unmapped(unmapped: list) -> None:
    if unmapped:
        eg = "、".join(os.path.basename(f.path) for f in unmapped[:5])
        print(f"  另有 {len(unmapped)} 个文件没对应到这场的赛果盘口（道具盘或其他比赛），已忽略，例如：{eg}")


def cs_book_stats(f: CsFile, max_events: int = 0) -> dict:
    st = dict(n=0, types={}, first=None, last=None, gaps=0, dups=0, crossed=0, checks=0, snapshots=0, errors=0)
    bids, asks, last, seen = {}, {}, None, set()
    for ats, t, prev, eid, data in f.events():
        st["n"] += 1
        st["types"][t] = st["types"].get(t, 0) + 1
        st["first"] = ats if st["first"] is None else min(st["first"], ats)
        st["last"] = ats if st["last"] is None else max(st["last"], ats)
        if t == 5:
            if str((data or (None,))[0]).upper() == "ERROR":
                st["errors"] += 1
            continue
        if t not in (0, 1):
            continue
        if eid is not None:
            if eid in seen:
                st["dups"] += 1
                continue
            seen.add(eid)
        if t == 0:
            st["snapshots"] += 1
            bids, asks = {}, {}
        elif prev is not None and last is not None and prev != last:
            st["gaps"] += 1
        for lv in data or []:
            side, p, q = lv[0], float(lv[1]), float(lv[2])
            book = bids if side == 0 else asks
            if q == 0.0:
                book.pop(p, None)
            else:
                book[p] = q
        last = eid if eid is not None else last
        if bids and asks:
            st["checks"] += 1
            if max(bids) >= min(asks):
                st["crossed"] += 1
        if max_events and st["n"] >= max_events:
            break
    st["bid"] = max(bids.items()) if bids else None
    st["ask"] = min(asks.items()) if asks else None
    st["levels"] = (len(bids), len(asks))
    return st


def ns_utc(ns) -> str:
    return "-" if ns is None else utc(int(ns) // 1_000_000)


def cmd_cs_inspect(args) -> int:
    paths = expand_paths(args.files)
    if not paths:
        print("没有可读的文件。", file=sys.stderr)
        return 2
    files = [CsFile(p) for p in paths]
    tname = {0: "快照", 1: "增量", 2: "成交", 5: "状态", 6: "最优价", 7: "标记价", 8: "指数价", 9: "资金费", 17: "强平", 18: "持仓量"}
    for f in files:
        i = f.inst
        print(f"== {f.path}")
        print("  头部 instrument：" + "，".join(f"{k}={i.get(k)!r}" for k in
              ("id", "code", "native_code", "exchange_code", "type", "ticksize", "lot_size") if k in i))
        extra = [k for k in i if k not in ("id", "code", "native_code", "exchange_code", "type", "ticksize", "lot_size")]
        if extra:
            print("  其他头部字段：" + "，".join(f"{k}={str(i[k])[:60]!r}" for k in extra))
        st = cs_book_stats(f, args.max_events)
        print(f"  时间（接收，UTC）：{ns_utc(st['first'])} — {ns_utc(st['last'])}；事件 {st['n']} 条：" +
              "、".join(f"{tname.get(k, f'类型{k}')} {v}" for k, v in sorted(st["types"].items())))
        print(f"  快照 {st['snapshots']} 次，事件链断点 {st['gaps']} 处，重复事件 {st['dups']} 条，ERROR 状态 {st['errors']} 次，坏行 {f.bad_lines} 行")
        if st["checks"]:
            rate = st["crossed"] / st["checks"]
            print(f"  买一 ≥ 卖一（交叉）占比 {rate:.2%}（共检查 {st['checks']} 次）" +
                  ("  ← 偏高：文件可能混有两个选项的报价，或数量不是绝对值" if rate > 0.05 else ""))
        if st["bid"] or st["ask"]:
            b, a = st["bid"], st["ask"]
            print(f"  文件末尾盘口：买一 {b[0] if b else '-'} × {b[1] if b else '-'}，卖一 {a[0] if a else '-'} × {a[1] if a else '-'}；"
                  f"买档 {st['levels'][0]}、卖档 {st['levels'][1]}")
        if args.head:
            print("  前几行事件原文：")
            for ln in f.raw_lines(args.head):
                print("    " + (ln if len(ln) <= 240 else ln[:240] + " …"))
        print()
    mt = load_match(args, include_closed=True)
    if mt:
        mapped, unmapped = map_cs_files(files, mt, args.cs_side)
        print("与盘口的对应：")
        for f, leg, ti, how in mapped:
            print(f"  {os.path.basename(f.path)} → {leg.question}「{leg.labels[ti]}」（{how}）")
        _print_unmapped(unmapped)
    return 0


class CsBooks(Books):
    def __init__(self):
        super().__init__()
        self.last: dict = {}
        self.seen: dict = {}
        self.gaps: dict = {}
        self.has_snap: set = set()
        self.dups = 0

    def apply(self, tok: str, t: int, prev, eid, data) -> bool:
        if t == 5:
            if str((data or (None,))[0]).upper() == "ERROR":
                self.suspect.add(tok)
                return True
            return False
        if t not in (0, 1):
            return False
        if eid is not None:
            s = self.seen.setdefault(tok, set())
            if eid in s:
                self.dups += 1
                return False
            s.add(eid)
        bids, asks = self.bids.setdefault(tok, {}), self.asks.setdefault(tok, {})
        if t == 0:
            bids.clear()
            asks.clear()
            self.suspect.discard(tok)
            self.has_snap.add(tok)
        elif tok not in self.has_snap:
            self.suspect.add(tok)                 # 还没见过快照：没有完整盘口
        elif prev is not None and self.last.get(tok) is not None and prev != self.last[tok]:
            self.gaps[tok] = self.gaps.get(tok, 0) + 1
            self.suspect.add(tok)                 # 断档：直到下一次快照前不用这个盘口
        for lv in data or []:
            side, p, q = lv[0], float(lv[1]), float(lv[2])
            book = bids if side == 0 else asks
            if q == 0.0:
                book.pop(p, None)
            else:
                book[p] = q
        if eid is not None:
            self.last[tok] = eid
        return True


def cmd_cs_replay(args) -> int:
    matches = []
    for mp in args.meta or []:
        meta = json.load(open(mp, encoding="utf-8"))
        ev = meta.get("event") or {}
        matches.append(build_match(ev.get("slug") or "", ev.get("title") or "", meta.get("markets") or [], True))
    for s in args.event_slug or []:
        info, markets = gamma_event(args.gamma, s)
        matches.append(build_match(info.get("slug") or s, info.get("title") or "", markets, True))
    matches = [m for m in matches if m]
    if not matches:
        print("需要 --meta 或 --event-slug 来确定比赛有哪些盘口（可以给多个）。", file=sys.stderr)
        return 2
    files = load_cs_files(args.files)
    rc = 0
    for mt in matches:
        rc |= _cs_replay_one(args, mt, files, args.out if len(matches) == 1 else None)
    return rc


def _cs_replay_one(args, mt: Match, files: list, out: str | None) -> int:
    print("=" * 72)
    print(describe(mt), "\n")
    mapped, unmapped = map_cs_files(files, mt, args.cs_side)
    if not mapped:
        print("没有任何文件对应到这场比赛的赛果盘口。先用 cs-inspect 看文件头部。", file=sys.stderr)
        return 2
    print("文件对应：")
    for f, leg, ti, how in mapped:
        print(f"  {os.path.basename(f.path)} → {leg.question}「{leg.labels[ti]}」（{how}）")
    _print_unmapped(unmapped)
    covered = {leg.tokens[0] for _, leg, _, _ in mapped}
    lacking = [leg.question for leg in mt.legs if leg.tokens[0] not in covered]
    if lacking:
        print("  没有数据的盘口：" + "；".join(lacking))
    print()

    model = Model(mt, void=not args.no_void, strict=args.strict)
    books = CsBooks()

    def stream(idx, f, tok):
        for n, (ats, t, prev, eid, data) in enumerate(f.events()):
            yield ats, idx, n, tok, t, prev, eid, data

    merged = heapq.merge(*[stream(i, f, leg.tokens[ti]) for i, (f, leg, ti, _) in enumerate(mapped)])

    def events():
        for ats, _, _, tok, t, prev, eid, data in merged:
            yield ats // 1_000_000, books.apply(tok, t, prev, eid, data)

    ep = scan_stream(model, books, events(), args, mt.title)
    out = out or f"cs_scan_{mt.slug or 'match'}.csv"
    ep.write_csv(out)
    print(f"评估 {ep.n_eval} 次盘口状态；全程锁定 $1 的最低成本最小值 {ep.min_unit:.4f}")
    gaps = sum(books.gaps.values())
    print(f"事件链断点 {gaps} 处（断点到下一次快照之间该盘口不参与计算），跨文件重复事件 {books.dups} 条已去重")
    print(ep.summary())
    print(f"明细：{os.path.abspath(out)}")
    return 0


# ============================================================ 命令行

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="LoL 同平台组合套利扫描（Polymarket，只读）")
    sub = p.add_subparsers(dest="cmd", required=True)

    def scan_opts(sp):
        sp.add_argument("--fee-rate", type=float, default=0.05, help="吃单费率，费用 = 费率 × p × (1−p) × 股数；默认 0.05")
        sp.add_argument("--min-profit", type=float, default=0.5, help="报告门槛：可锁定利润（美元），默认 0.5")
        sp.add_argument("--min-shares", type=float, default=5.0, help="最小下单量（股），只用于提示，默认 5")
        sp.add_argument("--max-cost", type=float, default=None,
                        help="每次组合的投入上限（美元，含手续费），如 2000；默认不限，吃满可见深度")
        sp.add_argument("--no-void", action="store_true", help="不考虑“整场取消、全部 50-50”")
        sp.add_argument("--strict", action="store_true", help="把“开赛后中途终止”也作为约束")

    def src_opts(sp):
        sp.add_argument("--meta", help="盘口清单 JSON（meta 子命令或 pm_recorder 的 meta_start.json）")
        sp.add_argument("--event-slug", help="从 Gamma 取盘口清单")
        sp.add_argument("--gamma", default=GAMMA)

    a = sub.add_parser("live", help="实时扫描")
    a.add_argument("--event-slug", nargs="*", help="一个或多个赛事 slug")
    a.add_argument("--discover", action="store_true", help="自动找当前所有 LoL 比赛（标签名未经实测）")
    a.add_argument("--tag", default="league-of-legends")
    a.add_argument("--interval", type=float, default=2.0, help="轮询间隔秒数，默认 2")
    a.add_argument("--once", action="store_true", help="只扫一轮")
    a.add_argument("--show-map", action="store_true", help="打印每个盘口被识别成什么")
    a.add_argument("--out", help="把发现的机会追加写入这个 JSONL 文件")
    a.add_argument("--gamma", default=GAMMA)
    a.add_argument("--clob", default=CLOB)
    scan_opts(a)
    a.set_defaults(fn=cmd_live)

    b = sub.add_parser("replay", help="回放 pm_recorder.py 的录制目录")
    b.add_argument("dir")
    b.add_argument("--step-ms", type=int, default=0, help="两次评估的最小间隔毫秒；默认 0（价格每变一次都评估）")
    scan_opts(b)
    b.set_defaults(fn=cmd_replay)

    c = sub.add_parser("meta", help="保存一场比赛的盘口清单")
    c.add_argument("--event-slug", required=True)
    c.add_argument("--out")
    c.add_argument("--gamma", default=GAMMA)
    c.set_defaults(fn=cmd_meta)

    d = sub.add_parser("cs-inspect", help="查看 CryptoStruct 文件")
    d.add_argument("files", nargs="+")
    d.add_argument("--head", type=int, default=3, help="打印前几行事件原文，默认 3")
    d.add_argument("--max-events", type=int, default=0, help="统计时最多读多少条事件，0 为全部")
    d.add_argument("--cs-side", choices=["auto", "first", "second"], default="auto",
                   help="文件里的价格对应盘口的哪个选项；auto：能对上 token id 就用，否则按第一个选项")
    src_opts(d)
    d.set_defaults(fn=cmd_cs_inspect)

    e = sub.add_parser("cs-replay", help="回放 CryptoStruct 历史数据")
    e.add_argument("files", nargs="+", help="文件或目录（.zst / .jsonl / .gz）")
    e.add_argument("--out", help="机会明细 CSV，默认 cs_scan_<slug>.csv")
    e.add_argument("--step-ms", type=int, default=0)
    e.add_argument("--cs-side", choices=["auto", "first", "second"], default="auto")
    e.add_argument("--meta", nargs="+", help="一个或多个盘口清单 JSON")
    e.add_argument("--event-slug", nargs="+", help="一个或多个赛事 slug，从 Gamma 取盘口清单")
    e.add_argument("--gamma", default=GAMMA)
    scan_opts(e)
    e.set_defaults(fn=cmd_cs_replay)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
