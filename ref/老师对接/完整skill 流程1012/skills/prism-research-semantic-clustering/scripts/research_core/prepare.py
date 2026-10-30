"""Freeze a small source-bound reading packet. Does not make semantic decisions."""
import argparse
from pathlib import Path
import json
import hashlib
import shutil
from datetime import datetime,timezone

HERE=Path(__file__).resolve().parent
VERSION="prism.research_semantic_clustering.v1"
INPUT_FILES=["semantic-units.jsonl","people.json","raw-evidence.jsonl","picture-contexts.jsonl",
             "image-display-views.jsonl","selection-groups.jsonl","concept-example-links.jsonl","data-contract.json"]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _pairs(items):
    result={}
    for k,v in items:
        if k in result:raise ValueError("duplicate JSON key: "+k)
        result[k]=v
    return result
def _decode(text):
    return json.loads(text,object_pairs_hook=_pairs,parse_constant=lambda s:(_ for _ in ()).throw(ValueError("nonfinite JSON")))
def read(path):return _decode(Path(path).read_text(encoding="utf-8-sig"))
def lines(path):return [_decode(s) for s in Path(path).read_text(encoding="utf-8-sig").splitlines() if s.strip()]
def write(path,value):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()

def bind(dataset):
    dataset=Path(dataset)
    return {"dataset_id":read(dataset/"data-contract.json")["dataset_id"],"files":{f:sha(dataset/f) for f in INPUT_FILES}}

def prepare(dataset,output):
    dataset=Path(dataset).resolve();out=Path(output).resolve();out.mkdir(parents=True,exist_ok=True)
    binding=bind(dataset);units=lines(dataset/"semantic-units.jsonl")
    packet={"schema_version":VERSION,"input_binding":binding,"units":units,"people":read(dataset/"people.json"),
            "instruction":(HERE/"prompts/cluster.md").read_text(encoding="utf-8"),
            "contract":read(HERE/"contract.json"),"semantic_decisions_generated":False}
    write(out/"reading-packet.json",packet)
    write(out/"input-manifest.json",{"created_at":datetime.now(timezone.utc).isoformat(),"dataset_path":str(dataset),
        "input_binding":binding,"unit_count":len(units),"external_model_calls":0,
        "method_files":{str(p.relative_to(HERE)).replace("\\","/"):sha(p) for p in HERE.rglob("*") if p.is_file() and "__pycache__" not in p.parts}})
    print(json.dumps({"status":"reading_packet_ready","units":len(units),"output":str(out)},ensure_ascii=False))
    return binding

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--dataset",required=True);p.add_argument("--output",required=True)
    a=p.parse_args();prepare(a.dataset,a.output)
