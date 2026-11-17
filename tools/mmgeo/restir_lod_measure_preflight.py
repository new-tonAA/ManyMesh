"""Exact finite GRIS measure/support control; not a path tracer or a novel estimator."""
import argparse
from fractions import Fraction as F
import hashlib
from itertools import product
import json
from pathlib import Path


def estimate(domains, target_area, value, target_density, support_aware=True, jacobian=True):
    """Enumerate candidate draws AND reservoir selection with rational arithmetic."""
    for domain in domains:
        image = [y for y in domain["mapping"] if y is not None]
        if len(image) != len(set(image)):
            raise ValueError("domain map is not a partial bijection")
        if sum(domain["probability"]) != 1 or any(p <= 0 for p in domain["probability"]):
            raise ValueError("invalid sampling probabilities")
    covers = [sum(y in d["mapping"] for d in domains) for y in range(len(target_area))]
    if min(covers) == 0:
        raise ValueError("target support is uncovered")
    expectation = F(0)
    combinations = 0
    for indices in product(*(range(len(d["mapping"])) for d in domains)):
        probability, weights, mapped = F(1), [], []
        for domain, x in zip(domains, indices):
            p = domain["probability"][x]
            probability *= p
            y = domain["mapping"][x]
            mapped.append(y)
            if y is None:
                weights.append(F(0))
                continue
            m = F(1, covers[y]) if support_aware else F(1, len(domains))
            area_ratio = target_area[y] / domain["area"][x] if jacobian else F(1)
            source_ucw = domain["area"][x] / p
            weights.append(m * target_density[y] * area_ratio * source_ucw)
        total = sum(weights)
        if total:
            for y, weight in zip(mapped, weights):
                if weight:
                    # P(select y)=weight/total; output UCW=total/pHat(y).
                    expectation += probability * (weight / total) * value[y] * total / target_density[y]
        combinations += 1
    return expectation, combinations


def cases():
    area = list(map(F, (1, 2, 3, 4)))
    value = list(map(F, (2, 5, 3, 7)))
    density = list(map(F, (3, 1, 8, 2)))
    canonical = dict(mapping=[0, 1, 2, 3], area=area, probability=[F(1, 4)] * 4)
    # Source and target have different atom surface areas and mixed LOD labels.
    # Indices are canonical-domain patches; a permuted map represents different topology.
    full = dict(mapping=[2, 0, 3, 1], area=list(map(F, (7, 5, 2, 9))),
                probability=[F(1, 10), F(2, 10), F(3, 10), F(4, 10)])
    # Selector-inconsistent or missing patches fail the partial map rather than being clamped.
    partial = dict(mapping=[2, None, None, 1], area=list(map(F, (7, 5, 2, 9))),
                   probability=[F(1, 10), F(2, 10), F(3, 10), F(4, 10)])
    reference = sum(a * f for a, f in zip(area, value))
    result = []
    for name, temporal, aware, jac in (
            ("full_map_standard_GRIS", full, True, True),
            ("partial_map_standard_GRIS", partial, True, True),
            ("partial_map_constant_half_MIS", partial, False, True),
            ("full_map_missing_area_Jacobian", full, True, False)):
        actual, draws = estimate([canonical, temporal], area, value, density, aware, jac)
        result.append(dict(case=name, exact_expectation=str(actual), reference=str(reference),
                           error=str(actual - reference), candidate_draw_combinations=draws,
                           unbiased_in_this_model=actual == reference))
    if [r["unbiased_in_this_model"] for r in result] != [True, True, False, False]:
        raise ValueError("unexpected measure/support control result")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    rows = cases()
    data = dict(schema=1, scope="finite exact GRIS control; no mesh/path/ray-selector implementation",
                script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), results=rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
