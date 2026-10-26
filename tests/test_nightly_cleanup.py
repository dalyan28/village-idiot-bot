"""Nächtliches Aufräumen um 2 Uhr: Posts und Threads beendeter Events weg, Daten bleiben (Dalyan, 26.10.2026)."""

from datetime import timedelta

from discord_ui import event_post
from tests.test_wizard_flow import GUILD, NOW, click, env, new_draft, run  # noqa: F401 (Fixture)


def _publish(bot):
    draft = new_draft(bot)
    click(bot, draft.id, "pick", "trouble_brewing")
    d = bot.store.get_draft(draft.id)
    data = d.data
    data.description = "x"
    bot.store.update_draft(d.id, data, "preview", int(NOW.timestamp()))
    click(bot, draft.id, "publish")
    return bot.store.list_events(GUILD)[-1]


def test_removes_post_and_thread_of_ended_events_only(env, monkeypatch):
    bot = env
    event = _publish(bot)
    msg = bot.channel.messages[event.message_id]
    deleted_threads = []

    class Thread:
        async def delete(self):
            deleted_threads.append(event.id)
    msg.thread = Thread()

    before_end = event.data.end - timedelta(minutes=1)
    assert run(event_post.remove_ended_posts(bot, bot.store, GUILD, before_end)) == 0  # läuft noch
    assert event.message_id in bot.channel.messages

    after_end = event.data.end + timedelta(hours=3)
    assert run(event_post.remove_ended_posts(bot, bot.store, GUILD, after_end)) == 1
    assert event.message_id not in bot.channel.messages and deleted_threads == [event.id]
    stored = bot.store.get_event(event.id)
    assert stored is not None and stored.message_id is None  # Daten bleiben, nur ohne Post

    # Ein beendetes Event ohne Post wird nicht neu gepostet
    monkeypatch.setattr(event_post, "now", lambda: after_end)
    assert run(event_post.update_event_message(bot, bot.store, stored, images_changed=False)) is None
    assert len(bot.channel.messages) == 0
