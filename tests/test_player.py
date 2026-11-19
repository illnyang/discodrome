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
        self.voice.channel = Mock(spec=discord.VoiceChannel)
        self.voice.channel.edit = AsyncMock()
        self.song = SimpleNamespace(song_id="track", title="Track", artist="Artist")
        for patcher in (
            patch("player.stream", new=AsyncMock(return_value="https://example.invalid/track")),
            patch("player.discord.FFmpegOpusAudio"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def finish_track(self):
        after = self.voice.play.call_args.kwargs["after"]
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
