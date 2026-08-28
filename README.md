# Spartacus Legends preservation server

This project restores the login/bootstrap path for the PS3 version of
Spartacus Legends using a local OnlineConfig and Quazal RendezVous server.
Once bootstrap completes, the preserved single-player game runs locally. The
server reimplements the retired economy, inventory, and native UserStorage
calls. At login, the game automatically enumerates and restores its server-side
profile, campaign, and complete gladiator-roster objects. The compatibility
patch also completes the post-fight gladiator-recruitment store refresh, which
otherwise retries indefinitely.

> [!TIP]
> **Optional 60 FPS mode:** Spartacus Legends runs correctly at 60 FPS in
> RPCS3 without modifying the game executable. Open the game's custom
> configuration, set **Advanced > VBlank Frequency** to **120 Hz**, and leave
> **GPU > Frame limit** on **Auto**. Menus, gameplay timers, cutscenes, input,
> and physics have been verified at normal speed. This is optional; leave
> VBlank Frequency at 60 Hz for the original 30 FPS presentation if your system
> cannot maintain 60 FPS.

Shop actions the retired service no longer answers, such as replacing a
gladiator's perk or buying Ludus execution boosts, previously left the game
waiting forever on a loading spinner. The server now answers every shop request,
so an unimplemented feature reports a failure instead of locking the game up.

Tested configuration:

- Game: Spartacus Legends, NPUB30746 version 01.00 or 01.06. Both have passed
  live login and native profile/campaign/roster persistence tests; the wider
  01.06 single-player pass also covers recruitment, fights, level-up rewards,
  Daily Goals, and initial Nemesis progression.
- RPCS3 PPU hash 01.00: `81471d050c14f4d20b4027686f8b571dafd32394`
- RPCS3 PPU hash 01.06: `131aece6ae8526d13307be925f48c87f73c43799`
- RPCS3 PPU decoder: Recompiler (LLVM)
- Original presentation: 30 FPS at the default 60 Hz VBlank frequency
- Optional presentation: verified 60 FPS at 120 Hz VBlank with frame limit Auto

No game files or decrypted executable content are included.

## Before you start

You need all four of these. The setup cannot work without them:

1. **The USA release of Spartacus Legends (`NPUB30746`), version 01.00 or
   01.06**, installed in RPCS3. Other regions are not supported, and each
   patch section matches one exact executable, so any other build silently
   goes unpatched. Check the **Version** column in RPCS3's game list — it must
  read `01.00` or `01.06`. If it reads anything else, the game's update data
  has to be removed. 01.00 is the build the release regression was run on;
  01.06 support is newer, but its core single-player and persistence paths
  have been live-tested.
2. **An RPCN account**, created and signed in through RPCS3 under
   **Manage > RPCN > RPCN Account**.
3. **RPCS3 closed** while you run the installer. RPCS3 rewrites its own
   configuration files when it exits, which would undo the setup.
4. **The release ZIP extracted to a real folder**, for example
   `C:\Games\SpartacusLegends-Preservation`. Do not run the programs from
   inside the ZIP: Windows unpacks them to a temporary folder and later deletes
   it, taking your saved profile, roster and campaign progress with it.

Both programs are unsigned, so Windows SmartScreen shows
**"Windows protected your PC"** the first time you run each one. Choose
**More info > Run anyway**. Some antivirus tools also flag them, which is a
known false positive for this kind of packaged Python program. Each release
publishes the ZIP's SHA-256 in its release notes if you want to check the
download first.

## Setup

Run these in order. Each step says what you should see.

**1. Close RPCS3.**

**2. Run `SpartacusLegendsPatchInstaller.exe`.** Either drag your RPCS3 folder
onto it, or double-click it and paste the path to that folder (the one
containing `rpcs3.exe`), then confirm.

The installer merges the supplied patch entries into RPCS3's imported patches,
applies the NPUB30746 network configuration, enables the required compatibility
patch, records the detected game version for the server, and clears the game's
PPU cache. Existing configuration files are backed up, and unrelated settings
and optional patch choices are kept. RPCS3 IPC is not required and the
installer does not change its IPC settings. Run the installer again after
installing or removing the 01.06 update so the server selects the same build.

It then re-reads RPCS3's own files and prints the result. Every line must
read `[OK]`, ending in:

```
SETUP OK. Start SpartacusLegendsServer.exe, then cold-boot the game in RPCS3.
```

A line marked `[XX]` is something the installer failed to write; a line marked
`[!!]` is something you need to fix yourself, such as an unsupported game
version or a missing RPCN account. Fix those before continuing — the game
cannot reach the main menu otherwise. You can re-check at any time by running
the installer again with `--verify`, which only reads:

```powershell
SpartacusLegendsPatchInstaller.exe "C:\path\to\RPCS3" --verify
```

**3. Run `SpartacusLegendsServer.exe` and leave its window open.** It should
report:

```
Port check passed: TCP 80, UDP 21000, UDP 21001
All services are ready.
```

Keep this window open for the whole play session. Press Ctrl+C to shut all
listeners down cleanly when you are finished.

**4. Start RPCS3 and cold-boot the game.** Right-click Spartacus Legends and
choose **Boot with default configuration** or simply start it — do not resume a
savestate. Log in normally. The game displays **Saving** and continues to the
main menu.

To confirm the patch actually applied, open RPCS3's log after booting and look
for the line beginning `PPU executable hash:`. It must read
`PPU-81471d050c14f4d20b4027686f8b571dafd32394` for version 01.00 or
`PPU-131aece6ae8526d13307be925f48c87f73c43799` for version 01.06. A different
hash means the game build is not the supported one and no patch will apply to
it.

## Manual setup

Use this only if the installer cannot find your RPCS3 folder. It performs the
same four changes by hand.

- Open `SpartacusLegends_ServerPatch.yml` in a text editor and save a copy
  named exactly `imported_patch.yml` in `<RPCS3 folder>\patches\`. On Windows,
  choose **All files (\*.\*)** when saving so the editor does not add a `.txt`
  extension.
- If `imported_patch.yml` already exists, do not overwrite it. Copy the
  `PPU-81471d050c14f4d20b4027686f8b571dafd32394` section (01.00) and/or the
  `PPU-131aece6ae8526d13307be925f48c87f73c43799` section (01.06) from the
  supplied file into the existing file beneath its single `Version: 1.2`
  header. Keeping both is harmless: RPCS3 applies only the section whose hash
  matches the executable it boots.
- Restart RPCS3, open **Manage > Game Patches**, enable **Spartacus Legends -
  Server emulator compatibility** for NPUB30746 at your installed version, and
  click **Save**. The separately listed optional patches can remain disabled
  unless wanted.
- Right-click the game, open its custom configuration, and under **Network**
  set:

  - **Network Status:** Connected
  - **PSN Status:** RPCN
  - **IP swap list:** `onlineconfigservice.ubi.com=127.0.0.1`

- Right-click the game and choose **Remove > PPU Cache** once after installing
  or changing the patch. This prevents RPCS3 from reusing LLVM code compiled
  from an older patch.

Afterwards, `SpartacusLegendsPatchInstaller.exe "<RPCS3 folder>" --verify`
still reports whether the result is complete.

This follows the RPCS3 Wiki's
[Manually adding custom patches](https://wiki.rpcs3.net/index.php?title=Help:Game_Patches#Manually_adding_custom_patches)
procedure. The filename and location are required: RPCS3 will not recognize a
custom patch saved under another name or outside its `patches` directory.

## Saves, backups, and upgrading

The authoritative server-side saves are beside `SpartacusLegendsServer.exe`.
Because 01.00 and 01.06 use incompatible campaign-object layouts, each build
has its own persistence namespace. The installer writes the active selection
to `data\server-config.json`; normal server startup reads it automatically.

| Build | Native objects | Economy companion |
| --- | --- | --- |
| 01.00 | `data\usercontent\8000000x\1.bin` | `data\profile.json` |
| 01.06 | `data\usercontent\01.06\8000000x\1.bin` | `data\profile-01.06.json` |

The three native object types are:

| Type | Contents | 01.00 size | 01.06 accepted sizes |
| --- | --- | ---: | ---: |
| `80000001` | Profile, currency, fame, and related account values | 4664 | 5560, 5520, or 4664 |
| `80000002` | Campaign, mission, Primus/Nemesis progress | 6148 | 7172 |
| `80000003` | Complete gladiator roster, equipment, and roster state | 21444 | 21448 or 21444 |

The server stores uploads atomically and returns these objects during automatic
save enumeration at the next login. The game also continues to write its normal
RPCS3 `PRG-DATA` save. To back up or move a profile, close both programs and
copy the server's entire `data` directory together with RPCS3's saved data. Do
not copy only one native object: the profile, campaign, roster, economy service,
and local save advance together.

There is deliberately no automatic conversion between 01.00 and 01.06. When
you switch builds, rerun the installer and that build resumes its own last
state. It never overwrites the other build's campaign object. Backing up the
entire `data` directory preserves both namespaces and the selected-version
configuration.

An explicit 01.00-to-01.06 migration is available while RPCS3 and the server
are closed:

```text
.\SpartacusLegendsServer.exe --migrate-01.00-to-01.06
```

The command requires all three exact-size 01.00 native objects plus
`data\profile.json`. It validates their economy balances, creates a timestamped
copy of the complete `data` directory beneath `backups`, refuses to overwrite
any existing 01.06 save, copies the compatible profile layout, extends the
roster with its new zero-initialized trailing word, and extends the campaign
object with the zero-initialized 01.06-only `0x400`-byte area. It then exits
without starting the network server. An audit record is written to
`data\migration-01.00-to-01.06.json`.

If an unwanted fallback 01.06 save was already created, the migration still
refuses it by default. After confirming that the existing 01.06 state may be
discarded, use both explicit flags:

```text
.\SpartacusLegendsServer.exe --migrate-01.00-to-01.06 --replace-existing-01.06
```

The complete `data` directory—including the replaced 01.06 state—is copied to
`backups` before anything is replaced. Do not use the replacement flag if the
existing 01.06 profile contains progress you want to keep.

This conversion was live-validated with a progressed 01.00 profile: all six
gladiators, equipment, purchased slots, currency/fame, and Primus progress
loaded; the client rewrote all three objects at native 01.06 sizes; an Ashur
Nemesis completion and new equipment then survived a full server restart and
cold boot. Keep the reported backup anyway. On the first 01.06 boot,
verify roster/equipment and purchased slots, gold/silver/fame, ordinary
campaign/Primus progress, clean Daily Goals and Nemesis state, then make a new
change and verify it again after a second cold boot.

The compatibility patch retains the local section-1 profile apply as a safe
fallback. RPCS3's `PRG-DATA` profile can initialize fame, currency, and related
values before a native type-1 object exists; when the server has a valid type-1
object, the game's normal server readback then applies the authoritative copy.

`data\roster.json` and `data\campaign.json` are legacy v0.3.x PINE snapshots.
The one-time legacy migration path is available only while serving 01.00;
01.06 never interprets those build-specific captures. `data\profile.json`
remains the 01.00 economy companion, while 01.06 uses
`data\profile-01.06.json`. Neither companion replaces the corresponding
native type-1 object.

### Upgrading from v0.3.x

The server can perform the one-time v0.3-to-native migration while serving
01.00. Before trying a current release:

1. Close RPCS3 and the old preservation server.
2. Back up the old server's complete `data` directory and RPCS3's saved data.
3. Extract v0.4 into a new folder rather than overwriting the working v0.3.x
   installation.
4. Copy the old `data` directory into the new folder so `profile.json` and the
   legacy recovery copies remain available.

On the first 01.00 startup, valid legacy JSON without a native counterpart is
detected and backed up before the one-time migration begins. Completed native
objects do not reactivate PINE. Keep the v0.3.x folder and backup until you
have confirmed profile, campaign, and roster persistence across a cold boot.

If automatic migration needs the legacy roster/campaign restore companion,
enable RPCS3 IPC on port `28012`. The explicit recovery form is:

```text
SpartacusLegendsServer.exe --legacy-roster-bridge
```

This is a temporary compatibility/recovery mode, not normal gameplay. Do not
delete the legacy JSON until the native cold-boot verification succeeds. It is
not used for 01.06.

The existing Legend recovery command also operates only on legacy
`roster.json` plus RPCS3 `PRG-DATA`. To inspect its plan without changing
anything, close both programs and run:

```text
SpartacusLegendsServer.exe --recover-legends "C:\path\to\RPCS3"
```

If the listed names and product IDs are correct, apply it:

```text
SpartacusLegendsServer.exe --recover-legends "C:\path\to\RPCS3" --apply-recovery
```

Recovery retains ordinary gladiators, removes each detected Legend from the
legacy roster and matching `PRG-DATA` manifest, and creates a complete rollback
copy under `recovery-backups`. It does not edit native UserStorage objects.

## Optional patches

For rapid testing, **Spartacus Legends - One-hit fight debug cheat (optional)**
can be enabled in RPCS3's patch manager. It makes the player invulnerable and
ends offline fights with the first damaging hit. Disable it for normal play;
after changing its state, remove the game's PPU cache and cold-boot once.

**Spartacus Legends - Skip startup logo screens (optional)** skips the four
publisher/developer video screens while retaining the legal notices and the
game's normal title transition. Enable it in RPCS3's patch manager if desired;
after changing its state, remove the game's PPU cache and cold-boot once.

**Spartacus Legends - Online matchmaking compatibility (experimental)** enables
RPCN matchmaking for user testing. It has completed repeated Ready Room and
Quickmatch games between two RPCN accounts, including fighter exchange, combat,
correct post-match results, return to the menu, and leaderboard updates. It is
still optional while cancellation, disconnect, and wider network conditions are
tested. Both players must use the same NPUB30746 build, enable this patch,
clear the
game's PPU cache, and cold-boot. Normal RPCN accounts are used; do not share
credentials. If a match fails, report which client hosted, the queue type, and
both RPCS3 logs.

## v0.6.2 release notes

This patch release adds the live-validated v1.06 Daily Login and Shop fidelity
work. Method 8 now restores persisted permanent purchases and consumable
remaining-use counts across cold boots; method 9 consumes one use and persists
the result. v1.06 Boost pages receive their ordinary retail price metadata for
all requested Boost IDs `60000`–`60023`, while method 8 remains authoritative
for ownership and quantities. The live-validated seven-stage Daily Login
service is enabled automatically during normal startup. To disable it for
troubleshooting, start the server with:

```powershell
SpartacusLegendsServer.exe --no-daily-login-rewards
```

Its reward schedule and claims persist atomically.

## What the server runs

- TCP 80: Ubisoft OnlineConfigService replacement
- UDP 21000: Quazal authentication/TicketGranting
- UDP 21001: Quazal secure connection and title services

All listeners bind to `127.0.0.1` by default. Logs are written to the `logs`
folder beside the executable. Normal startup does not connect to RPCS3 IPC.
Port `28012` is used only when `--legacy-roster-bridge` or a recovery operation
is explicitly requested.

Researchers running multiple RPCS3 clients through a LAN address can start the
server with `--host 0.0.0.0 --advertise-host <server-LAN-IP>`. The advertised
address is placed in both the OnlineConfig response and the Quazal auth redirect;
using only `--host` leaves clients redirected to loopback. Ordinary single-client
setups should keep the default loopback configuration.

RPCS3's **Bind address** and `<server-LAN-IP>` are not interchangeable. The
bind address is the source address RPCS3 uses; `--advertise-host` must name the
server address that source can reach. For example, the two-client test setup
used RPCS3 bind/source `192.168.1.10` and server address `192.168.0.153`:

```powershell
SpartacusLegendsServer.exe --host 0.0.0.0 --advertise-host 192.168.0.153
```

Advertising `192.168.1.10` in that setup made the client repeat its initial
Quazal SYN until login timed out. This distinction matters only when an
explicit RPCS3 bind address or multiple clients are in use.

## Troubleshooting

**Check the setup first.** These two commands answer most questions before you
report a problem:

```powershell
SpartacusLegendsPatchInstaller.exe "C:\path\to\RPCS3" --verify
SpartacusLegendsServer.exe --check
```

The first re-reads RPCS3's own configuration and reports each requirement; the
second tests the three ports and exits without starting the server.

**A port is unavailable.** Only one preservation server may run at a time. TCP
80 is also taken by web servers and by Windows' own HTTP service. Find the
program holding it:

```powershell
netstat -ano | findstr ":80 "
```

Then identify the process ID that command prints:

```powershell
tasklist /FI "PID eq <the number>"
```

**RPCS3 shows the service-unavailable dialog.** Verify the IP swap spelling,
that the server window reported all services ready, and that the compatibility
patch is enabled for NPUB30746 at your installed version. Confirm the booted
game's `PPU executable hash:` line in RPCS3's log matches
`81471d050c14f4d20b4027686f8b571dafd32394` (01.00) or
`131aece6ae8526d13307be925f48c87f73c43799` (01.06).

**The setup worked once and then stopped.** If RPCS3 was open while the
installer ran, RPCS3 overwrote the changes when it closed. Close RPCS3 and run
the installer again.

**Profile, roster, or campaign progress does not return.** Check that the three
files beneath `data\usercontent` exist at the exact sizes listed above. Inspect
`logs\online_config.log` for successful `PUT` entries when saving and `GET`
entries during the next login. RPCS3 IPC and PINE are not involved in normal
v0.4 persistence.

**A v0.3.x roster or campaign is missing after upgrading.** Normal v0.4 startup
does not import `roster.json` or `campaign.json`. Restore your backed-up folder
and follow the upgrade warning above; do not allow a new fallback roster to
replace your only legacy copy.

**Progress disappears between sessions.** Check that the server window is not
reporting that it is running from a temporary folder. If it is, close it,
extract the ZIP properly, and run the extracted copy.

## Running from source

Python 3.10 or newer is sufficient; there are no third-party runtime
dependencies:

```powershell
python tools\spartacus_server.py
```

To build the standalone Windows release:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_release.ps1
```

The build script creates `dist\SpartacusLegends-Preservation-v<version>.zip`,
where `<version>` is read from `tools\_version.py` (the single source of truth
for the version).
