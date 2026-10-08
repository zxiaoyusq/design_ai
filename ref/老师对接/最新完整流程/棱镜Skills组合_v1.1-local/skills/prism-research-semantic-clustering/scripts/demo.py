"""Offline synthetic replay; not a fresh semantic-model assessment."""
import argparse,json
from pathlib import Path
import research
p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args()
base=Path(__file__).resolve().parent.parent/'examples'
result=research.prepare_run(a.out,base/'research-input.synthetic.json')
run=Path(a.out).resolve()
proposal=research.p.read(base/'proposal.synthetic.template.json')
assert proposal['analyst']['actor_kind']=='synthetic_fixture'
proposal['input_binding']=research.p.bind(run/'dataset')
research.p.write(run/'demo-proposal.json',proposal)
research.accept(run,run/'demo-proposal.json')
print(json.dumps(research.verify(run),ensure_ascii=False,indent=2))
