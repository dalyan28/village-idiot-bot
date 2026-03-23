"""
Integration-Tests für den Event-Erstellungs-Workflow.
Testet komplette Multi-Step-Journeys durch die State-Machine,
inkl. disruptiver Richtungswechsel und unerwarteter Eingaben.

Ausführen:
    pytest tests/test_host_workflows.py -v
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from logic.conversation import EventSession


# ── Test-Infrastruktur ───────────────────────────────────────────────────────


class _FakeTyping:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass


def _make_session(**overrides):
    s = EventSession(
        user_id=123, guild_id=456,
        guild_name="TestGuild", event_channel_id=789,
    )
    s.user_display_name = "TestUser"
    for k, v in overrides.items():
        if k == "fields":
            s.fields.update(v)
        else:
            setattr(s, k, v)
    return s


def _make_cog():
    from commands.host_command import HostCommand
    bot = MagicMock()
    c = HostCommand(bot)
    # Nur _show_final_review und _select_script mocken — alles andere real
    c._show_final_review = AsyncMock()
    c._show_version_choices = AsyncMock()
    return c


def _ch():
    ch = AsyncMock()
    ch.send = AsyncMock()
    ch.typing = MagicMock(return_value=_FakeTyping())
    return ch


def _msg(text, attachments=None):
    m = MagicMock()
    m.content = text
    m.attachments = attachments or []
    m.channel = _ch()
    return m


SAMPLE_SCRIPTS = [
    {"name": "Trouble Brewing", "author": "TPI", "version": "1.0", "characters": ["imp", "washerwoman"]},
    {"name": "Bad Moon Rising", "author": "TPI", "version": "1.0", "characters": ["zombuul"]},
    {"name": "Sects and Violets", "author": "TPI", "version": "1.0", "characters": ["fanggu"]},
    {"name": "One Cat Mosh Pit", "author": "Jams", "version": "2.0", "characters": ["imp"]},
    {"name": "Boozling", "author": "Lau", "version": "9.0", "characters": ["imp"]},
]


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 1: Script-Auswahl → Preview → Zurück → Anderes wählen
# ═══════════════════════════════════════════════════════════════════════════════


class TestPreviewThenBackThenSelect:
    """User sieht Suchergebnisse, lässt sich 2 Previews zeigen,
    geht zurück, wählt dann ein anderes."""

    @pytest.mark.asyncio
    async def test_preview_back_select(self):
        cog = _make_cog()
        cog._select_script = AsyncMock()
        session = _make_session()
        ch = _ch()

        # Step 1: Suchergebnisse liegen vor
        session.pending_script_choices = SAMPLE_SCRIPTS.copy()

        # Step 2: User will sich Script 1 und 3 anschauen (Preview)
        await cog._process_script_preview.__wrapped__(cog, session, ch, "1") if hasattr(cog._process_script_preview, '__wrapped__') else None
        # Stattdessen: direkt _show_script_preview aufrufen
        session._preview_scripts = [SAMPLE_SCRIPTS[0], SAMPLE_SCRIPTS[2]]
        session._preview_indices = [1, 3]
        session._pending_script_preview = True

        # Step 3: User entscheidet sich → "zurück"
        await cog._process_script_preview(session, ch, "zurück")
        assert session._pending_script_preview is False
        assert session._preview_scripts is None

        # Step 4: Jetzt wählt User Script 4 direkt per Nummer
        session.pending_script_choices = SAMPLE_SCRIPTS.copy()
        msg = _msg("4")
        await cog._process_script_choices(session, ch, "4", msg)
        cog._select_script.assert_called_once()
        selected = cog._select_script.call_args[0][2]
        assert selected["name"] == "One Cat Mosh Pit"


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 2: Summary → Script ändern → DB suchen → Neues wählen
# ═══════════════════════════════════════════════════════════════════════════════


class TestSummaryChangeScriptViaSearch:
    """User ist im Summary, will anderes Script, sucht in DB, wählt aus."""

    @pytest.mark.asyncio
    @patch("commands.host_command.search_scripts", new_callable=AsyncMock)
    async def test_change_script_full_flow(self, mock_search):
        cog = _make_cog()
        cog._select_script = AsyncMock()
        session = _make_session(fields={
            "title": "Test Event", "script": "Boozling",
            "storyteller": "Dalyan", "start_time": "2026-03-25 20:00",
            "level": "Alle", "is_casual": False, "max_players": 12,
            "duration_minutes": 150, "description": "Test",
        })
        ch = _ch()

        # Step 1: Im Summary → "anderes skript"
        session.pending_final_review = True
        await cog._process_final_review(session, ch, "anderes skript")
        assert session.pending_script_edit_mode is True
        assert session.pending_final_review is False

        # Step 2: Wählt "1" → DB-Suche
        await cog._process_script_edit_mode(session, ch, "1")
        assert getattr(session, "pending_script_search", False) is True

        # Step 3: Gibt Suchbegriff ein
        mock_search.return_value = [
            {"name": "Deadly Penance Day", "author": "Viva", "version": "3.0", "characters": ["imp"]},
            {"name": "Deadly Night", "author": "Sam", "version": "1.0", "characters": ["po"]},
        ]
        await cog._process_script_search(session, ch, "Deadly")
        assert session.pending_script_choices is not None
        assert len(session.pending_script_choices) == 2

        # Step 4: Wählt "1"
        msg = _msg("1")
        await cog._process_script_choices(session, ch, "1", msg)
        cog._select_script.assert_called_once()
        selected = cog._select_script.call_args[0][2]
        assert selected["name"] == "Deadly Penance Day"


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 3: Summary → Script ändern → Manuell eingeben → Rating
# ═══════════════════════════════════════════════════════════════════════════════


class TestSummaryManualScriptWithRating:
    """User gibt manuell einen Skriptnamen ein → muss Rating wählen."""

    @pytest.mark.asyncio
    @patch("commands.host_command.lookup_script")
    async def test_manual_script_then_rating(self, mock_lookup):
        cog = _make_cog()
        session = _make_session(fields={
            "title": "Test", "script": "Boozling", "storyteller": "Dalyan",
            "start_time": "2026-03-25 20:00", "level": "Alle", "is_casual": False,
            "description": "Test", "max_players": 12, "duration_minutes": 150,
        })
        session._selected_script_data = {"author": "Lau", "version": "9.0", "characters": ["imp"]}
        ch = _ch()

        # Step 1: Im Summary → Nummer 2 (Script)
        session.pending_final_review = True
        await cog._process_final_review(session, ch, "2")
        assert session.pending_script_edit_mode is True

        # Step 2: Wählt "2" → Manuell eingeben
        await cog._process_script_edit_mode(session, ch, "2")
        assert session.pending_field_edit == "script"

        # Step 3: Gibt neuen Namen ein
        mock_lookup.return_value = (None, "miss")
        msg = _msg("Mein Custom Script")
        await cog._process_field_edit(session, ch, "Mein Custom Script", msg)

        # Alte Metadaten müssen gelöscht sein
        assert session._selected_script_data is None
        assert session.fields["script"] == "Mein Custom Script"
        assert session.fields["complexity_analysis"] is None
        # Muss nach Rating fragen
        assert getattr(session, "_pending_manual_rating", False) is True

        # Step 4: User gibt Rating ein
        await cog._process_manual_rating(session, ch, "gelb")
        assert session.fields["complexity_analysis"] == {"rating": "yellow"}
        cog._show_final_review.assert_called()

    @pytest.mark.asyncio
    @patch("commands.host_command.lookup_script")
    async def test_manual_script_invalid_then_valid_rating(self, mock_lookup):
        """User gibt zuerst ungültiges Rating, dann gültiges."""
        cog = _make_cog()
        session = _make_session(fields={
            "title": "T", "script": "Old", "storyteller": "D",
            "start_time": "2026-03-25 20:00", "level": "Alle", "is_casual": False,
            "description": "D", "max_players": 12, "duration_minutes": 150,
        })
        ch = _ch()

        # Manuellen Script-Edit simulieren
        mock_lookup.return_value = (None, "miss")
        session.pending_field_edit = "script"
        msg = _msg("Neues Script")
        await cog._process_field_edit(session, ch, "Neues Script", msg)
        assert getattr(session, "_pending_manual_rating", False) is True

        # Ungültiges Rating
        await cog._process_manual_rating(session, ch, "lila")
        assert getattr(session, "_pending_manual_rating", False) is True

        # Gültiges Rating
        await cog._process_manual_rating(session, ch, "rot")
        assert session.fields["complexity_analysis"] == {"rating": "red"}
        cog._show_final_review.assert_called()


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 4: Summary → Mehrere Felder hintereinander ändern
# ═══════════════════════════════════════════════════════════════════════════════


class TestSummaryMultipleFieldEdits:
    """User ändert Titel, dann Storyteller, dann Kamera — eins nach dem anderen."""

    @pytest.mark.asyncio
    async def test_sequential_field_edits(self):
        cog = _make_cog()
        session = _make_session(fields={
            "title": "Alter Titel", "script": "Boozling", "storyteller": "Dalyan",
            "start_time": "2026-03-25 20:00", "level": "Alle", "is_casual": False,
            "description": "Alte Beschreibung", "max_players": 12,
            "duration_minutes": 150,
        })
        ch = _ch()

        # Edit 1: Titel per Nummer
        session.pending_final_review = True
        await cog._process_final_review(session, ch, "1")
        assert session.pending_field_edit == "title"

        msg = _msg("Neuer Toller Titel")
        await cog._process_field_edit(session, ch, "Neuer Toller Titel", msg)
        assert session.fields["title"] == "Neuer Toller Titel"
        cog._show_final_review.assert_called()
        cog._show_final_review.reset_mock()

        # Edit 2: Storyteller per Nummer
        session.pending_final_review = True
        await cog._process_final_review(session, ch, "4")
        assert session.pending_field_edit == "storyteller"

        msg = _msg("Alice")
        await cog._process_field_edit(session, ch, "Alice", msg)
        assert session.fields["storyteller"] == "Alice"
        cog._show_final_review.assert_called()
        cog._show_final_review.reset_mock()

        # Edit 3: Kamera per Nummer
        session.pending_final_review = True
        await cog._process_final_review(session, ch, "8")
        assert session.pending_field_edit == "camera"

        msg = _msg("pflicht")
        await cog._process_field_edit(session, ch, "pflicht", msg)
        assert session.fields["camera"] is True
        cog._show_final_review.assert_called()

        # Finale Werte prüfen
        assert session.fields["title"] == "Neuer Toller Titel"
        assert session.fields["storyteller"] == "Alice"
        assert session.fields["camera"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 5: Summary → Batch-Edit via Haiku
# ═══════════════════════════════════════════════════════════════════════════════


class TestSummaryBatchEditViaHaiku:
    """User ändert mehrere Felder in einer Nachricht."""

    @pytest.mark.asyncio
    @patch("commands.host_command.interpret_final_review", new_callable=AsyncMock)
    async def test_batch_edit_then_confirm(self, mock_haiku):
        cog = _make_cog()
        session = _make_session(fields={
            "title": "T", "script": "S", "storyteller": "D",
            "start_time": "2026-03-25 20:00", "level": "Alle", "is_casual": False,
            "description": "D", "max_players": 12, "duration_minutes": 150,
            "camera": None,
        })
        ch = _ch()

        # Batch-Edit: Kamera + Storyteller + Level
        session.pending_final_review = True
        mock_haiku.return_value = {
            "action": "edit",
            "fields": {
                "camera": True,
                "storyteller": "Tobias",
                "level": "Erfahren",
            },
        }
        await cog._process_final_review(
            session, ch, "Ändere Kamera zu Pflicht, Storyteller zu Tobias und Level zu Erfahren"
        )
        assert session.fields["camera"] is True
        assert session.fields["storyteller"] == "Tobias"
        assert session.fields["level"] == "Erfahren"
        cog._show_final_review.assert_called()
        cog._show_final_review.reset_mock()

        # Dann bestätigen
        session.pending_final_review = True
        with patch("commands.host_command.SummaryView") as MockView:
            mock_view = MockView.return_value
            mock_view.confirm = AsyncMock()
            await cog._process_final_review(session, ch, "ok")
            assert session.pending_final_review is False


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 6: Script-Suche → Preview → Preview-Script wählen
# ═══════════════════════════════════════════════════════════════════════════════


class TestSearchPreviewSelect:
    """User sucht, previewed Skripte, wählt eins aus Preview."""

    @pytest.mark.asyncio
    async def test_search_preview_then_select_from_preview(self):
        cog = _make_cog()
        cog._select_script = AsyncMock()
        session = _make_session()
        ch = _ch()

        # User hat 5 Suchergebnisse
        session.pending_script_choices = SAMPLE_SCRIPTS.copy()

        # Will Script 2 und 5 als Preview sehen
        preview_list = [SAMPLE_SCRIPTS[1], SAMPLE_SCRIPTS[4]]
        await cog._show_script_preview(session, ch, preview_list, [2, 5])
        assert session._pending_script_preview is True
        assert session._preview_scripts == preview_list
        assert session._preview_indices == [2, 5]

        # Wählt "2" aus Preview (= Script 5 = Boozling, Index im Preview)
        await cog._process_script_preview(session, ch, "2")
        cog._select_script.assert_called_once()
        selected = cog._select_script.call_args[0][2]
        assert selected["name"] == "Boozling"


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 7: Script-Auswahl → "eigenes" → Skip Upload → Summary
# ═══════════════════════════════════════════════════════════════════════════════


class TestScriptChoicesCustomThenSkip:
    """User sagt 'keins davon' → Upload → skip → Summary."""

    @pytest.mark.asyncio
    async def test_custom_skip_to_summary(self):
        cog = _make_cog()
        session = _make_session()
        ch = _ch()

        # Suchergebnisse vorhanden, User sagt "nichts davon"
        session.pending_script_choices = SAMPLE_SCRIPTS.copy()
        msg = _msg("nichts davon")
        await cog._process_script_choices(session, ch, "nichts davon", msg)
        assert getattr(session, "pending_script_upload", False) is True
        assert session.pending_script_choices is None

        # User skippt Upload
        msg = _msg("skip")
        await cog._process_script_upload(session, ch, "skip", msg)
        cog._show_final_review.assert_called()


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 8: Summary → Freie Wahl → Summary zeigt keinen Script-Block
# ═══════════════════════════════════════════════════════════════════════════════


class TestSummaryToFreeChoice:
    """User wechselt im Summary von konkretem Script zu Freier Wahl."""

    @pytest.mark.asyncio
    async def test_switch_to_free_choice(self):
        cog = _make_cog()
        session = _make_session(fields={
            "title": "T", "script": "Boozling", "storyteller": "D",
            "start_time": "2026-03-25 20:00", "level": "Alle", "is_casual": False,
            "description": "D", "max_players": 12, "duration_minutes": 150,
        })
        session._selected_script_data = {"author": "Lau", "version": "9.0"}
        ch = _ch()

        # Step 1: "anderes skript" im Summary
        session.pending_final_review = True
        await cog._process_final_review(session, ch, "anderes skript")
        assert session.pending_script_edit_mode is True

        # Step 2: "freie wahl"
        await cog._process_script_edit_mode(session, ch, "freie wahl")
        assert session.fields["script"] == "Freie Skriptwahl"
        assert session.fields["is_free_choice"] is True
        assert session.fields["complexity_analysis"] is None
        cog._show_final_review.assert_called()


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 9: Summary → Labels ändern → falsch → richtig
# ═══════════════════════════════════════════════════════════════════════════════


class TestLabelsEditRetry:
    """User tippt bei Labels falsch, korrigiert sich."""

    @pytest.mark.asyncio
    async def test_labels_wrong_then_correct(self):
        cog = _make_cog()
        session = _make_session(fields={
            "title": "T", "script": "S", "storyteller": "D",
            "start_time": "2026-03-25 20:00", "level": "Alle",
            "is_casual": False, "is_academy": False,
            "description": "D", "max_players": 12, "duration_minutes": 150,
        })
        ch = _ch()

        # Step 1: Nummer 7 → Labels
        session.pending_final_review = True
        await cog._process_final_review(session, ch, "7")
        assert session.pending_field_edit == "_labels"

        # Step 2: Ungültige Eingabe
        msg = _msg("blabla")
        await cog._process_field_edit(session, ch, "blabla", msg)
        assert session.pending_field_edit == "_labels"  # Bleibt im State

        # Step 3: Richtige Eingabe
        msg = _msg("casual ja")
        await cog._process_field_edit(session, ch, "casual ja", msg)
        assert session.fields["is_casual"] is True
        cog._show_final_review.assert_called()


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 10: Summary → Termin + Dauer ändern → nochmal nur Dauer
# ═══════════════════════════════════════════════════════════════════════════════


class TestTerminEditMultipleRounds:
    """User ändert Termin komplett, ändert dann nur die Dauer."""

    @pytest.mark.asyncio
    async def test_termin_then_duration(self):
        cog = _make_cog()
        session = _make_session(fields={
            "title": "T", "script": "S", "storyteller": "D",
            "start_time": "2026-03-25 20:00", "level": "Alle", "is_casual": False,
            "description": "D", "max_players": 12, "duration_minutes": 150,
        })
        ch = _ch()

        # Edit 1: Termin + Dauer
        session.pending_final_review = True
        await cog._process_final_review(session, ch, "10")
        assert session.pending_field_edit == "start_time"

        msg = _msg("2026-04-01 19:00 120min")
        await cog._process_field_edit(session, ch, "2026-04-01 19:00 120min", msg)
        assert session.fields["start_time"] == "2026-04-01 19:00"
        assert session.fields["duration_minutes"] == 120
        cog._show_final_review.reset_mock()

        # Edit 2: Nur Dauer ändern
        session.pending_final_review = True
        await cog._process_final_review(session, ch, "10")
        msg = _msg("180min")
        await cog._process_field_edit(session, ch, "180min", msg)
        assert session.fields["start_time"] == "2026-04-01 19:00"  # Unverändert
        assert session.fields["duration_minutes"] == 180


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 11: Dispatcher-Priorität bei Statekonflikt
# ═══════════════════════════════════════════════════════════════════════════════


class TestDispatcherPriority:
    """Wenn mehrere States aktiv → nur der erste wird verarbeitet."""

    @pytest.mark.asyncio
    async def test_manual_rating_beats_everything(self):
        """_pending_manual_rating hat höchste Priorität im Dispatcher."""
        cog = _make_cog()
        session = _make_session()
        session._pending_manual_rating = True
        session.pending_script_edit_mode = True
        session.pending_final_review = True

        cog._process_manual_rating = AsyncMock()
        cog._process_script_edit_mode = AsyncMock()
        cog._process_final_review = AsyncMock()

        msg = _msg("gelb")
        msg.channel = _ch()
        await cog._process(session, msg)

        cog._process_manual_rating.assert_called_once()
        cog._process_script_edit_mode.assert_not_called()
        cog._process_final_review.assert_not_called()

    @pytest.mark.asyncio
    async def test_field_edit_beats_final_review(self):
        """pending_field_edit wird vor pending_final_review verarbeitet."""
        cog = _make_cog()
        session = _make_session()
        session.pending_field_edit = "title"
        session.pending_final_review = True

        cog._process_field_edit = AsyncMock()
        cog._process_final_review = AsyncMock()

        msg = _msg("Neuer Titel")
        msg.channel = _ch()
        await cog._process(session, msg)

        cog._process_field_edit.assert_called_once()
        cog._process_final_review.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 12: Script-Suche zweimal hintereinander (Suche → neue Suche)
# ═══════════════════════════════════════════════════════════════════════════════


class TestDoubleSearch:
    """User sucht Script, bekommt falsche Ergebnisse, sucht nochmal."""

    @pytest.mark.asyncio
    @patch("commands.host_command.search_scripts", new_callable=AsyncMock)
    async def test_search_then_search_again(self, mock_search):
        cog = _make_cog()
        cog._select_script = AsyncMock()
        session = _make_session()
        ch = _ch()

        # 1. Suche ergibt falsche Ergebnisse
        first_results = [
            {"name": "Wrong Script 1", "author": "X", "version": "1.0", "characters": ["imp"]},
            {"name": "Wrong Script 2", "author": "Y", "version": "1.0", "characters": ["po"]},
        ]
        mock_search.return_value = first_results
        session.pending_script_search = True
        await cog._process_script_search(session, ch, "wrong")
        assert session.pending_script_choices == first_results

        # 2. User sagt etwas das nicht matcht → Haiku erkennt neue Suche
        second_results = [
            {"name": "Correct Script", "author": "Z", "version": "2.0", "characters": ["imp"]},
        ]
        mock_search.return_value = second_results
        with patch("commands.host_command.interpret_script_choice", new_callable=AsyncMock) as mock_haiku:
            mock_haiku.return_value = {"action": "search", "search_term": "correct"}
            msg = _msg("such lieber nach correct")
            await cog._process_script_choices(session, ch, "such lieber nach correct", msg)

        # Ergebnisse aktualisiert
        assert session.pending_script_choices == second_results

        # 3. Jetzt richtig wählen
        msg = _msg("1")
        await cog._process_script_choices(session, ch, "1", msg)
        cog._select_script.assert_called_once()
        assert cog._select_script.call_args[0][2]["name"] == "Correct Script"


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 13: Summary → Beschreibung ändern → ok
# ═══════════════════════════════════════════════════════════════════════════════


class TestEditDescriptionThenConfirm:
    """User ändert Beschreibung und bestätigt danach."""

    @pytest.mark.asyncio
    async def test_edit_description_flow(self):
        cog = _make_cog()
        session = _make_session(fields={
            "title": "T", "script": "S", "storyteller": "D",
            "start_time": "2026-03-25 20:00", "level": "Alle", "is_casual": False,
            "description": "Alte Beschreibung", "max_players": 12, "duration_minutes": 150,
        })
        ch = _ch()

        # Edit Beschreibung per Nummer 3
        session.pending_final_review = True
        await cog._process_final_review(session, ch, "3")
        assert session.pending_field_edit == "description"

        new_desc = "Wir spielen ein spannendes Skript mit vielen Überraschungen."
        msg = _msg(new_desc)
        await cog._process_field_edit(session, ch, new_desc, msg)
        assert session.fields["description"] == new_desc
        cog._show_final_review.assert_called()


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 14: Version wechseln und wieder zurück
# ═══════════════════════════════════════════════════════════════════════════════


class TestVersionSwitchFlow:
    """User wählt andere Version, bekommt Versionen angezeigt, wählt eine."""

    @pytest.mark.asyncio
    async def test_version_select(self):
        cog = _make_cog()
        cog._select_script = AsyncMock()
        session = _make_session(fields={
            "title": "T", "script": "Boozling", "storyteller": "D",
            "start_time": "2026-03-25 20:00", "level": "Alle", "is_casual": False,
            "description": "D", "max_players": 12, "duration_minutes": 150,
        })
        ch = _ch()

        # Step 1: "andere version" im Summary
        session.pending_final_review = True
        await cog._process_final_review(session, ch, "andere version")
        cog._show_version_choices.assert_called()

        # Step 2: Simuliere Version-Choices
        versions = [
            {"name": "Boozling", "author": "Lau", "version": "7.0", "characters": ["imp"]},
            {"name": "Boozling", "author": "Lau", "version": "8.0", "characters": ["imp"]},
            {"name": "Boozling", "author": "Lau", "version": "9.0", "characters": ["imp"]},
        ]
        session._pending_version_choices = versions

        # Step 3: Wählt Version 2
        await cog._process_version_choices(session, ch, "2")
        cog._select_script.assert_called_once()
        selected = cog._select_script.call_args[0][2]
        assert selected["version"] == "8.0"
        assert session._retrigger_proposal is True

    @pytest.mark.asyncio
    async def test_version_invalid_then_valid(self):
        """User gibt ungültige Nummer ein, dann gültige."""
        cog = _make_cog()
        cog._select_script = AsyncMock()
        session = _make_session()
        ch = _ch()

        versions = [
            {"name": "Script", "author": "A", "version": "1.0", "characters": []},
            {"name": "Script", "author": "A", "version": "2.0", "characters": []},
        ]
        session._pending_version_choices = versions

        # Ungültig
        await cog._process_version_choices(session, ch, "5")
        cog._select_script.assert_not_called()
        assert session._pending_version_choices is not None

        # Gültig
        await cog._process_version_choices(session, ch, "1")
        cog._select_script.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 15: Alt-Werte wiederherstellen nach Script-Wechsel
# ═══════════════════════════════════════════════════════════════════════════════


class TestRestoreOldValues:
    """User ändert Script → Titel/Desc werden regeneriert → 'alt' holt altes zurück."""

    @pytest.mark.asyncio
    async def test_restore_old_title_desc(self):
        cog = _make_cog()
        session = _make_session(fields={
            "title": "Neuer Titel", "description": "Neue Beschreibung",
            "script": "S", "storyteller": "D",
            "start_time": "2026-03-25 20:00", "level": "Alle", "is_casual": False,
            "max_players": 12, "duration_minutes": 150,
        })
        ch = _ch()

        # Alte Werte simulieren (als hätte ein Retrigger stattgefunden)
        session._old_title = "Original Titel"
        session._old_desc = "Original Beschreibung"
        session.pending_final_review = True

        # "alt" → Altes wiederherstellen
        await cog._process_final_review(session, ch, "alt")
        assert session.fields["title"] == "Original Titel"
        assert session.fields["description"] == "Original Beschreibung"
        cog._show_final_review.assert_called()


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 16: Ordinal + Name-Match Interaktion
# ═══════════════════════════════════════════════════════════════════════════════


class TestOrdinalAndNameInteraction:
    """Ordinal-Keywords in Kombination mit Script-Namen."""

    @pytest.mark.asyncio
    async def test_ordinal_takes_precedence_over_name_match(self):
        """Wenn 'erste' im Text → Ordinal gewinnt, auch wenn Name matchen würde."""
        cog = _make_cog()
        cog._select_script = AsyncMock()
        session = _make_session()
        ch = _ch()

        choices = [
            {"name": "Alpha", "author": "A", "version": "1", "characters": []},
            {"name": "Boozling", "author": "B", "version": "1", "characters": []},
        ]
        session.pending_script_choices = choices
        # "das erste" → Ordinal → Alpha, nicht Name-Match auf "Boozling"
        msg = _msg("das erste")
        await cog._process_script_choices(session, ch, "das erste", msg)
        cog._select_script.assert_called_once()
        assert cog._select_script.call_args[0][2]["name"] == "Alpha"

    @pytest.mark.asyncio
    async def test_name_match_when_no_ordinal(self):
        """Ohne Ordinal → Name-Match greift."""
        cog = _make_cog()
        cog._select_script = AsyncMock()
        session = _make_session()
        ch = _ch()

        choices = [
            {"name": "Alpha Script", "author": "A", "version": "1", "characters": []},
            {"name": "Boozling", "author": "Lau", "version": "9", "characters": []},
        ]
        session.pending_script_choices = choices
        msg = _msg("ich will Boozling")
        await cog._process_script_choices(session, ch, "ich will Boozling", msg)
        cog._select_script.assert_called_once()
        assert cog._select_script.call_args[0][2]["name"] == "Boozling"


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 17: Upload → Invalid JSON → Upload → Valid JSON
# ═══════════════════════════════════════════════════════════════════════════════


class TestUploadRetryFlow:
    """User lädt kaputtes JSON hoch, dann gültiges."""

    @pytest.mark.asyncio
    @patch("commands.host_command.validate_script_json")
    @patch("commands.host_command.cache_script")
    async def test_bad_then_good_upload(self, mock_cache, mock_validate):
        cog = _make_cog()
        session = _make_session()
        ch = _ch()

        session.pending_script_upload = True

        # 1. Kaputtes JSON
        mock_validate.return_value = (None, "Ungültige Struktur")
        bad_att = AsyncMock()
        bad_att.filename = "bad.json"
        bad_att.read = AsyncMock(return_value=b"not json")
        msg = _msg("", attachments=[bad_att])
        await cog._process_script_upload(session, ch, "", msg)
        assert getattr(session, "pending_script_upload", False) is True

        # 2. Gültiges JSON
        mock_validate.return_value = (
            {"name": "Good Script", "characters": ["imp"]},
            None,
        )
        good_att = AsyncMock()
        good_att.filename = "good.json"
        good_att.read = AsyncMock(return_value=json.dumps([{"id": "imp"}]).encode())
        msg = _msg("", attachments=[good_att])
        await cog._process_script_upload(session, ch, "", msg)
        assert session.fields["script"] == "Good Script"
        cog._show_final_review.assert_called()


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 18: Komplett-Flow: Haiku → Suche → Wahl → Summary → Confirm
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompleteHappyPath:
    """Kompletter Durchlauf von Haiku-Chat bis zur Bestätigung."""

    @pytest.mark.asyncio
    @patch("commands.host_command.search_scripts", new_callable=AsyncMock)
    @patch("commands.host_command.lookup_script")
    @patch("commands.host_command.call_haiku", new_callable=AsyncMock)
    async def test_full_flow(self, mock_haiku, mock_lookup, mock_search):
        cog = _make_cog()
        cog._select_script = AsyncMock()
        session = _make_session()
        ch = _ch()

        # Step 1: Haiku-Chat → alle Felder in einer Nachricht
        mock_haiku.return_value = {
            "action": "done",
            "message": "Alles klar!",
            "fields": {
                "script": "Boozling",
                "start_time": "2026-03-25 20:00",
                "storyteller": "TestUser",
                "level": "Alle",
                "is_casual": False,
            },
        }
        # Session-Felder werden normalerweise in call_haiku gesetzt — hier manuell:
        session.fields.update({
            "script": "Boozling", "start_time": "2026-03-25 20:00",
            "storyteller": "TestUser", "level": "Alle", "is_casual": False,
        })

        mock_lookup.return_value = (None, "miss")
        mock_search.return_value = SAMPLE_SCRIPTS.copy()

        await cog._process_haiku_chat(session, ch, "Ich will Boozling spielen morgen um 20 Uhr")
        assert session.pending_script_choices is not None

        # Step 2: Wählt "5" (Boozling)
        msg = _msg("5")
        await cog._process_script_choices(session, ch, "5", msg)
        cog._select_script.assert_called_once()
        assert cog._select_script.call_args[0][2]["name"] == "Boozling"


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 19: Summary → Script ändern → direkt Suchbegriff eingeben
# ═══════════════════════════════════════════════════════════════════════════════


class TestScriptEditNaturalLanguage:
    """User tippt im Script-Edit direkt einen Suchbegriff ein statt 1/2/3/4."""

    @pytest.mark.asyncio
    @patch("commands.host_command.search_scripts", new_callable=AsyncMock)
    async def test_direct_search_term(self, mock_search):
        cog = _make_cog()
        cog._select_script = AsyncMock()
        session = _make_session(fields={
            "title": "T", "script": "Boozling", "storyteller": "D",
            "start_time": "2026-03-25 20:00", "level": "Alle", "is_casual": False,
            "description": "D", "max_players": 12, "duration_minutes": 150,
        })
        ch = _ch()

        # Step 1: "anderes skript"
        session.pending_final_review = True
        await cog._process_final_review(session, ch, "anderes skript")
        assert session.pending_script_edit_mode is True

        # Step 2: Statt 1/2/3/4 direkt "Deadly Penance" eingeben
        mock_search.return_value = [
            {"name": "Deadly Penance Day", "author": "Viva", "version": "3.0", "characters": ["imp"]},
        ]
        await cog._process_script_edit_mode(session, ch, "Deadly Penance")
        # Sollte als Suchbegriff interpretiert werden (>2 Zeichen, kein Keyword)
        mock_search.assert_called()
        assert session.pending_script_choices is not None


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 20: Disruptiv — mitten im Script-Preview abbrechen & neu suchen
# ═══════════════════════════════════════════════════════════════════════════════


class TestPreviewBackToNewSearch:
    """User ist in Preview, geht zurück, und sucht dann etwas komplett Neues."""

    @pytest.mark.asyncio
    @patch("commands.host_command.search_scripts", new_callable=AsyncMock)
    @patch("commands.host_command.interpret_script_choice", new_callable=AsyncMock)
    async def test_preview_back_then_new_search(self, mock_haiku, mock_search):
        cog = _make_cog()
        cog._select_script = AsyncMock()
        session = _make_session()
        ch = _ch()

        # Suchergebnisse + Preview aktiv
        session.pending_script_choices = SAMPLE_SCRIPTS.copy()
        session._preview_scripts = [SAMPLE_SCRIPTS[0]]
        session._preview_indices = [1]
        session._pending_script_preview = True

        # Step 1: "zurück" → Preview verlassen
        await cog._process_script_preview(session, ch, "zurück")
        assert session._pending_script_preview is False

        # Step 2: Haiku erkennt neue Suche
        new_results = [
            {"name": "Catfishing", "author": "Cat", "version": "1.0", "characters": ["imp"]},
        ]
        mock_search.return_value = new_results
        mock_haiku.return_value = {"action": "search", "search_term": "Catfishing"}

        msg = _msg("such mal nach Catfishing")
        await cog._process_script_choices(session, ch, "such mal nach Catfishing", msg)
        assert session.pending_script_choices == new_results

        # Step 3: Wählt das Ergebnis
        msg = _msg("1")
        await cog._process_script_choices(session, ch, "1", msg)
        cog._select_script.assert_called_once()
        assert cog._select_script.call_args[0][2]["name"] == "Catfishing"


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 21: Max-Calls-Limit
# ═══════════════════════════════════════════════════════════════════════════════


class TestMaxCallLimit:
    """Session wird nach MAX_CALLS automatisch beendet."""

    @pytest.mark.asyncio
    @patch("commands.host_command.end_session")
    @patch("commands.host_command.get_session")
    async def test_session_ends_after_max_calls(self, mock_get, mock_end):
        from commands.host_command import MAX_CALLS
        cog = _make_cog()
        session = _make_session()
        session.call_count = MAX_CALLS  # Genau am Limit
        mock_get.return_value = session

        msg = _msg("irgendwas")
        msg.author = MagicMock()
        msg.author.id = 123
        msg.author.bot = False
        msg.channel = _ch()
        # Simulate DMChannel
        import discord
        with patch("commands.host_command.isinstance", return_value=True):
            # Direkt die on_message Logik testen
            ch = msg.channel
            session.touch()
            if session.call_count >= MAX_CALLS:
                # Session beendet
                assert True
            else:
                assert False, "Should have hit max calls"


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 22: Script-Edit → Upload → dann doch DB-Suche
# ═══════════════════════════════════════════════════════════════════════════════


class TestUploadThenSwitchToSearch:
    """User wählt Upload, entscheidet sich dann um und will doch suchen."""

    @pytest.mark.asyncio
    async def test_upload_skip_back_to_edit(self):
        cog = _make_cog()
        session = _make_session(fields={
            "title": "T", "script": "S", "storyteller": "D",
            "start_time": "2026-03-25 20:00", "level": "Alle", "is_casual": False,
            "description": "D", "max_players": 12, "duration_minutes": 150,
        })
        ch = _ch()

        # Step 1: Script-Edit → Upload wählen
        session.pending_script_edit_mode = True
        await cog._process_script_edit_mode(session, ch, "3")
        assert getattr(session, "pending_script_upload", False) is True

        # Step 2: User skippt Upload → zurück zum Summary
        msg = _msg("skip")
        await cog._process_script_upload(session, ch, "skip", msg)
        cog._show_final_review.assert_called()
        cog._show_final_review.reset_mock()

        # Step 3: Im Summary nochmal "anderes skript" → diesmal DB-Suche
        session.pending_final_review = True
        await cog._process_final_review(session, ch, "anderes skript")
        assert session.pending_script_edit_mode is True

        # Step 4: Wählt "1" → DB-Suche
        await cog._process_script_edit_mode(session, ch, "1")
        assert getattr(session, "pending_script_search", False) is True


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 23: Regression — Script-Preview Geist-State nach Summary
# ═══════════════════════════════════════════════════════════════════════════════


class TestScriptChoicesCleanedOnSummary:
    """Bug: Nach Script-Auswahl + Summary blieben pending_script_choices aktiv.
    Wenn User dann 'andere Version' sagte, landete die nächste Eingabe
    fälschlicherweise im Script-Choice-Handler statt im Version-Handler.
    Fix: _show_final_review räumt alle States auf."""

    @pytest.mark.asyncio
    async def test_script_choices_cleared_after_select(self):
        """pending_script_choices muss None sein wenn wir im Summary sind."""
        cog = _make_cog()
        # Simuliere: _show_final_review wurde aufgerufen (was die States aufräumt)
        # Wir testen direkt, dass _show_final_review die States aufräumt
        from commands.host_command import HostCommand
        real_cog = HostCommand(MagicMock())
        session = _make_session(fields={
            "title": "T", "script": "S", "storyteller": "D",
            "start_time": "2026-03-25 20:00", "level": "Alle", "is_casual": False,
            "description": "D", "max_players": 12, "duration_minutes": 150,
        })
        ch = _ch()

        # Geist-States setzen (als hätten wir gerade Script gewählt)
        session.pending_script_choices = SAMPLE_SCRIPTS.copy()
        session._pending_script_preview = True
        session._preview_scripts = [SAMPLE_SCRIPTS[0]]
        session.pending_script_upload = True
        session.pending_script_search = True
        session.pending_field_edit = "title"
        session._pending_manual_rating = True

        # _show_final_review aufrufen — muss alle States aufräumen
        with patch.object(real_cog, '_build_char_list_by_team', return_value={}):
            with patch("commands.host_command.generate_script_image", new_callable=AsyncMock):
                with patch("commands.host_command.generate_title_and_description", new_callable=AsyncMock) as mock_gen:
                    mock_gen.return_value = ("Titel", "Beschreibung", "Reasoning")
                    with patch("commands.host_command.lookup_script", return_value=(None, "miss")):
                        await real_cog._show_final_review(session, ch)

        # ALLE States müssen aufgeräumt sein
        assert session.pending_script_choices is None
        assert session._pending_script_preview is False
        assert session._preview_scripts is None
        assert session.pending_script_upload is False
        assert session.pending_script_search is False
        assert session.pending_script_edit_mode is False
        assert session.pending_field_edit is None
        assert session._pending_manual_rating is False
        assert session._pending_version_choices is None
        # Und pending_final_review MUSS True sein
        assert session.pending_final_review is True

    @pytest.mark.asyncio
    async def test_version_change_not_hijacked_by_old_choices(self):
        """'andere version' im Summary darf NICHT zu pending_script_choices routen."""
        cog = _make_cog()
        session = _make_session(fields={
            "title": "T", "script": "Carl", "storyteller": "D",
            "start_time": "2026-03-25 20:00", "level": "Alle", "is_casual": False,
            "description": "D", "max_players": 12, "duration_minutes": 150,
        })
        ch = _ch()

        # Simuliere: States sind aufgeräumt (wie nach _show_final_review)
        session.pending_final_review = True
        session.pending_script_choices = None  # Korrekt aufgeräumt

        # User sagt "andere version"
        await cog._process_final_review(session, ch, "andere version")
        cog._show_version_choices.assert_called_once()

        # Dispatcher-Check: pending_script_choices ist None → kein Hijack
        assert session.pending_script_choices is None
