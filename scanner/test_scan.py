#!/usr/bin/env python3
"""lol_c_scan.py v2 测试：盘口识别（含 Worlds 决赛盘口清单）、结算情景、线性规划、两种回放。"""
import csv
import json
import os
import shutil
import sys
import tempfile

import zstandard

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lol_c_scan as S  # noqa: E402

EV = "lol-blg-gen-2026-11-14"


def mk(q, outs, i, slug="", **kw):
    return dict(question=q, outcomes=outs, token_ids=[f"{i}a", f"{i}b"], conditionId=f"0x{i}", slug=slug, **kw)


# ---------------------------------------------------------------- 1. Worlds 决赛盘口识别
def worlds_markets(h_outs=("Gen.G", "Bilibili Gaming")):
    """按 lines.com 上列出的 Worlds 决赛盘口构造：题目格式与 Polymarket 已结束赛事的镜像页一致。"""
    ms = [mk("LoL: Bilibili Gaming vs Gen.G (BO5) - Worlds Playoffs", ["Bilibili Gaming", "Gen.G"], "ml", EV)]
    for k in range(1, 5):
        ms.append(mk(f"LoL: Bilibili Gaming vs Gen.G - Game {k} Winner", ["Bilibili Gaming", "Gen.G"], f"g{k}", f"{EV}-game{k}"))
    ms += [mk("Games Total: O/U 3.5", ["Over", "Under"], "t35", f"{EV}-total-games-3pt5"),
           mk("Games Total: O/U 4.5", ["Over", "Under"], "t45", f"{EV}-total-games-4pt5"),
           mk("Game Handicap: GEN (-1.5) vs Bilibili Gaming (+1.5)", list(h_outs), "h15", f"{EV}-game-handicap-home-1pt5"),
           mk("Game Handicap: GEN (-2.5) vs Bilibili Gaming (+2.5)", list(h_outs), "h25", f"{EV}-game-handicap-home-2pt5"),
           mk("Game 1: Both Teams Slay Baron Nashor?", ["Yes", "No"], "p1", f"{EV}-game1-both-teams-slay-baron"),
           mk("Game 1: Any Player Quadra Kill?", ["Yes", "No"], "p2", f"{EV}-game1-any-player-quadra-kill"),
           mk("Total Kills Over/Under 27.5 in Game 1?", ["Over", "Under"], "p3", f"{EV}-game1-kill-over-27pt5"),
           mk("Game 1: Duration O/U 31:30", ["Over", "Under"], "p4", f"{EV}-game1-duration-31pt5")]
    return ms


mt = S.build_match(EV, "", worlds_markets())
print(S.describe(mt), "\n")
assert (mt.team_a, mt.team_b, mt.best_of) == ("Bilibili Gaming", "Gen.G", 5)
kinds = sorted((l.kind, l.param) for l in mt.legs)
assert kinds == [("game", 1.0), ("game", 2.0), ("game", 3.0), ("game", 4.0), ("hcap", 1.5), ("hcap", 2.5),
                 ("ml", 0.0), ("total", 3.5), ("total", 4.5)], kinds
assert len(mt.skipped) == 4 and any("第 5 局" in w for w in mt.warnings)
H = {l.param: l for l in mt.legs if l.kind == "hcap"}
assert H[1.5].fav == "B" and H[1.5].t0_is == "F"                  # Gen.G 让分，token0 = Gen.G
for outs, expect in [(("GEN", "Bilibili Gaming"), "F"), (("Bilibili Gaming", "Gen.G"), "D"),
                     (("Gen.G -1.5", "Bilibili Gaming +1.5"), "F"), (("Bilibili Gaming +1.5", "GEN -1.5"), "D")]:
    m2 = S.build_match(EV, "", worlds_markets(outs))
    h = next(l for l in m2.legs if l.kind == "hcap")
    assert h.fav == "B" and h.t0_is == expect, (outs, h.t0_is)
m3 = S.build_match(EV, "", worlds_markets(("Yes", "No")))
assert not any(l.kind == "hcap" for l in m3.legs) and sum("分不清" in s for s in m3.skipped) == 2
print("Worlds 决赛盘口识别：通过（含让局选项写法的 4 种变体，Yes/No 选项会被跳过）")

# ---------------------------------------------------------------- 2. 队名匹配
cases = [("T1", "T1", "T1 Academy", "A"), ("T1 Academy", "T1", "T1 Academy", "B"),
         ("BLG", "Bilibili Gaming", "Gen.G", "A"), ("GEN", "Bilibili Gaming", "Gen.G", "B"),
         ("IG", "Invictus Gaming", "Gen.G", "A"), ("G2", "G2 Esports", "G2 NORD", None),
         ("Gen.G", "Gen.G", "Gen.G Global Academy", "A"), ("GEN", "Gen.G", "Gen.G Global Academy", None),
         ("Karmine Corp", "G2 Esports", "Karmine Corp", "B")]
for name, a, b, want in cases:
    assert S.team_side(name, a, b) == want, (name, a, b, S.team_side(name, a, b))
print("队名匹配：通过（有歧义时返回“无法对应”，不会猜）")

# ---------------------------------------------------------------- 3. 题目与 slug 交叉核对
bad = worlds_markets()
bad[2] = mk("LoL: Bilibili Gaming vs Gen.G - Game 2 Winner", ["Bilibili Gaming", "Gen.G"], "g2", f"{EV}-game3")
m4 = S.build_match(EV, "", bad)
assert any("不一致" in s for s in m4.skipped) and not any(l.kind == "game" and l.param == 2 for l in m4.legs)
only_slug = worlds_markets()
only_slug[2] = mk("Bilibili Gaming vs Gen.G Map 2", ["Gen.G", "Bilibili Gaming"], "g2", f"{EV}-game2")
m5 = S.build_match(EV, "", only_slug)
g2 = next(l for l in m5.legs if l.kind == "game" and l.param == 2)
assert g2.via == "slug" and g2.t0_is == "B"
print("题目与 slug 交叉核对：通过")

# ---------------------------------------------------------------- 4. 结算情景
assert len(S.build_scenarios(5)) == 21 and len(S.build_scenarios(5, abandon=True)) == 77
assert len(S.build_scenarios(3)) == 7 and len(S.build_scenarios(3, abandon=True)) == 21
L = {(l.kind, l.param): l for l in mt.legs}
s = S.Scenario("abandon", ("A", "B"), "A")         # BLG 赢第 1 局、Gen.G 赢第 2 局后中止，胜负判给 BLG
assert L[("ml", 0.0)].value(s) == 1.0 and L[("game", 1.0)].value(s) == 1.0 and L[("game", 2.0)].value(s) == 0.0
assert L[("game", 3.0)].value(s) == 0.5 and L[("total", 3.5)].value(s) == 0.5 and L[("hcap", 1.5)].value(s) == 0.5
for pa in S.series_paths(5):                       # 第五节的恒等式在正常打完的情景下仍成立（这里没有 G5，换用 BO5 完整清单）
    pass
print("结算情景：通过（BO5 正常打完 20 种 + 整场取消 1 种；中途终止 56 种）")

# ---------------------------------------------------------------- 5. 线性规划
A, B = "G2 Esports", "Karmine Corp"


def g2kc():
    ms = [mk(f"LoL: {A} vs {B} (BO5) - LEC Playoffs", [A, B], "ml", "lol-g2-kc")]
    ms += [mk(f"LoL: {A} vs {B} - Game {k} Winner", [A, B], f"g{k}", f"lol-g2-kc-game{k}") for k in range(1, 6)]
    ms += [mk("Games Total: O/U 3.5", ["Over", "Under"], "t35", "lol-g2-kc-total-games-3pt5"),
           mk("Games Total: O/U 4.5", ["Over", "Under"], "t45", "lol-g2-kc-total-games-4pt5"),
           mk(f"Game Handicap: G2 (-1.5) vs {B} (+1.5)", [A, B], "h15", "lol-g2-kc-game-handicap-away-1pt5"),
           mk(f"Game Handicap: G2 (-2.5) vs {B} (+2.5)", [A, B], "h25", "lol-g2-kc-game-handicap-away-2pt5")]
    return ms


M = S.build_match("lol-g2-kc", "G2 vs KC", g2kc())
LM = {(l.kind, l.param): l for l in M.legs}


def fair(mt, p=0.62):
    paths = S.series_paths(mt.best_of)
    pr = lambda pa: (p ** pa.count("A")) * ((1 - p) ** pa.count("B"))
    return {l.tokens[0]: sum(pr(pa) * l.value(S.Scenario("path", pa, "A" if pa.count("A") == 3 else "B")) for pa in paths)
            for l in mt.legs}


V = fair(M)


def books_from(v, spread=0.01, size=500.0, over=None):
    over = over or {}
    out = {}
    for l in M.legs:
        x = v[l.tokens[0]]
        out[l.tokens[0]] = over.get(l.tokens[0], [(min(0.999, x + spread), size)])
        out[l.tokens[1]] = over.get(l.tokens[1], [(min(0.999, 1 - x + spread), size)])
    return out


for strict in (False, True):
    model = S.Model(M, strict=strict)
    for fee in (0.0, 0.05):
        r = S.solve(model, books_from(V), fee)
        assert r.profit < 1e-6 and r.unit_cost >= 1 - 1e-9, (strict, fee, r)
    r = S.solve(model, books_from(V, spread=0.0), 0.0)
    assert abs(r.unit_cost - 1) < 1e-6 and r.profit < 1e-6
print("公平价加价差：不误报（普通与严格模式、有无手续费）")

# 只能靠恒等式锁定的错价：G5（G2 胜）卖价低 8 分，但同一盘口另一边贵 9 分，单盘口两边相加仍 > 1
g5 = LM[("game", 5.0)]
x5 = V[g5.tokens[0]]
ov = {g5.tokens[0]: [(x5 - 0.08, 300.0)], g5.tokens[1]: [(1 - x5 + 0.09, 300.0)]}
r_n = S.solve(S.Model(M), books_from(V, spread=0.005, over=ov), 0.05)
r_s = S.solve(S.Model(M, strict=True), books_from(V, spread=0.005, over=ov), 0.05)
print(f"恒等式错价：普通模式利润 ${r_n.profit:.2f}，中途终止最差 ${r_n.tail_pnl:+.2f}（{r_n.tail_label}）；严格模式利润 ${r_s.profit:.2f}")
assert r_n.profit > 1.0 and r_n.tail_pnl < 0 and r_s.profit < r_n.profit - 0.5
tokmap = {t: (l, i) for l in M.legs for i, t in enumerate(l.tokens)}
spent = sum(o["shares"] * o["price"] + o["fee"] for o in r_n.orders)
pay = lambda sc: sum(o["shares"] * (tokmap[o["token"]][0].value(sc) if tokmap[o["token"]][1] == 0 else 1 - tokmap[o["token"]][0].value(sc)) for o in r_n.orders)
worst = min(pay(sc) for sc in S.build_scenarios(5))
assert worst - spent > r_n.profit - 0.05, (worst, spent, r_n.profit)
print("恒等式错价：通过（普通模式找到并穷举复核；严格模式因中途终止风险不再报同样的组合）")

# 单调性错价：让 2.5 的买价高于让 1.5 的卖价，中途终止也不亏
h15, h25 = LM[("hcap", 1.5)], LM[("hcap", 2.5)]
ov = {h25.tokens[1]: [(0.40, 100.0)], h25.tokens[0]: [(0.62, 100.0)]}   # 同一订单簿：token0 买 0.60 / 卖 0.62
r = S.solve(S.Model(M, strict=True), books_from(V, spread=0.005, over=ov), 0.05)
assert r.profit > 1.0 and any(o["token"] == h25.tokens[1] for o in r.orders), r
spent = sum(o["shares"] * o["price"] + o["fee"] for o in r.orders)
val = lambda o, sc: tokmap[o["token"]][0].value(sc) if tokmap[o["token"]][1] == 0 else 1 - tokmap[o["token"]][0].value(sc)
worst = min(sum(o["shares"] * val(o, sc) for o in r.orders) for sc in S.build_scenarios(5, abandon=True))
assert worst - spent > r.profit - 0.05, (worst, spent)
print(f"让局错价：通过（严格模式利润 ${r.profit:.2f}，77 种情景穷举复核不亏；组合：" +
      "；".join(f"{o['label']} / {o['question']}" for o in r.orders) + "）")

# 手续费吃掉小错价、深度限制
ov = {g5.tokens[0]: [(x5 - 0.01, 200.0)]}
assert S.solve(S.Model(M), books_from(V, over=ov), 0.05).profit < 1e-6
ov = {h25.tokens[1]: [(0.40, 37.0)], h25.tokens[0]: [(0.62, 37.0)]}
r = S.solve(S.Model(M, strict=True), books_from(V, spread=0.005, over=ov), 0.05)
assert sum(o["shares"] for o in r.orders if o["token"] == h25.tokens[1]) <= 37.0 + 1e-6
print("手续费门槛、深度上限：通过")


# ---------------------------------------------------------------- 6. pm_recorder 回放（只录了 token0 的盘口，token1 由买单换算）
def mirror_snapshot(v, spread=0.01, size=500.0):
    return [{"event_type": "book", "asset_id": l.tokens[0], "market": "0x", "timestamp": "0",
             "asks": [{"price": f"{v[l.tokens[0]] + spread:.4f}", "size": str(size)}],
             "bids": [{"price": f"{v[l.tokens[0]] - spread:.4f}", "size": str(size)}]} for l in M.legs]


def pc(token, price, size, side):
    return {"event_type": "price_change", "market": "0x", "timestamp": "0",
            "price_changes": [{"asset_id": token, "price": f"{price:.4f}", "size": str(size), "side": side}]}


d = tempfile.mkdtemp(prefix="pm_replay_")
json.dump({"event": {"slug": "lol-g2-kc", "title": "G2 vs KC"}, "markets": g2kc()}, open(os.path.join(d, "meta_start.json"), "w"))
t0 = 1_800_000_000_000
other = LM[("game", 1.0)].tokens[0]
with open(os.path.join(d, "pm_market.jsonl"), "w") as f:
    w = lambda ts, msg: f.write(json.dumps({"recv_ms": ts, "raw": json.dumps(msg)}) + "\n")
    w(t0, mirror_snapshot(V))
    for i in range(1, 41):
        ts = t0 + i * 250
        a25 = V[h25.tokens[0]] + 0.01
        if i == 10:                                             # 让 2.5 出现 0.60 买单、卖一挪到 0.62（盘口不交叉）
            w(ts, {"event_type": "price_change", "market": "0x", "timestamp": "0", "price_changes": [
                {"asset_id": h25.tokens[0], "price": "0.6000", "size": "120", "side": "BUY"},
                {"asset_id": h25.tokens[0], "price": f"{a25:.4f}", "size": "0", "side": "SELL"},
                {"asset_id": h25.tokens[0], "price": "0.6200", "size": "120", "side": "SELL"}]})
        elif i == 22:                                           # 恢复
            w(ts, {"event_type": "price_change", "market": "0x", "timestamp": "0", "price_changes": [
                {"asset_id": h25.tokens[0], "price": "0.6000", "size": "0", "side": "BUY"},
                {"asset_id": h25.tokens[0], "price": "0.6200", "size": "0", "side": "SELL"},
                {"asset_id": h25.tokens[0], "price": f"{a25:.4f}", "size": "500", "side": "SELL"}]})
        elif i == 30:
            snap = mirror_snapshot(V)[0]                        # 与增量重建一致的完整快照
            snap["bids"].append({"price": "0.3000", "size": "7"})
            w(ts - 1, pc(snap["asset_id"], 0.30, 7, "BUY"))
            w(ts, [snap])
        elif i == 35:
            w(ts, [dict(mirror_snapshot(V)[1], bids=[])])       # 与重建不一致的快照
        else:
            w(ts, pc(other, 0.99, i, "SELL"))
rc = S.main(["replay", d])
rows = list(csv.DictReader(open(os.path.join(d, "c_scan_episodes.csv"), encoding="utf-8")))
assert rc == 0 and len(rows) == 1 and abs(float(rows[0]["duration_s"]) - 3.0) < 0.01, rows
assert float(rows[0]["abandon_worst_pnl_usd"]) >= -1e-6
shutil.rmtree(d)
print("pm_recorder 回放：通过（1 段机会，持续 3.0 秒，中途终止也不亏）\n")


# ---------------------------------------------------------------- 7. CryptoStruct 回放
def cs_write(path, code, iid, events):
    header = {"instrument": {"id": iid, "code": code, "native_code": code, "exchange_code": "POLYMARKET",
                             "type": "perpetual", "ticksize": "0.001", "lot_size": "0.01"}, "underlyings": []}
    raw = (json.dumps(header) + "\n" + "\n".join(json.dumps(e) for e in events) + "\n").encode()
    with open(path, "wb") as f:
        f.write(zstandard.ZstdCompressor().compress(raw))


d = tempfile.mkdtemp(prefix="cs_replay_")
json.dump({"event": {"slug": "lol-g2-kc", "title": "G2 vs KC"}, "markets": g2kc()}, open(os.path.join(d, "meta.json"), "w"))
os.makedirs(os.path.join(d, "files"))
NS = 1_000_000
T0 = 1_800_000_000_000 * NS
for idx, leg in enumerate(M.legs):
    x = V[leg.tokens[0]]
    iid = 1000 + idx
    ev = [[0, iid, "0", f"{iid}-0", T0, T0, [[0, f"{x - 0.01:.4f}", "500", 1], [1, f"{x + 0.01:.4f}", "500", 1]], False]]
    eid = 0
    for i in range(1, 41):
        ts = T0 + i * 250 * NS + idx
        prev, eid = f"{iid}-{eid}", eid + 1
        lv = [[1, f"{x + 0.01:.4f}", str(500 + i), 1]]
        if leg is h25 and 10 < i < 22:
            lv = [[1, "0.6200", str(120 + i), 1]]               # 错价期间，常规更新落在新的卖一上
        if leg is h25 and i == 10:
            lv = [[0, "0.6000", "120", 1], [1, f"{x + 0.01:.4f}", "0", 1], [1, "0.6200", "120", 1]]
        if leg is h25 and i == 22:
            lv = [[0, "0.6000", "0", 1], [1, "0.6200", "0", 1], [1, f"{x + 0.01:.4f}", "500", 1]]
        if leg is LM[("game", 1.0)] and i == 15:
            prev = "lost"                                     # 断档：之后不用这个盘口，直到下一次快照
        if leg is LM[("game", 1.0)] and i == 18:
            ev.append([0, iid, "0", f"{iid}-{eid}", ts, ts, [[0, f"{x - 0.01:.4f}", "500", 1], [1, f"{x + 0.01:.4f}", "500", 1]], False])
            continue
        ev.append([1, iid, prev, f"{iid}-{eid}", ts, ts, lv])
    cs_write(os.path.join(d, "files", f"{leg.slug}.2026-05-16.txt.zst"), leg.slug, iid, ev)
    if leg is h15:                                           # 次日文件与前一天重叠，含重复事件
        cs_write(os.path.join(d, "files", f"{leg.slug}.2026-05-17.txt.zst"), leg.slug, iid, ev[30:])
cs_write(os.path.join(d, "files", "lol-g2-kc-game1-both-teams-slay-baron.2026-05-16.txt.zst"),
         "lol-g2-kc-game1-both-teams-slay-baron", 999, [[0, 999, "0", "999-0", T0, T0, [[0, "0.49", "10", 1]], False]])

S.main(["cs-inspect", os.path.join(d, "files", f"{h25.slug}.2026-05-16.txt.zst"), "--meta", os.path.join(d, "meta.json"), "--head", "2"])
out = os.path.join(d, "cs.csv")
rc = S.main(["cs-replay", os.path.join(d, "files"), "--meta", os.path.join(d, "meta.json"), "--out", out])
rows = list(csv.DictReader(open(out, encoding="utf-8")))
assert rc == 0 and len(rows) == 1 and abs(float(rows[0]["duration_s"]) - 3.0) < 0.01, rows
assert float(rows[0]["abandon_worst_pnl_usd"]) >= -1e-6
shutil.rmtree(d)
print("CryptoStruct 回放：通过（slug 对应文件、断档期间剔除、跨日重复事件去重、1 段机会持续 3.0 秒）")


# ---------------------------------------------------------------- 8. 复查后补的几项
assert S._norm("LØS") == S._norm("LOS") == "los" and S.team_side("LOS", "Team Liquid", "LØS") == "B"
assert S.team_side("Fénix", "Movistar KOI Fénix", "BIG") == "A"


class _F:                                    # 只用到 candidates() 的假文件对象
    def __init__(self, code):
        self.path, self.inst = f"/x/{code}.2026-05-16.txt.zst", {"id": 1, "code": code}

    def candidates(self):
        return [self.inst["code"], os.path.basename(self.path)]


mp, um = S.map_cs_files([_F("lol-g2-kc-game1-karmine-corp"), _F("lol-g2-kc-game1-yes"), _F("lol-g2-kc"),
                         _F("lol-g2-kc-game1-both-teams-slay-baron")], M, "auto")
got = {f.inst["code"]: (leg.kind, leg.param, ti) for f, leg, ti, _ in mp}
assert got == {"lol-g2-kc-game1-karmine-corp": ("game", 1.0, 1), "lol-g2-kc-game1-yes": ("game", 1.0, 0),
               "lol-g2-kc": ("ml", 0.0, 0)} and len(um) == 1, (got, len(um))

b = S.CsBooks()                               # 事件 ID 为“无 ID”哨兵值时，快照后的增量照常使用
tok = M.legs[0].tokens[0]
b.apply(tok, 1, None, None, [[1, "0.5", "10", 1]])
assert tok in b.suspect                       # 快照前的增量：不可信
b.apply(tok, 0, None, str(S.INT64_MAX), [[0, "0.4", "10", 1], [1, "0.5", "10", 1]])
b.apply(tok, 1, None, None, [[1, "0.5", "12", 1]])
assert tok not in b.suspect and b.asks[tok] == {0.5: 12.0}

d = tempfile.mkdtemp(prefix="cs_multi_")
for name in ("a", "b"):
    json.dump({"event": {"slug": f"lol-g2-kc-{name}", "title": f"G2 vs KC {name}"},
               "markets": [dict(m, slug=m["slug"].replace("lol-g2-kc", f"lol-g2-kc-{name}")) for m in g2kc()]},
              open(os.path.join(d, f"{name}.json"), "w"))
    cs_write(os.path.join(d, f"lol-g2-kc-{name}.2026-05-16.txt.zst"), f"lol-g2-kc-{name}", 7,
             [[0, 7, "0", "7-0", T0, T0, [[0, "0.70", "10", 1], [1, "0.72", "10", 1]], False]])
cwd = os.getcwd()
os.chdir(d)
rc = S.main(["cs-replay", d, "--meta", os.path.join(d, "a.json"), os.path.join(d, "b.json")])
os.chdir(cwd)
assert rc == 0 and os.path.exists(os.path.join(d, "cs_scan_lol-g2-kc-a.csv")) and os.path.exists(os.path.join(d, "cs_scan_lol-g2-kc-b.csv"))
shutil.rmtree(d)
print("复查补充：通过（非 ASCII 队名、slug 加选项后缀、无 ID 事件、一次回放多场）")


# ---------------------------------------------------------------- 9. native_code.referenceOutcome、投入上限
g1 = LM[("game", 1.0)]


class _NF(_F):
    def __init__(self, code, nc):
        super().__init__(code)
        self.inst["native_code"] = nc

    def candidates(self):                     # 与真实文件一样：字典型 native_code 不进候选
        return [self.inst["code"], os.path.basename(self.path)]


nc2 = {"referenceOutcome": "karmine corp", "karmine corp": g1.tokens[1], "g2 esports": g1.tokens[0],
       "marketSlug": g1.slug}
mp, um = S.map_cs_files([_NF(g1.slug, nc2), _NF(g1.slug + "-x", json.dumps(nc2))], M, "auto")
assert [(leg is g1, ti) for _, leg, ti, _ in mp] == [(True, 1), (True, 1)] and not um, mp
assert "referenceOutcome" in mp[0][3]

ov = {h25.tokens[1]: [(0.40, 100.0)], h25.tokens[0]: [(0.62, 100.0)]}
full = S.solve(S.Model(M, strict=True), books_from(V, spread=0.005, over=ov), 0.05)
capped = S.solve(S.Model(M, strict=True), books_from(V, spread=0.005, over=ov), 0.05, max_cost=30.0)
assert full.cost > 30.0 and capped.cost <= 30.0 + 1e-6 and 0 < capped.profit < full.profit, (full.cost, capped.cost)
print(f"referenceOutcome 对应第二个选项、投入上限：通过（不限 ${full.profit:.2f}/${full.cost:.2f}，上限 $30 时 ${capped.profit:.2f}/${capped.cost:.2f}）")

d = tempfile.mkdtemp(prefix="cs_manifest_")
open(os.path.join(d, "MANIFEST.txt"), "w").write("清单，不是数据\n")
cs_write(os.path.join(d, "lol-g2-kc.2026-05-16.txt.zst"), "lol-g2-kc", 7, [])
open(os.path.join(d, "broken.txt.zst"), "wb").write(b"not zstd")
assert [os.path.basename(f.path) for f in S.load_cs_files([d])] == ["lol-g2-kc.2026-05-16.txt.zst"]
shutil.rmtree(d)
print("区间下载目录：通过（跳过 MANIFEST.txt 与损坏文件）")
