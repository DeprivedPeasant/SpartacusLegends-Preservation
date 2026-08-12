# Spartacus Legends preservation server

This project restores the login/bootstrap path for the PS3 version of
Spartacus Legends using a local OnlineConfig and Quazal RendezVous server.
Once bootstrap completes, the preserved single-player game runs locally. The
server reimplements the retired economy and inventory calls, while the patch
restores locally saved fame, currency, levels, purchases, and fight progress
across cold boots. The compatibility patch also completes the post-fight
gladiator-recruitment store refresh, which otherwise retries indefinitely.

Tested configuration:

- Game: Spartacus Legends, NPUB30746 version 01.00
- RPCS3 PPU hash: `81471d050c14f4d20b4027686f8b571dafd32394`
- RPCS3 PPU decoder: Recompiler (LLVM), locked 30 FPS in testing

No game files or decrypted executable content are included.

## Quick setup

Before starting, install the **USA version of Spartacus Legends, version
01.00 (`NPUB30746`)**, in RPCS3. Other regions and game versions are not
supported by the supplied compatibility patch. You also need an **RPCN
account configured and signed in through RPCS3**.

1. Extract the release ZIP and run `SpartacusLegendsServer.exe`. Leave its
   window open while playing. It should report that TCP 80 and UDP 21000/21001
   are ready.
2. Close RPCS3, then run `SpartacusLegendsPatchInstaller.exe` and either drag
   your RPCS3 folder onto it or paste that folder's path. Confirm when prompted.
   The installer merges the three supplied patches, applies the NPUB30746
   network configuration, enables the required compatibility patch and IPC
   server, and clears the game's PPU cache. Existing configuration files are
   backed up and unrelated settings and optional patch choices are retained.

   Manual installation remains available if the updater cannot locate your
   RPCS3 folder:

   - Open `SpartacusLegends_ServerPatch.yml` in a text editor and save a copy
     named exactly `imported_patch.yml` in `<RPCS3 folder>\patches\`. On
     Windows, choose **All files (*.*)** when saving so the editor does not add
     a `.txt` extension.
   - If `imported_patch.yml` already exists, do not overwrite it. Copy the
     `PPU-81471d050c14f4d20b4027686f8b571dafd32394` section from the supplied
     file into the existing file beneath its single `Version: 1.2` header.
   - Restart RPCS3, open **Manage > Game Patches**, enable
     **Spartacus Legends - Server emulator compatibility** for NPUB30746
     01.00, and click **Save**. The separately listed optional patches can
     remain disabled unless wanted.
3. If performing a manual installation, right-click the game and open its
   custom configuration. Under **Network**, set:

   - **Network Status:** Connected
   - **PSN Status:** RPCN
   - **IP swap list:**

     `onlineconfigservice.ubi.com=127.0.0.1`

   In RPCS3, open **Manage > Network Services > IPC**, enable **Enable IPC
   Server**, and leave its port at `28012`. The preservation server uses this
   local PINE connection to preserve complete gladiator rosters and their
   per-gladiator equipment across cold boots.

4. For a manual installation, right-click the game and choose **Remove > PPU
   Cache** once after installing or changing the patch. This prevents RPCS3
   from reusing LLVM code compiled from an older patch.
5. Cold-boot the game and log in normally. The game should display **Saving**
   and continue to the main menu.

## Saves and optional patches

The server stores its economy profile in `data\profile.json`, its complete
gladiator roster (including purchased Ludus slot capacity) in `data\roster.json`,
and its campaign/Primus completion in `data\campaign.json`, all beside the
executable. The game continues to write its normal RPCS3 save data. Back up all
four when moving an established profile to another PC. `roster.json` and
`campaign.json` are created automatically after the first successful login while
RPCS3 IPC is enabled. Older schema-1 roster files are migrated conservatively so
every occupied slot remains available.

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

This follows the RPCS3 Wiki's
[Manually adding custom patches](https://wiki.rpcs3.net/index.php?title=Help:Game_Patches#Manually_adding_custom_patches)
procedure. The filename and location are required: RPCS3 will not recognize a
custom patch saved under another name or outside its `patches` directory.

## What the server runs

- TCP 80: Ubisoft OnlineConfigService replacement
- UDP 21000: Quazal authentication/TicketGranting
- UDP 21001: Quazal secure connection and title services
- TCP 28012 client: automatic PINE roster and campaign capture/restore through
  RPCS3 IPC

All listeners bind to `127.0.0.1` by default. Logs are written to the `logs`
folder beside the executable. Press Ctrl+C in the server window to shut all
three listeners down cleanly.

## Troubleshooting

If startup says a port is unavailable, close the older server instance or
other program using that port. Only one preservation server should run.

If RPCS3 shows the service-unavailable dialog, verify the IP swap spelling,
that the server reported all services ready, and that the compatibility patch
is enabled for NPUB30746 version 01.00.

If currency persists but the gladiator roster or defeated Primus/boss progress
does not, verify RPCS3's IPC Server is enabled on port `28012` and inspect
`logs\roster_bridge.log` (it records both roster and campaign capture/restore).
Do not run another PINE client at the same time as the preservation server.
Researchers can launch with `--no-roster-bridge` to leave IPC available to
another tool; this disables both roster and campaign persistence.

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

The build script creates `dist\SpartacusLegends-Preservation-v0.3.5.zip`.
