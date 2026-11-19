import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

import discord

with patch.dict(os.environ, {"DISCORD_OWNER_ID": "0", "DISCORD_TEST_GUILD": "", "APP_ID": "", "BOT_SEARCH_SUGGESTION_COUNT": "5"}):
    from models import AudioBalanceMode
    from player import Player, PlaybackSource, build_voice_status
    from subsonic import Song


class VoiceStatusTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.player = Player(SimpleNamespace(audio_balance_mode=AudioBalanceMode.OFF))
        self.player.play_audio_queue = AsyncMock()
        self.voice = Mock(spec=discord.VoiceClient)
        self.voice.is_connected.return_value = True
        self.voice.is_playing.return_value = False
        self.voice.is_paused.return_value = False
        self.voice.channel = Mock(spec=discord.VoiceChannel)
        self.voice.channel.edit = AsyncMock()
        self.song = Song({"id": "track", "title": "Track", "artist": "Artist", "duration": 120})
        self.player._send = AsyncMock()
        self.stream = AsyncMock(return_value="https://example.invalid/track")
        self.audio_factory = Mock()
        self.audio_factory.return_value.read.return_value = b"audio packet"
        for patcher in (
            patch("player.stream", new=self.stream),
            patch("player.discord.FFmpegOpusAudio", new=self.audio_factory),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.player._stop_voice_status_updates)

    async def finish_track(self, after=None):
        after = after or self.voice.play.call_args.kwargs["after"]
        future = await asyncio.to_thread(after, None)
        await asyncio.wrap_future(future)

    async def test_status_shows_track_and_artist_then_clears_before_advancing(self):
        async def advance(voice):
            self.voice.channel.edit.assert_awaited_with(status=None)
        self.player.play_audio_queue.side_effect = advance
        await self.player.stream_track(self.song, self.voice)
        self.voice.channel.edit.assert_awaited_with(status="Track by Artist (00:00/02:00)")
        await self.finish_track()
        self.voice.channel.edit.assert_has_awaits([
            call(status="Track by Artist (00:00/02:00)"),
            call(status=None),
        ])
        self.player.play_audio_queue.assert_awaited_once_with(self.voice)

    async def test_status_truncates_to_500_characters_and_accepts_none(self):
        await self.player._set_voice_status("🎵" * 501, self.voice)
        self.voice.channel.edit.assert_awaited_once_with(status="🎵" * 500)
        await self.player._set_voice_status(None, self.voice)
        self.voice.channel.edit.assert_awaited_with(status=None)

    async def test_stage_channel_playback_does_not_change_its_status(self):
        self.voice.channel = Mock(spec=discord.StageChannel)
        self.voice.channel.edit = AsyncMock()
        await self.player.stream_track(self.song, self.voice)
        self.voice.play.assert_called_once()
        await self.finish_track()
        self.voice.channel.edit.assert_not_awaited()
        self.player.play_audio_queue.assert_awaited_once_with(self.voice)

    async def test_permission_failure_does_not_block_playback_or_queue_advancement(self):
        self.voice.channel.edit.side_effect = discord.Forbidden(
            SimpleNamespace(status=403, reason="Forbidden"), "Missing permissions"
        )
        with self.assertLogs("player", level="WARNING"):
            await self.player.stream_track(self.song, self.voice)
            self.voice.play.assert_called_once()
            await self.finish_track()
        self.player.play_audio_queue.assert_awaited_once_with(self.voice)

    async def test_stop_clears_status_without_advancing_queue(self):
        await self.player.stream_track(self.song, self.voice)
        self.player.stop(self.voice)
        await self.finish_track()
        self.voice.channel.edit.assert_awaited_with(status=None)
        self.player.play_audio_queue.assert_not_awaited()

    async def test_seek_keeps_song_and_queue_and_ignores_replaced_source_callback(self):
        await self.player.stream_track(self.song, self.voice)
        old_after = self.voice.play.call_args.kwargs["after"]
        self.player.current_song = self.song
        self.player.queue = ["queued"]
        self.voice.is_playing.return_value = True

        self.assertTrue(await self.player.stream_track(self.song, self.voice, position=42))
        self.assertIn("-ss 42", self.audio_factory.call_args.kwargs["before_options"])
        self.assertEqual(self.player.current_position, 42)
        self.assertIs(self.player.current_song, self.song)
        self.assertEqual(self.player.queue, ["queued"])
        self.voice.channel.edit.reset_mock()
        await self.finish_track(old_after)
        self.voice.channel.edit.assert_not_awaited()
        self.player.play_audio_queue.assert_not_awaited()
        await self.finish_track()
        self.player.play_audio_queue.assert_awaited_once_with(self.voice)

    async def test_seek_preserves_paused_state(self):
        self.player.current_song = self.song
        self.voice.is_paused.return_value = True
        self.assertTrue(await self.player.stream_track(self.song, self.voice, position=0))
        self.voice.pause.assert_called_once()
        self.assertEqual(self.player.current_position, 0)
        self.player.play_audio_queue.assert_not_awaited()

    async def test_failed_seek_preparation_keeps_original_playback(self):
        self.player.current_song = self.song
        self.player.queue = ["queued"]
        self.voice.is_playing.return_value = True
        self.stream.return_value = ""
        with self.assertLogs("player", level="ERROR"):
            self.assertFalse(await self.player.stream_track(self.song, self.voice, position=10))
        self.voice.stop.assert_not_called()
        self.voice.play.assert_not_called()
        self.assertIs(self.player.current_song, self.song)
        self.assertEqual(self.player.queue, ["queued"])

    async def test_track_change_during_seek_does_not_stop_the_new_track(self):
        self.player.current_song = self.song
        self.voice.is_playing.return_value = True
        next_song = SimpleNamespace(song_id="next")
        async def change_track(song_id):
            self.player.current_song = next_song
            return "https://example.invalid/track"
        self.stream.side_effect = change_track
        self.assertFalse(await self.player.stream_track(self.song, self.voice, position=10))
        self.voice.stop.assert_not_called()
        self.audio_factory.return_value.cleanup.assert_called_once()
        self.assertIs(self.player.current_song, next_song)

    async def test_enqueue_does_not_advance_a_paused_track(self):
        self.player.current_song = self.song
        self.player.queue = ["queued"]
        self.voice.is_paused.return_value = True
        await Player.play_audio_queue(self.player, self.voice)
        self.assertIs(self.player.current_song, self.song)
        self.assertEqual(self.player.queue, ["queued"])
        self.voice.play.assert_not_called()

    async def test_skip_can_stop_a_paused_track(self):
        self.voice.is_paused.return_value = True
        await self.player.skip_track(self.voice)
        self.voice.stop.assert_called_once()

    async def test_frame_position_follows_seek_and_ignores_replaced_source(self):
        self.player.current_song = self.song
        self.assertTrue(await self.player.stream_track(self.song, self.voice))
        original = self.voice.play.call_args.args[0]
        for _ in range(125):
            original.read()
        self.assertEqual(self.player.current_position, 2)

        self.voice.is_playing.return_value = True
        self.assertTrue(await self.player.stream_track(self.song, self.voice, position=42))
        replacement = self.voice.play.call_args.args[0]
        self.assertEqual(self.player.current_position, 42)
        for _ in range(50):
            replacement.read()
        self.assertEqual(self.player.current_position, 43)
        for _ in range(50):
            original.read()
        self.assertEqual(self.player.current_position, 43)

        self.player.stop(self.voice)
        replacement.read()
        self.assertEqual(self.player.current_position, 0)

    async def test_status_refreshes_progress_without_repeating_unchanged_timestamps(self):
        self.player.current_song = self.song
        self.player._audio_source = PlaybackSource(self.audio_factory.return_value, 0)
        self.voice.is_playing.return_value = True
        ticks = iter(((15, False), (15, True), (30, False), (None, False)))
        async def tick(delay):
            position, paused = next(ticks)
            if position is None:
                self.voice.is_connected.return_value = False
            else:
                self.voice.is_playing.return_value = not paused
                self.voice.is_paused.return_value = paused
                self.player._audio_source.frames = position * 50
        with patch("player.asyncio.sleep", new=tick):
            await self.player._refresh_voice_status(self.song, self.voice, self.player._playback_id)
        self.assertEqual(
            [entry.kwargs["status"] for entry in self.voice.channel.edit.await_args_list],
            ["Track by Artist (00:15/02:00)", "Track by Artist (00:30/02:00)"],
        )

    async def test_replaced_track_cannot_refresh_voice_status(self):
        async def replace_track(delay):
            self.player._playback_id += 1
        with patch("player.asyncio.sleep", new=replace_track):
            await self.player._refresh_voice_status(self.song, self.voice, self.player._playback_id)
        self.voice.channel.edit.assert_not_awaited()

    def test_long_voice_status_keeps_the_timestamp_suffix(self):
        song = Song({"id": "long", "title": "x" * 600, "artist": "Artist", "duration": 245})
        status = build_voice_status(song, 83)
        self.assertEqual(len(status), 500)
        self.assertTrue(status.endswith(" (01:23/04:05)"))


class PlaybackPositionTests(unittest.TestCase):
    def setUp(self):
        self.original = Mock(spec=discord.AudioSource)
        self.original.read.return_value = b"audio packet"
        self.source = PlaybackSource(self.original, 0)
        self.player = Player(SimpleNamespace(audio_balance_mode=AudioBalanceMode.OFF))
        self.player.current_song = SimpleNamespace(duration=120)
        self.player._audio_source = self.source

    def test_only_complete_seconds_of_nonempty_audio_frames_advance_position(self):
        for _ in range(49):
            self.source.read()
        self.assertEqual(self.player.current_position, 0)
        self.source.read()
        self.assertEqual(self.player.current_position, 1)
        self.original.read.return_value = b""
        self.source.read()
        self.assertEqual(self.player.current_position, 1)

    def test_position_is_clamped_to_known_duration_but_not_unknown_duration(self):
        self.source.frames = 121 * 50
        self.assertEqual(self.player.current_position, 120)
        self.player.current_song.duration = 0
        self.assertEqual(self.player.current_position, 121)

    def test_changing_song_discards_the_previous_tracks_position(self):
        self.source.frames = 83 * 50
        self.assertEqual(self.player.current_position, 83)
        self.player.current_song = SimpleNamespace(duration=200)
        self.source.read()
        self.assertEqual(self.player.current_position, 0)
