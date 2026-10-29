"""Offline save-editor tests.

Everything runs against a ``tempfile.TemporaryDirectory``; nothing here reads or
writes the repository's ``data/`` directory.  The native profile is synthetic
bytes, not copied from an EBOOT or a live save.
"""

import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import socket
import unittest
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import migration_coordinator  # noqa: E402  (tools modules import siblings)
import prudp_server  # noqa: E402
import save_editor  # noqa: E402
import title_save_migration  # noqa: E402


BALANCE_OFFSETS = title_save_migration.PROFILE_BALANCE_OFFSETS
NATIVE_SIZE = save_editor.NATIVE_PROFILE_SIZE


def patterned_native(gold=1000, silver=2000, fame=30):
    """A deterministic 4664-byte profile with the three balance words set."""
    payload = bytearray(
        (index * 37 + 11) % 256 for index in range(NATIVE_SIZE))
    values = {"gold": gold, "silver": silver, "fame": fame}
    for name, offset in BALANCE_OFFSETS.items():
        struct.pack_into(">I", payload, offset, values[name])
    return bytes(payload)


def write_native(data_dir, title_version="01.00", payload=None, **balances):
    paths = save_editor.title_paths(data_dir, title_version)
    if payload is None:
        payload = patterned_native(**balances)
    paths.native_profile_path.parent.mkdir(parents=True, exist_ok=True)
    paths.native_profile_path.write_bytes(payload)
    return payload


def write_companion(data_dir, document, title_version="01.00"):
    paths = save_editor.title_paths(data_dir, title_version)
    paths.companion_path.parent.mkdir(parents=True, exist_ok=True)
    paths.companion_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return paths.companion_path


def native_words(payload):
    return {
        name: struct.unpack_from(">I", payload, offset)[0]
        for name, offset in BALANCE_OFFSETS.items()
    }


# Captured before any test patches it, so the probe itself can be exercised.
REAL_EXTERNAL_SERVER_REASON = save_editor.external_server_reason


class SaveEditorTestCase(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        # The real probe binds the live Quazal ports; keep unrelated tests
        # independent of whatever is running on this machine.
        probe = mock.patch.object(save_editor, "external_server_reason",
                                  return_value=None)
        self.external_probe = probe.start()
        self.addCleanup(probe.stop)
        self.data_dir = Path(self._temp.name) / "data"
        self.data_dir.mkdir()
        self.paths = save_editor.title_paths(self.data_dir, "01.00")
        self.companion_document = {
            "version": 1,
            "gold": 1000,
            "silver": 2000,
            "fame": 30,
            "owned_items": [10236, 60001, 80002],
            "item_quantities": {"60001": 5},
            "claimed_challenges": [1, 2],
            "daily_challenges": {"date": "", "claimed": []},
            "note_kept": {"nested": [True, "value"]},
        }
        self.original_native = write_native(
            self.data_dir, gold=1000, silver=2000, fame=30)
        write_companion(self.data_dir, self.companion_document)

    def native_bytes(self):
        return self.paths.native_profile_path.read_bytes()

    def companion_document_on_disk(self):
        return json.loads(self.paths.companion_path.read_text(encoding="utf-8"))


class PathTests(SaveEditorTestCase):
    def test_v100_uses_the_shipped_profile_and_usercontent_layout(self):
        self.assertEqual(
            self.paths.companion_path, self.data_dir / "profile.json")
        self.assertEqual(
            self.paths.user_content_dir, self.data_dir / "usercontent")
        self.assertEqual(
            self.paths.native_profile_path,
            self.data_dir / "usercontent" / "80000001" / "1.bin")

    def test_v106_uses_its_own_companion_and_namespaced_usercontent(self):
        # A 01.06-written profile: 0x15B8 bytes, zero in the 01.00 balance
        # words (as in every live 01.06 save), arbitrary content elsewhere.
        native = bytes((index * 7 + 3) & 0xFF for index in range(0x15B8))
        native = bytearray(native)
        for offset in BALANCE_OFFSETS.values():
            struct.pack_into(">I", native, offset, 0)
        native = write_native(self.data_dir, "01.06", payload=bytes(native))
        write_companion(self.data_dir, {
            "gold": 5, "silver": 6, "fame": 7, "owned_items": [],
        }, "01.06")

        v106 = save_editor.title_paths(self.data_dir, "01.06")
        self.assertEqual(v106.title_version.value, "01.06")
        self.assertEqual(
            v106.companion_path, self.data_dir / "profile-01.06.json")
        self.assertEqual(
            v106.user_content_dir,
            self.data_dir / "usercontent" / "01.06")
        self.assertEqual(
            v106.native_profile_path,
            self.data_dir / "usercontent" / "01.06" / "80000001" / "1.bin")

        state = save_editor.load(self.data_dir, "01.06")
        self.assertTrue(state.native_present)
        self.assertFalse(state.native_holds_balances)
        self.assertEqual(state.native_size, 0x15B8)
        self.assertIsNone(state.native_balances)
        self.assertFalse(state.mismatch)
        self.assertEqual(state.effective_balances,
                         {"gold": 5, "silver": 6, "fame": 7})

        result = save_editor.save(
            self.data_dir, "01.06", gold=50, silver=60, fame=70)
        # 01.06 balances live only in the companion (Shop m19/m20 push them);
        # the native object is never parsed or rewritten.
        self.assertFalse(result.native_written)
        self.assertEqual(v106.native_profile_path.read_bytes(), native)
        companion = json.loads(v106.companion_path.read_text("utf-8"))
        self.assertEqual(
            (companion["gold"], companion["silver"], companion["fame"]),
            (50, 60, 70))
        self.assertEqual(result.warnings, ())
        # The 01.00 files must not have been touched by a 01.06 save.
        self.assertEqual(native_words(self.native_bytes()),
                         {"gold": 1000, "silver": 2000, "fame": 30})
        self.assertEqual(self.companion_document_on_disk()["gold"], 1000)

    def test_unknown_title_version_is_rejected(self):
        with self.assertRaises(ValueError):
            save_editor.title_paths(self.data_dir, "02.00")


class LoadTests(SaveEditorTestCase):
    def test_load_reads_both_balances_and_reports_no_mismatch(self):
        state = save_editor.load(self.data_dir)
        self.assertTrue(state.native_present)
        self.assertEqual(state.native_size, NATIVE_SIZE)
        self.assertEqual(state.native_balances,
                         {"gold": 1000, "silver": 2000, "fame": 30})
        self.assertEqual(state.companion_balances,
                         {"gold": 1000, "silver": 2000, "fame": 30})
        self.assertFalse(state.mismatch)
        self.assertEqual(state.mismatch_fields, ())
        self.assertEqual(state.owned_items, (10236, 60001, 80002))
        self.assertEqual(state.item_quantities, {60001: 5})
        self.assertEqual(state.effective_balances,
                         {"gold": 1000, "silver": 2000, "fame": 30})

    def test_mismatch_is_flagged_per_field(self):
        write_native(self.data_dir, gold=1000, silver=9999, fame=30)
        state = save_editor.load(self.data_dir)
        self.assertTrue(state.mismatch)
        self.assertEqual(state.mismatch_fields, ("silver",))
        self.assertEqual(state.effective_balances["silver"], 9999)

    def test_missing_native_profile_loads_companion_only(self):
        self.paths.native_profile_path.unlink()
        state = save_editor.load(self.data_dir)
        self.assertFalse(state.native_present)
        self.assertIsNone(state.native_balances)
        self.assertIsNone(state.native_size)
        self.assertEqual(state.effective_balances,
                         {"gold": 1000, "silver": 2000, "fame": 30})
        self.assertFalse(state.mismatch)

    def test_wrong_sized_native_profile_is_refused_not_treated_as_absent(self):
        self.paths.native_profile_path.write_bytes(b"\x00" * 100)
        with self.assertRaises(save_editor.SaveEditorError) as caught:
            save_editor.load(self.data_dir)
        self.assertIn("100 bytes", str(caught.exception))
        self.assertIn(str(NATIVE_SIZE), str(caught.exception))

    def test_invalid_companion_json_is_refused(self):
        self.paths.companion_path.write_text("not json", encoding="utf-8")
        with self.assertRaises(save_editor.SaveEditorError):
            save_editor.load(self.data_dir)

    def test_companion_is_read_through_economy_store_normalisation(self):
        write_companion(self.data_dir, {
            "gold": -5,
            "silver": 250,
            "owned_items": [10236, prudp_server.STORE_REFRESH_SENTINEL, 10236],
            "item_quantities": {"10236": 500},
        })
        state = save_editor.load(self.data_dir)
        self.assertEqual(state.companion_balances["gold"], 0)
        self.assertEqual(state.owned_items, (10236,))
        self.assertEqual(state.item_quantities, {10236: 99})


class SaveBalanceTests(SaveEditorTestCase):
    def test_balance_round_trip_updates_both_files(self):
        result = save_editor.save(
            self.data_dir, gold=222, silver=333, fame=44)
        self.assertTrue(result.native_written)
        self.assertTrue(result.companion_written)
        self.assertFalse(result.companion_only)
        self.assertEqual(result.balances,
                         {"gold": 222, "silver": 333, "fame": 44})

        state = save_editor.load(self.data_dir)
        self.assertEqual(state.native_balances,
                         {"gold": 222, "silver": 333, "fame": 44})
        self.assertEqual(state.companion_balances,
                         {"gold": 222, "silver": 333, "fame": 44})
        self.assertFalse(state.mismatch)

        store = prudp_server.EconomyStore(str(self.paths.companion_path))
        self.assertEqual(
            (store.data["gold"], store.data["silver"], store.data["fame"]),
            (222, 333, 44))

    def test_every_byte_outside_the_three_words_is_unchanged(self):
        original = self.native_bytes()
        save_editor.save(self.data_dir, gold=111, silver=222, fame=333)
        edited = self.native_bytes()

        self.assertEqual(len(edited), len(original))
        for name, offset in BALANCE_OFFSETS.items():
            value = native_words(edited)[name]
            self.assertEqual(
                edited[offset:offset + 4], struct.pack(">I", value))
        # Slice hashes cover the unchanged regions between and around the words.
        self.assertEqual(edited[0x00:0x04], original[0x00:0x04])
        self.assertEqual(edited[0x08:0x0C], original[0x08:0x0C])
        self.assertEqual(edited[0x10:0x14], original[0x10:0x14])
        self.assertEqual(edited[0x18:], original[0x18:])
        self.assertEqual(
            hashlib.sha256(edited[0x18:]).hexdigest(),
            hashlib.sha256(original[0x18:]).hexdigest())

    def test_unedited_companion_keys_are_preserved(self):
        before = self.companion_document_on_disk()
        save_editor.save(self.data_dir, gold=7)
        after = self.companion_document_on_disk()

        for key in ("version", "owned_items", "item_quantities",
                    "claimed_challenges", "daily_challenges", "note_kept"):
            self.assertEqual(after[key], before[key], key)
        # Passing only gold keeps the other two companion balances.
        self.assertEqual((after["silver"], after["fame"]), (2000, 30))

    def test_wrong_sized_native_profile_is_refused_before_any_write(self):
        self.paths.native_profile_path.write_bytes(b"\x01" * (NATIVE_SIZE - 1))
        companion_before = self.paths.companion_path.read_bytes()
        with self.assertRaises(save_editor.SaveEditorError) as caught:
            save_editor.save(self.data_dir, gold=1)
        self.assertIn("exactly", str(caught.exception))
        self.assertEqual(self.paths.companion_path.read_bytes(),
                         companion_before)
        self.assertFalse((self.data_dir / "backups").exists())

    def test_missing_native_profile_edits_only_the_companion(self):
        self.paths.native_profile_path.unlink()
        result = save_editor.save(self.data_dir, gold=42, silver=43, fame=44)

        self.assertFalse(result.native_written)
        self.assertTrue(result.companion_only)
        self.assertFalse(self.paths.native_profile_path.exists())
        self.assertTrue(any("1.bin" in warning for warning in result.warnings))
        self.assertEqual(self.companion_document_on_disk()["gold"], 42)
        state = save_editor.load(self.data_dir)
        self.assertFalse(state.native_present)
        self.assertEqual(state.companion_balances,
                         {"gold": 42, "silver": 43, "fame": 44})

    def test_values_are_clamped_to_u32_and_large_values_are_flagged(self):
        result = save_editor.save(
            self.data_dir, gold=2 ** 32 + 7, silver=10_000_000)
        self.assertEqual(result.balances["gold"], 0xFFFFFFFF)
        self.assertEqual(result.balances["silver"], 10_000_000)
        warnings = " ".join(result.warnings)
        self.assertIn("32 bits", warnings)
        self.assertIn("9,999,999", warnings)
        self.assertEqual(
            save_editor.load(self.data_dir).native_balances["silver"],
            10_000_000)

    def test_negative_values_are_clamped_to_zero(self):
        result = save_editor.save(self.data_dir, gold=-5)
        self.assertEqual(result.balances["gold"], 0)
        self.assertTrue(any("negative" in warning
                            for warning in result.warnings))

    def test_refuses_while_the_server_is_running(self):
        native_before = self.native_bytes()
        companion_before = self.paths.companion_path.read_bytes()
        with self.assertRaises(save_editor.SaveEditorError) as caught:
            save_editor.save(self.data_dir, gold=1, server_running=True)
        self.assertIn("server is running", str(caught.exception))
        self.assertEqual(self.native_bytes(), native_before)
        self.assertEqual(self.paths.companion_path.read_bytes(),
                         companion_before)
        self.assertFalse((self.data_dir / "backups").exists())


class ExternalServerTests(SaveEditorTestCase):
    REASON = "UDP port 21001 on 127.0.0.1 is already in use (test)"

    def assert_untouched(self, native_before, companion_before):
        self.assertEqual(self.native_bytes(), native_before)
        self.assertEqual(self.paths.companion_path.read_bytes(),
                         companion_before)

    def test_save_refuses_when_a_server_runs_outside_the_gui(self):
        self.external_probe.return_value = self.REASON
        native_before = self.native_bytes()
        companion_before = self.paths.companion_path.read_bytes()
        with self.assertRaises(save_editor.SaveEditorError) as caught:
            save_editor.save(self.data_dir, gold=1, server_running=False)
        self.assertIn("refusing to edit save files", str(caught.exception))
        self.assertIn(self.REASON, str(caught.exception))
        self.assert_untouched(native_before, companion_before)
        self.assertFalse((self.data_dir / "backups").exists())

    def test_restore_refuses_when_a_server_runs_outside_the_gui(self):
        result = save_editor.save(self.data_dir, gold=5)
        native_before = self.native_bytes()
        companion_before = self.paths.companion_path.read_bytes()
        self.external_probe.return_value = self.REASON
        with self.assertRaises(save_editor.SaveEditorError) as caught:
            save_editor.restore_backup(self.data_dir, result.backup_dir.name)
        self.assertIn("refusing to restore a backup", str(caught.exception))
        self.assert_untouched(native_before, companion_before)

    def test_save_proceeds_when_no_server_is_found(self):
        self.external_probe.return_value = None
        save_editor.save(self.data_dir, gold=7)
        self.assertEqual(self.companion_document_on_disk()["gold"], 7)
        self.external_probe.assert_called()

    def test_probe_detects_a_held_udp_port_and_clears_after_release(self):
        holder = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                holder.setsockopt(socket.SOL_SOCKET,
                                  socket.SO_EXCLUSIVEADDRUSE, 1)
            holder.bind(("127.0.0.1", 0))
            port = holder.getsockname()[1]
            reason = REAL_EXTERNAL_SERVER_REASON(
                "127.0.0.1", (port,))
            self.assertIsNotNone(reason)
            self.assertIn(f"UDP port {port}", reason)
        finally:
            holder.close()
        self.assertIsNone(
            REAL_EXTERNAL_SERVER_REASON("127.0.0.1", (port,)))

    def test_probe_targets_only_the_quazal_ports(self):
        # Port 80 is often held by IIS/http.sys; it must not block offline edits.
        self.assertEqual(save_editor.SERVER_PROBE_PORTS, (21000, 21001))


class ItemEditingTests(SaveEditorTestCase):
    def test_grouping_uses_only_documented_id_ranges(self):
        groups = save_editor.group_items([
            10236, 120051, 25000, 30001, 49999, 50002, 60001, 60064,
            80002, 80008, 7,
        ])
        self.assertEqual(list(groups), [
            "1xxxx", "2xxxx", "3xxxx", "4xxxx",
            save_editor.GROUP_BOOSTS, save_editor.GROUP_SLOTS,
            save_editor.GROUP_OTHER,
        ])
        self.assertEqual(groups["1xxxx"], (10236,))
        self.assertEqual(groups["2xxxx"], (25000,))
        self.assertEqual(groups["3xxxx"], (30001,))
        self.assertEqual(groups["4xxxx"], (49999,))
        self.assertEqual(groups[save_editor.GROUP_BOOSTS], (60001,))
        self.assertEqual(groups[save_editor.GROUP_SLOTS], (80002,))
        self.assertEqual(groups[save_editor.GROUP_OTHER],
                         (7, 50002, 60064, 80008, 120051))

    def test_range_predicates(self):
        self.assertTrue(save_editor.is_boost(60000))
        self.assertTrue(save_editor.is_boost(60063))
        self.assertFalse(save_editor.is_boost(60064))
        self.assertTrue(save_editor.is_ludus_slot(80002))
        self.assertTrue(save_editor.is_ludus_slot(80007))
        self.assertFalse(save_editor.is_ludus_slot(80008))
        self.assertTrue(save_editor.quantity_editable(60006))
        self.assertFalse(save_editor.quantity_editable(10236))

    def test_add_remove_and_quantity_helpers_validate_input(self):
        owned = save_editor.add_owned_item((10236,), 60001)
        self.assertEqual(owned, (10236, 60001))
        with self.assertRaises(save_editor.SaveEditorError):
            save_editor.add_owned_item(owned, prudp_server.STORE_REFRESH_SENTINEL)
        with self.assertRaises(save_editor.SaveEditorError):
            save_editor.add_owned_item(owned, "not a number")

        removed = save_editor.remove_owned_item(owned, 60001)
        self.assertEqual(removed, (10236,))
        with self.assertRaises(save_editor.SaveEditorError):
            save_editor.remove_owned_item(removed, 60001)

        quantities = save_editor.set_item_quantity({}, owned, 60001, 7)
        self.assertEqual(quantities, {60001: 7})
        for invalid in (-1, 100, True, "many"):
            with self.subTest(quantity=invalid):
                with self.assertRaises(save_editor.SaveEditorError):
                    save_editor.set_item_quantity({}, owned, 60001, invalid)

    def test_effective_quantity_mirrors_the_economy_store_fallback(self):
        self.assertEqual(
            save_editor.effective_quantity((60020,), {}, 60020), 5)
        self.assertEqual(
            save_editor.effective_quantity((60005,), {}, 60005), 1)
        self.assertEqual(
            save_editor.effective_quantity((60005,), {60005: 0}, 60005), 0)
        self.assertEqual(
            save_editor.effective_quantity((), {}, 60005), 0)

    def test_offline_item_edits_round_trip(self):
        owned = save_editor.load(self.data_dir).owned_items
        owned = save_editor.add_owned_item(owned, 60020)
        owned = save_editor.remove_owned_item(owned, 80002)
        quantities = save_editor.set_item_quantity({}, owned, 60020, 9)
        result = save_editor.save(
            self.data_dir, owned_items=owned, item_quantities=quantities)

        self.assertEqual(result.owned_items, (10236, 60001, 60020))
        self.assertNotIn(80002, result.owned_items)
        store = prudp_server.EconomyStore(str(self.paths.companion_path))
        self.assertEqual(store.data["owned_items"], [10236, 60001, 60020])
        self.assertEqual(store.data["item_quantities"], {60020: 9})
        self.assertEqual(store.item_quantity(60020), 9)

    def test_companion_normalisation_parity_with_economy_store(self):
        write_companion(self.data_dir, {
            "version": 1,
            "gold": "5",
            "silver": 60,
            "fame": 10,
            "owned_items": [10236, 99999, 10236, "80002", 60020],
            "item_quantities": {
                "10236": 150,
                "10250": 4,
                "60020": -3,
                "60001": "7",
            },
            "claimed_challenges": [1, 2],
            "unknown_key": {"nested": [1, 2, 3]},
        })
        save_editor.save(self.data_dir, gold=11, silver=22, fame=33)

        raw = json.loads(self.paths.companion_path.read_text(encoding="utf-8"))
        # Every key the editor does not own survives verbatim.
        self.assertEqual(raw["unknown_key"], {"nested": [1, 2, 3]})
        self.assertEqual(raw["claimed_challenges"], [1, 2])
        self.assertEqual(raw["version"], 1)

        actual = prudp_server.EconomyStore(str(self.paths.companion_path))
        expected_path = Path(self._temp.name) / "expected-profile.json"
        expected_path.write_text(json.dumps({
            "gold": 11,
            "silver": 22,
            "fame": 33,
            "owned_items": [10236, 60020, 80002],
            "item_quantities": {"10236": 99, "60020": 0},
            "claimed_challenges": [1, 2],
        }), encoding="utf-8")
        expected = prudp_server.EconomyStore(str(expected_path))
        for key in ("gold", "silver", "fame", "owned_items",
                    "item_quantities", "claimed_challenges"):
            self.assertEqual(actual.data[key], expected.data[key], key)

    def test_supplied_items_are_normalised_before_writing(self):
        result = save_editor.save(
            self.data_dir,
            owned_items=[10236, 99999, 10236, "80002"],
            item_quantities={10236: 150, 60020: 5, 80002: "3"},
        )
        self.assertEqual(result.owned_items, (10236, 80002))
        self.assertEqual(result.item_quantities, {10236: 99, 80002: 3})
        store = prudp_server.EconomyStore(str(self.paths.companion_path))
        self.assertEqual(store.data["owned_items"], [10236, 80002])
        self.assertEqual(store.data["item_quantities"], {10236: 99, 80002: 3})


class BackupRestoreTests(SaveEditorTestCase):
    def _manifest(self, backup_dir):
        return json.loads((backup_dir / "manifest.json").read_text(
            encoding="utf-8"))

    def test_backup_manifest_hashes_the_pre_edit_files(self):
        native_before = self.native_bytes()
        companion_before = self.paths.companion_path.read_bytes()
        result = save_editor.save(self.data_dir, gold=222, silver=333,
                                  fame=44)

        self.assertTrue(result.backup_dir.is_dir())
        self.assertEqual(result.backup_dir.parent,
                         self.data_dir / "backups")
        manifest = self._manifest(result.backup_dir)
        self.assertEqual(manifest["format"], save_editor.BACKUP_FORMAT)
        self.assertEqual(manifest["title_version"], "01.00")
        expected = {
            "profile.json": companion_before,
            str(Path("usercontent") / "80000001" / "1.bin"): native_before,
        }
        self.assertEqual(set(manifest["files"]), set(expected))
        self.assertEqual(set(result.backed_up_files), set(expected))
        for relative, payload in expected.items():
            entry = manifest["files"][relative]
            self.assertEqual(entry["size"], len(payload))
            self.assertEqual(entry["sha256"],
                             hashlib.sha256(payload).hexdigest())
            backup_file = result.backup_dir / relative
            self.assertEqual(backup_file.read_bytes(), payload)

    def test_list_backups_is_newest_first_and_ignores_foreign_folders(self):
        first = save_editor.save(self.data_dir, gold=1)
        (self.data_dir / "backups" / "not-an-editor-backup").mkdir()
        second = save_editor.save(self.data_dir, gold=2)

        backups = save_editor.list_backups(self.data_dir)
        self.assertEqual([backup.name for backup in backups],
                         [second.backup_dir.name, first.backup_dir.name])
        self.assertEqual(backups[0].title_version, "01.00")
        self.assertIn("profile.json", backups[0].files)

    def test_restore_verifies_and_restores_both_files(self):
        native_before = self.native_bytes()
        companion_before = self.paths.companion_path.read_bytes()
        result = save_editor.save(self.data_dir, gold=222)
        self.assertNotEqual(self.paths.companion_path.read_bytes(),
                            companion_before)

        restored = save_editor.restore_backup(
            self.data_dir, result.backup_dir.name)
        self.assertEqual(self.native_bytes(), native_before)
        self.assertEqual(self.paths.companion_path.read_bytes(),
                         companion_before)
        self.assertEqual(set(restored.restored_files),
                         {"profile.json",
                          str(Path("usercontent") / "80000001" / "1.bin")})

    def test_restore_refuses_a_hash_mismatch_and_writes_nothing(self):
        result = save_editor.save(self.data_dir, gold=222)
        edited_native = self.native_bytes()
        edited_companion = self.paths.companion_path.read_bytes()
        tampered = result.backup_dir / "profile.json"
        tampered.write_bytes(tampered.read_bytes() + b"\n")

        with self.assertRaises(save_editor.SaveEditorError) as caught:
            save_editor.restore_backup(self.data_dir, result.backup_dir.name)
        self.assertIn("SHA-256", str(caught.exception))
        self.assertEqual(self.native_bytes(), edited_native)
        self.assertEqual(self.paths.companion_path.read_bytes(),
                         edited_companion)

    def test_restore_rejects_a_path_traversal_name(self):
        with self.assertRaises(save_editor.SaveEditorError):
            save_editor.restore_backup(self.data_dir, "../outside")

    def test_restore_refuses_while_the_server_is_running(self):
        result = save_editor.save(self.data_dir, gold=222)
        with self.assertRaises(save_editor.SaveEditorError):
            save_editor.restore_backup(
                self.data_dir, result.backup_dir.name, server_running=True)

    def test_v106_backup_covers_the_companion_and_leaves_native_alone(self):
        native = write_native(self.data_dir, "01.06",
                              payload=bytes(range(256)) * 21 + bytes(144))  # 0x1590
        write_companion(self.data_dir, {
            "gold": 5, "silver": 6, "fame": 7, "owned_items": [],
        }, "01.06")
        before = save_editor.load(self.data_dir, "01.06")
        result = save_editor.save(self.data_dir, "01.06", gold=8)
        self.assertTrue(result.backup_dir.is_dir())
        self.assertEqual(result.paths.title_version.value, "01.06")
        restored = save_editor.restore_backup(
            self.data_dir, result.backup_dir.name)
        after = save_editor.load(self.data_dir, "01.06")
        self.assertEqual(after.companion_balances, before.companion_balances)
        # Only the companion was edited, so only it is backed up/restored.
        self.assertEqual(len(restored.restored_files), 1)
        self.assertEqual(
            save_editor.title_paths(self.data_dir, "01.06")
            .native_profile_path.read_bytes(), native)

    def test_v106_accepts_every_size_the_01_06_client_writes(self):
        for size in (0x15B8, 0x1590, 0x1238):
            with self.subTest(size=size):
                write_native(self.data_dir, "01.06", payload=bytes(size))
                write_companion(self.data_dir, {
                    "gold": 1, "silver": 2, "fame": 3, "owned_items": [],
                }, "01.06")
                save_editor.save(self.data_dir, "01.06", fame=size)
                self.assertEqual(
                    save_editor.load(self.data_dir, "01.06")
                    .companion_balances["fame"], size)


if __name__ == "__main__":
    unittest.main()
