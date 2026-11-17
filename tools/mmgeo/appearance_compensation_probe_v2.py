#!/usr/bin/env python3
"""Run the frozen candidate protocol with an explicitly separate geometry-facing renderer."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file))
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module


common=load('facing_probe_common','appearance_compensation_probe.py')
variant=load('facing_probe_variant','normal_fit_control_v2.py')
# Reuse the identical protocol, candidate generation, solve budget and reporting.
# The override is local to this experiment process; the frozen v1 files remain unchanged.
common.m=variant


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=('prepare','measure'))
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    if args.mode=='prepare':
        common.prepare(args);path=args.out/'proposals.json';recipe=json.loads(path.read_text())
        recipe['scope']='eight current legal Torus proposals; classical normal fitting, geometric facing v2'
        recipe['rendererContract']='two-sided orientation from triangle geometry, independent of optimized normals'
        for item in (Path(__file__),Path(variant.base.__file__),Path(variant.base.s.__file__)):
            recipe['inputHashes'][str(item)]=common.digest(item)
        path.write_text(json.dumps(recipe,indent=2)+'\n')
        print('FINAL V2 FROZEN',path,common.digest(path),flush=True)
    else:
        recipe=json.loads((args.out/'proposals.json').read_text())
        if recipe.get('rendererContract')!='two-sided orientation from triangle geometry, independent of optimized normals':
            raise ValueError('requires explicit v2 renderer recipe')
        common.measure(args)


if __name__=='__main__':main()
