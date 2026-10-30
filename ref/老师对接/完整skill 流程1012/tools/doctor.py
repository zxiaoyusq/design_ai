"""Read-only Python dependency check; no automatic installation or inference."""
import importlib, importlib.metadata, json, sys
packages={'PIL':'Pillow','jsonschema':'jsonschema','openpyxl':'openpyxl'}
rows=[]
for module,distribution in packages.items():
    try:
        importlib.import_module(module)
        rows.append({'dependency':distribution,'available':True,'version':importlib.metadata.version(distribution)})
    except (ImportError,importlib.metadata.PackageNotFoundError):
        rows.append({'dependency':distribution,'available':False})
ok=sys.version_info >= (3,12) and all(r['available'] for r in rows)
print(json.dumps({'ready_for_offline_checks':ok,'python':sys.version.split()[0],'dependencies':rows,'model_calls':0,'note':'For missing dependencies use this interpreter with -m pip install -r requirements.txt; no installation performed.'},ensure_ascii=False))
raise SystemExit(0 if ok else 2)
