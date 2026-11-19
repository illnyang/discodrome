import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

import discord

with patch.dict(os.environ, {"DISCORD_OWNER_ID": "0", "DISCORD_TEST_GUILD": "", "APP_ID": "", "BOT_SEARCH_SUGGESTION_COUNT": "5"}):
    from models import AudioBalanceMode
    from player import Player


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
        self.song = SimpleNamespace(song_id="track", title="Track", artist="Artist")
        self.player._send = AsyncMock()
        self.stream = AsyncMock(return_value="https://example.invalid/track")
        self.audio_factory = Mock()
        for patcher in (
            patch("player.stream", new=self.stream),
            patch("player.discord.FFmpegOpusAudio", new=self.audio_factory),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def finish_track(self, after=None):
        after = after or self.voice.play.call_args.kwargs["after"]
        future = await asyncio.to_thread(after, None)
        await asyncio.wrap_future(future)

    async def test_status_shows_track_and_artist_then_clears_before_advancing(self):
        async def advance(voice):
            self.voice.channel.edit.assert_awaited_with(status=None)
        self.player.play_audio_queue.side_effect = advance
        await self.player.stream_track(self.song, self.voice)
        self.voice.channel.edit.assert_awaited_with(status="Currently playing: Track by Artist")
        await self.finish_track()
        self.voice.channel.edit.assert_has_awaits([
            call(status="Currently playing: Track by Artist"),
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
