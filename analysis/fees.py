import math

def pm_fee(p, rate=0.05):
    # Polymarket taker fee per share (USDC), fee = C*rate*p*(1-p)
    return rate * p * (1 - p)

def kalshi_fee_per_contract(P, C=100, mult=0.07):
    # Kalshi taker fee: round up (to cent) of mult*C*P*(1-P), per order of C contracts
    total = math.ceil(round(mult * C * P * (1 - P) * 100, 6)) / 100.0
    return total / C

print("== User example: PM GEN YES 0.46 + Kalshi GEN NO 0.51 ==")
pm = pm_fee(0.46); ks = kalshi_fee_per_contract(0.51)
print(f"PM taker fee/share = {pm*100:.3f}c ; Kalshi taker fee/contract (100 lot) = {ks*100:.3f}c")
gross = 1 - (0.46 + 0.51)
print(f"gross = {gross*100:.2f}c ; net both taker = {(gross - pm - ks)*100:.3f}c ; net PM taker + Kalshi maker(0) = {(gross - pm)*100:.3f}c ; net PM maker + Kalshi taker = {(gross - ks)*100:.3f}c")

print("\n== Break-even gross edge (cents per $1 payout), YES at p on venue1, NO at ~(1-p) on venue2 ==")
print("p     both_taker  PMtaker+KSmaker  PMmaker+KStaker")
for p in [0.10, 0.20, 0.30, 0.40, 0.50]:
    a = pm_fee(p); b = kalshi_fee_per_contract(1 - p)
    print(f"{p:.2f}  {100*(a+b):9.3f}  {100*a:15.3f}  {100*b:15.3f}")
