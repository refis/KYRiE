"""Audit presentation comparison hashes and reason coverage from a saved analysis."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from reconstruction.event_trials import compare_event_trials,event_semantics,trial_review
from reconstruction.comparison_anchors import anchor_identity
from storage.observation_export import save_observations


def review_unittalk(rows, max_details=1000):
    """Preliminary inventory only; a matching window and manual adoption are still required."""
    if type(max_details) is not int or not 1 <= max_details <= 1000:
        raise ValueError('Detail limit must be 1..1000')
    selected=[row for row in rows if row['kind']=='unittalk']
    reasons=Counter();details=[];candidates=0
    for row in selected:
        excluded=[]
        if row.get('context')!='outside_dialogue':excluded.append('context_'+str(row.get('context')))
        if row.get('entity_kind')!='NPC':excluded.append('not_npc')
        if row.get('target_observed') is not True:excluded.append('target_unobserved')
        try:anchor_identity(row)
        except ValueError:excluded.append('placement_unavailable')
        if row.get('comparison_scope') or row.get('anchor_type','presentation')!='presentation':
            excluded.append('comparison_only_scope')
        if type(row.get('packet_index')) is not int or row['packet_index']<0:excluded.append('packet_unavailable')
        when=row.get('timestamp')
        try:valid=type(when) in (int,float) and math.isfinite(when)
        except OverflowError:valid=False
        if not valid:excluded.append('invalid_time')
        fields=row.get('fields',{})
        if set(fields)!={'text'} or not isinstance(fields.get('text'),str) or len(fields['text'])>65535:
            excluded.append('invalid_text')
        reasons.update(excluded)
        candidates+=not excluded
        if len(details)<max_details:
            details.append(dict(capture_session=row.get('capture_session'),flow_id=row.get('flow_id'),
                packet_index=row.get('packet_index'),actor_id=row.get('actor_id'),
                npc=row.get('npc',{}),context=row.get('context'),fields=fields,
                exclusion_reasons=excluded,preliminary_anchor_candidate=not excluded))
    return dict(count=len(selected),contexts=dict(Counter(row['context'] for row in selected)),
        entity_kinds=dict(Counter(row.get('entity_kind') for row in selected)),
        preliminary_anchor_candidates=candidates,exclusion_reason_counts=dict(reasons),
        details=details,omitted_details=max(0,len(selected)-len(details)),
        preliminary_only=True,manual_adoption_performed=False,cause_confirmed=False,
        warning='Candidates still require matching anchors, a valid trial window, manual times and explicit confirmation. Reason counts overlap.')


def audit(path,dialogue_actions=False):
    path=Path(path).resolve()
    if path.stat().st_size>64*1024*1024:raise ValueError('Analysis exceeds 64 MiB')
    raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    report=json.loads(raw)
    rows=report['dialogues']['presentation_observations']
    unittalk=review_unittalk(rows)
    if dialogue_actions:
        from types import SimpleNamespace
        from reconstruction.dialogue import Conversation
        from reconstruction.comparison_anchors import comparison_rows
        store=SimpleNamespace(presentation_observations=rows,
            sessions=[Conversation(**row) for row in report['dialogues']['conversations']],
            map_arrival_anchors=report['dialogues']['map_arrival_anchors'])
        rows=comparison_rows(store,'dialogue_start',include_actions=True)
    if len(rows)>14000:raise ValueError('Presentation limit exceeded')
    groups={}
    for index,row in enumerate(rows):
        if dialogue_actions:
            if row.get('anchor_type')!='dialogue_start':continue
        elif row['context']!='outside_dialogue':continue
        try:identity=anchor_identity(row)
        except ValueError:continue
        key=json.dumps([identity,event_semantics(row)],sort_keys=True,ensure_ascii=False)
        groups.setdefault(key,[]).append(index)
    comparisons=[]
    for anchors in groups.values():
        if len(anchors)<2:continue
        anchors=anchors[:20]
        compared=compare_event_trials(rows,anchors,window_ms=5000)
        encoded=json.dumps(compared,sort_keys=True,ensure_ascii=False,allow_nan=False).encode('utf-8')
        excluded=Counter()
        for index in range(len(compared['trials'])):
            excluded.update(trial_review(compared,index,rows)['excluded_counts'])
        comparisons.append(dict(anchors=anchors,status=compared['status'],
            comparison_sha256=hashlib.sha256(encoded).hexdigest(),review_exclusions=dict(excluded)))
    if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Input changed during audit')
    return dict(kind='event_trial_review_audit',source_analysis=str(path),source_sha256=digest,
        observation_count=len(rows),kinds=dict(Counter(row['kind'] for row in rows)),
        contexts=dict(Counter(row['context'] for row in rows)),comparisons=comparisons,
        dialogue_actions=dialogue_actions,action_rows=sum(row.get('comparison_scope')=='dialogue_owner' for row in rows),
        unittalk_review=unittalk,selected_for_validation_only=True,cause_confirmed=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('analysis');parser.add_argument('--output',required=True)
    parser.add_argument('--dialogue-actions',action='store_true')
    args=parser.parse_args()
    report=audit(args.analysis,args.dialogue_actions)
    save_observations(args.output,report,[args.analysis])
    print(json.dumps(dict(observations=report['observation_count'],kinds=report['kinds'],
        comparison_groups=len(report['comparisons']),action_rows=report['action_rows'],
        unittalk={key:report['unittalk_review'][key] for key in ('count','preliminary_anchor_candidates','exclusion_reason_counts')})))


if __name__=='__main__':main()
