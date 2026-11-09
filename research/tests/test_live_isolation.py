"""Check CLI isolation and parsing without calling a model."""
import contextlib
import io
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('run_live', Path(__file__).resolve().parents[1] / 'run-live.py')
run_live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_live)


class LiveIsolationTests(unittest.TestCase):
    def test_runtime_copies_only_local_nonsecret_provider_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config = directory / 'input.json'
            config.write_text(json.dumps({'providers': {
                'local-llamacpp': {'baseUrl': 'http://127.0.0.1:8080/v1', 'api': 'openai-completions',
                    'apiKey': 'private-test-value', 'headers': {'Authorization': 'private-header'},
                    'models': [{'id': run_live.MODEL}]},
                'hosted': {'apiKey': 'another-private-test-value'},
            }}))
            with patch.object(run_live, 'WORK', directory), patch.object(run_live, 'BASE_CONFIG', config):
                env = run_live.runtime_env()
            generated = (directory / 'pi-config/models.json').read_text()
            self.assertNotIn('private', generated)
            self.assertNotIn('hosted', generated)
            self.assertEqual(json.loads(generated)['providers']['local-llamacpp']['apiKey'], 'local')
            self.assertEqual(env['PI_CODING_AGENT_DIR'], str(directory / 'pi-config'))
            self.assertEqual(env['WIKI_HOME'], str(directory / 'isolated-personal'))

    def test_nonlocal_inference_endpoint_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config = directory / 'input.json'
            config.write_text(json.dumps({'providers': {'local-llamacpp': {
                'baseUrl': 'https://example.org/v1', 'models': [{'id': run_live.MODEL}],
            }}}))
            with patch.object(run_live, 'WORK', directory), patch.object(run_live, 'BASE_CONFIG', config):
                with self.assertRaisesRegex(AssertionError, 'private-LAN inference'):
                    run_live.runtime_env()

    def test_declared_private_lan_model_route_is_allowed(self):
        self.assertTrue(run_live.private_endpoint('http://192.168.0.30:8080/v1'))
        self.assertTrue(run_live.private_endpoint('http://localhost:8080/v1'))
        self.assertFalse(run_live.private_endpoint('https://8.8.8.8/v1'))
        self.assertFalse(run_live.private_endpoint('https://example.org/v1'))

    def test_live_cli_is_bounded_and_records_actual_events(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'research/results').mkdir(parents=True)
            events = [
                {'type': 'tool_execution_start', 'toolName': 'read', 'args': {'path': 'wiki/example.md'}},
                {'type': 'message_end', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'Synthetic answer'}]}},
            ]
            output = SimpleNamespace(returncode=0, stdout='\n'.join(map(json.dumps, events)), stderr='')
            with patch.object(run_live, 'ROOT', directory), patch.object(run_live, 'WORK', directory / 'work'), \
                 patch.object(run_live, 'runtime_env', return_value={}), \
                 patch.object(run_live.subprocess, 'run', return_value=output) as cli, contextlib.redirect_stdout(io.StringIO()):
                result = run_live.run('nvk', 'q05', 'Synthetic question')
            self.assertEqual(cli.call_args.kwargs['timeout'], 150)
            for flag in ['--no-extensions', '--no-mcp', '--no-skills', '--no-context-files']:
                self.assertIn(flag, cli.call_args.args[0])
            self.assertEqual(result['answer'], 'Synthetic answer')
            self.assertEqual(result['tool_calls'], [{'name': 'read', 'args': {'path': 'wiki/example.md'}}])


if __name__ == '__main__':
    unittest.main()
