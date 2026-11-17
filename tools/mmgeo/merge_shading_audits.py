#!/usr/bin/env python3
"""Merge separately evaluated policies only when source/raster/shading/cameras agree."""
import argparse
import hashlib
import json
from pathlib import Path


def shared_inputs(data):
    return {key:value for key,value in data['inputHashes'].items()
            if 'filter-real-candidates' in Path(key).parts or
            Path(key).name in ('depth_candidate_pilot.py','evaluate_shading_controls.py')}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('inputs',nargs='+',type=Path);ap.add_argument('--out',required=True,type=Path)
    args=ap.parse_args();result=None;provenance={}
    for path in args.inputs:
        data=json.loads(path.read_text());provenance[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        if result is None:
            result=data;continue
        if (data['scope'],data['ratio'],data['sourceTriangles'])!=(result['scope'],result['ratio'],result['sourceTriangles']):
            raise ValueError('audit configuration mismatch')
        if shared_inputs(data)!=shared_inputs(result):raise ValueError('source/implementation mismatch')
        expected=[v['angle'] for v in next(iter(result['policies'].values()))['views']]
        for key,row in data['policies'].items():
            if key in result['policies']:raise ValueError('duplicate policy input')
            if [v['angle'] for v in row['views']]!=expected:raise ValueError('camera populations differ')
            result['policies'][key]=row
        for key,value in data['inputHashes'].items():
            if key in result['inputHashes'] and result['inputHashes'][key]!=value:
                raise ValueError('conflicting input hashes')
            result['inputHashes'][key]=value
    result['mergedAudits']=provenance
    result['mergeScriptSha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
