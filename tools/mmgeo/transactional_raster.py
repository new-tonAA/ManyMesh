#!/usr/bin/env python3
"""CPU research implementation of reversible fragment transactions.

Retains ALL depth layers, not just the closest K. An edit removes fragments by stable face ID,
adds rerasterized faces, then resolves only intersecting tiles. Transactions are versioned;
stale commits/undo are rejected. No novelty or real-time claim. Memory can grow with overdraw.
"""
from dataclasses import dataclass
import math
import numpy as np


@dataclass
class Tile:
    pixels: np.ndarray
    faces: np.ndarray
    depths: np.ndarray

    @property
    def nbytes(self):
        return self.pixels.nbytes+self.faces.nbytes+self.depths.nbytes


def empty_tile():
    return Tile(np.empty(0,dtype=np.int64),np.empty(0,dtype=np.int64),np.empty(0))


def face_fragments(triangle,size,scale,rect=None):
    a,b,c=triangle
    area=(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    if abs(area)<1e-14:
        return np.empty(0,dtype=np.int64),np.empty(0)
    lo=triangle[:,:2].min(0); hi=triangle[:,:2].max(0)
    n=size*scale
    left=max(0,math.ceil(lo[0]*scale-.5)); right=min(n,math.floor(hi[0]*scale-.5)+1)
    top=max(0,math.ceil(lo[1]*scale-.5)); bottom=min(n,math.floor(hi[1]*scale-.5)+1)
    if rect is not None:
        left=max(left,rect[0]*scale); top=max(top,rect[1]*scale)
        right=min(right,rect[2]*scale); bottom=min(bottom,rect[3]*scale)
    if left>=right or top>=bottom:
        return np.empty(0,dtype=np.int64),np.empty(0)
    yy,xx=np.mgrid[top:bottom,left:right]
    dx,dy=(xx+.5)/scale-a[0],(yy+.5)/scale-a[1]
    u=(dx*(c[1]-a[1])-dy*(c[0]-a[0]))/area
    v=((b[0]-a[0])*dy-(b[1]-a[1])*dx)/area
    inside=(u>=-1e-10)&(v>=-1e-10)&(u+v<=1+1e-10)
    depth=a[2]+u*(b[2]-a[2])+v*(c[2]-a[2])
    return (yy*n+xx)[inside],depth[inside]


@dataclass
class Transaction:
    version: int
    affected: tuple
    before: dict
    after: dict
    owner: object
    consumed: bool=False
    committed_version: int=-1


class FragmentCache:
    def __init__(self,projected,triangles,size,scale,tile_size=8):
        if size<1 or scale<1 or tile_size<1:
            raise ValueError('positive dimensions required')
        self.size=size; self.scale=scale; self.n=size*scale
        self.tile_size=tile_size*scale
        self.tile_cols=(self.n+self.tile_size-1)//self.tile_size
        self.tiles={}; self.face_tiles={}; self.version=0
        pending={}
        for face,tri in enumerate(projected[triangles]):
            pix,depth=face_fragments(tri,size,scale)
            ids=self.tile_ids(pix)
            self.face_tiles[face]=set(np.unique(ids).tolist())
            for tile in self.face_tiles[face]:
                keep=ids==tile
                pending.setdefault(tile,[]).append(Tile(pix[keep],
                    np.full(np.count_nonzero(keep),face,dtype=np.int64),depth[keep]))
        for tile,parts in pending.items():
            self.tiles[tile]=self.concatenate(parts)
        self.reference_fragments=sum(len(t.pixels) for t in self.tiles.values())

    @staticmethod
    def concatenate(parts):
        return Tile(*(np.concatenate([getattr(p,name) for p in parts])
                      for name in ('pixels','faces','depths'))) if parts else empty_tile()

    def tile_ids(self,pixels):
        return ((pixels//self.n)//self.tile_size)*self.tile_cols+(pixels%self.n)//self.tile_size

    @property
    def array_bytes(self):
        # Explicitly excludes Python objects, dictionary/set overhead and temporary transactions.
        return sum(t.nbytes for t in self.tiles.values())

    def propose(self,affected,replacement_triangles):
        """replacement_triangles maps surviving stable face IDs to three projected vertices."""
        affected=tuple(sorted(set(int(x) for x in affected)))
        if not set(replacement_triangles).issubset(affected):
            raise ValueError('replacement face outside removal support')
        touched=set()
        for face in affected: touched.update(self.face_tiles.get(face,()))
        additions={}
        for face,tri in replacement_triangles.items():
            pix,depth=face_fragments(np.asarray(tri),self.size,self.scale)
            ids=self.tile_ids(pix)
            for tile in np.unique(ids):
                tile=int(tile); touched.add(tile); mask=ids==tile
                additions.setdefault(tile,[]).append(Tile(pix[mask],
                    np.full(np.count_nonzero(mask),face,dtype=np.int64),depth[mask]))
        before={}; after={}
        for tile in touched:
            old=self.tiles.get(tile,empty_tile()); before[tile]=old
            keep=~np.isin(old.faces,affected)
            parts=[Tile(old.pixels[keep],old.faces[keep],old.depths[keep])]
            parts.extend(additions.get(tile,[]))
            after[tile]=self.concatenate(parts)
        return Transaction(self.version,affected,before,after,self)

    def resolve(self,rect,transaction=None):
        if transaction is not None and (transaction.owner is not self or transaction.consumed or
                                        transaction.version!=self.version):
            raise ValueError('foreign, stale or consumed transaction')
        x0,y0,x1,y1=(x*self.scale for x in rect)
        w=x1-x0; h=y1-y0
        depths=np.full(w*h,-np.inf)
        for ty in range(y0//self.tile_size,(y1-1)//self.tile_size+1):
            for tx in range(x0//self.tile_size,(x1-1)//self.tile_size+1):
                key=ty*self.tile_cols+tx
                tile=(transaction.after[key] if transaction is not None and key in transaction.after
                      else self.tiles.get(key))
                if tile is None: continue
                yy=tile.pixels//self.n; xx=tile.pixels%self.n
                keep=(xx>=x0)&(xx<x1)&(yy>=y0)&(yy<y1)
                pixels=(yy[keep]-y0)*w+xx[keep]-x0
                np.maximum.at(depths,pixels,tile.depths[keep])
        depths=depths.reshape(h,w); cover=np.isfinite(depths)
        return np.stack((cover.astype(float),np.where(cover,depths,0.)),axis=-1)

    def resolve_edit(self,rect,affected,replacements):
        """Read-only on-demand candidate resolution; no full transaction allocation."""
        if not set(replacements).issubset(affected):
            raise ValueError('replacement face outside removal support')
        x0,y0,x1,y1=(x*self.scale for x in rect)
        w=x1-x0; h=y1-y0; depths=np.full(w*h,-np.inf)
        for ty in range(y0//self.tile_size,(y1-1)//self.tile_size+1):
            for tx in range(x0//self.tile_size,(x1-1)//self.tile_size+1):
                tile=self.tiles.get(ty*self.tile_cols+tx)
                if tile is None: continue
                yy=tile.pixels//self.n; xx=tile.pixels%self.n
                keep=(xx>=x0)&(xx<x1)&(yy>=y0)&(yy<y1)&~np.isin(tile.faces,affected)
                np.maximum.at(depths,(yy[keep]-y0)*w+xx[keep]-x0,tile.depths[keep])
        for tri in replacements.values():
            pixels,values=face_fragments(np.asarray(tri),self.size,self.scale,rect)
            yy=pixels//self.n; xx=pixels%self.n
            np.maximum.at(depths,(yy-y0)*w+xx-x0,values)
        depths=depths.reshape(h,w); cover=np.isfinite(depths)
        return np.stack((cover.astype(float),np.where(cover,depths,0.)),axis=-1)

    def _replace(self,tiles,affected):
        for face in affected: self.face_tiles[face]=set()
        for key,tile in tiles.items():
            if len(tile.pixels): self.tiles[key]=tile
            else: self.tiles.pop(key,None)
            # Only changed faces need ownership updates; unaffected owners never moved.
            for face in np.intersect1d(np.unique(tile.faces),affected):
                self.face_tiles[int(face)].add(key)

    def commit(self,transaction):
        if transaction.owner is not self or transaction.consumed or transaction.version!=self.version:
            raise ValueError('foreign, stale or consumed transaction')
        self._replace(transaction.after,transaction.affected)
        self.version+=1
        transaction.consumed=True; transaction.committed_version=self.version

    def undo(self,transaction):
        if transaction.owner is not self or transaction.committed_version!=self.version:
            raise ValueError('undo requires the most recent committed transaction')
        self._replace(transaction.before,transaction.affected)
        self.version+=1
        transaction.committed_version=-1
