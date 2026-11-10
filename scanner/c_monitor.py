#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
c_monitor.py · C 方案实时监控（一场 LoL 系列赛，Polymarket，只读：不下单、不签名、不需要任何密钥）

做什么
  订阅这场比赛所有赛果类盘口的 market WebSocket，用 book / price_change 在本地维护订单簿；
  每当某个选项的卖一价变化（或当前有机会）就用 lol_c_scan 的线性规划重算“锁定 $1 的最低成本”和可锁定利润。

可靠性
  - 应用层 PING 每 10 秒；30 秒无任何消息主动重连；断线指数退避重连。断线期间全部选项标记为“不可信”，
    重连后收到该选项的完整快照才重新参与计算。
  - 每条 price_change 自带该选项的 best_bid / best_ask，用来实时核对本地重建；对不上就把该选项标为不可信并立刻用 REST 快照修复。
  - 每 60 秒用 REST /book 抽查一次全部选项；与本地不一致就以 REST 快照为准，并把这份快照写进录制（回放时状态一致）。
  - WebSocket 连不上超过 20 秒，自动改为 REST 轮询（每 2 秒），连上后恢复。
  - 每 60 秒刷新一次 Gamma：盘口关闭的选项退出计算；单局正式结算后按结果收窄情景（排除不可能的比分走势）；
    新上架的赛果盘口（例如第 5 局胜负）自动加入并重新订阅。系列赛胜负结算后再跑 --linger 秒自动停止。

输出目录（默认 rec_c_<slug>_<时间>/，已在 .gitignore 里）
  meta_start.json     赛事与盘口清单（与 pm_recorder 同格式，含各盘口 seconds_delay），新盘口上架时更新
  pm_market.jsonl     原始 WebSocket 消息 + 注入的 REST 快照（conn = "rest"），可直接 `lol_c_scan.py replay <目录>` 复核
  eval.jsonl          每次评估：时间、锁定 $1 的最低成本、可锁定利润、是否机会、参与计算的选项数
  episodes.jsonl      机会段（结束时写入）；live_episodes.csv 同口径 CSV（与 replay 的 c_scan_episodes.csv 列相同）
  log.jsonl           连接、断线、一致性检查、盘口结算、状态行
  meta_end.json       结束时的统计

用法
  python3 scanner/c_monitor.py --event-slug lol-blg-gen-2026-11-14 --check          # 20 秒自检
  caffeinate -i python3 scanner/c_monitor.py --event-slug lol-blg-gen-2026-11-14 --hours 8
  Ctrl+C 随时停止，已写入的数据不会丢。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import random
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lol_c_scan as S  # noqa: E402

try:
    import websockets
except ImportError:  # pragma: no cover
    sys.exit("缺少依赖 websockets：请先运行  python3 -m pip install websockets")

VERSION = "1.0"
MARKET_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
UA = "Mozilla/5.0 (read-only research monitor)"
SILENCE_RECONNECT_S = 30
CLOB_FIELDS = ("seconds_delay", "game_start_time", "accepting_orders", "minimum_tick_size",
               "minimum_order_size", "neg_risk", "active", "closed")


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def utc_iso(ms: int | None = None) -> str:
    ms = now_ms() if ms is None else ms
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="milliseconds")


class Jsonl:
    """逐行写入、行缓冲：进程被杀最多丢最后一行。"""

    def __init__(self, path: str):
        self.f = open(path, "a", encoding="utf-8", buffering=1)
        self.n = 0

    def write(self, obj) -> None:
        self.f.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.n += 1

    def close(self) -> None:
        try:
            self.f.close()
        except Exception:
            pass


def http_get_json(url: str, timeout: float = 8.0):
    """返回 (status, obj)。4xx/5xx 不抛异常，obj 为 None。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, None


def fetch_event_raw(gamma: str, slug: str) -> tuple[dict, list[dict]]:
    """Gamma 原始赛事对象（保留 closed、outcomePrices 等结算字段）。"""
    q = urllib.parse.quote(slug)
    for url in (f"{gamma}/events?slug={q}", f"{gamma}/events?slug={q}&closed=true"):
        st, d = http_get_json(url, timeout=10.0)
        evs = S._as_list(d) if st == 200 else []
        if evs and evs[0].get("markets"):
            return evs[0], [m for m in evs[0]["markets"] if isinstance(m, dict)]
    raise RuntimeError(f"Gamma 没找到 {slug!r}")


def _f(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def osa_notify(title: str, text: str) -> None:
    """macOS 通知 + 提示音；其他系统或失败时静默。"""
    if platform.system() != "Darwin":
        return
    t = text.replace('"', "'")[:200]
    try:
        subprocess.Popen(["osascript", "-e", f'display notification "{t}" with title "{title}" sound name "Glass"'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


class Monitor:
    def __init__(self, args, outdir: str):
        self.args = args
        self.outdir = outdir
        self.w = {n: Jsonl(os.path.join(outdir, f"{n}.jsonl")) for n in ("pm_market", "eval", "episodes", "log")}
        self.books = S.PmBooks()
        self.ep = S.Episodes(args.min_profit)
        self.known: dict = {}               # 已正式结算的单局：{局号: 'A'/'B'}
        self.closed_tokens: set = set()     # 盘口已关闭的选项，不再参与计算
        self.last_ts: dict = {}             # 每个选项最近一条 WS 消息的交易所时间戳（毫秒）
        self.snap_since_connect: set = set()
        self.ws_up = False
        self.ws_down_since = now_ms()
        self.ws_up_since = 0
        self.gen = 0                        # 连接代数：每次连上、断开都加 1，用来丢弃跨越断线的 REST 快照
        self.ws_last_rx = 0
        self.ep_written = 0
        self.mode = "WS"
        self.dirty = asyncio.Event()
        self.resub = asyncio.Event()
        self.refresh_now = asyncio.Event()
        self.stop = asyncio.Event()
        self.heal: set = set()              # 需要立刻用 REST 快照修复的选项
        self.last_sig = None
        self.last_eval_ms = 0
        self.ml_closed_at: int | None = None
        self.pool = ThreadPoolExecutor(max_workers=12)
        self.c = dict(msgs=0, evals=0, reconnects=0, bba_ok=0, bba_bad=0, rest_ok=0, rest_bad=0, rest_skip=0,
                      rest_polls=0, bad_msgs=0, alerts=0, other_markets=0)
        self.mt: S.Match | None = None
        self.model: S.Model | None = None
        self.meta: dict = {}

    # ------------------------------------------------------------ 公用
    def log(self, kind: str, msg: str = "", quiet: bool = False, **kw) -> None:
        self.w["log"].write({"recv_ms": now_ms(), "kind": kind, "msg": msg, **kw})
        if not quiet:
            print(f"[{stamp()}] {msg or kind}", flush=True)

    def tokens(self) -> list[str]:
        return self.model.tokens() if self.model else []

    def excluded(self) -> set:
        return self.books.suspect | self.closed_tokens

    def write_meta(self) -> None:
        with open(os.path.join(self.outdir, "meta_start.json"), "w", encoding="utf-8") as f:
            json.dump(self.meta, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------ 盘口清单
    def load(self) -> None:
        ev, raw = fetch_event_raw(self.args.gamma, self.args.event_slug)
        info = {k: ev.get(k) for k in ("id", "slug", "title", "startDate", "endDate", "closed") if k in ev}
        markets = [S.norm_market(m) for m in raw]
        mt = S.build_match(info.get("slug") or self.args.event_slug, info.get("title") or "", markets, include_closed=True)
        if not mt:
            raise SystemExit("没识别出 LoL 系列赛盘口。先跑  lol_c_scan.py meta --event-slug ...  看识别结果。")
        clob = {}
        cids = [l.condition_id for l in mt.legs if l.condition_id]
        for cid, d in zip(cids, self.pool.map(lambda c: http_get_json(f"{self.args.clob}/markets/{c}"), cids)):
            st, obj = d
            clob[cid] = {k: obj.get(k) for k in CLOB_FIELDS if k in obj} if st == 200 and obj else {"http": st}
        for m in markets:
            if m.get("conditionId") in clob:
                m["clob"] = clob[m["conditionId"]]
        self.meta = {"monitor": VERSION, "started_utc": utc_iso(), "started_ms": now_ms(), "host": platform.platform(),
                     "python": sys.version.split()[0], "args": vars(self.args), "event": info, "markets": markets}
        self.write_meta()
        self.mt = mt
        self.model = S.Model(mt, void=not self.args.no_void, strict=self.args.strict)
        self.books.suspect = set(self.tokens())
        print(S.describe(mt), flush=True)
        delays = sorted({str((clob.get(l.condition_id) or {}).get("seconds_delay")) for l in mt.legs})
        self.log("start", f"输出目录 {os.path.abspath(self.outdir)} · 纳入 {len(mt.legs)} 个盘口 / {len(self.tokens())} 个选项"
                          f" · seconds_delay 取值 {', '.join(delays)}")
        self.apply_resolution(raw, initial=True)

    def apply_resolution(self, raw: list[dict], initial: bool = False) -> None:
        """Gamma 盘口对象 → 关闭的选项、已结算单局、新上架盘口。"""
        by_cid = {m.get("conditionId"): m for m in raw}
        known, closed = dict(self.known), set(self.closed_tokens)
        for leg in self.mt.legs:
            m = by_cid.get(leg.condition_id)
            if not m or not m.get("closed"):
                continue
            closed.update(leg.tokens)
            px = [_f(x) for x in S._jl(m.get("outcomePrices"))]
            if leg.kind == "game" and len(px) == 2 and sorted(px) == [0.0, 1.0]:
                win0 = px[0] == 1.0
                other = "B" if leg.t0_is == "A" else "A"
                known[int(leg.param)] = leg.t0_is if win0 else other
            if leg.kind == "ml" and self.ml_closed_at is None:
                self.ml_closed_at = now_ms()
                self.log("series_closed", f"系列赛胜负盘口已关闭（outcomePrices={m.get('outcomePrices')}），"
                                          f"{self.args.linger:g} 秒后自动停止")
        # 新上架的赛果盘口
        cur = {l.condition_id for l in self.mt.legs}
        markets = [S.norm_market(m) for m in raw]
        new_mt = S.build_match(self.mt.slug, self.mt.title, markets, include_closed=True)
        rebuilt = False
        if new_mt and {l.condition_id for l in new_mt.legs} - cur and not initial:
            added = [l.question for l in new_mt.legs if l.condition_id not in cur]
            old = {m.get("conditionId") for m in self.meta["markets"]}
            self.meta["markets"] += [m for m in markets if m.get("conditionId") not in old]
            self.write_meta()
            self.mt = new_mt
            rebuilt = True
            self.log("new_markets", "新上架盘口加入计算并重新订阅：" + "；".join(added))
        if closed != self.closed_tokens:
            self.closed_tokens = closed
            self.log("closed", f"已关闭、不再参与计算的选项 {len(closed)} 个")
        if rebuilt or known != self.known:
            if known != self.known:
                self.log("known", "已结算单局：" + "，".join(
                    f"第 {k} 局 {self.mt.team_a if w == 'A' else self.mt.team_b}" for k, w in sorted(known.items())) +
                    "；情景按此收窄")
            self.known = known
            self.model = S.Model(self.mt, void=not self.args.no_void, strict=self.args.strict, known=known)
            self.last_sig = None
            if rebuilt:
                self.books.suspect |= {t for t in self.tokens() if t not in self.books.asks and t not in self.books.bids}
                self.resub.set()
        self.dirty.set()

    # ------------------------------------------------------------ 订单簿
    def ours(self, m: dict) -> bool:
        """custom_feature 的 new_market / market_resolved 是全平台广播（实测 5 分钟 190 条 new_market），只留本场的。"""
        slug = str(m.get("slug") or (m.get("event_message") or {}).get("slug") or "")
        cid = str(m.get("market") or m.get("condition_id") or "")
        return slug.startswith(self.args.event_slug) or cid in {l.condition_id for l in self.mt.legs}

    def ingest(self, raw: str, recv: int, conn) -> None:
        try:
            msg = json.loads(raw)
        except Exception:
            self.w["pm_market"].write({"recv_ms": recv, "conn": conn, "raw": raw})
            return
        items = [m for m in (msg if isinstance(msg, list) else [msg]) if isinstance(m, dict)]
        if items and all(m.get("event_type") in ("new_market", "market_resolved") and not self.ours(m) for m in items):
            self.c["other_markets"] += 1
            return
        self.w["pm_market"].write({"recv_ms": recv, "conn": conn, "raw": raw})
        try:
            changed = self.books.apply(items)
        except Exception as e:                       # 字段缺失或格式变化：记下来，不中断
            self.c["bad_msgs"] += 1
            self.log("bad_msg", f"无法解析的盘口消息：{e!r}", quiet=self.c["bad_msgs"] > 5, raw=raw[:500])
            return
        toks = set(self.tokens())
        for m in items:
            et = m.get("event_type")
            ts = int(_f(m.get("timestamp"), 0) or 0)
            if et == "book":
                a = str(m.get("asset_id"))
                self.last_ts[a] = max(self.last_ts.get(a, 0), ts)
                self.books.suspect.discard(a)
                self.snap_since_connect.add(a)
            elif et == "price_change":
                last = {}                                # 同一选项有多条变动时，只有最后一条的最优价对应整条消息应用后的状态
                for c in m.get("price_changes") or []:
                    a = str(c.get("asset_id"))
                    self.last_ts[a] = max(self.last_ts.get(a, 0), ts)
                    last[a] = c
                for a, c in last.items():
                    if a not in toks or c.get("best_bid") is None or c.get("best_ask") is None:
                        continue
                    bb = max((p for p, s in self.books.bids.get(a, {}).items() if s > 0), default=0.0)
                    ba = min((p for p, s in self.books.asks.get(a, {}).items() if s > 0), default=1.0)
                    eb, ea = _f(c.get("best_bid"), 0.0), _f(c.get("best_ask"), 1.0)
                    ea = 1.0 if ea <= 0.0 else ea            # 没有卖单时接口给的值未见文档，0 与 1 都按“无卖单”处理
                    if abs(bb - eb) < 1e-9 and abs(ba - ea) < 1e-9:
                        self.c["bba_ok"] += 1
                    elif a not in self.books.suspect:
                        self.c["bba_bad"] += 1
                        self.books.suspect.add(a)
                        self.heal.add(a)
                        self.log("bba_mismatch", f"本地重建与推送的最优价不一致（买一 {bb:g}/{eb:g}，卖一 {ba:g}/{ea:g}），"
                                                 f"该选项暂停计算并用 REST 快照修复", quiet=self.c["bba_bad"] > 20, asset=a)
            elif et in ("market_resolved", "new_market", "tick_size_change") and self.ours(m):
                self.log(et, f"本场盘口消息 {et}：{m.get('question') or m.get('slug') or ''}", raw=raw[:1000])
                self.refresh_now.set()
        if changed:
            self.dirty.set()

    def inject_rest(self, tok: str, d: dict, recv: int) -> None:
        """把 REST 快照当作 book 消息写入录制并应用（回放时状态一致）。"""
        snap = {"event_type": "book", "asset_id": tok, "market": d.get("market"), "timestamp": d.get("timestamp"),
                "hash": d.get("hash"), "bids": d.get("bids") or [], "asks": d.get("asks") or [], "src": "rest"}
        self.ingest(json.dumps(snap, separators=(",", ":")), recv, "rest")

    async def fetch_books(self, toks: list[str]) -> dict:
        loop = asyncio.get_running_loop()
        res = await asyncio.gather(*(loop.run_in_executor(
            self.pool, http_get_json, f"{self.args.clob}/book?token_id={t}", 6.0) for t in toks), return_exceptions=True)
        out = {}
        for t, r in zip(toks, res):
            if isinstance(r, Exception):
                continue
            st, d = r
            if st == 200 and isinstance(d, dict):
                out[t] = d
            elif st == 404:                          # 盘口已关闭、订单簿已撤
                out[t] = {"bids": [], "asks": [], "timestamp": str(now_ms())}
        return out

    @staticmethod
    def _levels(lv) -> dict:
        return {float(x["price"]): float(x["size"]) for x in lv or [] if float(x["size"]) > 0}

    # ------------------------------------------------------------ 任务
    async def market_ws(self) -> None:
        backoff = 1.0
        while not self.stop.is_set():
            toks = self.tokens()
            try:
                async with websockets.connect(self.args.market_ws, max_size=None, ping_interval=None,
                                              open_timeout=15, close_timeout=3) as ws:
                    await ws.send(json.dumps({"assets_ids": toks, "type": "market", "custom_feature_enabled": True}))
                    self.ws_up, backoff = True, 1.0
                    self.ws_last_rx = self.ws_up_since = now_ms()
                    self.gen += 1
                    self.snap_since_connect = set()
                    self.resub.clear()
                    self.log("connected", f"WebSocket 已连接，订阅 {len(toks)} 个选项")
                    if self.mode != "WS":
                        self.mode = "WS"
                        self.log("mode", "恢复 WebSocket 模式")
                    hb = asyncio.create_task(self._heartbeat(ws))
                    rs = asyncio.create_task(self._close_on(ws, self.resub))
                    try:
                        async for raw in ws:
                            t = now_ms()
                            self.ws_last_rx = t
                            if isinstance(raw, (bytes, bytearray)):
                                raw = raw.decode("utf-8", "replace")
                            if raw == "PONG":
                                continue
                            self.c["msgs"] += 1
                            self.ingest(raw, t, 0)
                    finally:
                        hb.cancel()
                        rs.cancel()
                self.log("closed", "WebSocket 连接关闭，重连")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.log("error", f"WebSocket 错误：{e!r}")
            if self.ws_up:
                self.ws_up = False
                self.gen += 1
                self.ws_down_since = now_ms()
                self.books.suspect |= set(self.tokens())     # 断线期间的盘口不可信，等重连后的快照
                self.dirty.set()
            if self.stop.is_set():
                break
            self.c["reconnects"] += 1
            await asyncio.sleep(0.2 if self.resub.is_set() else backoff + random.random())
            backoff = 1.0 if self.resub.is_set() else min(backoff * 2, 30.0)

    async def _close_on(self, ws, ev: asyncio.Event) -> None:
        await ev.wait()
        await ws.close()

    async def _heartbeat(self, ws) -> None:
        while True:
            await asyncio.sleep(10)
            try:
                await ws.send("PING")
            except Exception:
                return
            if now_ms() - self.ws_last_rx > SILENCE_RECONNECT_S * 1000:
                self.log("silent", f"{SILENCE_RECONNECT_S} 秒无消息，主动重连")
                await ws.close()
                return

    async def resync(self) -> None:
        """定期 REST 抽查；不一致以 REST 为准。另处理需立即修复、或连上后迟迟没有快照的选项。"""
        last_full = time.monotonic()
        while not self.stop.is_set():
            await asyncio.sleep(1.0)
            full = time.monotonic() - last_full >= self.args.resync
            stale = set()
            if self.ws_up and now_ms() - self.ws_last_rx < SILENCE_RECONNECT_S * 1000:
                stale = {t for t in self.books.suspect if t not in self.closed_tokens} \
                    if now_ms() - self.ws_up_since > 10_000 else set()
            want = set(self.heal) | stale
            if full:
                want |= {t for t in self.tokens() if t not in self.closed_tokens}
                last_full = time.monotonic()
            if not want or not self.ws_up:
                continue
            self.heal -= want
            gen = self.gen
            got = await self.fetch_books(sorted(want))
            await asyncio.sleep(1.0)                   # 让 REST 时刻之前发出的 WS 消息先到
            if gen != self.gen or not self.ws_up:      # 期间断线或重连：这批快照作废
                self.heal |= want & self.books.suspect
                continue
            for tok, d in got.items():
                rts = int(_f(d.get("timestamp"), 0) or 0)
                if tok not in self.books.suspect and self.last_ts.get(tok, 0) > rts:
                    self.c["rest_skip"] += 1           # 这期间又有更新：REST 快照已过时，下次再比
                    continue
                asks, bids = self._levels(d.get("asks")), self._levels(d.get("bids"))
                if tok not in self.books.suspect:
                    if S._same_levels(self.books.asks.get(tok, {}), asks) and S._same_levels(self.books.bids.get(tok, {}), bids):
                        self.c["rest_ok"] += 1
                        continue
                    self.c["rest_bad"] += 1
                    self.log("rest_mismatch", "REST 快照与本地重建不一致，以 REST 为准",
                             quiet=self.c["rest_bad"] > 20, asset=tok)
                self.inject_rest(tok, d, now_ms())

    async def rest_fallback(self) -> None:
        """WebSocket 长时间不可用时改为 REST 轮询。"""
        while not self.stop.is_set():
            await asyncio.sleep(self.args.interval if self.mode == "REST" else 1.0)
            down = (not self.ws_up) and now_ms() - self.ws_down_since > self.args.fallback_after * 1000
            if self.args.rest_only or down:
                if self.mode != "REST":
                    self.mode = "REST"
                    self.log("mode", "WebSocket 不可用，改为 REST 轮询" if not self.args.rest_only else "REST 轮询模式")
                toks = [t for t in self.tokens() if t not in self.closed_tokens]
                got = await self.fetch_books(toks)
                self.c["rest_polls"] += 1
                t = now_ms()
                for tok, d in got.items():
                    self.inject_rest(tok, d, t)

    async def gamma_refresh(self) -> None:
        while not self.stop.is_set():
            try:
                await asyncio.wait_for(self.refresh_now.wait(), timeout=self.args.refresh)
            except asyncio.TimeoutError:
                pass
            self.refresh_now.clear()
            try:
                _, raw = await asyncio.get_running_loop().run_in_executor(
                    self.pool, fetch_event_raw, self.args.gamma, self.mt.slug)
                self.apply_resolution(raw)
            except Exception as e:
                self.log("gamma_error", f"刷新盘口状态失败：{e!r}", quiet=True)
            if self.ml_closed_at and now_ms() - self.ml_closed_at > self.args.linger * 1000:
                self.log("done", "系列赛已结算，停止")
                self.stop.set()

    async def evaluator(self) -> None:
        while not self.stop.is_set():
            await self.dirty.wait()
            gap = self.args.min_gap_ms / 1000 - (time.monotonic() - self.last_eval_ms / 1000)
            if gap > 0:
                await asyncio.sleep(gap)
            self.dirty.clear()
            self.evaluate()

    def evaluate(self) -> None:
        excl = self.excluded()
        lb = {t: v for t, v in self.books.lp_books(self.model).items() if t not in excl}
        toks = self.tokens()
        sig = tuple((lb[t][0][0] if lb.get(t) else None) for t in toks) + (tuple(sorted(excl)), tuple(sorted(self.known.items())))
        if sig == self.last_sig and self.ep.cur is None:
            return
        self.last_sig = sig
        self.last_eval_ms = time.monotonic() * 1000
        ts = now_ms()
        t0 = time.perf_counter()
        r = S.solve(self.model, lb, self.args.fee_rate, self.args.min_shares, exclude=excl)
        dt = (time.perf_counter() - t0) * 1000
        self.c["evals"] += 1
        was_open, n_items = self.ep.cur is not None, len(self.ep.items)
        self.ep.update(ts, r)
        opp = bool(r and r.profit >= self.args.min_profit)
        self.w["eval"].write({"ts_ms": ts, "unit_cost": None if r is None else round(r.unit_cost, 6),
                              "profit": None if r is None else round(r.profit, 4), "opp": opp,
                              "priced": sum(1 for t in toks if lb.get(t)), "excluded": len(excl),
                              "solve_ms": round(dt, 2)})
        if opp and not was_open:
            self.c["alerts"] += 1
            print("\a\n" + "=" * 72 + f"\n[{stamp()}] 发现组合机会（候选，未计多腿不同时成交与吃单延迟）\n"
                  + S.fmt_result(self.mt, r, self.args.min_shares) + "\n" + "=" * 72, flush=True)
            self.log("episode_open", f"机会开始：利润 ${r.profit:.2f}，投入 ${r.cost:.2f}", quiet=True,
                     unit_cost=r.unit_cost, orders=r.orders, tail_pnl=r.tail_pnl, tail_label=r.tail_label)
            if self.args.notify:
                osa_notify("C 组合机会", f"可锁定 ${r.profit:.2f}，投入 ${r.cost:.2f}")
        if len(self.ep.items) > n_items:
            self.write_episode(self.ep.items[-1])

    def write_episode(self, e: dict) -> None:
        self.w["episodes"].write(dict(e, start_utc=S.utc(e["start_ms"])))
        self.ep_written += 1
        self.ep.write_csv(os.path.join(self.outdir, "live_episodes.csv"))
        self.log("episode_close", f"机会结束：持续 {e['duration_s']:.1f} 秒，最大利润 ${e['max_profit']:.2f}，投入 ${e['cost']:.2f}"
                 + ("" if e["tail"] is None else f"，中途终止最差 ${e['tail']:+.2f}"))

    def status_line(self) -> str:
        c = self.c
        age = (now_ms() - self.ws_last_rx) / 1000 if self.ws_last_rx else float("nan")
        unit = self.ep.last_unit
        susp = len(self.books.suspect - self.closed_tokens)
        return (f"{self.mode}{'·已连接' if self.ws_up else '·未连接'} · 消息 {c['msgs']}（距上条 {age:.0f}s）· 评估 {c['evals']}"
                f" · 锁定$1成本 当前 {unit:.4f} 最低 {self.ep.min_unit:.4f} · 机会 {len(self.ep.items) + (1 if self.ep.cur else 0)} 段"
                f" · 暂停计算 {susp}/{len(self.tokens())}，已关闭 {len(self.closed_tokens)}"
                f" · 最优价核对 {c['bba_ok']}/{c['bba_bad']} · REST 抽查 {c['rest_ok']}/{c['rest_bad']} · 重连 {c['reconnects']}")

    async def status(self) -> None:
        while not self.stop.is_set():
            await asyncio.sleep(self.args.status_every)
            self.log("status", self.status_line())

    def finish(self) -> dict:
        self.ep.close(now_ms())
        for e in self.ep.items[self.ep_written:]:
            self.write_episode(e)
        self.ep.write_csv(os.path.join(self.outdir, "live_episodes.csv"))
        end = {"ended_utc": utc_iso(), "ended_ms": now_ms(), "counts": self.c, "known": self.known,
               "closed_tokens": sorted(self.closed_tokens), "min_unit_cost": self.ep.min_unit,
               "episodes": len(self.ep.items), "summary": self.ep.summary()}
        with open(os.path.join(self.outdir, "meta_end.json"), "w", encoding="utf-8") as f:
            json.dump(end, f, ensure_ascii=False, indent=2, default=str)
        for w in self.w.values():
            w.close()
        self.pool.shutdown(wait=False)
        return end


async def amain(args) -> int:
    outdir = args.out or f"rec_c_{args.event_slug}_{datetime.now():%Y%m%d-%H%M%S}"
    os.makedirs(outdir, exist_ok=True)
    mon = Monitor(args, outdir)
    try:
        mon.load()
    except RuntimeError as e:
        print(f"读取盘口清单失败：{e}", file=sys.stderr)
        return 2
    tasks = [asyncio.create_task(x) for x in (mon.evaluator(), mon.resync(), mon.rest_fallback(),
                                              mon.gamma_refresh(), mon.status())]
    if not args.rest_only:
        tasks.append(asyncio.create_task(mon.market_ws()))
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, mon.stop.set)
        except (NotImplementedError, RuntimeError, ValueError):
            pass
    duration = 20.0 if args.check else args.hours * 3600
    print(f"[{stamp()}] 开始监控，{'自检 20 秒' if args.check else f'最长 {args.hours:g} 小时'}；"
          f"吃单费率 {args.fee_rate}，利润门槛 ${args.min_profit:g}，"
          f"{'严格模式（中途终止也不亏）' if args.strict else '中途终止情形单独报告'}；Ctrl+C 停止", flush=True)
    try:
        await asyncio.wait_for(mon.stop.wait(), timeout=duration)
    except asyncio.TimeoutError:
        pass
    finally:
        mon.stop.set()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        end = mon.finish()
        print(f"[{stamp()}] 已停止。{mon.status_line()}", flush=True)
        print(f"[{stamp()}] {end['summary']}", flush=True)
        if args.check:
            n = len(mon.tokens())
            fresh = n - len(mon.books.suspect - mon.closed_tokens)
            ok = mon.c["msgs"] > 0 and fresh == n and mon.c["evals"] > 0 and mon.c["bba_bad"] == 0
            print("自检结果：" + "；".join([
                f"WebSocket {'正常' if mon.c['msgs'] else '20 秒内没收到消息'}",
                f"有快照的选项 {fresh}/{n}",
                f"评估 {mon.c['evals']} 次，当前锁定 $1 成本 {mon.ep.last_unit:.4f}",
                f"最优价核对 一致 {mon.c['bba_ok']} / 不一致 {mon.c['bba_bad']}",
                f"REST 抽查 一致 {mon.c['rest_ok']} / 不一致 {mon.c['rest_bad']}",
            ]) + ("  → 可以正式开跑" if ok else "  → 有问题，先看上面的日志"), flush=True)
        print(f"[{stamp()}] 数据在：{os.path.abspath(outdir)}；赛后复核：python3 scanner/lol_c_scan.py replay {outdir}", flush=True)
    return 0


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="C 方案实时监控：一场 LoL 系列赛的跨盘口无风险组合（Polymarket，只读）")
    p.add_argument("--event-slug", required=True, help="赛事 slug，例如 lol-blg-gen-2026-11-14")
    p.add_argument("--hours", type=float, default=8.0, help="最长监控小时数，默认 8")
    p.add_argument("--check", action="store_true", help="自检 20 秒后退出")
    p.add_argument("--out", help="输出目录，默认 rec_c_<slug>_<时间>")
    p.add_argument("--fee-rate", type=float, default=0.05, help="吃单费率，默认 0.05")
    p.add_argument("--min-profit", type=float, default=0.5, help="报警门槛：可锁定利润（美元），默认 0.5")
    p.add_argument("--min-shares", type=float, default=5.0, help="最小下单量（股），只用于提示，默认 5")
    p.add_argument("--no-void", action="store_true", help="不考虑“整场取消、全部 50-50”")
    p.add_argument("--strict", action="store_true", help="把“开赛后中途终止”也作为约束")
    p.add_argument("--notify", action=argparse.BooleanOptionalAction, default=True,
                   help="发现机会时发 macOS 通知（默认开；--no-notify 关闭）")
    p.add_argument("--status-every", type=float, default=30.0, help="状态行间隔秒数，默认 30")
    p.add_argument("--resync", type=float, default=60.0, help="REST 抽查间隔秒数，默认 60")
    p.add_argument("--refresh", type=float, default=60.0, help="Gamma 盘口状态刷新间隔秒数，默认 60")
    p.add_argument("--min-gap-ms", type=float, default=50.0, help="两次评估的最小间隔毫秒，默认 50")
    p.add_argument("--fallback-after", type=float, default=20.0, help="WebSocket 断开多少秒后改用 REST 轮询，默认 20")
    p.add_argument("--interval", type=float, default=2.0, help="REST 轮询间隔秒数，默认 2")
    p.add_argument("--rest-only", action="store_true", help="不用 WebSocket，只用 REST 轮询")
    p.add_argument("--linger", type=float, default=300.0, help="系列赛胜负盘口关闭后再跑多少秒，默认 300")
    p.add_argument("--gamma", default=S.GAMMA)
    p.add_argument("--clob", default=S.CLOB)
    p.add_argument("--market-ws", default=MARKET_WS)
    a = p.parse_args(argv)
    if a.check:
        a.status_every = min(a.status_every, 5.0)
        a.resync = min(a.resync, 8.0)
    return a


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(amain(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
