#!/usr/bin/env python3
"""Replay source-area normal moments through saved collapse history.

Classical attribute-transfer control, not a novel metric or original authored-normal export.
Replay validates BOTH geometric positions and connectivity against the saved checkpoint.
"""
import json
from pathlib import Path

import numpy as np


def transfer(capture_path,manifest,ratio,positions,triangles):
    data=json.loads(Path(capture_path).read_text())
    source_positions=[];source_faces=[];offsets={};vo=0
    for ui,unit in enumerate(data['units']):
        if not unit['triangles']:continue
        ps=np.asarray(unit['positions'],float);fs=np.asarray(unit['triangles'],int)
        offsets[ui]=(vo,ps)
        source_positions.extend(ps);source_faces.extend(fs+vo);vo+=len(ps)
    source_positions=np.asarray(source_positions);source_faces=np.asarray(source_faces)
    if len(positions)!=len(source_positions):raise ValueError('checkpoint vertex layout differs')
    moment=np.zeros_like(source_positions);tri=source_positions[source_faces]
    face_normal=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
    for column in range(3):np.add.at(moment,source_faces[:,column],face_normal)
    replay_positions=source_positions.copy();replay_faces=source_faces.copy();count=0
    for unit in manifest['units']:
        ui=unit['unit'];offset,ps=offsets[ui]
        center=(ps.min(0)+ps.max(0))*.5
        radius=max(float(np.linalg.norm(ps-center,axis=1).max()),1e-12)
        if 'levels' in unit:
            applied=next(level['applied'] for level in unit['levels'] if level['ratio']==float(ratio))
        else:
            checkpoint=next(c for c in manifest['checkpoints'] if c['ratio']==float(ratio))
            applied=next(level['applied'] for level in checkpoint['levels'] if level['unit']==ui)
        for action in unit['actions'][:applied]:
            keep,remove=offset+action['keep'],offset+action['remove']
            np.testing.assert_allclose((replay_positions[keep]-center)/radius,action['oldKeep'],atol=1e-11,rtol=1e-11)
            np.testing.assert_allclose((replay_positions[remove]-center)/radius,action['oldRemove'],atol=1e-11,rtol=1e-11)
            replay_positions[keep]=center+radius*np.asarray(action['target'])
            replay_faces[replay_faces==remove]=keep
            moment[keep]+=moment[remove];moment[remove]=0.;count+=1
    alive=(replay_faces[:,0]!=replay_faces[:,1])&(replay_faces[:,1]!=replay_faces[:,2])&(replay_faces[:,2]!=replay_faces[:,0])
    np.testing.assert_array_equal(replay_faces[alive],triangles)
    np.testing.assert_allclose(replay_positions[np.unique(triangles)],positions[np.unique(triangles)],atol=1e-11,rtol=1e-11)
    lengths=np.linalg.norm(moment,axis=1)
    normals=np.divide(moment,lengths[:,None],out=np.zeros_like(moment),where=lengths[:,None]>1e-15)
    return normals,dict(replayedCollapses=count,zeroMomentUsedVertices=int(np.sum(lengths[np.unique(triangles)]<=1e-15)))
