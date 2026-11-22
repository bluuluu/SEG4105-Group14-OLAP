"""SEG4105 Group 14 — reproducible Monte Carlo schedule risk simulation.

This is a planning model, not observed construction/project performance.
Activity distributions are illustrative and should be approved by the team.

Requires: numpy, matplotlib (pip install numpy matplotlib)
Run: python OLAP_Schedule_Monte_Carlo.py
"""
import numpy as np
import matplotlib.pyplot as plt

SEED = 14
TRIALS = 200_000
# optimistic, most likely, pessimistic duration in weeks
ACTIVITIES = {
    "A": (1, 2, 3),        # Requirements
    "B": (1, 2, 3),        # Design
    "C": (2, 3, 5),        # Data warehouse (parallel)
    "D": (2, 3, 5),        # OLAP development (parallel)
    "E": (1, 2, 3),        # Dashboards
    "F": (1, 2, 4),        # Testing
    "G": (0.5, 1, 2),      # Deployment
}

rng = np.random.default_rng(SEED)
durations = {activity: rng.triangular(low, mode, high, TRIALS)
             for activity, (low, mode, high) in ACTIVITIES.items()}
# E waits for BOTH C and D, so use the later-finishing parallel branch.
completion = (durations["A"] + durations["B"]
              + np.maximum(durations["C"], durations["D"])
              + durations["E"] + durations["F"] + durations["G"])

print(f"Simulations: {TRIALS:,} | random seed: {SEED}")
print(f"Mean completion: {completion.mean():.2f} weeks")
print(f"Median (P50): {np.percentile(completion, 50):.2f} weeks")
print(f"P80: {np.percentile(completion, 80):.2f} weeks")
print(f"P90: {np.percentile(completion, 90):.2f} weeks")
print(f"P(complete <= 12 weeks): {np.mean(completion <= 12):.1%}")
print(f"P(complete <= 14 weeks): {np.mean(completion <= 14):.1%}")

fig, ax = plt.subplots(figsize=(9, 4))
ax.hist(completion, bins=70, edgecolor='white', linewidth=.3)
ax.axvline(12, linestyle='--', label='12-week baseline')
ax.axvline(np.percentile(completion, 80), linestyle=':', label='P80')
ax.set(xlabel='Completion duration (weeks)', ylabel='Simulated trials',
       title='OLAP Project — Monte Carlo Schedule Risk')
ax.legend()
fig.tight_layout()
fig.savefig('OLAP_Monte_Carlo_Histogram.png', dpi=180)
print('Saved OLAP_Monte_Carlo_Histogram.png')
