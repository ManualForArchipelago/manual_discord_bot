from interactions.models import listen, Extension, ThreadChannel
from interactions.api.events import MessageReactionAdd, MessageReactionRemove
from interactions.client.utils import misc_utils

class Pins(Extension):
    @listen()
    async def on_message_reaction_add(self, event: MessageReactionAdd) -> None:
        if not can_pin(event):
            return
        if event.emoji.name == '📌':
            await event.message.pin()

    @listen()
    async def on_message_reaction_remove(self, event: MessageReactionRemove) -> None:
        if not can_pin(event):
            return
        if event.emoji.name == '📌':
            reaction = misc_utils.find(lambda r: r.emoji.name == '📌', event.message.reactions)
            if reaction and reaction.count > 1:
                return
            # raw fires before count is updated, so this is off-by-one if it's in the cache (but not if we fetched it)
            await event.message.unpin()


def can_pin(event: MessageReactionAdd | MessageReactionRemove) -> bool:
    channel = event.message.channel
    if not isinstance(channel, ThreadChannel):
        return False
    if channel.parent_channel.category.id != 1097565035066298378:
        # Hardcoded reference to the "Games in Manual" category
        return False
    if event.author.id != channel.owner_id:
        return False
    return True
