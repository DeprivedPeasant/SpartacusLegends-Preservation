# Current AI handoff — v0.5.0 checkpoint

- **Checkpoint:** 2026-08-25
- **Repository:** `C:\Users\Jake\Coding\SpartacusLegends-RE`
- **Supported title:** Spartacus Legends `NPUB30746` version `01.00`
- **PPU hash:** `81471d050c14f4d20b4027686f8b571dafd32394`

Read `AGENTS.md` first. This file is the current engineering checkpoint, not a
substitute for verifying the repository. At the start of a new session run:

```powershell
git status --short
git log -3 --oneline --decorate
python -m unittest discover -s tests -p 'test_*.py'
```

## Shipped baseline

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

## Recommended next objective

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

At this checkpoint the full suite contains 63 tests. The number should grow as
migration coverage is added; do not hard-code 63 into future acceptance logic.

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

Read AGENTS.md and CURRENT_HANDOFF.md completely first. Treat README.md and tag
v0.4.0 as the shipped baseline. Do not start with notes/00-plan.md; it is a
chronological research archive containing superseded conclusions.

Verify the checkpoint with:
  git status --short
  git log -3 --oneline --decorate
  python -m unittest discover -s tests -p 'test_*.py'

The recommended next objective is Phase 1 of
notes/07-v0.4-save-migration-plan.md. Begin with read-only inspection and a
concrete implementation plan, then implement the coordinator and unit tests if
the current user request authorizes changes. Do not enable PINE during normal
startup, alter player save data, publish releases, or push changes without
explicit approval.
```
