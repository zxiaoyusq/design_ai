"""Extract supplied PPTX text/media and layout associations; never infer preferences."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,posixpath,shutil,zipfile,xml.etree.ElementTree as ET
from io_utils import read,write,fresh,ref,resolve

NS={'a':'http://schemas.openxmlformats.org/drawingml/2006/main','p':'http://schemas.openxmlformats.org/presentationml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
RNS='{http://schemas.openxmlformats.org/package/2006/relationships}'
def extract(config,out):
    config=Path(config).resolve();cfg=read(config);out=fresh(out);records=[];pictures=[];sources=[];people={};units=[]
    for src in cfg['sources']:
        sid,pid=src['source_id'],src['person_id']
        if not sid or not pid or sid in {s['source_id'] for s in sources}:raise ValueError('Unique source_id and person_id required')
        source=resolve(src['path'],config.parent)
        if source.suffix.lower()!='.pptx':raise ValueError('This helper only handles .pptx; use the corresponding document reader for other formats')
        dest=out/'sources'/(hashlib.sha256(source.read_bytes()).hexdigest()+'.pptx');dest.parent.mkdir(exist_ok=True)
        if not dest.exists():shutil.copyfile(source,dest)
        sources.append({'source_id':sid,'label':src.get('label',source.name),'locator':source.name,'evidence_kind':'document_excerpt','original_ref':ref(source),'archive_ref':ref(dest)})
        people[pid]={'person_id':pid,'display_name':src.get('display_name',pid)}
        with zipfile.ZipFile(source) as z:
            rels={r.attrib['Id']:r.attrib['Target'] for r in ET.fromstring(z.read('ppt/_rels/presentation.xml.rels')) if r.attrib.get('TargetMode')!='External'}
            presentation=ET.fromstring(z.read('ppt/presentation.xml'))
            slide_order=[posixpath.normpath(posixpath.join('ppt',rels[s.attrib['{'+NS['r']+'}id']])) for s in presentation.findall('p:sldIdLst/p:sldId',NS)]
            for page,name in enumerate(slide_order,1):
                root=ET.fromstring(z.read(name));relname=str(PurePosixPath(name).parent/'_rels'/(PurePosixPath(name).name+'.rels'))
                mappings={}
                if relname in z.namelist():
                    mappings={r.attrib['Id']:posixpath.normpath(posixpath.join(str(PurePosixPath(name).parent),r.attrib['Target'])) for r in ET.fromstring(z.read(relname)) if r.attrib.get('TargetMode')!='External'}
                for shape in root.findall('.//p:sp',NS):
                    c=shape.find('p:nvSpPr/p:cNvPr',NS);shape_id=c.attrib.get('id','unknown') if c is not None else 'unknown'
                    text='\n'.join(''.join(t.text or '' for t in p.findall('.//a:t',NS)) for p in shape.findall('.//a:p',NS)).strip()
                    if not text:continue
                    uid=f'{sid}-P{page:03}-S{shape_id}'
                    row={'unit_id':uid,'source_id':sid,'person_id':pid,'page':page,'shape_id':shape_id,'text':text,'role':'unclassified','extraction':'pptx_text_shape','not_assumed_interview_verbatim':True}
                    records.append(row);units.append({'unit_id':uid,'person_id':pid,'source_id':sid,'text':text,'kind':'reference','attitude':'unknown','scope':None,'locator':f'page {page}, shape {shape_id}','page':page})
                for shape in root.findall('.//p:pic',NS):
                    c=shape.find('p:nvPicPr/p:cNvPr',NS);blip=shape.find('.//a:blip',NS)
                    key=blip.attrib.get('{'+NS['r']+'}embed') if blip is not None else None
                    if key not in mappings:continue
                    member=mappings[key]
                    if not member.startswith('ppt/media/'):continue
                    info=z.getinfo(member)
                    if info.file_size>50*1024*1024:raise ValueError('Oversized media; handle explicitly')
                    body=z.read(member);digest=hashlib.sha256(body).hexdigest();asset=out/'media'/(digest+PurePosixPath(member).suffix);asset.parent.mkdir(exist_ok=True)
                    if not asset.exists():asset.write_bytes(body)
                    crop=shape.find('.//a:srcRect',NS);transform=shape.find('.//a:xfrm',NS)
                    pictures.append({'source_id':sid,'person_id':pid,'page':page,'shape_id':c.attrib.get('id') if c is not None else None,'original_media_ref':ref(asset),'crop_OOXML':crop.attrib if crop is not None else {},'transform_OOXML':ET.tostring(transform,encoding='unicode') if transform is not None else None,'association_role':'layout_candidate_only_not_preference','pixels_rendered':False})
    write(out/'raw-evidence.jsonl',''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in records));write(out/'picture-occurrences.jsonl',''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in pictures))
    public_sources=[{k:s[k] for k in ('source_id','label','locator','evidence_kind')} for s in sources]
    write(out/'research-input.draft.json',{'schema_version':'prism.research_semantic_input.v1','dataset_id':cfg['dataset_id'],'dataset_mode':cfg.get('dataset_mode','real_or_public'),'people':list(people.values()),'sources':public_sources,'units':units})
    write(out/'manifest.json',{'sources':sources,'text_shapes':len(records),'picture_occurrences':len(pictures),'role_classification_complete':False,'page_rendering_complete':False,'draft_has_no_inferred_preferences':True,'new_model_calls':0})
    return {'out':str(out),'text_shapes':len(records),'picture_occurrences':len(pictures),'next':'Inspect original pages; classify questions/options/answers and create reviewed research-input.json; the draft is not finished semantic evidence.'}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--out',required=True);a=p.parse_args();print(json.dumps(extract(a.config,a.out),ensure_ascii=False))
