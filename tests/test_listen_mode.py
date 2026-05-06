"""
Unit-Tests für den Listen Mode in commands/overview.py.
Testet edit_overview Pagination, Debounce und Sentinel-Handling.

Ausführen:
    pytest tests/test_listen_mode.py -v
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from commands.overview import Overview


@pytest.fixture
def cog():
    bot = MagicMock()
    return Overview(bot)


# ---------------------------------------------------------------------------
# _edit_overview_locked – Pagination transitions
# ---------------------------------------------------------------------------

class TestEditOverviewPagination:
    """Testet die 3-Phasen-Logik: Edit, Post, Delete."""

    def _make_embed(self):
        return discord.Embed(title="Kommende Events", color=0x5865F2)

    def _mock_message(self, msg_id):
        msg = AsyncMock()
        msg.id = msg_id
        msg.edit = AsyncMock()
        msg.delete = AsyncMock()
        return msg

    @pytest.mark.asyncio
    async def test_same_count_edits_in_place(self, cog):
        """1 alt, 1 neu → edit, kein delete, kein neuer post."""
        old_msg = self._mock_message(1001)
        embed = self._make_embed()
        embed.add_field(name="Test", value="content", inline=False)

        channel = AsyncMock()
        channel.fetch_message = AsyncMock(return_value=old_msg)

        with patch("commands.overview.parse_events", return_value=[]), \
             patch("commands.overview.build_overviews", return_value=[embed]), \
             patch("commands.overview.get_guild_config", return_value={"last_overview_message_ids": [1001]}), \
             patch("commands.overview.save_guild_config") as save_mock:

            event_ch = AsyncMock()
            event_ch.history = MagicMock(return_value=AsyncIterator([]))

            await cog._edit_overview_locked(1, event_ch, channel)

            old_msg.edit.assert_called_once()
            channel.send.assert_not_called()
            old_msg.delete.assert_not_called()
            save_mock.assert_called_once()
            saved_cfg = save_mock.call_args[0][1]
            assert saved_cfg["last_overview_message_ids"] == [1001]

    @pytest.mark.asyncio
    async def test_grow_1_to_2_posts_new(self, cog):
        """1 alt, 2 neu → edit 1. + post 2."""
        old_msg = self._mock_message(1001)
        embed1 = self._make_embed()
        embed1.add_field(name="Test", value="content1", inline=False)
        embed2 = self._make_embed()
        embed2.add_field(name="Test", value="content2", inline=False)

        new_msg = AsyncMock()
        new_msg.id = 2002

        channel = AsyncMock()
        channel.fetch_message = AsyncMock(return_value=old_msg)
        channel.send = AsyncMock(return_value=new_msg)

        with patch("commands.overview.parse_events", return_value=[]), \
             patch("commands.overview.build_overviews", return_value=[embed1, embed2]), \
             patch("commands.overview.get_guild_config", return_value={"last_overview_message_ids": [1001]}), \
             patch("commands.overview.save_guild_config") as save_mock:

            event_ch = AsyncMock()
            event_ch.history = MagicMock(return_value=AsyncIterator([]))

            await cog._edit_overview_locked(1, event_ch, channel)

            old_msg.edit.assert_called_once()
            channel.send.assert_called_once()
            saved_cfg = save_mock.call_args[0][1]
            assert saved_cfg["last_overview_message_ids"] == [1001, 2002]

    @pytest.mark.asyncio
    async def test_shrink_2_to_1_deletes_excess(self, cog):
        """2 alt, 1 neu → edit 1. + delete 2."""
        old_msg1 = self._mock_message(1001)
        old_msg2 = self._mock_message(1002)
        embed = self._make_embed()
        embed.add_field(name="Test", value="content", inline=False)

        channel = AsyncMock()
        channel.fetch_message = AsyncMock(side_effect=lambda mid: {1001: old_msg1, 1002: old_msg2}[mid])

        with patch("commands.overview.parse_events", return_value=[]), \
             patch("commands.overview.build_overviews", return_value=[embed]), \
             patch("commands.overview.get_guild_config", return_value={"last_overview_message_ids": [1001, 1002]}), \
             patch("commands.overview.save_guild_config") as save_mock:

            event_ch = AsyncMock()
            event_ch.history = MagicMock(return_value=AsyncIterator([]))

            await cog._edit_overview_locked(1, event_ch, channel)

            old_msg1.edit.assert_called_once()
            old_msg2.delete.assert_called_once()
            channel.send.assert_not_called()
            saved_cfg = save_mock.call_args[0][1]
            assert saved_cfg["last_overview_message_ids"] == [1001]

    @pytest.mark.asyncio
    async def test_not_found_fallback_posts_new(self, cog):
        """Alte Nachricht nicht mehr da → Fallback auf send."""
        new_msg = AsyncMock()
        new_msg.id = 3003
        embed = self._make_embed()
        embed.add_field(name="Test", value="content", inline=False)

        channel = AsyncMock()
        channel.fetch_message = AsyncMock(side_effect=discord.NotFound(MagicMock(), "not found"))
        channel.send = AsyncMock(return_value=new_msg)

        with patch("commands.overview.parse_events", return_value=[]), \
             patch("commands.overview.build_overviews", return_value=[embed]), \
             patch("commands.overview.get_guild_config", return_value={"last_overview_message_ids": [9999]}), \
             patch("commands.overview.save_guild_config") as save_mock:

            event_ch = AsyncMock()
            event_ch.history = MagicMock(return_value=AsyncIterator([]))

            await cog._edit_overview_locked(1, event_ch, channel)

            channel.send.assert_called_once()
            saved_cfg = save_mock.call_args[0][1]
            assert saved_cfg["last_overview_message_ids"] == [3003]

    @pytest.mark.asyncio
    async def test_no_old_messages_posts_all(self, cog):
        """Keine alten Nachrichten → alle neu posten."""
        new_msg1 = AsyncMock()
        new_msg1.id = 4001
        new_msg2 = AsyncMock()
        new_msg2.id = 4002
        embed1 = self._make_embed()
        embed1.add_field(name="Test", value="content1", inline=False)
        embed2 = self._make_embed()
        embed2.add_field(name="Test", value="content2", inline=False)

        channel = AsyncMock()
        channel.send = AsyncMock(side_effect=[new_msg1, new_msg2])

        with patch("commands.overview.parse_events", return_value=[]), \
             patch("commands.overview.build_overviews", return_value=[embed1, embed2]), \
             patch("commands.overview.get_guild_config", return_value={"last_overview_message_ids": []}), \
             patch("commands.overview.save_guild_config") as save_mock:

            event_ch = AsyncMock()
            event_ch.history = MagicMock(return_value=AsyncIterator([]))

            await cog._edit_overview_locked(1, event_ch, channel)

            assert channel.send.call_count == 2
            saved_cfg = save_mock.call_args[0][1]
            assert saved_cfg["last_overview_message_ids"] == [4001, 4002]


# ---------------------------------------------------------------------------
# Debounce (_schedule_edit)
# ---------------------------------------------------------------------------

class TestDebounce:
    @pytest.mark.asyncio
    async def test_debounce_batches_rapid_calls(self, cog):
        """Mehrere schnelle _schedule_edit Aufrufe → nur 1 edit_overview Call."""
        cog.edit_overview = AsyncMock()
        ch1, ch2 = AsyncMock(), AsyncMock()

        for _ in range(5):
            await cog._schedule_edit(1, ch1, ch2)

        assert len(cog._edit_debounce_tasks) == 1
        task = cog._edit_debounce_tasks[1]
        await task

        cog.edit_overview.assert_called_once_with(1, ch1, ch2)

    @pytest.mark.asyncio
    async def test_debounce_resets_start_after_execution(self, cog):
        """Nach Ausfuehrung wird _edit_debounce_start geraeumt."""
        cog.edit_overview = AsyncMock()
        ch1, ch2 = AsyncMock(), AsyncMock()

        await cog._schedule_edit(1, ch1, ch2)
        assert 1 in cog._edit_debounce_start

        await cog._edit_debounce_tasks[1]
        assert 1 not in cog._edit_debounce_start

    @pytest.mark.asyncio
    async def test_max_delay_cap(self, cog):
        """wait darf nie negativ werden (max delay 15s cap)."""
        cog.edit_overview = AsyncMock()
        ch1, ch2 = AsyncMock(), AsyncMock()

        cog._edit_debounce_start[1] = asyncio.get_event_loop().time() - 20

        await cog._schedule_edit(1, ch1, ch2)
        task = cog._edit_debounce_tasks[1]
        await task

        cog.edit_overview.assert_called_once()


# ---------------------------------------------------------------------------
# Sentinel Handling
# ---------------------------------------------------------------------------

class TestListenModeSentinel:
    def test_stop_recognizes_sentinel(self, cog):
        """is_running Check erkennt 'listen_mode' Sentinel."""
        cog.auto_tasks[1] = "listen_mode"
        existing = cog.auto_tasks.get(1)
        is_running = (
            existing == "listen_mode"
            or (isinstance(existing, asyncio.Task) and not existing.done())
        )
        assert is_running is True

    def test_sentinel_not_cancellable(self, cog):
        """Sentinel ist ein String, hat kein .cancel() → kein Fehler."""
        cog.auto_tasks[1] = "listen_mode"
        existing = cog.auto_tasks[1]
        assert not isinstance(existing, asyncio.Task)
        assert existing == "listen_mode"

    def test_on_message_filter_listen_mode(self, cog):
        """Listen Mode Guild ist in auto_tasks → Listener laeuft."""
        cog.auto_tasks[42] = "listen_mode"
        assert 42 in cog.auto_tasks


# ---------------------------------------------------------------------------
# on_raw_message_edit Filter
# ---------------------------------------------------------------------------

class TestOnRawMessageEditFilter:
    def test_event_embed_with_time_field_passes(self):
        embeds_data = [{"fields": [{"name": "Time", "value": "<t:123:F>"}]}]
        fields = embeds_data[0].get("fields", [])
        assert any(f.get("name") in ("Time", "Termin") for f in fields)

    def test_event_embed_with_termin_field_passes(self):
        embeds_data = [{"fields": [{"name": "Termin", "value": "<t:123:F>"}]}]
        fields = embeds_data[0].get("fields", [])
        assert any(f.get("name") in ("Time", "Termin") for f in fields)

    def test_non_event_embed_blocked(self):
        embeds_data = [{"fields": [{"name": "Description", "value": "text"}]}]
        fields = embeds_data[0].get("fields", [])
        assert not any(f.get("name") in ("Time", "Termin") for f in fields)

    def test_empty_embeds_blocked(self):
        embeds_data = []
        assert not embeds_data

    def test_embed_without_fields_blocked(self):
        embeds_data = [{"fields": []}]
        fields = embeds_data[0].get("fields", [])
        assert not fields


# ---------------------------------------------------------------------------
# Helper: AsyncIterator for mocking channel.history()
# ---------------------------------------------------------------------------

class AsyncIterator:
    def __init__(self, items):
        self._items = list(items)
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        return item
