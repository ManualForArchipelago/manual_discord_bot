import os
import attrs
from interactions.models import Embed

@attrs.define()
class Report:
    path: str
    name: str
    base_version: str
    errors: dict[str, list[str]]

    modified_hooks: list[str] = attrs.field(factory=list)
    checksums: dict[str, str] = attrs.field(factory=dict)

    def load_game(self, game_table: dict):
        if game_table is None:
            return
        game = game_table.get("game", {})
        creator = game_table.get("creator", "") or game_table.get("player", "")
        if game and creator:
            self.name = f"Manual_{game}_{creator}"

    def to_embed(self) -> Embed:
        embed = Embed(title=self.name)
        embed.add_field(name="Manual Version", value=self.base_version or "Unknown")
        if self.name.lower() not in self.filename().lower():
            self.errors[self.filename()] = [f"Filename should be {self.name.lower()}.apworld"]
        for fn, errors in self.errors.items():
            embed.add_field(name=f'{fn} errors', value="\n".join(f'`{e}`' for e in errors), inline=False)
        if self.modified_hooks:
            embed.add_field(name="Modified Hooks", value="\n".join(self.modified_hooks), inline=False)
        return embed

    def filename(self) -> str:
        return os.path.basename(self.path)
