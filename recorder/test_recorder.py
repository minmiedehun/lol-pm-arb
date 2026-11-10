#!/usr/bin/env python3
"""用本地模拟服务器测试 pm_recorder.py：盘口 WS（含断线重连与 PING/PONG）、比分 WS（ping/pong 与过滤）、
Gamma/CLOB 元数据、NBA 逐回合（新增、修改、消失、ETag）、SNTP 偏差符号。"""
import asyncio
import hashlib
import json
import os
import shutil
import socket
import struct
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import websockets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pm_recorder  # noqa: E402

T0 = time.time()
STATE = {"market_conns": 0, "market_subs": [], "pings": 0, "pongs": 0, "sports_conns": 0, "nba_304": 0}


# ---------------- HTTP: Gamma / CLOB / NBA
def pbp_body():
    el = time.time() - T0
    n = min(12, 1 + int(el / 0.5))
    actions = []
    for i in range(1, n + 1):
        if i == 3 and el > 4.0:      # 第 3 条在 4 秒后被删除
            continue
        desc = f"action {i}"
        if i == 2 and el > 3.0:      # 第 2 条在 3 秒后被修改
            desc = "action 2 (edited)"
        actions.append({"actionNumber": i, "clock": "PT11M00.00S", "period": 1,
                        "timeActual": "2026-11-11T01:0%d:00.0Z" % (i % 10), "description": desc})
    return json.dumps({"meta": {"version": 1}, "game": {"gameId": "0022600123", "actions": actions}}).encode()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj=None, raw=None, headers=None):
        body = raw if raw is not None else (json.dumps(obj).encode() if obj is not None else b"")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/events":
            if q.get("slug") == ["nba-test"]:
                return self._send(200, [{"id": "1", "slug": "nba-test", "title": "Celtics vs. 76ers", "markets": [
                    {"id": "10", "question": "Celtics vs. 76ers", "slug": "m1", "conditionId": "0xaaa",
                     "outcomes": "[\"Celtics\", \"76ers\"]", "clobTokenIds": "[\"111\", \"222\"]"},
                    {"id": "11", "question": "Spread: 76ers (-3.5)", "slug": "m2", "conditionId": "0xbbb",
                     "outcomes": "[\"76ers\", \"Celtics\"]", "clobTokenIds": "[\"333\", \"444\"]"}]}])
            return self._send(200, [])
        if u.path == "/markets/0xaaa":
            return self._send(200, {"seconds_delay": 0, "game_start_time": "2026-11-11T01:00:00Z", "neg_risk": False})
        if u.path == "/markets/0xbbb":
            return self._send(200, {"seconds_delay": 3, "game_start_time": "2026-11-11T01:00:00Z"})
        if u.path == "/scoreboard.json":
            return self._send(200, {"scoreboard": {"games": [
                {"gameId": "0022600999", "homeTeam": {"teamTricode": "NYK"}, "awayTeam": {"teamTricode": "MIA"}},
                {"gameId": "0022600123", "homeTeam": {"teamTricode": "PHI"}, "awayTeam": {"teamTricode": "BOS"}}]}})
        if u.path == "/pbp/0022600123.json":
            body = pbp_body()
            etag = '"' + hashlib.md5(body).hexdigest() + '"'
            if self.headers.get("If-None-Match") == etag:
                STATE["nba_304"] += 1
                return self._send(304, raw=b"", headers={"ETag": etag})
            return self._send(200, raw=body, headers={"ETag": etag, "Age": "0"})
        return self._send(404, {"error": "not found"})


# ---------------- WebSocket: market / sports
async def market_handler(ws, *_):
    STATE["market_conns"] += 1
    conn_no = STATE["market_conns"]
    sub = json.loads(await ws.recv())
    STATE["market_subs"].append(sub)
    assert sub["type"] == "market" and sub["assets_ids"], sub
    ts = lambda: str(int(time.time() * 1000))
    await ws.send(json.dumps([{"event_type": "book", "asset_id": a, "market": "0x", "timestamp": ts(),
                               "bids": [{"price": "0.48", "size": "100"}], "asks": [{"price": "0.52", "size": "90"}]}
                              for a in sub["assets_ids"]]))

    async def reader():
        async for m in ws:
            if m == "PING":
                STATE["pings"] += 1
                await ws.send("PONG")

    r = asyncio.create_task(reader())
    start = time.time()
    try:
        while True:
            await asyncio.sleep(0.1)
            await ws.send(json.dumps({"event_type": "price_change", "market": "0x", "timestamp": ts(),
                                      "price_changes": [{"asset_id": sub["assets_ids"][0], "price": "0.49",
                                                         "size": "10", "side": "BUY", "best_bid": "0.49",
                                                         "best_ask": "0.52"}]}))
            if conn_no == 1 and time.time() - start > 1.2:   # 第一条连接 1.2 秒后被服务器断开
                await ws.close()
                return
    except websockets.ConnectionClosed:
        pass
    finally:
        r.cancel()


async def sports_handler(ws, *_):
    STATE["sports_conns"] += 1
    last_pong = time.time()

    async def reader():
        nonlocal last_pong
        async for m in ws:
            if m == "pong":
                STATE["pongs"] += 1
                last_pong = time.time()

    r = asyncio.create_task(reader())
    i = 0
    try:
        while True:
            await asyncio.sleep(0.25)
            i += 1
            if i % 2 == 0:
                await ws.send("ping")
            if time.time() - last_pong > 3.0:
                await ws.close(code=4000, reason="no pong")
                return
            if i % 3 == 0:
                msg = {"gameId": 1, "leagueAbbreviation": "nba", "homeTeam": "76ers", "awayTeam": "Celtics",
                       "status": "InProgress", "score": f"{i}-{i - 1}", "period": "Q1", "live": True}
            else:
                msg = {"gameId": 2, "leagueAbbreviation": "nhl", "homeTeam": "Rangers", "awayTeam": "Devils",
                       "status": "InProgress", "score": "1-0", "period": "P2", "live": True}
            await ws.send(json.dumps(msg))
    except websockets.ConnectionClosed:
        pass
    finally:
        r.cancel()


def free_port(kind=socket.SOCK_STREAM):
    s = socket.socket(socket.AF_INET, kind)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def start_ws_servers(pm, ps, ready):
    async def run():
        async with websockets.serve(market_handler, "127.0.0.1", pm), \
                   websockets.serve(sports_handler, "127.0.0.1", ps):
            ready.set()
            await asyncio.Future()
    asyncio.run(run())


# ---------------- SNTP：模拟服务器时间比本机快 1.5 秒
def start_ntp(port, skew=1.5):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", port))

    def loop():
        while True:
            data, addr = s.recvfrom(48)
            t = time.time() + skew + pm_recorder.NTP_DELTA
            sec, frac = int(t), int((t - int(t)) * 2 ** 32)
            pkt = bytearray(48)
            pkt[0] = 0x24
            pkt[32:40] = struct.pack("!II", sec, frac)
            pkt[40:48] = struct.pack("!II", sec, frac)
            s.sendto(bytes(pkt), addr)
    threading.Thread(target=loop, daemon=True).start()


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def main():
    hp, pm, ps, np_ = free_port(), free_port(), free_port(), free_port(socket.SOCK_DGRAM)
    httpd = ThreadingHTTPServer(("127.0.0.1", hp), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    ready = threading.Event()
    threading.Thread(target=start_ws_servers, args=(pm, ps, ready), daemon=True).start()
    assert ready.wait(5)
    start_ntp(np_)

    # SNTP 符号：服务器快 1.5 秒 → offset ≈ +1500 ms（本机慢）
    pm_recorder_socket_port = np_
    orig = socket.socket.sendto

    def sendto(self, data, addr):
        if addr[1] == 123:
            addr = ("127.0.0.1", pm_recorder_socket_port)
        return orig(self, data, addr)
    socket.socket.sendto = sendto
    off, rtt = pm_recorder.sntp_offset_ms("127.0.0.1")
    socket.socket.sendto = orig
    assert 1400 < off < 1600, off
    print(f"SNTP 偏差符号正确：offset={off:.1f}ms rtt={rtt:.2f}ms")

    base = f"http://127.0.0.1:{hp}"
    assert pm_recorder.find_nba_game(base + "/scoreboard.json", "PHI,BOS") == "0022600123"

    out = tempfile.mkdtemp(prefix="rec_test_")
    pm_recorder.SPORTS_UNFILTERED_SAMPLE = 3
    rc = pm_recorder.main([
        "--event-slug", "nba-test", "--nba-teams", "PHI,BOS", "--sports-filter", "76ers,Celtics",
        "--hours", str(14 / 3600), "--gamma", base, "--clob", base,
        "--market-ws", f"ws://127.0.0.1:{pm}", "--sports-ws", f"ws://127.0.0.1:{ps}",
        "--nba-pbp-url", base + "/pbp/{gid}.json", "--nba-scoreboard-url", base + "/scoreboard.json",
        "--nba-interval", "0.2", "--no-ntp", "--out", out])
    assert rc == 0

    meta = json.load(open(os.path.join(out, "meta_start.json"), encoding="utf-8"))
    assert meta["token_count"] == 4 and meta["nba_game_id"] == "0022600123"
    assert [m["clob"]["seconds_delay"] for m in meta["markets"]] == [0, 3]

    mk = read_jsonl(os.path.join(out, "pm_market.jsonl"))
    logs = read_jsonl(os.path.join(out, "log.jsonl"))
    conns = [x for x in logs if x["src"].startswith("pm_market") and x["kind"] == "connected"]
    assert len(conns) >= 2, "应在服务器断开后重连"
    assert STATE["market_subs"][0]["assets_ids"] == ["111", "222", "333", "444"]
    assert STATE["market_subs"][0].get("custom_feature_enabled") is True
    books = [x for x in mk if x["raw"].startswith("[")]
    assert len(books) >= 2, "每次连接都应收到 book 快照"
    pcs = [json.loads(x["raw"]) for x in mk if not x["raw"].startswith("[")]
    assert all(p["event_type"] == "price_change" for p in pcs) and len(pcs) > 50
    lag = [x["recv_ms"] - int(json.loads(x["raw"])["timestamp"]) for x in mk if not x["raw"].startswith("[")]
    assert all(-5 <= v < 500 for v in lag), (min(lag), max(lag))
    assert STATE["pings"] >= 1, "应在 10 秒时发送 PING"
    assert not any(x["raw"] == "PONG" for x in mk), "PONG 不应写入数据"

    sp = read_jsonl(os.path.join(out, "pm_sports.jsonl"))
    kept = [json.loads(x["raw"]) for x in sp]
    samples = [x for x in sp if x.get("sample")]
    assert len(samples) == 3, len(samples)
    assert all(m["homeTeam"] == "76ers" for x, m in zip(sp, kept) if not x.get("sample"))
    assert not any(x["raw"] == "ping" for x in sp)
    assert STATE["pongs"] >= 10 and STATE["sports_conns"] == 1, STATE

    nb = read_jsonl(os.path.join(out, "nba_pbp.jsonl"))
    firsts = [x for x in nb if x.get("kind") == "action" and x["first"]]
    edits = [x for x in nb if x.get("kind") == "action" and not x["first"]]
    gone = [x for x in nb if x.get("kind") == "gone"]
    assert len(firsts) >= 10, len(firsts)
    assert any(e["action"]["description"].endswith("(edited)") for e in edits)
    assert any(g["actionNumber"] == 3 for g in gone)
    assert STATE["nba_304"] > 0, "ETag 未生效"
    assert os.path.exists(os.path.join(out, "nba_pbp_final.json"))
    end = json.load(open(os.path.join(out, "meta_end.json"), encoding="utf-8"))
    assert len(end["markets_end"]) == 2

    print(f"通过：盘口 {len(mk)} 条（重连 {len(conns) - 1} 次，PING {STATE['pings']} 次）；"
          f"比分 {len(sp)} 条（样本 {len(samples)}，pong {STATE['pongs']} 次）；"
          f"NBA 新增 {len(firsts)}、修改 {len(edits)}、消失 {len(gone)}，304 共 {STATE['nba_304']} 次")
    shutil.rmtree(out)


if __name__ == "__main__":
    main()
