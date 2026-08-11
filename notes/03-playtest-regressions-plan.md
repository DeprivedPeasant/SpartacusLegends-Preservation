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
