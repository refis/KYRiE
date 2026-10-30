"""Summarize reported problems without declaring capture completeness."""
from collections import Counter


def summarize_quality(report):
    findings = []
    def add(section, code, count):
        if count:
            findings.append(dict(section=section, code=code, count=count))
    transport = report['replay']
    add('transport', 'stopped_connections', transport.get('failed_connections', 0))
    add('transport', 'incomplete_streams', len(transport.get('incomplete_streams', [])))
    add('transport', 'session_end_missing', int(transport.get('session_end_present') is not True))
    stats = transport.get('tcp_statistics')
    if stats is None:
        add('transport', 'tcp_diagnostics_unavailable', 1)
    else:
        add('transport', 'assumed_boundaries', stats.get('assumed_boundaries', 0))
        add('transport', 'waiting_for_syn', stats.get('waiting_syn_segments', 0))
    issue_counts = {}
    for name in ('world', 'player', 'dialogues', 'shops', 'combat', 'skills'):
        issue_counts[name] = report[name].get('issue_count', 0)
        add(name, 'analysis_issues', issue_counts[name])
    for name in ('combat', 'skills', 'mob_spawns'):
        add(name, 'capacity_reached', int(report[name].get('saturated', False)))
    add('world', 'pending_names_evicted', report['world'].get('evicted_pending_names', 0))
    add('world', 'display_observations_dropped', report['world'].get('display_dropped', 0))
    dialogues = report['dialogues']
    add('dialogues', 'presentations_dropped', dialogues.get('presentation_dropped', 0))
    statuses = Counter(row['status'] for row in dialogues.get('conversations', []))
    add('dialogues', 'capacity_reached', statuses.get('capacity_reached', 0))
    # Conversation issues can exist without incrementing the store's issue count.
    add('dialogues', 'conversation_issues', sum(len(row.get('issues', []))
                                              for row in dialogues.get('conversations', [])))
    flags = Counter(flag for row in dialogues.get('timelines', []) for flag in row.get('quality_flags', []))
    for flag, count in sorted(flags.items()):
        add('dialogues', 'timeline_' + flag, count)
    merged = report['merged_dialogues']
    add('generation', 'errors', len(merged.get('generation_errors', [])))
    add('generation', 'input_capacity_reached', int(merged.get('input_capacity_reached', False)))
    add('generation', 'excluded_conversations', len(merged.get('excluded', [])))
    add('dialogues', 'presentation_conflicts', sum(group.get('presentation_check', {}).get('conflicts', 0)
                                                  for group in merged.get('groups', [])))
    return dict(status='review_required' if findings else 'no_reported_issues',
                capture_completeness='not_verified', issue_counts=issue_counts,
                findings=findings, conversation_statuses=dict(sorted(statuses.items())),
                unattributed_skill_notifications=report['skills'].get('unattributed_notifications', 0),
                unattributed_attack_notifications=report['combat'].get('unattributed_attack_notifications', 0))
