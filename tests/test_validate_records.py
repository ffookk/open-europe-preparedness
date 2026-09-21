"""Regression cases for realistic record editing mistakes and CLI failure modes."""
import contextlib
import copy
import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts.validate_records import main, validate_document

ROOT = Path(__file__).resolve().parents[1]


class RecordValidationTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads((ROOT / 'examples/synthetic.json').read_text(encoding='utf-8'))
        self.record = self.document['records'][0]

    def test_repository_fixtures_pass_together(self):
        seen = set()
        for path in sorted((ROOT / 'data').glob('*.json')) + sorted((ROOT / 'examples').glob('*.json')):
            document = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual([], validate_document(document, path.name, seen))

    def test_dataset_partitions_cannot_mix_synthetic_or_unreviewed_records(self):
        for filename, expected_status in (('verified.json', 'verified'), ('pending.json', 'pending')):
            records = json.loads((ROOT / 'data' / filename).read_text(encoding='utf-8'))['records']
            self.assertTrue(records)
            for record in records:
                with self.subTest(dataset=filename, record_id=record['id']):
                    self.assertEqual('real', record['record_type'])
                    self.assertEqual(expected_status, record['verification_status'])

    def test_verified_proposal_does_not_require_adoption_or_effective_date(self):
        self.assertEqual('proposed', self.record['policy_stage'])
        self.assertIsNone(self.record['dates']['effective_at'])
        self.assertEqual([], validate_document(self.document))
        self.record['policy_stage'] = 'unknown'
        self.assertEqual([], validate_document(self.document))

    def test_duplicate_ids_across_separate_files_are_rejected(self):
        seen = set()
        self.assertEqual([], validate_document(self.document, 'first', seen))
        self.assertTrue(any('duplicate ID' in e for e in validate_document(self.document, 'second', seen)))

    def test_impossible_dates_are_rejected_but_leap_day_is_valid(self):
        self.record['dates']['target_at'] = '2024-02-29'
        self.assertEqual([], validate_document(self.document))
        for invalid in ('2025-02-29', '2024-13-01', '2024-2-01', '2024-01-01T00:00:00Z', 20240101):
            with self.subTest(invalid=invalid):
                self.record['dates']['target_at'] = invalid
                self.assertTrue(any('.dates.target_at:' in e for e in validate_document(self.document)))

    def test_pending_lead_cannot_claim_a_review_date(self):
        self.record['verification_status'] = 'pending'
        self.assertTrue(any('pending records must use null' in e for e in validate_document(self.document)))
        self.record['last_verified_at'] = None
        self.record['sources'][0].update(locator=None, accessed_at=None, supports=None)
        self.assertEqual([], validate_document(self.document))

    def test_verified_source_requires_location_access_date_and_specific_support(self):
        for field in ('locator', 'accessed_at', 'supports'):
            with self.subTest(field=field):
                document = copy.deepcopy(self.document)
                document['records'][0]['sources'][0][field] = None
                self.assertTrue(any(f'.sources[0].{field}:' in e for e in validate_document(document)))

    def test_review_date_cannot_precede_source_access_or_be_in_future(self):
        self.record['last_verified_at'] = '2024-01-02'
        self.assertTrue(any('later than last_verified_at' in e for e in validate_document(self.document)))
        self.record['last_verified_at'] = '9999-12-31'
        self.assertTrue(any('cannot be in the future' in e for e in validate_document(self.document)))

    def test_as_of_ceiling_is_inclusive_for_review_and_access_dates(self):
        ceiling = dt.date(2024, 2, 29)
        for value, rejected in [('2024-02-28', False), ('2024-02-29', False), ('2024-03-01', True)]:
            with self.subTest(date=value):
                self.record['last_verified_at'] = value
                self.record['sources'][0]['accessed_at'] = value
                with mock.patch('scripts.validate_records.dt.datetime') as clock:
                    errors = validate_document(self.document, as_of=ceiling)
                    clock.now.assert_not_called()
                if rejected:
                    self.assertEqual(2, len(errors))
                    self.assertTrue(any('.last_verified_at:' in error for error in errors))
                    self.assertTrue(any('.sources[0].accessed_at:' in error for error in errors))
                else:
                    self.assertEqual([], errors)

    def test_default_date_uses_current_utc_day_once(self):
        current = dt.datetime(2024, 2, 29, 23, 59, tzinfo=dt.timezone.utc)
        for value, rejected in [('2024-02-29', False), ('2024-03-01', True)]:
            with self.subTest(date=value):
                self.record['last_verified_at'] = value
                self.record['sources'][0]['accessed_at'] = value
                with mock.patch('scripts.validate_records.dt.datetime') as clock:
                    clock.now.return_value = current
                    errors = validate_document(self.document)
                    clock.now.assert_called_once_with(dt.timezone.utc)
                self.assertEqual(rejected, bool(errors))

    def test_as_of_does_not_replace_source_chronology_or_policy_dates(self):
        self.record['last_verified_at'] = '2024-02-28'
        self.record['sources'][0]['accessed_at'] = '2024-02-29'
        self.record['dates']['target_at'] = '2025-01-01'
        errors = validate_document(self.document, as_of=dt.date(2024, 2, 29))
        self.assertEqual(1, len(errors))
        self.assertIn('cannot be later than last_verified_at', errors[0])

    def test_cli_uses_one_date_ceiling_across_all_files(self):
        current = dt.datetime(2024, 2, 29, 23, 59, tzinfo=dt.timezone.utc)
        later = current + dt.timedelta(days=1)
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for index, value in enumerate(['2024-02-29', '2024-03-01']):
                document = copy.deepcopy(self.document)
                record = document['records'][0]
                record['id'] = f'synthetic-cutoff-{index}'
                record['last_verified_at'] = value
                record['sources'][0]['accessed_at'] = value
                path = Path(directory) / f'synthetic-private-marker-{index}.json'
                path.write_text(json.dumps(document), encoding='utf-8')
                paths.append(str(path))
            for options in [[], ['--as-of', '2024-02-29']]:
                with self.subTest(options=options):
                    stderr = io.StringIO()
                    with mock.patch('scripts.validate_records.dt.datetime') as clock, contextlib.redirect_stderr(stderr):
                        clock.now.side_effect = [current, later]
                        self.assertEqual(1, main(options + paths))
                        if options:
                            clock.now.assert_not_called()
                        else:
                            clock.now.assert_called_once_with(dt.timezone.utc)
                    self.assertNotIn('input-1', stderr.getvalue())
                    self.assertEqual(2, stderr.getvalue().count('input-2'))
                    self.assertNotIn(directory, stderr.getvalue())
                    self.assertNotIn('synthetic-private-marker', stderr.getvalue())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, main(['--as-of', '2024-03-01'] + paths))

    def test_cli_rejects_invalid_as_of_without_echoing_supplied_values(self):
        invalid_dates = ['2023-02-29', '2024-13-01', '0000-01-01', '20240229',
                         '2024-W09-4', '2024-2-29', '2024-02-29T00:00:00Z',
                         'synthetic-private-date-marker']
        with tempfile.TemporaryDirectory() as directory:
            private_input = str(Path(directory) / 'synthetic-private-input-marker.json')
            invalid_dates.append(private_input)
            for value in invalid_dates:
                with self.subTest(value=value):
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        with self.assertRaises(SystemExit) as raised:
                            main(['--as-of=' + value, private_input])
                    self.assertEqual(2, raised.exception.code)
                    self.assertIn('must be a valid calendar date in YYYY-MM-DD format', stderr.getvalue())
                    self.assertNotIn(value, stdout.getvalue() + stderr.getvalue())
                    self.assertNotIn(private_input, stdout.getvalue() + stderr.getvalue())

    def test_synthetic_records_cannot_be_mistaken_for_real_evidence(self):
        self.record['sources'][0]['url'] = 'https://commission.europa.eu/topics/preparedness_en'
        self.assertTrue(any('synthetic sources must' in e for e in validate_document(self.document)))
        self.record['sources'][0]['url'] = 'https://sub.example.org/fixture'
        self.record['record_type'] = 'real'
        self.record['id'] = 'real-example'
        self.assertTrue(any('real records cannot use reserved' in e for e in validate_document(self.document)))

    def test_source_urls_reject_credentials_and_invalid_ports(self):
        for invalid in ('http://example.org/page', 'https://fictional-user@example.org/page', 'https://example.org:abc/page', 'https://example.org:8080/page', 'https://example.org/a b', 'https://[bad/page'):
            with self.subTest(url=invalid):
                self.record['sources'][0]['url'] = invalid
                self.assertTrue(any('.url:' in e for e in validate_document(self.document)))

    def test_source_urls_reject_local_hosts_ip_literals_and_credential_queries(self):
        for url in ('https://localhost/page', 'https://policy.local/page', 'https://127.0.0.1/page', 'https://[::1]/page', 'https://8.8.8.8/page', 'https://example.org/page?api_key=synthetic', 'https://example.org/page?access_token=synthetic'):
            with self.subTest(url=url):
                self.record['sources'][0]['url'] = url
                self.assertTrue(any('.url:' in e for e in validate_document(self.document)))
        self.record['record_type'] = 'real'
        self.record['id'] = 'treaty-source-query'
        self.record['sources'][0]['url'] = 'https://treaties.un.org/Pages/ViewDetails.aspx?chapter=26&clang=_en&mtdsg_no=XXVI-5&src=TREATY'
        self.assertEqual([], validate_document(self.document))

    def test_absolute_dns_names_cannot_bypass_local_ip_or_reserved_checks(self):
        self.record['record_type'] = 'real'
        self.record['id'] = 'absolute-dns-name-test'
        for url in ('https://localhost./page', 'https://policy.local./page', 'https://127.0.0.1./page', 'https://example.org./page', 'https://sub.example.com./page'):
            with self.subTest(url=url):
                self.record['sources'][0]['url'] = url
                self.assertTrue(any('.url:' in e for e in validate_document(self.document)))
        self.record['sources'][0]['url'] = 'https://treaties.un.org./Pages/ViewDetails.aspx?chapter=26&src=TREATY'
        self.assertEqual([], validate_document(self.document))

    def test_cli_never_prints_a_private_input_filename(self):
        marker = 'synthetic-private-filename-marker'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / (marker + '.json')
            path.write_text('{', encoding='utf-8')
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(1, main([str(path)]))
            self.assertNotIn(marker, stdout.getvalue() + stderr.getvalue())
            self.assertIn('input-1:', stderr.getvalue())

    def test_wrong_types_and_unknown_fields_produce_errors_without_crashing(self):
        self.record['policy_stage'] = []
        self.record['sources'] = 'not an array'
        self.record['private-field-marker'] = 'must not print this raw value'
        errors = validate_document(self.document)
        self.assertGreaterEqual(len(errors), 3)
        self.assertNotIn('private-field-marker', '\n'.join(errors))
        self.assertNotIn('must not print this raw value', '\n'.join(errors))

    def test_blank_evidence_is_not_a_verified_source(self):
        self.record['sources'][0]['supports'] = '   '
        self.record['limitations'] = []
        self.assertTrue(any('.supports:' in e for e in validate_document(self.document)))
        self.assertTrue(any('.limitations:' in e for e in validate_document(self.document)))

    def test_cli_reports_success_but_never_claims_factual_verification(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            paths = sorted((ROOT / 'data').glob('*.json')) + sorted((ROOT / 'examples').glob('*.json'))
            result = main([str(path) for path in paths])
        self.assertEqual(0, result)
        expected_count = sum(len(json.loads(path.read_text(encoding='utf-8'))['records']) for path in paths)
        self.assertIn(f'{expected_count} structurally valid records', output.getvalue())
        self.assertIn('not factual verification', output.getvalue())

    def test_cli_rejects_malformed_duplicate_key_and_non_finite_json(self):
        cases = ('{', '{"schema_version":1,"schema_version":1,"records":[]}', '{"schema_version":NaN,"records":[]}')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'invalid.json'
            for content in cases:
                with self.subTest(content=content):
                    path.write_text(content, encoding='utf-8')
                    stderr = io.StringIO()
                    with contextlib.redirect_stderr(stderr):
                        self.assertEqual(1, main([str(path)]))
                    self.assertIn('input-1:', stderr.getvalue())
                    self.assertNotIn(directory, stderr.getvalue())

    def test_cli_missing_file_returns_failure_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                result = main([str(Path(directory) / 'missing.json')])
            self.assertEqual(1, result)
            self.assertNotIn('Traceback', stderr.getvalue())
            self.assertNotIn(directory, stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
