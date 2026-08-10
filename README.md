Known Issue: Currently unlocks of money and items is not implemented (they were stored server side), this makes progressing a little difficult at the moment.

# Spartacus Legends preservation server

This project restores the login/bootstrap path for the PS3 version of
Spartacus Legends using a local OnlineConfig and Quazal RendezVous server.
Once bootstrap completes, the preserved single-player game runs locally.

Tested configuration:

- Game: Spartacus Legends, NPUB30746 version 01.00
- RPCS3 PPU hash: `81471d050c14f4d20b4027686f8b571dafd32394`
- RPCS3 PPU decoder: Recompiler (LLVM), locked 30 FPS in testing

No game files or decrypted executable content are included.

## Quick setup

1. Extract the release ZIP and run `SpartacusLegendsServer.exe`. Leave its
   window open while playing. It should report that TCP 80 and UDP 21000/21001
   are ready.
2. Install the supplied custom patch using RPCS3's manual-patch procedure:

   - Open `SpartacusLegends_ServerPatch.yml` in a text editor and save a copy
     named exactly `imported_patch.yml` in `<RPCS3 folder>\patches\`. On
     Windows, choose **All files (*.*)** when saving so the editor does not add
     a `.txt` extension.
   - If `imported_patch.yml` already exists, do not overwrite it. Copy the
     `PPU-81471d050c14f4d20b4027686f8b571dafd32394` section from the supplied
     file into the existing file beneath its single `Version: 1.2` header.
   - Restart RPCS3, open **Manage > Game Patches**, enable
     **Spartacus Legends - Server emulator compatibility** for NPUB30746
     01.00, and click **Save**.
3. Right-click the game and open its custom configuration. Under **Network**,
   set:

   - **Network Status:** Connected
   - **PSN Status:** RPCN
   - **IP swap list:**

     `onlineconfigservice.ubi.com=127.0.0.1`

4. After installing or changing the patch, right-click the game and choose
   **Remove > PPU Cache** once. This prevents RPCS3 from reusing LLVM code
   compiled from an older patch.
5. Cold-boot the game and log in normally. The game should display **Saving**
   and continue to the main menu.

This follows the RPCS3 Wiki's
[Manually adding custom patches](https://wiki.rpcs3.net/index.php?title=Help:Game_Patches#Manually_adding_custom_patches)
procedure. The filename and location are required: RPCS3 will not recognize a
custom patch saved under another name or outside its `patches` directory.

## What the server runs

- TCP 80: Ubisoft OnlineConfigService replacement
- UDP 21000: Quazal authentication/TicketGranting
- UDP 21001: Quazal secure connection and title services

All listeners bind to `127.0.0.1` by default. Logs are written to the `logs`
folder beside the executable. Press Ctrl+C in the server window to shut all
three listeners down cleanly.

## Troubleshooting

If startup says a port is unavailable, close the older server instance or
other program using that port. Only one preservation server should run.

If RPCS3 shows the service-unavailable dialog, verify the IP swap spelling,
that the server reported all services ready, and that the compatibility patch
is enabled for NPUB30746 version 01.00.

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

The build script creates `dist\SpartacusLegends-Preservation-v0.1.0.zip`.
