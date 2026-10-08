"""Portable access to frozen local quality and H2 validators. No model execution."""
from pathlib import Path
import argparse,importlib,inspect,json,sys
from io_utils import read,write,ref,resolve

SUPPORT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SUPPORT/'runtime'))
ALIASES={'quality':'prism_sidecars.quality_selected_target_v2.protocol','r5':'prism_runtime.clustering.r5_dual_v2.adapter','alias-r5':'prism_runtime.clustering.r5_exact_byte_alias_v1.adapter','id':'prism_runtime.clustering.id_reference_board_v5.protocol','cmf':'prism_runtime.clustering.cmf_reference_board_v4.protocol'}
OPERATIONS={'quality':['prepare','build_request','validate_grant','accept','clustering_view'],'r5':['load_record','adapt_r5'],'alias-r5':['load_record'],'id':['prepare','current','grouping_view','grouping_template','accept_grouping','prepare_board_review','board_review_template','accept_board_review'],'cmf':['prepare','current','grouping_view','grouping_template','accept_grouping','prepare_board_review','board_review_template','accept_board_review']}
def module(name):
    if name in ('alias-id','alias-cmf'):
        from prism_runtime.clustering.r5_exact_byte_alias_v1 import consumer
        m=consumer('ID' if name=='alias-id' else 'CMF');return importlib.import_module(m.__name__+'.protocol')
    return importlib.import_module(ALIASES[name])
def arguments(v,base):
    if isinstance(v,dict):
        if set(v)=={'$json'}:return read(resolve(v['$json'],base))
        if set(v)=={'$ref'}:return ref(resolve(v['$ref'],base))
        return {k:arguments(x,base) for k,x in v.items()}
    if isinstance(v,list):return [arguments(x,base) for x in v]
    return v
def describe(name):
    m=module(name);key=name.replace('alias-','') if name in ('alias-id','alias-cmf') else name
    return {k:str(inspect.signature(getattr(m,k))) for k in OPERATIONS[key]}
def doctor():
    from prism_runtime.clustering.r5_dual_v2.adapter import producer
    from prism_runtime.clustering.id_reference_board_v5.common import pins as idpins
    from prism_runtime.clustering.cmf_reference_board_v4.common import pins as cmfpins
    from prism_runtime.clustering.r5_exact_byte_alias_v1.registry import dependencies
    engine=producer();idpins();cmfpins();dependencies()
    return {'runtime_pins_verified':True,'R5_normalizer_loaded':True,'active_dictionary_fields':len(engine.ACTIVE),'quality_executor_label':module('quality').ROOT_THREAD,'new_model_calls':0,'APIs':{k:describe(k) for k in ('quality','r5','alias-r5','id','cmf','alias-id','alias-cmf')}}
def main():
    a=argparse.ArgumentParser();a.add_argument('operation',choices=['doctor','describe','call']);a.add_argument('--module',choices=[*ALIASES,'alias-id','alias-cmf']);a.add_argument('--method');a.add_argument('--args',type=Path);a.add_argument('--out',type=Path);args=a.parse_args()
    if args.operation=='doctor':result=doctor()
    elif args.operation=='describe':result=describe(args.module)
    else:
        if not args.out or not args.args:raise ValueError('call requires --args and fresh --out')
        if args.out.exists():raise ValueError('Output already exists')
        if args.method not in describe(args.module):raise ValueError('Operation not exposed')
        data=arguments(read(args.args),args.args.resolve().parent)
        result=getattr(module(args.module),args.method)(**data)
    if args.out:write(args.out,result)
    print(json.dumps(result if args.operation!='call' else {'written':str(args.out),'new_model_calls':0},ensure_ascii=False))
if __name__=='__main__':main()
