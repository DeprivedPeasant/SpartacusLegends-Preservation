# Current AI handoff — v0.6.2 release candidate

- **Checkpoint:** 2026-08-28
- **Repository:** `C:\Users\Jake\Coding\SpartacusLegends-RE`
- **Supported title:** Spartacus Legends `NPUB30746`, versions `01.00` and
  `01.06`
- **PPU hash `01.00`:** `81471d050c14f4d20b4027686f8b571dafd32394`
- **PPU hash `01.06`:** `131aece6ae8526d13307be925f48c87f73c43799`

Read `AGENTS.md` first. This file is the current engineering checkpoint, not a
substitute for verifying the repository. At the start of a new session run:

```powershell
git status --short
git log -3 --oneline --decorate
python -m unittest discover -s tests -p 'test_*.py'
```

## Current shipped release

Version `0.6.1` is publicly released. It retains live-tested title versions
`01.00` and `01.06` and adds the live-validated, backup-first 01.00 -> 01.06
native-save migration documented later in this handoff:

- Release commit: `9401053e103740496e57943609c2742bfef484f8`
- Annotated tag: `v0.6.1`
- Required patch versions: `4.2` for 01.00 and `4.4` for 01.06
- Release:
  `https://github.com/DeprivedPeasant/SpartacusLegends-Preservation/releases/tag/v0.6.1`
- Release ZIP SHA-256:
  `702613743195f1dcf454f5a60e1a7fe0fb0367f790cecc5f86981d8023571a3a`
- Final tagged validation: 184 tests passed; a fresh extraction exercised both
  packaged executables, first migration, safe refusal, explicit backed-up
  replacement, expected initial object sizes, and 01.06 server configuration.

## v0.5.0 migration baseline retained

Version `0.5.0` is publicly released. It adds automatic v0.3 -> v0.4 save
migration to the v0.4.0 native persistence baseline:

- Annotated tag: `v0.5.0`
- Patch version: `4.2` (unchanged)
- Release:
  `https://github.com/DeprivedPeasant/SpartacusLegends-Preservation/releases/tag/v0.5.0`
- Re-verify the release commit and ZIP SHA-256 from the GitHub release
  page rather than trusting this file's date.

v0.5.0 migration behavior:

- Normal startup detects legacy v0.3 `roster.json`/`campaign.json` without
  a native counterpart and enables a one-time PINE migration automatically;
  no command-line flag is needed.
- Fresh and completed installations never open PINE. A completed
  installation records `data/migration-v0.4.json` with status `complete`.
- A timestamped backup of the complete `data` directory is created beside
  it under `backups/` before any conversion activity; no legacy file is
  deleted.
- Pending type-2/type-3 uploads are deferred (HTTP 503) until the legacy
  object is restored, so a fallback roster/campaign can never become
  authoritative. All gated uploads must match the exact native size.
- A malformed native object blocks that type's migration and rejects its
  uploads; it is never treated as absent.
- Migration is independent per type; the campaign can complete while the
  roster is blocked.
- The controlled live upgrade (Phase 5 of
  `notes/07-v0.4-save-migration-plan.md`) passed: legacy 3-gladiator
  roster and 25-cell campaign restored once, exact-size native objects
  captured, and two subsequent native-only cold boots restored migrated
  plus post-migration changes with no PINE connection.

The v0.4.0 release was built from the tagged commit, extracted into a fresh
folder, and both packaged executables were launched. The public release has the
ZIP and a `.sha256` attachment. At handoff time `origin/main`, local `main`, and
the peeled release commit agreed. Re-verify this rather than trusting the date.

## Proven working

- Complete Quazal/RendezVous login through the local preservation server.
- Remote-config discovery, metadata selection, SHA-256 verification, HTTP
  download, and minimum KFF mode-3 application.
- Automatic native UserStorage enumeration at login.
- Native profile readback: currency, fame, and related profile/account values.
- Native campaign readback: mission, district, and Primus progression.
- Native complete-roster readback: all gladiators, equipment, and roster state.
- Native autosave uploads and subsequent cold-boot restoration.
- Purchased Ludus slot capacity across cold boots, including empty slots.
- Recruitment refresh countdown restored to approximately 30 minutes.
- Existing economy, inventory, recruitment, store completion, optional
  matchmaking, one-hit, logo-skip, and 60 FPS configuration remain available.

The final packaged regression used two cold boots. The first restored profile,
campaign, full roster, and all products `80002..80007`; it showed the correct
timer. The player then changed gladiator/progression state and completed a
fight. The server stored all three exact-size objects, including final profile
values gold `999682` and silver `1052161`. A second cold boot restored every
change, slot, currency/fame value, campaign result, roster entry, and timer.
Normal mode made no PINE connection. Sixty-three unit tests passed for the
tagged implementation.

## Current persistence architecture

The authoritative native objects live beside the server executable:

| Type | Path | Exact size | Meaning | Format property 100 |
| --- | --- | ---: | --- | ---: |
| `0x80000001` | `data\usercontent\80000001\1.bin` | 4664 (`0x1238`) | Profile, currency, fame, related values | 2 |
| `0x80000002` | `data\usercontent\80000002\1.bin` | 6148 (`0x1804`) | Campaign, mission, Primus progress | 1 |
| `0x80000003` | `data\usercontent\80000003\1.bin` | 21444 (`0x53C4`) | Complete roster, equipment, roster state | 2 |

Relevant implementation:

- `tools/spartacus_server.py` fixes persistence beneath the release directory,
  starts native mode by default, and imports `roster_bridge` only when
  `--legacy-roster-bridge` is explicitly selected.
- `tools/prudp_server.py` implements UserStorage enumeration, upload/download
  handshakes, Monetization, and the required native response encoders.
- `tools/UbiOnlineConfigService/spartacus_onlineconfig.py` serves OnlineConfig,
  remote config, and atomic native UserContent PUT/GET bodies.
- `tools/patch_installer.py` installs patch/network configuration without
  enabling or modifying RPCS3 IPC.

`data\profile.json` remains active as the server-side economy/inventory
database. `data\roster.json` and `data\campaign.json` are legacy PINE-era data,
not normal v0.4 authority. Do not delete them: the planned migration needs them.

## Required client patch

Commerce2 remains incomplete in RPCS3, so patch 4.2 is still required. Its
required instructions are distributed identically in:

- `packaging\SpartacusLegends_ServerPatch.yml`
- `patches\SpartacusLegends_OfflineFix.yml`

The required patch entries are:

- `0x004F2B64 -> 0x48000458`: enter the Commerce2/state-26 success path.
- `0x00105710 -> 0x38000001`: supply readiness to the game's guarded native
  save enumerator.
- `0x00068504 -> 0x480000BC`: apply the locally saved section-1 profile as a
  safe pre-native fallback.
- `0x00174A9C -> 0x98090022`: accept recruitment-pool refresh completion.

Do not remove the local-profile patch merely because native type-1 works. It is
the bootstrap fallback before the first native type-1 upload exists.

## Two v0.4 RC bugs that are already resolved

### Purchased slots

Purchased slot capacity is not equivalent to roster occupancy and is not
safely restored from the type-3 owned count. The game persists slot products in
the server economy database. Monetization method 8 returns transaction records
with wire shape:

```text
u32 item_id, u64 packed_quazal_datetime, u32 quantity
```

At login the client passes positive-quantity transactions into its native
category dispatcher. Replaying only products `80002..80007` restores the
highest purchased slot even when some purchased slots are empty. Do not replace
this with `max(roster_count, 2)` or an unlock-all patch.

### Recruit timer

Method 8's trailing server time is a packed Quazal DateTime. Sending Unix
seconds is the correct width but the wrong representation; the client converts
it as calendar fields and creates a huge signed clock offset, producing a timer
such as `35791394:07`. `encode_monetization_server_time()` now uses
`encode_qdatetime()` for both transaction timestamps and server time.

Static evidence: `FUN_001F2D64` converts the calendar object to the game's
epoch, while the method-8 callback stores converted-server minus local time at
clock-owner `+0x11F8`.

## v0.6.0: 01.06 as a second supported build

Release work since `v0.5.0`. Live boots have exercised login, protocol 106,
all three native save objects, and the complete visual bootstrap through an
unobstructed main menu.

`01.06` is the same `NPUB30746` with update PKGs `SPARTACUSPATCH01..06`
applied, so both builds share one title ID and one save directory. Four
existing required patch instructions were relocated by static comparison of
the two executables. Live diagnosis then found two additional v1.06-only
compatibility sites; the per-site evidence is in `notes/13-v106-port.md`.

Required patch, `01.00` -> `01.06`:

| Purpose | `01.00` | `01.06` |
| --- | --- | --- |
| Pre-product-info Commerce2 middleware readiness | not present | `0x0057BE8C -> 0x60000000` |
| Orphaned Updating Game Data modal | not present | `0x0057BF24 -> 0x60000000` |
| Commerce2 / state-26 success | `0x004F2B64 -> 0x48000458` | `0x0057BAF8 -> 0x4800034C` |
| Save-enumerator readiness | `0x00105710 -> 0x38000001` | `0x00156DB4 -> 0x38000001` |
| Local section-1 profile fallback | `0x00068504 -> 0x480000BC` | `0x000B7908 -> 0x60000000` |
| Recruitment refresh completion | `0x00174A9C -> 0x98090022` | `0x001DBD34 -> 0x98090022` |

`01.06` inverted the profile-fallback branch, so that one site is a `nop`
rather than an unconditional branch. The three optional patch groups were
relocated the same way and are in the YAML too.

Native save-object sizes are **not** the same across builds:

| Type | `01.00` accepted | `01.06` accepted |
| --- | --- | --- |
| `0x80000001` profile | `0x1238` | `0x15B8`, `0x1590`, `0x1238` |
| `0x80000002` campaign | `0x1804` | `0x1C04` |
| `0x80000003` roster | `0x53C4` | `0x53C8`, `0x53C4` |

Neither build accepts the other's campaign object. There is no cross-build
campaign conversion and none should be invented without live evidence.

Implementation in the working tree:

- Both distributed YAMLs carry a second `PPU-131aece6...` section with all
  four patch groups. They remain byte-identical.
- `tools/migration_coordinator.py`: `TitleVersion`,
  `NATIVE_OBJECTS_BY_VERSION`, `native_objects()`, `PPU_HASHES`, and
  `NativeObjectInfo.accepted_sizes`. `UploadGate`, `evaluate_installation()`,
  `build_marker()`, and `InstallationReport` are version-aware. The `01.00`
  default reproduces the previous behaviour and stays exact-size.
- `tools/spartacus_server.py`: `--title-version {01.00,01.06}`, default
  resolved automatically from installer-owned `data/server-config.json`, with
  an explicit CLI override and a backward-compatible 01.00 fallback when the
  config is absent. 01.00 retains `data/usercontent` plus `data/profile.json`;
  01.06 uses `data/usercontent/01.06` plus `data/profile-01.06.json`.
- `tools/patch_installer.py`: installs and enables both PPU sections and
  accepts either `APP_VER`. It records the detected `APP_VER` in
  `data/server-config.json`, verifies it, and backs up that file when a user
  switches builds. Two latent merge bugs were fixed that only
  mattered once a second section existed - project entries could be inserted
  into the following PPU section, and the blank separator line was swallowed
  on a repeated install. Both merges now have idempotence tests.
- Tests: `tests/test_title_versions.py` plus additions to
  `tests/test_patch_installer.py` and `tests/test_release_patch.py`.
  The current suite is 177 tests and passes.

`01.06` adds eight RendezVous custom protocols that `01.00` does not have.
Live boots proved the original relocated instructions, native uploads at
`0x15B8` / `0x53C8`, and protocol 106 end-to-end. Method 1 must return
`[3, 2, 2, 0, 0]`; that is now the server default. The remaining blocker was
traced to a middleware-ready check added in v1.06 before the existing
product-info bypass: `0x0026F894` returns zero when the Commerce2 middleware
singleton/callback is unavailable, and the branch at `0x0057BE8C` parks the
machine in state 21 waiting for controller byte `+0x0A` to be set externally.
A clean live snapshot proved the actual controller tick-enable byte at `+0x2C`
was 1, disproving the earlier "job disabled" conclusion. Patch version 4.3
NOPed only `0x0057BE8C`, preserving the normal path that sets state 22 and
controller byte `+0x09`. A clean patched boot reached Commerce2 state 33, read
the `0x53C8` roster, and created a native `0x1C04` campaign object, but a
window screenshot proved that the new v1.06 `Updating Game Data` modal still
covered the loaded main menu. The normal `P53M1=zero` no-file result takes the
state-14 status-3 continuation, which never calls the modal teardown routine.
Patch version 4.4 additionally NOPs only the modal show call at `0x0057BF24`;
its clean-cache cold boot reached the unobstructed main menu. The same boot
enumerated and downloaded existing profile (`0x15B8`), campaign (`0x1C04`),
and roster (`0x53C8`) objects without recreating the campaign, completing the
first native-save restore test. Full evidence is in `notes/13-v106-port.md`.

Note recorded there: both builds assign 101 to Monetization and 102 to Shop, so
`PROTO_MONETIZATION = 102` is a misnomer for the Shop protocol. Behaviour is
unaffected; renaming is deferred pending a decision.

The first wider gameplay pass exposed three v1.06 Shop changes, now handled in
the working tree and live-validated:

- Method 20 deposits fight rewards as three signed deltas
  `{gold, silver, fame}` and returns the three absolute balances. Returning the
  old generic receipt crashed the level-up unlock screen. The structured
  response completed that screen normally.
- Method 19 shares method 20's three-u32 response parser and is the login
  balance readback. Returning an item-receipt-shaped body reset fame to zero;
  returning `{gold, silver, fame}` restored fame 140 and level 2.
- Method 24 returns a count followed by 21-byte Shop ownership records shaped
  `{u32, u32, u32, u32, bool, u32}`. The post-load validator at `0x0025C730`
  compares each native owned gladiator's `record+0x08` key with the first u32
  in this list and removes unmatched gladiators. The server now extracts those
  keys from the authoritative v1.06 type-3 object (`count @ +0x53B4`, records
  `@ +0x0810`, stride `0x0158`, key `@ record+0x08`). Its bool is copied into
  native `record+0x13C`, so the server also replays that byte; the first test's
  false placeholder restored the gladiator as dead and required a 150-silver
  revive. A cold boot sent ownership ID 1000 and restored the gladiator; the
  follow-up native upload contains keys 1000/1008 and active flags 1/1. The
  previous empty-list response was the direct cause of the zero-gladiator
  Ludus. The next cold boot sent `[(1000, 1), (1008, 1)]`; both gladiators
  restored and neither required revival, proving the active-flag correction.
- v1.06 method 13 adds a category u32 before the unchanged signed gold/silver
  cost pair. The observed request was `{1008, 0, 6, -1, 420}`. Parsing it as
  v1.00's four fields incorrectly charged 6 gold and ignored the 420-silver
  price. Dispatch now selects the exact captured layout by title version. A
  second live request `{1014, 0, 5, -1, 420}` correctly changed silver from
  598 to 178 while leaving gold at zero.

The new v1.06 Daily Goals/Challenge surface is also implemented and
live-validated:

- Retail `XML.dat` supplies all 72 exact reward rows in database order
  `{id, item_id, item_quantity, silver, gold, fame}`.
- Protocol 109's six-u32 response DTO instead uses
  `{id, gold, silver, fame, item_id, item_quantity}`. Sending DB order put
  silver in the client's fame slot; the encoder now performs the explicit
  conversion.
- Permanent method 1 requests are `{player_pid, challenge_id}`. Daily method
  3 was captured live as `{challenge_id, qdatetime}`. Methods 2/4 enumerate
  persisted permanent/current-day completed IDs.
- Daily ID 52 credited 2000 silver and 2000 fame, played both animations,
  persisted across a full server restart/cold boot, and remained
  non-claimable. Permanent ID 7 then credited and animated 1000 silver.
  The isolated checkpoint is `2 gold / 7411 silver / 2704 fame`, permanent
  `[4, 7, 43]`, daily `[52]` dated 2026-08-26. Do not treat this test profile
  as release seed data.

The first v1.06 Nemesis progression test also passed without new server work.
Ashur encounter 1 launched/completed normally, awarded ordinary fight rewards
(`+809 silver / +127 fame`), and unlocked encounter 2. A before/after native
capture changed the `0x1C04` campaign object only at two aligned big-endian
u32 fields: `+0x1804: 0 -> 3` and `+0x1810: 0 -> 1`. These are in the v1.06-only
extension beyond the v1.00 campaign size; do not assign narrower names from
one sample. After a full server restart/cold boot, balances restored as
`2 gold / 8220 silver / 2831 fame`, encounter 1 remained complete, and
encounter 2 remained available. No new RendezVous call appeared, so the tested
Nemesis path is already covered by native type-2 persistence. Remaining Ashur,
Gannicus, and Agron fights are characterization/regression work rather than a
known blocker.

The full automated suite contains 177 passing tests after these changes.

## Live-validated 01.00 -> 01.06 save migration

An explicit backup-first migration is implemented in
`tools/title_save_migration.py` and exposed through
`SpartacusLegendsServer.exe --migrate-01.00-to-01.06`. Normal startup never
invokes it, and it refuses any existing 01.06 namespace, companion, or marker.
It requires exact-size complete 01.00 native objects and `profile.json`, checks
gold/silver against the native profile, recovers old unstored fame from the
native `+0x14` field, backs up the complete `data` directory, and records an
auditable marker with hashes.

For users who already created an unwanted fallback 01.06 save, the separate
`--replace-existing-01.06` flag may be combined with the migration command.
The default still refuses replacement. The explicit replacement path validates
the 01.00 source and backs up the complete `data` directory—including the old
01.06 state—before replacing only the versioned destination, companion, and
marker. It must not be used when the existing 01.06 progress should be kept.

The conversion preserves the old profile, appends a zeroed `0x400`-byte
Nemesis/new-feature extension to campaign (`0x1804 -> 0x1C04`), and appends a
zeroed trailer word to roster (`0x53C4 -> 0x53C8`). The first live roster
attempt incorrectly passed through `0x53C4`: the client downloaded it and the
server replayed all six Shop ownership records, but format 4 fell back to one
gladiator. Static dispatch confirmed its native branch requires `0x53C8`.

The corrected conversion passed end to end on 2026-08-26. First boot restored
all six gladiators/equipment/slots, profile values `999710 / 1046714 / 7748`,
and previous Primus progress, with clean Nemesis state. Buying/equipping a
training item and completing Ashur 1 caused exact-size native 01.06 rewrites
of all three objects and values `999683 / 1047092 / 7853`; Ashur 2 unlocked.
After a full server restart, the second cold boot restored the complete roster,
new item, balances/fame, Primus state, and Ashur 2. Six focused migration tests
were added alongside CLI coverage; the full suite is now 184 tests.

The automatic-version/isolation release-candidate test also passed end to end
with the packaged v0.5.0 executables on 2026-08-26. The installer read
`rpcs3-B`'s `APP_VER=01.06`, wrote `data/server-config.json`, and the server
selected `01.06` without a command-line version override. A hash-verified copy
of the established checkpoint was placed under
`data/usercontent/01.06/{80000001,80000002,80000003}/1.bin`, with the economy
companion at `data/profile-01.06.json`. The first cold boot restored both
gladiators, currency/fame, campaign, Daily Goals, and Ashur progress. One
ordinary fight then awarded `+3 gold / +236 silver / +148 fame`, producing
balances `5 / 5369 / 3179`; the client uploaded all three exact-size native
objects. After a complete server stop/restart, a second cold boot restored the
new balances and all other state. No PINE or legacy migration path activated.

Network caveat proven during that test: `rpcs3-B`'s explicit bind/source was
`192.168.1.10`, but the reachable server address was `192.168.0.153`. The
successful command was `--host 0.0.0.0 --advertise-host 192.168.0.153`.
Advertising the RPCS3 bind address instead caused repeated auth SYNs with no
accepted SYN-ACK. Do not infer `--advertise-host` directly from RPCS3's Bind
address; ordinary unbound single-client setups should keep loopback defaults.

Before any `01.06` release:

1. ~~Finish the wider 01.06 gameplay regression.~~ **DONE for the exercised
   single-player path.** Fight reward/profile readback, level-up unlock
   presentation, deletion, replacement recruitment, native autosave, and two
   cold boots passed. The final object contained keys 1008/1014 with active
   flags 1/1; method 24 replayed both, the deleted key 1000 stayed absent,
   neither gladiator required revival, fame/fight progress restored, and the
   corrected 420-silver recruitment debit persisted. The test profile's
   starting currency had already been contaminated by the earlier bad parser,
   so do not quote its absolute balances as a clean default-profile result.
2. Exercise remaining unobserved 01.06 protocol methods and the optional
   matchmaking patch beyond bootstrap. The observed Tournament, LoginReward,
   DailyPopup, Challenge, and CommunityBossFight calls now have structured
   responses; protocol-109 permanent/daily claims are proven, but unobserved
   methods are not claimed complete.
3. ~~Decide the shared-save-directory policy for players who move between
   builds.~~ **DONE in the working tree.** The existing 01.00 paths remain
   unchanged, while 01.06 has a separate native/economy namespace selected by
   the installer. No cross-version campaign conversion is attempted, and the
   v0.3 JSON/PINE migration path is restricted to 01.00.

## v0.6.2 release work

This release carries the v1.06 Daily Login and consumable-boost fidelity work.
The opt-in protocol-107 implementation, successful reward-screen and
currency/item claim tests, and live-proven Shop method-9/method-10 quantity
semantics are recorded in `notes/16-v106-daily-login-boost-handoff.md`.

A 2026-08-27 static session inside that note resolved the root cause of both
failed overlays: boost counts live in a separate volatile singleton at
`0x01A7FAA8`, not in the type-3 roster allocation. Counts are not serialized in
any native object; do not attempt further UserContent byte injection.

The original server path is now statically and live proven. Shop method 8's
v1.06 family-6 replay handler loads the transaction quantity from record
`+0x18` and passes it directly to count setter `0x00259980`. The emulator had
returned method-8 records only for purchased Ludus slots, all at quantity 1.
It now also returns owned consumables `60000..60063` with their persisted
remaining counts, and the disproven roster overlay has been removed.

First live cold boot replayed `[(60005, 1), (60020, 32), (60021, 1)]`. Ludus
showed Face Carver x32 and Hold Still x1 with no depletion popup. No method-10
request was needed. One fight then sent Shop method 9 for Face Carver, persisted
32 -> 31, and a normal close/restart/cold boot restored Face Carver x31 and Hold
Still x1 without a popup. This proves the complete server-only,
restore-consume-persist-restore loop; do not add the proposed `0x002579F4` YAML
predicate patch.

The same method-8 path is also the general purchase-history reconstruction
mechanism, not a slot/consumable-only endpoint. A user report exposed that
permanent weapons and gear appeared owned only for the purchase session, then
returned to the shop at `1 gold` after a restart; ownership challenges likewise
fell back to the single native-roster item. The economy database still contained
the purchases, but `method_8_transactions()` omitted every non-slot permanent
item. Method 3's later requested-inventory response was too late to reconstruct
the boot-time purchase state.

Method 8 now replays every persisted non-consumable purchase at quantity 1,
alongside slot products and consumables at their saved remaining counts;
zero-count consumables remain omitted. The isolated profile first cold-booted
with permanent items `10250`, `10296`, `30001`, `30005`, and `50002`: all stayed
owned without the `1 gold` repurchase state, and the Dual Swords challenge read
`2/5`. Jake then purchased Bent Iron Gladii (`10311`, 2,980 silver) and Dented
Iron Swords (`10282`, 3,580 silver). After a normal shutdown and second cold
boot, both remained owned, neither showed the `1 gold` state, and the challenge
remained `4/5`. The full suite passed 196 tests at that checkpoint.

### v1.06 owned-boost prices and the separate sale overlay

Historical 01.00 footage proves a consumable can simultaneously show
`PURCHASED x5` and its nonzero refill price. The method-3 purchased-item DTO's
first numeric/bool pair is price/currency metadata: the earlier `(1, true)`
probe rendered `1 gold`, while the normal fabricated `(0, false)` rendered
owned boosts as `0 silver` in 01.06.

A controlled 01.06 cold boot suppressed only method-3 consumable rows while
leaving complete method-8 replay enabled. Face Carver restored at `x31` and
displayed its original `500 silver` refill price. This proves method 8 is
sufficient for owned-boost quantity/ownership and method 3 was overwriting the
retail catalog. `method_3_inventory_items()` now omits IDs `60000..60063` only
for 01.06; 01.00 behavior remains unchanged. Three focused tests cover version
selection and exact ID boundaries; the full suite is now 199 passing.

The same test independently proved the universal `SALE!` overlay is not method
3: it remained on every unowned boost, with a crossed-out zero, even when
method 3 returned no consumable rows. The correct catalog price remained above
it and was used by purchases. A later read-only live snapshot proved both the
KFF sale-source count and runtime sale-manager count are zero. The Market
controller's sale-class bytes at `+0x20AC..+0x20BA` are also all zero, exactly
matching the native initializer's calls to `0x00276550`. Thus the title's
native sale manager does not classify these cards as active sales.

Static comparison also corrected a false lead: v1.00 and v1.06 construct
`saleEquip%dT` with the same widget lookup class, and both gate the named
`showSale` animation on the same widget-internal null check. The only direct
v1.06 call to that animation routine is an input-event path at `0x001EC0C0`;
Jake's opening-Ludus test did not hit its breakpoint. It is therefore not the
source of the cards already visible when the screen opens. Surviving February
2014 build notes say the patch which added Daily Goals also fixed an incorrect
`Sale` overlay on silver boosts and made category-sale items work, making the
remaining issue most likely a default Market timeline/configuration state, not
Shop transaction metadata. Treat this as a separate cosmetic/configuration
issue; do not reintroduce method-3 price records to address it.

Health Boost (`60005`) displayed x1 because the isolated test profile already
listed it in `owned_items` but lacked an `item_quantities` entry. The intentional
legacy compatibility fallback assigns one use to an owned consumable with no
saved count. This is prior test-profile history, not a synthetic default grant.

At this checkpoint the full suite has 206 passing tests, and normal startup
still leaves Daily Login disabled. The live test uses only
`.build\daily-login-live-20260827`. Never touch authoritative player saves.
During the last exchange Jake drove RPCS3 and the isolated server was running
in the local Codex terminal; server and game state must always be re-checked
in-process before any restart.

## Shipped migration implementation (historical reference)

The v0.3 -> v0.4 migration (all phases of
`notes/07-v0.4-save-migration-plan.md`) shipped in v0.5.0. Implementation:

- `tools/migration_coordinator.py`: detection, per-type state, backups,
  marker, and the thread-safe `UploadGate`.
- `tools/roster_bridge.py`: `MigrationBridge` restore-once companion with
  independent roster/campaign selection, plus the legacy Legend-adoption
  fixes described below.
- `tools/UbiOnlineConfigService/spartacus_onlineconfig.py`: optional
  migration-aware upload gating with exact-length enforcement.
- `tools/spartacus_server.py`: `MigrationController` launcher integration.
- Tests: `tests/test_migration_coordinator.py`,
  `tests/test_migration_bridge.py`, `tests/test_migration_upload_gate.py`,
  `tests/test_migration_launcher.py` (113 tests total).

### Migration-era roster bridge fixes

Live testing exposed a pre-existing false positive: the pointer-shape
heuristic treated in-band float data in procedural gladiator records as live
Legend catalog pointers, which could strand a legitimate v0.3 roster. Legend
records are now identified by their backing token (`_LEGEND_`), the same
discriminator `legend_recovery` uses. Genuine schema-1/2 Legend records with
no `record+4` root (the real retail layout) are adopted by scanning for a
self-contained 0x200-byte block anchored on its definition-pointer header;
`materialize()` publishes the rebased root at `record+4`. A legacy Legend
whose catalog cannot be proven still blocks fail-closed and remains
recoverable through `--recover-legends`.

Next candidates are the secondary tracks below; nothing in them blocks the
shipped release.

## Secondary work tracks

These are not prerequisites for migration and should remain separate:

- Multiplayer cancellation/disconnect soak testing and deciding whether more
  experimental matchmaking instructions should enter the required patch. Read
  `notes/09-multiplayer-handoff.md`; do not use its stale
  `notes/11-next-session-prompt.md` as the general project prompt.
- Optional splash/logo-skip issue on a completely fresh tutorial profile. The
  title screen can remain rendered over the tutorial; see
  `notes/10-known-issues.md` if that local ignored note is available.
- Remaining shop fidelity, especially consumable quantities/use counts and
  unexercised Monetization methods. See `notes/05-monetization-method-map.md`.

## Evidence routing

Use the smallest relevant source set:

- `README.md`: authoritative shipped setup and user-facing save rules.
- `notes/07-v0.4-save-migration-plan.md`: current migration design.
- `notes/02-original-profile-sync-plan.md`: chronological native writer,
  enumeration, format-property, and readback discovery.
- `notes/04-remote-config-static-analysis.md`: remote-config state machine,
  metadata, SHA, KFF, and live positive-path evidence.
- `notes/03-playtest-regressions-plan.md`: historical shop, slot, roster,
  campaign, and transaction evidence. Its original PINE-default baseline is
  superseded by v0.4 native persistence.
- `notes/05-monetization-method-map.md`: protocol-102 response shapes and open
  store questions.
- `notes/09-multiplayer-handoff.md`: multiplayer architecture and testing.
- `notes/00-plan.md`: full research diary. Search it for a specific address or
  event only after reading the focused note; do not follow its old NEXT labels.
- `notes/11-next-session-prompt.md`: stale multiplayer-specific prompt.

Many research notes are intentionally ignored by Git and exist only in this
workspace. A clone from GitHub contains the tracked release documentation and
migration plan, but not every local disassembly report.

## Toolchain

Ghidra 12.1.2:

```text
C:\Users\Jake\Downloads\Compressed\ghidra_12.1.2_PUBLIC_20260605\ghidra_12.1.2_PUBLIC\support\analyzeHeadless.bat
```

Project/program:

```text
C:\Users\Jake\Coding\SpartacusLegends-RE\ghidra_project\SpartacusLegends
EBOOT.elf
```

Typical headless form:

```powershell
& 'C:\Users\Jake\Downloads\Compressed\ghidra_12.1.2_PUBLIC_20260605\ghidra_12.1.2_PUBLIC\support\analyzeHeadless.bat' `
  'C:\Users\Jake\Coding\SpartacusLegends-RE\ghidra_project' SpartacusLegends `
  -process EBOOT.elf -noanalysis `
  -scriptPath 'C:\Users\Jake\Coding\SpartacusLegends-RE\scripts' `
  -postScript SomeScript.java
```

The v1.06 sale-overlay investigation traced the visual defect
to Shop method-3 metadata, not the `saleEquip%dT` animation. Boost catalog
records retain correct active gold/silver prices at `+0x10/+0x14`, but their
comparison/original gold/silver pair at `+0x6C/+0x68` is zero. `FUN_001E6470` copies the
ordinary gold/silver fields C/D and optional sale fields E/F/G from each
method-3 response row into those catalog fields. The emulator currently
returns rows only for owned requested IDs; the client requests the whole page.
That omission left unowned comparison prices zero and produced the exact
crossed-out-zero plus `SALE!` display. See
`notes/16-v106-daily-login-boost-handoff.md`, "Exact comparison-price writer
and revised method-3 model", for the static and live evidence. Do not alter
authoritative saves.

That probe succeeded. Unowned `60003` was returned at its captured 10-gold
retail price with `sale=false`; exactly that card lost the false `SALE!` banner
and crossed-out zero. A subsequent full unowned-catalog run fixed every
unowned card but left the owned cards incorrect. An owned Face Carver (`60020`)
probe then removed its false sale presentation while retaining its correct
method-8-restored use count. Production source therefore returns authentic
ordinary-price metadata for every requested v1.06 Boost ID `60000..60023`,
owned or unowned; method 8 remains the authority for ownership and remaining
uses. Final ungated live validation succeeded with both diagnostic probes
absent: both Boost pages had correct retail prices, no false `SALE!` banners or
crossed-out zeroes, and all owned quantities—including Face Carver x31—were
retained. This issue is resolved server-side.

Known RPCS3 installs for two-client work:

```text
C:\Users\Jake\Desktop\Clean RPCS3\rpcs3-A\rpcs3.exe
C:\Users\Jake\Desktop\Clean RPCS3\rpcs3-B\rpcs3.exe
```

The native-persistence live work used RPCS3 `0.0.42-19803`. Do not reuse the
obsolete RPCS3/Ghidra paths at the beginning of `notes/00-plan.md`.

## Verification and build commands

```powershell
python -m unittest discover -s tests -p 'test_*.py'
python -m py_compile tools\prudp_server.py tools\spartacus_server.py tools\patch_installer.py tools\UbiOnlineConfigService\spartacus_onlineconfig.py
git diff --check

$a = (Get-FileHash packaging\SpartacusLegends_ServerPatch.yml).Hash
$b = (Get-FileHash patches\SpartacusLegends_OfflineFix.yml).Hash
if ($a -ne $b) { throw 'Distributed patch YAML files differ' }

powershell -ExecutionPolicy Bypass -File packaging\build_release.ps1
```

At this checkpoint the full suite contains 206 tests. The number will grow as
coverage is added; do not hard-code a test count into future acceptance logic.

## Dead ends and corrections not to repeat

- Do not restore normal persistence with a continuously polling PINE companion.
- Do not infer purchased slot capacity from roster count or type-3 occupancy.
- Do not send Unix seconds in Monetization method 8.
- Do not remove Commerce2 patching on the theory that Quazal emulation replaces
  it; Commerce2 is a separate RPCS3 compatibility boundary.
- Do not serve native content without ContentProperty 100. Mode 0 decodes but
  skips the apply path.
- Do not reintroduce the provisional type-3 HTTP word rotation. Format property
  2 selects the direct raw-copy branch; persisted and served uploads remain
  byte-exact.
- Do not assume successful transport ACK/PING means an RMC session survived a
  server restart.
- Do not treat `notes/00-plan.md` NEXT labels as current assignments.

## Paste-ready new-session prompt

```text
Continue work in C:\Users\Jake\Coding\SpartacusLegends-RE.

Read AGENTS.md and CURRENT_HANDOFF.md completely first, then read
notes/16-v106-daily-login-boost-handoff.md. Treat README.md and tag v0.6.2 as
the shipped baseline. Do not start with notes/00-plan.md; it is a chronological
research archive containing superseded conclusions.

Verify the checkpoint with:
  git status --short
  git log -3 --oneline --decorate
  python -m unittest discover -s tests -p 'test_*.py'

The v1.06 Daily Login and consumable-boost work is included in v0.6.2. Daily
Login remains behind an explicit opt-in flag, Shop method 9 decrements Face
Carver uses, method 8 restores persisted quantities, and method 3 supplies
ordinary retail metadata for Boost IDs 60000..60023. Do not alter player save
data outside an explicitly isolated live test.
```
