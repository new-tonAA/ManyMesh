#!/usr/bin/env python3
"""Direct pair placement experiment; no production or novelty claim."""
import numpy as np


def pair_metrics(a, b, frames=8):
    if frames < 1:
        raise ValueError('positive history length required')
    mean = (a+b)*.5
    difference = (a-b)*.5
    bias = float(np.square(mean).sum())
    variance = float(np.square(difference).sum())
    return dict(bias=bias, expected=bias+variance/frames,
                coverageExpected=float(np.square(mean[..., 0]).sum() +
                                       np.square(difference[..., 0]).sum()/frames),
                worstInstantaneous=max(float(np.square(a).sum()), float(np.square(b).sum())))


def search(seed, edge_length, evaluate, guard, paired):
    """Equal proposal ceiling, deterministic tie-breaking; evaluate returns residual image."""
    targets = [np.asarray(seed).copy() for _ in range(2 if paired else 1)]
    images = [evaluate(seed)]
    if paired:
        images.append(images[0].copy())
    def score(values):
        return pair_metrics(*values)['expected'] if paired else float(np.square(values[0]).sum())
    best = score(images)
    best_single = float(np.square(images[0]).sum())
    best_single_target = targets[0].copy()
    rasters, rejected, attempts = 1, 0, 0
    for sweep in range(8):
        index = sweep % len(targets)
        radius = edge_length*.125*(.5**(sweep//2))
        center = targets[index].copy()
        next_target, next_image = center, images[index]
        for axis in np.eye(3):
            for sign in (-1, 1):
                target = center + sign*radius*axis
                attempts += 1
                if not guard(target):
                    rejected += 1
                    continue
                image = evaluate(target)
                rasters += 1
                single_error = float(np.square(image).sum())
                if single_error < best_single:
                    best_single, best_single_target = single_error, target.copy()
                trial = images.copy()
                trial[index] = image
                value = score(trial)
                if value < best-1e-14:
                    best, next_target, next_image = value, target.copy(), image
        targets[index], images[index] = next_target, next_image
    return dict(targets=targets, images=images, score=best, bestSingle=best_single,
                bestSingleTarget=best_single_target, rasters=rasters, rejected=rejected,
                attempts=attempts)
