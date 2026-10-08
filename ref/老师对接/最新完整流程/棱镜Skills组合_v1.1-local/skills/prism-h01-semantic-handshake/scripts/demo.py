"""Offline synthetic replay of H01, including an explicitly fictional selection."""
import argparse,json
from pathlib import Path
import handshake
from h01_core.common import read,write,digest
p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args()
base=Path(__file__).resolve().parent.parent/'examples'
handshake.prepare(base/'config.synthetic.json',a.out)
run=Path(a.out).resolve();prepared=read(run/'prepared.json')
assert prepared['options']['dataset_mode']=='synthetic_fixture'
reply=read(base/'proposal.synthetic.template.json');reply['request_snapshot']=prepared['request']['request_snapshot']
write(run/'demo-proposal.json',reply);handshake.accept(run,run/'demo-proposal.json')
choices=read(base/'choices.synthetic.json')
confirmation={'status':'confirmed','actor_kind':'synthetic_fixture','actor_id':'package-demo',
    'source_ref':'synthetic:package-demo','candidate_digest':read(run/'accepted.json')['workflow_candidates']['digest'],
    'selection_digest':digest(choices)}
write(run/'demo-confirmation.json',confirmation)
handshake.select(run,base/'choices.synthetic.json',run/'demo-confirmation.json')
print(json.dumps(handshake.verify_run(run),ensure_ascii=False,indent=2))
