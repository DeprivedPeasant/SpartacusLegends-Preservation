# Spartacus Legends Preservation Server

A local preservation server and patch installer for the PS3 version of **Spartacus Legends** (`NPUB30746`) on RPCS3. It restores login, economy, shop, recruitment, and native server-side save persistence so you can play the single-player game locally.

- **Download:** [Latest Release](https://github.com/DeprivedPeasant/SpartacusLegends-Preservation/releases/latest)
- **Community & Support:** [Join the Discord](https://discord.gg/TgJ6n9qDHG) for updates, help, and bug reports

> No game files or copyrighted content are included.

---

## Requirements

Before you start, make sure you have:

1. **Spartacus Legends (USA — `NPUB30746`)** installed in RPCS3, version **`01.00`** or **`01.06`** (check the **Version** column in RPCS3). Other regions and versions are not supported.
2. **An RPCN account** signed in through RPCS3 under **Manage > RPCN > RPCN Account**.
3. **RPCS3 closed** while running setup (RPCS3 overwrites its config files when it exits).

---

## Installation & Setup

### 1. Download and extract

1. Download the latest ZIP from [Releases](https://github.com/DeprivedPeasant/SpartacusLegends-Preservation/releases/latest).
2. Extract the entire ZIP to a permanent folder (for example, `C:\Games\SpartacusLegends-Preservation`).
   - Do **not** run the app from inside the ZIP — Windows unpacks it to a temporary folder and will later delete your saves.
   - Keep `SpartacusLegendsServerGUI.exe` in the same folder as `SpartacusLegendsServerGUI_runtime`.

> [!NOTE]
> The executables are unsigned, so Windows SmartScreen may show **"Windows protected your PC"** on first launch. Click **More info > Run anyway**. Some antivirus tools may also flag packaged Python apps as a false positive; each release includes a SHA-256 checksum if you want to verify the download.

### 2. Run Patch Setup

1. Make sure **RPCS3 is closed**.
2. Open **`SpartacusLegendsServerGUI.exe`**.
   - Available in **English, Spanish, and Brazilian Portuguese** (follows your Windows language by default, or change it from the bottom-left menu).
3. On the **Patch setup** page, select your RPCS3 folder (the folder containing `rpcs3.exe`).
4. Click **Install / repair setup**.
5. Confirm every item in the checklist reads **OK**. If you see a **WARNING** (such as an unsupported game version or missing RPCN account), fix it before continuing.

> Re-run **Patch setup** anytime you install or remove the `01.06` game update.

### 3. Start the server and play

1. Open the **Server** page in the app and click **Start server**. Wait until the status reads **Ready** and leave the app open while you play.
2. Launch RPCS3 and boot *Spartacus Legends* normally (do **not** resume a savestate).
3. Log in as usual. The app status will switch to **Game connected** and show when your save loads and updates.

### 4. Closing the game safely

When you finish playing:

1. Return to the **Ludus** and wait about **20 seconds** for the game's autosave to finish.
2. Close **RPCS3**.
3. Click **Stop server** in the app.

---

## Features in the App

- **Server:** Start/stop the server and view plain-language save, load, and connection activity.
- **Player:** Edit gold, silver, and fame. Gold and silver can be edited while playing (applied after your next fight or shop purchase); on `01.00`, fame must be edited with the server stopped. Every offline edit creates a backup in `data\backups`.
- **Items:** View and edit owned items, Boost uses *(live edits are experimental)*, and purchased Ludus slots.
- **Patch setup:** Automatically configures RPCS3 patches, network settings, PPU cache clearing, and game version detection. Includes experimental adaptive patching if your executable is a different dump.

---

## Optional Enhancements

### 60 FPS Mode

Spartacus Legends runs cleanly at 60 FPS in RPCS3 without modifying the game:

1. Right-click the game in RPCS3 → **Change Custom Configuration**.
2. Set **Advanced > VBlank Frequency** to **120 Hz**.
3. Leave **GPU > Frame limit** on **Auto**.

*(Leave VBlank Frequency at 60 Hz for the original 30 FPS presentation if your PC can't hold 60 FPS.)*

### Optional Patches

You can toggle these in RPCS3 under **Manage > Game Patches** (after toggling any patch, right-click the game → **Remove > PPU Cache** and cold-boot):

- **Skip startup logo screens** — Skips the intro publisher/developer videos.
- **One-hit fight debug cheat** — Makes you invulnerable and ends offline fights in one hit (for testing).
- **Online matchmaking compatibility (experimental)** — Enables RPCN matchmaking between two players on the same version (`01.00` or `01.06`).

---

## Saves, Backups & Updating

- Your server-side saves are stored in the **`data\`** folder next to the app (`01.00` and `01.06` saves are kept separate).
- **To back up your progress:** Close RPCS3 and the server, then copy both the server's `data\` folder and your RPCS3 save folder (`PRG-DATA`).
- **To update to a new release:** Close RPCS3 and the server, extract the new release to a folder, and copy your existing `data\` folder into it.
- **Migrating a `01.00` save to `01.06`:** See [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md).

---

## Troubleshooting

**The game says the service is unavailable**
- Make sure the app's Server page says **Ready** before booting the game.
- Check **Patch setup** and make sure all items are **OK** (and that RPCS3 was closed when you ran setup).

**A port is already in use (TCP 80, UDP 21000, or UDP 21001)**
- Make sure another copy of the server isn't already running.
- Port 80 can also be held by another local web server or Windows HTTP service. Run `netstat -ano | findstr ":80 "` in PowerShell to find the PID using it.

**Progress didn't save / version mismatch error**
- If you updated or downgraded between `01.00` and `01.06`, close RPCS3, stop the server, and run **Patch setup** again so the server matches your installed game version.

**Saves disappeared between sessions**
- Make sure you extracted the ZIP to a permanent folder and aren't running the app from inside the archive or a temporary directory.

**Windows "Low integrity" warning**
- Move the extracted folder to a normal location like `C:\Games\` or your Desktop and run it from there.

Still stuck? Join the [Discord](https://discord.gg/TgJ6n9qDHG) and share the files from your `logs\` folder along with `RPCS3.log`.

---

## Advanced

<details>
<summary>Manual RPCS3 setup (if automatic Patch setup can't find RPCS3)</summary>

1. Copy `SpartacusLegends_ServerPatch.yml` into `<RPCS3 folder>\patches\imported_patch.yml`.
   - If `imported_patch.yml` already exists, do **not** overwrite it — append the `PPU-81471d050c14f4d20b4027686f8b571dafd32394` (`01.00`) and/or `PPU-131aece6ae8526d13307be925f48c87f73c43799` (`01.06`) sections beneath its existing `Version: 1.2` header.
2. Open RPCS3 → **Manage > Game Patches**, enable **Spartacus Legends - Server emulator compatibility** for your version, and click **Save**.
3. Right-click the game → **Change Custom Configuration** → **Network**:
   - **Network Status:** `Connected`
   - **PSN Status:** `RPCN`
   - **IP swap list:** `onlineconfigservice.ubi.com=127.0.0.1`
4. Right-click the game → **Remove > PPU Cache**.

</details>

<details>
<summary>Console tools & command-line options</summary>

`SpartacusLegendsServer.exe` and `SpartacusLegendsPatchInstaller.exe` are included for scripted or advanced use (English only). Do not run the console server at the same time as the GUI server.

```powershell
# Verify RPCS3 setup without modifying anything
.\SpartacusLegendsPatchInstaller.exe "C:\path\to\RPCS3" --verify

# Test required ports (TCP 80, UDP 21000, UDP 21001) without starting the server
.\SpartacusLegendsServer.exe --check

# Start the console server directly (skip GUI prompt)
.\SpartacusLegendsServer.exe --console

# Explicitly select a game version or disable daily login rewards
.\SpartacusLegendsServer.exe --title-version 01.06
.\SpartacusLegendsServer.exe --no-daily-login-rewards

# Listen on LAN for multi-client setups
.\SpartacusLegendsServer.exe --host 0.0.0.0 --advertise-host <server-LAN-IP>
```

</details>

<details>
<summary>Running and building from source</summary>

Requires Python 3.10+. The console server has no third-party dependencies:

```powershell
python tools\spartacus_server.py
```

For the Qt GUI:

```powershell
python -m pip install "PySide6>=6.7,<7"
python tools\spartacus_gui.py
```

To build the standalone Windows release ZIP:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_release.ps1
```

</details>
