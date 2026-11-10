import itertools

def series_paths(best_of):
    need = best_of // 2 + 1
    paths = []
    def rec(seq, a, b):
        if a == need or b == need:
            paths.append(tuple(seq)); return
        rec(seq + ['A'], a + 1, b); rec(seq + ['B'], a, b + 1)
    rec([], 0, 0)
    return paths

def payoffs(path, best_of):
    n = len(path); a = path.count('A'); b = path.count('B')
    need = best_of // 2 + 1
    ML_A = 1.0 if a == need else 0.0
    out = {'ML_A': ML_A}
    for k in range(1, best_of + 1):
        out[f'G{k}_A'] = (1.0 if path[k-1] == 'A' else 0.0) if k <= n else 0.5   # Polymarket: unplayed game -> 50-50
    for line in [x + 0.5 for x in range(need, best_of)]:
        out[f'O{line}'] = 1.0 if n > line else 0.0
        out[f'U{line}'] = 1.0 - out[f'O{line}']
    for h in [x + 0.5 for x in range(1, need)]:
        out[f'HC_A-{h}'] = 1.0 if (ML_A == 1 and a - b > h) else 0.0
        out[f'HC_B-{h}'] = 1.0 if (ML_A == 0 and b - a > h) else 0.0
    return out

for bo in (3, 5):
    paths = series_paths(bo)
    last = f'G{bo}_A'; dec = f'U{bo-0.5}'; hc = 'HC_A-1.5'
    ok = all(abs(payoffs(p,bo)['ML_A'] + 0.5*payoffs(p,bo)[dec] - payoffs(p,bo)[last] - payoffs(p,bo)[hc]) < 1e-12 for p in paths)
    print(f"BO{bo}: identity ML_A + 0.5*{dec} == {last} + {hc} holds in all {len(paths)} paths: {ok}")

paths = series_paths(5)
ok1 = all(abs(payoffs(p,5)['U3.5'] - payoffs(p,5)['HC_A-2.5'] - payoffs(p,5)['HC_B-2.5']) < 1e-12 for p in paths)
ok2 = all(payoffs(p,5)['HC_A-2.5'] <= min(payoffs(p,5)['G1_A'], payoffs(p,5)['G2_A'], payoffs(p,5)['G3_A']) for p in paths)
ok3 = all(payoffs(p,5)['G4_A'] <= payoffs(p,5)['O3.5'] + 0.5*payoffs(p,5)['U3.5'] + 1e-12 for p in paths)
ok4 = all(payoffs(p,5)['G4_A'] >= 0.5*payoffs(p,5)['U3.5'] - 1e-12 for p in paths)
print("BO5: U3.5 == HC_A-2.5 + HC_B-2.5:", ok1, "| HC_A-2.5 <= G1,G2,G3:", ok2, "| G4_A <= O3.5 + 0.5*U3.5:", ok3, "| G4_A >= 0.5*U3.5:", ok4)

# iid model consistency check vs. display prices of an LCP BO5 (TSW vs DCG) mirrored by orrery.me
p = 0.66
def prob(path): 
    r = 1.0
    for g in path: r *= p if g == 'A' else (1-p)
    return r
exp = {}
for path in paths:
    pr = prob(path)
    for k, v in payoffs(path, 5).items():
        exp[k] = exp.get(k, 0) + pr * v
listed = {'ML_A': 0.78, 'O3.5': 0.67, 'O4.5': 0.29, 'HC_A-1.5': 0.64, 'HC_A-2.5': 0.33, 'G1_A': 0.66}
print("\niid per-game p=0.66 model vs listed display prices:")
for k in ['ML_A','G1_A','O3.5','O4.5','HC_A-1.5','HC_A-2.5','G4_A','G5_A']:
    print(f"  {k:9s} model={exp[k]:.3f}  listed={listed.get(k,'-')}")
implied_G5 = listed['ML_A'] + 0.5*(1-listed['O4.5']) - listed['HC_A-1.5']
print(f"implied G5_A from identity using listed prices = {implied_G5:.3f} (model {exp['G5_A']:.3f})")
