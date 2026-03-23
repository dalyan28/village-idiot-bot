"""
Unit-Tests für die State-Machine in commands/host_command.py.
Testet alle Dispatcher-States und ihre Übergänge ohne Discord-Verbindung.

Ausführen:
    pytest tests/test_host_states.py -v
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from logic.conversation import EventSession


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def session():
    """Frische EventSession mit Default-Feldern."""
    s = EventSession(
        user_id=123,
        guild_id=456,
        guild_name="TestGuild",
        event_channel_id=789,
    )
    s.user_display_name = "TestUser"
    return s


@pytest.fixture
def cog():
    """HostCommand-Cog mit gemocktem Bot."""
    from commands.host_command import HostCommand
    bot = MagicMock()
    c = HostCommand(bot)
    # Mock _select_script und _show_final_review (haben eigene Tests)
    c._select_script = AsyncMock()
    c._show_final_review = AsyncMock()
    c._show_version_choices = AsyncMock()
    return c


class _FakeTyping:
    """Async context manager für ch.typing()."""
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass


@pytest.fixture
def channel():
    """Mock-DM-Channel mit send() und typing()."""
    ch = AsyncMock()
    ch.send = AsyncMock()
    # typing() ist KEIN Coroutine, sondern gibt direkt einen Context Manager zurück
    ch.typing = MagicMock(return_value=_FakeTyping())
    return ch


def _make_message(content: str, attachments=None):
    """Erzeugt ein Mock-Message-Objekt."""
    msg = MagicMock()
    msg.content = content
    msg.attachments = attachments or []
    msg.channel = AsyncMock()
    return msg


# ═══════════════════════════════════════════════════════════════════════════════
# STATE 1: pending_script_edit_mode
# ═══════════════════════════════════════════════════════════════════════════════

class TestScriptEditMode:
    """_process_script_edit_mode: Wähle DB-Suche oder manuell."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("input_text", ["1", "suchen", "datenbank", "db"])
    async def test_db_search_keywords(self, cog, session, channel, input_text):
        session.pending_script_edit_mode = True
        await cog._process_script_edit_mode(session, channel, input_text)
        assert session.pending_script_search is True
        assert session.pending_script_edit_mode is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("input_text", ["2", "eingeben", "manuell", "selbst"])
    async def test_manual_entry_keywords(self, cog, session, channel, input_text):
        session.pending_script_edit_mode = True
        await cog._process_script_edit_mode(session, channel, input_text)
        assert session.pending_field_edit == "script"
        assert session.pending_script_edit_mode is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("input_text", ["3", "hochladen", "upload", "json"])
    async def test_upload_keywords(self, cog, session, channel, input_text):
        session.pending_script_edit_mode = True
        await cog._process_script_edit_mode(session, channel, input_text)
        assert getattr(session, "pending_script_upload", False) is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("input_text", ["4", "frei", "freie wahl"])
    async def test_free_choice_keywords(self, cog, session, channel, input_text):
        session.pending_script_edit_mode = True
        await cog._process_script_edit_mode(session, channel, input_text)
        assert session.fields["script"] == "Freie Skriptwahl"
        assert session.fields["is_free_choice"] is True
        cog._show_final_review.assert_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("input_text", ["", "5"])
    async def test_invalid_input_stays_in_state(self, cog, session, channel, input_text):
        session.pending_script_edit_mode = True
        await cog._process_script_edit_mode(session, channel, input_text)
        assert session.pending_script_edit_mode is True
        channel.send.assert_called()

    @pytest.mark.asyncio
    @patch("commands.host_command.search_scripts", new_callable=AsyncMock)
    async def test_natural_language_triggers_search(self, mock_search, cog, session, channel):
        """Text >2 Zeichen der kein Keyword ist → wird als Suchbegriff interpretiert."""
        mock_search.return_value = [{"name": "Test", "author": "A", "version": "1", "characters": []}]
        session.pending_script_edit_mode = True
        await cog._process_script_edit_mode(session, channel, "boozling")
        mock_search.assert_called()

    @pytest.mark.asyncio
    async def test_case_insensitive(self, cog, session, channel):
        session.pending_script_edit_mode = True
        await cog._process_script_edit_mode(session, channel, "SUCHEN")
        assert session.pending_script_search is True

    @pytest.mark.asyncio
    async def test_whitespace_trimmed(self, cog, session, channel):
        session.pending_script_edit_mode = True
        await cog._process_script_edit_mode(session, channel, "  1  ")
        assert session.pending_script_search is True


# ═══════════════════════════════════════════════════════════════════════════════
# STATE 2: pending_script_search
# ═══════════════════════════════════════════════════════════════════════════════

class TestScriptSearch:
    """_process_script_search: Sucht in botcscripts.com."""

    @pytest.mark.asyncio
    @patch("commands.host_command.search_scripts", new_callable=AsyncMock)
    async def test_search_with_results(self, mock_search, cog, session, channel):
        mock_search.return_value = [
            {"name": "Trouble Brewing", "author": "TPI", "version": "1.0", "characters": []},
        ]
        session.pending_script_search = True
        await cog._process_script_search(session, channel, "Trouble Brewing")
        assert session.pending_script_choices is not None
        assert len(session.pending_script_choices) == 1
        assert session.pending_script_search is False

    @pytest.mark.asyncio
    @patch("commands.host_command.search_scripts", new_callable=AsyncMock)
    async def test_search_no_results(self, mock_search, cog, session, channel):
        mock_search.return_value = []
        session.pending_script_search = True
        await cog._process_script_search(session, channel, "nonexistent_xyz")
        assert session.pending_script_search is True  # Stays in state for retry
        channel.send.assert_called()  # Error message sent

    @pytest.mark.asyncio
    @patch("commands.host_command.search_scripts", new_callable=AsyncMock)
    async def test_search_sets_return_flag(self, mock_search, cog, session, channel):
        mock_search.return_value = [{"name": "Test", "author": "A", "version": "1", "characters": []}]
        session.pending_script_search = True
        await cog._process_script_search(session, channel, "Test")
        assert session._script_choice_return_to_summary is True


# ═══════════════════════════════════════════════════════════════════════════════
# STATE 3: pending_field_edit
# ═══════════════════════════════════════════════════════════════════════════════

class TestFieldEdit:
    """_process_field_edit: Verschiedene Felder bearbeiten."""

    @pytest.mark.asyncio
    async def test_edit_title(self, cog, session, channel):
        session.pending_field_edit = "title"
        session.pending_final_review = True
        msg = _make_message("Neuer Toller Titel")
        await cog._process_field_edit(session, channel, "Neuer Toller Titel", msg)
        assert session.fields["title"] == "Neuer Toller Titel"
        assert session.pending_field_edit is None
        cog._show_final_review.assert_called()

    @pytest.mark.asyncio
    async def test_edit_storyteller(self, cog, session, channel):
        session.pending_field_edit = "storyteller"
        msg = _make_message("Alice")
        await cog._process_field_edit(session, channel, "Alice", msg)
        assert session.fields["storyteller"] == "Alice"

    @pytest.mark.asyncio
    async def test_edit_max_players_numeric(self, cog, session, channel):
        session.pending_field_edit = "max_players"
        msg = _make_message("15")
        await cog._process_field_edit(session, channel, "15", msg)
        assert session.fields["max_players"] == 15

    @pytest.mark.asyncio
    async def test_edit_max_players_non_numeric(self, cog, session, channel):
        session.pending_field_edit = "max_players"
        msg = _make_message("viele")
        await cog._process_field_edit(session, channel, "viele", msg)
        # Falls int() fehlschlägt, wird der Rohtext gespeichert
        assert session.fields["max_players"] == "viele"

    @pytest.mark.asyncio
    async def test_edit_camera_pflicht(self, cog, session, channel):
        session.pending_field_edit = "camera"
        msg = _make_message("pflicht")
        await cog._process_field_edit(session, channel, "pflicht", msg)
        assert session.fields["camera"] is True

    @pytest.mark.asyncio
    async def test_edit_camera_keine_pflicht(self, cog, session, channel):
        session.pending_field_edit = "camera"
        msg = _make_message("keine pflicht")
        await cog._process_field_edit(session, channel, "keine pflicht", msg)
        assert session.fields["camera"] is None

    @pytest.mark.asyncio
    async def test_edit_camera_nein(self, cog, session, channel):
        session.pending_field_edit = "camera"
        msg = _make_message("nein")
        await cog._process_field_edit(session, channel, "nein", msg)
        assert session.fields["camera"] is None

    @pytest.mark.asyncio
    async def test_edit_is_casual_ja(self, cog, session, channel):
        session.pending_field_edit = "is_casual"
        msg = _make_message("ja")
        await cog._process_field_edit(session, channel, "ja", msg)
        assert session.fields["is_casual"] is True

    @pytest.mark.asyncio
    async def test_edit_is_casual_nein(self, cog, session, channel):
        session.pending_field_edit = "is_casual"
        msg = _make_message("nein")
        await cog._process_field_edit(session, channel, "nein", msg)
        assert session.fields["is_casual"] is False

    @pytest.mark.asyncio
    async def test_edit_labels_casual_ja(self, cog, session, channel):
        session.pending_field_edit = "_labels"
        msg = _make_message("casual ja")
        await cog._process_field_edit(session, channel, "casual ja", msg)
        assert session.fields["is_casual"] is True

    @pytest.mark.asyncio
    async def test_edit_labels_casual_nein(self, cog, session, channel):
        session.pending_field_edit = "_labels"
        msg = _make_message("casual nein")
        await cog._process_field_edit(session, channel, "casual nein", msg)
        assert session.fields["is_casual"] is False

    @pytest.mark.asyncio
    async def test_edit_labels_academy_ja(self, cog, session, channel):
        session.pending_field_edit = "_labels"
        msg = _make_message("academy ja")
        await cog._process_field_edit(session, channel, "academy ja", msg)
        assert session.fields["is_academy"] is True

    @pytest.mark.asyncio
    async def test_edit_labels_invalid(self, cog, session, channel):
        session.pending_field_edit = "_labels"
        msg = _make_message("blabla")
        await cog._process_field_edit(session, channel, "blabla", msg)
        # Stays in labels edit mode (re-prompt)
        assert session.pending_field_edit == "_labels"

    @pytest.mark.asyncio
    async def test_edit_start_time_full(self, cog, session, channel):
        session.pending_field_edit = "start_time"
        msg = _make_message("2026-03-25 20:00 180min")
        await cog._process_field_edit(session, channel, "2026-03-25 20:00 180min", msg)
        assert session.fields["start_time"] == "2026-03-25 20:00"
        assert session.fields["duration_minutes"] == 180

    @pytest.mark.asyncio
    async def test_edit_start_time_only_date(self, cog, session, channel):
        session.pending_field_edit = "start_time"
        msg = _make_message("2026-03-25 20:00")
        await cog._process_field_edit(session, channel, "2026-03-25 20:00", msg)
        assert session.fields["start_time"] == "2026-03-25 20:00"

    @pytest.mark.asyncio
    async def test_edit_start_time_only_duration_minutes(self, cog, session, channel):
        session.pending_field_edit = "start_time"
        msg = _make_message("120min")
        await cog._process_field_edit(session, channel, "120min", msg)
        assert session.fields["duration_minutes"] == 120

    @pytest.mark.asyncio
    async def test_edit_start_time_hours(self, cog, session, channel):
        session.pending_field_edit = "start_time"
        msg = _make_message("2h")
        await cog._process_field_edit(session, channel, "2h", msg)
        assert session.fields["duration_minutes"] == 120

    @pytest.mark.asyncio
    async def test_edit_start_time_raw_number(self, cog, session, channel):
        """Reine Zahl ohne Suffix → wird als Minuten interpretiert."""
        session.pending_field_edit = "start_time"
        msg = _make_message("90")
        await cog._process_field_edit(session, channel, "90", msg)
        assert session.fields["duration_minutes"] == 90


# ═══════════════════════════════════════════════════════════════════════════════
# STATE 4: pending_script_upload
# ═══════════════════════════════════════════════════════════════════════════════

class TestScriptUpload:
    """_process_script_upload: JSON hochladen oder überspringen."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("input_text", ["skip", "überspringen", "s"])
    async def test_skip_keywords(self, cog, session, channel, input_text):
        session.pending_script_upload = True
        msg = _make_message(input_text)
        await cog._process_script_upload(session, channel, input_text, msg)
        assert session.pending_script_upload is False
        cog._show_final_review.assert_called()

    @pytest.mark.asyncio
    async def test_non_json_attachment(self, cog, session, channel):
        session.pending_script_upload = True
        att = MagicMock()
        att.filename = "script.txt"
        msg = _make_message("", attachments=[att])
        await cog._process_script_upload(session, channel, "", msg)
        channel.send.assert_called()
        # Stays in upload state
        assert session.pending_script_upload is True

    @pytest.mark.asyncio
    @patch("commands.host_command.validate_script_json")
    @patch("commands.host_command.cache_script")
    async def test_valid_json_upload(self, mock_cache, mock_validate, cog, session, channel):
        mock_validate.return_value = (
            {"name": "TestScript", "characters": ["imp", "washerwoman"]},
            None,
        )
        att = AsyncMock()
        att.filename = "test.json"
        att.read = AsyncMock(return_value=json.dumps([{"id": "imp"}, {"id": "washerwoman"}]).encode())
        msg = _make_message("", attachments=[att])
        session.pending_script_upload = True
        await cog._process_script_upload(session, channel, "", msg)
        assert session.fields["script"] == "TestScript"
        assert session.pending_script_upload is False

    @pytest.mark.asyncio
    @patch("commands.host_command.validate_script_json")
    async def test_invalid_json_upload(self, mock_validate, cog, session, channel):
        mock_validate.return_value = (None, "JSON-Struktur ungültig")
        att = AsyncMock()
        att.filename = "bad.json"
        att.read = AsyncMock(return_value=b"not json")
        msg = _make_message("", attachments=[att])
        session.pending_script_upload = True
        await cog._process_script_upload(session, channel, "", msg)
        # Stays in upload state
        assert session.pending_script_upload is True

    @pytest.mark.asyncio
    async def test_no_attachment_text_input(self, cog, session, channel):
        session.pending_script_upload = True
        msg = _make_message("was soll ich tun")
        await cog._process_script_upload(session, channel, "was soll ich tun", msg)
        channel.send.assert_called()
        assert session.pending_script_upload is True


# ═══════════════════════════════════════════════════════════════════════════════
# STATE 5: pending_script_choices
# ═══════════════════════════════════════════════════════════════════════════════

class TestScriptChoices:
    """_process_script_choices: Auswahl aus 5 Suchergebnissen."""

    SAMPLE_CHOICES = [
        {"name": "Trouble Brewing", "author": "TPI", "version": "1.0", "characters": ["imp"]},
        {"name": "Bad Moon Rising", "author": "TPI", "version": "1.0", "characters": ["zombuul"]},
        {"name": "Sects and Violets", "author": "TPI", "version": "1.0", "characters": ["fanggu"]},
        {"name": "One Cat Mosh Pit", "author": "Jams", "version": "2.0", "characters": ["imp"]},
        {"name": "Boozling", "author": "Lau", "version": "9.0", "characters": ["imp"]},
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("input_text", ["skip", "überspringen", "s"])
    async def test_skip_keywords(self, cog, session, channel, input_text):
        session.pending_script_choices = self.SAMPLE_CHOICES
        msg = _make_message(input_text)
        await cog._process_script_choices(session, channel, input_text, msg)
        assert session.pending_script_choices is None
        cog._show_final_review.assert_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("input_text", ["custom", "homebrew", "eigenes", "keines", "keins davon", "nichts davon"])
    async def test_custom_keywords(self, cog, session, channel, input_text):
        session.pending_script_choices = self.SAMPLE_CHOICES
        msg = _make_message(input_text)
        await cog._process_script_choices(session, channel, input_text, msg)
        assert session.pending_script_upload is True
        assert session.pending_script_choices is None

    @pytest.mark.asyncio
    async def test_direct_number_valid(self, cog, session, channel):
        session.pending_script_choices = self.SAMPLE_CHOICES
        msg = _make_message("3")
        await cog._process_script_choices(session, channel, "3", msg)
        cog._select_script.assert_called_once()
        selected = cog._select_script.call_args[0][2]
        assert selected["name"] == "Sects and Violets"

    @pytest.mark.asyncio
    async def test_direct_number_out_of_range(self, cog, session, channel):
        session.pending_script_choices = self.SAMPLE_CHOICES
        msg = _make_message("7")
        await cog._process_script_choices(session, channel, "7", msg)
        cog._select_script.assert_not_called()
        channel.send.assert_called()

    @pytest.mark.asyncio
    async def test_direct_number_zero(self, cog, session, channel):
        session.pending_script_choices = self.SAMPLE_CHOICES
        msg = _make_message("0")
        await cog._process_script_choices(session, channel, "0", msg)
        cog._select_script.assert_not_called()

    @pytest.mark.asyncio
    async def test_direct_number_negative(self, cog, session, channel):
        session.pending_script_choices = self.SAMPLE_CHOICES
        msg = _make_message("-1")
        await cog._process_script_choices(session, channel, "-1", msg)
        cog._select_script.assert_not_called()

    @pytest.mark.asyncio
    async def test_ordinal_erste(self, cog, session, channel):
        session.pending_script_choices = self.SAMPLE_CHOICES
        msg = _make_message("das erste")
        await cog._process_script_choices(session, channel, "das erste", msg)
        cog._select_script.assert_called_once()
        selected = cog._select_script.call_args[0][2]
        assert selected["name"] == "Trouble Brewing"

    @pytest.mark.asyncio
    async def test_ordinal_letzte(self, cog, session, channel):
        session.pending_script_choices = self.SAMPLE_CHOICES
        msg = _make_message("das letzte")
        await cog._process_script_choices(session, channel, "das letzte", msg)
        cog._select_script.assert_called_once()
        selected = cog._select_script.call_args[0][2]
        assert selected["name"] == "Boozling"

    @pytest.mark.asyncio
    async def test_ordinal_zweite(self, cog, session, channel):
        session.pending_script_choices = self.SAMPLE_CHOICES
        msg = _make_message("nimm die zweite")
        await cog._process_script_choices(session, channel, "nimm die zweite", msg)
        cog._select_script.assert_called_once()
        selected = cog._select_script.call_args[0][2]
        assert selected["name"] == "Bad Moon Rising"

    @pytest.mark.asyncio
    async def test_name_match_exact(self, cog, session, channel):
        session.pending_script_choices = self.SAMPLE_CHOICES
        msg = _make_message("Boozling")
        await cog._process_script_choices(session, channel, "Boozling", msg)
        cog._select_script.assert_called_once()
        selected = cog._select_script.call_args[0][2]
        assert selected["name"] == "Boozling"

    @pytest.mark.asyncio
    async def test_name_match_partial(self, cog, session, channel):
        """'Mosh' als Teilwort > 2 Zeichen → Score 5 → Match."""
        session.pending_script_choices = self.SAMPLE_CHOICES
        msg = _make_message("Mosh")
        await cog._process_script_choices(session, channel, "Mosh", msg)
        cog._select_script.assert_called_once()
        selected = cog._select_script.call_args[0][2]
        assert selected["name"] == "One Cat Mosh Pit"

    @pytest.mark.asyncio
    async def test_author_match(self, cog, session, channel):
        """'Jams' als Autor → Score 8 → Match."""
        session.pending_script_choices = self.SAMPLE_CHOICES
        msg = _make_message("das von Jams")
        await cog._process_script_choices(session, channel, "das von Jams", msg)
        cog._select_script.assert_called_once()
        selected = cog._select_script.call_args[0][2]
        assert selected["name"] == "One Cat Mosh Pit"

    @pytest.mark.asyncio
    async def test_short_word_no_match(self, cog, session, channel):
        """Wörter ≤ 2 Zeichen werden ignoriert beim Teilwort-Match."""
        session.pending_script_choices = self.SAMPLE_CHOICES
        msg = _make_message("im")
        # "im" hat nur 2 Zeichen → kein Teilwort-Match → Haiku-Fallback
        with patch("commands.host_command.interpret_script_choice", new_callable=AsyncMock) as mock_haiku:
            mock_haiku.return_value = {"action": "unclear", "message": "Was meinst du?"}
            await cog._process_script_choices(session, channel, "im", msg)
            mock_haiku.assert_called_once()

    @pytest.mark.asyncio
    async def test_json_attachment_redirects(self, cog, session, channel):
        """JSON-Attachment in script_choices → Redirect zu script_upload."""
        session.pending_script_choices = self.SAMPLE_CHOICES
        att = MagicMock()
        att.filename = "myscript.json"
        # Text muss non-empty sein, weil "" in jedem String enthalten ist → Name-Match
        msg = _make_message("hier mein script", attachments=[att])
        cog._process = AsyncMock()
        await cog._process_script_choices(session, channel, "hier mein script", msg)
        assert getattr(session, "pending_script_upload", False) is True
        assert session.pending_script_choices is None
        cog._process.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# STATE 6: _pending_version_choices
# ═══════════════════════════════════════════════════════════════════════════════

class TestVersionChoices:
    """_process_version_choices: Version des Scripts auswählen."""

    SAMPLE_VERSIONS = [
        {"name": "Boozling", "author": "Lau", "version": "7.0", "characters": ["imp"]},
        {"name": "Boozling", "author": "Lau", "version": "8.0", "characters": ["imp"]},
        {"name": "Boozling", "author": "Lau", "version": "9.0", "characters": ["imp"]},
    ]

    @pytest.mark.asyncio
    async def test_valid_number(self, cog, session, channel):
        session._pending_version_choices = self.SAMPLE_VERSIONS
        await cog._process_version_choices(session, channel, "2")
        cog._select_script.assert_called_once()
        selected = cog._select_script.call_args[0][2]
        assert selected["version"] == "8.0"
        assert session._pending_version_choices is None

    @pytest.mark.asyncio
    async def test_number_out_of_range(self, cog, session, channel):
        session._pending_version_choices = self.SAMPLE_VERSIONS
        await cog._process_version_choices(session, channel, "5")
        cog._select_script.assert_not_called()
        channel.send.assert_called()
        # Stays in state
        assert session._pending_version_choices is not None

    @pytest.mark.asyncio
    async def test_non_numeric(self, cog, session, channel):
        session._pending_version_choices = self.SAMPLE_VERSIONS
        await cog._process_version_choices(session, channel, "die neueste")
        cog._select_script.assert_not_called()
        channel.send.assert_called()

    @pytest.mark.asyncio
    async def test_zero(self, cog, session, channel):
        session._pending_version_choices = self.SAMPLE_VERSIONS
        await cog._process_version_choices(session, channel, "0")
        cog._select_script.assert_not_called()

    @pytest.mark.asyncio
    async def test_retrigger_set(self, cog, session, channel):
        """Version-Wechsel setzt _retrigger_proposal für Titel/Desc-Regenerierung."""
        session._pending_version_choices = self.SAMPLE_VERSIONS
        await cog._process_version_choices(session, channel, "1")
        assert session._retrigger_proposal is True


# ═══════════════════════════════════════════════════════════════════════════════
# STATE 7: _pending_script_preview
# ═══════════════════════════════════════════════════════════════════════════════

class TestScriptPreview:
    """_process_script_preview: Vorschau von Scripts mit Details."""

    PREVIEW = [
        {"name": "Script A", "author": "Author A", "version": "1.0", "characters": ["imp"]},
        {"name": "Script B", "author": "Author B", "version": "2.0", "characters": ["imp"]},
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("input_text", ["zurück", "back", "liste"])
    async def test_back_keywords(self, cog, session, channel, input_text):
        session._pending_script_preview = True
        session._preview_scripts = self.PREVIEW
        session._preview_indices = [1, 2]
        session.pending_script_choices = self.PREVIEW  # Original-Liste
        await cog._process_script_preview(session, channel, input_text)
        assert session._pending_script_preview is False
        assert session._preview_scripts is None

    @pytest.mark.asyncio
    async def test_select_by_number(self, cog, session, channel):
        session._pending_script_preview = True
        session._preview_scripts = self.PREVIEW
        session._preview_indices = [2, 4]
        await cog._process_script_preview(session, channel, "1")
        cog._select_script.assert_called_once()
        selected = cog._select_script.call_args[0][2]
        assert selected["name"] == "Script A"

    @pytest.mark.asyncio
    async def test_number_out_of_range(self, cog, session, channel):
        session._pending_script_preview = True
        session._preview_scripts = self.PREVIEW
        session._preview_indices = [1, 2]
        # 5 ist nicht im Preview (nur 2 Scripts)
        with patch("commands.host_command.interpret_script_preview", new_callable=AsyncMock) as mock_haiku:
            mock_haiku.return_value = {"action": "unclear", "message": "Nur 1 oder 2 möglich."}
            await cog._process_script_preview(session, channel, "5")
            mock_haiku.assert_called()


# ═══════════════════════════════════════════════════════════════════════════════
# STATE 8: pending_final_review
# ═══════════════════════════════════════════════════════════════════════════════

class TestFinalReview:
    """_process_final_review: Abschluss-Screen."""

    def _fill_session(self, session):
        """Füllt Session mit allen Pflichtfeldern."""
        session.fields["title"] = "🟡 Test Event"
        session.fields["description"] = "Test Beschreibung"
        session.fields["script"] = "Boozling"
        session.fields["storyteller"] = "Dalyan"
        session.fields["start_time"] = "2026-03-25 20:00"
        session.fields["level"] = "Alle"
        session.fields["is_casual"] = False
        session.fields["max_players"] = 12
        session.fields["duration_minutes"] = 150
        session.pending_final_review = True
        return session

    @pytest.mark.asyncio
    @pytest.mark.parametrize("input_text", ["ok", "fertig", "bestätigen", "confirm", "ja", "yes", "passt", "gut"])
    async def test_confirm_keywords(self, cog, session, channel, input_text):
        self._fill_session(session)
        # Mock SummaryView
        with patch("commands.host_command.SummaryView") as MockView:
            mock_view = MockView.return_value
            mock_view.confirm = AsyncMock()
            await cog._process_final_review(session, channel, input_text)
            assert session.pending_final_review is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("input_text", ["anderes skript", "skript ändern", "anderes script", "script ändern"])
    async def test_change_script_keywords(self, cog, session, channel, input_text):
        self._fill_session(session)
        await cog._process_final_review(session, channel, input_text)
        assert session.pending_script_edit_mode is True
        assert session.pending_final_review is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("input_text", ["andere version", "version ändern", "version wechseln"])
    async def test_change_version_keywords(self, cog, session, channel, input_text):
        self._fill_session(session)
        await cog._process_final_review(session, channel, input_text)
        cog._show_version_choices.assert_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("input_text", ["alt", "alte", "bisherige", "vorherige"])
    async def test_restore_old_values(self, cog, session, channel, input_text):
        self._fill_session(session)
        session._old_title = "Alter Titel"
        session._old_desc = "Alte Beschreibung"
        await cog._process_final_review(session, channel, input_text)
        assert session.fields["title"] == "Alter Titel"
        assert session.fields["description"] == "Alte Beschreibung"

    @pytest.mark.asyncio
    async def test_restore_without_old_values(self, cog, session, channel):
        self._fill_session(session)
        # Keine _old_title / _old_desc gesetzt
        await cog._process_final_review(session, channel, "alt")
        channel.send.assert_called()
        # Titel bleibt unverändert
        assert session.fields["title"] == "🟡 Test Event"

    @pytest.mark.asyncio
    async def test_number_1_edits_title(self, cog, session, channel):
        self._fill_session(session)
        await cog._process_final_review(session, channel, "1")
        assert session.pending_field_edit == "title"

    @pytest.mark.asyncio
    async def test_number_2_triggers_script_workflow(self, cog, session, channel):
        self._fill_session(session)
        await cog._process_final_review(session, channel, "2")
        assert session.pending_script_edit_mode is True
        assert session.pending_final_review is False

    @pytest.mark.asyncio
    async def test_number_3_edits_description(self, cog, session, channel):
        self._fill_session(session)
        await cog._process_final_review(session, channel, "3")
        assert session.pending_field_edit == "description"

    @pytest.mark.asyncio
    async def test_number_7_edits_labels(self, cog, session, channel):
        self._fill_session(session)
        await cog._process_final_review(session, channel, "7")
        assert session.pending_field_edit == "_labels"

    @pytest.mark.asyncio
    async def test_number_10_edits_termin(self, cog, session, channel):
        self._fill_session(session)
        await cog._process_final_review(session, channel, "10")
        assert session.pending_field_edit == "start_time"

    @pytest.mark.asyncio
    async def test_number_out_of_range(self, cog, session, channel):
        self._fill_session(session)
        await cog._process_final_review(session, channel, "11")
        channel.send.assert_called()

    @pytest.mark.asyncio
    async def test_number_zero(self, cog, session, channel):
        self._fill_session(session)
        await cog._process_final_review(session, channel, "0")
        channel.send.assert_called()

    @pytest.mark.asyncio
    @patch("commands.host_command.interpret_final_review", new_callable=AsyncMock)
    async def test_haiku_batch_edit(self, mock_haiku, cog, session, channel):
        """Batch-Edit: 'Ändere Kamera und Storyteller'."""
        self._fill_session(session)
        mock_haiku.return_value = {
            "action": "edit",
            "fields": {
                "camera": True,
                "storyteller": "Tobias",
            },
        }
        await cog._process_final_review(session, channel, "Ändere die Kamera zu Pflicht und den Storyteller zu Tobias")
        assert session.fields["camera"] is True
        assert session.fields["storyteller"] == "Tobias"
        cog._show_final_review.assert_called()

    @pytest.mark.asyncio
    @patch("commands.host_command.interpret_final_review", new_callable=AsyncMock)
    async def test_haiku_confirm(self, mock_haiku, cog, session, channel):
        """Haiku erkennt Bestätigung in natürlicher Sprache."""
        self._fill_session(session)
        mock_haiku.return_value = {"action": "confirm"}
        with patch("commands.host_command.SummaryView") as MockView:
            mock_view = MockView.return_value
            mock_view.confirm = AsyncMock()
            await cog._process_final_review(session, channel, "alles super, erstell das event")

    @pytest.mark.asyncio
    @patch("commands.host_command.interpret_final_review", new_callable=AsyncMock)
    async def test_haiku_change_script(self, mock_haiku, cog, session, channel):
        self._fill_session(session)
        mock_haiku.return_value = {"action": "change_script"}
        await cog._process_final_review(session, channel, "ich will ein anderes script spielen")
        assert session.pending_script_edit_mode is True

    @pytest.mark.asyncio
    @patch("commands.host_command.interpret_final_review", new_callable=AsyncMock)
    async def test_haiku_unclear(self, mock_haiku, cog, session, channel):
        self._fill_session(session)
        mock_haiku.return_value = {"action": "unclear", "message": "Ich habe nicht verstanden, was du möchtest."}
        await cog._process_final_review(session, channel, "xyz gibberish 123")
        channel.send.assert_called()

    @pytest.mark.asyncio
    @patch("commands.host_command.interpret_final_review", new_callable=AsyncMock)
    async def test_haiku_returns_none(self, mock_haiku, cog, session, channel):
        """Haiku gibt None zurück → Fallback-Fehlermeldung."""
        self._fill_session(session)
        mock_haiku.return_value = None
        await cog._process_final_review(session, channel, "???")
        # Muss die Fallback-Meldung senden
        last_call = channel.send.call_args[1].get("content", "") if channel.send.call_args[1] else channel.send.call_args[0][0]
        assert "1-10" in last_call


# ═══════════════════════════════════════════════════════════════════════════════
# Dispatcher: _process
# ═══════════════════════════════════════════════════════════════════════════════

class TestDispatcher:
    """_process: State-Dispatch-Reihenfolge."""

    @pytest.mark.asyncio
    async def test_script_edit_mode_takes_priority(self, cog, session, channel):
        """pending_script_edit_mode wird VOR pending_final_review geprüft."""
        session.pending_script_edit_mode = True
        session.pending_final_review = True
        cog._process_script_edit_mode = AsyncMock()
        msg = _make_message("1")
        msg.channel = channel
        await cog._process(session, msg)
        cog._process_script_edit_mode.assert_called_once()

    @pytest.mark.asyncio
    async def test_final_review_reached_when_no_other_state(self, cog, session, channel):
        """Wenn nur pending_final_review aktiv → wird auch aufgerufen."""
        session.pending_final_review = True
        cog._process_final_review = AsyncMock()
        msg = _make_message("ok")
        msg.channel = channel
        await cog._process(session, msg)
        cog._process_final_review.assert_called_once()

    @pytest.mark.asyncio
    async def test_default_to_haiku_chat(self, cog, session, channel):
        """Kein State aktiv → Haiku-Chat (Step 1)."""
        cog._process_haiku_chat = AsyncMock()
        msg = _make_message("Ich möchte Boozling spielen morgen um 20 Uhr")
        msg.channel = channel
        await cog._process(session, msg)
        cog._process_haiku_chat.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# Nischige Interaktionen / Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Grenzfälle und unerwartete Inputs."""

    @pytest.mark.asyncio
    async def test_empty_input_in_script_edit(self, cog, session, channel):
        """Leerer String in pending_script_edit_mode."""
        session.pending_script_edit_mode = True
        await cog._process_script_edit_mode(session, channel, "")
        assert session.pending_script_edit_mode is True

    @pytest.mark.asyncio
    async def test_ordinal_with_only_one_choice(self, cog, session, channel):
        """'das letzte' bei nur einem Suchergebnis."""
        choices = [{"name": "Only One", "author": "A", "version": "1.0", "characters": []}]
        session.pending_script_choices = choices
        msg = _make_message("das letzte")
        await cog._process_script_choices(session, channel, "das letzte", msg)
        cog._select_script.assert_called_once()
        selected = cog._select_script.call_args[0][2]
        assert selected["name"] == "Only One"

    @pytest.mark.asyncio
    async def test_ordinal_beyond_list_falls_through(self, cog, session, channel):
        """'das fünfte' bei nur 3 Ergebnissen → Ordinal wird übersprungen, fällt durch zu Haiku."""
        # Namen müssen lang genug sein, damit keine Substring-Matches mit dem Input entstehen
        choices = [
            {"name": "Zombuul Rising", "author": "Author1", "version": "1", "characters": []},
            {"name": "Phantom Dance", "author": "Author2", "version": "1", "characters": []},
            {"name": "Crimson Herald", "author": "Author3", "version": "1", "characters": []},
        ]
        session.pending_script_choices = choices
        msg = _make_message("das fünfte")
        # "fünfte" → index 4, idx < 3 = False → kein Ordinal-Match
        # Kein Name/Author-Match → Haiku-Fallback
        with patch("commands.host_command.interpret_script_choice", new_callable=AsyncMock) as mock_haiku:
            mock_haiku.return_value = {"action": "unclear", "message": "Nur 3 Ergebnisse."}
            await cog._process_script_choices(session, channel, "das fünfte", msg)
            mock_haiku.assert_called()

    @pytest.mark.asyncio
    async def test_camera_edge_values(self, cog, session, channel):
        """Verschiedene Formulierungen für Kamera."""
        for text, expected in [("an", True), ("ja", True), ("egal", None), ("optional", None), ("Aus", False)]:
            session.pending_field_edit = "camera"
            msg = _make_message(text)
            await cog._process_field_edit(session, channel, text, msg)
            assert session.fields["camera"] == expected, f"Input '{text}' → expected {expected}, got {session.fields['camera']}"

    @pytest.mark.asyncio
    async def test_confirm_case_insensitive(self, cog, session, channel):
        """'OK' und 'Ok' und 'oK' sollen alle bestätigen."""
        session.pending_final_review = True
        session.fields["title"] = "Test"
        with patch("commands.host_command.SummaryView") as MockView:
            mock_view = MockView.return_value
            mock_view.confirm = AsyncMock()
            await cog._process_final_review(session, channel, "OK")
            assert session.pending_final_review is False

    @pytest.mark.asyncio
    async def test_field_edit_preserves_label(self, cog, session, channel):
        """Label-Prefix bleibt erhalten wenn Titel bearbeitet wird (über Feldbearbeitung)."""
        session.pending_field_edit = "title"
        session.fields["title"] = "🟡 Altes Event"
        msg = _make_message("Neues Event")
        # Der Feldwert wird direkt gesetzt — Label-Prefix wird beim Anzeigen neu berechnet
        await cog._process_field_edit(session, channel, "Neues Event", msg)
        assert session.fields["title"] == "Neues Event"

    @pytest.mark.asyncio
    async def test_multiple_states_only_first_runs(self, cog, session, channel):
        """Wenn mehrere State-Flags gesetzt → nur der erste im Dispatcher wird ausgeführt."""
        session.pending_script_edit_mode = True
        session.pending_script_upload = True
        session.pending_final_review = True
        cog._process_script_edit_mode = AsyncMock()
        cog._process_script_upload = AsyncMock()
        cog._process_final_review = AsyncMock()
        msg = _make_message("test")
        msg.channel = channel
        await cog._process(session, msg)
        cog._process_script_edit_mode.assert_called_once()
        cog._process_script_upload.assert_not_called()
        cog._process_final_review.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# _format_termin_german
# ═══════════════════════════════════════════════════════════════════════════════

class TestFormatTerminGerman:
    """Helper-Funktion für deutsches Datumsformat."""

    def test_basic_format(self):
        from commands.host_command import _format_termin_german
        result = _format_termin_german("2026-03-24 15:00", 120)
        assert "Dienstag" in result
        assert "24.03.2026" in result
        assert "15:00" in result
        assert "17:00" in result

    def test_invalid_date_returns_raw(self):
        from commands.host_command import _format_termin_german
        result = _format_termin_german("invalid", 120)
        assert result == "invalid"

    def test_none_date(self):
        from commands.host_command import _format_termin_german
        result = _format_termin_german(None, 120)
        assert result == "-"

    def test_german_day_names(self):
        from commands.host_command import _format_termin_german
        # 2026-03-23 = Montag
        assert "Montag" in _format_termin_german("2026-03-23 10:00", 60)
        # 2026-03-28 = Samstag
        assert "Samstag" in _format_termin_german("2026-03-28 10:00", 60)
        # 2026-03-29 = Sonntag
        assert "Sonntag" in _format_termin_german("2026-03-29 10:00", 60)

    def test_duration_overflow_past_midnight(self):
        from commands.host_command import _format_termin_german
        result = _format_termin_german("2026-03-24 23:00", 120)
        assert "23:00" in result
        assert "01:00" in result  # Nächster Tag

    def test_dd_mm_yyyy_format(self):
        from commands.host_command import _format_termin_german
        result = _format_termin_german("24.03.2026 15:00", 90)
        assert "Dienstag" in result
        assert "16:30" in result
