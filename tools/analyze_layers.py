import os
os.environ['COVASIM_VERBOSE'] = '0'
import json
import numpy as np

best = json.loads(open('examples/figures/campus_calibration/best_pars.json').read())
beta_campus = best['beta']

# ---- Campus model (calibrated) ----
campus_layers = [
    ("d (dormitory)",      5,  best['beta_layer_d']),
    ("clu (classroom-UG)", 25, best['beta_layer_cl']),
    ("clg (classroom-GR)", 12, best['beta_layer_cl']),
    ("of (lab/office)",    6,  best['beta_layer_cl'] * 0.8),
    ("ta (staff)",         3,  best['beta_layer_cl'] * 1.2),
    ("cm (common spaces)", 12, best['beta_layer_cm']),
]

# ---- Covasim hybrid model (default, peer-reviewed) ----
beta_hybrid = 0.016
hybrid_layers = [
    ("h (household)",  2,  3.0),
    ("s (school)",     20, 0.6),
    ("w (work)",       16, 0.6),
    ("c (community)",  20, 0.3),
]

print("=" * 70)
print("COMPARISON: Campus (calibrated) vs Hybrid (Covasim default)")
print("=" * 70)

total_c = 0
for name, cts, wt in campus_layers:
    total_c += cts * beta_campus * wt

print(f"\nCAMPUS (beta={beta_campus:.4f}): {'Layer':<22s} {'ct':>4s} {'wt':>6s} {'contrib':>8s} {'%':>7s}")
for name, cts, wt in campus_layers:
    contrib = cts * beta_campus * wt
    print(f"  {name:<22s} {cts:>4d} {wt:>6.2f} {contrib:>8.3f} {contrib/total_c*100:>6.1f}%")
print(f"  {'TOTAL':<22s} {'--':>4s} {'--':>6s} {total_c:>8.3f}")
print(f"  Implied R0 (infectious period ~5d): {total_c * 5:.1f}")
print(f"  Actual model R_eff: ~4.1")

total_h = 0
for name, cts, wt in hybrid_layers:
    total_h += cts * beta_hybrid * wt

print(f"\nHYBRID (beta={beta_hybrid:.4f}): {'Layer':<22s} {'ct':>4s} {'wt':>6s} {'contrib':>8s} {'%':>7s}")
for name, cts, wt in hybrid_layers:
    contrib = cts * beta_hybrid * wt
    print(f"  {name:<22s} {cts:>4d} {wt:>6.2f} {contrib:>8.3f} {contrib/total_h*100:>6.1f}%")
print(f"  {'TOTAL':<22s} {'--':>4s} {'--':>6s} {total_h:>8.3f}")
print(f"  Implied R0 (infectious period ~5d): {total_h * 5:.1f}")
print(f"  Typical hybrid R_eff: ~1.5-2.5")

# ---- KEY INSIGHT ----
print("\n" + "=" * 70)
print("KEY DIAGNOSIS")
print("=" * 70)
print(f"""
Campus model has {sum(c for _,c,_ in campus_layers)} daily contacts vs hybrid's {sum(c for _,c,_ in hybrid_layers)}.
But hybrid uses LOW layer weights (0.3-0.6) for school/work/community.
Campus uses MUCH HIGHER weights (0.43-2.73) even after calibration.

WHY? Because the optimizer needed high weights to match the diagnosis curve.
The campus model's testing intervention (test_num) has a low ascertainment rate
(~24%), so to produce enough DIAGNOSES, it needs many more INFECTIONS.
More infections = higher R_eff.

THE FIX: The contact numbers themselves aren't the problem. The issue is the
RATIO of contacts to beta_layer weights. Either:
  A) Lower contacts to represent "close contacts" (not room occupants)
  B) Accept that campus model R_eff ~4 is a structural feature, document it
  C) Increase testing ascertainment so model doesn't need as many infections
     to match diagnoses (e.g., symp_test higher, quar_test higher)
""")

# ---- Option C test: what if ascertainment were higher? ----
print("=" * 70)
print("OPTION C: Impact of higher testing ascertainment")
print("=" * 70)
for symp_test in [80, 95, 100]:
    for quar_test in [30, 50, 70]:
        # Quick sim to check ascertainment
        pass  # Would need actual sim, just estimate

print("""
With symp_test=95 and quar_test=70 (aggressive testing like Notre Dame actually did):
  - Ascertainment might rise from ~24% to ~40-50%
  - Model would need FEWER infections to match same diagnosis curve
  - beta would calibrate lower → R_eff would drop
  - This is more realistic: Notre Dame tested ~700 tests/day at peak
""")
