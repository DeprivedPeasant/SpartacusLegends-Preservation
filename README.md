# Spartacus Legends preservation server

This project restores the login/bootstrap path for the PS3 version of
Spartacus Legends using a local OnlineConfig and Quazal RendezVous server.
Once bootstrap completes, the preserved single-player game runs locally. The
server reimplements the retired economy and inventory calls, while the patch
restores locally saved fame, currency, levels, purchases, and fight progress
across cold boots. The compatibility patch also completes the post-fight
gladiator-recruitment store refresh, which otherwise retries indefinitely.

Shop actions the retired service no longer answers, such as replacing a
gladiator's perk or buying Ludus execution boosts, previously left the game
waiting forever on a loading spinner. The server now answers every shop request,
so an unimplemented feature reports a failure instead of locking the game up.

Tested configuration:

- Game: Spartacus Legends, NPUB30746 version 01.00
- RPCS3 PPU hash: `81471d050c14f4d20b4027686f8b571dafd32394`
- RPCS3 PPU decoder: Recompiler (LLVM), locked 30 FPS in testing

No game files or decrypted executable content are included.

## Before you start

You need all four of these. The setup cannot work without them:

1. **The USA release of Spartacus Legends, version 01.00 (`NPUB30746`)**,
   installed in RPCS3. Other regions and versions are not supported: the patch
   matches one exact executable, so a different build silently goes unpatched.
   Check the **Version** column in RPCS3's game list — it must read `01.00`. If
   it reads anything else, the game's update data has to be removed.
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

The installer merges the three supplied patches into RPCS3's imported patches,
applies the NPUB30746 network configuration, enables the required compatibility
patch, enables the IPC server, and clears the game's PPU cache. Existing
configuration files are backed up, and unrelated settings and optional patch
choices are kept.

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
`PPU-81471d050c14f4d20b4027686f8b571dafd32394`. A different hash means the
game build is not the supported one and no patch will apply to it.

## Manual setup

Use this only if the installer cannot find your RPCS3 folder. It performs the
same four changes by hand.

- Open `SpartacusLegends_ServerPatch.yml` in a text editor and save a copy
  named exactly `imported_patch.yml` in `<RPCS3 folder>\patches\`. On Windows,
  choose **All files (\*.\*)** when saving so the editor does not add a `.txt`
  extension.
- If `imported_patch.yml` already exists, do not overwrite it. Copy the
  `PPU-81471d050c14f4d20b4027686f8b571dafd32394` section from the supplied file
  into the existing file beneath its single `Version: 1.2` header.
- Restart RPCS3, open **Manage > Game Patches**, enable **Spartacus Legends -
  Server emulator compatibility** for NPUB30746 01.00, and click **Save**. The
  separately listed optional patches can remain disabled unless wanted.
- Right-click the game, open its custom configuration, and under **Network**
  set:

  - **Network Status:** Connected
  - **PSN Status:** RPCN
  - **IP swap list:** `onlineconfigservice.ubi.com=127.0.0.1`

- Open **Manage > Network Services > IPC**, enable **Enable IPC Server**, and
  leave its port at `28012`. The preservation server uses this local PINE
  connection to preserve complete gladiator rosters and their per-gladiator
  equipment across cold boots.
- Right-click the game and choose **Remove > PPU Cache** once after installing
  or changing the patch. This prevents RPCS3 from reusing LLVM code compiled
  from an older patch.

Afterwards, `SpartacusLegendsPatchInstaller.exe "<RPCS3 folder>" --verify`
still reports whether the result is complete.

This follows the RPCS3 Wiki's
[Manually adding custom patches](https://wiki.rpcs3.net/index.php?title=Help:Game_Patches#Manually_adding_custom_patches)
procedure. The filename and location are required: RPCS3 will not recognize a
custom patch saved under another name or outside its `patches` directory.

## Saves and optional patches

The server stores its economy profile in `data\profile.json`, its complete
gladiator roster (including purchased Ludus slot capacity) in `data\roster.json`,
and its campaign/Primus completion in `data\campaign.json`, all beside the
executable. The game continues to write its normal RPCS3 save data. When moving
an established profile to another PC, back up those three files together with
RPCS3's own save data. `roster.json` and `campaign.json` are created
automatically after the first successful login while RPCS3 IPC is enabled. Older
schema-1 roster files are migrated conservatively so every occupied slot remains
available.

Roster schema 3 also preserves the relocatable definition block used by Legends.
Unlike procedural gladiators, retail Legend records contain pointers to a live
packed definition/string catalog and cannot safely be replayed as a flat byte
array after a cold boot. The companion captures a bounded `0x200`-byte window
and rebases its internal pointers into fixed unused roster-manager backing
storage before publishing the owned count. The retail layout provides room for
four such Legend windows, including the three present in the affected profile.
Legacy schema-1/2 files containing process-local Legend pointers are never
written back into RPCS3 memory: roster restoration and capture are disabled for
that session, the original JSON is retained for recovery, and the reason is
recorded in `logs\roster_bridge.log`.

To remove owned Legends from any schema-1/2/3 roster so they can be recruited
again, first close both RPCS3 and the preservation server. From a Command Prompt
in the preservation-server folder, inspect the recovery plan without changing
anything:

```text
SpartacusLegendsServer.exe --recover-legends "C:\path\to\RPCS3"
```

If the listed names and product IDs are correct, apply it:

```text
SpartacusLegendsServer.exe --recover-legends "C:\path\to\RPCS3" --apply-recovery
```

Recovery retains ordinary gladiators, removes each detected Legend from
`roster.json`, and removes matching entries from the native `PRG-DATA` manifest
when present. A missing native entry is accepted because the game may already
have discarded it during a failed boot; duplicate native entries are all
removed. `campaign.json` is not altered. A complete timestamped rollback copy
is created under `recovery-backups` before either file is written. Cold-boot
afterward and use Recruit/store refresh to recruit the defeated Legends again.
The command refuses malformed saves, ambiguous RPCS3 users, or a running RPCS3
PINE endpoint instead of guessing.

`campaign.json` preserves defeated Primus battles and district-boss progress
across cold boots. The game saves this progress locally but does not re-apply it
on load, so the same RPCS3 IPC bridge that restores the roster also restores the
campaign completion after each login.

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
tested. Both players must use NPUB30746 01.00, enable this patch, clear the
game's PPU cache, and cold-boot. Normal RPCN accounts are used; do not share
credentials. If a match fails, report which client hosted, the queue type, and
both RPCS3 logs.

## What the server runs

- TCP 80: Ubisoft OnlineConfigService replacement
- UDP 21000: Quazal authentication/TicketGranting
- UDP 21001: Quazal secure connection and title services
- TCP 28012 client: automatic PINE roster and campaign capture/restore through
  RPCS3 IPC

All listeners bind to `127.0.0.1` by default. Logs are written to the `logs`
folder beside the executable.

Researchers running multiple RPCS3 clients through a LAN address can start the
server with `--host 0.0.0.0 --advertise-host <server-LAN-IP>`. The advertised
address is placed in both the OnlineConfig response and the Quazal auth redirect;
using only `--host` leaves clients redirected to loopback. Ordinary single-client
setups should keep the default loopback configuration.

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
patch is enabled for NPUB30746 version 01.00. Confirm the booted game's
`PPU executable hash:` line in RPCS3's log matches
`81471d050c14f4d20b4027686f8b571dafd32394`.

**The setup worked once and then stopped.** If RPCS3 was open while the
installer ran, RPCS3 overwrote the changes when it closed. Close RPCS3 and run
the installer again.

**Currency persists but the gladiator roster or defeated Primus/boss progress
does not.** Verify RPCS3's IPC Server is enabled on port `28012` and inspect
`logs\roster_bridge.log` (it records both roster and campaign capture/restore).
Do not run another PINE client at the same time as the preservation server.
Researchers can launch with `--no-roster-bridge` to leave IPC available to
another tool; this disables both roster and campaign persistence.

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
