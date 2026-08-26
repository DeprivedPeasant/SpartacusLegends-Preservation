# Migrate a Spartacus Legends 1.00 save to 1.06

Use Spartacus Legends Preservation Server **v0.6.1 or newer**. This transfers
your server-side gladiators, equipment, purchased slots, currency, fame, and
Primus campaign progress into version 1.06. New 1.06 features such as Nemesis
progress start cleanly.

## Before you start

1. Close RPCS3 and the preservation server.
2. Make a separate copy of the old server's complete `data` folder and your
   RPCS3 saved data.
3. Extract v0.6.1 into a new permanent folder. Do not run it from inside the
   ZIP.
4. Copy the old server's complete `data` folder into the new v0.6.1 folder.

The migration needs these old 1.00 files:

```text
data\profile.json
data\usercontent\80000001\1.bin
data\usercontent\80000002\1.bin
data\usercontent\80000003\1.bin
```

## Run the migration

Open PowerShell or Command Prompt in the v0.6.1 server folder and run:

```text
.\SpartacusLegendsServer.exe --migrate-01.00-to-01.06
```

If you already launched version 1.06 and it created an unwanted fallback
roster, the safe command above will refuse to overwrite it. Only if that
existing 1.06 progress may be discarded, run:

```text
.\SpartacusLegendsServer.exe --migrate-01.00-to-01.06 --replace-existing-01.06
```

The replacement form backs up the complete `data` folder first, including the
old 1.06 state. Do not use it if you have 1.06 progress you want to keep.

The command should report the backup folder, migrated save paths, and recovered
gold, silver, and fame values. It then exits without starting the server.

## Start version 1.06

1. Run `SpartacusLegendsPatchInstaller.exe` against the RPCS3 folder containing
   your updated 1.06 game.
2. Start `SpartacusLegendsServer.exe` normally.
3. Cold-boot version 1.06 and log in.
4. Verify your complete roster and equipment, purchased slots, currency/fame,
   and previous Primus progress.
5. Make a small change, such as equipping an item or completing a fight. Return
   to the Ludus and wait about 20 seconds before closing RPCS3.
6. Restart the server and cold-boot once more to confirm the new change returns.

Keep the reported backup until both cold boots succeed. If the migration prints
an error, do not delete either save manually; preserve the error message and
the complete `data` folder for troubleshooting.
