"""python -m prism_runtime.quality --image metadata.json --result result.json"""
import argparse
import json
from pathlib import Path
from .adapter import adapt_file


def main():
    ap = argparse.ArgumentParser(description='Offline trend-only quality result adapter; zero API calls.')
    ap.add_argument('--image', required=True, help='ImageDNA or image metadata JSON with explicit source_kind')
    ap.add_argument('--result', required=True, help='Saved quality result; never read for ineligible sources')
    ap.add_argument('--rubric-version', help='Explicit original version for legacy results lacking it')
    ap.add_argument('--calibration-only', action='store_true')
    ap.add_argument('--synthetic', action='store_true')
    ap.add_argument('--out', help='Optional destination, exclusive-create to preserve old outputs')
    args = ap.parse_args()
    image = json.loads(Path(args.image).read_text(encoding='utf-8-sig'))
    result = adapt_file(image, args.result, rubric_version=args.rubric_version,
                        calibration_only=args.calibration_only,
                        provenance_mode='synthetic' if args.synthetic else 'existing_model_output')
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        dest = Path(args.out)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open('x', encoding='utf-8') as fp:
            fp.write(encoded + '\n')
    print(encoded)
    return 0 if result['status'] in {'complete', 'not_applicable'} else 2


if __name__ == '__main__':
    raise SystemExit(main())
