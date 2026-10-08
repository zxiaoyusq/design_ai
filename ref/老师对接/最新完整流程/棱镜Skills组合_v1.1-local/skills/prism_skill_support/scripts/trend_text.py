"""Freeze text, check complete membership/support, rank and export H01 text inputs.
Semantic judgements must be supplied by an actual analyst/model, never by this script.
"""
from pathlib import Path
from collections import Counter
import argparse,csv,json
from io_utils import read,write,fresh,ref,digest

def rows_from(path):
    p=Path(path)
    if p.suffix.lower()=='.csv':
        with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
    if p.suffix.lower()=='.jsonl':return [json.loads(x) for x in p.read_text(encoding='utf-8-sig').splitlines() if x.strip()]
    d=read(p);return d if isinstance(d,list) else d['records']
def prepare(path,out,batch_size=64):
    rows=rows_from(path);ids=set();normal=[]
    for raw in rows:
        aid=str(raw.get('article_id','')).strip()
        if not aid or aid in ids:raise ValueError('Unique article_id required')
        ids.add(aid);title=raw.get('title') or '';summary=raw.get('summary') or ''
        if not isinstance(title,str) or not isinstance(summary,str):raise ValueError('Title and summary must be text')
        kind=raw.get('text_kind','source_paraphrase')
        if kind not in ('source_paraphrase','original_text','original_text_excerpt'):raise ValueError('Explicit text_kind required')
        urls=raw.get('image_urls',[])
        if isinstance(urls,str):urls=json.loads(urls) if urls.strip().startswith('[') else [x.strip() for x in urls.splitlines() if x.strip()]
        if not isinstance(urls,list) or not all(isinstance(u,str) for u in urls):raise ValueError('image_urls must be a string array')
        normal.append({**raw,'article_id':aid,'title':title,'summary':summary,'text_kind':kind,'image_urls':urls,'text':title+'\n'+summary,'source_group_id':raw.get('source_group_id') or 'article:'+aid,'claim_origin_id':raw.get('claim_origin_id') or 'article:'+aid})
    source=read(path) if Path(path).suffix.lower()=='.json' else None
    mode=source.get('dataset_mode','real_or_public') if isinstance(source,dict) else 'real_or_public'
    folder=fresh(out);corpus={'schema_version':'prism.portable_text_corpus.v1','dataset_mode':mode,'input_ref':ref(path),'records':normal,'image_calls':0};write(folder/'corpus.json',corpus)
    if not 1<=batch_size<=256:raise ValueError('batch_size 1..256')
    for start in range(0,len(normal),batch_size):
        # Image references are deliberately absent from semantic packets.
        rows=[{k:r.get(k) for k in ('article_id','title','summary','tags','text_kind','source_group_id','claim_origin_id','detail_url','published_at')} for r in normal[start:start+batch_size]]
        write(folder/'batches'/f'batch-{start//batch_size+1:04}.json',{'corpus_digest':digest(corpus),'records':rows,'stage':'text_only_catalogue_or_assignment','visual_certification':False})
    write(folder/'proposal-template.json',{'corpus_digest':digest(corpus),'analyst':{'actor_id':'record actual analyst','model':'unknown'},'themes':[],'assignments':[]})
    return {'records':len(normal),'batches':(len(normal)+batch_size-1)//batch_size,'out':str(folder),'model_calls':0}
def compile_run(corpus_path,proposal_path,review_path,out):
    corpus=read(corpus_path);proposal=read(proposal_path);review=read(review_path)
    if proposal.get('corpus_digest')!=digest(corpus):raise ValueError('Proposal bound to another corpus')
    if review.get('proposal_sha256')!=ref(proposal_path)['sha256']:raise ValueError('Review bound to another proposal')
    for obj in (proposal,review):
        who=obj.get('analyst') or obj.get('reviewer')
        if not isinstance(who,dict) or not who.get('actor_id'):raise ValueError('Actual analyst/reviewer identity required')
    records={r['article_id']:r for r in corpus['records']};themes={r['theme_id']:r for r in proposal['themes']}
    if len(themes)!=len(proposal['themes']):raise ValueError('Duplicate theme identity')
    for t in themes.values():
        if not all(isinstance(t.get(k),str) and t[k].strip() for k in ('theme_id','title','definition','boundary','design_question')):raise ValueError('Theme meaning and boundary required')
    assigns={r['article_id']:r for r in proposal['assignments']};reviews={r['article_id']:r for r in review['reviews']}
    if len(assigns)!=len(proposal['assignments']) or set(assigns)!=set(records):raise ValueError('Every original article must have exactly one primary disposition')
    assigned={i for i,a in assigns.items() if a.get('theme_id') is not None}
    if len(reviews)!=len(review['reviews']) or set(reviews)!=assigned:raise ValueError('All proposed primary assignments need an actual support review')
    accepted={};coverage=[]
    for aid,a in assigns.items():
        if not a.get('reason'):raise ValueError('Disposition reason required')
        tid=a.get('theme_id')
        if tid is None:coverage.append({'article_id':aid,'primary_theme_id':None,'status':'unassigned','reason':a['reason']});continue
        if tid not in themes or not a.get('anchor') or a['anchor'] not in records[aid]['text']:raise ValueError('Missing/foreign assignment text anchor')
        r=reviews[aid]
        if r.get('theme_id')!=tid or r.get('status') not in ('supported','uncertain','unsupported') or not r.get('reason'):raise ValueError('Support review identity/status/reason invalid')
        if not r.get('anchor') or r['anchor'] not in records[aid]['text']:raise ValueError('Support review text anchor missing')
        if r['status']=='supported':accepted[aid]=tid
        coverage.append({'article_id':aid,'primary_theme_id':tid if r['status']=='supported' else None,'candidate_theme_id':tid,'status':r['status'],'reason':r['reason'],'anchor':r['anchor']})
    folder=fresh(out);evidence=[];articles=[]
    for aid,r in records.items():
        sid='ARTICLE:'+aid;eid='TEXT:'+aid;url=r.get('detail_url') or r.get('source_url')
        evidence.append({'evidence_id':eid,'source_id':sid,'source_group_id':r['source_group_id'],'claim_origin_id':r['claim_origin_id'],'text':r['text'],'text_kind':r['text_kind'],'locator':{'article_id':aid},'source_url':url,'original_text_excerpt':r['text'] if r['text_kind']!='source_paraphrase' else None})
        articles.append({'source_id':sid,'title':r['title'],'source_url':url,'publisher_group':r['source_group_id']})
    clusters=[];rank=[]
    for tid,t in themes.items():
        ids=[aid for aid,label in accepted.items() if label==tid]
        row={'theme_id':tid,'title':t['title'],'definition':t['definition'],'boundary':t['boundary'],'supported_primary_articles':len(ids),'unique_detail_urls':len({records[i].get('detail_url') for i in ids if records[i].get('detail_url')}),'member_article_ids':ids}
        rank.append(row)
        if not ids:continue
        clusters.append({'cluster_id':tid,'title':t['title'],'definition':t['definition'],'design_question':t['design_question'],'boundaries':{'shared_design_mechanism':t['definition'],'includes':[t['definition']],'excludes':[t['boundary']]},'evidence_refs':['TEXT:'+i for i in ids],'source_ids':['ARTICLE:'+i for i in ids],'source_group_ids':sorted({records[i]['source_group_id'] for i in ids}),'claim_origin_ids':sorted({records[i]['claim_origin_id'] for i in ids}),'hypotheses':[],'unknowns':['Source text may be imported paraphrases; photos have not been analysed.'],'semantic_truth_verified':False})
    rank.sort(key=lambda r:(-r['supported_primary_articles'],-r['unique_detail_urls'],r['theme_id']))
    for i,r in enumerate(rank,1):r['rank']=i
    mode=corpus.get('dataset_mode','real_or_public')
    write(folder/'trend-clusters.json',{'schema_version':'prism.trends.semantic_clusters.v0.1','dataset_mode':mode,'clusters':clusters})
    write(folder/'text-catalogue.json',{'dataset_mode':mode,'evidence':evidence,'articles':articles})
    write(folder/'ranking.json',{'rule':'supported_primary_articles desc, unique_detail_urls desc, theme_id asc','meaning':'Corpus size only; not market heat or visual coherence','directions':rank})
    write(folder/'coverage.json',coverage);write(folder/'source-records.json',corpus)
    write(folder/'manifest.json',{'inputs':[ref(corpus_path),ref(proposal_path),ref(review_path)],'records':len(records),'statuses':dict(Counter(r['status'] for r in coverage)),'reviewer':review['reviewer'],'new_model_calls':0,'semantic_accuracy_proven':False})
    return {'out':str(folder),'supported_primary':len(accepted),'H01_text_clusters':len(clusters),'all_original_records_retained':True,'model_calls':0}
if __name__=='__main__':
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('prepare');a.add_argument('--input',required=True);a.add_argument('--out',required=True);a.add_argument('--batch-size',type=int,default=64)
    a=sub.add_parser('compile');a.add_argument('--corpus',required=True);a.add_argument('--proposal',required=True);a.add_argument('--review',required=True);a.add_argument('--out',required=True)
    a=p.parse_args();result=prepare(a.input,a.out,a.batch_size) if a.command=='prepare' else compile_run(a.corpus,a.proposal,a.review,a.out);print(json.dumps(result,ensure_ascii=False))
