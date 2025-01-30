from collections import defaultdict
import json
import logging
import os
import re
from interactions import events
from interactions.models import Extension, listen, GuildCategory, GuildForum, GuildForumPost, User
from interactions.models.internal import tasks

MANUALS = {}

class Scanner(Extension):
    @listen()
    async def on_ready(self, event: events.Ready) -> None:
        if os.path.exists("manuals.json"):
            with open("manuals.json") as f:
                MANUALS.update(json.load(f))
        await self.iterate_threads()
        # await self.build_index()

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
                logging.info(f"Joining {thread.name}")
                await thread.join()
            pins = await thread.fetch_pinned_messages()
            for pin in pins:
                if pin._guild_id is None:
                    pin._guild_id = forum._guild_id
                MANUALS[forum.name][thread_id].setdefault("pins", {})[str(pin.id)] = {
                    "author": pin._author_id,
                    "content": pin.content,
                    "attachments": [attachment.filename for attachment in pin.attachments],
                    "url": pin.proto_url,
                }

    async def build_index(self) -> None:
        await self.write_page("board_games", "Board & Card Games", MANUALS["board-card-games"])
        await self.write_page("meta-games", "Meta Games", MANUALS["meta-games"])
        await self.write_page("video-games", "Video Games", MANUALS["video-games"])
        pass

    async def write_page(self, filename: str, title: str, data: dict) -> None:
        async def lookup_user(user_id: int) -> str:
            user: User = await self.bot.fetch_user(user_id)
            return user.display_name

        with open(f"docs/{filename}.md", "w", encoding='utf-8') as f:
            f.write('---\n')
            f.write('layout: default\n')
            f.write(f"title: {title}\n")
            f.write(f'permalink: /{filename}/\n')
            f.write('---\n')
            for thread_id, thread in data.items():
                if "Ready to Use" not in thread.get("tags", []):
                    continue
                url = f"discord://-/channels/1097532591650910289/{thread_id}"
                f.write(f'## [{thread["title"]}]({url})\n')
                f.write(f'by {await lookup_user(thread["author"])}\n')
                if "tags" in thread:
                    f.write(f'\nTags: {", ".join(thread["tags"])}\n')
                f.write('\n')
                if "pins" in thread:
                    for _pin_id, pin in thread["pins"].items():
                        data = self.interpret_pin(pin)
                        if "github_url" in data:
                            f.write(f'#### [{data["github_url"]}]({data["github_url"]})\n')
                        elif "attached_apworld" in data:
                            f.write(f'#### [{data["attached_apworld"]}]({pin["url"]})\n')

                f.write('\n')
        pass

    def interpret_pin(self, pin: dict) -> dict:
        ret = {}
        for attachment in pin["attachments"]:
            if attachment.endswith(".apworld"):
                ret["attached_apworld"] = attachment
        release = re.match(r"https://github.com/([\w_\-]+)/([\w_\-]+)/releases(/latest|/tag/([\w_\.\-]+))?", pin["content"])
        if release:
            ret["github_username"] = release.group(1)
            ret["github_repo"] = release.group(2)
            if release.group(4):
                ret["tag"] = release.group(4)
                ret["github_url"] = f"https://github.com/{ret['github_username']}/{ret['github_repo']}/releases/tag/{ret['tag']}"
            else:
                ret["github_url"] = f"https://github.com/{ret['github_username']}/{ret['github_repo']}/releases"
        return ret
