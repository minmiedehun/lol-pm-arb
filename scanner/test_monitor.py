#!/usr/bin/env python3
"""c_monitor.py 测试：本地模拟 Gamma / CLOB REST / market WebSocket，不联网。
覆盖：增量维护订单簿与机会段、断线重连、最优价核对、REST 抽查纠错、单局结算后收窄情景、新盘口上架重新订阅、
WebSocket 不可用时改用 REST 轮询、录制可被 replay 复现。"""
import asyncio
import csv
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import websockets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lol_c_scan as S  # noqa: E402
import c_monitor as C  # noqa: E402

EV = "lol-blg-gen-2026-11-14"
T, F = "Bilibili Gaming", "Gen.G"


def mk(q, outs, i, slug):
    return {"id": i, "question": q, "slug": slug, "conditionId": f"0x{i}", "outcomes": json.dumps(outs),
            "clobTokenIds": json.dumps([f"{i}a", f"{i}b"]), "closed": False, "outcomePrices": json.dumps(["0.5", "0.5"])}


def markets(phase):
    ms = [mk(f"LoL: {T} vs {F} (BO5) - Worlds Playoffs", [T, F], "ml", EV)]
    ms += [mk(f"LoL: {T} vs {F} - Game {k} Winner", [T, F], f"g{k}", f"{EV}-game{k}") for k in range(1, 5)]
    ms += [mk("Games Total: O/U 3.5", ["Over", "Under"], "t35", f"{EV}-total-games-3pt5"),
           mk("Games Total: O/U 4.5", ["Over", "Under"], "t45", f"{EV}-total-games-4pt5"),
           mk(f"Game Handicap: GEN (-1.5) vs {T} (+1.5)", [F, T], "h15", f"{EV}-game-handicap-home-1pt5"),
           mk(f"Game Handicap: GEN (-2.5) vs {T} (+2.5)", [F, T], "h25", f"{EV}-game-handicap-home-2pt5"),
           mk("Game 1: Any Player Penta Kill?", ["Yes", "No"], "p1", f"{EV}-game1-any-player-penta-kill")]
    if phase >= 2:                                    # 第 1 局 BLG 胜并结算；第 5 局胜负上架
        ms[1].update(closed=True, outcomePrices=json.dumps(["1", "0"]))
        ms.append(mk(f"LoL: {T} vs {F} - Game 5 Winner", [T, F], "g5", f"{EV}-game5"))
    return ms


# ---------------- 服务器端订单簿：token0 与 token1 互为镜像（与真实接口一样各自有完整订单簿）
MT = S.build_match(EV, "", [S.norm_market(m) for m in markets(2)], include_closed=True)
LEG = {(l.kind, l.param): l for l in MT.legs}
PAIR = {}
for l in MT.legs:
    PAIR[l.tokens[0]], PAIR[l.tokens[1]] = l.tokens[1], l.tokens[0]


def fair(p=0.5, g1=None):
    """公平价；g1 给定时为第 1 局结果已知的条件价格。"""
    paths = [pa for pa in S.series_paths(5) if g1 is None or pa[0] == g1]
    w = {pa: (p ** pa.count("A")) * ((1 - p) ** pa.count("B")) for pa in paths}
    tot = sum(w.values())
    return {l.tokens[0]: sum(w[pa] * l.value(S.Scenario("path", pa, "A" if pa.count("A") == 3 else "B"))
                             for pa in paths) / tot for l in MT.legs}


V = fair()
BOOK = {}           # token → {"bids": {p: s}, "asks": {p: s}}
SPREAD = 0.01


def set_level(tok, side, p, s):
    """token 的 side（BUY/SELL）档位设为 s，同时更新镜像 token；返回两条 price_change。"""
    p = round(p, 4)
    out = []
    for t, sd, px in ((tok, side, p), (PAIR[tok], "SELL" if side == "BUY" else "BUY", round(1 - p, 4))):
        b = BOOK[t]["bids" if sd == "BUY" else "asks"]
        if s <= 0:
            b.pop(px, None)
        else:
            b[px] = s
        bb = max(BOOK[t]["bids"], default=0.0)
        ba = min(BOOK[t]["asks"], default=0.0)
        out.append({"asset_id": t, "price": f"{px:.4f}", "size": str(s), "side": sd, "best_bid": str(bb), "best_ask": str(ba)})
    return out


def price_all(v):
    for l in MT.legs:
        for t in l.tokens:
            BOOK[t] = {"bids": {}, "asks": {}}
        x = v[l.tokens[0]]
        if x <= 0.0 or x >= 1.0:                      # 已成定局的选项：贴着 0.001 / 0.999 报价、量小
            b = 0.001 if x <= 0.0 else 0.998
            set_level(l.tokens[0], "BUY", b, 100)
            set_level(l.tokens[0], "SELL", b + 0.001, 100)
            continue
        set_level(l.tokens[0], "BUY", round(x - SPREAD, 4), 500)
        set_level(l.tokens[0], "SELL", round(x + SPREAD, 4), 500)


price_all(V)


def book_msg(t):
    return {"event_type": "book", "asset_id": t, "market": "0x", "timestamp": str(int(time.time() * 1000)),
            "bids": [{"price": str(p), "size": str(s)} for p, s in sorted(BOOK[t]["bids"].items())],
            "asks": [{"price": str(p), "size": str(s)} for p, s in sorted(BOOK[t]["asks"].items(), reverse=True)]}


ST = {"phase": 1, "subs": [], "conns": set(), "t0": None}
LOCK = threading.Lock()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/events":
            if q.get("slug") == [EV]:
                return self._send(200, [{"id": "1", "slug": EV, "title": f"LoL: {T} vs {F} (BO5) - Worlds Playoffs",
                                         "markets": markets(ST["phase"])}])
            return self._send(200, [])
        if u.path.startswith("/markets/"):
            return self._send(200, {"seconds_delay": 1, "minimum_tick_size": 0.01, "minimum_order_size": 5})
        if u.path == "/book":
            t = (q.get("token_id") or [""])[0]
            with LOCK:
                if t not in BOOK:
                    return self._send(404, {"error": "No orderbook exists for the requested token id"})
                return self._send(200, dict(book_msg(t), timestamp=str(int(time.time() * 1000))))
        return self._send(404, {})


async def ws_handler(ws, *_):
    sub = json.loads(await ws.recv())
    ST["subs"].append(sub)
    if ST["t0"] is None:
        ST["t0"] = time.time()
    ST["conns"].add(ws)
    try:
        with LOCK:
            await ws.send(json.dumps([book_msg(t) for t in sub["assets_ids"] if t in BOOK]))
        async for m in ws:
            if m == "PING":
                await ws.send("PONG")
    except websockets.ConnectionClosed:
        pass
    finally:
        ST["conns"].discard(ws)


async def broadcast(changes):
    msg = json.dumps({"event_type": "price_change", "market": "0x", "timestamp": str(int(time.time() * 1000)),
                      "price_changes": changes})
    for ws in list(ST["conns"]):
        try:
            await ws.send(msg)
        except Exception:
            pass


async def script():
    while ST["t0"] is None:
        await asyncio.sleep(0.02)
    at = lambda s: asyncio.sleep(max(0.0, ST["t0"] + s - time.time()))
    h15, h25 = LEG[("hcap", 1.5)], LEG[("hcap", 2.5)]
    a25 = round(V[h25.tokens[0]] + SPREAD, 4)
    await at(1.0)                                       # Gen.G 让 2.5 出现 0.40 买单（高于让 1.5 的卖价）：单调性错价
    with LOCK:
        ch = set_level(h25.tokens[0], "SELL", a25, 0) + set_level(h25.tokens[0], "SELL", 0.42, 100) \
            + set_level(h25.tokens[0], "BUY", 0.40, 100)
    await broadcast(ch)
    await at(2.5)                                       # 恢复
    with LOCK:
        ch = set_level(h25.tokens[0], "BUY", 0.40, 0) + set_level(h25.tokens[0], "SELL", 0.42, 0) \
            + set_level(h25.tokens[0], "SELL", a25, 500)
    await broadcast(ch)
    await at(3.2)                                       # 服务器断开全部连接
    for ws in list(ST["conns"]):
        await ws.close()
    await at(5.0)                                       # 第 1 局 BLG 胜：先按条件价格重新报价，再在 Gamma 上结算
    V2 = fair(g1="A")
    with LOCK:
        price_all(V2)
        snaps = [book_msg(t) for t in BOOK]
    for ws in list(ST["conns"]):
        await ws.send(json.dumps(snaps))
    ST["phase"] = 2
    await at(7.0)                                       # 全平台广播的无关新盘口：不应写入录制、不应触发刷新
    for ws in list(ST["conns"]):
        await ws.send(json.dumps({"event_type": "new_market", "slug": "btc-updown-15m-1", "market": "0xother",
                                  "question": "Bitcoin Up or Down", "assets_ids": ["x1", "x2"]}))
    await at(7.5)                                       # 静默改动（不推送）：只有 REST 抽查能发现
    g3 = LEG[("game", 3.0)].tokens[0]
    with LOCK:
        set_level(g3, "SELL", round(V2[g3] + SPREAD, 4), 77)
    while True:                                         # 平时的小变动，让连接保持有消息
        await asyncio.sleep(0.3)
        g2 = LEG[("game", 2.0)].tokens[0]
        with LOCK:
            ch = set_level(g2, "BUY", 0.01, int(time.time() * 10) % 50 + 1)
        await broadcast(ch)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def start_ws(port, ready):
    async def run():
        async with websockets.serve(ws_handler, "127.0.0.1", port):
            ready.set()
            await script()
    asyncio.run(run())


def args_for(out, hp, wp, secs, **kw):
    a = C.parse_args(["--event-slug", EV, "--out", out, "--gamma", f"http://127.0.0.1:{hp}",
                      "--clob", f"http://127.0.0.1:{hp}", "--market-ws", f"ws://127.0.0.1:{wp}",
                      "--hours", str(secs / 3600), "--no-notify", "--status-every", "2", "--resync", "3",
                      "--refresh", "1", "--min-gap-ms", "0"] + [x for k, v in kw.items() for x in (f"--{k}", str(v))])
    return a


def run_monitor(args):
    holder = {}
    orig = C.Monitor.finish

    def finish(self):
        holder["mon"] = self
        return orig(self)
    C.Monitor.finish = finish
    try:
        rc = asyncio.run(C.amain(args))
    finally:
        C.Monitor.finish = orig
    return rc, holder["mon"]


def main():
    # 1. 条件化情景
    m = S.Model(MT, known={1: "A"})
    assert len(m.main) == 10 and all(s.kind == "path" and s.games[0] == "A" for s in m.main), len(m.main)
    assert m.tail and all(len(s.games) >= 1 and s.games[0] == "A" for s in m.tail)
    assert S.Model(MT, known={1: "A", 2: "A", 3: "A", 4: "B"}).known == {}           # 不可能的组合：不条件化
    r0 = S.solve(S.Model(MT), {t: sorted(BOOK[t]["asks"].items()) for t in BOOK}, 0.05)
    assert r0.profit < 1e-6 and r0.unit_cost >= 1 - 1e-9, r0
    print("条件化情景：通过（第 1 局结算后保留 10 条比分走势，排除整场取消；公平价不误报）")

    hp, wp = free_port(), free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", hp), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    ready = threading.Event()
    threading.Thread(target=start_ws, args=(wp, ready), daemon=True).start()
    ready.wait(5)

    # 2. 完整流程
    d = tempfile.mkdtemp(prefix="c_mon_")
    out = os.path.join(d, "rec")
    rc, mon = run_monitor(args_for(out, hp, wp, 14.0))
    assert rc == 0
    c = mon.c
    rows = list(csv.DictReader(open(os.path.join(out, "live_episodes.csv"), encoding="utf-8")))
    assert len(rows) == 1 and 1.2 <= float(rows[0]["duration_s"]) <= 1.9, rows
    assert float(rows[0]["max_profit_usd"]) > 1.0 and float(rows[0]["abandon_worst_pnl_usd"]) >= -1e-6, rows
    assert c["reconnects"] >= 1 and c["bba_bad"] == 0 and c["bba_ok"] > 20, c
    assert c["rest_bad"] >= 1 and c["rest_ok"] > 10, c
    g3 = LEG[("game", 3.0)].tokens[0]
    assert mon.books.asks[g3] == {round(fair(g1="A")[g3] + SPREAD, 4): 77.0}, mon.books.asks[g3]     # 已按 REST 纠正
    g1 = LEG[("game", 1.0)]
    assert mon.known == {1: "A"} and set(g1.tokens) <= mon.closed_tokens, (mon.known, mon.closed_tokens)
    assert len(mon.mt.legs) == 10 and len(mon.model.main) == 10
    g5 = LEG[("game", 5.0)]
    assert set(g5.tokens) <= set(ST["subs"][-1]["assets_ids"]) and len(ST["subs"]) >= 2, len(ST["subs"])
    assert not (mon.books.suspect - mon.closed_tokens), mon.books.suspect
    assert c["other_markets"] == 1 and "btc-updown" not in open(os.path.join(out, "pm_market.jsonl")).read(), c
    ev = [json.loads(x) for x in open(os.path.join(out, "eval.jsonl"))]
    assert sum(e["opp"] for e in ev) >= 1 and ev[-1]["priced"] == 18, ev[-1]       # 10 盘口 20 选项，第 1 局 2 个已关闭
    meta = json.load(open(os.path.join(out, "meta_start.json")))
    assert any(m["slug"] == f"{EV}-game5" for m in meta["markets"]) and meta["markets"][0].get("clob")
    eps = [json.loads(x) for x in open(os.path.join(out, "episodes.jsonl"))]
    assert len(eps) == 1
    log = [json.loads(x)["kind"] for x in open(os.path.join(out, "log.jsonl"))]
    assert {"known", "new_markets", "rest_mismatch", "closed", "status"} <= set(log), set(log)
    print(f"完整流程：通过（1 段机会 {float(rows[0]['duration_s']):.2f} 秒、利润 ${float(rows[0]['max_profit_usd']):.2f}；"
          f"重连 {c['reconnects']} 次；最优价核对 {c['bba_ok']}/{c['bba_bad']}；REST 抽查纠正 {c['rest_bad']} 次；"
          f"第 1 局结算后收窄情景、第 5 局上架后重新订阅）")

    # 3. 录制可被 replay 复现
    assert S.main(["replay", out]) == 0
    rr = list(csv.DictReader(open(os.path.join(out, "c_scan_episodes.csv"), encoding="utf-8")))
    assert len(rr) == 1 and abs(float(rr[0]["duration_s"]) - float(rows[0]["duration_s"])) < 0.3, rr
    print("录制回放：通过（replay 复现同一段机会）")

    # 4. WebSocket 不可用 → REST 轮询
    out2 = os.path.join(d, "rest")
    rc, mon = run_monitor(args_for(out2, hp, free_port(), 4.0, **{"fallback-after": 1, "interval": 0.5}))
    assert rc == 0 and mon.mode == "REST" and mon.c["rest_polls"] >= 2 and mon.c["evals"] >= 1, mon.c
    ev = [json.loads(x) for x in open(os.path.join(out2, "eval.jsonl"))]
    assert ev[-1]["priced"] == 18 and ev[-1]["unit_cost"] is not None and not ev[-1]["opp"], ev[-1]
    print("REST 后备：通过（WebSocket 连不上 1 秒后改为轮询，照常评估）")
    httpd.shutdown()
    shutil.rmtree(d)
    print("监控测试全部通过")


if __name__ == "__main__":
    main()
