"""离线模拟CLI输出；禁止在验证中启动真实模型或供应商。"""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

from app.services.visual_workflow import codex_transport as transport


def stream(*extra):
    events=[{'type':'thread.started','thread_id':'fixture'}, {'type':'turn.started'}, *extra,
            {'type':'item.completed','item':{'id':'message','type':'agent_message','text':'{"decision":"pending"}'}},
            {'type':'turn.completed','usage':{'input_tokens':100,'cached_input_tokens':60,'output_tokens':12}}]
    return '\n'.join(json.dumps(row) for row in events)+'\n'


class CodexTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.home=self.root/'auth';self.home.mkdir()
        (self.home/'auth.json').write_text(json.dumps({'auth_mode':'chatgpt','tokens':{'access_token':'fixture-not-real'},'OPENAI_API_KEY':None}))
        self.env=patch.dict(transport.os.environ,{'CODEX_HOME':str(self.home),'OPENAI_API_KEY':'must-not-pass','LLM_KEY':'must-not-pass','LLM_URL':'https://must-not-pass.invalid'},clear=False)
        self.env.start();self.addCleanup(self.env.stop)
        image=self.root/'image.png';image.write_bytes(b'unchanged-fixture-image')
        self.images=[{'path':str(image),'sha256':hashlib.sha256(image.read_bytes()).hexdigest(),'role':'original','candidate_id':'H002-fixture'}]
        self.folder=self.root/'call'

    def fake_run(self,events=None,returncode=0):
        def run(args,**kwargs):
            if args==['codex','--version']: return SimpleNamespace(returncode=0,stdout='codex-cli 0.159.3')
            self.assertNotIn('OPENAI_API_KEY',kwargs['env']);self.assertNotIn('LLM_URL',kwargs['env'])
            self.assertNotIn('LLM_KEY',kwargs['env']);self.assertNotEqual(kwargs['cwd'],str(Path.cwd()))
            self.assertIn(self.images[0]['sha256'],kwargs['input'])
            kwargs['stdout'].write(events if events is not None else stream());kwargs['stdout'].flush()
            kwargs['stderr'].write('fixture actual stderr retained');kwargs['stderr'].flush()
            Path(args[args.index('-o')+1]).write_text('{"decision":"pending"}')
            return SimpleNamespace(returncode=returncode)
        return run

    def test_isolates_credentials_and_preserves_order_and_bytes(self):
        other={**self.images[0],'role':'actual_view','candidate_id':'H002-other'}
        text=transport.build_stdin('exact-stage-system',{'source':'exact-payload'},self.images+[other])
        self.assertLess(text.index('H002-fixture'),text.index('H002-other'))
        argv=transport.build_argv(self.folder,self.images)
        self.assertIn('--ignore-user-config',argv);self.assertIn('features.shell_tool=false',argv)
        self.assertFalse(any('model_providers.' in arg for arg in argv))
        self.assertEqual(argv[argv.index('-i')+1],self.images[0]['path'])
        env=transport.isolated_environment({'PATH':'x','HOME':'y','OPENAI_BASE_URL':'bad','CUSTOM_VENDOR_KEY':'bad','LLM_URL':'bad','CODEX_API_KEY':'bad'})
        self.assertEqual(env,{'PATH':'x','HOME':'y'})

    def test_success_records_real_turn_usage_without_double_cached_tokens(self):
        with patch.object(transport.subprocess,'run',side_effect=self.fake_run()) as cli:
            result=transport.run_codex_cli(self.folder,'system',{},self.images)
        self.assertEqual(cli.call_count,2) # --version一次；实际推理仅一次。
        self.assertEqual(result['usage']['total_tokens'],112)
        self.assertEqual(result['usage']['cached_input_tokens'],60)
        self.assertIsNone(result['metadata']['actual_model'])
        self.assertIsNone(result['metadata']['cli_internal_http_retry_count'])
        self.assertEqual(result['metadata']['tool_event_count'],0)

    def test_failed_cli_preserves_actual_outputs_without_restart(self):
        with patch.object(transport.subprocess,'run',side_effect=self.fake_run(returncode=1)) as cli:
            with self.assertRaises(transport.CodexTransportError):
                transport.run_codex_cli(self.folder,'system',{},self.images)
        self.assertEqual(cli.call_count,2)
        self.assertEqual((self.folder/'stderr.txt').read_text(),'fixture actual stderr retained')
        self.assertEqual((self.folder/'answer.raw.txt').read_text(),'{"decision":"pending"}')

    def test_tool_events_reject_even_if_cli_exit_success(self):
        for kind in ('command_execution','mcp_tool_call','web_search','todo_list','file_change'):
            with self.subTest(kind=kind),patch.object(transport.subprocess,'run',side_effect=self.fake_run(stream({'type':'item.completed','item':{'type':kind,'id':'tool'}}))):
                with self.assertRaises(transport.CodexTransportError) as error:
                    transport.run_codex_cli(self.folder,'system',{},self.images)
                self.assertEqual(error.exception.metadata['tool_event_count'],1)

    def test_auth_not_chatgpt_fails_before_any_cli(self):
        (self.home/'auth.json').write_text('{"auth_mode":"apikey","OPENAI_API_KEY":"fixture"}')
        with patch.object(transport.subprocess,'run') as cli:
            with self.assertRaises(transport.CodexTransportError):transport.run_codex_cli(self.folder,'system',{},self.images)
            cli.assert_not_called()

    def test_malformed_or_failed_events_are_not_silent_success(self):
        for events in (stream()+'not JSON\n',stream({'type':'turn.failed','error':{'message':'actual failure'}}),stream()+stream()):
            with self.subTest(events=events),patch.object(transport.subprocess,'run',side_effect=self.fake_run(events)):
                with self.assertRaises(transport.CodexTransportError):transport.run_codex_cli(self.folder,'system',{},self.images)

    def recovery_events(self):
        return [{'type':'error','message':f'Reconnecting... {i}/5 (stream disconnected before completion: websocket closed by server before response.completed)'} for i in range(2,6)] + [
            {'type':'item.completed','item':{'id':'item_0','type':'error','message':'Falling back from WebSockets to HTTPS transport. stream disconnected before completion: websocket closed by server before response.completed'}}]

    def test_real_recovered_WS_to_HTTPS_diagnostics_are_not_tools_or_terminal_failure(self):
        parsed=transport.parse_events(stream(*self.recovery_events()))
        self.assertEqual(parsed['tool_event_count'],0);self.assertEqual(parsed['failure_events'],[])
        self.assertTrue(parsed['transport_diagnostics_recovered']);self.assertEqual(parsed['observed_reconnect_diagnostic_count'],4)
        self.assertEqual(len(parsed['transport_diagnostics']),5)
        self.assertTrue(parsed['usage']['turn_usage_complete']);self.assertFalse(parsed['usage']['usage_complete'])
        self.assertEqual(parsed['usage']['total_tokens'],112);self.assertIsNone(parsed['actual_http_request_count'])
        with patch.object(transport.subprocess,'run',side_effect=self.fake_run(stream(*self.recovery_events()))) as cli:
            result=transport.run_codex_cli(self.folder,'system',{},self.images)
        self.assertEqual(cli.call_count,2);self.assertTrue(result['metadata']['websocket_to_https_observed'])

    def test_recovery_never_hides_terminal_unknown_errors_or_tools(self):
        terminal=[{'type':'turn.failed','error':{'message':'terminal failure'}},
                  {'type':'error','message':'unexpected authentication failure'},
                  {'type':'item.completed','item':{'type':'error','message':'unknown terminal item error'}},
                  {'type':'item.completed','item':{'type':'command_execution','id':'tool'}}]
        for event in terminal:
            parsed=transport.parse_events(stream(*self.recovery_events(),event))
            with self.subTest(event=event):
                self.assertFalse(parsed['transport_diagnostics_recovered'])
                self.assertTrue(parsed['failure_events'] or parsed['tool_event_count'])
        unknown_item=transport.parse_events(stream(terminal[2]))
        self.assertEqual(unknown_item['tool_event_count'],0);self.assertTrue(unknown_item['failure_events'])

    def test_reconnection_without_later_single_completion_remains_failure(self):
        no_completion='\n'.join(json.dumps(e) for e in [{'type':'turn.started'},*self.recovery_events()])
        parsed=transport.parse_events(no_completion)
        self.assertFalse(parsed['transport_diagnostics_recovered']);self.assertTrue(parsed['failure_events'])
        after=transport.parse_events(stream()+'\n'+json.dumps(self.recovery_events()[0]))
        self.assertFalse(after['transport_diagnostics_recovered']);self.assertTrue(after['failure_events'])

    def test_actual_provider_model_only_from_actual_event(self):
        data=transport.parse_events(stream({'type':'response.metadata','model':'gpt-6.1-sol-provider-version','provider':'openai'}))
        self.assertEqual(data['actual_model'],'gpt-6.1-sol-provider-version')
        self.assertEqual(data['actual_provider'],'openai')


if __name__=='__main__':unittest.main()
