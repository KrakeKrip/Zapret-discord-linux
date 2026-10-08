import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('menu', 'src/zapret_console/app.py')
menu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(menu)


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'custom-strategies').mkdir()
        (self.root / 'zapret-latest').mkdir()
        for n in ('general_alt11.bat', 'general_alt10.bat'):
            (self.root / 'zapret-latest' / n).touch()
        self.patches = [patch.object(menu, 'ROOT', self.root),
                        patch.object(menu, 'STATE', self.root / 'state'),
                        patch.object(menu, 'KNOWN', self.root / 'state/known-good.json'),
                        patch.object(menu, 'trusted')]
        for p in self.patches:
            p.start()
        self.old = dict(interface='any', gamefiltertcp='true', gamefilterudp='false',
                        strategy='general_alt11.bat', firewall_backend='nftables')
        menu.write_config(self.old)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_strategy_preserves_flags_and_does_not_start_stopped_service(self):
        with patch.object(menu.os, 'geteuid', return_value=0), patch.object(menu, 'active', return_value=False), patch.object(menu, 'systemctl') as ctl:
            menu.admin('strategy', 'general_alt10.bat')
            ctl.assert_not_called()
        new = menu.config()
        self.assertEqual(new['strategy'], 'general_alt10.bat')
        self.assertEqual({k: v for k, v in new.items() if k != 'strategy'}, {k: v for k, v in self.old.items() if k != 'strategy'})

    def test_failed_restart_restores_config(self):
        new = self.old | {'strategy': 'general_alt10.bat'}
        with patch.object(menu, 'active', return_value=True), patch.object(menu, 'systemctl', side_effect=[RuntimeError('failed'), None]) as ctl:
            with self.assertRaisesRegex(RuntimeError, 'восстановлена'):
                menu.apply_config(new)
            self.assertEqual(ctl.call_count, 2)
        self.assertEqual(menu.config(), self.old)

    def test_rejects_shell_text_and_paths_before_mutation(self):
        for value in ('../../evil.bat', 'general_alt11.bat; touch /tmp/test', 'missing.bat'):
            with self.assertRaises(ValueError):
                menu.apply_config(self.old | {'strategy': value})
            self.assertEqual(menu.config(), self.old)

    def test_save_and_restore_working_config(self):
        with patch.object(menu.os, 'geteuid', return_value=0), patch.object(menu, 'active', return_value=False):
            menu.admin('save-good')
            menu.admin('strategy', 'general_alt10.bat')
            menu.admin('restore-good')
        self.assertEqual(menu.config(), self.old)

    def test_config_text_is_never_executed(self):
        sentinel = self.root / 'unsafe'
        with (self.root / 'conf.env').open('a') as f:
            f.write(f'\nstrategy=$(touch {sentinel})\n')
        with self.assertRaises(ValueError):
            menu.config()
        self.assertFalse(sentinel.exists())

    def test_eof_in_websocket_handshake_is_bounded(self):
        from unittest.mock import MagicMock
        sock = MagicMock()
        sock.recv.return_value = b''
        context = MagicMock()
        context.wrap_socket.return_value = sock
        with patch.object(menu.socket, 'create_connection', return_value=sock), patch.object(menu.ssl, 'create_default_context', return_value=context):
            with self.assertRaisesRegex(RuntimeError, 'handshake'):
                menu.gateway_probe()

    def test_restore_previous_swaps_profiles(self):
        with patch.object(menu.os, 'geteuid', return_value=0), patch.object(menu, 'active', return_value=False):
            menu.admin('strategy', 'general_alt10.bat')
            menu.admin('restore-previous')
        self.assertEqual(menu.config(), self.old)
        import json
        self.assertEqual(json.loads((menu.STATE / 'previous.json').read_text())['strategy'], 'general_alt10.bat')

    def test_settings_reject_service_command_injection(self):
        import json
        path = self.root / 'settings.json'
        path.write_text(json.dumps({'backend_root': '/opt/test', 'service': 'zapret; touch /tmp/unsafe'}))
        with patch.object(menu, 'SETTINGS', path), self.assertRaises(ValueError):
            menu.load_settings()

    def test_relative_backend_path_is_rejected(self):
        import json
        path = self.root / 'settings.json'
        path.write_text(json.dumps({'backend_root': '../test', 'service': 'zapret.service'}))
        with patch.object(menu, 'SETTINGS', path), self.assertRaises(ValueError):
            menu.load_settings()

    def test_failed_service_after_restart_is_rolled_back(self):
        new = self.old | {'strategy': 'general_alt10.bat'}
        with patch.object(menu, 'active', side_effect=[True, False]), patch.object(menu, 'systemctl') as ctl, patch('time.sleep'):
            with self.assertRaisesRegex(RuntimeError, 'восстановлена'):
                menu.apply_config(new)
            self.assertEqual(ctl.call_count, 2)
        self.assertEqual(menu.config(), self.old)


if __name__ == '__main__':
    unittest.main()
