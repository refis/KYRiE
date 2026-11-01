"""Detached model state and rendering inputs for background report construction."""
from copy import deepcopy
from dataclasses import dataclass


@dataclass(frozen=True)
class MobReportSnapshot:
    store: object
    extras: dict

    def build(self):
        # Summary generation uses only detached buckets/events/counters, never world.
        return dict(self.store.snapshot(),**self.extras)


def freeze_mob_report(store,sources,names=None):
    # Preserve aliases between events, pending casts and buckets with one memo.
    # World is mutable, large and unnecessary for summaries; never copy/share it.
    detached=deepcopy(store,{id(store.world):None})
    extras={'source_sessions':deepcopy({str(key):value for key,value in sources.items()})}
    if names is not None:extras['skill_names']={str(key):value for key,value in names.items()}
    return MobReportSnapshot(detached,extras)


@dataclass(frozen=True)
class NpcReportSnapshot:
    entities: list
    conversations: list
    sources: dict
    merge: bool
    shops: list
    barters: list
    rendering: object
    text_output: bool=False
    identity: dict | None=None

    def build(self):
        from reconstruction.npc_bundle import build_npc_bundle
        with self.rendering.activate():
            report=build_npc_bundle(self.entities,self.conversations,self.sources,merge=self.merge,shops=self.shops,
                                   barters=self.barters, identity=self.identity)
        if not report['entries'] and not report['excluded']:raise ValueError('NPCの観測がありません。')
        return report


def freeze_npc_report(entities,conversations,sources,*,merge,shops=(),barters=(),identity=None):
    from reconstruction.render_inputs import freeze_npc_render_inputs
    entities,conversations,sources,shops,barters=deepcopy(
        (list(entities),list(conversations),dict(sources),list(shops),list(barters)))
    return NpcReportSnapshot(entities,conversations,sources,merge,shops,barters,freeze_npc_render_inputs(),
                             identity=dict(identity or {}))
