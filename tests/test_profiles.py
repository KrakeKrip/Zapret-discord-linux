import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from zapret_console import app, core


class ProfileTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'custom-strategies').mkdir()
        (self.root / 'zapret-latest').mkdir()
        for n in ('general_alt11.bat', 'general_alt10.bat'):
            (self.root / 'zapret-latest' / n).touch()
        self.ctx = core.BackendContext(root=self.root, state=self.root / 'state',
                                       unit='zapret_discord_youtube.service')
        self.patches = []
        self.old = dict(interface='any', gamefiltertcp='true', gamefilterudp='false',
                        strategy='general_alt11.bat', firewall_backend='nftables')
        self.other = self.old | {'strategy': 'general_alt10.bat'}
        core.write_config(self.ctx, self.old)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def as_root(self):
        return patch.object(core.os, 'geteuid', return_value=0)

    def profiles(self):
        return core.profiles_dir(self.ctx)

    def save_profile(self, name, with_config=None):
        if with_config is not None:
            core.write_config(self.ctx, with_config)
        with self.as_root(), patch.object(core, 'active', return_value=False), patch.object(core, 'trusted'):
            core.admin_command(self.ctx, 'profile-save', name)


class ProfileStorageTests(ProfileTestBase):
    def setUp(self):
        super().setUp()
        self.trusted_patch = patch.object(core, 'trusted')
        self.trusted_mock = self.trusted_patch.start()
        self.patches.append(self.trusted_patch)

    def test_two_profiles_saved_listed_deterministically_and_restored_fully(self):
        self.save_profile('home')
        self.save_profile('mobile', with_config=self.other)
        self.assertEqual(json.loads((self.profiles() / 'home.json').read_text()), self.old)
        entries = dict(core.profile_entries(self.ctx))
        self.assertEqual([n for n, _ in core.profile_entries(self.ctx)], ['home', 'mobile'])
        self.assertEqual(entries['home'], self.old)
        self.assertEqual(entries['mobile'], self.other)
        core.write_config(self.ctx, self.other | {'firewall_backend': 'iptables'})
        with self.as_root(), patch.object(core, 'active', return_value=False), patch.object(core, 'systemctl') as ctl:
            core.admin_command(self.ctx, 'profile-restore', 'home')
            ctl.assert_not_called()
        self.assertEqual(core.config(self.ctx), self.old)
        with self.as_root(), patch.object(core, 'active', return_value=False):
            core.admin_command(self.ctx, 'profile-restore', 'mobile')
        self.assertEqual(core.config(self.ctx), self.other)

    def test_save_under_occupied_name_keeps_file_until_explicit_replace(self):
        self.save_profile('home')
        core.write_config(self.ctx, self.other)
        with self.as_root():
            with self.assertRaisesRegex(RuntimeError, 'уже существует'):
                core.admin_command(self.ctx, 'profile-save', 'home')
        self.assertEqual(json.loads((self.profiles() / 'home.json').read_text()), self.old)
        with self.as_root():
            core.admin_command(self.ctx, 'profile-replace', 'home')
        self.assertEqual(json.loads((self.profiles() / 'home.json').read_text()), self.other)

    def test_replace_requires_existing_profile(self):
        with self.as_root():
            with self.assertRaisesRegex(RuntimeError, 'не найден'):
                core.admin_command(self.ctx, 'profile-replace', 'absent')
        self.assertFalse(self.profiles().exists() and list(self.profiles().iterdir()))

    def test_delete_touches_only_selected_profile(self):
        self.save_profile('home')
        self.save_profile('mobile', with_config=self.other)
        core.write_config(self.ctx, self.other)
        with self.as_root():
            core.admin_command(self.ctx, 'profile-delete', 'home')
            with self.assertRaisesRegex(RuntimeError, 'не найден'):
                core.admin_command(self.ctx, 'profile-delete', 'home')
        self.assertFalse((self.profiles() / 'home.json').exists())
        self.assertTrue((self.profiles() / 'mobile.json').exists())
        self.assertEqual(core.config(self.ctx), self.other)

    def test_invalid_names_rejected_before_any_file_change(self):
        self.save_profile('home')
        before_tree = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        conf_before = (self.root / 'conf.env').read_text()
        for name in ('', ' ', ' lead', 'trail ', 'two words', 'do.t', 'a/b', '../evil',
                     'a;b', 'a$b', 'a`b', 'a\nb', 'a\tb', '-lead', '_lead', '.dot',
                     'профиль', 'a' * 49):
            with self.as_root(), self.assertRaises(ValueError):
                core.admin_command(self.ctx, 'profile-save', name)
            with self.as_root(), self.assertRaises(ValueError):
                core.admin_command(self.ctx, 'profile-delete', name)
        self.assertEqual(sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')), before_tree)
        self.assertEqual((self.root / 'conf.env').read_text(), conf_before)

    def test_name_length_boundaries(self):
        self.save_profile('a' * 48)
        self.assertTrue((self.profiles() / ('a' * 48 + '.json')).exists())

    def test_save_checks_trust_of_existing_profiles_dir(self):
        self.profiles().mkdir(parents=True)
        with self.as_root(), patch.object(core, 'active', return_value=False):
            core.admin_command(self.ctx, 'profile-save', 'home')
        self.trusted_mock.assert_any_call(core.profiles_dir(self.ctx))
        self.assertTrue((self.profiles() / 'home.json').exists())

    def test_save_checks_trust_of_state_before_creating_profiles_dir(self):
        with self.as_root(), patch.object(core, 'active', return_value=False):
            core.admin_command(self.ctx, 'profile-save', 'home')
        self.trusted_mock.assert_any_call(self.ctx.state)
        self.trusted_mock.assert_any_call(core.profiles_dir(self.ctx))
        self.assertEqual(core.profiles_dir(self.ctx).stat().st_mode & 0o777, 0o755)
        self.assertEqual((core.profiles_dir(self.ctx) / 'home.json').stat().st_mode & 0o777, 0o644)

    def test_missing_profiles_dir_is_not_an_error_for_listing(self):
        self.assertEqual(core.profile_entries(self.ctx), [])

    def test_damaged_profiles_listed_as_unavailable_and_not_restorable(self):
        self.save_profile('home')
        self.profiles().mkdir(parents=True, exist_ok=True)
        (self.profiles() / 'broken.json').write_text('{not json')
        (self.profiles() / 'half.json').write_text(json.dumps({'strategy': 'general_alt11.bat'}))
        (self.profiles() / 'num.json').write_text('5')
        (self.profiles() / 'list.json').write_text('[1, 2]')
        entries = dict(core.profile_entries(self.ctx))
        self.assertEqual(entries['home'], self.old)
        for name in ('broken', 'half', 'num', 'list'):
            self.assertIsNone(entries[name], name)
        conf_before = (self.root / 'conf.env').read_text()
        with self.as_root():
            for name in ('broken', 'half', 'num', 'list'):
                with self.assertRaises(ValueError, msg=name):
                    core.admin_command(self.ctx, 'profile-restore', name)
        self.assertEqual((self.root / 'conf.env').read_text(), conf_before)
        with self.as_root():
            core.admin_command(self.ctx, 'profile-delete', 'broken')
        self.assertFalse((self.profiles() / 'broken.json').exists())

    def test_damaged_profile_values_are_never_executed(self):
        sentinel = self.root / 'sentinel'
        self.profiles().mkdir(parents=True)
        (self.profiles() / 'evil.json').write_text(json.dumps(self.old | {'strategy': f'$(touch {sentinel})'}))
        with self.as_root():
            with self.assertRaises(ValueError):
                core.admin_command(self.ctx, 'profile-restore', 'evil')
        self.assertFalse(sentinel.exists())
        self.assertEqual(core.config(self.ctx), self.old)

    def test_restore_with_absent_strategy_rejected_before_any_change(self):
        self.profiles().mkdir(parents=True)
        (self.profiles() / 'custom.json').write_text(json.dumps(self.old | {'strategy': 'general_alt07.bat'}))
        with self.as_root(), patch.object(core, 'active', return_value=False):
            with self.assertRaisesRegex(ValueError, 'Стратегия отсутствует'):
                core.admin_command(self.ctx, 'profile-restore', 'custom')
        self.assertEqual(core.config(self.ctx), self.old)
        self.assertFalse((self.ctx.state / 'previous.json').exists())

    def test_restore_with_absent_interface_rejected_before_any_change(self):
        self.profiles().mkdir(parents=True)
        (self.profiles() / 'wifi.json').write_text(json.dumps(self.old | {'interface': 'eth-absent'}))
        with self.as_root(), patch.object(core, 'active', return_value=False), \
             patch.object(core.os, 'listdir', return_value=['lo', 'wlan0']):
            with self.assertRaisesRegex(ValueError, 'интерфейс'):
                core.admin_command(self.ctx, 'profile-restore', 'wifi')
        self.assertEqual(core.config(self.ctx), self.old)
        self.assertFalse((self.ctx.state / 'previous.json').exists())

    def test_restore_keeps_stopped_service_stopped(self):
        self.save_profile('home')
        core.write_config(self.ctx, self.other)
        with self.as_root(), patch.object(core, 'active', return_value=False), patch.object(core, 'systemctl') as ctl:
            core.admin_command(self.ctx, 'profile-restore', 'home')
            ctl.assert_not_called()
        self.assertEqual(core.config(self.ctx), self.old)

    def test_restore_on_active_service_restarts_on_success(self):
        self.save_profile('home')
        core.write_config(self.ctx, self.other)
        with self.as_root(), patch.object(core, 'active', side_effect=[True, True]), \
             patch.object(core, 'systemctl') as ctl, patch('time.sleep'):
            core.admin_command(self.ctx, 'profile-restore', 'home')
            ctl.assert_called_once_with(self.ctx, 'restart')
        self.assertEqual(core.config(self.ctx), self.old)

    def test_restore_on_active_service_rolls_back_after_failed_restart(self):
        self.save_profile('home')
        core.write_config(self.ctx, self.other)
        with self.as_root(), patch.object(core, 'active', side_effect=[True, False]), \
             patch.object(core, 'systemctl', side_effect=[RuntimeError('restart failed'), None]) as ctl, \
             patch('time.sleep'):
            with self.assertRaisesRegex(RuntimeError, 'восстановлена'):
                core.admin_command(self.ctx, 'profile-restore', 'home')
            self.assertEqual(ctl.call_count, 2)
        self.assertEqual(core.config(self.ctx), self.other)

    def test_old_good_and_previous_flows_unchanged(self):
        with self.as_root(), patch.object(core, 'active', return_value=False):
            core.admin_command(self.ctx, 'save-good')
            core.admin_command(self.ctx, 'strategy', 'general_alt10.bat')
            core.admin_command(self.ctx, 'restore-previous')
        self.assertEqual(core.config(self.ctx), self.old)
        self.assertFalse(self.profiles().exists())

    def test_symlink_rejection_precedes_mocked_trust(self):
        outside = self.root / 'outside.json'
        outside.write_text(json.dumps(self.other))
        self.profiles().mkdir(parents=True)
        (self.profiles() / 'home.json').symlink_to(outside)
        with self.as_root():
            for action in ('profile-save', 'profile-replace', 'profile-restore', 'profile-delete'):
                with self.assertRaisesRegex(RuntimeError, 'символической', msg=action):
                    core.admin_command(self.ctx, action, 'home')
        self.assertEqual(outside.read_text(), json.dumps(self.other))
        self.assertEqual(core.config(self.ctx), self.old)


class RealTrustTests(ProfileTestBase):
    """Symlink and trust checks must hold without mocking trusted()."""

    def op(self, action, name):
        return core.profile_op(self.ctx, action, name)

    def test_save_into_untrusted_existing_dir_is_refused_by_real_trusted(self):
        self.profiles().mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, 'доступен для изменения'):
            self.op('profile-save', 'home')
        self.assertFalse((self.profiles() / 'home.json').exists())
        self.assertEqual(core.config(self.ctx), self.old)

    def test_save_into_missing_dir_requires_trusted_state(self):
        self.ctx.state.mkdir()
        with self.assertRaisesRegex(RuntimeError, 'доступен для изменения'):
            self.op('profile-save', 'home')
        self.assertFalse((self.ctx.state / 'profiles').exists())
        self.assertEqual(core.config(self.ctx), self.old)

    def test_entries_reject_symlinked_profiles_dir(self):
        self.ctx.state.mkdir(parents=True)
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'external.json').write_text(json.dumps(self.old))
        (self.ctx.state / 'profiles').symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError, 'символической'):
            core.profile_entries(self.ctx)
        self.assertEqual((outside / 'external.json').read_text(), json.dumps(self.old))

    def test_entries_reject_dangling_symlinked_profiles_dir(self):
        self.ctx.state.mkdir(parents=True)
        (self.ctx.state / 'profiles').symlink_to(self.root / 'nowhere')
        with self.assertRaisesRegex(RuntimeError, 'символической'):
            core.profile_entries(self.ctx)

    def test_symlinked_profiles_dir_is_rejected_for_every_operation(self):
        outside = self.root / 'elsewhere'
        outside.mkdir()
        self.ctx.state.mkdir()
        (self.ctx.state / 'profiles').symlink_to(outside)
        for action in ('profile-save', 'profile-replace', 'profile-restore', 'profile-delete'):
            with self.assertRaisesRegex(RuntimeError, 'символической', msg=action):
                self.op(action, 'home')
        self.assertEqual(list(outside.iterdir()), [])

    def test_symlinked_profile_file_is_rejected_and_target_untouched(self):
        outside = self.root / 'outside.json'
        outside.write_text('keep me')
        self.profiles().mkdir(parents=True)
        (self.profiles() / 'home.json').symlink_to(outside)
        # replace/restore/delete check the file symlink before trusting it
        for action in ('profile-replace', 'profile-restore', 'profile-delete'):
            with self.assertRaisesRegex(RuntimeError, 'символической', msg=action):
                self.op(action, 'home')
        # save trusts the real directory first; in this fixture that refuses the write anyway
        with self.assertRaises(RuntimeError, msg='profile-save'):
            self.op('profile-save', 'home')
        self.assertTrue((self.profiles() / 'home.json').is_symlink())
        self.assertEqual(outside.read_text(), 'keep me')
        self.assertEqual(core.config(self.ctx), self.old)

    def test_untrusted_existing_profile_is_refused_by_real_trusted(self):
        self.profiles().mkdir(parents=True)
        (self.profiles() / 'home.json').write_text(json.dumps(self.other))
        with self.assertRaisesRegex(RuntimeError, 'доступен для изменения'):
            self.op('profile-restore', 'home')
        self.assertEqual(core.config(self.ctx), self.old)


class ProfileMenuTests(ProfileTestBase):
    def setUp(self):
        super().setUp()
        self.priv = patch.object(app, 'privileged').start()
        self.msg = patch.object(app, 'show').start()
        self.patches += [self.priv, self.msg]

    def run_profiles_menu(self, menu_sides, dialog_sides):
        with patch.object(app, 'menu', side_effect=menu_sides) as m, \
             patch.object(app, 'dialog', side_effect=dialog_sides):
            app.profiles_menu(self.ctx)
        return m

    def test_save_new_profile_goes_through_launcher(self):
        self.run_profiles_menu(['save', None], ['mobile'])
        self.priv.assert_called_once_with('profile-save', 'mobile')
        self.msg.assert_not_called()

    def test_replace_offers_confirmation_and_proceeds_on_confirm(self):
        self.save_profile('home')
        self.run_profiles_menu(['save', 'home', None], ['home', ''])
        self.priv.assert_called_once_with('profile-replace', 'home')

    def test_replace_cancel_changes_nothing(self):
        self.save_profile('home')
        self.run_profiles_menu(['save', 'home', None], ['home', None])
        self.priv.assert_not_called()
        self.assertEqual(json.loads((self.profiles() / 'home.json').read_text()), self.old)

    def test_delete_cancel_changes_nothing(self):
        self.save_profile('home')
        self.save_profile('mobile', with_config=self.other)
        self.run_profiles_menu(['delete', 'mobile', None], [None])
        self.priv.assert_not_called()
        self.assertTrue((self.profiles() / 'mobile.json').exists())
        self.assertTrue((self.profiles() / 'home.json').exists())

    def test_delete_confirmed_goes_through_launcher(self):
        self.save_profile('home')
        self.run_profiles_menu(['delete', 'home', None], [''])
        self.priv.assert_called_once_with('profile-delete', 'home')

    def test_empty_list_shows_message_without_launcher(self):
        self.run_profiles_menu(['restore', None], [])
        self.priv.assert_not_called()
        self.assertIn('нет', self.msg.call_args[0][0])

    def test_menu_shows_error_for_symlinked_profiles_dir(self):
        self.ctx.state.mkdir(parents=True)
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'external.json').write_text(json.dumps(self.old))
        (self.ctx.state / 'profiles').symlink_to(outside)
        self.run_profiles_menu(['restore', None], [])
        self.priv.assert_not_called()
        self.assertIn('символической', self.msg.call_args[0][0])

    def test_trailing_newline_in_input_is_normalized(self):
        self.run_profiles_menu(['save', None], ['mobile\n'])
        self.priv.assert_called_once_with('profile-save', 'mobile')

    def test_trailing_newline_on_existing_name_offers_replace(self):
        self.save_profile('home')
        self.run_profiles_menu(['save', 'home', None], ['home\n', ''])
        self.priv.assert_called_once_with('profile-replace', 'home')

    def test_replace_cancel_with_newline_name_changes_nothing(self):
        self.save_profile('home')
        self.run_profiles_menu(['save', 'home', None], ['home\n', None])
        self.priv.assert_not_called()
        self.assertEqual(json.loads((self.profiles() / 'home.json').read_text()), self.old)

    def test_internal_newline_and_spaces_still_rejected(self):
        for bad in ('bad name\n', 'a\nb\n', '\n'):
            self.msg.reset_mock()
            self.priv.reset_mock()
            self.run_profiles_menu(['save', None], [bad])
            self.priv.assert_not_called()
            self.assertIn('Имя профиля', self.msg.call_args[0][0])

    def test_damaged_profile_listed_but_not_restorable(self):
        self.save_profile('home')
        self.profiles().mkdir(parents=True, exist_ok=True)
        (self.profiles() / 'broken.json').write_text('{oops')
        self.run_profiles_menu(['restore', 'broken', None], [])
        self.priv.assert_not_called()
        self.assertIn('повреждён', self.msg.call_args[0][0])

    def test_invalid_or_empty_name_rejected_without_launcher(self):
        for bad in ('', '   ', 'bad name', '../evil', 'bad.name'):
            self.msg.reset_mock()
            self.run_profiles_menu(['save', None], [bad])
            self.priv.assert_not_called()
            self.assertIn('Имя профиля', self.msg.call_args[0][0])

    def test_listing_shows_name_strategy_and_interface(self):
        self.save_profile('home')
        entries = core.profile_entries(self.ctx)
        self.assertEqual(app.profile_label(*entries[0]), f'home — {self.old["strategy"]} · интерфейс: {self.old["interface"]}')
        damaged = app.profile_label('x', None)
        self.assertIn('повреждён', damaged)


class SavedProfileMenuWiringTests(ProfileTestBase):
    def test_named_profiles_section_inside_saved_profile_menu(self):
        captured = []

        def fake_menu(prompt, entries, default=None, tags=False):
            captured.append([key for key, _ in entries])
            return 'good' if len(captured) == 1 else None

        with patch.object(app, 'menu', side_effect=fake_menu), \
             patch.object(app, 'status', return_value='СТАТУС'), \
             patch.object(app, 'load_context', return_value=self.ctx), \
             patch.object(core, 'preflight', return_value=[]), \
             patch.object(core, 'active', return_value=False), \
             patch.object(app.sys, 'argv', ['zapret-console']), \
             patch.object(app.sys.stdin, 'isatty', return_value=True):
            app.main()
        self.assertIn('good', captured[0])
        self.assertIn('profiles', captured[1])


if __name__ == '__main__':
    unittest.main()
