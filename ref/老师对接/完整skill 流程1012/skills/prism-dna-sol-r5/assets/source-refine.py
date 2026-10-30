"""Two bounded evidence passes: mixed appearance regions and optical ambiguity.
Original calls/answers are immutable. No teacher answers or target feature values.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
import time
import algorithm as a
import run
from algorithm import ROOT,c

def hp(case,m):
    raw=c.read(ROOT/'calls/P-HP01/answer.json')
    # Names indicating multiple region referents are selected; no Astra values enter input.
    chosen={str(i):x for i,x in enumerate(raw['areas']) if '及' in x['name'] or '与' in x['name']}
    schema=a.schema();area=schema['properties']['areas']['items'];defs=schema['$defs'];defs['appearance_area']=area
    reply=a.obj({'groups':a.obj({k:a.obj({'areas':{'type':'array','minItems':1,'items':{'$ref':'#/$defs/appearance_area'}},
        'evidence':{'type':'string','minLength':2,'maxLength':120}}) for k in chosen})});reply['$defs']=defs
    prompt='''对同一张原图，只补充解析指定的混合外观区域，不重新解析整图、不重建坐标。原结果将多个表面或部件写进一个区域名，可能遗漏了区域内部的CMF差异。
逐groups编号检查其范围内，颜色、纹理或光学外观是否确有不同的子区域。确有差异才拆分，不能因这次要求而强行新增；外壳、支架或同一个部件的名称不保证表面外观一致。输出该组完整的替换areas，原组会被替换而不是累计，故保留其中可靠的旧判断并补齐实际可见差异。不要重复不在指定范围内的其他区域。主体色、材质视觉、光泽、透明度与纹理按原DNA字段和类型填，证据不足为null。纹理visible时逐项检查单元、方向、重复、覆盖等，微观结构不可辨则不要猜。
材料只作外观判断；光照阴影不是固有颜色分区；孔洞与印刷标记不能仅凭同样是黑色合成同一纹理通道。只使用原图，不借产品知识。每组evidence短说保留或拆分的可见依据。\n'''+c.canonical({'selected_groups':chosen,
        'other_regions_do_not_duplicate':[x['name'] for i,x in enumerate(raw['areas']) if str(i) not in chosen],
        'dictionary':a.r3.dictionary_view(a.CMF)})
    start=time.perf_counter();answer,receipt=m.call({'call_id':'H-HP01','prompt':prompt,'schema':reply,
        'image_path':case['path'],'image_sha256':case['sha256'],'timeout_seconds':150,
        'binding':{'stage':'mixed_appearance_recovery','image_id':'HP01','selected_original_area_indices':list(chosen),'teacher_answers_used':False}})
    c.write_new(ROOT/'refined/HP01.json',{'answer':answer,'receipt':receipt,'selected_indices':list(chosen),
        'seconds':round(time.perf_counter()-start,4),'cost':run.cost(receipt)})
    print(c.canonical({'refined':'HP01','schema_valid':receipt['schema_valid'],'seconds':receipt['wall_seconds'],'cost':run.cost(receipt)}),flush=True)

def mc(case,m):
    final=c.read(ROOT/'final/MC01.json')
    target=[f for f in final['local_features'] if f['p']=='OPT-008' or (f['p']=='OPT-007' and f['v']!='不透明')]
    reply=a.obj({'checks':a.obj({str(i):a.obj({'decision':{'type':'string','enum':['supported','unsupported','uncertain']},
        'value':{'anyOf':[a.vs(x['p']),{'type':'null'}]},'evidence':{'type':'string','minLength':2,'maxLength':100}}) for i,x in enumerate(target)})})
    prompt='''只检查下列少量光学判断在原图中有没有真实可见依据。不要重新解析其他特征，也不要从“风挡”“灯罩”等部件名称推断材料会透光。分别注意材料本体透光、透见后方、漫射内部光，与表面高光/反射是不同证据。黑色或红色本身不证明半透明；看不见背景也不能单凭此事强判不透明。OPT-008只有在存在可判断的透射内容时才有依据。
supported时给出该字段在此位置实际可支持的值（允许明确纠正），unsupported或uncertain时value=null。简短说明图像依据，不用复现图片。\n'''+c.canonical({'targets':target,'dictionary':a.r3.dictionary_view(sorted({x['p'] for x in target}))})
    start=time.perf_counter();answer,receipt=m.call({'call_id':'H-MC01','prompt':prompt,'schema':reply,
        'image_path':case['path'],'image_sha256':case['sha256'],'timeout_seconds':120,
        'binding':{'stage':'optical_evidence_check','image_id':'MC01','target_count':len(target),'teacher_answers_used':False}})
    c.write_new(ROOT/'refined/MC01.json',{'answer':answer,'receipt':receipt,'targets':target,
        'seconds':round(time.perf_counter()-start,4),'cost':run.cost(receipt)})
    print(c.canonical({'refined':'MC01','schema_valid':receipt['schema_valid'],'seconds':receipt['wall_seconds'],'cost':run.cost(receipt)}),flush=True)

if __name__=='__main__':
    e=c.read(ROOT/'experiment.json');m=run.transport();cases={x['image_id']:x for x in e['data']}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(hp,cases['HP01'],m),pool.submit(mc,cases['MC01'],m)]
        for f in futures:f.result()
