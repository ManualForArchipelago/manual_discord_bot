from collections import defaultdict
import json
import os
from interactions import events
from interactions.models import Extension, listen, GuildCategory, GuildForum, GuildForumPost
from interactions.models.internal import tasks

MANUALS = {}

class Scanner(Extension):
    @listen()
    async def on_ready(self, event: events.Ready) -> None:
        if os.path.exists("manuals.json"):
            with open("manuals.json") as f:
                MANUALS.update(json.load(f))
        await self.iterate_threads()

    @tasks.Task.create(tasks.CronTrigger("0 0 * * *"))
    async def daily_tasks(self) -> None:
        await self.iterate_threads()

    async def iterate_threads(self) -> None:
        category: GuildCategory = self.bot.get_channel(1097565035066298378)
        if category is None:
            return
        for forum in category.channels:
            if isinstance(forum, GuildForum):
                await self.scan_forum(forum)
        with open("manuals.json", "w") as f:
            json.dump(MANUALS, f, indent=2)

    async def scan_forum(self, forum: GuildForum) -> None:
        MANUALS.setdefault(forum.name, defaultdict(dict))
        for thread in await forum.fetch_posts():
            await self.scan_thread(forum, thread)
        older = forum.archived_posts()
        async for thread in older:
            await self.scan_thread(forum, thread)

    async def scan_thread(self, forum: GuildForum, thread: GuildForumPost) -> None:
        thread_id = str(thread.id)
        MANUALS[forum.name].setdefault(thread_id, {}).update({
                "title": thread.name,
                "author": thread.owner_id,
            })
        if thread.applied_tags:
            MANUALS[forum.name][thread_id]["tags"] = [tag.name for tag in thread.applied_tags]
        if not thread.archived:
            # A bunch of stuff not worth doing for threads that havn't been touched in a while
            if not MANUALS[forum.name].setdefault(thread_id, {}).get("_joined_thread", False):
                MANUALS[forum.name][thread_id]["_joined_thread"] = True
                await thread.join()
            pins = await thread.fetch_pinned_messages()
            for pin in pins:
                MANUALS[forum.name][thread_id].setdefault("pins", {})[pin.id] = {
                    "author": pin._author_id,
                    "content": pin.content,
                    "attachments": [attachment.filename for attachment in pin.attachments],
                }
