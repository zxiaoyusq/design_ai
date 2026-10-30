"""Exercise the optional consumer on a full synthetic native CMF fixture."""
from pathlib import Path
from copy import deepcopy
import json,os,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'skills/prism_skill_support/runtime'))
from prism_runtime.clustering.cmf_reference_board_v4 import fixtures as f
from prism_runtime.clustering.h2_original_negative_future_ref_v1 import consumer,derive_future_references
from prism_runtime.clustering.id_reference_board_v5.common import checked

class OptionalFutureConsumer(unittest.TestCase):
 def test_only_reference_guard_changes(self):
  root=Path(os.environ.get('PRISM_TEST_ROOT',str(ROOT.parent/'future-test-work')));root.mkdir(parents=True,exist_ok=True)
  with tempfile.TemporaryDirectory(dir=root,prefix='future-') as name:
   p=Path(name);args=f.build(p/'input');base=consumer('CMF');prepared=base.prepare(**args)
   trace=f.save(p/'trace.json',{'synthetic_fixture':True,'actual_model_calls':0});proposal=f.proposal(prepared,trace)
   proposal['negative_dispositions'][0]['deferred_obligation_indices']=[]
   pr=f.save(p/'proposal.json',proposal)
   with self.assertRaisesRegex(ValueError,'future_negative_must_retain_original_obligation'):base.accept_grouping(prepared,pr)
   doc=derive_future_references(prepared,pr);fr=f.save(p/'future.json',doc)
   result=consumer('CMF',future_reference_ref=fr).accept_grouping(prepared,pr)
   self.assertEqual(result['negative_audit'],prepared['brief']['negative_audit'])
   self.assertEqual(result['deferred_obligations'],prepared['brief']['deferred_obligations'])
   self.assertEqual(result['negative_dispositions'],checked(pr)['negative_dispositions'])
   self.assertFalse(result['original_negative_future_reference']['document']['references'][0]['resolved'])
   self.assertFalse(result['visual_pass'])
   bad=deepcopy(doc);bad['references'][0]['resolved']=True;br=f.save(p/'tampered.json',bad)
   with self.assertRaises(ValueError):consumer('CMF',future_reference_ref=br).accept_grouping(prepared,pr)
if __name__=='__main__':unittest.main()
