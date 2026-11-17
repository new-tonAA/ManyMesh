#!/usr/bin/env python3
"""Finite-state convex bias diagnostic; standard optimization, not a novelty claim."""
import numpy as np


def solve_bias(residuals, max_steps=10000, relative_gap=1e-9):
    """Rows are residuals. Return a feasible mixture and a numerical FW certificate."""
    d = np.asarray(residuals, dtype=float)
    if d.ndim != 2 or not len(d) or not np.isfinite(d).all():
        raise ValueError('nonempty finite residual matrix required')
    if max_steps < 1 or relative_gap < 0:
        raise ValueError('positive iteration count and nonnegative tolerance required')
    gram = d @ d.T
    magnitude = float(np.max(np.diag(gram)))
    w = np.zeros(len(d))
    best = int(np.argmin(np.diag(gram)))
    w[best] = 1.
    if magnitude == 0:
        return dict(weights=w, energy=0., lower=0., gap=0., steps=0,
                    bestStatic=0., uniform=0., iid8=0., iid16=0.)
    G = gram/magnitude
    for step in range(max_steps):
        Gw = G @ w
        energy = float(w @ Gw)
        index = int(np.argmin(Gw))
        gap = max(0., 2*(energy-float(Gw[index])))
        if gap <= relative_gap*max(energy, 1e-15):
            break
        direction = -w.copy()
        direction[index] += 1.
        curvature = float(direction @ G @ direction)
        if curvature <= 0:
            break
        alpha = np.clip((energy-Gw[index])/curvature, 0., 1.)
        w += alpha*direction
    # Evaluate the actual residual to avoid cancellation in the primal energy.
    energy = float(np.square(w @ d).sum())
    gap = max(0., 2*(energy-float(np.min(gram @ w))))
    second = float(w @ np.diag(gram))
    return dict(weights=w, energy=energy, lower=max(0., energy-gap), gap=gap,
                steps=step+1, bestStatic=float(gram[best, best]),
                uniform=float(np.square(d.mean(axis=0)).sum()),
                iid8=energy+max(0., second-energy)/8,
                iid16=energy+max(0., second-energy)/16)
