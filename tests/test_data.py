import json
import os
import pickle
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

with patch.dict(os.environ, {"DISCORD_OWNER_ID": "0", "DISCORD_TEST_GUILD": "", "APP_ID": "", "BOT_SEARCH_SUGGESTION_COUNT": "5"}):
    import data
    from models import AudioBalanceMode, AutoplayMode
    from player import build_audio_filter
    from subsonic import Song


class GuildPersistenceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.state = Path(directory.name) / "guild_properties.json"
        self.legacy = self.state.with_suffix(".pickle")
        for target, value in (
            ("GUILD_PROPERTIES_FILE", str(self.state)),
            ("LEGACY_GUILD_PROPERTIES_FILE", str(self.legacy)),
            ("_guild_property_instances", {}),
            ("_guild_data_instances", {}),
        ):
            patcher = patch.object(data, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_queue_and_modes_survive_restart_without_leaking_between_guilds(self):
        first = data.guild_properties(1)
        first.autoplay_mode = AutoplayMode.SIMILAR
        first.audio_balance_mode = AudioBalanceMode.OFF
        song = Song({"id": "track-1", "title": "Track", "artist": "Artist", "duration": 123})
        data.guild_data(1).player.queue.append(song)
        second = data.guild_properties(2)
        self.assertEqual(second.autoplay_mode, AutoplayMode.NONE)
        self.assertEqual(second.audio_balance_mode, AudioBalanceMode.DYNAMIC)
        data.save_guild_properties_to_disk()
        data._guild_property_instances.clear()
        data._guild_data_instances.clear()
        data.load_guild_properties_from_disk()
        self.assertEqual(data.guild_properties(1).autoplay_mode, AutoplayMode.SIMILAR)
        player = data.guild_data(1).player
        self.assertEqual(player.guild_properties.audio_balance_mode, AudioBalanceMode.OFF)
        restored = player.queue[0]
        self.assertEqual(
            (restored.song_id, restored.title, restored.artist, restored.duration),
            ("track-1", "Track", "Artist", 123),
        )
        self.assertEqual(data.guild_data(2).player.queue, [])

    def test_legacy_enum_path_migrates_with_queue_and_new_defaults(self):
        properties = data.GuildProperties()
        properties.autoplay_mode = AutoplayMode.RANDOM
        properties.queue = [Song({"id": "legacy", "duration": 90})]
        del properties._properties["audio-balance-mode"]
        payload = pickle.dumps({1: properties}, protocol=2)
        payload = payload.replace(b"cmodels\nAutoplayMode\n", b"cdata\nAutoplayMode\n")
        self.legacy.write_bytes(payload)
        data.load_guild_properties_from_disk()
        saved = json.loads(self.state.read_text())["guilds"]["1"]
        self.assertEqual(saved["autoplay-mode"], "random")
        self.assertEqual(saved["audio-balance-mode"], "dynamic")
        self.assertEqual(saved["queue"][0]["id"], "legacy")
        self.assertEqual(self.legacy.read_bytes(), payload)

    def test_unreadable_or_unsupported_state_is_not_replaced(self):
        for payload in ("{", "[]", '{"guilds": []}'):
            with self.subTest(payload=payload):
                self.state.write_text(payload)
                with self.assertRaises(ValueError):
                    data.load_guild_properties_from_disk()
                self.assertEqual(self.state.read_text(), payload)
        self.state.unlink()
        self.legacy.write_bytes(b"cos\nsystem\n.")
        with self.assertRaises(pickle.UnpicklingError):
            data.load_guild_properties_from_disk()
        self.assertFalse(self.state.exists())

    def test_balance_filters(self):
        self.assertIsNone(build_audio_filter(AudioBalanceMode.OFF))
        replaygain = build_audio_filter(AudioBalanceMode.REPLAYGAIN)
        self.assertEqual(replaygain, "volume=replaygain=track:replaygain_noclip=1")
        self.assertEqual(build_audio_filter(AudioBalanceMode.DYNAMIC), replaygain + ",dynaudnorm=f=250:g=15:p=0.95:m=10,alimiter=limit=0.95")
