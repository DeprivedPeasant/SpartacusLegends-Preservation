# Current AI handoff — v0.6.5 release checkpoint

## 2026-09-05 boost refill fix (packaged live validation passed; released as v0.6.5)

**Live validation passed:** isolated test at
`.build/boost-refill-live-20260905-181627` used the corrected packaged server
(SHA256 `BE6BA9DFFDBE0DC1A8766D1545C673CEC6FF94531F433298770330D931F29336`).
Jake bought two Fame Boost packs: UI 10 uses, two 20-gold debits. One fight
sent one method-9 call for 60006 and saved 9 uses; Jake confirmed UI x9.
Exact-size native profile/campaign/roster uploads followed. The game sent
DISCONNECT at 18:25:31, then the server stopped cleanly. The launcher remained
open with the game stopped. Server restarted at 18:26:17; second boot replayed
`(60006, 9)` at 18:27:36 and served all three native objects. Jake confirmed
9 uses after the cold boot. Purchase/consume/persist/restore is live proven.

The validation server was stopped cleanly after the second boot. Original dist
installation/data was unchanged; the test folder contains matched pre-test
backups and boot-1 saved hashes. The original v0.6.4 ZIP is backed up there.
The 0.6.5 release artifact was built with `packaging/build_release.ps1` and
checked with both packaged `--help` commands. ZIP SHA-256 is
`3C1F623F4CDCBC686F8A38F64AB273374E8F1F6922BEDEAAD80C27054AA43073`;
server executable SHA-256 is
`0F248E225C31276AA576CA709286E5E6C63147EB4808F6EF63FC440B9BEFAC02`;
installer executable SHA-256 is
`4A557DEF937FE759D1EB616EDCDE4B52C32DA0FF87A965A7B07A5803C34271F1`.

Jake reported Fame Boost x6 becoming x0 after a fight. The running packaged
v0.6.4 log at `dist/SpartacusLegends-Preservation-v0.6.4/logs/prudp.log`
proves method 8 restored item 60006 at quantity 1 at 18:04:49; method 7
accepted a refill at 18:06:07 but left its saved count/balance unchanged;
one method-9 request at 18:06:12 returned remaining=0. A subsequent refill
at 18:09:16 likewise left the saved zero unchanged. This is a refill-accounting
bug, not six consumption requests. Only Face Carver had a known pack mapping,
so other owned boosts were treated as permanent, non-repeatable purchases.

Retail 01.06 `SP_Skills.psf` (24 records, stride 0x70) has five at +0x1C
for every purchasable row 1..23. Native purchase code at 0x0019E3F4/404
resolves the boost catalog record; 0x0019E410 preserves it in r31 and
0x0019E614..628 adds record+0x1C to the existing count via 0x00259980.
The source pack mapping now covers 60001..60023 at five uses. This corrects
new purchases, refills, and the existing daily-login pack conversion. Legacy
missing-count defaults are separated and unchanged; explicit counts, including
zero, remain authoritative. Past lost uses cannot be recovered automatically.

Regression coverage exercises all 23 boosts: refill 1->6, consume 6->5,
restart/method-8 restoration, depletion and repurchase; first purchase,
99-use cap, and legacy-count preservation also pass. Full suite: 240 tests;
module compilation and diff checks pass. Earlier daily-login investigation
added two tests proving seven-stage growth across restarts and day-1 reset
after daily cash-in; the reporting user's choice remains unconfirmed.

No running executable, player save, or server session was changed. The open
packaged server still contains the bug. Build/deploy a candidate only after
the active game/server can be closed safely; validate Fame Boost purchase,
one-fight decrement, and cold-boot restoration before release. No commit or
release operation was authorized or performed.

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

## Current release

Version `0.6.3` is the PRUDP fragmentation hotfix for `0.6.2`. Shop method 8
responses larger than 962 logical bytes are split into acknowledged DATA
packets with intermediate fragment IDs `1..n`, final ID `0`, and sequential
packet IDs. Small RMC responses retain the title-validated v0.6.2 framing.

The affected 73-transaction save was tested from an isolated copy. Its
1194-byte method-8 RMC response was sent as 975- and 245-byte packets; the
client acknowledged both, requested campaign type `0x80000002` and roster type
`0x80000003`, restored the complete save, and subsequently uploaded exact-size
7172-byte campaign and 21448-byte roster objects. The automated suite contains
211 passing tests at this checkpoint.

## Unreleased post-v0.6.3 reliable-fragment hotfix

User testing found that v0.6.3's fragments were transport-ACKed but method 8
was not fully applied: purchased Ludus slots were not restored and the
recruitment shop could return to its refresh loop. The v0.6.3 live test had
proved only that bootstrap continued after both ACKs; it had not explicitly
checked slot entitlements or the recruitment timer.

The original legacy Quazal implementation provides the missing transport
semantics. Ordinary RMC replies below 963 logical bytes remain `NEED_ACK` and
use request sequence plus one. Replies at the 963-byte fragmentation threshold
enter a separate `RELIABLE | NEED_ACK` substream whose sequence counter starts
at one per connection and resets on reconnect. Fragment IDs still rise from
one with final zero, and compression framing plus RC4 remain independent per
packet. The working tree implements those rules in `tools/prudp_server.py` and
adds focused threshold, sequencing, reconnect, and affected-response tests in
`tests/test_prudp_responses.py`. The full suite contains 214 passing tests.

This correction passed a two-boot live test using only the isolated copy at
`.build/affected-save-reliable-live-20260828-231427`; the reported user's
source data was not modified. On the first boot, the 1194-byte method-8 reply
was sent as 976/244-byte reliable fragments on sequence IDs 1/2. Its saved
transaction history did not yet contain slot products, but the recruitment
timer was correct and the shop no longer refreshed repeatedly, proving the
fragmented callback was applied. Jake repurchased the slots, adding products
`80002..80007`. After closing RPCS3 and cold-booting again, method 8 replayed
all six products in a 1290-byte reply sent as 976/340-byte reliable fragments;
the new connection correctly restarted at sequence IDs 1/2. The client
restored every purchased slot, retained the correct timer, and showed no
refresh loop. RPCS3 was closed before the isolated server, which then stopped
cleanly.

### v0.6.4 release-candidate validation

The unreleased fix is versioned `0.6.4` and has passed source, packaging, and
live validation. The source suite contains 214 passing tests, the relevant
Python modules compile, `git diff --check` passes, and the two distributed
patch YAML files are byte-identical.

The release candidate was built only through
`packaging/build_release.ps1`. Its artifact is:

- ZIP: `dist/SpartacusLegends-Preservation-v0.6.4.zip`
- Size: `16,657,004` bytes
- SHA-256: `77282e03edb5b4088173634e2eed74e7ab2b327466acad3ddd900ce962f77916`
- Server executable SHA-256:
  `4d95f265d69afff20b4a46b0e547c9fb0aab72e990bb2d7d24ab7fba82d5a97b`
- Installer executable SHA-256:
  `3c4e6434493213efef1432de42591bc9f5849b77ec87c49bcef76592279edf57`

A completely fresh extraction at
`.build/release-validation-v0.6.4-20260828-233324` contained only the expected
five release files. Both packaged executables passed `--help`; the packaged
server started and stopped cleanly on alternate ports as v0.6.4, selected
title version 01.06, used `data/usercontent/01.06`, enabled Daily Login by
default, and made no normal-mode PINE connection. The packaged installer was
also exercised against the closed clean `rpcs3-B` installation: initial
verification correctly found its missing server configuration, installation
completed, a second verification returned `SETUP OK`, backups were created,
and the packaged server subsequently selected 01.06 from that installer
configuration.

The final packaged live test used a separate hash-verified save copy at
`.build/release-live-v0.6.4-20260828-233527`. The method-8 response replayed
all purchased slot records `80002..80007` in a 1290-byte response split into
976/340-byte reliable packets. The client ACKed connection-local reliable
sequence IDs 1 and 2 and continued bootstrap. Jake confirmed the complete
live checklist: save restoration, purchased slots, recruitment timer, and
shop behavior were all correct. RPCS3 then sent a normal DISCONNECT and was
closed before the packaged server, which stopped cleanly. This completes the
v0.6.4 RC validation gate. No release commit, tag, push, or GitHub release has
yet been made.

## Previous shipped release

Version `0.6.2` is publicly released. It retains live-tested title versions
`01.00` and `01.06`, adds v1.06 Daily Login and Shop quantity/metadata
fidelity, and includes the live-validated cold-boot Boost persistence fix:

- Release commit: `707bbb29511a846e2ca1d93f5fac771515801efb`
- Annotated tag: `v0.6.2`
- Required patch versions: `4.2` for 01.00 and `4.4` for 01.06
- Release:
  `https://github.com/DeprivedPeasant/SpartacusLegends-Preservation/releases/tag/v0.6.2`
- Release ZIP SHA-256:
  `8c9a08fb2877d366829518998a3426a6307ef9bfaba8daaa9cbf197033ef71b5`
- Release ZIP: 16,671,428 bytes.
- Final tagged validation: 206 tests passed; a fresh extraction exercised both
  packaged executables, alternate-port checks, full packaged server startup,
  expected release contents, and the v1.06 CLI configuration.

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

Before the v0.6.0 `01.06` release (historical checklist):

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

## v0.6.2 release contents

This release carries the v1.06 Daily Login and consumable-boost fidelity work.
The default-on protocol-107 implementation, successful reward-screen and
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

Daily Login is enabled by default in normal startup; the explicit
`--no-daily-login-rewards` switch is retained for troubleshooting. The live
research used only `.build\daily-login-live-20260827`. Never touch
authoritative player saves. Server and game state must always be re-checked
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

## Unreleased v1.06 Shroud perk experiment (2026-08-29)

The actual weighted random perk selector is `0x00260F28`; the earlier
`0x001BF848` / `0x00257C2C` hypothesis was an ancillary resolver and is
superseded. Retail v1.06 gives every ordinary enabled perk weight 100 in each
of seven selector columns, while Shroud of the Fallen I–III (runtime ids
78–80) have zero in all seven. Setting only Shroud I to a very high diagnostic
weight made it appear after a fight. Jake accepted and replaced a perk with
it, then cold-booted and confirmed it remained attached, validating UI,
effects, commit, and native persistence.

**Update 2026-08-30:** the trilogy (records 78–80 at weight 100) is confirmed
acquirable by users testing. The seven weight columns are selector categories
0..6 (identity mapping through jump-table getter `0x00260CA0`; the category
is `*(game-context singleton+0x2C)` via `0x000B8F1C`, written only by
`0x000B9F5C`). Records 68–77 are fully authored ordinary perks disabled only
by their zero weights: trigger tags `Taunt`/`Roll`/`GrabBlock`, correct
durations and magnitudes, complete six-language descriptions. Seven of the
ten have real display names (BRAVADO, COCKY, TANK, PATCH UP, BARREL ROLL,
NIMBLE, RUTHLESS COUNTER); records 68/69/70 (`Perk99/100/101_Name`) have
zero-length name strings in `strings.dat` and would display blank. A
named7+trilogy candidate
(`SP_Perks.named7-plus-trilogy-weight100.psf`, SHA-256
`E87F8F7B47446E370702B3CA536818EA3838573A542BD9C5BB7F5379E0017E4E`,
70 weight bytes changed vs retail) is installed in `rpcs3-B` for the next
live run; an all-13 variant (`910DA6B4A5E2F7D35963DEBFB7DFFA7E48E685BF4552446BDA8E7C7BC38AB1FB`)
exists but is not installed. Evidence and candidate table:
`notes/16-v106-perk-grant-and-shroud.md` §10. The retail reference table and
its dump tool are `tools/dump_perk_table_v106.py` and
`tools/build_perk_enable_v106.py`. No production patch, commit, or release
includes this yet.

The superseded trilogy-only candidate (`086803BB...`, ids 78–80 only) remains
available at `.build/shroud-trilogy-experiment-20260829/`. The pristine retail
SHA-256 is
`F66B2319310BC3AD4E344B49D81AEBB50864397C7B9DB97174AA032F1DBA49EA`.
See `notes/16-v106-perk-grant-and-shroud.md` §9–§10.

## Verification and build commands

### Optional Mark of Achilles I prototype (2026-08-31; not live tested)

**Latest: combined Achilles + Agron I-III private normal-drop pack built.**
Jake selected ALL Agron effects gated by low health, then explicitly requested
adding the family for two private testers. Earlier mixed-condition blocker
is superseded; no YAML patch needed for this interpretation.
`outputs/achilles-agron-normal-drop-20260831/` contains the combined ZIP/pair,
guide/manifest/checksums. Existing IDs0-83 byte-identical to Achilles trilogy;
Agron IDs84-86 clone Fury's <=20% gate and lifecycle, remove its attack-speed
bonus, set damage10/15/20% at BOTH +94/+10C, resistance5/10/15% at+B0/+B4,
IgnorePain +C0=1/+C4=INTEGER5, ratings20/30/40, seven weights100.
Fury icon placeholder; English text; normal reward gates unchanged. Builder
`tools/build_achilles_trilogy_v106.py --include-agron`; guide
`notes/20-achilles-agron-private-candidate.md`. Agron live behavior including
healing-above-threshold deactivation is untested and disclosed. No installed
files, saves, server sessions, production patches, or releases changed.
ZIP SHA256 `0d3ff9c0e3eeb934b14a7b848d2db6b4addd73432a849795abeca43258007d50`.
Old Achilles-only artifact retained as a checkpoint; send the COMBINED ZIP now.

**Newest: full Achilles I-III normal-drop candidate built, NOT installed.**
`outputs/achilles-trilogy-normal-drop-20260831/` contains the shareable ZIP,
checksums, manifest, tester guide, and XML pair. Builder:
`tools/build_achilles_trilogy_v106.py`; guide: `notes/18-achilles-trilogy-candidate.md`.
IDs81/82/83, weight100 in all7categories, shield icon, HP5/10/15,
resistance5/10/15%, regen0.25/0.5/1%sec, rating20/35/50. Base remains
named7+Shroud; first81records unchanged, ID81 byte-identical to revision2
normal-drop. Independent Node verification preserves45952old localization
cells and all21tables; six new rows. Full suite232passed. ZIP SHA256:
`10a7020147770616ac7861acb8615b03cc50ca1699b141a009f991a4ee3317af`.
II/III, normal acquisition, and shield presentation still require live tests.
No install/save/server/production patch/Git release change this turn.

Jake also requested Agron's Rage. It is NOT included: native per-perk activation
gates every combat effect together; cannot currently represent independently
conditional damage with unconditional resistance/Ignore Pain in one XML row.
Asked whether a separate optional YAML patch is acceptable; await answer.
See `notes/19-agron-reconstruction-blocker.md`, full decompiler evidence in
`.build/agron-condition-analysis.log`. IgnorePain +0xC4 is INTEGER15, not a
float; +0x10C is generic damage, not a special low-health field. Do not silently
ship an approximation. Exact Agron historical threshold remains unknown.

**Newest:** Jake reports gameplay working and supplies historical footage of
Achilles II using the same shield icon as Ignore Pain. Exact retail row24
reference is Textures/Spartacus/Icons/PRK_DefenseAction_gold.png. Rebuilt BOTH
variants in `.build/achilles-prototype-20260831-r2-shield/`; independent binary
diff confirms only new ID81's +0x0C icon word changes vs corresponding revision1,
strings.dat byte-identical, effects/IDs untouched; 12 focused tests pass.
Revision2 is NOT installed. Next install normal-drop revision2 with RPCS3 closed,
then confirm retained perk and shield icon. Original revision1 installed files
remain for now. User's working-gameplay report is not a precise numeric hit test.

**Latest live evidence 12:19:58:** interpreter breakpoint0x0009A0AC, r4
0x35755F10 confirmed Frideric/key3192. Achilles ID81 is active (state1).
Actual cached combat aggregate reads12% in both resistance channels and
0.5% regen/s: Fearless Fists7%/0.25% plus Achilles5%/0.25%. Evidence
`.build/achilles-live-20260831-115406/runtime-1788142798958.json` (68 read-only
serial reads). Activation/aggregate stacking now verified. Direct hit/healing
measurements and normal-drop variant test remain outstanding. Server30538
unchanged; RPCS3 currently stopped at breakpoint pending user's resume.

**Cold boot 2 confirmed by Jake:** Achilles remains attached, Frideric118 HP /
277 Rating. New-ID acquisition, native upload, and cold-boot readback passed.
Combined resistance/regeneration effects remain unverified, and normal-drop
variant has not yet been installed. Current server session30538 remains active.

**Latest 12:04 update:** acquisition/UI and native upload of new ID81 succeeded.
See `.build/achilles-live-20260831-115406/boot2-status.md`. Frideric key3192
replaced Warrior's Insurance (51), not an unknown perk. Awaiting first cold-boot
readback; combat effects still unverified. One-hit now disabled, title EBOOT PPU
cache moved to recoverable backup. Server cleanly restarted, new PTY30538
(old70432 closed). Extra after-acquisition save checkpoint retained.

**Live-test preparation authorized and completed 2026-08-31 11:54:**
`.build/achilles-live-20260831-115406/live-test.json` records 37 verified
copies. Its `backup/` holds the complete last perk-test server data, local
`rpcs3-B` NPUB30746-STYAUTO- save, original two XML files, and patch/network
configs. `test-high-drop` SP_Perks.psf and strings.dat are now installed in
`rpcs3-B` and hash-verified. The original server data was NOT changed; the
test runs a separate copy under that live folder's `server/data`. Packaged
v0.6.4 is running on loopback ports 80/21000/21001, all services ready, game
01.06, native persistence; exec PTY session 70432 (Ctrl+C only after RPCS3
closes). The one-hit optional patch remains enabled for acquisition; disable
it with RPCS3 closed before combat-effect validation. Awaiting first boot and
perk offer. Do not start the older server against the experimental local save.
For rollback use this matched backup, not an earlier research checkpoint.

Jake authorized an optional reconstruction prototype, not a production release
or installation. `tools/build_achilles_prototype_v106.py` appends runtime perk
ID 81 to the existing 81 rows and adds two unique localized rows to strings.dat.
The candidate uses Shroud I's +5 HP/20 rating, removes its defense/damage bonuses,
and copies Hardened Flesh's two 0.05 resistance channels and Apollo's 0.0025
regeneration field. Existing Shroud icon, English text for all languages.

Built from the installed named7+trilogy PSF and pristine retail localization:
`.build/achilles-prototype-20260831/` contains `test-high-drop` (weight 1,000,000)
and `normal-drop` (weight 100), each with SP_Perks.psf and strings.dat, plus
README and manifest. No install, save, server, code patch, or Git release was
modified. New ID persistence and combined combat effects remain UNTESTED.
Do not distribute as validated. Test using a disposable/backed-up save; rollback
must restore pre-test saves as well as XML files if ID 81 was acquired.

Twelve new synthetic tests passed; full suite 226 tests passed. Independent
Node verification retained all 81 original records, all 45,952 existing
localization cells across 21 tables, and byte-identical unrelated tables.
See `notes/17-achilles-prototype.md` for installation, rollback, live checklist,
field provenance, and precise static evidence. Builder/test/note are local
research files covered by existing ignore rules, not a committed feature.

Important corrections to older perk notes: actual PSF record base is 0x24,
not 0x10; the old tool's field-offset shift happened to cancel for most fields.
True +0xA8/+0xAC are additive health/defense, NOT delete costs. Native parser
0x261354 uses count/stride and treats string offset zero as VALID; only -1
is null. Original strings.dat also contains conflicting duplicate Perk99/100/101
name keys: empty early rows and nonempty later INTIMIDATION/SWAGGER/SWOLLEN HEAD
rows. Earlier claims that those names are definitely absent are superseded;
runtime duplicate-key precedence remains unverified.

```powershell
python -m unittest discover -s tests -p 'test_*.py'
python -m py_compile tools\prudp_server.py tools\spartacus_server.py tools\patch_installer.py tools\UbiOnlineConfigService\spartacus_onlineconfig.py
git diff --check

$a = (Get-FileHash packaging\SpartacusLegends_ServerPatch.yml).Hash
$b = (Get-FileHash patches\SpartacusLegends_OfflineFix.yml).Hash
if ($a -ne $b) { throw 'Distributed patch YAML files differ' }

powershell -ExecutionPolicy Bypass -File packaging\build_release.ps1
```

At this checkpoint the full suite contains 214 tests. The number will grow as
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

## 2026-09-01 v1.06 weapon GUI / lost live-service item finding

The final v1.06 weapon GUI can be extracted losslessly. `FrontEndGlobal.gbs`
contains fixed records with logical sprite path, pixel dimensions, internal
atlas ID, and UV rectangle. Atlas IDs 1000..1007 map to the eight
`GUI/Textures/TA_1012_1.dds` .. `TA_1012_8.dds` pages. Local research tool
`tools/extract_weapon_gui_v106.mjs` generated
`outputs/weapon-gui-v106-20260901/`: 94 unique PNG weapon sprites,
371/377 weapon-table rows mapped, original DDS pages, CSV and JSON manifests.
The tool/output are ignored research artifacts, not shipped release content.

Historical screenshots in `C:\Users\Jake\Downloads\Compressed\ITEMS` establish
high-confidence reuse: Spear of Minerva matches `uiMarket_SP_Spear_T3_00.png`
and Spear of Apollo matches `uiMarket_SP_Spear_T1_00.png`. Corresponding
`SP_Spear_T3_00.PSSG` and `SP_Spear_T1_00.PSSG` models already exist in the base
HDDCache.pak. Exact lost-item names are absent from final v1.06 equipment tables
and strings.dat, and archive filenames contain no unique Minerva/Apollo spear.
Current hypothesis: historical live tables added definitions which reused
shipped generic assets; reconstruct rows rather than inventing models/textures.
See `outputs/weapon-gui-v106-20260901/INVESTIGATION.md` locally.

**Spear of Minerva candidate built (not installed):** Player evidence in
`C:\Users\Jake\Downloads\Compressed\ITEMS\STATS INFO.txt` plus the historical
screenshot establishes +4 Health, +8 Defense, +28% Damage, rating 81,
Excellent parrying, +50% critical chance, +15% damage resistance, and +6%
weapon speed. `outputs/spear-of-minerva-v106-candidate-20260901/` contains an
append-only private candidate with new item ID 10387, its manifest/readme, and
shareable ZIP. It combines the screenshot-matched `SP_Spear_T3_00` model/card
with an Excellent spear behavior record. All 387 retail weapon records are
byte-identical. Candidate PSF SHA-256:
`8EA8D700A2F90584C6E26A8C01917F3B33E158B3A986FC46235CD461E017C9CC`.
ZIP SHA-256:
`8F1D49FF9F6FF4404BC2E04E9BE4F0DD704802C0BBCE86D99A22C1B33AC96916`.
Original ID/description/price/acquisition metadata remain unrecovered; health
and defense encoding must be checked live. Builder:
`tools/build_spear_minerva_v106.py`. Do not install or grant ID 10387 without a
matched XML + save/server-data backup; rollback must restore both.

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
Login is enabled by default with an explicit `--no-daily-login-rewards`
troubleshooting switch. Shop method 9 decrements Face Carver uses, method 8
restores persisted quantities, and method 3 supplies ordinary retail metadata
for Boost IDs 60000..60023. Do not alter player save data outside an explicitly
isolated live test.
```
