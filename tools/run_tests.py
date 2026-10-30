"""Explicit feature suites; no implicit full-suite execution."""
import argparse
import unittest

GROUPS = {'catalog': ['tests.unit.test_skill_catalog','tests.unit.test_skill_units','tests.unit.test_reference_names','tests.unit.test_client_names','tests.unit.test_navigation'], 'release': ['tests.unit.test_snapshot'],'commands': ['tests.unit.test_script_commands'], 'capture': ['tests.unit.test_capture',
             'tests.unit.test_send_capture',
             'tests.unit.test_process_monitor',
             'tests.unit.test_protocol',
             'tests.unit.test_protocol_probe',
             'tests.unit.test_extractor'],
 'ipc': ['tests.unit.test_ipc'],
 'dialogue': ['tests.unit.test_dialogue',
              'tests.unit.test_dialogue_closing',
              'tests.unit.test_dialogue_format',
              'tests.unit.test_branches',
              'tests.unit.test_timeout_merging',
              'tests.unit.test_instance_mode'],
 'presentation': ['tests.unit.test_script_commands', 'tests.unit.test_conversation_actions', 'tests.unit.test_announcement_observations',
                  'tests.unit.test_classchange_observations',
                  'tests.unit.test_effect_removal',
                  'tests.unit.test_effect_value',
                  'tests.unit.test_external_presentations',
                  'tests.unit.test_music_observations',
                  'tests.unit.test_overhead_observations',
                  'tests.unit.test_progressbar_observations',
                  'tests.unit.test_viewpoint_observations'],
 'npc': ['tests.unit.test_actor_appearance', 'tests.unit.test_touch_npc', 'tests.unit.test_npc_bundle',
         'tests.unit.test_npc_initial_state',
         'tests.unit.test_entity_metadata',
         'tests.unit.test_actor_identity'],
 'shop': ['tests.unit.test_shops', 'tests.unit.test_shop_export', 'tests.unit.test_npc_bundle'],
 'player': ['tests.unit.test_inventory_audit', 'tests.unit.test_player',
            'tests.unit.test_quest_observations',
            'tests.unit.test_world'],
 'mob': ['tests.unit.test_report_snapshot', 'tests.unit.test_skill_hp_context', 'tests.unit.test_combat',
         'tests.unit.test_skills',
         'tests.unit.test_mob_spawns',
         'tests.unit.test_mob_skill_export'],
 'display': ['tests.unit.test_display', 'tests.unit.test_ignorepacket'],
 'events': ['tests.unit.test_timing',
            'tests.unit.test_event_trials',
            'tests.unit.test_event_trial_selection',
            'tests.unit.test_event_timer_export'],
 'storage': ['tests.unit.test_database', 'tests.unit.test_observation_export',
             'tests.unit.test_session_log',
             'tests.unit.test_session_quality',
             'tests.unit.test_project'],
 'gui-capture': ['tests.integration.test_gui_capture'],
 'gui-display': ['tests.integration.test_gui_display'],
 'gui-restoration': ['tests.integration.test_gui_restoration'],
 'gui-timing': ['tests.integration.test_gui_timing'],
 'offline': ['tests.integration.test_offline', 'tests.integration.test_project_references'],
 'pipe': ['tests.integration.test_pipe_server'],
 'selection': ['tests.unit.test_test_selection']}


def selected_names(targets):
    names = []
    for target in targets:
        if target in GROUPS:
            names.extend(GROUPS[target])
        elif target.startswith(('tests.unit.test_', 'tests.integration.test_')):
            names.append(target)
        else:
            raise ValueError('Unknown test target: ' + target)
    return list(dict.fromkeys(names))


def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


def selected_suite(names, loader=None):
    loader = loader or unittest.TestLoader()
    unique = {}
    for name in names:
        for case in cases(loader.loadTestsFromName(name)):
            unique.setdefault(case.id(), case)
    return unittest.TestSuite(unique.values())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('targets', nargs='*', help='Feature group or dotted unittest module/class/method')
    parser.add_argument('--list', action='store_true', help='List groups without importing or running tests')
    parser.add_argument('--dry-run', action='store_true', help='Show selected case IDs without running them')
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args(argv)
    if args.list:
        for group, names in GROUPS.items():
            print(group + ': ' + ', '.join(names))
        return 0
    if not args.targets:
        parser.error('Specify feature groups or test names; use --list to inspect groups.')
    try:
        names = selected_names(args.targets)
    except ValueError as exc:
        parser.error(str(exc))
    loader = unittest.TestLoader()
    suite = selected_suite(names, loader)
    if args.dry_run:
        for case in cases(suite):
            print(case.id())
        if loader.errors:
            for error in loader.errors:
                print(error)
            return 1
        print('Selected: ' + str(suite.countTestCases()))
        return 0
    print('Targets: ' + ', '.join(names), flush=True)
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
