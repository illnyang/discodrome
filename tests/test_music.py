import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

with patch.dict(os.environ, {"DISCORD_OWNER_ID": "0", "DISCORD_TEST_GUILD": "", "APP_ID": "", "BOT_SEARCH_SUGGESTION_COUNT": "5"}):
    import data
    from discord.ext import commands
    from extensions.music import MusicCog, QueueView, parse_seek_position
    from subsonic import Song
    from player import PlaybackSource


class QueueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.state = Path(directory.name) / "guild_properties.json"
        patcher = patch.multiple(data, GUILD_PROPERTIES_FILE=str(self.state), _guild_property_instances={}, _guild_data_instances={})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ctx = Mock(spec=commands.Context, guild=SimpleNamespace(id=1), author=SimpleNamespace(id=10), interaction=None, send=AsyncMock())
        self.cog = MusicCog(SimpleNamespace())
        self.player = data.guild_data(1).player
        self.player.queue = [Song({"id": str(i), "title": f"Track {i}"}) for i in range(1, 12)]

    async def test_move_in_both_directions_and_remove_are_persisted(self):
        original = list(self.player.queue)
        await self.cog.show_queue.callback(self.cog, self.ctx, "move", 1, 11)
        self.assertEqual(self.player.queue, original[1:] + original[:1])
        await self.cog.show_queue.callback(self.cog, self.ctx, "move", 11, 1)
        self.assertEqual(self.player.queue, original)
        await self.cog.show_queue.callback(self.cog, self.ctx, "remove", 2)
        self.assertEqual(self.player.queue, original[:1] + original[2:])
        saved = json.loads(self.state.read_text())["guilds"]["1"]["queue"]
        self.assertEqual([song["id"] for song in saved], [song.song_id for song in self.player.queue])

    async def test_invalid_edits_leave_queue_unchanged(self):
        original = list(self.player.queue)
        for args in (("invalid", 1, 2), ("remove", None, None), ("remove", 0, None), ("remove", 12, None), ("move", 1, None), ("move", 1, 0), ("move", 1, 12), ("move", 1, 1)):
            with self.subTest(args=args):
                self.ctx.send.reset_mock()
                await self.cog.show_queue.callback(self.cog, self.ctx, *args)
                self.assertEqual(self.player.queue, original)
                self.assertFalse(self.state.exists())
                self.assertEqual(self.ctx.send.call_args.kwargs["embed"].title, "Error")
        self.player.queue.clear()
        await self.cog.show_queue.callback(self.cog, self.ctx, "remove", 1)
        self.assertFalse(self.state.exists())

    async def test_pages_show_snapshot_and_restrict_controls_to_author(self):
        await self.cog.show_queue.callback(self.cog, self.ctx)
        view = self.ctx.send.call_args.kwargs["view"]
        self.assertIn("10. **Track 10**", view.current_embed().description)
        self.assertNotIn("11. **Track 11**", view.current_embed().description)
        self.player.queue.clear()
        interaction = SimpleNamespace(user=SimpleNamespace(id=10), response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock()))
        self.assertTrue(await view.interaction_check(interaction))
        await view.next_page.callback(interaction)
        self.assertIn("11. **Track 11**", interaction.response.edit_message.call_args.kwargs["embed"].description)
        self.assertTrue(view.next_page.disabled)
        self.assertFalse(view.previous_page.disabled)
        interaction.user.id = 20
        self.assertFalse(await view.interaction_check(interaction))
        self.assertTrue(interaction.response.send_message.call_args.kwargs["ephemeral"])

    async def test_empty_queue_still_shows_current_song(self):
        self.player.queue.clear()
        self.player.current_song = Song({"id": "current", "title": "Current Track", "duration": 245})
        self.player._audio_source = PlaybackSource(Mock(spec=discord.AudioSource), 83)
        await self.cog.show_queue.callback(self.cog, self.ctx)
        response = self.ctx.send.call_args.kwargs
        self.assertNotIn("view", response)
        self.assertIn("Current Track", response["embed"].description)
        self.assertIn("Queue is empty!", response["embed"].description)
        self.assertIn("(01:23/04:05)", response["embed"].description)

    async def test_queue_timestamp_is_a_snapshot_and_refreshes_on_next_request(self):
        self.player.current_song = Song({"id": "current", "duration": 245})
        audio = Mock(spec=discord.AudioSource)
        audio.read.return_value = b"audio packet"
        self.player._audio_source = PlaybackSource(audio, 83)
        await self.cog.show_queue.callback(self.cog, self.ctx)
        view = self.ctx.send.call_args.kwargs["view"]
        self.assertIn("(01:23/04:05)", view.current_embed().description)
        for _ in range(50):
            self.player._audio_source.read()
        interaction = SimpleNamespace(response=SimpleNamespace(edit_message=AsyncMock()))
        await view.next_page.callback(interaction)
        self.assertIn("(01:23/04:05)", interaction.response.edit_message.call_args.kwargs["embed"].description)
        await self.cog.show_queue.callback(self.cog, self.ctx)
        self.assertIn("(01:24/04:05)", self.ctx.send.call_args.kwargs["embed"].description)


class SeekTimestampTests(unittest.TestCase):
    def test_formats_follow_duration_including_thresholds(self):
        for duration, timestamp, expected in (
            (10, "5", 5),
            (60, "59", 59),
            (61, "01:00", 60),
            (3600, "59:59", 3599),
            (3601, "01:00:00", 3600),
            (360001, "100:00:00", 360000),
        ):
            with self.subTest(duration=duration, timestamp=timestamp):
                self.assertEqual(parse_seek_position(timestamp, duration), expected)

    def test_invalid_formats_and_out_of_range_positions_are_rejected(self):
        for duration, timestamp in (
            (0, "00"), (-1, "00"), (60, "60"), (10, "10"), (10, "-1"),
            (60, "00:10"), (61, "10"), (120, "1:00"), (120, "02:00"),
            (120, "00:60"), (120, "00:-1"), (120, "00:1.5"),
            (120, "００:１０"), (120, " 00:10"), (120, ""),
            (3601, "59:59"), (3601, "1:00:00"), (3601, "00:60:00"),
            (3601, "01:00:01"),
        ):
            with self.subTest(duration=duration, timestamp=timestamp):
                with self.assertRaises(ValueError):
                    parse_seek_position(timestamp, duration)


class PlaybackControlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher = patch.multiple(data, _guild_property_instances={}, _guild_data_instances={})
        patcher.start()
        self.addCleanup(patcher.stop)
        guild = SimpleNamespace(id=1)
        self.ctx = Mock(spec=commands.Context, guild=guild, author=SimpleNamespace(id=10),
                        channel=SimpleNamespace(), interaction=None, send=AsyncMock(), defer=AsyncMock())
        self.state = {"playing": True, "paused": False}
        self.voice = Mock(spec=discord.VoiceClient)
        self.voice.guild = guild
        self.voice.is_connected.return_value = True
        self.voice.is_playing.side_effect = lambda: self.state["playing"]
        self.voice.is_paused.side_effect = lambda: self.state["paused"]
        self.voice.pause.side_effect = lambda: self.state.update(playing=False, paused=True)
        self.voice.resume.side_effect = lambda: self.state.update(playing=True, paused=False)
        self.voice.stop.side_effect = lambda: self.state.update(playing=False, paused=False)
        self.voice.play.side_effect = lambda *args, **kwargs: self.state.update(playing=True, paused=False)
        self.voice.channel = Mock(spec=discord.VoiceChannel)
        self.voice.channel.edit = AsyncMock()
        self.cog = MusicCog(SimpleNamespace(voice_clients=[self.voice]))
        async def invoke(command, **kwargs):
            return await command.callback(self.cog, self.ctx, **kwargs)
        self.ctx.invoke = AsyncMock(side_effect=invoke)
        self.player = data.guild_data(1).player
        self.song = Song({"id": "current", "title": "Current", "duration": 120})
        self.player.current_song = self.song
        self.player.queue = [Song({"id": "queued"})]
        self.queue = list(self.player.queue)
        self.audio_factory = Mock()
        for patcher in (
            patch("player.stream", new=AsyncMock(return_value="https://example.invalid/track")),
            patch("player.discord.FFmpegOpusAudio", new=self.audio_factory),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.player._stop_voice_status_updates)

    async def test_pause_and_resume_long_and_short_commands_preserve_song_and_queue(self):
        for pause_command, resume_command in (
            (self.cog.pause, self.cog.resume),
            (self.cog.pause_short, self.cog.resume_short),
        ):
            await pause_command.callback(self.cog, self.ctx)
            self.assertEqual(self.state, {"playing": False, "paused": True})
            await resume_command.callback(self.cog, self.ctx)
            self.assertEqual(self.state, {"playing": True, "paused": False})
            self.assertIs(self.player.current_song, self.song)
            self.assertEqual(self.player.queue, self.queue)
        self.voice.stop.assert_not_called()

    async def test_goto_and_g_seek_without_changing_song_queue_or_paused_state(self):
        for command in (self.cog.goto, self.cog.goto_short):
            for paused in (False, True):
                with self.subTest(command=command.name, paused=paused):
                    self.state.update(playing=not paused, paused=paused)
                    await command.callback(self.cog, self.ctx, position="00:45")
                    self.assertEqual(self.state, {"playing": not paused, "paused": paused})
                    self.assertEqual(self.player.current_position, 45)
                    self.assertIn("-ss 45", self.audio_factory.call_args.kwargs["before_options"])
                    self.assertIs(self.player.current_song, self.song)
                    self.assertEqual(self.player.queue, self.queue)

    async def test_invalid_position_does_not_interrupt_playback(self):
        for position in ("45", "02:00", "00:60", "-00:01", "00:00:10"):
            with self.subTest(position=position):
                await self.cog.goto.callback(self.cog, self.ctx, position=position)
                self.assertEqual(self.state, {"playing": True, "paused": False})
                self.assertEqual(self.ctx.send.call_args.kwargs["embed"].title, "Error")
        self.voice.stop.assert_not_called()
        self.audio_factory.assert_not_called()

    async def test_invalid_control_states_leave_playback_unchanged(self):
        for command, playing, paused in (
            (self.cog.pause, False, True),
            (self.cog.pause, False, False),
            (self.cog.resume, True, False),
            (self.cog.resume, False, False),
            (self.cog.goto, False, False),
        ):
            with self.subTest(command=command.name, playing=playing, paused=paused):
                self.state.update(playing=playing, paused=paused)
                kwargs = {"position": "00:10"} if command is self.cog.goto else {}
                await command.callback(self.cog, self.ctx, **kwargs)
                self.assertEqual(self.state, {"playing": playing, "paused": paused})
                self.assertEqual(self.ctx.send.call_args.kwargs["embed"].title, "Error")
        self.voice.stop.assert_not_called()

    async def test_disconnected_controls_report_an_error_without_connecting(self):
        self.cog.bot.voice_clients.clear()
        for command in (self.cog.pause, self.cog.resume, self.cog.goto):
            kwargs = {"position": "00:10"} if command is self.cog.goto else {}
            await command.callback(self.cog, self.ctx, **kwargs)
            self.assertEqual(self.ctx.send.call_args.kwargs["embed"].title, "Error")
        self.voice.pause.assert_not_called()
        self.voice.resume.assert_not_called()
        self.voice.stop.assert_not_called()
