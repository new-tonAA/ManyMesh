#!/usr/bin/env python3
"""Losslessly add unused normal/UV fields expected by the image scorer."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import numpy as np

HEADER = ("ply\nformat binary_little_endian 1.0\n"
          "element vertex {n}\n"
          "property float x\nproperty float y\nproperty float z\n"
          "property float nx\nproperty float ny\nproperty float nz\n"
          "property float s\nproperty float t\n"
          "element face {m}\n"
          "property list uchar int vertex_indices\n"
          "property uint material_id\nproperty uint submesh_id\nend_header\n")

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--receipt',type=Path,required=True)
    a=ap.parse_args()
    raw=a.input.read_bytes()
    split=raw.find(b'end_header\n')
    if split<0: raise ValueError('missing PLY header terminator')
    header=raw[:split+len(b'end_header\n')].decode('ascii').splitlines()
    if 'format binary_little_endian 1.0' not in header: raise ValueError('unexpected PLY format')
    n=int(next(x.split()[2] for x in header if x.startswith('element vertex ')))
    m=int(next(x.split()[2] for x in header if x.startswith('element face ')))
    props=[]; in_vertex=False
    for line in header:
        if line.startswith('element '): in_vertex=line.startswith('element vertex ')
        elif in_vertex and line.startswith('property '): props.append(tuple(line.split()[1:]))
    if props != [('float','x'),('float','y'),('float','z')]: raise ValueError(f'unexpected input vertex schema: {props}')
    offset=split+len(b'end_header\n')
    vertex_bytes=n*12; face_bytes=m*21
    if len(raw)-offset != vertex_bytes+face_bytes: raise ValueError('unexpected binary PLY payload length')
    xyz=np.frombuffer(raw,dtype='<f4',count=n*3,offset=offset).reshape(n,3)
    vertices=np.zeros((n,8),dtype='<f4'); vertices[:,:3]=xyz
    faces=raw[offset+vertex_bytes:]
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_bytes(HEADER.format(n=n,m=m).encode('ascii')+vertices.tobytes()+faces)
    d={'input':str(a.input),'input_sha256':sha(a.input),'output':str(a.output),
       'output_sha256':sha(a.output),'vertices':n,'triangles':m,
       'adapter_sha256':sha(Path(__file__).resolve()),
       'scope':'positions and face bytes copied unchanged; zero normal and UV fields are unused by load_binary_ply and the scorer'}
    a.receipt.parent.mkdir(parents=True,exist_ok=True)
    a.receipt.write_text(json.dumps(d,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'vertices':n,'triangles':m,'input_sha256':d['input_sha256'],'output_sha256':d['output_sha256']}))
if __name__=='__main__': main()
