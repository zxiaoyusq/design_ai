"""Freeze a scoped self-assessment for the independent loop owner."""
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json
from .export_examples import OUTPUT,WORKSPACE,EXPERIMENTS
from .policy import VERSION

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main():
    module=Path(__file__).resolve().parent;current=EXPERIMENTS/'designer-boards-round2-v06'
    checks=load(OUTPUT/'verification.json');ui=load(current/'ui-checks.json');summary=load(current/'summary.json')
    assert checks['success'] and ui['success']
    examples=load(OUTPUT/'examples-index.json')
    code=[p for p in sorted(module.iterdir()) if p.is_file() and p.suffix in ['.py','.md']]
    artifacts=[current/n for n in ['RELEASE.json','summary.json','report.html','resolved-manifest.json','freeze.json','prompt-v0.5.txt','prior-gold-regression.json','ui-checks.json']]
    inputs=[Path(x['input']) for x in examples];outputs=[Path(x['output']) for x in examples]
    sources=[Path(x['existing_result']) for x in examples if Path(x['existing_result']).is_file()]
    manifest=[{'path':str(p),'sha256':sha(p)} for p in code+artifacts+inputs+outputs+sources]
    dump(OUTPUT/'delivery-hashes.json',manifest)
    limits=[
        '算法效果仅达到设计师正样本校准；缺设计师负样本及独立未调参盲测，不能声称整体准确率/负例拦截率合格。',
        '旧138张、本组16板及103画面均用于调参；白T恤未被设计师标负，仅作边界探针。',
        '复核后的对照理由仍含独特/创新措辞；材料/工艺/细结构陈述有图像证据限制，保留原话并未实物验证。',
        '接口是离线既有结果适配与复核组合，未集成生产API调用、身份映射服务或正式库写入。',
        '校准素材不可伪装为真实趋势源；用研/生成/未知源绕过。当前合成趋势夹具只证明接口边界。',
    ]
    command='"C:/Users/Admin/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe" -B -X utf8 -m prism_runtime.quality.verify'
    handoff={
        'module':'quality','owner_thread_id':'01a0dbe0-1fa5-7bd1-95e7-6363a4cef078',
        'status':'partial','contract_version':'0.1','algorithm_version':VERSION,
        'interface_status':'ready','algorithm_effect_status':'positive_calibration_pass_negative_and_holdout_unverified',
        'assessed_scope':'可独立验收离线路由/原判定导出/复核组合；整体高级感算法不宣称已通过业务验收。',
        'entrypoint':'python -m prism_runtime.quality --image <ImageDNA-or-metadata.json> --result <saved-result.json> [--calibration-only]',
        'entrypoints':{'import':'prism_runtime.quality.adapt_file; prism_runtime.quality.route_quality',
                      'policy':'prism_runtime.quality.policy.resolve',
                      'examples':'python -m prism_runtime.quality.export_examples','verify':command},
        'files':[str(p) for p in code],
        'fixture_or_existing_output':[str(OUTPUT/'examples-index.json'),str(current/'resolved-manifest.json')],
        'verification':{'command':command,'result':'PASS: 16 tests, 0 skipped, 9 exact example replays; 138 old positives and 119 new saved decisions verified offline.',
                        'record':str(OUTPUT/'verification.json')},
        'new_paid_calls':0,'paid_call_scope':'Interface/loop delivery introduces zero calls. User-authorized calibration round already completed 119 primary + 5 explicit confirmation calls.',
        'prior_user_authorized_calibration_calls':124,'prior_calibration_tokens':summary['usage']['total_tokens'],
        'limitations':limits,'hash_manifest':str(OUTPUT/'delivery-hashes.json'),
        'self_assessment':str(OUTPUT/'self-assessment.json'),
        'input_examples':[str(p) for p in inputs],'output_examples':[str(p) for p in outputs],
        'report':str(current/'report.html'),'release':str(current/'RELEASE.json'),
        'contract_notes':[
            '成功的trend输出使用prism.trend_quality.v0.1；非适用/错误/校准输出使用prism.quality_route.v0.1附加状态。',
            '校准导出保留source_kind=calibration, applicable=false, production_admission=false。',
            'error/invalid_output/needs_confirmation 的decision=null，不得纳入审美FAIL。',
            '不同模块image_id必须由上游提供真实映射；本模块拒绝静默换号。',
        ],
    }
    assessment={
        'module':'quality','owner_thread_id':handoff['owner_thread_id'],'status':'partial',
        'assessed_scope':handoff['assessed_scope'],'algorithm_version':VERSION,
        'entrypoint':handoff['entrypoint'],'input_examples':handoff['input_examples'],'output_examples':handoff['output_examples'],
        'self_assessment':{
            'qualified':False,
            'qualified_scopes':['offline_source_router','existing_verdict_export','bounded_confirmation_policy','designer_positive_calibration'],
            'unqualified_scopes':['overall_quality_discrimination','negative_specificity','unseen_holdout_generalization','production_deployment'],
            'criteria':['非趋势不进正式判标','技术异常不当FAIL','原判定与身份版本可追溯','拼图PASS不能遮蔽子图','调参集不冒充独立盲测'],
            'actual_results':{'offline_tests':checks['tests_run'],'example_replays':len(examples),'ui_checks':ui,
                              'real_calibration':summary['final'],'old_gold_offline_replay':summary['prior_gold']},
            'known_failures':[
                {'image_id':'B08-T04','first':'FAIL','final':'PASS','cause':'明确结构/表面关系被常规产品/独特性语言压低',
                 'primary':str(EXPERIMENTS/'designer-boards-round2/runs/B08-T04/result.json'),
                 'confirmation':str(current/'runs/B08-T04/result.json')},
                {'image_ids':['B07-T04','B08-T03','B11-T01'],'first':'invalid_output: []','final':'PASS',
                 'cause':'HTTP200模型仅返回空数组，3条失败记录仍保存'},
                {'image_id':'control04','remaining':'FAIL理由仍出现独特/创新措辞；未标定负例，不算已证明正确拒绝'},
            ],
        },
        'source_materials':[
            str(EXPERIMENTS/'designer-boards-round2/board-sources.json'),
            str(EXPERIMENTS/'designer-boards-round2/manifest.json'),
            str(EXPERIMENTS/'designer-boards-round2/designer-labels.json'),
            str(EXPERIMENTS/'ee1-cmf-calibration-v052/designer-labels.json'),
            str(EXPERIMENTS/'ee1-cmf-calibration-v052/manifest.json'),
            str(WORKSPACE/'docs/prism/跨任务循环执行.md'),str(WORKSPACE/'prism_runtime/CONTRACT.md'),
        ],
        'training_and_tuning_materials':[
            {'set':'EE1 138 images / 140 placements','use':'v0.5 style-bias/partial-reference calibration, offline v0.6 regression'},
            {'set':'16 boards / 103 source frames','use':'first-pass evaluation then v0.6 targeted consistency correction; not independent after tuning'},
            {'set':'12 unlabelled sentinels; control04 targeted confirmation','use':'boundary observation only, no designer negative labels'},
        ],
        'holdout_description':'当前无设计师标定的独立未调参正负留出集。本组在首次运行前已知整组为设计师正标签，发现问题后参与规则修正。',
        'paid_calls_required_for_retest':0,'limitations':limits,
        'handoff_ref':str(OUTPUT/'handoff.json'),
    }
    dump(OUTPUT/'self-assessment.json',assessment);dump(OUTPUT/'handoff.json',handoff)
    completion={'status':'complete','completed_utc':datetime.now(timezone.utc).isoformat(),
                'version':VERSION,'report':str(current/'report.html'),'report_sha256':sha(current/'report.html'),
                'summary_sha256':sha(current/'summary.json'),'new_calls':124,'all_new_designer_images_pass':True,
                'first_attempts_preserved':True,'independent_holdout_validated':False,'production_modified':False,
                'timer_status':'PAUSED','ui_verified':True,'offline_module_tests':checks['tests_run']}
    dump(current/'completion.json',completion)
    previous=EXPERIMENTS/'active-gate.json'
    if not (current/'previous-active-gate.json').exists():
        (current/'previous-active-gate.json').write_bytes(previous.read_bytes())
    dump(previous,{'version':VERSION,'release':str(current/'RELEASE.json'),
                   'scope':'Default for subsequent local calibration/tests only; not production activation',
                   'negative_gold_still_needed':True,'interface_status':'ready','algorithm_business_status':'partial'})
    print(json.dumps({'handoff':str(OUTPUT/'handoff.json'),'status':'partial','interface':'ready','new_paid_calls':0},ensure_ascii=False))

if __name__=='__main__':main()
