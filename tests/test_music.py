import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

with patch.dict(os.environ, {"DISCORD_OWNER_ID": "0", "DISCORD_TEST_GUILD": "", "APP_ID": "", "BOT_SEARCH_SUGGESTION_COUNT": "5"}):
    import data
    from discord.ext import commands
    from extensions.music import MusicCog, QueueView
    from subsonic import Song


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
        self.player.current_song = Song({"id": "current", "title": "Current Track"})
        await self.cog.show_queue.callback(self.cog, self.ctx)
        response = self.ctx.send.call_args.kwargs
        self.assertNotIn("view", response)
        self.assertIn("Current Track", response["embed"].description)
        self.assertIn("Queue is empty!", response["embed"].description)
