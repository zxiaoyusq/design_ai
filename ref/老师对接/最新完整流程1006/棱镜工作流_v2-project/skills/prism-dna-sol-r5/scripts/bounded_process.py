"""File-backed subprocess transport; no model/schema/normalization decisions."""
from pathlib import Path
import json,os,subprocess

def execute(args,prompt,cwd,timeout,folder):
    folder=Path(folder);stdin=folder/'transport.stdin.utf8';stdout=folder/'transport.stdout';stderr=folder/'transport.stderr'
    stdin.write_bytes(prompt.encode('utf-8'));process=None;timed=False;error=None;code=None
    try:
        with stdin.open('rb') as inp,stdout.open('wb') as out,stderr.open('wb') as err:
            process=subprocess.Popen(args,stdin=inp,stdout=out,stderr=err,cwd=cwd,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            (folder/'owned-process.json').write_text(json.dumps({'pid':process.pid,'owned_by_this_request':True}),encoding='utf-8')
            try:code=process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:timed=True;error='timeout_no_retry'
    except OSError as exc:error=type(exc).__name__+': '+str(exc)
    finally:
        if process and process.poll() is None:
            try:
                if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                else:process.kill()
                code=process.wait(timeout=10)
            except Exception as exc:error=(error or 'cleanup_failed')+'; '+str(exc)
    return code,stdout.read_text(encoding='utf-8',errors='replace') if stdout.exists() else '',stderr.read_text(encoding='utf-8',errors='replace') if stderr.exists() else '',timed,error
