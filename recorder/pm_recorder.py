#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pm_recorder.py · 只读行情与比分记录器（不下单，不需要任何 API key）

记录内容（每条都带本机接收时间 recv_ms，Unix 毫秒）：
  pm_market.jsonl  Polymarket CLOB market 频道原始消息：book / price_change /
                   last_trade_price / best_bid_ask 等，消息里的 timestamp 是交易所毫秒时间
  pm_sports.jsonl  Polymarket sports 频道比分推送（消息里没有交易所时间戳）
  nba_pbp.jsonl    可选：NBA 公开逐回合 JSON 里新出现、被修改或消失的动作
  clock.jsonl      本机时钟相对 NTP 的偏差，每 5 分钟一次（offset_ms > 0 表示本机慢）
  log.jsonl        连接、断线、重连、HTTP 状态
  meta_start.json / meta_end.json  盘口清单、token、seconds_delay、开赛时间

用法：
  python3 -m pip install websockets
  # 出门前先检查（约 15 秒）：
  python3 pm_recorder.py --event-slug <Polymarket 赛事网址最后一段> --nba-game-id <10 位数字> --check
  # 正式记录：
  python3 pm_recorder.py --event-slug <...> --nba-game-id <...> --hours 4
  macOS 防止睡眠：在命令前加  caffeinate -i
  Ctrl+C 随时停止，已写入的数据不会丢。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import random
import signal
import socket
import ssl
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

try:
    import websockets
except ImportError:  # pragma: no cover
    sys.exit("缺少依赖 websockets：请先运行  python3 -m pip install websockets")

VERSION = "0.1.2"

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:  # 没装 certifi 就用系统证书
    SSL_CTX = ssl.create_default_context()
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
MARKET_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
SPORTS_WS = "wss://sports-api.polymarket.com/ws"
NBA_PBP = "https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{gid}.json"
NBA_SCOREBOARD = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
# 全赛季赛程（约 7MB）。todaysScoreboard 白天仍停在前一天（11/10 美东 11:25 实测 gameDate=2026-11-09），
# 查不到时用它按美东日期找比赛编号
NBA_SCHEDULE = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
NBA_HEADERS = {"Referer": "https://www.nba.com/", "Origin": "https://www.nba.com"}
UA = "Mozilla/5.0 (read-only research recorder)"

ASSETS_PER_CONN = 100          # 每条 market 连接订阅的 token 数上限（官方未公布上限，保守取值）
SILENCE_RECONNECT_S = 30       # 这么久没有任何消息（含 PONG / ping）就主动重连
SPORTS_UNFILTERED_SAMPLE = 200 # 开了 --sports-filter 时，前 200 条不匹配的消息仍保留作格式样本
CLOB_FIELDS = ("seconds_delay", "game_start_time", "accepting_orders", "accepting_order_timestamp",
               "minimum_tick_size", "minimum_order_size", "neg_risk", "active", "closed", "end_date_iso")


# ---------------------------------------------------------------- 工具

def now_ms() -> int:
    return time.time_ns() // 1_000_000


def utc_iso(ms: int | None = None) -> str:
    ms = now_ms() if ms is None else ms
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="milliseconds")


def stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


class Jsonl:
    """逐行写入、行缓冲落盘：进程被杀最多丢最后一行。"""

    def __init__(self, path: str):
        self.path = path
        self.f = open(path, "a", encoding="utf-8", buffering=1)
        self.n = 0

    def write(self, obj: dict) -> None:
        self.f.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.n += 1

    def close(self) -> None:
        try:
            self.f.close()
        except Exception:
            pass


def ssl_kw(url: str) -> dict:
    return {"ssl": SSL_CTX} if url.startswith("wss://") else {}


def http_get(url: str, timeout: float = 10.0, headers: dict | None = None, etag: str | None = None):
    """返回 (status, body_bytes, headers_lowercase)。304 / 4xx / 5xx 不抛异常。"""
    h = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        h.update(headers)
    if etag:
        h["If-None-Match"] = etag
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
            return r.status, r.read(), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        hdrs = {k.lower(): v for k, v in e.headers.items()} if e.headers else {}
        return e.code, b"", hdrs


def http_json(url: str, headers: dict | None = None):
    status, body, _ = http_get(url, headers=headers)
    if status != 200:
        raise RuntimeError(f"HTTP {status}: {url}")
    return json.loads(body.decode("utf-8"))


def _json_list(v) -> list:
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            x = json.loads(v)
            return x if isinstance(x, list) else []
        except Exception:
            return []
    return []


# ---------------------------------------------------------------- Polymarket 元数据

def _market_row(m: dict) -> dict:
    return {
        "question": m.get("question"),
        "slug": m.get("slug"),
        "conditionId": m.get("conditionId"),
        "gamma_id": m.get("id"),
        "outcomes": _json_list(m.get("outcomes")),
        "token_ids": [str(t) for t in _json_list(m.get("clobTokenIds"))],
        "active": m.get("active"),
        "closed": m.get("closed"),
        # 以下字段供扫描器核对盘口识别与结算规则；接口没有时为 null
        "feesEnabled": m.get("feesEnabled"),
        "sportsMarketType": m.get("sportsMarketType"),
        "groupItemTitle": m.get("groupItemTitle"),
        "line": m.get("line"),
        "gameStartTime": m.get("gameStartTime"),
        "description": m.get("description"),
    }


def resolve_event(gamma: str, slug: str) -> tuple[dict, list[dict]]:
    """赛事 slug → 赛事信息 + 全部盘口（含 token）。也接受单个盘口的 slug。"""
    data = http_json(f"{gamma}/events?slug={urllib.parse.quote(slug)}")
    events = data if isinstance(data, list) else (data.get("data") or data.get("events") or [data])
    events = [e for e in events if isinstance(e, dict) and e.get("markets")]
    if events:
        ev = events[0]
        info = {k: ev.get(k) for k in ("id", "slug", "title", "startDate", "endDate", "gameStartTime", "negRisk")
                if k in ev}
        return info, [_market_row(m) for m in ev.get("markets") or []]
    data = http_json(f"{gamma}/markets?slug={urllib.parse.quote(slug)}")
    rows = data if isinstance(data, list) else (data.get("data") or [])
    rows = [m for m in rows if isinstance(m, dict)]
    if not rows:
        raise SystemExit(f"Gamma 没找到 slug = {slug!r}。请复制 Polymarket 赛事页网址的最后一段，例如 nba-bos-phi-2026-11-10。")
    return {"slug": slug, "note": "按盘口 slug 解析"}, [_market_row(m) for m in rows]


def clob_info(clob: str, condition_id: str) -> dict:
    try:
        d = http_json(f"{clob}/markets/{condition_id}")
        return {k: d.get(k) for k in CLOB_FIELDS if k in d}
    except Exception as e:
        return {"error": repr(e)}


def find_nba_game(url: str, teams: str, schedule_url: str | None = None, date_est: str | None = None) -> str | None:
    """先查今日比分板；没有再查全赛季赛程里美东日期 date_est（默认今天）的比赛。"""
    want = {t.strip().upper() for t in teams.split(",") if t.strip()}
    if not want:
        return None
    err = None
    try:
        d = http_json(url, headers=NBA_HEADERS)
        for g in (d.get("scoreboard") or {}).get("games") or []:
            codes = {str((g.get("homeTeam") or {}).get("teamTricode", "")).upper(),
                     str((g.get("awayTeam") or {}).get("teamTricode", "")).upper()}
            if want <= codes:
                return str(g.get("gameId"))
    except Exception as e:
        err = e
    if schedule_url:
        if not date_est:
            try:
                from zoneinfo import ZoneInfo
                date_est = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
            except Exception:  # 没有时区库：按 UTC−5 近似
                date_est = datetime.fromtimestamp(time.time() - 5 * 3600, tz=timezone.utc).strftime("%Y-%m-%d")
        status, body, _ = http_get(schedule_url, timeout=30.0, headers=NBA_HEADERS)
        if status == 200:
            sched = json.loads(body.decode("utf-8")).get("leagueSchedule") or {}
            for gd in sched.get("gameDates") or []:
                for g in gd.get("games") or []:
                    if not str(g.get("gameDateEst") or "").startswith(date_est):
                        continue
                    codes = {str((g.get("homeTeam") or {}).get("teamTricode", "")).upper(),
                             str((g.get("awayTeam") or {}).get("teamTricode", "")).upper()}
                    if want <= codes:
                        return str(g.get("gameId"))
    if err:
        raise err
    return None


# ---------------------------------------------------------------- NTP

NTP_DELTA = 2208988800  # 1900-01-01 到 1970-01-01 的秒数


def sntp_offset_ms(host: str, timeout: float = 3.0) -> tuple[float, float]:
    """返回 (offset_ms, rtt_ms)。offset_ms > 0 表示本机时钟比 NTP 慢。"""
    pkt = b"\x1b" + 47 * b"\0"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        t0 = time.time()
        s.sendto(pkt, (host, 123))
        data, _ = s.recvfrom(48)
        t3 = time.time()
    if len(data) < 48:
        raise RuntimeError("NTP 回包太短")

    def ts(off: int) -> float:
        sec, frac = struct.unpack("!II", data[off:off + 8])
        return sec - NTP_DELTA + frac / 2 ** 32

    t1, t2 = ts(32), ts(40)
    return ((t1 - t0) + (t2 - t3)) / 2 * 1000, ((t3 - t0) - (t2 - t1)) * 1000


# ---------------------------------------------------------------- 记录器

class Recorder:
    def __init__(self, args, outdir: str):
        self.args = args
        self.outdir = outdir
        self.w = {n: Jsonl(os.path.join(outdir, f"{n}.jsonl"))
                  for n in ("pm_market", "pm_sports", "nba_pbp", "clock", "log")}
        self.last_rx: dict[str, int] = {}
        self.counts = {"pm_market": 0, "pm_sports": 0, "pm_sports_skipped": 0,
                       "nba_changes": 0, "reconnects": 0, "pongs_sent": 0}
        self.nba_status: int | None = None
        self.nba_last_body: bytes | None = None

    def log(self, src: str, kind: str, **kw) -> None:
        self.w["log"].write({"recv_ms": now_ms(), "src": src, "kind": kind, **kw})
        detail = kw.get("err") or kw.get("info") or ""
        print(f"[{stamp()}] {src} {kind} {detail}".rstrip(), flush=True)

    async def _watchdog(self, ws, src: str, send: str | None, every: float) -> None:
        """send 不为空时定期发应用层心跳；长时间静默则关闭连接触发重连。"""
        while True:
            await asyncio.sleep(every)
            if send:
                try:
                    await ws.send(send)
                except Exception:
                    return
            if now_ms() - self.last_rx.get(src, now_ms()) > SILENCE_RECONNECT_S * 1000:
                self.log(src, "silent", info=f"{SILENCE_RECONNECT_S} 秒无消息，主动重连")
                await ws.close()
                return

    async def market_conn(self, idx: int, asset_ids: list[str]) -> None:
        src = f"pm_market#{idx}"
        backoff = 1.0
        while True:
            try:
                async with websockets.connect(self.args.market_ws, max_size=None, ping_interval=None,
                                              open_timeout=15, close_timeout=3, **ssl_kw(self.args.market_ws)) as ws:
                    await ws.send(json.dumps({"assets_ids": asset_ids, "type": "market",
                                              "custom_feature_enabled": True}))
                    self.log(src, "connected", info=f"{len(asset_ids)} 个 token")
                    backoff = 1.0
                    self.last_rx[src] = now_ms()
                    hb = asyncio.create_task(self._watchdog(ws, src, send="PING", every=10))
                    try:
                        async for raw in ws:
                            t = now_ms()
                            self.last_rx[src] = t
                            if isinstance(raw, (bytes, bytearray)):
                                raw = raw.decode("utf-8", "replace")
                            if raw == "PONG":
                                continue
                            self.w["pm_market"].write({"recv_ms": t, "conn": idx, "raw": raw})
                            self.counts["pm_market"] += 1
                    finally:
                        hb.cancel()
                self.log(src, "closed")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.log(src, "error", err=repr(e))
            self.counts["reconnects"] += 1
            await asyncio.sleep(backoff + random.random())
            backoff = min(backoff * 2, 30.0)

    async def sports_conn(self) -> None:
        src = "pm_sports"
        backoff = 1.0
        filt = [f.strip().lower() for f in (self.args.sports_filter or "").split(",") if f.strip()]
        sample_left = SPORTS_UNFILTERED_SAMPLE
        while True:
            try:
                async with websockets.connect(self.args.sports_ws, max_size=None, ping_interval=None,
                                              open_timeout=15, close_timeout=3, **ssl_kw(self.args.sports_ws)) as ws:
                    self.log(src, "connected")
                    backoff = 1.0
                    self.last_rx[src] = now_ms()
                    hb = asyncio.create_task(self._watchdog(ws, src, send=None, every=5))
                    try:
                        async for raw in ws:
                            t = now_ms()
                            self.last_rx[src] = t
                            if isinstance(raw, (bytes, bytearray)):
                                raw = raw.decode("utf-8", "replace")
                            if raw.strip().lower() == "ping":      # 服务器每 5 秒发 ping，需回 pong
                                await ws.send("pong")
                                self.counts["pongs_sent"] += 1
                                continue
                            rec = {"recv_ms": t, "raw": raw}
                            if filt and not any(f in raw.lower() for f in filt):
                                if sample_left <= 0:
                                    self.counts["pm_sports_skipped"] += 1
                                    continue
                                sample_left -= 1
                                rec["sample"] = True
                            self.w["pm_sports"].write(rec)
                            self.counts["pm_sports"] += 1
                    finally:
                        hb.cancel()
                self.log(src, "closed")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.log(src, "error", err=repr(e))
            self.counts["reconnects"] += 1
            await asyncio.sleep(backoff + random.random())
            backoff = min(backoff * 2, 30.0)

    async def nba_poller(self, gid: str) -> None:
        src = "nba_pbp"
        url = self.args.nba_pbp_url.format(gid=gid)
        seen: dict = {}
        etag = None
        last_raw_dump = 0
        while True:
            t0 = now_ms()
            try:
                status, body, h = await asyncio.to_thread(http_get, url, 8.0, NBA_HEADERS, etag)
                t1 = now_ms()
                ok_now, ok_before = status in (200, 304), self.nba_status in (200, 304)
                if self.nba_status is None or ok_now != ok_before or (not ok_now and status != self.nba_status):
                    self.log(src, "http", info=f"HTTP {status}")
                self.nba_status = status
                if status == 200:
                    etag = h.get("etag") or etag
                    self.nba_last_body = body
                    hdr = {k: h[k] for k in ("age", "last-modified", "date", "etag") if k in h}
                    try:
                        data = json.loads(body.decode("utf-8"))
                        actions = (data.get("game") or {}).get("actions")
                    except Exception:
                        actions = None
                    if not isinstance(actions, list):
                        if t1 - last_raw_dump > 30_000:   # 结构不认识：每 30 秒存一次原文
                            self.w["nba_pbp"].write({"recv_ms": t1, "req_ms": t0, "kind": "raw", "hdr": hdr,
                                                     "raw": body.decode("utf-8", "replace")[:1_000_000]})
                            last_raw_dump = t1
                    else:
                        present = set()
                        for a in actions:
                            if not isinstance(a, dict):
                                continue
                            key = a.get("actionNumber", a.get("orderNumber"))
                            present.add(key)
                            digest = hashlib.sha1(json.dumps(a, sort_keys=True).encode()).hexdigest()[:16]
                            if seen.get(key) != digest:
                                self.w["nba_pbp"].write({"recv_ms": t1, "req_ms": t0, "kind": "action",
                                                         "first": key not in seen, "hdr": hdr, "action": a})
                                seen[key] = digest
                                self.counts["nba_changes"] += 1
                        for key in [k for k in seen if k not in present]:
                            self.w["nba_pbp"].write({"recv_ms": t1, "req_ms": t0, "kind": "gone",
                                                     "actionNumber": key, "hdr": hdr})
                            del seen[key]
                            self.counts["nba_changes"] += 1
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.log(src, "error", err=repr(e))
            wait = self.args.nba_interval if self.nba_status in (200, 304) else 5.0
            await asyncio.sleep(max(0.05, wait - (now_ms() - t0) / 1000))

    async def clock_task(self) -> None:
        while True:
            try:
                off, rtt = await asyncio.to_thread(sntp_offset_ms, self.args.ntp_host)
                self.w["clock"].write({"recv_ms": now_ms(), "ntp_host": self.args.ntp_host,
                                       "offset_ms": round(off, 2), "rtt_ms": round(rtt, 2)})
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.w["clock"].write({"recv_ms": now_ms(), "ntp_host": self.args.ntp_host, "error": repr(e)})
            await asyncio.sleep(300)

    def status_line(self) -> str:
        c = self.counts
        ages = " ".join(f"{k}:{(now_ms() - v) / 1000:.0f}s" for k, v in sorted(self.last_rx.items()))
        return (f"盘口消息 {c['pm_market']} · 比分 {c['pm_sports']}（滤掉 {c['pm_sports_skipped']}）"
                f" · NBA 变动 {c['nba_changes']} · 重连 {c['reconnects']} · 距上条 {ages or '-'}")

    async def status_task(self, every: float) -> None:
        while True:
            await asyncio.sleep(every)
            print(f"[{stamp()}] {self.status_line()}", flush=True)

    def close(self) -> None:
        for w in self.w.values():
            w.close()


# ---------------------------------------------------------------- 主流程

def write_json(path: str, obj) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


async def amain(args) -> int:
    label = args.event_slug or "tokens"
    outdir = args.out or f"rec_{label}_{datetime.now():%Y%m%d-%H%M%S}"
    os.makedirs(outdir, exist_ok=True)

    event_info, markets = {}, []
    if args.event_slug:
        event_info, markets = await asyncio.to_thread(resolve_event, args.gamma, args.event_slug)
    sem = asyncio.Semaphore(12)

    async def fill_clob(m):
        async with sem:
            m["clob"] = await asyncio.to_thread(clob_info, args.clob, m["conditionId"])

    if markets:
        print(f"[{stamp()}] 读取 {len(markets)} 个盘口的撮合设置…", flush=True)
    await asyncio.gather(*(fill_clob(m) for m in markets if m.get("conditionId")))
    token_ids = list(dict.fromkeys([t for m in markets for t in m["token_ids"]] + list(args.token_ids or [])))
    if not token_ids and not args.no_market:
        raise SystemExit("没有可订阅的 token：请给 --event-slug 或 --token-ids")

    gid = args.nba_game_id
    if not gid and args.nba_teams:
        try:
            gid = await asyncio.to_thread(find_nba_game, args.nba_scoreboard_url, args.nba_teams,
                                         args.nba_schedule_url or None)
        except Exception as e:
            print(f"[{stamp()}] 自动查找 NBA 比赛失败：{e!r}；可改用 --nba-game-id", flush=True)
        if not gid:
            print(f"[{stamp()}] 今日赛程里没找到 {args.nba_teams}，NBA 逐回合不记录", flush=True)

    meta = {
        "recorder": VERSION, "started_utc": utc_iso(), "started_ms": now_ms(),
        "host": platform.platform(), "python": sys.version.split()[0],
        "websockets": getattr(websockets, "__version__", "?"),
        "args": {k: v for k, v in vars(args).items()},
        "event": event_info, "markets": markets, "token_count": len(token_ids), "nba_game_id": gid,
    }
    write_json(os.path.join(outdir, "meta_start.json"), meta)

    delays = sorted({str((m.get("clob") or {}).get("seconds_delay")) for m in markets})
    print(f"[{stamp()}] 输出目录：{os.path.abspath(outdir)}", flush=True)
    print(f"[{stamp()}] 赛事：{event_info.get('title') or event_info.get('slug') or '-'}"
          f" · 盘口 {len(markets)} 个 · token {len(token_ids)} 个 · seconds_delay 取值 {', '.join(delays) or '-'}",
          flush=True)
    for m in markets[:12]:
        sd = (m.get("clob") or {}).get("seconds_delay")
        print(f"    - {m.get('question')}  [seconds_delay={sd}]", flush=True)
    if len(markets) > 12:
        print(f"    … 另有 {len(markets) - 12} 个盘口，见 meta_start.json", flush=True)

    rec = Recorder(args, outdir)
    tasks: list[asyncio.Task] = []
    if not args.no_market:
        for i in range(0, len(token_ids), ASSETS_PER_CONN):
            tasks.append(asyncio.create_task(rec.market_conn(i // ASSETS_PER_CONN, token_ids[i:i + ASSETS_PER_CONN])))
    if not args.no_sports:
        tasks.append(asyncio.create_task(rec.sports_conn()))
    if gid:
        tasks.append(asyncio.create_task(rec.nba_poller(gid)))
    if not args.no_ntp:
        tasks.append(asyncio.create_task(rec.clock_task()))
    tasks.append(asyncio.create_task(rec.status_task(5 if args.check else 30)))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError, ValueError):
            pass  # Windows：Ctrl+C 由 asyncio.run 取消主任务，下面的 finally 照样执行

    duration = 15.0 if args.check else args.hours * 3600
    print(f"[{stamp()}] 开始记录，{'检查模式 15 秒' if args.check else f'最长 {args.hours:g} 小时'}；Ctrl+C 停止",
          flush=True)
    try:
        await asyncio.wait_for(stop.wait(), timeout=duration)
    except asyncio.TimeoutError:
        pass
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        end = {"ended_utc": utc_iso(), "ended_ms": now_ms(), "counts": rec.counts, "nba_last_http": rec.nba_status,
               "markets_end": []}
        if not args.check:
            for m in markets:
                if m.get("conditionId"):
                    end["markets_end"].append({"conditionId": m["conditionId"],
                                               "clob": clob_info(args.clob, m["conditionId"])})
        write_json(os.path.join(outdir, "meta_end.json"), end)
        if rec.nba_last_body:
            with open(os.path.join(outdir, "nba_pbp_final.json"), "wb") as f:
                f.write(rec.nba_last_body)
        rec.close()
        print(f"[{stamp()}] 已停止。{rec.status_line()}", flush=True)
        if args.check:
            c = rec.counts
            ok_market = c["pm_market"] > 0 or args.no_market
            ok_sports = c["pm_sports"] > 0 or args.no_sports
            if not gid:
                nba_msg = "未启用（没给比赛编号，或今日赛程里还没有这场）"
            elif rec.nba_status in (200, 304):
                nba_msg = "正常"
            else:
                nba_msg = f"HTTP {rec.nba_status}（开赛前可能还没有文件）"
            print("检查结果：" + "；".join([
                f"盘口 {'正常' if ok_market else '15 秒内没收到消息'}",
                f"比分推送 {'正常' if ok_sports else '15 秒内没收到消息（赛前可能本来就少）'}",
                f"NBA 逐回合 {nba_msg}",
            ]), flush=True)
        print(f"[{stamp()}] 数据在：{os.path.abspath(outdir)}", flush=True)
    return 0


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="只读记录 Polymarket 盘口、比分推送与 NBA 逐回合数据（不下单）")
    p.add_argument("--event-slug", help="Polymarket 赛事页网址的最后一段，例如 nba-bos-phi-2026-11-10")
    p.add_argument("--token-ids", nargs="*", help="额外订阅的 token id")
    p.add_argument("--nba-game-id", help="NBA 比赛编号：nba.com 比赛页网址末尾的 10 位数字")
    p.add_argument("--nba-teams", help="不知道编号时按今日赛程查，如 PHI,BOS")
    p.add_argument("--nba-interval", type=float, default=1.0, help="逐回合轮询间隔秒数，默认 1")
    p.add_argument("--sports-filter", help="只保留含这些关键词的比分消息，逗号分隔，如 76ers,Celtics")
    p.add_argument("--hours", type=float, default=4.0, help="最长记录小时数，默认 4")
    p.add_argument("--check", action="store_true", help="只跑 15 秒，检查各数据源是否通")
    p.add_argument("--out", help="输出目录，默认 rec_<slug>_<时间>")
    p.add_argument("--no-market", action="store_true", help="不记录盘口")
    p.add_argument("--no-sports", action="store_true", help="不记录比分推送")
    p.add_argument("--no-ntp", action="store_true", help="不做 NTP 对时")
    p.add_argument("--ntp-host", default="pool.ntp.org")
    # 以下用于测试或接口变更时覆盖地址
    p.add_argument("--gamma", default=GAMMA)
    p.add_argument("--clob", default=CLOB)
    p.add_argument("--market-ws", default=MARKET_WS)
    p.add_argument("--sports-ws", default=SPORTS_WS)
    p.add_argument("--nba-pbp-url", default=NBA_PBP, help="含 {gid} 占位符")
    p.add_argument("--nba-scoreboard-url", default=NBA_SCOREBOARD)
    p.add_argument("--nba-schedule-url", default=NBA_SCHEDULE, help="比分板查不到时查的全赛季赛程；给空字符串则不查")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if not args.event_slug and not args.token_ids and not args.no_market:
        print("需要 --event-slug（或 --token-ids）。示例见文件开头说明。", file=sys.stderr)
        return 2
    try:
        return asyncio.run(amain(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
