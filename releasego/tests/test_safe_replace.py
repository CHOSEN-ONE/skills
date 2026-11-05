"""Offline safety regression: synthetic metadata; HTTP transport never runs."""
import json
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from releasego_http_session import ReleaseGoHttpSession, JsonResponse
from releasego_security import Redactor
import releasego_http_session as module


def reply(rows=None, code=200, status=200):
    return JsonResponse(status, 'https://fixture.test', 'application/json',
                        {'code': code, 'data': rows, 'count': 0}, '')


class SafeReplaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.backup = Path(self.tmp.name) / 'backup.json'
        self.s = object.__new__(ReleaseGoHttpSession)
        self.s.redactor = Redactor(('fixture-user', 'fixture-secret'))
        self.s.request_json = Mock(side_effect=AssertionError('No network allowed'))
        self.s.product_list = Mock(return_value=reply([
            {'code': c, 'name': n} for c, n in
            [('app', 'APP'), ('mp', 'Mobile Platform'), ('browser', 'Browser'),
             ('common', 'Common'), ('CustomUP', 'Custom Display')]]))
        self.s.release_list = Mock(return_value=reply([{'id': 42, 'releaseVersion': 'V-test', 'status': 0}]))
        self.plan = {'id': 9, 'releaseVersionId': 42, 'product': 'app', 'productCheck': 0}
        self.s.plan_list = Mock(return_value=reply([self.plan]))
        self.s.applications_by_product = Mock(return_value=reply([{'applicationId': 'artifact', 'productCode': 'app'}]))
        self.versions = [{'applicationVersionId': v, 'applicationId': 'artifact', 'scmTag': v, 'commitId': v + '-sha'} for v in ['old', 'new']]
        self.s.application_versions = Mock(return_value=reply(self.versions))
        self.s.application_build_ids = Mock(side_effect=lambda v: reply([{'buildNumber': '1' if v == 'old' else '2', 'buildTag': v, 'commitId': v + '-sha'}]))
        self.old = {'releaseApplicationsId': 8, 'releaseVersionId': 42, 'productCode': 'app', 'applicationId': 'artifact', 'applicationVersionId': 'old', 'buildNumber': '1', 'scmTag': 'old'}
        self.rows = [self.old.copy()]
        self.s.application_list = Mock(side_effect=lambda *a, **k: reply([r.copy() for r in self.rows]))
        def delete(*a):
            self.rows.clear()
            return reply()
        def save(**kw):
            self.rows.append({'releaseApplicationsId': 10, 'releaseVersionId': kw['release_version_id'], 'productCode': kw['product_code'], 'applicationId': kw['application_id'], 'applicationVersionId': kw['application_version_id'], 'buildNumber': kw['build_number'], 'scmTag': kw['application_version_id']})
            return reply()
        self.save = save
        self.s.delete_application = Mock(side_effect=delete)
        self.s.save_application = Mock(side_effect=save)

    def run_replace(self):
        return self.s.replace_application('V-test', 42, 'app', 'artifact', 'new', '2', self.backup)

    def test_display_name_rejected_before_post(self):
        self.s.request_json.side_effect = None
        self.s.request_json.return_value = reply()
        with self.assertRaises(SystemExit):
            self.s.save_plan(42, 'APP')
        self.s.request_json.assert_not_called()

    def test_all_exact_codes_and_visible_idempotence(self):
        for code in ['app', 'mp', 'browser', 'common', 'CustomUP']:
            with self.subTest(code=code):
                self.s.plan_list.return_value = reply([{**self.plan, 'product': code}])
                self.s.save_plan(42, code)
        self.s.request_json.assert_not_called()

    def test_plan_save_requires_visible_readback(self):
        self.s.plan_list.return_value = reply([])
        self.s.request_json.side_effect = None
        for code in [200, 500]:
            self.s.request_json.return_value = reply(code=code)
            with self.assertRaises(SystemExit):
                self.s.save_plan(42, 'app')

    def test_invalid_plan_never_deletes(self):
        for response in [reply([]), reply(None), reply([], code=500), reply([], status=500), reply([self.plan, self.plan])]:
            self.s.plan_list.return_value = response
            with self.assertRaises(SystemExit):
                self.run_replace()
        self.s.delete_application.assert_not_called()

    def test_build_mismatch_never_deletes(self):
        self.s.application_build_ids.side_effect = lambda v: reply([{'buildNumber': '1' if v == 'old' else '2', 'buildTag': 'wrong'}])
        with self.assertRaises(SystemExit):
            self.run_replace()
        self.s.delete_application.assert_not_called()

    def test_old_build_unrecoverable_never_deletes(self):
        self.s.application_build_ids.side_effect = lambda v: reply([] if v == 'old' else [{'buildNumber': '2', 'buildTag': 'new'}])
        with self.assertRaises(SystemExit):
            self.run_replace()
        self.s.delete_application.assert_not_called()

    def test_replace_and_readback(self):
        self.assertEqual(self.run_replace()['status'], 'replaced')
        self.assertEqual(self.rows[0]['applicationVersionId'], 'new')
        self.s.delete_application.assert_called_once_with(8, 42)
        self.s.save_application.assert_called_once()
        snapshot = json.loads(self.backup.read_text(encoding='utf-8'))
        self.assertEqual(snapshot['oldRowId'], 8)
        self.assertEqual(snapshot['restore']['application_version_id'], 'old')

    def test_failed_save_restores_once(self):
        self.s.save_application.side_effect = lambda **kw: reply(code=500) if kw['application_version_id'] == 'new' else self.save(**kw)
        with self.assertRaisesRegex(SystemExit, 'restored'):
            self.run_replace()
        self.assertEqual(self.rows[0]['applicationVersionId'], 'old')
        self.assertEqual(self.s.save_application.call_count, 2)

    def test_failed_restore_reports_missing_and_backup(self):
        self.s.save_application.side_effect = None
        self.s.save_application.return_value = reply(code=500)
        with self.assertRaisesRegex(SystemExit, 'row missing.*backup'):
            self.run_replace()
        self.assertEqual(self.s.save_application.call_count, 2)

    def test_timeout_after_save_does_not_repeat_or_restore(self):
        def timed_out(**kw):
            self.save(**kw)
            raise TimeoutError('timeout')
        self.s.save_application.side_effect = timed_out
        self.assertEqual(self.run_replace()['status'], 'replaced')
        self.s.save_application.assert_called_once()

    def test_backup_is_exclusive(self):
        self.backup.write_text('KEEP', encoding='utf-8')
        with self.assertRaises(SystemExit):
            self.run_replace()
        self.assertEqual(self.backup.read_text(), 'KEEP')
        self.s.delete_application.assert_not_called()

    def test_idempotent_and_new_only(self):
        self.rows = [{**self.old, 'applicationVersionId': 'new', 'buildNumber': '2', 'scmTag': 'new'}]
        self.assertEqual(self.run_replace()['status'], 'unchanged')
        self.s.save_application.assert_not_called()
        self.rows.clear()
        self.assertEqual(self.run_replace()['status'], 'added')
        self.s.delete_application.assert_not_called()

    def test_delete_success_without_removal_must_not_save(self):
        self.s.delete_application.side_effect = None
        self.s.delete_application.return_value = reply()
        with self.assertRaisesRegex(SystemExit, 'Delete'):
            self.run_replace()
        self.s.save_application.assert_not_called()

    def test_real_metadata_field_shapes(self):
        self.s.applications_by_product.return_value = reply([{'id': 'artifact', 'product': 'app'}])
        self.s.application_versions.return_value = reply([
            {'id': v, 'applicationId': 'artifact', 'scmTag': v, 'gitCommitId': v + '-sha'}
            for v in ['old', 'new']])
        self.s.application_build_ids.side_effect = lambda v: reply([{
            'id': 71, 'applicationVersionId': v, 'buildNumber': '1' if v == 'old' else '2',
            'buildTag': v, 'buildCommitId': v + '-sha'}])
        self.assertEqual(self.run_replace()['status'], 'replaced')

    def test_plan_post_is_exact_and_read_back(self):
        for code in ['app', 'mp', 'browser', 'common', 'CustomUP']:
            self.s.plan_list.side_effect = [reply([]), reply([{**self.plan, 'product': code}])]
            self.s.request_json.side_effect = None
            self.s.request_json.return_value = reply()
            self.s.save_plan(42, code)
            self.assertEqual(self.s.request_json.call_args.kwargs['json_body']['product'], code)

    def test_ownership_commit_and_release_fail_closed(self):
        for field, value in [('status', 1), ('id', 99), ('releaseVersion', 'other')]:
            self.s.release_list.return_value = reply([{**{'id': 42, 'releaseVersion': 'V-test', 'status': 0}, field: value}])
            with self.assertRaises(SystemExit):
                self.run_replace()
        self.s.release_list.return_value = reply([{'id': 42, 'releaseVersion': 'V-test', 'status': 0}])
        self.s.application_build_ids.side_effect = lambda v: reply([{'buildNumber': '2', 'buildTag': 'new', 'commitId': 'different-sha'}])
        with self.assertRaises(SystemExit):
            self.run_replace()
        self.s.delete_application.assert_not_called()

    def test_row_race_stops_before_delete(self):
        self.s.application_list.side_effect = [reply([self.old]), reply([{**self.old, 'releaseApplicationsId': 99}])]
        with self.assertRaisesRegex(SystemExit, 'changed'):
            self.run_replace()
        self.s.delete_application.assert_not_called()

    def test_inherited_version_can_be_replaced(self):
        self.rows = [{**self.old, 'sinceReleaseVersionId': 41}]
        self.assertEqual(self.run_replace()['status'], 'replaced')

    def test_cross_release_and_truncated_rows_never_delete(self):
        self.rows = [{**self.old, 'releaseVersionId': 41}]
        with self.assertRaises(SystemExit):
            self.run_replace()
        self.rows = [self.old] + [
            {**self.old, 'applicationId': f'other-{i}'} for i in range(199)]
        with self.assertRaises(SystemExit):
            self.run_replace()
        self.s.delete_application.assert_not_called()

    def test_zero_code_is_not_success(self):
        self.s.product_list.return_value = reply([{'code': 'app'}], code=0)
        with self.assertRaisesRegex(SystemExit, 'code=0'):
            self.run_replace()
        self.s.delete_application.assert_not_called()

    def test_concurrent_plan_duplicate_readback(self):
        self.s.plan_list.side_effect = [reply([]), reply([self.plan])]
        self.s.request_json.side_effect = None
        self.s.request_json.return_value = reply(code=-1)
        self.s.request_json.return_value.data['msg'] = 'already participating'
        self.assertEqual(self.s.save_plan(42, 'app').data['data'], [self.plan])

    def test_delete_timeout_after_removal_continues_once(self):
        def delete(*a):
            self.rows.clear()
            raise TimeoutError('fixture-secret timeout')
        self.s.delete_application.side_effect = delete
        result = self.run_replace()
        self.assertEqual(result['status'], 'replaced')
        self.assertNotIn('fixture-secret', str(result))
        self.s.delete_application.assert_called_once()
        self.s.save_application.assert_called_once()

    def test_delete_timeout_without_removal_preserves_old(self):
        self.s.delete_application.side_effect = TimeoutError('timeout')
        with self.assertRaisesRegex(SystemExit, 'old row retained.*TimeoutError'):
            self.run_replace()
        self.s.delete_application.assert_called_once()
        self.s.save_application.assert_not_called()

    def test_business_failure_keeps_redacted_root_cause(self):
        bad = reply(code=-1)
        bad.data['msg'] = 'plan missing fixture-secret'
        self.s.save_application.side_effect = None
        self.s.save_application.return_value = bad
        with self.assertRaises(SystemExit) as error:
            self.run_replace()
        message = str(error.exception)
        self.assertIn('HTTP=200 code=-1', message)
        self.assertIn('plan missing', message)
        self.assertNotIn('fixture-secret', message)

    def test_readback_unknown_never_restores(self):
        self.s.application_list.side_effect = [reply([self.old]), reply([self.old]), reply([]), reply(None)]
        with self.assertRaisesRegex(SystemExit, 'unknown'):
            self.run_replace()
        self.s.save_application.assert_called_once()

    def test_backup_has_no_credentials(self):
        self.old['username'] = 'fixture-user'
        self.old['password'] = 'fixture-secret'
        self.run_replace()
        content = self.backup.read_text(encoding='utf-8')
        for forbidden in ('fixture-user', 'fixture-secret', 'username', 'password'):
            self.assertNotIn(forbidden, content)

    def test_cli_confirmation_then_login(self):
        argv = ['tool', 'replace-app', '--release-version', 'V-test', '--release-version-id', '42',
                '--product-code', 'app', '--application-id', 'artifact', '--application-version-id',
                'new', '--build-number', '2', '--backup', str(self.backup)]
        with patch.object(sys, 'argv', argv), patch.object(module, 'load_config') as cfg, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                module.main()
            cfg.assert_not_called()
        session = Mock()
        session.redactor.json.return_value = '{}'
        with patch.object(sys, 'argv', argv + ['--confirm-write', 'yes']), patch.object(module, 'load_config'), patch.object(module, 'ReleaseGoHttpSession', return_value=session), contextlib.redirect_stdout(io.StringIO()):
            module.main()
        self.assertEqual([c[0] for c in session.method_calls][:2], ['login', 'replace_application'])


if __name__ == '__main__':
    unittest.main()
