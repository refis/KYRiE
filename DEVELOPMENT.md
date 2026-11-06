# Development baseline and plan

## Local ignorepacket defaults; no empty ZIP/Git overwrite (2026-11-06)

ignorepacket.json is gitignored and omitted from source snapshots (like
user_settings). Missing file: IgnorePacket.ensure_default_file writes an empty
preset once and never overwrites an existing file. Tracked template is
ignorepacket.example.json. Snapshot no longer injects empty ignorepacket into
the ZIP. Selected: display release + unit ignorepacket.

## GUI P2-2 shortcuts and startup checklist (2026-11-06)

After v0.0.10: F5 start / F8 stop / Ctrl+Shift+O open log, blocked while typing
in editable fields. Non-modal startup checklist is guidance-only (does not flip
capture/display settings); dismissal sets startup_checklist_seen in user_settings.
Auto-show skipped under QT_QPA_PLATFORM=offscreen. Selected: storage + gui-display.

## v0.0.10 snapshot and no-EXE policy (2026-11-06)

Bumped to v0.0.10 before GUI discoverability work changes the feel. Packaging
note now forbids EXE builds and EXE distribution (venv+source and private
source ZIP only). Docs index already split user/contract/development.
Post-snapshot next: guide purification then GUI P2-1.

## Packaging / docs audience / GUI UX consideration (2026-11-06)

Added docs/development/packaging-docs-gui-ux.md and docs index audience split.
Later revised: EXE packaging/distribution cancelled by user policy.

## Roadmap / docs / tests sync after #128–#133 (2026-11-06)

Resynced `docs/development/development-roadmap.md` next-work units with post-v0.0.9
main (#128 Auriga navigateto/progressbar_npc, #129/#131 flood thrash, #130/#132
Zeny/EXP adoption, #133 0ACC suppress + observation-log pin). Fixed stale EXP
wording in receive-display / P1-A / MARiA §3 / O1. Tidied progress-notes and
tests/README (grouped module count, point snapshot pointer to v0.0.9). Docs/tests
catalog only; no runtime change. Not full discover.

## MARiA gap docs refresh (2026-11-01)

Reconfirmed MARiA vs KYRiE claims against current code (local `.reference/MARiA`
absent in this environment; no fresh upstream re-fetch). Updated
docs/capture/receive-display.md: replaced stale “未移植” / “追加提案（未実装）”
with implemented vs intentional-gap lists and remaining display/load work.
Tightened development-roadmap.md §2 into a per-kind table (observe / comment /
conditional command). Docs only; no runtime change. Not full discover.

## rAthena status Icon 12/50 adoption and display sc_end conversion (2026-10-31)

Re-verified frozen baseline commit d4b8e7b8 against current rAthena master (same SHA).
status.hpp / db/re/status.yml / status.cpp SHA256 matched the recorded values.
Adopted EFST_INC_AGI (12)→SC_INCREASEAGI (32) and EFST_NOEQUIPWEAPON (50)→SC_STRIPWEAPON (68)
by user policy (not observation-unique); exclusion candidates kept under excluded_candidates.
entries 888 / ambiguous 6 remain. argument_policy stays review for both; transform val1_only
unchanged. rAthena display 0196 flag=0 now emits sc_end with converted SC only; unresolved
icons become @status_end_unresolved. Generation path already used script_id. CLI emulator
flag was deferred then; see following section. No ongoing upstream tracking in this change.
Selected: display + conversation_actions + gui-display. Not full discover.

## CLI --emulator for generation profiles (2026-10-31)

Analysis CLIs that load generation profiles accept `--emulator auriga|rathena`
(default auriga): analyze_session, analyze_dialogues, merge_dialogues,
analyze_entities, analyze_skills, compare_dialogue_timing. Shared helper
tools/cli_emulator.py calls set_target before analysis. Reports record
`emulator` and profile paths under config/<emulator>/. Receive-display JSON
CLI switching remains out of scope. Selected: cli-emulator + offline sample.

## rAthena input scope prefix .@ (2026-10-30)

rAthena dialogue/display input templates now use `.@gpa_*` / `.@num` / `.@str$`
instead of Auriga's `'@` temporary-variable prefix. Auriga profiles unchanged.

## rAthena generation profiles and emulator switch (2026-10-30)

Filled config/rathena/status_ids.json from a one-shot check of rAthena master
d4b8e7b8 (status.hpp SC/EFST enums + db/re/status.yml Icon/SendVal1). No ongoing
upstream tracking. Added rAthena dialogue/entity_metadata/shops/mob_*/event_timers/
script_commands JSON with dialect adaptations (npctalk, instance_mapname/npcname,
specialeffect, progressbar quoted color, setnpcdisplay function form, makeitem).
send_display stays shared. Wired reconstruction.emulator_profiles.set_target into
GUI emulator selection and generation loaders. Targeted presentation/display/
dialogue-related checks; no full discovery.

## rAthena receive-display JSON parity (2026-10-30)

Expanded config/rathena/display.json from the four-dialogue seed to the same
packet-ID set as config/auriga/display.json for emulator log viewing. Omitted
Auriga instance_* getmdmapname/mdenter keys; left entity_metadata false for the
receive-display profile; rewrote unverified messize/mespos/mesalign/mdcreate/
self-unittalk lines as review comments. Generation profiles were added in a
follow-up (see section above). Targeted display and related GUI emulator checks
only; no full discovery.

## GitHub management bootstrap (2026-10-30)

Added CONTRIBUTING.md, SECURITY.md, NOTICE, Issue/PR templates, CODEOWNERS,
offscreen CI workflow, docs/development/working-agreement.md,
docs/development/github-labels.md and docs/releases/README.md. Snapshot allowlist
now packages .github templates and the new root docs. Custom labels could not be
created by the integration token (403); maintainer runs github-labels.md once.
Targeted release/selection checks passed, including the new snapshot packaging
case. No full discovery. Branch protection remains a manual GitHub setting.

CI on ubuntu-latest timed out wait_display_export (5s) during large MOB JSON
generation with the skill-name dictionary, cascading into later export_busy
skips. Raised shared export/close waits to 60s and generation-gate waits on the
large NPC/MOB/capture export tests. Re-check gui-restoration and gui-capture
locally before relying on Actions.

## Profile packet-table insertion and durable DB writes (post-v0.0.4, 2026-10-29)

Added profile_packet_path using temporary synthetic SQLite files and a bare
QTableWidget, isolating file/memory DB commits from row insertion. No live capture,
real packet database, semantic decoding or full GUI latency included. Fixed explicit
closing of verification connections in the profiler before temporary-directory cleanup.

2000-packet 3-run isolated after medians: rollback file 3704.841ms, WAL+FULL
756.547ms, memory 5.627ms, table insertion 87.056ms. Earlier comparison independently
showed 3726.286 vs 754.968ms. File commit was dominant in this environment. Adopted
WAL with synchronous FULL and kept commit per packet; no delay/batch queue introduced.
Unavailable WAL falls back to the existing journal; memory DB stays memory. Actual
mode/sync/fallback are captured in capture_options metadata. Existing schema and
packet contents remain unchanged. Documentation explains backup after app exit and
not deleting live WAL sidecars; frozen snapshots still exclude the DB.

Targeted database/IPC/selection/capture GUI checks: 19 passed, followed by two
additional stop/file-visibility and offline-replay checks. Independent readers see
every successful add immediately and close/reopen preserves counts. No full suite
or deferred live checks. Local profile records use packet-path-profile-*.json.
Next: inspect DB failure diagnostics and GUI queued/processed visibility.

## Cast-heavy rendering and no-change refresh (post-v0.0.4, 2026-10-29)

Extended profile_mob_views with --casts and separate unchanged refresh timings.
5000 casts plus 5000 skill-damage notifications rendered 5000 cast rows at a
1321.030ms median. Reused the bounded pager with candidate/observation-order labels;
all existing candidate links remain retained, with at most 1000 visible rows.
Same isolated 3-run scenario after: 499.664ms median, 1000 visible cast rows.
1000-cast scenario: 484.774 -> 474.296ms. This is specific offscreen detail rendering,
not capture/DB/end-to-end performance. Skill model records remain 10000 in both.
No-change skill refresh already skipped rebuilding (median ~0.003ms); no additional
cache introduced. Saved-log profiles now fingerprint definitions as well as source.

Regression covers >1000 casts, both endpoints, history-page persistence, scope
clearing and unchanged full skill snapshots. Targeted skills/DB and relevant cast/
interval/HP/save GUI checks: 30 passed. No full discovery, live checks or new source
snapshot. Profile records: logs/mob-view-cast-profile-before.json and -after.json.
Next: measure packet row insertion and DB persistence separately from detail views.

## Measure and bound MOB detail rendering (post-v0.0.4, 2026-10-29)

Added tools.profile_mob_views with bounded synthetic sizes and saved-log replay.
Offscreen timing excludes capture, DB writes, exports and memory peaks. Three-run
isolated medians on 5000 synthetic notifications: skill detail 801.566 -> 267.990ms,
performance detail 1306.037 -> 254.799ms. On 1000, 249.260 -> 265.558ms and
228.640 -> 235.230ms: no general small-data speedup claim. Timing is environment-
specific and not end-to-end GUI/capture latency. Initial concurrent after/replay
measurement was superseded by an isolated after run for a comparable baseline.

Interval tables now page at 1000 rows with original endpoint references; older
pages stay navigable and selected historical pages survive refresh. Shared bounded
preview projection limits long JSON arrays, records per-path omission counts and
keeps full statistical counts and source data. Full exports and DB candidates stay
unchanged. Regression covers >1000 intervals, page navigation, source endpoints,
selection clearing, preview limits and complete model snapshots. Targeted combat/
skills/DB/HP and relevant GUI/save checks: 49 passed; no full suite.

Local records: logs/mob-view-profile-before.json, after-isolated.json (prefixed
mob-view-profile-), and mob-view-profile-saved-log.json. Saved Toy Factory replay:
11729 packets, 90 skill/1450 performance records; heaviest class detail medians
5.357ms (skills) and 60.509ms (performance), with no inferred conditions/settings.
Frozen v0.0.4 archive and deferred manual checks unchanged. Next: cast-heavy and
no-change redraw measurement before further O1/O2 changes.

## Parallel percentage/skill evidence (post-v0.0.4, 2026-10-29)

User expects percentage rather than absolute HP notifications and wants convenient
inspection for percentage-based skill conditions. The skill notification view now
shows preceding 0A36 five-percent-step value, acquisition-time age and separate HP
packet navigation. Optional manually entered <=/>= comparisons describe notification
values only; they never confirm current HP, trigger conditions or fill DB fields.
Cast-start and later effect/damage notifications remain separate time points.

A derived context helper uses capture/connection/map/actor/appearance/class scope,
packet ordering and valid timestamps; no future values, absolute-HP conversion,
interpolation or stale-value fallback. Unknown percentages, reversed times, quality
warnings and class roundtrips are not compared. Incomplete class-change history is
conservatively flagged. No new persistent record collection; source observations,
statistics, exports and DB candidates stay unchanged. Targeted context/skills/combat/
DB/selection and relevant GUI checks: 49 tests passed. No full suite, no deferred
manual checks, and frozen v0.0.4 archive unchanged.

## Compare retained individual MOB performance (post-v0.0.4, 2026-10-29)

Added a read-only individual-comparison tab under performance: server/ActorID order,
capture/map/visibility identities, outgoing/incoming notifications, speeds, observed
max HP, HP damage ranges and per-appearance minimum HP tick intervals. Quality flag
counts and first/last retained performance packet references are available per row.
Known invalid HP remains excluded by the existing model; no inferred base stats,
cooldowns, population counts or cross-appearance intervals are introduced.

The selected individual scope is respected, selection survives refresh and clears
on scope removal. At most 1000 summary rows are displayed, with complete exports
and source observations unchanged. Targeted combat and relevant performance/export
GUI checks: 19 tests passed. No full suite or deferred manual checks. Frozen v0.0.4
archive unchanged; no floor-item history work. Next: measure retained/synthetic-data
GUI/JSON display costs to choose O1/O2 work from evidence.

## Auriga skill DB NAME convention (post-v0.0.4, 2026-10-29)

Generated NAME now uses observed monster name + fullwidth ＠ + dictionary skill
name. External mob_skills.json supplies naming/fallback templates. Missing or
conflicting monster names use an explicit MOB_ID placeholder; unknown skill names
use SKILL_ID. Unsafe labels stay unresolved. Japanese manual NAME values are valid
up to 256 characters; delimiters/control characters, // and clear remain rejected.
The whole UTF-8 DB row is bounded to 1018 bytes for the reference reader's buffer.

Editor no longer silently truncates NAME at 64 characters. Old manually reviewed
NAME fields remain unchanged on reload; only the old generated observation label
is normalized for otherwise identical evidence/source validation. Other changes
remain strictly rejected. Targeted export and relevant GUI checks: 10 passed.
No full suite or deferred runtime checks; frozen v0.0.4 snapshot unchanged.

## Inspect retained MOB skill notifications (post-v0.0.4, 2026-10-29)

Added a read-only notification tab for the selected MOB class/skill or individual.
Shows capture/map generation/ActorID/visibility interval, kind, target/ground point,
level (not notified versus unknown raw versus observed valid), notification values,
quality and packet navigation. No new capture records, drop history or inferred
usage counts, levels, AI conditions or cooldowns. Selection survives refresh while
retained; clearing/changing scope clears stale references. Class/skill/entity checks
also protect detail selection from unrelated packet-index collisions.

Notification table and preview bodies are bounded to the last 1000 records; full
statistics, casts, intervals, storage limits, JSON export and DB candidates remain
unchanged. Restored original MOB tab ordering by appending appearance history last,
fixing an earlier view-position regression discovered by the existing GUI test.
Targeted skills/DB-candidate and relevant skill/appearance GUI verification: 31 tests
passed. No full suite or deferred manual checks. v0.0.4 archive stays frozen. Next:
inspect individual performance comparison and quality navigation.

## Drop floor-item history expansion from plan (2026-10-29)

User declined floor-item history due to data growth and the availability of official
monster drop data for their workflow. Remove the proposed long-session history
expansion and do not add a drop-history view or collection/aggregation feature.
Keep the existing short correlation/deduplication needed for NPC dropitem candidates.
Prioritize NPC dialogue/event restoration and MOB skill/performance analysis. This
supersedes the floor-history next-step notes below. Documentation only; no code or
source data changes and no tests rerun. Deferred manual checks remain deferred.

## Navigate observed appearance changes (post-v0.0.4, 2026-10-29)

NPC/MOB details now include an appearance-history tab over the selected visibility
interval's retained 32 changes. Shows class/visual attributes/options/position deltas,
time, packet evidence and in-sight versus out-of-sight/reappearance uncertainty.
Selection survives list refresh when its evidence remains retained; changing or
hiding the entity clears stale references. Missing/evicted history is not invented.
Read-only copies preserve initial appearance, world observations and generation.
Targeted GUI display plus appearance offline-replay verification: 19 tests passed,
including NPC/MOB packet navigation, duplicate suppression, hair deltas, selection,
capacity and reappearance warnings. No full suite or deferred manual checks. Frozen
v0.0.4 archive remains unchanged. Next: bounded floor-item history for long sessions.

## Inspect event differences and excluded observations (post-v0.0.4, 2026-10-29)

User deferred clean-environment, live capture, Auriga runtime and publication checks;
continue feature work. Frozen v0.0.4 ZIP and its verification sidecars remain untouched.
P1-B now shows per-event targets and target/kind/content differences against the first
eligible reference. Missing counterpart observations remain explicit, with separate
current/reference packet navigation. A target-only MAP-window mismatch previously
appeared as content-equal in the summary; shared event semantics now keep grouping
and UI explanations consistent.

Added a separate derived review of same-capture/flow, within-window exclusions:
input/close waits, dialogue/external contexts, other targets/maps and next boundaries.
Per-reason counts and a 1000-detail cap preserve bounded inspection. Original reports,
variant membership, timer evidence and selection formats remain unchanged. Stale
references clear on observation/setting updates. No new timer or cause inference.
Targeted event comparison/selection/timer and GUI verification: 20 tests passed.
No full discovery and no deferred manual checks. Next: packet navigation from the
individual appearance-change history.

## v0.0.4 source snapshot preparation (2026-10-29)

Version is centralized in version.py and shown in the main window/application.
README now describes the current snapshot; removed the nonexistent example-definition
reference and obsolete planned-only claims. Updated documentation index, roadmap,
GUI/timer, empty NPC/OnInit and anchor comparison descriptions. Release record:
docs/releases/v0.0.4.md. Historical validation counts remain historical.

One full snapshot validation run discovered 485 tests: 483 initially passed and two
GUI expectations used older behavior. The partial-start fixture now uses a genuine
non-contact class; named external unittalk expects the implemented native command.
Both corrected tests passed on targeted rerun. No second full discovery. pip check
reported no broken requirements, and 39 Markdown files had no broken local links.
Current environment versions are recorded in requirements-lock.txt; clean dependency
installation and live Npcap/Auriga verification remain pending manual checks.

Added deterministic source packaging with an allowlist, per-file SHA-256 manifest,
ZIP checksum and overwrite refusal. Excludes logs/DB, client executables/extracted
maps, reference repositories, generated root code and caches. Only archived
ignorepacket preferences reset to defaults; working data stays unchanged. Packaging
exclusion/reproducibility/hash protection is included in the full test run.

## Server/ActorID ordering and explicit comparison anchors (2026-10-29)

NPC/MOB lists, world JSON and NPC bundles now sort by numeric server IP, port,
and numeric ActorID with stable capture/visibility ties. Unknown servers follow
known ones. Merged placements use their minimum source server/ActorID; grouped MOB
placement reports/candidates use their minimum observed ActorID. Selection survives
list refresh. Identity grouping, counts and source evidence are unchanged.

P1-B adds selectable dialogue-start and map-arrival anchors in the existing event
trial panel. Start anchors require observed click/touch and known placement; map
anchors require actual 0091/0092, not character-selection hints. Boundaries, flow,
capture and map generations prevent cross-map/window mixing. Dialogue steps project
supported presentations without changing original conversations; pending input and
close waits stay excluded. Map comparisons retain multiple target identities and
unassigned notifications without assigning NPC ownership. Name projection is for
comparison only. Hash-based anchor save/reload survives session/global-index changes
when the same comparison mode is selected. New anchor kinds cannot directly generate
NPC timers; existing manual times/adoption behavior is preserved.

Scope is bounded (2000 map anchors, 14000 comparison rows) with visible failures;
next-boundary lookup uses sorted per-flow indices. Existing manual presentation mode
and selection JSON remain compatible. Final selected verification: 41 tests passed
across ordering, bundle, MOB candidates, comparison, selection/timer export and GUI.
Earlier dependency checks covered 70 selected world/dialogue/quality/offline/GUI cases.
No full discovery or live/Auriga runtime run. Toy Factory replay: 11729 packets,
100 conversations, 44 groups, 12 map anchors, zero world/dialogue issues; both sorted
bundle modes retain 141 placements/12 exclusions. Source logs/previous exports kept.

## Review of work since October 28 19:21 JST (2026-10-29)

Scope was identified from development records and changed files, covering contact
ranges/instance names, scoped actions and conditional commands, appearance state,
NPC grouping/export and GUI/offline replay. This is a source review, not an
exhaustive historical Git diff or proof of live-game compatibility.

Five reproduced defects were fixed:
- Own-NPC 01B0 bypassed delta/visibility actions, duplicating unchanged commands and
  executing out-of-sight changes. Known own/other NPCs now share the action path.
- Projection to class 844 lost OnTouch in merged placement files. Touch evidence now
  retains observed and declaration classes separately; projection preserves scope.
- Invalid initial declaration classes could produce invalid output or abort a whole
  bundle during sorting. Projected classes are validated before placement grouping.
- Appearance-history capacity loss was absent from session quality findings.
- Initial visibility leaked across instance maps when ActorIDs coincided. Appearance
  and initial-state stores now share one server/capture/instance identity helper.

Two stale tests were repaired: classchange expects native setnpcdisplay, and source
mutation detection is keyed to the source path rather than fingerprint call count.
217 targeted cases were selected across the changed responsibilities and four GUI/
offline scenarios: 215 passed initially, the two corrected cases passed on rerun.
No full discovery. Synthetic cases cover the five fixes; no live/Auriga runtime run.

Replays: Toy Factory 11729 packets/100 conversations/44 groups; 20261027-175743
5457/31/12; 20261027-193248 3204/6/2. The eight world warnings in the second log are
identical to the previous same-source report (cp932 name fields), not regressions.
Toy Factory bundles retain 141 placements/12 exclusions, saved under audit-20261029
names without replacing previous exports or source logs. Transport/start-observation
quality warnings remain; none are treated as complete captures.

No speculative processing/timer values were imported from the reference script.
Floor-item history is deliberately bounded and retains disappeared IDs to avoid
mistaking viewport re-entry for a new scripted drop. A long-session history/eviction
policy and a clickable appearance history are follow-up improvements, not automatic
changes to command attribution. Continue with P1-B explicit dialogue-start/map-arrival
comparison anchors, preserving manual timer values and no inferred causes.

## Recorded appearance replay consistency (2026-10-29)

Added one integration scenario spanning SessionLog TCP segment persistence,
framing across an appearance packet boundary, CLI analysis and GUI offline replay.
Initial job appearance survives a class change, disappearance and reappearance;
only one initial-display OnInit is emitted. Duplicate appearances stay quiet,
CLI and GUI bundle outputs agree, and the source log remains byte-identical.
The single selected test passed. No production correction was needed; no full
suite or live/Auriga runtime run.

## Inspect initial and latest appearance in GUI (2026-10-29)

Individual information now shows initial/current class, NPC declaration class,
and initial versus last-observed visual fields. Unknown fields stay unknown; a
class-only notification does not prove other appearance values changed. Added
end-to-end coverage that merges conversations before/after a class change and
keeps the initial full setnpcdisplay once in OnInit, both in a single merged
placement file and the all-NPC bundle. Source state remains unmodified.
Targeted verification: 14 appearance tests and one relevant GUI test passed.
No full-suite or Auriga runtime run; no replay needed for this GUI-only change.

## Stable placement identity across class changes (2026-10-29)

Dialogue grouping now uses the initial declaration class, including class 844
for player-job NPC appearances. Later class changes no longer split the same
placement into separate conversation groups. Raw initial/current classes remain
untouched; genuinely different initial declaration classes remain distinct. Both
identified map placements and capture-local identities are covered. Unknown extra
appearance arguments are not assumed equivalent across packet types.
Targeted appearance/branch/bundle/timeout merging verification: 43 tests passed.
Replay retains 11729 packets, 100 conversations and 44 groups; regenerated bundle
modes each contain 141 placements with 12 exclusions. No full-suite or runtime run.

## Appearance notifications inside dialogue (2026-10-29)

Fixed an omission: class changes learned through 09FF/09FE/09FD now retain
setnpcdisplay actions for the speaking NPC or another NPC in the same map
generation. Full observed job appearance is retained, while reappearance changes
stay warning comments. Duplicate notifications are ignored. Action semantics omit
position/speed fields so unrelated movement cannot create appearance conflicts.
Targeted appearance/class-change/action/branch/bundle tests: 48 passed. Replay
retains 11729 packets, 100 conversations and 44 groups; this capture has no
class-change samples. No full-suite or Auriga runtime verification.

## First appearance, change-only logs and NPC display restoration (2026-10-28)

NPC/MOB first observations remain visible; subsequent observations emit changed
fields only, with raw packets retained. Player-job NPC declarations use class 844
and observed initial appearance in OnInit. Job IDs and display templates are external.
Initial classes survive later changes. In-sight NPC class changes use setnpcdisplay;
out-of-sight/reappearance changes remain warning comments. Dialogue actions include
other NPC targets; unassigned changes retain evidence without invented triggers.
Native shop declarations with player appearances remain review-only.

65 targeted tests passed across appearance, world, class changes, metadata, bundle,
shop, display, selection and one GUI scenario. Contact fixtures were adjusted to
represent actual first classes; the 15-test contact module also passed (80 targeted
tests total). Both regenerated bundle modes retain 141 placements/12 exclusions.
No full-suite or Auriga runtime run. Replay of 20261028-012526-0abe69d9 retained
11729 packets, 100 conversations and 44 groups. This capture has no player-job NPC
or class-change samples; those paths were validated synthetically. See
docs/observations/entity-observations.md for behavior and argument order.

## Conditional inventory/UI commands and waitingroom OnInit (2026-10-28)

Added scoped command candidates for openstorage, sc_end load notifications,
getitem/getitem2/delitem/delequip, refine results, unequip and own sit/stand.
Waitingroom observations bind only to verified NPC owners and render in OnInit;
observation-log suppression preserves raw packets and player/unknown rooms.
Equipment slots and pre-refine values must be observed; unsupported attributes
stay comments. Refine side effects supersede duplicate item-loss/unequip commands.
Observed storage transfers/manual drops are not NPC rewards. Requests survive
slow replies within a map generation, and send/receive half names share state by
flow. Reused inventory slots never inherit an earlier equipment binding.

Drop candidates exclude known MOB deaths and manual drops using a configurable
correlation window, including later death notifications. User-specified TOTAL
lifetime is 60000ms, with assumed Auriga base 60000ms; emit the difference 0,
rather than adding 60000ms to an existing base. Initial-view uncertainty stays
review-only. Instance map calls use getmdmapname. cutincard was explicitly
cancelled; existing cutin observations are unchanged. Global unassigned commands
retain evidence instead of acquiring an invented NPC owner.

Targeted verification covered command/inventory/dialogue/display/metadata modules
and three relevant GUI scenarios. One old observation-only expectation was updated
and rerun in isolation; subsequent changes used the commands suite, now 21 passing
tests, rather than full discovery. No full-suite run. The supplied capture retains
11729 packets, 100 conversations, 44 groups and zero dialogue issues: getitem11 and
dropitem9 candidates; both bundle modes retain 141 placements/12 placement exclusions.
Refine, posture, storage and waitingroom paths use synthetic validation; no Auriga
runtime test. See docs/npc/item-and-ui-commands.md for extra conditions and policy.

## Scoped dialogue actions and 15-cell contact ranking (2026-10-28)

Contact inference uses a 15-cell radius, class 139/111/844/45/other priority, then
a unique nearest candidate within the best class. Equal nearest candidates remain
unassigned with bounded inference evidence. Walk destinations never confirm arrival
or axes. Conversation.actions retains normal progressbars, observed hide/cloak
changes and self-player status notifications without changing input reply indices.
Other-NPC unittalk is projected inline with a named target; own-NPC commands omit
the target. Pending-input notifications carry explicit deferred-placement comments.
Actions and quest commands preserve source order, repeats compare semantic values
and timeout prefix normalization includes actions strictly before the unanswered
request. GUI timelines expose action labels and packet navigation.

External Auriga SI-to-SC mappings retain 643 unique IDs, 570 nonidentity values and
3 ambiguous icons, with source hashes. Argument policies default to review: only
three verified val1 correspondences generate sc_start; unobserved levels are never
filled. rAthena has a separate unverified empty table. Targeted unit progressbars
remain comments because the referenced Auriga has no matching NPC command.

Validation: 107 affected tests including two GUI scenarios passed; the revised
nearest-selection behavior was subsequently checked by the 15 touch tests only.
No full-suite run. Replayed the supplied capture: 11729 packets, 100 conversations,
44 merged groups, zero dialogue issues; progress5/visibility6/status4 actions. New
actions-named exports retain 141 placements/12 placement exclusions and actor15403
warp. One unresolved equal-nearest contact is retained in inference evidence.

## Event NPC contact candidates and independent range axes (2026-10-28)

Class 139 actor-addressed dialogue can anchor contact candidates alongside class 45.
Spatial warp association excludes currently hidden/cloaked entities, rather than
using initial visibility, and stays ambiguous when multiple eligible entities
remain at the same cell. X/Y positional evidence is stored independently. A lone
observed axis supplies a provisional value to its partner; later evidence for both
axes overrides borrowed values independently. Range-provisional comments remain
until both axes have evidence, for script and warp forms. Walk destinations never
confirm axes. Empty NPC one-line rendering applies to all classes.

Validation: 49 targeted tests in touch/bundle/initial-state/instance/format passed,
with the current-visibility case additionally checked for hideoff/cloakoff from
hidden initial states. No full-suite run. Replayed and regenerated the supplied
log: 141 placements, 12 placement exclusions, 44 merged groups, 1 class-139 contact
placement and 97 one-line empty declarations. Original raw evidence is retained.

## Conservative touch bounds and instance base names (2026-10-28)

Walking destinations are not arrival evidence: walk-only and unknown contact ranges
now use 1,1 (3x3); coordinate observations also have a minimum radius of 1 per axis.
Only coordinate events update the cached positional evidence, preventing status
notifications from relabelling a walk start as a confirmed position.

Instance warp declarations remain active and use literal base MAP names. Projection
removes a runtime three-character MAP prefix only when followed by the instance
MAP structure, and trims NPC suffixes only when all four characters match that MAP
token. Partial suffixes remain unchanged with ambiguous_partial in rendered_names;
raw observations are retained. Shared rendering, external NPC references and display
warp text use the base names while decoder fields stay raw.

Validation: 61 targeted touch/instance/bundle/shop/format/display tests passed; no
full-suite run. Regenerated both touch bundle modes for the supplied capture: 141
placements, 12 exclusions, 6 native warp entries, 12 unresolved partial-name cases.
Actor 15403 now renders as #fac1wp on 1@xm_d.gat with 45,1,1 and the observed warp.
This supersedes the previous default-5x5 and commented-instance-native-warp rules.

## Class-45 contact NPC restoration (2026-10-28)

Actor-addressed mes without a click can anchor a class-45 contact candidate.
Touch provenance preserves observed positions/walk destinations, minimum extents
and the default 5x5 fallback. Single nearby candidates at a map boundary retain
a warp observation, scoped by capture, flow and previous map generation; ambiguous
associations remain unassigned. Dialogue and warp paths merge under OnTouch without
fabricating SEND packets or conditions. Pure identical warp paths become warp
placements; instance-native declarations remain commented because they cannot
evaluate getmdmapname. Script warp calls retain instance functions. Empty placement
NPCs now use one line, preserving initial hidden/cloaked modifiers. All formatting
is externalized.

Targeted validation: 72 tests across touch, bundle, initial state, branches, closing,
instance and formatting; supplementary selection/timeout/quest checks and the
existing whole-NPC GUI-save scenario also passed. No full-suite run. Replayed the
Toy Factory capture: 11729 packets, 100 observations, 43 merged groups; 141 placements
and 12 placement exclusions retained. Actor 15403 combines three dialogue trials
and one warp trial. New touch-named exports preserve previous files and raw logs.

## Isolate invalid initial visibility during bulk export (2026-10-28)

Moved initial-state validation into the per-placement error boundary. Invalid
options previously aborted the entire bundle before that boundary; now only the
affected placement is excluded, with its original entities, observations, shops
and conversations retained. No visibility fallback is invented. Validation: 13
targeted tests in test_npc_bundle and test_npc_initial_state passed, including
negative, boolean, string and oversized options in both merge modes. No full run.

## Initial visibility in bundle NPC summaries (2026-10-28)

Bundle entry npc summaries now retain the resolved initial visibility and evidence
used to render their placement. Previously a first observation without initial
state could leave the JSON summary unknown even when a later dialogue observation
provided the HIDDEN declaration. Raw entity/conversation evidence stays unchanged
and current options remain distinct. Validation: 12 targeted tests in
test_npc_bundle and test_npc_initial_state passed; no full-suite run.

## Review count for initially hidden direct shops (2026-10-28)

Commented direct shops with initially hidden, cloaked or ambiguous visibility now
contribute to review_only_count and carry review_only in their JSON entry. This
corrects the existing GUI summary without changing shop code. Supported hidden
script/callshop forms remain active candidates. Validation: 12 targeted tests in
test_npc_bundle and test_shop_export passed; no full-suite run.

## Targeted test execution policy (2026-10-28)

Normal edits now run affected methods/modules or explicit feature groups via
python -m tools.run_tests. Groups cover existing modules without executing them;
--list and --dry-run expose scope, and overlapping selections run each case once.
No target implicitly runs the whole suite. Existing unit/integration layout and
unittest discovery remain available for justified broad changes and releases.
Updated project rules and test instructions. Validation for this change: selection
mechanism only, 3 passing tests; shop dry-run lists 14 cases without running them.
No full-suite run was performed.

## Consistent review-only bundle projections (2026-10-28)

NPC entries in JSON now carry the same final commented code as the aggregate
projection when placement names, initial states or shop bindings conflict. Previously
review_only was true while the entry code retained its active pre-review form.
Regression coverage includes ambiguous merchandise binding, duplicate placement
names, JSON round-trip, unresolved-shop evidence and unchanged inputs. All 402
tests pass.

## Merchandise binding across merged menu responses (2026-10-28)

Validated distinct products/prices on separate menu responses: each callshop keeps
its own hidden shop target and the merged response remains a switch. Conflicting
products on the same response retain both candidates in indented unconditional
blocks, without inferred conditions. Added regression coverage for bindings and
unchanged source observations. All 401 tests pass.

## Close acknowledgement before shop continuation (2026-10-28)

Track closed dialogue windows per rendering path. An acknowledged close followed
by an effect and shop transition emits one close2 at the observed boundary, rather
than waiting again before callshop. A subsequent mes reopens the window and requires
a new close2. Regression coverage includes individual exports and both bundle merge
modes, preserving observations and command order. All 400 tests pass.

## Complete placed NPC/shop export and default metadata suppression (2026-10-28)

The full placed-code menu includes placement-only NPCs, checkbox-controlled dialogue
merging and observed direct shops/callshop targets, separated by blank lines. Shop
bindings enter copied path boundaries; identical observed outcomes can share menu
responses. Unresolved associations retain raw evidence, and merchandise/form conflicts
are commented instead of generating duplicate active declarations. Bulk shop IDs are
explicitly unverified client-ID candidates; individual confirmed exports remain strict.
Group <=0 and blank titles no longer project commands; empty initialization is omitted,
including metadata-only placement saves. Observed fields remain unchanged. All 399
tests pass. Real exports: 141 placements/zero OnInit for the added log, plus all 5
shop observations in the earlier 175743 log in both modes with no shop import errors.

## Resource-aware timeout prefix matching (2026-10-28)

Timeout partial observations may now include resource evidence strictly before
the unanswered request. Continuation matching hashes semantic anchors and ordered
kind/fields, comparing values and multiplicity while ignoring capture-specific
packet numbering. Prefix token/resource hashes are streamed rather than expanding
all prefix strings. Matching quest commands are emitted once from normal evidence;
partial contributions remain non-complete trials. Post-request, parallel and external
observations stay review-only. All 396 tests pass, covering resource state/value/
count/order differences, deterministic input order, unchanged evidence and GUI output.

## Timeout-prefix normalization against observed continuations (2026-10-28)

Unanswered-close paths can now join the same NPC's normal continuation when their
observed body/prompt prefix matches after removing timeout termination artifacts.
They add partial contributions/evidence only, not trie branches, invented replies
or complete repeat trials. Rolling length-delimited hashes bound prefix indexing;
accepted node-capacity paths alone supply continuation evidence. Unmatched prefixes,
other quality issues or added resource/parallel/external observations remain review
exclusions. GUI and bulk export use the unified path while standalone output retains
the original timeout suspicion. All 393 tests pass, including all prompt types,
close waits, executable equality, deterministic order, original evidence and GUI modes.

## Late input evidence after unanswered server close (2026-10-28)

Matching next/menu/number/text replies after suspected unanswered closure now remain
separate late_replies instead of creating orphan-reply errors. Capture/flow/actor
and original unanswered prompt are checked; reply links, active dialogue and close2
remain unchanged, with server acceptance unverified. New conversation/operation,
map and capture boundaries clear the bounded markers. JSON, timeline navigation
and a code warning preserve evidence with global/per-conversation limits and drop
counts. All 389 tests pass, including ACK ordering, non-time-based matching, scope
resets and GUI navigation. A separate late-replies replay preserves the raw source.

## Structural unanswered-close timeout suspicion (2026-10-28)

Unanswered next/menu/number/text followed by server close, or repeated close while
awaiting dismissal, now retains timeout suspicion and original prompt evidence.
No elapsed-time threshold is used. Projection comments the unanswered wait and
keeps a terminal close; late dismissal cannot arm after-close/shop continuation.
Unrelated warp/presentation/quest packets therefore cannot convert it to close2.
Code/timeline/JSON expose the suspicion without asserting cause. Normal new-dialogue
close2 behavior remains covered. All 386 tests pass. The separate timeout-close
replay retains source logs and unverified capture completeness.

## Quest command loop and close-reply boundaries (2026-10-28)

Quest set/delete and deferred-review nodes are now reviewed straight-line nodes
for menu folding/sharing, retaining side effects before observed loop returns.
Same-flow quest additions/deletions within the original two-second close ACK window
can produce close2/quest/end candidates. Before-ACK, other-flow and expired events
remain outside; state/count-only updates do not trigger close2. Continuation proof
stays on resource evidence rather than fabricating a map/shop termination. All
383 tests pass, including source ordering, original-window expiry and unchanged
observations. session-analysis-quest-continuation-review.json is a separate replay.

## QuestID command projection and timeline state reference (2026-10-28)

At the user's request, same-flow dialogue quest additions/deletions now project
setquest/delquest using observed QuestIDs at their path anchors. Waiting-input
notifications defer to a matching observed reply with a review note; unresolved
prompts retain evidence without an executable command. Merged branch differences
stay explicit. Timeline reference values expose quest ID/raw state, deletion and
received counts for manual checkquest reasoning, without generating conditions or
equating packet state with checkquest results. All 381 tests pass; additional-log
replay keeps 90 conversations/34 groups with capture completeness still unverified.

## Versioned quest objective count evidence (2026-10-28)

02B5/09FA/0AFE/08FE variable notifications validate total length, entry width and
explicit counts where present, retaining zero to three objectives per the checked
Auriga sender. Objective namespaces stay version-specific; received required/current
counts are not clamped or converted into completion conditions. Evidence appears
in global quest observations, same-flow dialogue comments/timelines and external
quest_counter display templates. All 379 tests pass, including invalid layouts,
cross-flow isolation and full unsigned counts. Source scripts remain reference-only.
Additional log validation retains 5 updates (08FE: 2, 0AFE: 3), 6 objective entries,
90 conversations/34 groups and zero dialogue issues in session-analysis-quest-counts-review.json.

## Quest notification evidence (2026-10-28)

Versioned fixed-size quest additions, deletion and 02B7 state responses now retain
global bounded evidence and same-flow active-dialogue resource comments. Addition
headers are parsed; full objective payload bytes remain explicitly unparsed.
No setquest/delquest, completion conditions, rewards or timer causation are inferred.
Malformed/capacity-limited notifications remain visible issues without changing reply
links or fabricating conversations. All 376 tests pass. The additional log retains
8 additions and 6 deletions, 90 conversations/34 groups and zero dialogue issues
in session-analysis-quests-review.json. Count/list layouts remain future work.

## Unassigned BGM in presentation-window comparison (2026-10-28)

Manually selected NPC observation windows now retain same-capture/flow BGM as
unassigned related events. Known map/generation mismatches stay excluded. Name,
mode and presence differences form distinct variants, with GUI packet navigation
and unchanged source observations. The strict announcement helper remains separate
so BGM cannot inherit announcement timer adoption. Local musiceffect requires a
player; no NPC timer command or implicit event omission is introduced. All 373
tests pass, covering comparison boundaries, GUI evidence and unsupported adoption.

## Valued effect observations without lossy generation (2026-10-28)

0284 is strictly decoded as 14 bytes with actor, effect ID and additional value.
Distinct effect_value events participate in dialogue, input-wait/external recipient
review, repeated conflicts, window comparison and observation filtering. External
templates retain both numbers as comments. The local Auriga sender exists but no
misceffect_value script registration was found, so no executable replacement is
invented; manual timer adoption rejects such trials rather than dropping events.
All 370 tests pass, including full-width values, layout rejection, both-field
conflicts, read-only GUI evidence and explicit unsupported generation.
Older log 20261027-193248-fcdc039c contains one outside-dialogue valued effect
(657, 90406), retained by session-analysis-valued-effect-review.json; replay still
has 6 conversations, 2 groups and zero dialogue issues.

## Explicit effect removal observations (2026-10-28)

0B0D is strictly decoded as a 10-byte actor/effect removal notification, distinct
from effect additions. Dialogue, input-wait comparison, unknown-target observation,
external NPC candidates and ignorepacket classification share the existing target
and lifecycle rules. External removals remain commented; own-NPC removals use
external delmisceffect templates. Manual timer adoption supports removals with the
existing confirmation/times/evidence checks and command-ID validation. All 367 tests
pass; coverage is synthetic packets and GUI, not native runtime confirmation.

## Shop initial-state preservation (2026-10-28)

Shop snapshots now retain server/first-observed visibility evidence and expose it
in the confirmation dialog. Callshop uses the NPC script visibility headers;
direct shop declarations with hidden/cloaked initial state remain fully commented
review candidates because the local Auriga shop parser has no state modifier.
No dialogue or initialization helper is invented to change the observed shop form.
The warning is external and legacy profiles inherit its default. All 364 tests pass,
including current-visible/initial-hidden shop observation and both candidate modes.

## First-observed NPC placement visibility (2026-10-28)

NPC initial options/evidence are fixed per capture/server/ActorID across updates,
visibility intervals and reconnects; unknown server identity stays connection-local.
Current options remain separate. Single, merged, metadata-only and bulk placement
exports use external HIDDEN/CLOAKED header templates. Auriga type 6 uses
script[(HIDDEN/CLOAKED)]; type 12 walking NPCs use script2[(HIDDEN/CLOAKED)].
Reobserved 0x9FD for type 12 emits npcwalkto. Conflicting initial observations are not silently selected;
bulk candidates are commented, combined unsupported flags retain exclusion evidence.
Real replay also exposed interrupted external candidates incorrectly bounded by
their last body step; validation now uses an observed termination when available.
All 362 tests pass. The added log has 90 hidden visibility intervals, producing
38 hidden declarations among 141 placements, with 12 invalid placement records
retained. CLOAKED is synthetic coverage; native Auriga execution is unverified.

## Server ActorID observation-history GUI (2026-10-28)

NPC and MOB detail workspaces expose same-server/same-ActorID observations within
one capture. The read-only history retains hidden visibility intervals, map/state,
and navigation to the first retained/last evidence packets. Unknown server identity
shows only the selected interval; different servers and captures stay separate.
The existing 32-reference evidence bound is explicit and interval statistics are
unchanged. All 357 tests pass, including both entity kinds, client-port changes,
filters, source navigation, empty-state cleanup and unchanged world observations.

## Server ActorID namespaces versus visibility intervals (2026-10-28)

The user clarified sequential script-load ActorIDs per server IP/port, stable over
visibility loss, with maintenance-sensitive numbering and runtime random IDs for
dynamic NPCs/event MOBs/instances. Entity appearance is now described as a visibility
interval, not server ID reassignment. Entities/MOB visibility records expose parsed
server endpoints. World reports group observed IDs per capture/server without
claiming confirmed entity identity, configured spawn counts or allocation kind on
ordinary maps. Instance allocation is explicit. Client ports/SYN values do not form
server identity; capture boundaries remain separate. All 355 tests pass, covering
server IP/port separation, reconnects, visibility loss and 1001..1200 sequences.
Existing entity keys and conservative dialogue/combat interval boundaries remain.

## External presentation appearance boundaries (2026-10-28)

External candidate association now requires the contextual conversation NPC to
remain the observed current appearance. Removed/reused actor IDs no longer attach
other-NPC effects to old dialogues; notifications remain outside-dialogue evidence.
Recipient reappearance creates separate immutable target evidence. Source-context
and recipient entity keys are recorded and checked during single/merged generation;
the review table shows recipient appearance. Legacy candidates without the added
keys retain prior validation. All 352 tests pass, including source removal/reuse,
recipient reappearance and mismatched-key rejection. No caller is inferred.

## External presentation evidence navigation (2026-10-28)

The dialogue workspace now has a read-only external-presentation review tab with
observed recipient, packet identity, contextual conversation and JSON evidence.
Separate actions navigate to the presentation packet and its preceding dialogue
step. The merge toggle includes all group contributions; conflict captions explicitly
cover all presentations, not just external ones. Selection/detail/navigation state
is cleared on context changes. All 350 tests pass, including source jumps, empty
conversations, merged review and unchanged observations. No caller is confirmed.

## External NPC presentation candidates (2026-10-28)

Same-flow, same-map-generation presentations targeting another known NPC during
dialogue now remain external candidates, without interrupting the active NPC or
input reply links. Observed recipient and contextual conversation actor stay
separate; cause remains unconfirmed. Presence, content and target differences
participate in repeated presentation review. Default command candidates are
commented, using named NPC references (and getmdnpcname in instances); unittalk
uses getnpcid rather than fixed live IDs. Sound remains evidence-only because
soundeffect has no NPC target argument. Added strict 008D unit-talk decoding.
All 349 tests pass. Additional log: 6 external effect candidates, 65 standalone
unit-talk observations, 90 conversations/34 groups and zero dialogue issues.
Unknown/MOB/other-flow targets are not promoted to external NPC calls.

## Instance references and map-scoped announcement trials (2026-10-28)

Observed maps containing @ enable instance handling. Dialogue/merged warp candidates
and Auriga display use getmdmapname for instance destinations from instance maps;
entry from normal or unknown maps is commented with the possible mdenter origin.
Observed source maps remain in warp evidence. Instance callshop name arguments use
getmdnpcname; declarations stay literal. All wording/references are external templates.
Announcement evidence includes observed map/generation and instance mode; timer windows
include possibly other-user announcements but reject known map/generation mismatches.
All 345 tests pass. Additional-log replay keeps 90 conversations and 34 groups with
zero dialogue issues; session-analysis-instance-review.json retains capture caveats.
No base-map remapping, mdenter calls, conditions or timing values are inferred.

## Announcement dialogue/timer association and contradiction review (2026-10-28)

At the user's request, same-flow active dialogue announcements now enter dialogue
paths; input-wait announcements remain parallel and participate in presentation
conflict review. Presence, text and style changes retain existing review blocks
and evidence. Actor-less announcements in manually selected timer windows join
trial comparisons without changing observed actor/target metadata; other flows
are excluded. Manual timer adoption supports announcement templates, explicit
times and confirmation, with saved-evidence roundtrips. All 341 tests pass.
Additional log: 31 announcements, one dialogue step and one parallel observation;
90 conversations, 34 groups and zero dialogue issues. The separate associated-review
report retains incomplete-capture quality and never imports reference-script logic.

## Unassigned announcement observations (2026-10-28)

Broadcast 009A and styled announce 01C3/040C now retain decoded text/style fields
and packet evidence as bounded, unassigned presentation observations. Length,
terminator and CP932 checks reject invalid layouts. No NPC association, dialogue
steps, close2 continuation or timer causation is inferred. Existing display profiles
remain responsible for text formatting. All 338 tests pass. Additional-log replay
still has 11,729 packets, 90 conversations and 34 groups, with 31 styled announcements.
The separate session-analysis-announcement-review.json preserves review-required
capture quality; no original event-script logic or timing values were used.

## Configured editor/project destination audit (2026-10-28)

Timer, MOB skill and MOB placement editors already used atomic replacement with
32MiB/8MiB limits and confirmation/evidence checks. They now reject all config
destinations, including unrelated settings. Single, multiple and relocated project
saves share that destination rule while retaining fsync and reference validation.
The reusable destination validator is separate from encoding, capacity and writing.
All 335 tests pass, including existing manual confirmation/load roundtrips and
configuration preservation in all three editor and project paths.
Next feature work: P2 notification coverage, beginning with announce packet/layout
evidence and target scope; reference event scripts must not supply missing logic.

## Protected visible and diagnostic log export (2026-10-28)

Visible packet text and standalone diagnostics freeze text before destination
selection and use bounded atomic saving with source/definition/config protection.
Session JSONL export copies bounded bytes under the existing session lock, protects
its length snapshot and additional source references, and preserves same-source
no-op behavior. Failed output replacement preserves previous files and does not
poison ongoing recording. Shared atomic output now supports bytes without encoding
conversion. All 334 tests pass. Remaining save audit: configured editors/projects.

## Documentation navigation and classification (2026-10-28)

All 32 feature documents are grouped under docs/guide, capture, npc, mob,
observations and development. docs/README.md provides a task-oriented index;
individual documents link back to it and the project README. Root README,
development notes and cross-document relative links use the new locations.
All documents are indexed and 194 local Markdown links resolve. Specifications
and historical validation records are retained; runtime code is unchanged.

## Stable comparison report export (2026-10-28)

Repeated dialogue timing and presentation-anchor comparison JSON now share atomic
saving while retaining their stricter 32MiB UTF-8 limit. Report text and protected
input paths are fixed before destination selection, so modal-time invalidation
does not change the reviewed output. Source logs, selected definitions and config
are protected; nonfinite JSON values are rejected. All 331 tests pass, including
live invalidation, replacement failure, UTF-8 limits and existing evidence navigation.
Comparison consistency still does not confirm timer values or event causation.
Next: visible display/diagnostic exports and existing configured-editor save contracts.

## Stable player and combat observation export (2026-10-28)

Player observations now include capture-session source references and share bounded
atomic saving. Player and combat exports freeze data/source references before the
destination dialog and protect selected packet definitions as well as source logs
and configuration. Tests cover live updates, all protected destination categories
and failed replacement. All 329 tests pass; observation semantics are unchanged.

Remaining export work: visible packet text and diagnostic logs; repeated timing and
event-trial comparison reports; review configured editors/project saves against
their existing size limits and source-protection contracts. Preserve distinct
limits and live diagnostic-session export semantics when unifying these paths.

## Protected MOB placement and skill candidate exports (2026-10-28)

Placement observation JSON and placement/skill review candidates now use bounded
atomic saving. Both protect source logs, selected length definitions and configuration,
and preserve existing files on replacement failure. Placement and skill snapshots,
source references and candidate text are fixed before destination selection. Tests
exercise observation JSON plus candidate JSON/TXT during additional capture events,
and input protection/failure paths for both panels. All 328 tests pass. No active
placement/skill settings are inferred or enabled by this change.

## Stable, protected shop exports (2026-10-28)

Shop observation JSON and confirmed Auriga candidates share bounded atomic saving,
protecting source logs, selected packet definitions and all configuration. Shop
confirmation edits a copied observation/conversation; live capture updates cannot
change the product prices or dialogue under review. Export snapshots and source
references are fixed before modal dialogs. All 326 tests pass, including failed
replacement preservation and source/definition/configuration overwrite rejection.
Direct shop versus callshop semantics and explicit item-ID confirmation remain.

## Protected dialogue exports (2026-10-28)

Conversation text/JSON, merged JSON and placed NPC exports now share bounded
atomic saving. Source logs, selected definitions and configuration are protected;
failed replacement preserves previous output. Rendered content, merge choice and
source references are fixed before opening the destination dialog. Regression
coverage exercises all four paths, modal-time observation changes and every
protected destination category. All 324 tests pass. Capture and rendering semantics
are unchanged; shop identity confirmation remains in the dedicated shop exporter.

## Protected NPC/MOB list export (2026-10-28)

Entity-list JSON exports now share bounded atomic observation saving, protecting
source logs, selected packet definitions and configuration. Snapshots and source
references are frozen before the destination dialog, preserving the chosen list
when capture updates during saving. Regression coverage checks both NPC and MOB,
source overwrite rejection and failed replacement preserving the previous file.

## Bulk NPC export and initialization termination (2026-10-28)

The Export menu saves all observed NPC placements as TXT or evidence-bearing JSON.
The dialogue merge checkbox controls merged versus individual dialogue bodies;
list visibility filters do not limit export. Initialization-only bodies end before
OnInit; dialogue bodies retain their existing close/end termination.
321 tests pass. The additional log exports 141 placements in both modes, with 12
excluded observation records preserved in JSON. See docs/npc/npc-bundle-export.md.

## NPC placement/initialization-only export (2026-10-28)

The NPC list can save a selected observed placement and 0x0ADF initialization as
TXT or evidence-bearing JSON, even without dialogue. Output explicitly excludes
dialogue rather than assuming none exists. Missing placement/metadata is rejected;
source logs, the selected definitions and configuration are protected. The entity
snapshot is copied before the destination dialog and output replacement is atomic.
317 tests pass. No map remapping, hidden conditions or original script inference.

## Observed entity group/title projection (2026-10-28)

At the user's request, 0x0ADF group/title observations now produce NPC OnInit blocks
and MOB setunitgroup/setunittitle log commands. Per-field evidence distinguishes zero
and empty from unknown; pending names resolve only at known appearances. NPC body,
merged and placement output share one OnInit projection. Conflicts remain review
blocks; valid partial metadata can combine. The MOB detail view includes values,
commands and field-specific evidence. Templates are external and Auriga-only.
315 tests pass. The new log contains 46 NPC and 107 MOB metadata records, all zero
group/empty title; non-default values are covered synthetically. No event script
settings or timing logic were used. See docs/observations/entity-group-title.md.

## Protected MOB observation export (2026-10-28)

Skill/performance observation JSON exports now share bounded atomic saving with
source-log and configuration protection. Replacement failures preserve previous
reports; temporary files are cleaned and nonfinite values rejected. 311 tests pass,
including both GUI paths. This changes export behavior only, not capture or analysis.

## MOB attack interval navigation (2026-10-28)

The performance view now exposes HP/SP-separated interval samples with individual,
counterparty, action and both packet endpoints. Summary samples retain known opponent
appearance/class metadata. 309 tests pass; the new log still has 453 attack packets,
1,450 observations, 10 classes and no combat issues. Original observations are equal;
no ATK, DEF or configured attack delay is inferred.

## Explicit cast tracking termination evidence (2026-10-28)

Pending casts now retain why tracking ended and the packet observed at that point.
Decoder resets and capacity exhaustion no longer leave falsely pending casts; an
unstored cancel at capacity is not promoted to a recorded cancellation. Lifecycle,
superseding cast and capture-generation transitions remain distinct. The GUI exposes
a separate tracking-evidence action. 308 tests pass. Both tracking ends in the new
log correspond to death notifications, without inferring cast cancellation causes.

## MOB cast candidate review (2026-10-28)

A read-only GUI/report view exposes existing cast links, declared cast duration,
observed elapsed time, cancellation/pending states and packet endpoints. It creates
no new associations, checks appearance/class/skill/capture scope and keeps confirmed
status false. 307 tests pass, covering mixed individuals, pending casts, navigation
and unchanged source observations. No CASTTIME or cancellation settings are inferred.

## MOB interval evidence navigation (2026-10-28)

The skill panel now lists every interval series with appearance identity, optional
effect target/result, duration and both packet endpoints. Users can navigate to
either endpoint; changing the selected skill clears old interval selection. Evidence
and inferred-setting policy are unchanged. 305 tests pass, including separation of
interleaved individuals, endpoint selection and unchanged observation snapshots.

## MOB effect notification intervals (2026-10-28)

Arrival intervals for tick-less effect notifications are now a separate series,
scoped by individual appearance, class/skill, target ID and result. Samples retain
both packet endpoints; unknown targets and unreliable timestamps do not contribute.
The GUI distinguishes them from server ticks and configured cooldowns. The new log
yields 15 samples across 2 class/skill groups; all DELAY candidates remain unknown.
304 tests pass. Existing manual JSON evidence comparisons stay strict after replay.

## Excluded dialogue review navigation (2026-10-28)

The unified report and dialogue GUI now expose excluded observations with NPC/map,
status/reason, capture identity and packet range. The GUI selects the original
conversation and first evidence packet without modifying its start-unobserved flag
or promoting it to merged code. 302 tests pass. In the latest observation log the
remaining exclusions are retained scope/cancellation limits, not repaired from the
reference event script.

## Additional Toy Factory observation context (2026-10-28)

Log 20261028-012526-0abe69d9 observes the map/NPC/MOB set used as reference for
C:/project/Auriga/script/npc/memorial/npc_memorial_horroroftoy.sc. The user explicitly
requires reference-only use: do not infer processing, fill unseen conditions, adopt
timer values, or treat implementation differences as evidence of analyzer bugs.
session-analysis.json and observation-context.json preserve independent observation
results and this restriction. The source log and reference script remain unchanged.
The initial report rejected 5 menus with multiple trailing empty option slots.
Packet/reply evidence now supports stripping trailing empty slots without changing
earlier choice numbers. The separate session-analysis-menu-review.json retains 93
conversations with 1 dialogue issue, versus the original report's 98 and 11. Internal
empty slots remain rejected, original text is preserved, and 297 tests pass.
The inventory review identified same-index/item/type-10 entries in normal quantity
lists and equipment lists without quantities. Complementary entries within one
snapshot now retain only the received normal quantity; unknown quantities and
conflicting duplicates remain rejected. session-analysis-inventory-review.json
reports 0 player issues (previously 34), 1 dialogue issue and no generation errors.
299 tests pass. No quantities or logic were taken from the reference script.
The subsequent session-analysis-cancel-review.json associates 3 immediate 00B6
notifications with actually matched menu cancellations, rather than creating stale
close-button waits. Later observed dialogue remains a separate start-unobserved path.
All semantic issue counts and generation errors are now zero; capture/timeline scope
limitations remain. 301 tests pass. No event conditions or timers were inferred.

## Session quality summary (2026-10-28)

The unified report now aggregates transport findings, semantic issues, bounded-store
losses, nested conversation issues, timing flags, presentation conflicts and generation
exclusions/errors. Findings retain section/code/count without replacing original evidence.
No-reported-issues remains distinct from verified capture completeness. 296 tests pass;
the summary does not automatically filter or alter reconstruction results.

## One-pass session verification (2026-10-28)

tools.analyze_session updates semantic stores in GUI order from one replay and saves
transport diagnostics, all observation snapshots, spawn candidates and merged NPC
code together. Source/definition/profile hashes and bounded measurement fields are
retained. Input changes and protected destinations are rejected; output replacement
is atomic. 294 tests pass, including comparison with existing analyzers. Transport
completeness remains unverified. See docs/capture/session-analysis.md.

## NPC timer candidate text export (2026-10-28)

Confirmed timer candidates can export their complete comparison/manual-setting
envelope as an escaped JSON comment followed by regenerated Auriga code. The same
envelope validation is shared with resume. No starts or trigger logic are added.
Text output retains source protection, size bounds, stale-comparison checks after
the destination dialog and atomic replacement. 293 tests pass, including output
integrity and preservation of existing files on replacement failure or stale state.

## NPC timer manual-setting resume (2026-10-28)

Saved timer candidates can restore explicit manual times only against the same NPC,
adopted trial, complete comparison evidence and regenerated code. Flags and the full
saved envelope are checked; duplicate keys, nonfinite values and oversized files are
rejected. Loading and time edits clear confirmation and preview. Stale comparison
guards remain active. 292 tests pass; no timer origins or start conditions are inferred.

## Menu projection across additional presentations (2026-10-28)

Overhead messages, viewpoints, class changes and targeted progress bars no longer
block repeated-menu folding or shared identical continuations. Presentation values
must still match before continuations are shared; input and closing barriers remain.
The render projection preserves the observation graph. 291 tests pass. The latest
saved dialogue log still yields 6 conversations, 2 merged groups and no errors.

## MOB skill editing consistency (2026-10-28)

Skill and spawn editors now pin independent evidence snapshots, clear confirmation
and preview on field changes, show the reviewed row with evidence, and replace saved
files only after a complete temporary write. GUI regression coverage checks text and
choice changes, snapshot independence and preservation of existing output on failure.
276 tests pass; no new skill levels, AI conditions or configured delays are inferred.

## Manual MOB placement resume and text export (2026-10-28)

Placement settings can be reopened against the same observation/source envelope.
Saved rows, confirmation markers, templates and evidence must match; duplicate keys,
nonfinite JSON values and oversized input are rejected. Reopening clears confirmation.
Confirmed text output includes all evidence as escaped comments and one placement row.
No spawn settings are inferred and source observations are not changed. Full regression
suite: 276 tests pass; native Auriga loading/execution remains unverified.
See docs/mob/mob-spawn-observations.md. ignorepacket display controls and persistence
are described separately in docs/guide/ignorepacket.md.

## Dialogue review formatting (2026-10-27)

User-directed replacement of conflict stops and input suffix suppression:
emit each conflicting suffix (including at conversation start) in indented review
blocks; continue after input replies with escaped numeric/text comments. Do not
infer causes, original variables or hidden conditions. Multiple choices use Auriga
menu result @menu with switch/case/break. Single choices and fully observed,
identical complete suffixes use an unlabelled menu and a shared continuation.
Both single-path and merged output use the same renderer. Structural templates
remain external; historical profiles inherit new defaults. Merged IR is schema v2.
209 tests pass. See docs/npc/dialogue-merging.md for the current generation contract;
the initial conflict-stop behavior described below has been superseded.

## Observed dialogue branch merging (2026-10-27)

Added conservative menu-path tries with placement or capture-local entity identity,
source evidence, original conversations, conflict stops and bounded expansion.
Input suffixes and server conditions remain ungenerated. Existing single-path
output stays the default. Optional external templates, GUI preview/export and
tools.merge_dialogues share the same representation. Generation limits preserve
IR JSON with explicit errors rather than returning partial code.
198 tests pass, including two synthetic bidirectional raw logs, GUI exports and
legacy profile compatibility. Existing logs produce one single-conversation local
candidate and one identity exclusion; they do not prove multi-path restoration.
See docs/npc/dialogue-merging.md for supported scope and limits.

## MOB performance observations (2026-10-27)

Added signed normal-attack-family decoding, separate outgoing/incoming MOB roles,
HP/SP isolation, two-hand notification sums, target/action scoped individual tick
intervals, and direct speed/HP samples. The MOB performance tab supports source
navigation, evidence JSON and export. Added the offline analyze_combat command.
WorldStore now exposes shared current-entity lookup without changing identity rules.
Corrected signed attack/HP fields in the Auriga profile and HP decoder.
183 tests pass; the additional log yields 449 role/state observations across five
classes, with no performance decoder errors. No base ATK/DEF or configured delay
is inferred. See docs/mob/mob-performance.md for limits and validation.

## MOB skills (2026-10-27)

Added bounds-checked skill observations and per-appearance intervals before class
aggregation, cast/cancel candidate links, raw unknown levels and packet evidence.
The MOB detail tabs expose summaries, JSON export, source navigation and an external
name dictionary. Corrected signed 01DE fields in the Auriga display profile.
Validated 168 tests and two raw logs; the additional log has 23 MOB damage
notifications across four class/skill pairs with no decoder errors.
Configured cooldowns, AI conditions and mob_skill_db generation remain unimplemented.
See docs/mob/mob-skills.md for semantics, limits and validation.

## Basic data and observation coverage (2026-10-27)

Expanded the Auriga profile to 93 IDs. PlayerStore tracks map, observed position,
walking destination, inventory snapshots/deltas and Zeny independently of text.
Added the compact GUI summary, inventory window, JSON export and offline replay tool.
Inventory completion requires valid start/list/end framing; partial observations,
unidentified balances and different flows remain separate. Player and actor
decoder names are fixed profile capabilities, never executable expressions.
152 tests pass. Two raw logs replay without player-state errors; the additional
log contains a complete 84-slot, 706-item snapshot. See docs/observations/player-observations.md.

## Dialogue timing (2026-10-27)

Added prompt/reply spans, input-free observation gaps, map-transition evidence,
conservative quality flags and placement/path scoped repeat statistics.
GUI selection jumps to individual timing evidence. Snapshot schema v2 includes
timelines, summaries and source sessions. External optional observed_gap template
adds comments without changing generated commands. See docs/npc/dialogue-timing.md.
Validated synthetic timing/GUI cases and replayed two existing capture logs;
one 101.522ms input-free gap was excluded due to an assumed boundary; no server
timer was established by those logs.

## Dialogue restoration (2026-10-27)

Added capture-independent dialogue observations, paired TCP flow identity, prompt/reply
links, bounded evidence storage, external Auriga generation templates and the
会話・コード workspace. SQLite columns and strict framing remain unchanged.
Validated two raw capture logs and 128 regression tests; see
docs/npc/dialogue-restoration.md for supported layouts and remaining scope.
Generated bodies still require review in an NPC script and execution validation in Auriga.

## Investigation (2026-10-26)

The supplied workspace has no Git metadata. Preserve PacketLength.txt and the
existing packets.sqlite3. Baseline: four unittest cases pass on Python 3.13.
README contained v0.2 claims inconsistent with v0.3 code. hook/ and ipc/ were
empty packages. The GUI already used Qt signals for capture events and SQLite
storage. No native build project or game-specific plaintext entry point exists.

## Development rules

Project-wide rules are in `.cursor/rules/project.mdc`. Every behavior change
requires a regression test. Packet framing must follow the supplied definitions,
stop on unknown IDs, and never search payload bytes for a plausible boundary.
Keep passive receive capture operational independently of optional IPC.

## Work order

Current priority: receive presentation and external display profiles precede any
native send/encryption work. See docs/capture/receive-display.md for the implemented
profile contract, MARiA comparison, validation and remaining coverage.

1. Process tracking: isolate connections by four-tuple, synchronize discovery,
   retire disappeared sockets, preserve state on duplicate SYN, bound SYN cache.
2. TCP robustness: reordered delivery and retransmissions, sequence rollover,
   ambiguous buffered overlaps, bounded pending bytes and missing-byte timeout.
3. Shared immutable PacketEvent without capture/Qt dependencies; preserve database schema.
4. Design the authorized x86 plaintext producer and versioned binary contract.
5. Add opt-in Qt local server, decode/validate SEND records, deliver through the
   existing GUI signal/storage path; test native integration separately.

## Validation still required on the target machine

- Npcap login -> server transfer -> reconnect, multiple concurrent server sockets.
- Child process selection, permission errors, rapid socket churn and PID restart.
- Real capture drops and delayed retransmission; validate the 30 second gap policy.
- An x86 native producer writing fragmented records to the displayed pipe name.
- GUI shutdown while capturing and while a producer is connected.

Synthetic tests do not establish real game or Npcap compatibility. Early payload
after a captured SYN is now cached until process discovery, subject to explicit
byte/count/expiry limits. Strict mode never treats a missing prefix as a packet
boundary; the optional existing-connection mode makes this assumption explicit.
Delivered-byte overlap conflicts cannot be
checked after payload history is discarded. FIN currently closes immediately;
out-of-order bytes pending at FIN are discarded, not recovered. IPv4 fragments
are not assembled. GUI table/history and per-packet SQLite commits still need
throughput work. psutil polling can miss short connections and does not track
process identity across PID reuse. Restarted processes must be reselected.

## Receive display validation (2026-10-26)

37 unittest cases pass, including the original 20 and 17 display/GUI cases.
Verified Japanese cp932 dialogue, quoted string escaping, typed dialogue offset,
NUL/no-NUL strings, malformed input isolation, cutin/map context isolation,
64-bit experience, profile validation, hot reload with last-good retention,
history replay across capture sessions, visible text export and raw DB retention.
An offscreen GUI preview with an explicitly loaded Windows Japanese font was
visually inspected at 1050x680. This verifies layout and synthetic rendering,
not live Npcap/game data or complete MARiA stateful behavior.

## Capture failure investigation

The user reproduced zero packets by starting capture after the game had already
connected, with Interface blank. The strict SYN gate explains that operation:
discovering PID endpoints does not establish the TCP/game stream boundary.
MARiA instead begins with received payload without requiring SYN. This project
now offers an explicit opt-in first-payload boundary assumption, while retaining
strict default behavior and stopping on unknown IDs in both modes.

Also fixed early payload loss between SYN capture and process polling, blank
interface using only Scapy's default adapter, and invisible asynchronous sniffer
startup failures. GUI now locks capture settings and disables manual IP/port in
process mode. Persistent diagnostics expose the stage at which traffic stops.

All 49 tests pass after these fixes. Twelve additional cases cover opt-in
midstream delivery and failure isolation, early data replay/overflow/expiry,
interface selection, asynchronous sniffer failure/cancellation and GUI controls.
Live capture against the user's game still needs a target-machine retest.

## False PacketID 0000: Ethernet padding regression

Scapy represents Ethernet bytes beyond the IP length as a Padding layer below
TCP, or below Raw for data-bearing frames. bytes(tcp.payload) included this layer.
An ACK with six padding bytes could create three false ID 0000 packets when the
definition map contains 0000=2. Padding on SYN/ACK also advanced TCP next_seq,
causing legitimate subsequent payload to be discarded or truncated. This was
introduced when the Raw-only payload check was replaced with an unqualified
bytes(tcp.payload) call; the previous tests constructed IP/TCP/Raw directly and
did not exercise wire-level Ethernet padding.

The receiver now excludes only Scapy's identified Padding bytes before process
caching and TCP reassembly. Application zeros and legitimate ID 0000 remain
untouched. Padding cannot trigger existing-connection attachment. Six additional
serialized/dissected Ethernet regression tests cover SYN/ACK, pure ACK, real
data, nonzero padding, early process discovery, attachment and IPv6. All 55 tests
pass. The GUI reports ignored padding bytes. User-reported unknown IDs may have
the same cause, but without raw frames that attribution is unconfirmed; no
protocol preamble skipping or unknown-ID resynchronization was added.

## Client extraction and persistent diagnostics

See docs/capture/capture-analysis.md. The provided unpacked Win32 client was statically
inspected without executing it. A reproducible, narrowly scoped extractor found
1,785 registrations (1,783 unique IDs), including 0C3C=6. The generated candidate
and provenance/diff report are separate files in client/; the original length
map is unchanged. Static registration attributes are not assumed to prove direction.

Start now creates a capped JSONL diagnostic session and a normalized definition
snapshot. Raw receive recording is explicitly opt-in. It includes matched TCP
segments even after framing stops, enabling offline comparison under a new map.
Framing errors retain previous IDs, configured/applied lengths and stream offsets.
Valid packets preceding an unknown ID in the same chunk are no longer discarded.
All 81 regression tests pass. In the provided receive log, fixing the extractor's
omission of attribute -1 restores 0B12=2 and 0BBB=-1. The map stream now frames
308 packets through the recorded end without unknown IDs or buffered leftovers.
HTTP on port 3000 and a headerless account ID echo on port 6121 were confirmed
from that log and are still stopped by the game framer. Original logs are preserved.

Opt-in passive SEND capture now uses reverse owned endpoints, independent TCP and
framing state, directional logs and separate external SEND presentation. Both
directions are replayable; old receive-only logs retain their meaning. No native
hook, packet transmission or decryption is introduced. Live plaintext SEND
verification still needs a new bidirectional capture.

## Auriga restoration priority and HTTP PASS

The user clarified the primary goal: Auriga NPC code reconstruction including
timed events, plus MOB performance and skill analysis, with MARiA as the baseline.
docs/development/restoration-plan.md records the implementation order and evidence rules.
NPC/MOB state, conversation/timer IR and statistical reconstruction remain pending.

The default receive profile is config/auriga/display.json. A separate rAthena
dialogue-only seed exists at config/rathena/display.json. The previous receive
profile is retained. Initial HTTP/1 start lines and the HTTP/2 preface now PASS
both directions without game framing, including fragmented starts and deferred
peer SYN/ACK from the process-discovery cache. Defined game IDs take precedence.
There is no scanning/resynchronization and no port-only exclusion.

All 90 tests pass. Replaying the supplied bidirectional log retains SEND 69 and
RECV 463 packets, passes two HTTP connections and leaves one framing stop for the
headerless account ID echo. The new report is replay-http-pass.json alongside
the original capture. The original capture and earlier reports are preserved.

## Restoration workspace GUI

The main window now focuses on target selection, capture start/stop and formatted
observations, with a secondary packet inspector. Capture/display/recording/pipe
options live in a nonmodal settings dialog; connections, detailed counters and
diagnostic export live in a separate nonmodal diagnostics dialog. Layout building
is separated into gui/layout.py. The existing capture/storage behavior and control
references are retained.

SEND is now enabled by default for NPC interaction correlation, and the extracted
length map is selected by default when it exists. Raw recording remains opt-in.
Undefined presentation is hidden from the observation log by default, while RAW
and table data remain available. docs/guide/gui-workspace.md describes the current
surfaces and planned NPC/MOB/event/code views; those stateful engines are still
pending. Headless visual checks use synthetic data and an in-memory database.
All 98 tests pass after the GUI reorganization; live capture with the new layout
still needs target-machine verification.

## NPC/MOB observation state

The first restoration stage now has a display-independent semantic decoder and
WorldStore, with capture/connection/map/appearance scopes. The NPC/MOB views use
QAbstractTableModel, retain selection on batched updates, expose packet evidence
and export JSON. Invalid text is isolated to field issues while verified numeric
fields survive; bounds/length errors reject the semantic update, not capture.
Queued callbacks retain their original capture generation across restart.

tools/analyze_entities.py replays raw logs through the same decoder/store. The
provided bidirectional recording yields NPC 23 (21 names, two unresolved cp932
names), MOB 0 and no observed map name. No MOB or map identity is invented.
117 tests pass, including entity scope/lifecycle/limits, CLI and GUI behavior.
Synthetic NPC/MOB screenshots were visually inspected; live MOB validation and
new-GUI capture remain. Conversation/code generation, timers and skill statistics
are still pending.


## 2026-10-29: DB failure and delivery diagnostics (after frozen v0.0.4)

SQLite add failures attempt rollback and preserve the original error. GUI capture
stops, keeps received events in memory, counts DB results as unconfirmed, and blocks
restart in that window. Exception text and packet data are excluded from the error
metadata. Already published Qt notifications still apply without retrying the DB.
Diagnostics separate live publication, GUI acceptance, processing and DB confirmation.
Offline replay stops on DB failure without enabling project save or claiming completion.
Selected 18 database/capture/offline tests pass, including four new regression cases;
no full-suite, live capture or Auriga checks were run. Qt queue bounding and retention
limits remain future work. The frozen v0.0.4 archive is unchanged.


## 2026-10-29: bounded live GUI delivery

Moved Bridge/PacketDelivery into gui/packet_delivery.py, retaining imports from
main_window for compatibility. Live capture and Pipe share admission limits of
4096 pending packet notifications and 16 MiB pending RAW. First overflow latches
rejection, emits one stop request to the GUI thread, and marks capture incomplete.
Accepted packets still drain through persistence and analysis; restart is blocked.
Diagnostics count attempts, accepted, waiting, pending bytes and rejected notices.
Metadata contains counts only. This bounds packet notifications, not status signals,
Qt/Python overhead or processed history. The producer is not blocked waiting for Qt.

Selected 19 capture/database/offline failure tests pass, including count and byte
limits, concurrent producers, one overflow signal and admitted-prefix preservation.
No full suite or live integration was run. Synthetic paused-consumer measurement:
10000 x 4096-byte packets retain 16,777,216 RAW bytes instead of 40,960,000;
Python traced peak 17.9 MB vs 43.8 MB (Qt allocations excluded). Reproduce with
python -m tools.profile_packet_delivery --output logs/packet-delivery-burst-profile.json.
The frozen snapshot is unchanged. Next: processed GUI history retention measurements.


## 2026-10-29: bounded processed-history widgets

Packet table now pages matching history at 1000 rows using original packet indices
in Qt.UserRole. Source navigation opens the corresponding page; ignore selection,
RAW detail and profile replay use source indices rather than page-relative rows.
Past-page browsing stays stable during live additions. Summary cells retain only
512 characters; selected details and underlying DisplayResult keep the full text.
Observation document keeps at most 5000 blocks and approximately 262144 characters.
Rebuild walks backward to gather only the bounded preview. Save snapshots all
matching history under current filters/ignore options before the file dialog,
retaining the existing 64 MiB atomic export limit. Models, DB and code output are
not trimmed. Full-history formatting/filtering and model retention remain future work.

50 selected GUI display/capture/source-navigation/offline cases passed, including
new cross-page selection/filter/ignore/reformat coverage and full-history export
from a truncated preview. One new test fixture had DisplayResult arguments reversed;
corrected and rerun successfully. Full discovery and live integration were not run.
Synthetic widget-only 10000-record measurement: rows 10000 to 1000, document chars
5138889 to 204832; render 2685 to 3176 ms. This reduces widget retention but does not
claim a speed gain. RSS deltas depend on allocator/order; Qt allocations are absent
from Python tracemalloc. Reproduce using tools.profile_packet_history. Snapshot unchanged.


## 2026-10-29: cancellable history updates

Added GUI-thread HistoryTasks with latest-job checks, generator disposal and timer
slices (up to 1000 iterations or a target 8 ms). Histories over 2000 events stage
reformatted results and filtered table/document projections; small histories stay
synchronous. Reformat handles appended packets and capture boundaries, then swaps
renderers/results. Committed profile paths are separate from edited input paths.
Cancellation restores timestamp/emulator controls when replay is incomplete.
Cancelled/failed view projections stay stale until explicit refresh; live data is
still stored/analyzed but cannot mix with the old visible projection. Observation
and project saving wait while updates are pending/stale. Source navigation forces
an immediate projection. Window close cancels work, including offline worker shutdown.
Text is clipped by block count before entering Qt, and duplicate table redraw on
reformat completion was removed. Final widget commit and source navigation can
still exceed the slice budget; whole-history export remains synchronous.

41 distinct selected display/capture/offline tests passed across targeted runs;
four new cases cover cancellation/supersession/live append, filtering recovery,
profile-path/emulator transaction and failure/close. New fixture initially used a
helper lacking timestamp support; corrected to the timestamp-aware packet helper.
No full discovery or live/Auriga execution. Frozen v0.0.4 archive unchanged.
Synthetic 50000-event profile: reformat callback 1206 -> 0.73 ms, total 1206 ->
1007 ms, maximum Qt heartbeat gap 1206 -> 92 ms; filter callback 86 -> 0.17 ms,
total 86 -> 56 ms, heartbeat gap 86 -> 5 ms. Single-run offscreen comparison only.
Reproduce via tools.profile_history_updates; reports under logs are not packaged.
Next: full observation-text export allocation and responsiveness measurements.


## 2026-10-29: streamed observation-text save

Added save_observation_chunks: bounded UTF-8 encoding blocks, a small binary buffer,
64 MiB output limit, cancellation checks and sibling-temp atomic replacement. The
existing target survives cancellation/limit/write errors; cancellation after replace
is reported as success. Existing JSON/other export entry points are unchanged.
ObservationTextSnapshot fixes the history prefix, result-list identity, immutable
ignore settings and filter before the dialog without copying the full history.
The prefix is append-only and entries must not be rewritten in-place. GUI widgets
are never read by the save worker. Large exports (>2000 events or >262144 candidate
characters) run in a QThread; small ones stream synchronously. Live additions and
profile replacement cannot alter the saved prefix. Duplicate save requests are
ignored; errors use controlled text without arbitrary exception/payload content.
Close requests cancel export and wait for the worker, including offline exports
owned by the main workspace. Offline windows are deleted only after close accepts.

11 distinct targeted storage/display/capture/offline cases passed across selected
runs, including UTF-8 boundaries, byte limits, cancellation/commit, original-file
preservation, frozen filters/results and owner/child shutdown. No full discovery,
live capture or Auriga execution. Frozen v0.0.4 remains unchanged. Headless window
construction still fits 1050px (minimum hint 874px in the idle state).

Synthetic 50000-record Japanese export: 39088889 output bytes and identical SHA-256;
extra traced Python memory 66.4 MB buffered vs 86 KB streaming. With tracemalloc,
elapsed 69 vs 457 ms: a memory reduction, not a throughput claim. Worker/event-loop
measurement traced about 107 KB, start callback 0.17 ms, heartbeat gap at most
3.9 ms, completion 1.35 s; loop/tracing overhead included. Reproduce using
tools.profile_observation_save --mode buffered|stream|worker. Reports stay in logs.
Next: inspect output sizes and GUI occupancy of NPC bundle/MOB JSON export paths.


## 2026-10-29: shared structured-report export

save_observations now uses JSONEncoder.iterencode with 16K-character batching and
the bounded atomic UTF-8 writer. save_observation_text uses that writer as well.
Indentation, key order, Unicode, strict non-finite handling and terminal JSON newline
stay byte-identical. Late invalid values/cycles leave the old destination intact.
A bounded report-size estimate distinguishes repeated aliases from actual cycles.

Large NPC bundles, entity lists and MOB skill/performance reports share the existing
workspace export thread/slot. Reports remain detached before the dialog; writing
never reads mutable live models or Qt widgets. Standalone panels retain synchronous
fallback. Small reports still finish synchronously. NPC success messages now run
only after successful atomic replacement. Cancellation and shutdown reuse the same
worker lifetime rules as observation-text export. Existing and current source paths
are checked at dispatch. Snapshot/model generation remains on the GUI thread.

21 distinct targeted storage/NPC/MOB/observation/offline cases passed across selected
runs, including two new GUI cases and strict JSON streaming coverage. Some existing
panel-save checks were updated to await async completion before reading/errors;
no full-suite execution. Shared test wait helper avoids duplication. Initial size
estimation treated shared references as cycles; corrected to track active containers.
Frozen snapshot and live/Auriga checks remain unchanged/deferred.

Synthetic six-scenario profiling preserves every JSON/TXT output hash. NPC1000
placement-only report: build about 565-592 ms, serialization peak 14.7 -> 0.41 MB.
MOB5000 skill/performance serialization: 14.5/17.4 -> 0.213/0.212 MB. With memory
tracing, serialization is slower (0.50/0.58 -> 1.41/1.62 s), not a throughput claim.
GUI offload targets writing/serialization, not the remaining roughly 0.5 s report
construction. Huge scalar JSON strings can still allocate encoder escape copies.
Reproduce via tools.profile_structured_exports --mode buffered|stream; previous
observation-save profiler's buffered mode now explicitly preserves the old algorithm.
Next: generation/snapshot responsiveness while preserving frozen evidence semantics.


## 2026-10-29: detached MOB report generation

Added MobReportSnapshot: copy SkillStore/CombatStore once with the mutable WorldStore
excluded via deepcopy memo, preserving aliases among event/bucket/pending records.
Source metadata and skill names are fixed separately, including existing null values.
The detached export-only store computes summaries/snapshot in the save worker; live
capture never mutates it. Over 1000 observations, GUI panels freeze before the dialog
and defer report generation. Small data/standalone panels retain the old path.
The worker checks interruption before/after generation and before writing; arbitrary
mid-summary interruption is not promised. Existing close/writer lifetime rules apply.

11 distinct selected model/GUI/export/selection/offline checks passed. New regression
coverage verifies original snapshot equivalence after late cast/counter/capture changes,
actual non-GUI generation, modified live records/source metadata, and cancellation
before any output replaces the target. No full discovery or live integration. Frozen
v0.0.4 untouched. The dedicated snapshot test is registered in the mob feature group.

Synthetic 5000-observation comparison under tracemalloc: GUI freeze skill 323 ms and
performance 279 ms, versus previous snapshot+deepcopy 508/571 ms. Worker generation
40/60 ms; hashes match all original MOB reports. Copying still blocks the GUI for a
size-dependent interval. Run tools.profile_structured_exports --deferred to separate
freeze/build/write. NPC generation remains unchanged pending a contract that freezes
conversation/shop state together with all external rendering inputs.


## 2026-10-29: frozen NPC generation inputs and rendering files

NpcReportSnapshot fixes entity dictionaries, conversations, shop associations, source
paths and merge mode before the dialog. Large bundles (>100 placements, >50
conversations, >1000 total steps or >100 shop records) generate in the existing save
worker, selecting JSON or TXT afterward without rebuilding mutable live inputs.
Only required NPC entity dictionaries are prepared, avoiding unused world snapshot
history/summary copies. Small bundles keep prior behavior. Worker completion carries
only summary counts for the success message; no report/payload enters diagnostics.

render_inputs freezes dialogue/shop/entity-metadata/status-ID file bytes (2 MiB per
file), including fallback inputs. ContextVar scope is private to the worker task;
normal GUI reads remain current. Nested shop rendering and OnInit loads use the same
frozen bytes. Logical absolute paths avoid re-resolving links after capture; missing
unused profiles retain lazy failure behavior. Unknown file requests fail closed.
Context is restored on exit; no global monkey-patching or rendering-file cache.

38 distinct selected NPC/shop/metadata/status/snapshot/GUI/offline checks passed.
Three new cases cover frozen dialogue/shop/rendering equivalence, thread scope
isolation, and actual background JSON/TXT generation with late live changes and
cancellation. The equivalence test blocks file opens/reads/path resolution after
capture. Initial fixture used a duplicate actor_id keyword; fixed and rerun.
No full discovery, live capture or Auriga execution. Frozen v0.0.4 unchanged.

Synthetic 1000-placement profile: freeze 80.7 ms, generation 561.2 ms; generation
moves off the GUI thread. This excludes initial Entity dictionary preparation and
uses no conversations. Both JSON and TXT hashes match prior outputs. Reproduce with
tools.profile_structured_exports --npc-deferred --only-npc. Copy and one expensive
merged conversation can still block their respective phase; interruption is checked
before/after generation and during writing. Next: capture/export stop/error/shutdown
combinations while preserving the fixed evidence prefix.


## 2026-10-29: capture/export shutdown ordering audit

Found a real ordering defect: MainWindow could close SQLite while admitted Qt
packet deliveries were still pending. Bridge now seals new admission on workspace
close, separately counting shutdown rejection without marking overflow. Already
admitted packets, including the admission-before-emit race, drain before DB closure.
Closed workspaces ignore late direct callbacks. Normal stop remains restartable
and preserves old-generation delivery behavior.

Close keeps an open session log until drain/export/child shutdown completes, so a
DB failure during drain is recorded before session_end. packet_delivery_shutdown
records counts when the log is still open; previously stopped logs are not reopened.
The owner now waits for any remaining offline child, including replay workers, and
closing offline workspaces reject new exports immediately. GUI test cleanup waits
for accepted close to avoid deleting temporary resources while work is pending.

24 distinct targeted capture/display/offline cases passed across selected runs,
including four new regression cases for queued/admitted-unemitted packets, frozen
MOB/NPC exports across stop/restart/DB failure, close during generation/DB error,
and owner close during replay. Independent file-DB reads confirm drained commits;
metadata excludes private exception text. No full discovery or live/Auriga execution.
Frozen v0.0.4 unchanged. This is scoped verification, not a claim of all thread races.
Next return to P1-B observed-event comparison coverage and exclusion diagnostics.


## 2026-10-29: event-trial exclusion evidence audit

Audited retained observations in the existing Toy Factory analysis: 198 rows across
7 presentation kinds, already recognized by the comparison UI. Found diagnostic
gaps: invalid/reversed times and events beyond the per-trial cap were absent from
excluded-observation inspection. Shared clock classification now drives both the
comparison and review. Derived review shows invalid_time/time_reversed/event_limit,
nullable offsets, original packets and bounded details with full reason counts.
Unlocatable times are not assigned a synthetic window position. GUI displays an
unavailable offset explicitly and preserves source navigation/invalidation.

14 distinct selected event-trial/selection/timer/GUI cases passed, including two new
regressions for invalid/reversed/huge clocks, limits/omissions and GUI packet jumps.
Existing report format, eligibility, variants and timer adoption remain unchanged.
The audit tool creates validation-only anchor groups from saved analysis; six groups
have byte-identical canonical comparison hashes before/after, with input SHA-256
unchanged. Outputs are logs/event-trial-review-{baseline,after}.json. No new server
logic, timer estimates or unsupported packet decoding. No full discovery or live
integration; frozen snapshot unchanged. Next: dialogue-action comparison coverage,
with explicit duplicate and target-association rules.


## 2026-10-29: opt-in dialogue-action comparison

Added include_actions=False to dialogue-start comparison projection and an explicit
GUI checkbox enabled only for that mode. Legacy presentation/map modes and default
saved selections stay unchanged. Five validated action kinds project into comparison
rows without mutating conversations or generated NPC code. Dialogue owner scopes
actor_id/npc; effect_target describes the actual/unknown recipient. Status tick stays
in raw_fields but is excluded from semantic comparison. Instance target names use
existing complete-suffix rules. Target differences participate in variants/review.

Prompt/reply links and packet order classify waits, without guessed timeout lengths.
Waits, after-close replies, outside-visibility changes, unresolved targets and review
candidates remain excluded with reasons. Existing presentation/step packets take
precedence; identical actions deduplicate, distinct same-packet contents remain.
Capacity and action validation fail closed. Dropped action counts are visible in GUI
and opt-in comparison JSON. No manual timer adoption extension. Anchor reload uses
the same checkbox option and strict source/observation hashes; global index/session
remaps are tested. Old selections still load with the default option OFF.

17 distinct targeted trial/selection/timer/GUI cases passed across selected runs,
including three new cases for all action kinds, scope/target/wait/duplicate rules,
tick handling, target variants, selection remap and GUI reload/source navigation.
Saved analysis yields all 37 action rows among 411 projected rows/89 dialogue starts;
24 anchor groups are validation-only. Default six comparison hashes and input SHA-256
remain unchanged. No full discovery or live/Auriga execution; frozen snapshot unchanged.
Next: multi-log and regenerated-instance target identity/exclusion review.


## 2026-10-29: instance action-target scope and ambiguous names

Found two identity gaps: runtime map projection could disguise a recipient in a
different instance, and partial owner suffixes could match across unrelated scopes.
Action projection now validates raw recipient maps before canonicalization; foreign
maps/instances and ambiguous partial recipient names become explicit exclusion
contexts. Existing dropitem candidate map arguments use the same validation and
comparison-only normalization, without adding floor-item history. Raw evidence stays.

Dialogue-start anchors with ambiguous owner names add a capture/flow/raw-map/ActorID
scope. Same-ID viewport re-observation and map-visit changes remain comparable; no
appearance counter is treated as ID reassignment. Full names retain cross-log and
regenerated-instance placement comparison. Presentation/manual-timer modes are not
extended by this guard. Exclusion review now retains recipient metadata rather than
mistakenly displaying only the conversation owner. GUI shows raw recipient names/maps,
tooltips and a note distinguishing raw display from projected comparison semantics.

24 distinct selected trial/selection/instance/timer/GUI checks passed across targeted
runs, including three new cases for three-log order/session/index remaps, instance
recipient guards/partial names, and exclusion GUI/source navigation. Existing source
analysis and all 24 opt-in/6 default comparison hashes remain unchanged for the
provided log. No full-suite or live/Auriga execution. Frozen v0.0.4 untouched.
Next: bind comparison mode/options to saved anchor settings with old-format support.


### 2026-10-29 — Comparison settings in saved anchors
GUI anchor selections now save schema 2 comparison mode and include_actions; legacy
schema 1 callers and readers remain compatible. A validated row factory projects
saved settings before log/event hash matching. GUI controls change only after full
validation; failed loads preserve selected anchors, window, options and report.
Successful loads invalidate old results and require explicit recomparison.
Five selected selection/GUI tests passed, including legacy factories, invalid option
rejection before row projection, automatic cross-mode restore and failed-load retention.
No full suite, live capture or Auriga execution; frozen v0.0.4 unchanged.
Next: review multi-log resume and evidence display, including missing/retained-data limits.


### 2026-10-29 — Multi-log resume evidence and retention limits
Comparison differences now show capture generation, flow and current source log for
both sides. Anchor/event/exclusion Packet tooltips retain provenance, including
reference-only observations. Map-anchor dropped counts now survive compute and
comparison JSON export. All retention notes distinguish global retained-data counters
from trial-local loss and explicitly avoid claiming completeness for zero counts.
Six selected tests passed after preserving existing difference-label prefixes;
new GUI regression reorders three logs and remaps session/global Packet indices,
then checks selected/reference/excluded navigation and failure-free restoration.
No full suite or live/Auriga checks; frozen release unchanged.
Next: check comparison/manual-timer adoption boundaries for the added anchor modes/actions.


### 2026-10-29 — Shared manual timer adoption entry guard
Editor and generator now share validate_timer_trial. Only presentation mode (including
legacy absent mode) is eligible; additional anchor modes, opt-in dialogue action
reports and owner-scoped/extra-anchor rows are rejected before editor construction.
The editor also checks the live-comparison callback before allocating its UI.
Nine selected timer unit/GUI tests passed. New coverage exercises unknown/extra
modes and row markers plus real window/mode/option/revision/report changes while an
editor remains open. Existing manual-time, confirmation, stale save/load, announce
and effect-removal paths pass. Reports are not mutated; no auto code integration.
No full suite or live/Auriga checks. Frozen v0.0.4 unchanged.
Next: review unsupported presentation kinds and explicit recipient/adoption constraints.


### 2026-10-29 — Recipient and context validation before timer editing
Moved existing recipient/placement/scope/packet/offset checks into shared trial
validation, so invalid evidence is rejected before editor allocation as well as
at generation. Unassigned announce's explicit same-flow association now also
requires outside_dialogue; known-map and generation guards remain intact.
The anchor itself must be an observed NPC presentation outside dialogue.
Nine distinct selected timer unit/GUI tests passed; the amended GUI entry test was
rerun after adding foreign/unknown/waiting/unsupported/missing-packet cases.
Unsupported sound/music/unittalk/viewpoint/action kinds remain comparison-only
for this timer exporter; existing conversation generation is unchanged.
No full suite/live/Auriga execution; frozen v0.0.4 unchanged.
Next: cross-check P2 sound/unittalk command arguments and recipient requirements
against existing dialogue rendering before selecting a bounded manual export extension.


### 2026-10-29 — Self-NPC unittalk manual timer candidates
Checked local Auriga buildin_unittalk: string-first form targets the executing NPC.
Added only observed same-NPC outside-dialogue unittalk, preserving scope guards and
requiring exact text-only fields, manual times and explicit confirmation. External,
MOB and unresolved recipients remain blocked. Existing event_timers profile gains
unittalk with old-profile fallback; rendered command/text must match validated input.
GUI labels/preview/JSON reload support the new kind. Eleven selected unit/GUI checks
passed, including quoted/newline text, unsafe profiles, legacy profiles and source
immutability. Sound remains comparison-only: buildin_soundeffect requires attached
player, which ordinary NPC timer observations do not establish.
No full suite/live/Auriga execution. Frozen v0.0.4 unchanged.
Next: inspect existing-log unittalk recipients and contexts without inferring cause.


### 2026-10-29 — Existing-log unittalk inventory diagnostic
Added bounded unittalk_review to the existing read-only comparison audit. Retains
source Packet/session/flow/ActorID/raw placement/text and overlapping exclusion
reasons; candidate flags are explicitly preliminary, not manual adoption or cause.
Existing toy-factory analysis: 65 unittalk (49 outside,16 close_wait), 46 preliminary
anchor candidates and 19 excluded observations (16 waiting,3 non-NPC/unresolved).
Output: logs/unittalk-presentation-review-audit.json. Input SHA and all six existing
comparison objects/digests match the prior default audit; detail omissions zero.
Eight selected timer/audit tests passed. Local clif_GlobalMessage confirms payload
text is passed unchanged; name-like text prefixes are not inferred away.
No source rewrite, timer selection/generation, full suite or live/Auriga execution.
Frozen v0.0.4 unchanged. Next: explain unsupported kinds within candidate windows
at the comparison surface before users attempt manual adoption.


### 2026-10-29 — Self-player speech SEND association (user steering)
Local Auriga parser/overhead code confirms 008C input,008D surrounding broadcast,
008E self echo. Added bounded exact-byte matching for the supported variable-length
008C layout: same capture/flow/known self ActorID, ordered packets and finite times
within 5 seconds. At most 64 pending messages,1024 bytes per packet. Unique matches
retain SEND Packet evidence; duplicates remain ambiguous; missing SEND is unresolved,
never evidence of script origin. Each matched candidate is consumed once.
008E is retained as player_chat; known self 008D/008E is PLAYER rather than NPC.
No player utterance is adopted as an NPC timer. Candidate origin remains unconfirmed.
Selection hashes exclude only nested SEND navigation index while retaining all other
origin metadata and exact source hashes, allowing global Packet remaps on reload.
22 selected external-presentation/timer/selection/GUI tests passed. No full suite,
live-input test, protocol table changes or frozen release changes.
Next: resume unsupported-window-kind/adoption-reason display work.


### 2026-10-29 — Pre-adoption status in comparison UI
Selected trials now expose shared validate_timer_trial results before editor launch.
Unsupported kinds include per-kind counts; invalid trials disable the create button.
Eligible status explicitly requires manual times/confirmation and does not claim
causality or completeness. Invalidation resets the status and button. No filtering,
trial mutation or removal of unsupported events is performed to enable adoption.
Eleven selected timer/GUI tests passed, including supported unittalk, unsupported
music/self-chat, comparison-only modes and original report immutability.
No full suite/live/Auriga execution; frozen release unchanged.
Next: replay existing logs to inspect actual self-chat/SEND associations and
missing-capture/unsupported-layout diagnostics without inferring script origin.


### 2026-10-29 — Raw-log player speech replay diagnostic
Replayed six of seven existing logs using each recorded PacketLength.used.txt.
20261026-222844-32e7f1c6 cannot replay because payload recording was disabled.
Latest capture:11,729 packets,73 RECV008D,all different from the observed self ActorID;
no SEND008C or RECV008E. Thus real self-input matching remains unverified. Existing
65 retained presentations plus eight dialogue steps account for all73; dropped zero.
Added tools.audit_player_speech with source/definition hashes checked before/after,
source overwrite protection, bounded details, raw-payload hashes and preserved replay
diagnostics. Stored logs/player-speech-replay-audit.json (detail omissions zero).
Speech metadata now distinguishes unsupported layout,unknown self,different actor,
no matching send,unique match and ambiguous matches. Unsupported layout takes priority.
14 distinct selected tests passed; amended unsupported-layout reason test rerun passed.
No full suite/live/Auriga execution. Frozen release unchanged.
Next: human-readable speech-origin explanation and navigation to matched SEND evidence.


### 2026-10-29 — Speech-origin explanation and SEND navigation
Observation selection now shows human-readable speech-origin status and unresolved
reasons. One SEND-evidence button is enabled only for a confirmed-self unique
association with an integer nonnegative SEND index preceding the receive index.
Ambiguous/unknown/invalid/no selection cannot navigate; stale observation revisions
require refresh and reselection. Tooltips retain generation/flow/current source.
Comparison differences use the same explanation labelled for selected/reference
trials. Source confirmation is independent of timer adoption and comparison windows;
no cause/script attribution is inferred and full metadata remains in saved analyses.
Three selected GUI tests passed, including end-to-end packet delivery/self echo,
stale-source blocking, reason/status guards and existing multi-log evidence display.
No full suite/live/Auriga execution. Frozen release unchanged.
Next: return to P2 presentation kinds, separating player-attached and NPC-self commands.


### 2026-10-29 — Raw-packet collection checklist requested by user
Added docs/capture/raw-packet-collection-checklist.md and documentation index link.
Prioritizes missing self-input/receive speech examples, then login/reconnect, menu
order/loop merging, input values, normal/timeout-prefix merging and close/close2.
Includes repeated event/instance/visibility/metadata/shop and optional resource/MOB
HP-ratio/skill/effect examples, grouped into four practical capture sessions.
Distinguishes game operation order from packet order, records actual choices and
initial-state differences, keeps full raw logs plus used definitions and notes.
No forced packet injection/resync, no floor-drop history collection, and no live/
Auriga execution is performed or implicitly resumed. Documentation-only change.


### 2026-10-29 — New user capture: chat, choices and timeout validation
20261029-215033-0a6328fa:15,472 packets (880 SEND/14,592 RECV),27 connections,
no framing errors or incomplete streams;20 conversations,10 merged groups,no generation errors.
Found real SEND008C/self008E lack terminating NUL. Accept optional terminator only
for these supported layouts while validating exact total length/no embedded NUL.
Two input pairs now uniquely match; prior two self-chat layout issues disappear.
Old toy-factory capture DOES contain three self-targeted08B3 overhead messages,
not008D. Corrected earlier coverage claim; classify known-self overhead as PLAYER,
retain non_chat_notification reason, never consume normal-chat SEND for this kind.
Added real-byte regression and ran22 selected speech/selection/GUI/timeout/menu tests.
Verified choices1/2/3 merge, loop generation, and timeout close prefix normalization
for conversations6(menu) and18(next). Preserve cancelled255 paths as excluded.
Saved verified analysis, speech audits, validation-summary.json and merged-dialogues-reviewed.txt.
Six09FF name CP932 issues plus timeline warnings remain; quality stays review_required.
No source rewrite, inferred causal conditions, full suite or Auriga execution.
Frozen release untouched. Next: inspect truncated/invalid spawn-name bytes first.


### 2026-10-29 — Incomplete spawn-name tail diagnostics
All six09FF issues in the new capture have a23-byte name at the correct offset84,
ending in a single CP932 lead byte. Retained strict decoding; no offset search,
replacement character or inferred suffix. Add non-authoritative valid-prefix/raw
boundary diagnostics to entity metadata and observation evidence only. GUI labels
unnamed records as incomplete/reference; authoritative Entity.name stays unchanged.
A valid later name clears current diagnostics; later malformed observations never
replace an existing valid name. Historical evidence/issues are retained.
22 distinct selected world/GUI/metadata tests passed across targeted runs (one amended
world test rerun). Real-capture replay confirms all six packet diagnostics, unchanged
source SHA and byte-identical generated dialogue strings for all ten groups.
Saved session-analysis-name-diagnostics-review.json and spawn-name-diagnostics.json.
Quality remains review_required; warnings are explained, not hidden. No full suite,
live capture or Auriga execution; frozen release unchanged.
Next: inspect two overlapping-prompt timeline notices in the new capture.


### 2026-10-30 — Preserve aborted waits instead of false prompt overlap
New capture conversations6(menu) and18(next) received marked server close with no
reply to the recorded pending request. Timing previously replaced pending, lost the
original incomplete wait, and emitted overlapping_prompt. Exact prompt kind/index
matching now records unanswered_termination, preserving incomplete wait/observed-until
and termination step/Packet. Close ACK is tracked separately; no timeout duration is
inferred. Repeat samples remain excluded. Genuine/unmatched overlaps remain unchanged.
GUI interval/quality labels distinguish aborted input; prefix normalization accepts
this quality marker without changing its evidence guards or restoring continuation.
16 selected timing/timeout/GUI tests passed. Actual replay preserves source SHA,
normalizations for6/18 and all ten generated dialogue strings. Stored new analysis
and unanswered-wait-validation.json. Quality still review_required. No full suite,
live operation or Auriga execution. Frozen release untouched.
Next: inspect the one start-unobserved OnTouch/warp observation in this capture.


### 2026-10-30 — OnTouch-only warp observation review
New capture conversation10 has no click/body:class45 ActorID6 at ev_season01(27,91),
walk-destination Packet3415 and warp Packet3419 to prontera(86,58). Candidate is the
unique nearest in the highest-priority observed class. Preserve cause-unconfirmed,
walk-arrival-unconfirmed and provisional1/1 radius; no inference expansion.
Native warp placement is equal with merge on/off. Stored touch-warp-review.json
and touch-warp-reviewed.txt. GUI now explains start_unobserved as an OnTouch candidate
with radius/walk evidence rather than a generic missing-click warning. Underlying
quality flag and repeat exclusion remain intact; no capture or generation changes.
16 selected touch/GUI tests passed. No full suite or Auriga execution; frozen release
unchanged. New-capture warning review is bounded-complete, not transport verification.
Next: P2 self-player overhead notifications and their in/out-of-dialogue association display.


### 2026-10-30 — Self-player overhead context association and review
Known-self08B3 keeps PLAYER recipient. Same capture/flow and matching known NPC/player
map allow association to active conversation or close-pending context only; retain
conversation/owner IDs and preceding step with cause_confirmed=false. Contexts are
during_dialogue,input_wait,close_wait; no owner or mismatched map/flow remains outside.
Keep associations solely in presentation_observations, not conversation command or
parallel/external generation lists. Existing target-review panel now includes these
notifications separately from external NPC effects, with both source Packet jumps.
17 distinct selected overhead/external/GUI tests passed across targeted runs. Old
capture replay retains three outside-dialogue self overhead notifications and all
100 conversations' steps/terminations. In-dialogue cases are synthetic verification,
not claimed live coverage. Saved dialogues-player-overhead-context-review.json.
No full suite/live operation/Auriga execution; frozen release unchanged.
Next: inspect merged contribution source matching, duplicates and navigation for
player notifications across logs/observation generations.


### 2026-10-30 — Merged player-notification source and stale-view guards
Index player notifications by capture/flow/conversation/owner instead of rescanning
all observations for every contribution. Match contribution/current source strings
when both exist; show source-mismatch counts. Deduplicate identical full evidence
rows in the view only, retain content differences even at the same Packet index.
Invalid/nonpreceding anchor indices cannot navigate. GUI captures store identity,
revision and source-map snapshot; changed evidence/source clears stale view before
navigation. Fixed a new Qt reentrant selection-clear crash with QSignalBlocker.
Four distinct selected GUI tests passed after repair, plus a focused rerun after
adding source-only-change coverage. Synthetic3-log/session/global-index remaps,
duplicate/foreign contributions and input immutability covered. No source/model/code
generation changes or claims of real multi-log self-notification coverage.
No full suite/live/Auriga execution; frozen release unchanged.
Next: add associated self notifications as observation-only dialogue timeline rows,
keeping NPC command paths and autonomous timing samples separate.


### 2026-10-30 — Observation-only self-notification timeline projection
Shared index/linked-row helpers select recorded self-overhead associations by
capture/flow/conversation/owner and valid preceding step/Packet interval; deduplicate
identical evidence. Append observation-only rows after original delta/candidate
calculations, preserving all original NPC rows,waits,candidates and quality.
PLAYER target/owner IDs,text/context are explicit; no delta/wait time or command
inference. GUI and snapshots share projection, max1000 details with count/omissions.
18 distinct selected timing/timeout/GUI tests passed across runs; amended GUI source
jump test rerun passed. Saved20-conversation timeline and timing summary semantics
unchanged apart from added notification counters; stored player-notification-timeline-review.json.
Also found the previously appended aborted-wait unit test below __main__ and outside
the test class: moved it into the class and explicitly executed it successfully.
Prior suite results did not include that new case; current selected run includes it.
In-dialogue self-notification coverage remains synthetic. No full suite/live/Auriga
execution; frozen release unchanged. Next: read-only presence/text differences for
self notifications across repeated observations of the same dialogue path.


### 2026-10-30 — Purpose-focused workspace layout review
Found comparison buried below code with~930px minimum height and tiny tables.
Moved it to a dedicated top-level tab, reordered NPC/dialogue/MOB workspaces and
classified menus as Work/Export/Settings-Diagnostics. Export merge action synchronizes
with the existing checkbox; selected/busy availability follows current state.
Comparison uses resizable observation/result split and side-by-side trial/event
views, with compact nearby source/adoption buttons. Hidden columns retain full data
in tooltips/detail/JSON. Dialogue code/details have deliberate initial split sizes.
CurrentPageTabs stops hidden heavy MOB pages from compressing the entity list.
Optional nonmodal comparison popup reparents the SAME widget, preserving report,
selection/settings and source protection. Close/return reattaches; owner close waits
for existing export shutdown then closes it. Popup supports resizing/maximizing.
Main preferred geometry is bounded by available screen; settings/diagnostics/basic
data/popup first placement is clamped, while later manual geometry is retained.
22 distinct selected layout/timing/entity/basic-data GUI checks passed across runs.
An insertMenu argument error found during development was corrected before passing.
Existing-data Qt rendering inspected at1024x740 and1200x820 plus popup; Meiryo font
registration used only in preview process (no product font override). Saved images
under logs/gui-layout-review. No full suite/live capture/frozen release changes.
Next: return to read-only repeated-observation differences for self notifications.


### 2026-10-30 — Read-only self-notification repeat differences
Added player_notification_review: complete same-placement/same-observed-step+token
paths only; selections/inputs/body/actions constrain grouping. Compare notification
presence,raw text,context and preceding-step position, not delay or ActorID numbers.
Keep source/session/conversation/target IDs and both Packet references. Empty valid
observations mean unobserved, never loss/nonoccurrence. Partial/timeout/open-wait,
source mismatch,quality/scope/time problems,unknown self/unsupported origin and
conflicting same-Packet evidence are excluded rather than counted as absence.
Existing target-review caption/detail JSON display status and excluded/duplicate
counts; no extra window/buttons, code mutation, command/condition/timer inference.
Capacity guards:2000 contributions,100k steps,1000 notices/observation; detail view
200k chars. Original observations and full held review data remain intact.
Nine distinct selected overhead/GUI tests passed across runs, including amendments
for invalid origins/times,partial-count display and truncation without data deletion.
Saved old-log player-notification-repeat-review.json: no in-dialogue repeat groups;
three known-self overhead observations are outside dialogue. Synthetic coverage is
explicit; no full suite/live/Auriga execution, frozen release unchanged.
Next: P2 player-dependent sound/music/progress recipient/context display review.


### 2026-10-30 — Presentation recipient roles and player-context notes
Added view-only presentation_context descriptions:01D3 actor is sound origin rather
than receiver;07FE/0B8C and02F0 do not record target ActorID;09D1 records progress
unit,not necessarily caller. Owner-scoped progress actions never reuse owner ID
as target. Local Auriga sound/music/progress functions confirm attached-player
requirements;09D1 execution context remains unconfirmed. No new timer generation.
Comparison target cells,selection note/tooltip and both difference sides expose
these roles without modifying observation fields,context classification or reports.
Sixteen selected music/action/GUI tests passed,including source immutability and
existing contextual progress generation. Existing analyses contain11 music,5 progress
actions and6 sounds; source hashes and all6 default comparison objects remain equal.
Saved logs/presentation-target-context-review.json.09D1 coverage remains synthetic.
No full suite/live/Auriga execution; frozen release untouched.
Next: inspect progress completion/cancellation and following conversation without
inferring success,elapsed wait or unseen server script conditions.


### 2026-10-30 — User-requested default length definition
GUI startup now always selects project-root PacketLength.txt; extracted client
lengths remain manually selectable. Updated current README/setup guides. Frozen
release artifacts and previously captured PacketLength.used.txt are unchanged.


### 2026-10-30 — Bounded progress protocol diagnostics
Added ProgressTrace and exposed its snapshot in the existing dialogue diagnostic JSON.
02F0 starts, SEND02F1 reports, RECV02F2 aborts and same-dialogue followups retain
packet evidence without changing dialogue steps or inferring server success/timers.
Overlapping unresolved starts, invalid layouts/times, flow/capture/boundary separation,
record limits and GUI visibility are covered by 7 selected passing tests (no full suite).
Replayed 11729 packets with normal player observations: all5 start/report/followup pairs
found;100 conversations and merged generated output match a same-revision replay with
ProgressTrace.observe disabled. Earlier historical reports include unrelated changes
and were not used as the final equivalence baseline. Source SHA unchanged; saved
logs/20261028-012526-0abe69d9/progress-protocol-review.json.
Real abort/09D1 coverage remains pending; frozen snapshot remains untouched.


### 2026-10-30 — Progress capture procedure and pending coverage
Expanded existing collection checklist C04: normal finish, attempted interruption,
restart and targeted09D1 observations, expected packet orders and noncausal limits.
Normal5 pairs are already covered; actual02F2/09D1 remain pending, without blocking
other development. Corrected obsolete GUI menu/default-length instructions and
an outdated claim that self-input chat had not been captured. No protocol or
script-generation behavior changed. Next: viewpoint/typed-effect/removal targets
and generation conditions.


### 2026-10-30 — Marker and effect target review
Reviewed local Auriga clif_viewpoint/buildin_viewpoint and delmisceffect alongside
existing decoder/render guards. Added view-only marker NPC / effect target notes
in comparison lists and details. Kept known marker generation, raw valued-effect
comments, external removal proposals and manually confirmed removal timers intact.
15 selected unit tests in4 related modules and2 selected GUI tests passed; no full
suite or live/Auriga execution. Observation models and command-generation rules
were not changed. Next: comparison evidence navigation and stale-view guards.


### 2026-10-30 — Comparison evidence identity guards
EventTrialPanel now checks store identity, observation revision and an immutable
source-reference mapping key for list freshness and report validity. Source-only
changes and replacement stores with equal revisions invalidate old navigation,
recomputation, save initiation and timer adoption. Retain the store in the key so
Python object ID reuse cannot make a different store appear current.
7 distinct selected GUI tests passed (one new test covers source/store/revision
changes and all6 navigation paths). Multi-log/current/reference/excluded evidence,
manual adoption and frozen-at-save-start export behavior remain covered. No full
suite, packet decoding or generated script changes.


### 2026-10-30 — Current MARiA gaps and map cell observations
Refreshed obsolete gap statements in the roadmap using current code, without
changing frozen v0.0.4 claims or deferred live/Auriga verification.
Added strict24-byte RECV0192 decoding and bounded, unassigned presentation retention.
Do not create conversations or emit setcell/timers. Preserve packet map/coordinates/
cell_type and wait context. Window association requires explicit current scene,
matching capture/flow/map generation and exact packet target-map equality.
8 selected unit and3 selected GUI tests passed; no full suite. Replayed11729 packets:
100 conversations and merged code equal same revision with cell retention disabled.
No0192 occurred, so real coverage remains pending. Source SHA unchanged; saved
logs/20261028-012526-0abe69d9/mapcell-observation-review.json.
Next: dialogue size/position/alignment observation scope and preservation.


### 2026-10-30 — Dialogue layout observations and wait-context guard
Added strict receive layouts:0BA2 size,0BA3/0BB5 position (10 bytes),0BA1 alignment
(3 bytes). Preserve unsigned raw values, context and same-flow conversation/start
references without actor assignment, command steps, inferred defaults or timers.
Dialogue-start comparison requires exact start packet and explicit scene evidence.
Found and fixed unassigned window association bypassing wait-context exclusions
for mapcell and new layouts; music/announcement behavior unchanged.
11 selected unit tests and4 selected GUI tests passed. Normal-path replay of two
logs (11729/15472 packets,100/20 conversations) equals layout-retention-disabled
replay for conversations and merged code. New log has3 size observations; no actual
position/alignment coverage. Source and definition SHA unchanged. Saved per-log
dialogue-layout-review.json. Next: repeated layout differences and evidence display.


### 2026-10-30 — User-confirmed dialogue layout command generation
User confirmed the specification and requested generation. Active-dialogue layouts
now also become validated bounded actions; retain original unassigned observations.
Added external templates for messize/mespos/mesalign with old-profile fallback.
Reuse existing action ordering and wait deferral plus warning; unanswered waits,
close-wait and outside-dialogue notifications do not generate commands.
Added presentation conflict and menu-loop support.10 selected tests passed,
covering all4 packet IDs, order, value/presence differences, wait replies, custom/
legacy profiles, typed field validation and GUI output. No full suite.
Replayed15472 packets,20 conversations,10 merged groups:3 messize commands,
zero generation errors. Saved dialogue-layout-generation-review.json and
merged-dialogues-layout-generated.txt; source/definition hashes unchanged.
Position/alignment real capture remains pending; frozen snapshot unchanged.


### 2026-10-30 — Placed layout exports and frozen save verification
No additional production fix was needed. Added a reusable complete placed layout
fixture and3 focused export tests: merge ON/OFF TXT/JSON parity, model/profile read
isolation after freeze, and actual51-conversation GUI background export while the
save dialog mutates live widths. All3 passed; no full suite.
Replayed the15472-packet log through world/player/dialogue/shop handlers and verified
both merge modes:161 entries,8 exclusions,3 messize commands; frozen report equals
direct report in full. Source/definition hashes unchanged. Saved
npc-layout-bundle-review.json and all-npcs-layout-generated-merged.txt.
Do not treat exclusions as resolved or frozen-export equivalence as Auriga runtime
validation. Next: waiting/unanswered-end layout merging.


### 2026-10-30 — Matching wait layouts in timeout-prefix merging
Previously any post-prompt action prevented timeout-prefix normalization. Allow
only validated size/position/alignment observations in the final unanswered wait,
and require an exact ordered kind/value/count signature from the corresponding
answered wait. Validate packet/time bounds, ordering and duplicate packet evidence.
Other post-prompt evidence remains outside normalization. Keep original actions;
project only pre-prompt actions for prefix matching. Generate commands solely from
the normal observation and retain matched_wait_layout_observations provenance.
10 distinct targeted tests passed, covering4 input kinds, presence/value/order/
count differences, invalid packet/flow/bounds and reverse timestamps, original
immutability, ordering independence, GUI and bulk export. No full suite.
Replayed15472 packets:20 conversations,10 groups,2 existing timeout normalizations
and generated code unchanged. Actual wait-layout+timeout coverage remains absent;
source/definition hashes unchanged; saved wait-layout-timeout-review.json.


### 2026-10-30 — Supplied client data survey and utilization plan
Read-only inventory of.reference/data:3109 files,174068656 bytes. Saved full
path/size/SHA manifest and restricted skill-name pilot to
logs/client-data-reference-inventory.json. Current dictionary1325 names; skillinfoz
has1976 SKID symbols/1975 numeric IDs and1750 resolved name records. Byte-level
Lua unescaping before strict CP932 yields588 additions,122 differing names and163
current-only entries. Do not delete current-only names or infer unit IDs from SKID.
Found1517 binary Lua headers among1534.lub files; iteminfo.lua/.lub are identical
text.10 Lua files contain decompiler-error markers; one recorded bad-header failure.
No Lua,exe orbat execution. Added client-data-utilization-plan.md and linked docs/
roadmap. Next priority: limited static import and dry-run for the2 skill files,
then provenance-aware dictionaries and independent unit/state/effect catalogs.
No runtime/config dictionary changes or tests; this turn was survey and planning.


### 2026-10-30 — User-confirmed Lua priority for differing skill names
Applied122 verified name differences from the prior restricted literal audit after
checking both source hashes and the baseline dictionary hash. Lua names win;
retain current-only IDs and do not yet add the588 new candidates. ID set/count
remain1325. Validated with the existing loader before atomic replacement. Recorded
source/policy metadata in the dictionary and reversible before/after names in
logs/skill-name-lua-priority-update.json.3 selected tests passed: Lua labels in
MOB candidates, unchanged packet skill ID/model, existing naming and loader API.
No full suite; future importer will use this priority without per-name approval.


### 2026-10-30 — Restricted static skill-name importer and588 additions
Added reconstruction.skill_catalog and tools.import_skill_names with dry-run default,
strict byte-literal unescaping before CP932/UTF-8, bounded table parsing and no Lua
execution. Reject duplicate keys, function/call syntax, invalid/unresolved names
and conflicting numeric-ID names. Keep Lua priority and current-only names.
Centralized existing skill dictionary validation without changing its API. Before
atomic apply recheck all3 input hashes and the proposed document hash; preserve
existing output on failure. Protect.reference and report source/config paths.
13 selected tests passed, including CLI/dry-run/apply, escaped CP932, mixed-case
symbols, malformed data, file changes mid-write, replacement failure, idempotence,
MOB names and frozen reporting. Registered catalog suite; no full test run.
Full parser found the mixed-case All_EVENT_20TH_ANNIVERSARY omitted by the initial
uppercase-only pilot:1977 symbols/1976 IDs,1751 named IDs,162 current-only names.
Added588 names, changed0 (122 prior Lua name differences were already applied):
1325->1913. Repeated import reports add0/change0/issues0 and identical output.
Applied dictionary SHA256:51cced23d431efe54001a50316fee81c119508228f903f5d77a0b07682f2a1e5.
Saved import plan and after-update report; original reference data unchanged.
Next priority is independent skill-unit ID name resolution; client data does not
supply server AI/conditions/timers.


### 2026-10-30 — Skill unit-type labels without skill-use inference
Added a bounded catalog loader and static reference builder. Python UNITID is read
through AST constants, C enum through literal/increment parsing, unit DB links only
when client SKID symbol and numeric ID agree.173 types accepted;264/265 conflicts
excluded;6 unresolved links retained. Source hashes pinned; no reference execution.
Standard09CA display now separates runtime unit actor(offset4), source actor(offset8)
and unit type(offset16), preserving legacy actor_id and raw packet IDs. Show shared
skill candidates without adding skill observations. Profile freezes catalog at load;
fields include mapping basis/catalog SHA. Unknown/disputed IDs remain numeric.
10 selected tests passed, including GUI and unchanged MOB identity/skill count.
Old capture has25 decoded/known09CA; no length errors. New capture has none.
Source bytes unchanged; logs/skill-unit-label-review.json records the review.
Project catalog bundling and state/effect labels remain separate follow-up work.


### 2026-10-30 — Display-only status and visual-effect symbol catalogs
Added static constant builder and bounded loader:1318 status-icon IDs and121 visual-
effect IDs in distinct namespaces. Record3 identical duplicate definitions; reject
conflicts. Ignore only the exact known EFST unknown-state guard tail, without
executing Lua or changing the general skill importer grammar.
Standard receive/Auriga profiles label7 packet formats with frozen reference names
and catalog SHA. Preserve all packet IDs/fields; no SC conversion policy, dialogue
commands or MOB skill observations added. Unknown IDs remain numeric.
8 selected tests passed for static parsing/guards, namespace isolation, malformed
catalogs, all7 formats, fixed reads, GUI, existing SC conversion and suite coverage.
Two existing logs:3213 relevant notifications, zero display errors;2255/2566 status
and51/647 visual effects resolve. Remaining IDs stay explicitly unknown. Input
source hashes unchanged; saved logs/reference-name-display-review.json.
Next: project pinning/verification for the new name catalogs; Japanese descriptions
and broader effect dictionaries remain later work. No full-suite/live/Auriga test.


### 2026-10-30 — Project name-catalog references and runtime verification
Added optional catalogs references to current schema1/2 projects; old manifests
remain accepted. GUI save captures the loaded skill-name hash from the same bytes
used for decoding and frozen display catalog hashes. Disk or cross-presenter
mismatch blocks save. Project verification checks referenced files and actual
bundled runtime dictionaries; arbitrary external runtime overrides/embedding are
not introduced. Public replay results also check loaded hashes before publication.
Reference repair lists the3 catalog types and preserves same-content relocation.
Legacy projects show a title warning that catalog versions were not recorded.
Fixed the stale5-tab validation limit to allow current packet-details tab index5.
9 distinct selected tests passed for storage(single/multiple), old/new GUI roundtrip,
stale save, runtime mismatch, pre-publication mismatch, relocation and name reload.
No full suite. Created/verified real-log catalog-pinned-work.gpa.json with3 catalog
hashes; raw input unchanged. Next: item/MAP/quest display name dictionaries.


### 2026-10-30 — Client item/map/quest labels and observed identification
Added static TXT builder/catalog:15880 identified item names,4906 nonempty map names,
8030 quest IDs.8 empty map labels and6 duplicate quest records retained as evidence;
5 distinct-title conflicts shown as alternatives. User explicitly excluded unidentified
names; no import/display of that table. Compact1.2MB JSON stays within2MiB limits.
GUI shares one loaded catalog for inventory labels/map summary/quest timeline and
pins its hash in projects. Partial old catalog manifests show a version warning.
Confirmed inventory identification bit0 for0B09(offset33)/0B0A(offset66), preserving
raw flags/source PID. Pickup bytes and0179 success0 update state; failure or unknown
slot cannot fabricate inventory.0B38/0B39 flag layout remains unknown. Quantities,
reference names and identification stay distinct; no NPC command IDs rewritten.
13 selected tests passed for dictionaries/masks/acks/quantity/GUI/versioning. Earlier
full affected Player module also passed; no global suite. Old/new logs have265/336
final slots, all named, zero Player issues;106/156 slots identified and159/180 unknown.
Saved client-name-identification-review.json; raw/definition hashes unchanged.
Next: shop item labels and evidence for newer inventory flag positions.


### 2026-10-30: shop reference names and modern equipment flags

ShopPanel shares the loaded client-name catalog and appends a reference-name column.
Client item IDs, prices, observations and generated shop code remain unchanged.
0B39 equipment records now read identification bit0 at offset67, independently of
grade at offset66 and favorite bit2. This supersedes the earlier 0B39 unknown note;
0B38 remains unknown. The official rAthena EQUIPITEM_INFO layout and recorded
0B39 flag values 1/5 were checked. Validation uses six focused player/shop GUI tests.

### 2026-10-30: dialogue item reference labels

Conversation timeline rows for getitem/getitem2/delitem show client ID, quantity
and reference item name. Unknown IDs remain visible. Tooltips retain command
arguments and distinguish reference labels from server DB identity or causality.
No model or renderer changes. Three focused GUI/script-command tests pass.

### 2026-10-30: navigation reference browser and v0.0.5 snapshot

Added static navigation import and a nonmodal, 100-row paged map/quest/NPC/MOB/link/scroll/pick-NPC reference browser.
Map labels prefer existing TXT and fall back to navigation only when absent. Reference numeric columns remain uninterpreted.
Client-name and navigation catalogs reproduce from source. Overlapping map names have zero differences.
Navigation catalog alone allows 4MiB; other configs remain capped at 2MiB. Project save/open/repair pins five catalog hashes.
Focused navigation/name/GUI/project tests: 15 passed. No full suite. Existing v0.0.4 remains frozen.
Version advanced to v0.0.5 for the authorized source snapshot; runtime/Auriga/clean-environment checks remain deferred.

### 2026-10-30: post-v0.0.5 inventory-layout evidence audit

Added tools.audit_inventory to extract bounded, source-linked receive inventory records.
Unknown 0B38 identification offsets remain unknown. Other inventory types and invalid rows are counted separately.
Limits: 32 packet samples per layout, 8 raw records per sample; omitted counts are explicit.
Source and definition hashes are checked before/after replay; protected input/config output is rejected.
Three targeted unit/registration tests passed. Two real logs contain zero 0B38 packets:
0B09 has 251 records; 0B39 has 342 records; invalid inventory packets zero.
Collection checklist I01 documents controlled identification and independent favorite-flag trials.
Saved v0.0.4/v0.0.5 archives remain unchanged; this is subsequent working-tree development.

### 2026-10-30: MARiA-only status-name supplementation

Static AST import of MARiA const.EFST supplements seven missing Lua status-icon IDs.
1034 overlaps agree, zero conflicts. Lua and numeric IDs remain authoritative within their namespace;
conflicting IDs/symbols reject the build rather than silently overwrite. Supplemental provenance is explicit.
Status names: 1325; visual effects: unchanged at 121. No SC conversion or new command generation.
Eleven focused reference/SC/GUI tests passed. Two real logs gain 105 named status notifications;
2360/2566 statuses known, 206 unknown; all 3213 reference notifications decode without errors.
Report: logs/reference-name-maria-supplement-review.json. Frozen v0.0.4/v0.0.5 ZIPs unchanged.

### 2026-10-30: pending capture evidence and dialogue CLI preservation

Rechecked 100/20 conversations in the two current reference logs: zero dialogue issues.
No numeric/text input packets, dialogue position/alignment, progress abort or targeted progress examples.
Menu/next timeout-suspected closes in conversations 6/18 and three 0BA2 packets remain confirmed.
Updated collection priorities; evidence absence is not a parser failure or capture-completeness claim.
Fixed legacy analyze_dialogues export: protected destinations checked before analysis, bounded replay,
source and CLI definition before/after hashes, atomic observation export preserving existing reports on failure.
Three focused tests passed, including equality with one-pass session analysis. Frozen snapshots unchanged.

### 2026-10-30: deferred dialogue JSON views

Added DeferredJsonView: hidden JSON tabs stage a producer, materialize on show or explicit text access,
and reuse unchanged output. Dialogue evidence now serializes once after merge selection instead of twice.
Keys include store identity/revision; selected evidence additionally includes conversation, source refs and merge mode.
Display checks synchronize pending ingestion before materialization to avoid mixing updated dialogue with old timelines.
Also fixed same-revision store replacement reusing an old merge cache. Full-model export is unchanged.
Seven focused GUI tests pass: hidden/reused/visible output, updates before refresh, store replacement,
timeout normalization, progress, quests, status notifications and unanswered close behavior.
Synthetic 5000 observations, 20 hidden updates: JSON matches all 918306 characters; zero hidden serializations, one on access.
Schedule ~0.18ms, first materialization ~86ms, cached access ~3.2ms. No capture/end-to-end speed claim.
Report: logs/deferred-dialogue-json-review.json. Frozen snapshots unchanged.

### 2026-10-31: v0.0.6 source snapshot

Advanced version.py to 0.0.6 / 2026-10-31. Captures post-v0.0.5 GitHub workflow, adoption gates,
timer/VAL/dict layers, identity protection, cart-move attribution guard, touch-trial comparison,
and spawn amount/delay manual-only docs. Frozen v0.0.4/v0.0.5 ZIPs unchanged.
Selected verification: release+catalog+commands+npc+player+presentation+events+mob+display+dialogue+shop (426)
and gui-restoration+gui-display+offline+storage (153); total 579. Not full discover.
Artifacts: dist/KYRiE-v0.0.6-source.zip (+.sha256, verification.json; gitignored).
See docs/releases/v0.0.6.md. Runtime/Npcap/Auriga/clean-environment checks remain deferred.

### 2026-11-01: Snapshot rules require root README version sync

v0.0.6 metadata advanced version.py and release notes, but root README.md stayed on the v0.0.5 banner
(and the frozen ZIP embedded that stale README). Updated docs/releases/README.md checklist,
aligned root README / SNAPSHOT.json to 0.0.6, and gated `build_snapshot` plus `release` tests on
matching `# KYRiE v{version} (Windows)` and the release-note link. Existing v0.0.6 ZIP SHA is unchanged.
Selected: `python -m tools.run_tests release` (4). Not full discover.

### 2026-10-31: Packet structure overlay and field index tags (#35 P0)

Explicit version-1 JSON overlays merge into PacketLength and display for unknown/extended IDs only.
Field `index` tags annotate actor/item/quest/map/class/skill/status/effect from existing catalogs;
wire values and SQLite raw stay unchanged. Session evidence writes PacketOverlay.used.json and
overlay_sha256 beside PacketLength.used.txt. GUI settings expose the overlay path; packet detail
shows `値（注釈）`. Example: config/packet_overlay.example.json. No unknown-ID resync.
Selected: display + test_packet_overlay + session_log + gui-display + gui-capture (90). Not full discover.

### 2026-10-31: Packet-detail overlay editor (#35 P1)

「パケット詳細」から選択パケットの長さ・フィールド・indexを編集し、オーバーレイJSONへ
upsert保存→表示再解析。長さ確認は定義長と観測raw・フィールド被覆のみ（再同期なし）。
Selected: display + gui-display（overlay editor含む）. Not full discover.

### 2026-10-31: Same-ID instance diff and overlay export (#35 P2)

同一PacketIDの2インスタンスraw差分（フィールド注釈付き）と、確定オーバーレイの
PacketLength／display断片エクスポート（本体定義は非上書き）。
Selected: display + gui-display. Not full discover.

### 2026-11-02: v0.0.7 source snapshot

Advanced version.py to 0.0.7 / 2026-11-02. Captures post-v0.0.6 shop/barter/callshop,
display_only observe paths, MapTypeProperty, history eviction, and docs organize (#81/#82).
Frozen v0.0.4/v0.0.5/v0.0.6 ZIPs unchanged.
Selected verification: release+catalog+commands+npc+player+presentation+events+mob+display+dialogue+shop (470)
and gui-restoration+gui-display+offline+storage (165); total 635. Not full discover.
Artifacts: dist/KYRiE-v0.0.7-source.zip (+.sha256, verification.json; gitignored).
See docs/releases/v0.0.7.md. Runtime/Npcap/Auriga/clean-environment checks remain deferred.

### 2026-11-02: O2 presentation JSON differential keys and eviction profile (#85)

Presentations DeferredJsonView keys track presentation/quest/progress/script_command
collection growth instead of DialogueStore.revision, so mes/menu-only updates skip rematerialize.
Added tools.profile_memory_eviction for synthetic DB-confirmed eviction counts.
Selected: dialogue + gui-restoration (presentation deferred tests). Not full discover.

### 2026-11-02: O2 merge worker and eviction limit evidence (#85)

Keep MEMORY_EVENT_LIMIT=50000. Synthetic eviction profile (confirm_db):
limit50/packets80 retain50 origin30; limit500/600 retain500; limit2000/2100 retain2000;
DB-failed path never evicts. Dialogue merge for >=64 sessions runs in MergeWorker;
stale key results are discarded; save_merged forces sync. Selected gui-restoration+dialogue.

### 2026-11-03: v0.0.8 source snapshot

Advanced version.py to 0.0.8 / 2026-11-03. Captures post-v0.0.7 timer boundaries, quest chronology,
MOB editor evidence, ActorID/offscreen CI fixes, and shared async shop/spawn export (#84–#120).
Frozen v0.0.4/v0.0.5/v0.0.6/v0.0.7 ZIPs unchanged.
Selected verification: release+catalog+commands+npc+player+presentation+events+mob+display+dialogue+shop (511)
and gui-restoration+gui-display+offline+storage (170); total 681. Not full discover.
Artifacts: dist/KYRiE-v0.0.8-source.zip (+.sha256, verification.json; gitignored).
See docs/releases/v0.0.8.md. Runtime/Npcap/Auriga/clean-environment checks remain deferred.

### 2026-11-04: v0.0.9 source snapshot

Advanced version.py to 0.0.9 / 2026-11-04. Captures post-v0.0.8 large-capture budgets (#122),
08E2 navigation observe and cloak/colocated notes (#123–#125), actor comment enrichment,
ignorepacket per-ID flags, showeventflag, and update_status log suppress (#126).
Frozen v0.0.4/v0.0.5/v0.0.6/v0.0.7/v0.0.8 ZIPs unchanged.
Selected verification: release+catalog+commands+npc+player+presentation+events+mob+display+dialogue+shop (521)
and gui-restoration+gui-display+offline+storage (173); total 694. Not full discover.
Artifacts: dist/KYRiE-v0.0.9-source.zip (+.sha256, verification.json; gitignored).
See docs/releases/v0.0.9.md. Runtime/Npcap/Auriga/clean-environment checks remain deferred.
