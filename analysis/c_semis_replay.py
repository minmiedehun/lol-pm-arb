"""两场半决赛回放：一次扫描同时给出 不限 / 2000u / 500u 三档的机会段，并记录每分钟最低“锁定$1成本”。只读分析。
用法：python3 analysis/c_semis_replay.py <赛事slug> <数据根目录（含 meta_<slug>.json 与 2026-11-0*/）> <输出目录> [strict]"""
import sys, os, json, csv, heapq, glob, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scanner'))
import lol_c_scan as S

slug, root, outdir = sys.argv[1], sys.argv[2], sys.argv[3]
strict = len(sys.argv) > 4 and sys.argv[4] == 'strict'
meta = json.load(open(os.path.join(root, f'meta_{slug}.json'), encoding='utf-8'))
ev = meta.get('event') or {}
mt = S.build_match(ev.get('slug') or slug, ev.get('title') or '', meta.get('markets') or [], True)
paths = sorted(glob.glob(os.path.join(root, '2026-11-0*', f'polymarket-{slug}*.zst')))
files = S.load_cs_files(paths)
mapped, unmapped = S.map_cs_files(files, mt, 'auto')
for f, leg, ti, how in mapped:
    print(os.path.basename(f.path), '→', leg.question, leg.labels[ti], '|', how, flush=True)
model = S.Model(mt, strict=strict)
books = S.CsBooks()
BUD = [None, 2000.0, 500.0]
eps = [S.Episodes(0.5) for _ in BUD]
toks = model.tokens()

def stream(idx, f, tok):
    for n, (ats, t, prev, eid, data) in enumerate(f.events()):
        yield ats, idx, n, tok, t, prev, eid, data
merged = heapq.merge(*[stream(i, f, leg.tokens[ti]) for i, (f, leg, ti, _) in enumerate(mapped)])
minute = {}   # minute -> [min_unit, n_eval, max_profit_2000]
last_sig = None; n_ev = 0; n_lp = 0; t0 = time.time(); last_ts = None
for ats, _, _, tok, t, prev, eid, data in merged:
    n_ev += 1
    if n_ev % 500000 == 0:
        print(f'  {n_ev} 事件, {n_lp} 次求解, {time.time()-t0:.0f}s, 到 {S.utc(ats//1_000_000)}', flush=True)
    if not books.apply(tok, t, prev, eid, data):
        continue
    ts = ats // 1_000_000
    lb = books.lp_books(model)
    sig = tuple((lb[x][0][0] if lb.get(x) else None) for x in toks) + tuple(sorted(books.suspect))
    active = any(e.cur is not None for e in eps)
    if sig == last_sig and not active:
        continue
    last_sig, last_ts = sig, ts
    r = S.solve(model, lb, 0.05, 5.0, exclude=books.suspect); n_lp += 1
    eps[0].update(ts, r)
    rb = [r]
    for e, b in zip(eps[1:], BUD[1:]):
        x = r if (r is None or r.profit <= 0) else S.solve(model, lb, 0.05, 5.0, exclude=books.suspect, max_cost=b)
        e.update(ts, x); rb.append(x)
    if r is not None:
        m = minute.setdefault(ts // 60000, [9.0, 0, 0.0, 0])
        m[0] = min(m[0], r.unit_cost); m[1] += 1
        if rb[1] is not None: m[2] = max(m[2], rb[1].profit)
        m[3] = max(m[3], len(books.suspect))
tag = slug + ('_strict' if strict else '')
for e, b in zip(eps, BUD):
    if last_ts: e.close(last_ts)
    name = 'nolimit' if b is None else str(int(b))
    e.write_csv(os.path.join(outdir, f'ep_{tag}_{name}.csv'))
    print(name, '|', e.summary(), flush=True)
with open(os.path.join(outdir, f'minute_{tag}.csv'), 'w', newline='') as f:
    w = csv.writer(f); w.writerow(['minute_utc', 'min_unit', 'n_eval', 'max_profit_2000', 'suspect'])
    for k in sorted(minute): w.writerow([S.utc(k * 60000), round(minute[k][0], 5), minute[k][1], round(minute[k][2], 3), minute[k][3]])
print(f'完成：{n_ev} 事件，{n_lp} 次求解，{time.time()-t0:.0f}s；断点 {sum(books.gaps.values())}，重复 {books.dups}；全程最低单位成本 {eps[0].min_unit:.4f}', flush=True)
