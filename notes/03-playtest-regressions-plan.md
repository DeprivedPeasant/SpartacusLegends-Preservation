# Playtest regression and missing-persistence plan

**Created:** 2026-08-11  
**Status:** ready for handoff  
**Baseline source:** `main` at `3898b4c` (`Fix post-fight recruit store refresh`)  
**Target build:** NPUB30746 01.00 under RPCS3  

## Objective

Reproduce, isolate, and fix five playtest findings without regressing the
working login, economy, recruit receipt, post-fight store-refresh fix, or PINE
roster restoration:

1. the gladiator recruitment shop can still enter refresh-loop/broken-refresh
   states through sequences other than the already-fixed post-fight path;
2. purchased gladiator roster slots are not preserved across cold boots;
3. defeated Primus progression is not preserved across cold boots;
4. combat death leaves the game in an infinite waiting state, likely at an
   unimplemented asynchronous completion boundary;
5. the recruit pool appears limited to Sword-and-Shield gladiators, and its
   style, quality, and campaign/fame gating is not yet understood.

Treat these as five independent investigations. Change one server response,
client patch, or restored memory field per experiment.

## Current implementation baseline

- `tools/prudp_server.py` handles Monetization(102):
  - method 3: inventory/economy query;
  - method 6: income deposit;
  - method 7: ordinary item purchase and recruit-pool refresh command 99999;
  - method 13: gladiator recruitment receipt.
- Item ID `99999` is a command, not inventory. The server currently debits the
  supplied non-negative gold/silver cost, returns a method-7 receipt with
  quantity zero, and filters old sentinel pollution from `profile.json`.
- The compatibility patch at `0x00174A9C` forces completion of the known
  recruit-pool refresh callback. It fixed the reproduced post-fight loop, but
  may be too narrow for other refresh entry points or may hide distinct
  completion semantics.
- `tools/roster_bridge.py` schema 2 stores the active owned-roster count, each
  active `0x158` gladiator record, each corresponding `0x40` backing block,
  and purchased roster-slot capacity as `unlocked_slots`. Legacy schema-1
  files migrate with `max(2, owned_count)` so no occupied slot is locked out.
- Currency, fame, general level, and previously tested fight/campaign state
  are restored through the existing profile/economy work. Primus completion
  must be tested separately; do not infer it from fame or map access.
- The historical guides describe recruit cards as style-specific gladiators,
  rather than loadouts that can be freely converted. They also associate
  recruit colour/cost with fame and state that defeated Legends can later
  appear in the recruit pool. This is behavioral context only: it does not
  identify the client field or prove exactly when a candidate should appear.
- Optional one-hit/invulnerability debug patch is available and should be used
  to shorten repeated Primus and autosave tests.

## Guardrails and evidence requirements

- Preserve the user's current `data/profile.json`, `data/roster.json`, and
  RPCS3 `PRG-DATA` before the first mutation test. Record SHA-256 hashes.
- Verify the exact executable/server build at the start of every report. The
  package scripts currently name v0.3.2, while local Git tags are incomplete;
  use commit/build identity rather than trusting a displayed release label.
- Keep RPCS3 IPC enabled for bridge tests. Use `--no-roster-bridge` only for a
  bounded manual PINE capture, and never run two PINE owners simultaneously.
- Distinguish a warm UI re-entry, game reboot, RPCS3 process restart, and true
  cold boot. Persistence claims require a complete RPCS3 process restart.
- Retain `logs/prudp.log`, `logs/roster_bridge.log`, before/after JSON, relevant
  RPCS3 logs, and screenshots for every decisive test.
- Do not promote a forced-success patch until the underlying request, callback,
  state transition, and side effects are understood.
- Existing unrelated working-tree changes belong to the patch-installer work:
  `.gitignore`, `README.md`, `packaging/build_release.ps1`,
  `tools/patch_installer.py`, and `tests/test_patch_installer.py`. Preserve them.

## Track A — Recruitment-shop refresh regressions

### A1. Establish the paid-refresh contract

#### Verified result (2026-08-11)

Track A1 is reproduced and fixed against NPUB30746 01.00. A manual refresh
sends Monetization method 7 with `item_id=99999`, `gold_cost=5`, and
`silver_cost=-1`. The working method-7 receipt returns updated balances and a
transaction object containing:

- item ID `99999` (the client classifies this as category 9, remainder 9999);
- a packed UTC Quazal date/time with zero-based month and day fields;
- quantity `1`, acknowledging the refresh without adding 99999 to inventory.

The original zero date/time decoded as an invalid pre-epoch value. The client
completed the network callback but immediately considered the generated pool
expired, producing unique zero-cost refresh calls indefinitely. Returning ID
9999 suppressed that retry but routed the receipt through category 0 and left
the `recruitReload` UI animation stuck. The verified contract produces one
five-gold debit, one pool mutation, no follow-up method-7 calls, an interactive
shop, and a roughly 30-minute countdown.

Successful-run evidence is retained under
`captures/track-a1-paid-refresh-success-20260811-230516`.

The recruitment shop offers a manual refresh for 5 gold. The strongest current
hypothesis is that it sends Monetization method 7 with:

```text
item_id = 99999
gold_cost = 5
silver_cost = -1
```

Do not assume this until captured.

Controlled test:

1. Start with at least 10 gold and record exact balances.
2. Enter Recruit and capture the six candidate records/product IDs before the
   purchase. Record the visible timer and candidate names/styles.
3. Purchase exactly one 5-gold refresh.
4. Capture the complete RMC request/response, including call ID, raw parameter
   bytes, decoded costs, response body, and subsequent calls.
5. Verify all expected effects independently:
   - gold decreases by exactly 5 once;
   - silver does not change;
   - 99999 is absent from `owned_items` and method-3 inventory replies;
   - the candidate pool changes exactly once;
   - the UI becomes interactive and does not repeatedly refresh;
   - leaving and re-entering Recruit preserves the refreshed pool for the
     intended timer/session behavior.
6. Cold boot only after the same-session behavior is understood. Candidate
   persistence is not currently a requirement unless retail behavior proves it.

### A2. Build a refresh reproduction matrix

Test each path independently from a clean process start. For every row, record
whether 99999 is sent, its costs, callback timing, number of pool mutations,
and whether the UI loops or locks:

| Path | Expected distinguishing feature |
|---|---|
| First Recruit entry after login | initial pool, no purchase |
| Natural timer expiry while shop remains open | timer-driven refresh |
| Leave and re-enter after timer expiry | deferred timer refresh |
| Manual 5-gold refresh | paid method-7 command |
| Free post-fight refresh | known zero-cost path |
| Recruit purchase via method 13 | refresh following successful hire |
| Failed/insufficient-funds refresh | must not mutate pool or debit |
| Failed/insufficient-funds recruit | must return to usable shop |
| Rapid re-entry/back navigation | callback/re-entry race |

Progression-triggered refreshes must be added to this matrix. Playtest evidence
indicates that unlocking a new weapon/fighting style invalidates the current
pool so newly eligible gladiator styles can appear. This likely explains user
reports of an apparently spontaneous refresh bug during progression: it uses
the same zero-cost 99999 transaction path that the malformed timestamp caused
to repeat.

Ask affected users for their exact navigation sequence and both logs. “Refresh
bug” is not a sufficient reproduction description because several paths share
the same screen but may use different callbacks.

### A3. Diagnose before changing the patch

If a loop occurs:

1. Determine whether repeated RMC calls are being sent or whether only the UI
   animation repeats locally.
2. Compare the failing callback and status object with the fixed post-fight
   path at `0x00174A9C`.
3. Identify whether the server receipt is wrong, the callback is never marked
   complete, completion is consumed by the wrong screen instance, or the pool
   refresh event is emitted repeatedly.
4. Prefer a correct response/callback transition. Add another patch only if a
   specific RPCS3/client incompatibility prevents the retail transition.

### A4. Required automated tests

Extend `tests/test_economy_store.py` to cover:

- paid refresh deducts 5 gold exactly once;
- insufficient gold behavior once the retail result is known;
- retry/replayed call IDs do not double-debit if retransmission is possible;
- free and paid refreshes never create owned item 99999;
- receipt quantity and balances match the captured retail parser contract.

Add patch-level coverage only for each address that remains necessary.

## Track B — Purchased roster-slot persistence

### B1. Reproduce and separate slot ownership from roster occupancy

Important observed behavior: after a cold boot, a previously purchased slot is
shown as locked, but a gladiator already stored in that slot is still restored.
This proves slot ownership/capacity is separate from the active gladiator
records currently preserved by the bridge.

Use this fixture:

1. Start with one starting gladiator and the initial free empty slot.
2. Record which slots are open, locked, empty, or occupied, plus silver/gold.
3. Purchase exactly one additional roster slot. Capture every RMC call and the
   exact currency deduction. Historical notes say later slots cost 3,500
   silver; verify the displayed and transmitted cost rather than assuming it.
4. Recruit a gladiator into the newly purchased slot.
5. Wait for autosaves and two stable roster-bridge captures.
6. Fully close RPCS3 and cold boot.
7. Record both facts separately:
   - whether the gladiator record remains present;
   - whether the UI still regards that slot as purchased/unlocked.

### B2. Identify the slot-unlock state

The roster bridge must not guess capacity from `owned_count`. Use bounded
before/after captures around one slot purchase:

- diff the roster manager near `0x019CE3B0`, including fields after the owned
  arrays and counters;
- diff the account/profile structure already associated with section 1;
- compare `PRG-DATA` before purchase, after autosave, and after cold boot;
- inspect the RMC request that performs the slot purchase and any method-3
  inventory IDs returned afterward;
- search for a count, bitmask, per-slot flags, or product IDs that change once
  and survive same-session UI re-entry.

Run a second purchase if feasible. A field changing `2 -> 3 -> 4` is stronger
evidence of capacity than a one-off boolean. Confirm locked/empty/occupied UI
against the candidate field before writing it.

### B3. Persistence design

Once identified, choose the narrowest owner:

- If the unlock is an ordinary server-owned product, persist it through
  `profile.json`/method 3 and let the client apply it.
- If it is a stable live field not reconstructed from server inventory, extend
  `roster.json` to schema 2 with an explicit `unlocked_slots` value or slot
  bitmask. Restore it after the default manager is initialized and before
  publishing/restoring roster occupancy.
- If it is already serialized in `PRG-DATA` but ignored by the current forced
  profile branch, correct the local apply path instead of duplicating it.

Do not infer unlocked capacity from the highest occupied slot. Empty purchased
slots must remain purchased, and legacy schema-1 files need a safe migration
rule that never locks out an existing stored gladiator.

### B3.1 Verified slot transaction and persistence fix (2026-08-12)

The captured purchase used Monetization method 7, item ID `80002`, gold cost
`-1`, and silver cost `3360` (the client's discounted price from a 3,500 base).
The third slot unlocked immediately. Correcting the normal purchase receipt to
return a nonzero Quazal timestamp and quantity one made the receipt retail-like,
but did not preserve the unlock across a cold boot.

Neither the bounded roster-manager capture nor `PRG-DATA` identified a durable
capacity change, and the cold-boot client did not request Monetization method 3
inventory with which the server could replay the owned slot products. A wider
static-memory before/after capture identified `0x008FF448` changing from `1`
to `2`: the stored value is the highest unlocked zero-based slot index, so
these values expose two and three usable slots respectively.

Roster schema 2 therefore stores the human-readable capacity as
`unlocked_slots`. The bridge validates it against the owned count and the
eight-slot maximum, then restores `unlocked_slots - 1` to `0x008FF448` before
publishing the roster backing blocks, records, and active count. Schema-1
files migrate to `max(2, owned_count)`. A cold boot with an empty purchased
third slot was manually verified: the slot remained unlocked without another
purchase.

### B4. Acceptance matrix

- purchase a slot and cold boot while it is empty;
- purchase a slot, fill it, and cold boot;
- remove/lose the gladiator and verify the purchased slot remains;
- restore a schema-1 roster with two or more gladiators;
- unlock multiple slots across separate sessions;
- verify balances are debited once and no slot product pollutes equipment;
- verify all eight maximum slots remain bounded by bridge safety checks.

## Track C — Primus completion persistence

### C1. Define correct historical behavior

Use the GameFAQs guides as behavioral references, not binary-format evidence:

- Berserker's full PS3 guide:
  https://gamefaqs.gamespot.com/ps3/676739-spartacus-legends/faqs/67272
- SeverenceUFB's guide:
  https://gamefaqs.gamespot.com/ps3/676739-spartacus-legends/faqs/67328

The guides establish that Primus battles are ordered single-player progression
missions: winning removes that Primus battle, unlocks the next link, and after
all Primus battles in a district the district boss becomes available. Some
later battles require particular fighting styles. After completing the full
game, Primus events return in a harder second playthrough. Preserve these
semantics; a blanket “all events unlocked” patch would be inaccurate.

### C2. Minimal controlled reproduction

Choose the earliest currently available Primus whose successor is clearly
documented. Record its district, opponent name, required style, reward perk,
and the before-state of every event in that district.

1. Hash and back up `PRG-DATA`, `profile.json`, and `roster.json`.
2. Capture a screenshot of the district/event chain before the fight.
3. Enable the optional one-hit debug patch and defeat exactly that Primus.
4. Record reward, perk, fame, currency, newly unlocked event, and whether the
   defeated event disappears.
5. Wait for every autosave to finish. Capture hashes/byte diffs and the RMC
   timeline from fight completion through return to the map.
6. Re-enter the district in the same process to prove the live transition.
7. Fully close RPCS3, cold boot, and record each field independently:
   - defeated Primus hidden/completed;
   - successor unlocked;
   - perk retained on the relevant gladiator;
   - district boss state unchanged unless appropriate;
   - fame/currency/general level retained.

This distinguishes Primus-chain loss from a general profile failure.

### C3. Locate the authoritative state

Compare three likely owners:

1. **Local section-1 profile:** inspect the already-restored mission/fight
   fields and determine whether the current patch applies only a coarse
   campaign value while omitting per-event completion.
2. **Local section 3:** inspect the 56,000-byte loaded section and its handler
   around the controlled Primus delta. Do not assume section 3 is roster-only.
3. **Server economy/inventory:** check whether the victory sends only method-6
   income or also an event/progression RMC. Existing evidence says ordinary
   autosave often sends no separate progression request, but Primus victory
   must be captured explicitly.

Use a second Primus after the first field is identified. Ordered changes across
two known event IDs should reveal whether the representation is a bitset,
state array, highest-completed index, or district-specific structure.

### C4. Fix hierarchy

Prefer, in order:

1. apply the client's existing locally serialized Primus state correctly;
2. persist and restore the exact stable live/local fields through a bounded
   companion schema if RPCS3/client behavior prevents the retail apply path;
3. create a private server-side progression representation only if no native
   local representation exists.

Do not patch individual Primus events to “completed.” The solution must support
ordered chains, district bosses, style requirements, perks, and second-cycle
progression.

### C5. Acceptance matrix

- one Primus survives a cold boot and remains unavailable for replay;
- its successor remains unlocked;
- two sequential Primus wins survive separate cold boots;
- district boss unlock occurs only after the documented final prerequisite;
- ordinary arena fights/cooldowns are unaffected;
- fame, balances, roster, equipment, perks, and slot ownership all coexist;
- second-playthrough behavior is not prematurely activated.

## Track D — Gladiator death completion and roster deletion

### D1. Controlled death capture

Combat death is destructive state, so use a disposable recruited gladiator in
a known slot. Back up `profile.json`, `roster.json`, and `PRG-DATA`, record
the full roster layout, and do not use the only starter gladiator.

1. Start the normal source server with the roster bridge enabled and ensure
   IPC is healthy before entering combat.
2. Record the gladiator's slot, name, record bytes, equipment, balances, and
   roster count. Keep the ordinary one-hit patch disabled.
3. Arrange one intentional death using the least ambiguous available route.
   Record fight type, difficulty/lethality settings, opponent, and the exact
   moment the UI changes to its waiting state.
4. Preserve the complete `prudp.log`, `roster_bridge.log`, and RPCS3 log from
   at least 30 seconds before death until the loop is established. Capture
   PINE snapshots immediately before death and while the loop is active.
5. If an RMC arrives, record protocol, method, call ID, decoded parameters,
   and the client-side return/callback path before replying. If no RMC arrives,
   inspect the live call stack and local completion flag: the spinner may be a
   local callback/state-machine failure rather than an omitted server method.
6. After the transaction is understood, allow exactly one candidate response
   or local completion change, then verify the roster UI in the same process
   and after a full cold boot.

Never globally pause all RPCS3 threads while relying on PINE; it prevents IPC
from proving whether the bridge observed the deletion. A debugger stop on the
relevant PPU thread is sufficient for a bounded capture.

### D2. Determine the correct persistence semantics

Do not assume a combat death is identical to manually deleting a gladiator.
Establish the retail-facing result from the client transition and any request:

- is the gladiator permanently removed, merely marked unavailable, or offered
  a revive/recovery path;
- does the slot become empty while remaining unlocked;
- are equipped items returned, retained, or lost;
- does the roster count/active-slot ordering compact;
- does the roster bridge take a stable post-death snapshot or accidentally
  restore the pre-death roster on the next launch.

The bridge now owns both active records and purchased capacity, so Track D must
be regression-tested together with Track B. Do not introduce automatic
resurrection or remove a record in `roster.json` until the actual completion
semantics are captured.

### D2.1 Verified death/revival transaction (2026-08-11)

The controlled lethal-fight traces established two native outcomes: the first
death is revived for free, while a later unpaid death deletes the gladiator.
The client first marks its local gladiator state and sends these server calls:

1. Monetization `102/m12`, containing only the gladiator ID: a void death
   notification. The server must answer it with an empty RMC body.
2. Monetization `102/m6`, containing the normal fight-income deltas: return
   the updated `<u32 gold, u32 silver>` pair.
3. Monetization `102/m11`, containing `<u32 gladiator_id, i32 gold_cost,
   i32 silver_cost>`: return that same balance pair. The observed first-death
   request was `(1006, 0, -1)`, so it is a no-cost settlement.

The prior infinite spinner was two sequential omissions: first the missing
`m12` response, then (after that was fixed) the missing `m11` balance-pair
response. With both handlers present, the user confirmed the game reaches its
normal outcome screen. The first gladiator death is revived for free; later
deaths are expected to offer silver-or-gold prevention; an unpaid later death
permanently deletes the gladiator. This was verified in a second controlled
unpaid death: the live owned count fell from 2 to 1 and remained there. Its
wire path is `m12` (void death notification), then `m6` (fight income), with
no `m11` request; after the income response the client emits only keepalive
pings. The user confirmed this returns to the normal **map** screen, not a
spinner. Entering Ludus afterward caused a guest access violation in the
client at `0x00141fa8`, before any new server request was made. An experimental
global string-pointer mask was rejected: it produced the same routine's access
violation during startup on an otherwise ordinary pointer. In particular, its
write at `0x00141fcc` replaced the routine's required `mr r30,r3` instruction.
It has been removed from both the release and active RPCS3 patch sets. Do not
add another client patch until the write that corrupts or invalidates the Ludus
record is found.

A subsequent control test killed the only owned gladiator in the first Ludus
slot. The same `m12` then `m6` exchange completed, the owned count reached zero,
and Ludus opened normally with two empty recruit slots. The inactive record's
old bytes remained allocated but were correctly ignored at count zero. The
failure is therefore not a general unpaid-death or server-response failure: the
known crash requires at least one surviving active gladiator after deletion.
Compare the `2 -> 1` survivor case against this successful `1 -> 0` control,
including both deletion of the last active record and deletion that forces the
last record to be compacted into an earlier slot.

The immediate `2 -> 1` control also succeeded: two fresh recruits (IDs 1006
and 1007) occupied the first two records, ID 1007 died in the second slot, and
Ludus correctly displayed surviving ID 1006. Its active name-backing pointer
was the expected `0x019d2870`; the inactive second record remained allocated
but was outside the owned count. This disproves a general last-slot deletion or
`2 -> 1` survivor-rendering defect. In the earlier crash, the equivalent first
record contained `0xb09d2870`. Focus next on how that particular long-lived
starter record acquired the bad first word, including prior restore/history,
rather than on the identical `m12`/`m6` responses or roster compaction itself.

Accordingly, the server must preserve the client-owned record and
debit only non-negative m11 cost fields; it must neither delete nor
automatically resurrect the gladiator. Capture the paid prevention outcome
before defining bridge deletion behavior.

### D3. Acceptance matrix

- a deliberate death reaches the native revive/prevention result instead of
  an infinite wait;
- the correct roster result survives same-session re-entry and a cold boot;
- the affected slot's purchased/unlocked status is preserved;
- no unrelated gladiator, equipment record, balance, or campaign progress is
  changed;
- repeated boot does not cause the bridge to reintroduce the lost gladiator.

## Track E — Recruit-pool styles, quality, and progression gates

### E1. Establish what the pool is expected to supply

The GameFAQs full guide describes each recruit as having an exclusive fighting
style, with the card icon identifying that style; it also links better recruit
availability/cost to fame and says defeated Legends can appear randomly in the
pool. Historical Primus chains impose style requirements. Therefore a healthy
preservation implementation must eventually expose the required styles, but it
must not invent candidates or remove documented campaign/fame gates merely to
fill the initial pool.

### E2. Build a candidate-pool evidence table

For every observed pool generation, record:

- test identity: profile backup/hash, fame/general level, district/Primus
  completions, date/timer state, and cold-boot versus warm re-entry;
- refresh trigger: first entry, natural expiry, paid 5-gold refresh,
  post-fight refresh, or post-recruit refresh;
- every displayed candidate: position, product/candidate ID, name, colour,
  fighting-style icon, visible price/currency, lock condition, and whether it
  can actually be recruited;
- complete RMC/PINE timeline and a recruit-screen screenshot.

Sample at least 20 independent pool generations across the first available
states before declaring a style unavailable. Repeated paid refreshes belong in
Track A's transaction validation: every sample must debit exactly once and
complete cleanly.

### E3. Separate static client generation from server-provided state

Existing evidence suggests recruitment is finalized by Monetization method 13
and the server does not author the whole candidate list. Test that conclusion:

Verified Track-A evidence now also shows that a healthy manual refresh on a
progressed account generates multiple fighting styles locally. The leading
hypothesis is that weapon/style unlock progression invalidates the pool and
triggers a zero-cost 99999 refresh so newly eligible style categories enter the
client generator. Capture the next natural unlock boundary to connect the
specific progression field, automatic request, and resulting candidate styles.

1. compare candidate records in the roster manager before and after each pool
   mutation, including the observed `0x158` record stride and nearby counts;
2. inspect all RMC around pool creation/refresh. If no candidate payload is
   sent, trace the client generator and its inputs rather than fabricating a
   server response;
3. vary one native prerequisite at a time: fame level, documented Primus
   completion, district unlock, and timer/refresh trigger;
4. compare a clean baseline profile with the retained progression profile to
   identify stale local state or a restoration omission.

If a pool gate is represented by a missing client/profile field, restore that
field through the narrowest correct owner. If the pool is intentionally random,
retain its native selection behavior and only ensure the completion callback
and prerequisite state are correct.

### E4. Acceptance matrix

- initial recruit pool remains valid for a new tutorial-complete profile;
- manual and automatic refreshes produce valid, non-looping pools;
- at the historically appropriate fame/progression point, candidates include
  the styles needed for the next documented Primus paths;
- prices, colour/quality, locks, and recruit receipts remain internally
  consistent;
- no style is made permanently unavailable by roster restoration, the refresh
  fix, or a fabricated server inventory response;
- a defeated Legend's later pool appearance, if encountered, does not corrupt
  roster or campaign state.

## Recommended execution order

1. **Paid 5-gold refresh:** quickest wire-level test and likely exercises the
   existing 99999 code directly.
2. **Pool sampling during that test:** record styles and candidate IDs on every
   clean refresh; it provides Track E evidence without any extra mutation.
3. **Deliberate disposable-gladiator death capture:** establish whether the
   waiting loop is an RMC boundary or a local state-machine failure before any
   roster-delete behavior is implemented.
4. **Slot purchase capture:** needed before recruiting further test fixtures;
   likely a small extension to the current profile or bridge schema.
5. **Primus controlled delta:** use the one-hit patch after roster capacity is
   reliable, because later historical progression requires multiple styles.
6. Run a combined cold-boot regression with paid refresh, three gladiators,
   purchased empty capacity, distinctive equipment, one intentionally removed
   gladiator where supported, and two defeated Primus battles.

## Handoff checklist

At the start of the next session:

1. Read this file, then the final experiment sections of
   `notes/01-luna-roster-storage-plan.md` and the bootstrap verdict in
   `notes/02-original-profile-sync-plan.md`.
2. Inspect `git status`; preserve the existing patch-installer changes.
3. Back up the three user-state files before launching RPCS3.
4. Start the source server with normal roster bridge ownership and confirm its
   commit/build in the logs.
5. Begin only Track A1: capture one manual 5-gold refresh from a clean process.

The first next-session success signal is not “the shop looked okay.” It is a
complete paid-refresh transaction showing exact request parameters, one debit,
one pool mutation, no sentinel inventory entry, and a stable interactive UI.

### C-FINDING: boss/Primus progress is SAVED but not APPLIED on boot (2026-08-12)

Controlled early-Primus win, one-hit debug, autosave allowed to finish, then a
full RPCS3 cold boot. Result: **chain reverted in-game, but the local save is
intact and durable across the boot.**

Evidence:
- Baseline PRG-DATA `dff367f3...` (pre-fight, backups/trackC-pre-primus-20260812-150852).
- Post-fight PRG-DATA `70348005...` (backups/trackC-post-primus-20260812-152029),
  44 bytes changed by the autosave.
- After cold boot + login + return to menu, PRG-DATA is **byte-for-byte identical
  to the post-fight snapshot** (0 changed bytes, same SHA `70348005...`, mtime
  unchanged 15:18:12 -> the boot session did not rewrite it). The chain still
  reverted in the UI. => the loss is in LOAD/APPLY, not SAVE.
- Victory wire trace (logs/prudp.log after marker line 45785): the ONLY
  game-service RMC was `Monetization(102) m6` income (+439 silver). No distinct
  progression/event RMC. Boss completion is NOT server-authoritative on our wire.

Where the fight wrote (section map: sec0@0x0, sec1@0xB4, sec3@0xCB64):
- Section 1: economy silver@0xB914 updated (expected). NEW nonzero record at
  **0xCA67 = `3F 00000001 7D0165A1`** (was all-zero) — mission/completion entry +
  packed-timestamp-looking tail. Near the END of section 1, well after the
  economy/fame block that already restores.
- Section 3: NEW writes at 0xCBB5-0xCBB7 and 0xD698 (previously this section was
  observed all-zero in a roster-only save; a Primus win DOES write it).

Interpretation: economy/fame restore because they sit in the 0x1238 profile
sub-block that the 0x00068504 patch forces to apply. The campaign/mission
completion record (0xCA67 in section 1, and/or the section-3 writes) is loaded
from disk but NOT re-applied to the live campaign manager — the game
re-initializes the Primus chain to its default instead. This is the section-1
"applied-but-partial" / section-3 "loaded-but-never-applied" gap, now for
mission data (binary has `m_missionSaveDataUserContent`).

NEXT (static): map the campaign/mission load+apply path. Determine whether the
completion state is (a) section 1 outside the applied 0x1238 block, or (b)
section 3's unapplied buffer 0x329295E0. Then fix the narrowest apply gate,
analogous to 0x00068504. Do NOT patch individual events to "completed".

### C-STATIC: section-1 apply only pushes 3 scalars; campaign data loaded-not-applied (2026-08-12)

Decompiled the section-1 deserializer `FUN_00068450` (notes/save_load_branch_disasm.txt,
save_section_dispatch.txt). Structure:
- `FUN_00748814(handler+8, *src, 0xCA88)` copies the ENTIRE section-1 payload
  (incl. the 0xCA67 completion record) into the resident handler buffer. So the
  saved campaign data DOES reach memory on load.
- 0x15(21)-iteration loop: `FUN_00068060(i)` (reads float @buf+0xac6c+i*4) then
  `FUN_0006a1dc(i)`. Looks like a per-index (district/arena?) applier. PRIME
  SUSPECT for the campaign apply that is missing/misrouted.
- Validity gate `FUN_00067f0c` (reads flag @buf[0xca80]); branch @0x00068504
  (patched 409E00BC->480000BC forces the ELSE/apply-saved branch). The applied
  ELSE branch pushes only THREE scalar fields to live state:
  `FUN_00127fa4(*puVar2)`, `FUN_001dda90(puVar2[1])`, `FUN_00139fa4(puVar2[2])`
  = the economy/fame/level triple. THAT IS ALL it applies. The campaign/mission
  completion in the payload tail is never pushed to the live campaign manager.

So the fix is NOT in the 3-field profile apply. Targets:
1. `FUN_0006a1dc` (the 21-loop applier) — does it read the saved buffer or a
   default template? Does it cover Primus/mission completion? Find the live
   campaign/mission manager it writes.
2. The default-campaign GENERATOR that produces the reverted chain, and its
   GUARD (choose "apply saved" vs "generate default") — the 0x00068504 analogue.
3. Map file offset 0xCA67 -> resident buffer base (PTR_DAT_008b9024) offset, to
   pinpoint the completion record's in-memory location for a live PINE readback.
Do NOT patch individual events to completed; must support ordered chains/bosses.

### C-STATIC 2: campaign apply function + live managers mapped (2026-08-12)

`FUN_001e08b4(applyCtx, handler+0xacdc)` IS the campaign/mission completion
applier, called UNCONDITIONALLY in FUN_00068450 during section-1 load (before
the validity gate). It reads a saved flag array from the resident buffer at
+0xacdc (payload offset ~0xACD4; file ~0xAD94 — the Primus fight DID write bytes
here: 0xAD36-0xAD87) and, per manager, sets a completion flag=1 wherever the
saved byte is nonzero. Each block is gated by `if (manager != 0)`.

Live campaign managers (decompiled getters, notes/campaign_managers.txt):
| # | static slot   | shape   | stride | flag off | flag-array off in save buf |
|---|---------------|---------|--------|----------|-----------------------------|
| 1 | 0x008C1B6C    | 512     | 0x158  | +0x154   | +0xacdc +[0..0x1ff]         |
| 2 | 0x008C1724    | 2x128   | 0x110  | +0x104   | +0xacdc +0x200 / +0x280     |
| 3 | 0x008C19A8    | 128     | 0x140  | +0x134   | +0xacdc +0x300              |
| 4 | 0x008C1B00    | 128     | 0x13c  | +0x130   | +0xacdc +0x380              |
| 5 | 0x008C1A7C    | 6x64    | 0x164  | (consumer FUN_001e3800) | +0xacdc +0x400 +i*0x40+j |

Manager 5 = 6 districts x 64 events = prime Primus/mission completion grid.
Accessors: m1 FUN_001e697c, m2 FUN_001d3cb8/FUN_001d3a68, m3 FUN_001dd168,
m4 FUN_001e52dc, m5 FUN_001e2b4c(mgr,i,j) -> entry+j*0x164; consumer FUN_001e3800
re-invokes FUN_001e2510 apply.

ROOT-CAUSE HYPOTHESIS (needs one live confirmation): the apply runs during
section-1 load but the manager getters return 0 (collections not yet built) so
every block is skipped; the game then default-generates the campaign, so the
saved completion never reaches the live grid. Alt: apply runs but later default
generation clobbers it. Alt: completion is really in the 0xCA67 tail record, not
the +0xacdc flag array (the fight wrote both regions).

FIX STRATEGIES:
(A) Client patch to make FUN_001e08b4's apply effective (re-run after managers
    init, or move/gate). Needs live root-cause first; risk of the section-1
    ordering being load-bearing elsewhere.
(B) PINE companion (like roster_bridge): post-login state 26 (managers built),
    read saved completion flags from resident buffer OR snapshot live manager
    flags after fights, and write them into managers 1-5 at the offsets above.
    Proven, low-risk, no client patch. RECOMMENDED, consistent with the shipped
    roster/slot-unlock fixes.

NEXT LIVE DIAGNOSTIC (decides A vs B and confirms cause): with the game at the
menu post-boot (reverted chain), read via PINE:
  - deref each manager slot (0x008C1B6C etc.) -> nonzero => managers ARE built
    at menu (so a companion CAN write them);
  - manager 5 grid entries' completion state for the just-defeated Primus ==
    not-complete (confirms apply gap);
  - the resident save buffer flag bytes (base *(0x008b9024)+0xacdc region) ==
    set (confirms save has the data, apply just didn't land it).
Requires releasing PINE from the roster bridge (run server --no-roster-bridge)
or an RPCS3 breakpoint on 0x001e08b4 reading the five manager registers.

### C-CONFIRMED: gap is manager 5 (Primus grid) only; live-verified (2026-08-12)

Live PINE at the menu (server run with --no-roster-bridge to free IPC),
post-cold-boot reverted state:
- All 5 manager pointer slots deref non-null (managers built at menu):
  m1 0x008C1B6C->0x019D68B0, m2 0x008C1724->0x019CE05C, m3 0x008C19A8->0x019D39E4,
  m4 0x008C1B00->0x019D6740, m5 0x008C1A7C->0x019D4D64. Resident buf 0x008B9024->
  0x008F28F8 (matches handler).
- Resident save buffer holds a POPULATED completion flag array at handler+0xacdc
  (0x008FD5D4, many 0x01). So saved completion IS loaded into memory.
- Managers 1-4 DID apply: m2 live entries[0],[1] at +0x104 == 1 (matching saved
  flags at 0x008FD7D4). So the boot apply works for simple-flag managers.
- Manager 5 grid IS populated at menu: entry-array ptrs mgr5+0x48[0..5] all
  non-null (0x3182F230 ...). But the Primus chain still reverted.

Manager-5 completion mechanism (notes/m5_completion.txt):
- FUN_001e2578(mgr5, d, e) = mgr5 + 0xc4 + (d*0x40+e)*0x10  (d<6, e<0x40): the
  completion CELL address. Completion table = mgr5+0xc4, 6*64 cells * 0x10 B.
- FUN_001e25b4 writes cell fields {+0:int, +4:float, +8:int, +c:int} and sets
  DIRTY flag mgr5+0x18c8 = 1 (only if values differ).
- Apply path FUN_001e3800(entry): cell = lookup(entry+0x15c=d, entry+0x18=e);
  FUN_001e25b4(mgr5, d, e, local_20). NB the game passes an UNINITIALIZED
  local_20 here -> completion is marked by the ACT of writing + dirty flag, cell
  data values are not load-bearing for the mark.
- FUN_001e08b4's m5 loop reads grid entry via FUN_001e2b4c = *(mgr5+0x48+i*4)+
  j*0x164 and BREAKS on the first null entry pointer. At section-1 load the grid
  isn't built yet -> loop breaks immediately -> zero Primus cells marked. At menu
  the grid is built but the one-shot apply already ran. => selective m5 failure.

Live completion table sample (reverted): mgr5+0xc4 cells mostly zero with a few
0x01; dirty flag already 1. (Which (d,e) == the beaten Primus not yet indexed.)

### FIX DESIGN (recommended): extend roster_bridge with campaign snapshot/restore

Root cause is timing-specific to manager 5, and everything needed is live at the
menu (state 26) - exactly where roster_bridge already runs. Cleanest fix: extend
the existing PINE companion to also snapshot/restore the manager-5 completion
table, mirroring the roster/slot-unlock pattern:
- CAPTURE (post-fight, stable across 2 polls like roster): mgr5 = *(0x008C1A7C);
  read completion table mgr5+0xc4 (0x1800 B) + dirty flag mgr5+0x18c8; store in a
  new data file (e.g. data/campaign.json) keyed to the profile.
- RESTORE (post-login state 26, grid built): mgr5 = *(0x008C1A7C); write the
  saved completion table back + set dirty flag = 1. Verify read-back like roster.
Snapshot/restore (vs replaying saved grid flags) captures EXACTLY the values the
game writes, sidestepping the uninitialized-local_20 question. Guard against
non-stable pointer-looking words (cells appear to hold scalars, but verify no
heap pointers before persisting). No client patch needed; robust to the exact
load-order cause. Managers 1-4 already apply, so scope stays m5.

NEXT: (1) capture a live in-session Primus win delta on the m5 completion table
to confirm exactly which words change per win and that they are boot-stable
scalars; (2) implement the campaign snapshot/restore in tools/roster_bridge.py
behind the same build/runtime/pointer guards; (3) cold-boot regression.

### C-DELTA: in-session Primus win writes stable scalars to the m5 cell (2026-08-12)

Live in-session capture (no reboot): snapshot mgr5 completion table district-0
region (mgr5+0xc4, cells 0..63) before/after beating one Primus. Files in
captures/trackC-m5-delta/. Real, in-bounds delta (post capture paste was
truncated at byte 885; ignore cells >~55):
- cell 1 == (district 0, event 1): field+0x4 0 -> 3, field+0x8 0 -> 1. This is
  the completion record a win writes. Values are small ints (3, 1) = STABLE
  scalars, NOT heap pointers -> safe to snapshot/restore.
- cells 49/50/52: only field3 high byte flipped 256 -> 0 (volatile "new/
  available"? unrelated to completion) -> EXCLUDE from restore.
- dirty flag mgr5+0x18c8 stayed 1.

Cell layout (0x10 B at mgr5+0xc4+(d*64+e)*0x10): {+0:int, +4:int(=3 on win),
+8:int(=1 on win), +c:int(volatile hi-byte)}. Completion signature = field+0x4
and/or field+0x8 nonzero.

=> Companion design validated. Snapshot cells with a completion signature
(field+0x4/field+0x8 nonzero), stable across two polls (roster_bridge pattern);
restore those cells + set dirty flag on boot. Exclude all-zero and field3-only
cells. Persist per-profile in data/campaign.json. Build in tools/roster_bridge.py
under the same guards; regression across a real cold boot.

### C-IMPLEMENTED: campaign completion companion in roster_bridge.py (2026-08-12)

Extended tools/roster_bridge.py to snapshot/restore the manager-5 Primus
completion table alongside the roster, sharing the same PINE connection,
state-26 readiness, and stable-across-2-polls capture discipline.
- New constants: CAMPAIGN_MANAGER_SLOT 0x008C1A7C, EXPECTED_CAMPAIGN_MANAGER
  0x019D4D64, table +0xC4, dirty +0x18C8, 6x64 cells * 0x10.
- CampaignSnapshot (non-empty cells + dirty flag) with build/UUID guard and a
  HEAP_POINTER band (0x30000000-0x3FFFFFFF) guard that refuses to persist any
  cell word that looks like a live, non-boot-stable pointer.
- CampaignStore -> data/campaign.json (atomic write, same style as roster).
- read_campaign/restore_campaign guard the manager pointer against the expected
  value; restore writes cells + forces dirty=1, then verifies ONLY the cells it
  wrote (the game may set additional cells at boot).
- _start_campaign (first ready: restore saved, else capture initial) and
  _poll_campaign (capture stable mutation) are best-effort: any campaign fault
  is logged and disables campaign for the session without affecting the proven
  roster path. Wired into _run_connection parallel to the roster tracking.
- run_roster_bridge builds a CampaignStore (SPARTACUS_CAMPAIGN_PROFILE env, added
  to spartacus_server.configure_environment).
5 focused unit tests added (round-trip/build guard, restore+verify tolerant of
game-set cells, pointer guard + poll swallow, manager guard, start restore);
full suite green (19 tests).

LIVE TEST PLAN (end to end): fresh cold boot -> bridge captures reverted state as
initial -> beat a Primus in-session (bridge saves the stable mutation to
campaign.json) -> cold boot -> bridge restores -> Primus stays cleared; confirm
economy/roster unaffected.

### C-VALIDATED: boss/Primus persistence works across cold boots (2026-08-12)

End-to-end confirmed by the user and roster_bridge.log:
- boot 1: `created initial campaign profile (19 completion cell(s))` (reverted
  baseline captured);
- two Primus wins in-session captured as stable mutations 19 -> 20 -> 21 cells
  (`saved stable campaign update`);
- boot 2 (cold): `restored 21 campaign completion cell(s)`; user confirms the
  defeated Primus stay cleared and successors unlocked, with economy and roster
  intact. data/campaign.json cell 1 = {field+4=3, field+8=1} (win signature).
Working state backed up under backups/trackC-working-<ts>/. Track C objective
(Primus completion persistence) is met via the campaign companion; no client
patch was required.

Follow-ups (not blockers): (1) README/packaging should list data/campaign.json
as a third persisted file to back up, and the build should ship it like roster;
(2) the restored dirty flag reads as 0x01000000 via read32 (round-trips
faithfully, game accepts it) - harmless, worth a tidy later; (3) broader
regression: full-game second-playthrough Primus, multiple districts, and a
death+cold-boot combined run.
