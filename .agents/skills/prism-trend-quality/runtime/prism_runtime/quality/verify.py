"""Reproduce module checks using saved outputs, zero API requests."""
from datetime import datetime, timezone
from pathlib import Path
import io, json, unittest
from .export_examples import OUTPUT
from .adapter import adapt_file

def main():
    stream=io.StringIO()
    suite=unittest.defaultTestLoader.loadTestsFromName('prism_runtime.quality.test_quality')
    test=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    checks=[]
    for example in json.loads((OUTPUT/'examples-index.json').read_text(encoding='utf-8')):
        image=json.loads(Path(example['input']).read_text(encoding='utf-8'))
        expected=json.loads(Path(example['output']).read_text(encoding='utf-8'))
        actual=adapt_file(image,example['existing_result'],calibration_only=example['calibration_only'])
        checks.append({'name':example['name'],'identical_output':actual==expected,
                       'status':actual['status'],'decision':actual['decision']})
    result={'checked_utc':datetime.now(timezone.utc).isoformat(),'tests_run':test.testsRun,
            'unit_test_success':test.wasSuccessful(),'skipped':len(test.skipped),
            'example_checks':checks,'new_paid_calls':0,
            'success':test.wasSuccessful() and not test.skipped and all(x['identical_output'] for x in checks),
            'test_log':stream.getvalue()}
    (OUTPUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ['test_log','example_checks']},ensure_ascii=False))
    return 0 if result['success'] else 1

if __name__=='__main__':raise SystemExit(main())
