# Agent operating guide

Read `CURRENT_HANDOFF.md` before doing project work. It is the current
checkpoint. `notes/00-plan.md` is a chronological research archive with many
superseded conclusions and is never the starting document.

## Economical delegation

The `multimodels` MCP server is available for economical delegation. Confirm
the currently enabled model IDs with `list_models` before delegating. The
expected models are:

- `deepseek:deepseek-v4-flash`
- `zai:glm-5.3-flash`

Use `delegate_task` only for bounded, token-heavy subtasks. Delegate
asynchronously by default and continue useful local work; retrieve the result
later with `check_task` rather than polling in a loop. Critically verify every
delegated answer before using it or applying changes. Do not send secrets or
unnecessary files to a delegated model.

Vastly prefer `zai:glm-5.3-flash` for coding, debugging, protocol analysis,
and other work requiring technical judgment. It is the default delegated model
for substantive engineering tasks. Use `deepseek:deepseek-v4-flash` primarily
for very fast, straightforward, low-judgment work such as broad searches,
mechanical summaries, or initial triage; do not rely on it for nuanced coding
conclusions without especially careful independent verification.

## Project and supported build

- Repository: `C:\Users\Jake\Coding\SpartacusLegends-RE`
- Game: Spartacus Legends, USA PSN release `NPUB30746`, version `01.00`
- PPU hash: `81471d050c14f4d20b4027686f8b571dafd32394`
- The game is 64-bit big-endian PowerPC with 32-bit addresses.
- The current shipped baseline is recorded in `CURRENT_HANDOFF.md`; verify it
  with Git rather than assuming the handoff is still current.

## Authority and safety

- Never modify, delete, stage, or publish player save data unless Jake
  explicitly requests it. This includes `data`, RPCS3 `PRG-DATA`, and live-test
  copies beneath `.build`.
- Treat `data\usercontent` as the authoritative native server-save directory.
  `profile.json` remains the economy service's companion database;
  `roster.json` and `campaign.json` are legacy/migration inputs.
- Preserve dirty worktrees. Inspect status and diffs, then stage only named
  project files. Never use `git add .`, `git add -A`, destructive reset, or
  broad cleanup commands.
- Do not commit, tag, push, publish a release, or mutate GitHub state without
  explicit authorization for that release operation.
- Do not fabricate binary formats, save objects, patch addresses, or response
  fields. Mark hypotheses as hypotheses and require static, wire, or live
  evidence before changing production behavior.
- Research outputs in `.build`, `captures`, `ghidra_project`, and most of
  `notes` are local evidence, not automatically release inputs. Do not commit
  generated artifacts merely because they exist.

## Persistence invariants

- Normal v0.4+ startup uses the game's native UserStorage path and must not
  connect to RPCS3 IPC/PINE.
- PINE is allowed only for explicitly selected legacy migration, recovery, or
  research. The current opt-in runtime flag is `--legacy-roster-bridge`.
- The Commerce2 compatibility patch remains required. Do not remove it on the
  assumption that server emulation can replace RPCS3's incomplete Commerce2
  result.
- The local section-1 profile patch remains a deliberate safe fallback before
  a native type-1 object exists. Native type-1 readback is authoritative once
  present.
- Purchased Ludus slots are separate entitlements. They are restored by
  replaying persisted products `80002..80007` through Monetization method 8;
  they are not safely inferred from occupied roster count.
- Monetization method 8 uses a packed Quazal DateTime, not Unix seconds.

## Live-test protocol

- Never restart the preservation server while the game session is active. The
  UDP transport may continue pinging while the RMC session is already invalid.
- After changing an RPCS3 code patch, clear the NPUB30746 PPU cache and cold
  boot. Savestates are not valid persistence tests.
- Before shutdown, return to the Ludus/main menu and allow roughly 20 seconds
  for native autosaves. Confirm the server received exact-size PUTs.
- Close RPCS3 before the server. Verify files and hashes before the next boot.
- A release persistence test requires two cold boots: restore existing state,
  make a new roster/campaign/profile change, save, then restore that new state.
- Prefer a bounded local PINE script or the RPCS3 debugger GUI over high-rate
  interactive tool polling. Prior interactive polling caused Codex hangs and
  PINE reply starvation.
- One PINE client may control an RPCS3 instance at a time. Stop any companion
  before attaching a research watcher.

## Working with Jake in the RPCS3 debugger

- Jake is colorblind. Never identify the current instruction or breakpoint by
  highlight color. Always state the exact hexadecimal PC/address and thread.
- A selected row is not necessarily the current PC. Ask for or use the PC
  marker/address explicitly.
- RPCS3 has Step and Step Over, but no Step Out in the relevant GUI. Do not call
  Step Over equivalent to Step Out.
- Before a live breakpoint run, give the expected thread, exact address, what
  register/memory value to report, and the next address to continue to.
- Avoid clusters of nearby breakpoints when one breakpoint plus a register or
  single-step observation can answer the question.
- Keep user-visible reasoning and timing instructions in chat. Do not hide a
  required WAIT/GO transition inside a tool call.

## Tooling and validation

- Use PowerShell commands from the repository root.
- Prefer existing scripts in `scripts` and `tools` over retyping research
  logic. Use `rg`/`rg --files` for discovery.
- Ghidra project: `ghidra_project\SpartacusLegends`, program `EBOOT.elf`.
- Decrypted binary: `decrypted\EBOOT.elf`.
- Current Ghidra launcher:
  `C:\Users\Jake\Downloads\Compressed\ghidra_12.1.2_PUBLIC_20260605\ghidra_12.1.2_PUBLIC\support\analyzeHeadless.bat`
- Known two-client RPCS3 installs:
  `C:\Users\Jake\Desktop\Clean RPCS3\rpcs3-A` and
  `C:\Users\Jake\Desktop\Clean RPCS3\rpcs3-B`.
- Baseline automated validation:

  ```powershell
  python -m unittest discover -s tests -p 'test_*.py'
  python -m py_compile tools\prudp_server.py tools\spartacus_server.py tools\patch_installer.py tools\UbiOnlineConfigService\spartacus_onlineconfig.py
  git diff --check
  ```

- Both distributed patch files must remain byte-identical:
  `packaging\SpartacusLegends_ServerPatch.yml` and
  `patches\SpartacusLegends_OfflineFix.yml`.
- Build standalone releases only with:

  ```powershell
  powershell -ExecutionPolicy Bypass -File packaging\build_release.ps1
  ```

## Documentation routing

- `README.md`: current user-facing setup and shipped behavior.
- `CURRENT_HANDOFF.md`: current engineering checkpoint and next work.
- `notes/07-v0.4-save-migration-plan.md`: approved deferred migration design.
- `notes/02-original-profile-sync-plan.md`: native-save discovery evidence.
- `notes/04-remote-config-static-analysis.md`: remote-config/static evidence.
- `notes/03-playtest-regressions-plan.md`: historical shop and persistence
  findings; its PINE-era baseline is partly superseded.
- `notes/09-multiplayer-handoff.md`: multiplayer-only evidence.
- `notes/11-next-session-prompt.md`: stale multiplayer prompt; do not use as a
  general handoff.
- `notes/00-plan.md`: full historical notebook; consult only for a targeted
  question after reading the current handoff.
