from copy import deepcopy
import unittest

from reconstruction.session_quality import summarize_quality


def report_fixture():
    return dict(replay=dict(failed_connections=0, incomplete_streams=[], session_end_present=True,
                            tcp_statistics={}),
                **{key: {'issue_count': 0} for key in ('world', 'player', 'dialogues', 'shops', 'combat', 'skills')},
                mob_spawns={}, merged_dialogues={})


class SessionQualityTests(unittest.TestCase):
    def test_no_reported_issues_never_means_complete_capture(self):
        report = report_fixture()
        before = deepcopy(report)
        quality = summarize_quality(report)
        self.assertEqual(quality['status'], 'no_reported_issues')
        self.assertEqual(quality['capture_completeness'], 'not_verified')
        self.assertEqual(quality['findings'], [])
        self.assertEqual(report, before)

    def test_transport_capacity_nested_dialogue_and_generation_findings_are_separate(self):
        report = report_fixture()
        report['replay'].update(failed_connections=1, incomplete_streams=[{}], session_end_present=False,
                                tcp_statistics={'assumed_boundaries': 2, 'waiting_syn_segments': 3})
        report['world'].update(issue_count=4, evicted_pending_names=1)
        report['skills'].update(saturated=True, unattributed_notifications=5)
        report['dialogues'].update(presentation_dropped=1,
            conversations=[dict(status='capacity_reached', issues=[{'message': 'nested issue'}])],
            timelines=[{'quality_flags': ['unmatched_reply']}])
        report['merged_dialogues'].update(generation_errors=[{}], excluded=[{}], input_capacity_reached=True,
                                         groups=[{'presentation_check': {'conflicts': 2}}])
        before = deepcopy(report)
        quality = summarize_quality(report)
        codes = {(row['section'], row['code']): row['count'] for row in quality['findings']}
        self.assertEqual(quality['status'], 'review_required')
        for section, code, count in (('transport', 'stopped_connections', 1),
                                     ('transport', 'assumed_boundaries', 2),
                                     ('transport', 'session_end_missing', 1),
                                     ('world', 'analysis_issues', 4), ('skills', 'capacity_reached', 1),
                                     ('dialogues', 'conversation_issues', 1),
                                     ('dialogues', 'presentation_conflicts', 2),
                                     ('generation', 'errors', 1)):
            with self.subTest(code=code):
                self.assertEqual(codes[section, code], count)
        self.assertEqual(quality['unattributed_skill_notifications'], 5)
        self.assertEqual(quality['issue_counts']['dialogues'], 0)
        self.assertEqual(report, before)
        report['replay']['tcp_statistics'] = None
        self.assertIn('tcp_diagnostics_unavailable', [row['code'] for row in summarize_quality(report)['findings']])

    def test_dropped_appearance_changes_require_review(self):
        report=report_fixture()
        report['world']['display_dropped']=3
        quality=summarize_quality(report)
        self.assertEqual(quality['status'],'review_required')
        self.assertIn(dict(section='world',code='display_observations_dropped',count=3),quality['findings'])
