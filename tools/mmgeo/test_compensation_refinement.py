import copy
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('refine_test',Path(__file__).with_name('refine_compensation_probe.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class RefinementProvenanceTests(unittest.TestCase):
    def test_parent_finalization_deltas_preserve_binding_but_changed_fits_do_not(self):
        partial=dict(id='edge-00',fit=dict(parameters=[.1,.2],fittedSSE=1.2),views=[dict(angle=.4)])
        final=copy.deepcopy(partial);final['fit'].update(deltaFixedSSE=.2,deltaFittedSSE=-.1)
        self.assertEqual(m.case_hash(partial),m.case_hash(final))
        final['fit']['parameters'][0]+=.001
        self.assertNotEqual(m.case_hash(partial),m.case_hash(final))
        other=copy.deepcopy(partial);other['views'][0]['angle']=.5
        self.assertNotEqual(m.case_hash(partial),m.case_hash(other))


if __name__=='__main__':unittest.main()
