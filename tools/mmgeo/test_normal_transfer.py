import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

spec=importlib.util.spec_from_file_location('transfer_test',Path(__file__).with_name('collapse_normal_transfer.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class TransferTests(unittest.TestCase):
    def test_planar_normal_carry_and_geometry_history_validation(self):
        ps=np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0]],float)
        fs=np.array([[0,1,2],[0,2,3]])
        center=np.array([.5,.5,0]);radius=np.sqrt(.5)
        target=np.array([.25,0,0]);out=ps.copy();out[0]=target
        manifest=dict(units=[dict(unit=0,levels=[dict(ratio=.5,applied=1)],actions=[dict(
            keep=0,remove=1,target=((target-center)/radius).tolist(),
            oldKeep=((ps[0]-center)/radius).tolist(),oldRemove=((ps[1]-center)/radius).tolist())])])
        capture=dict(units=[dict(positions=ps.tolist(),triangles=fs.tolist())])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'capture.json';path.write_text(json.dumps(capture))
            normals,report=m.transfer(path,manifest,'0.5',out,np.array([[0,2,3]]))
            np.testing.assert_allclose(normals[[0,2,3]],[[0,0,1]]*3)
            self.assertEqual(report['replayedCollapses'],1)
            with self.assertRaises(AssertionError):
                m.transfer(path,manifest,'0.5',out,np.array([[0,3,2]]))
            wrong=out.copy();wrong[2,2]=.1
            with self.assertRaises(AssertionError):m.transfer(path,manifest,'0.5',wrong,np.array([[0,2,3]]))


if __name__=='__main__':unittest.main()
