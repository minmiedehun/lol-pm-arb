# Taker-fee hurdle for the BO5 identity basket: ML_A + 0.5*U4.5  vs  G5_A + HC_A(-1.5)
# Using the LCP example display prices (not executable): ML 0.78, U4.5 = 1-0.29, HC-1.5 0.64, G5 ~0.55 (model)
rate = 0.05
def f(p, w=1.0): return w * rate * p * (1 - p)
legs = {'ML_A': (0.78, 1.0), 'U4.5': (0.71, 0.5), 'G5_A': (0.55, 1.0), 'HC_A-1.5': (0.64, 1.0)}
tot = sum(f(p, w) for p, w in legs.values())
print("per-unit taker fee by leg (cents):", {k: round(100*f(p, w), 3) for k, (p, w) in legs.items()})
print(f"total taker fee for the 4-leg basket = {100*tot:.2f} cents per unit")
# Simple 2-leg monotonic arb, e.g. HC_A(-2.5) priced above G1_A: sell HC (buy HC_B side), buy G1
print(f"2-leg example at p~0.30/0.66: {100*(f(0.30)+f(0.66)):.2f} cents")
