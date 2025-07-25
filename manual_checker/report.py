import os
import attrs
from interactions.models import Embed

@attrs.define()
class Report:
    id: int
    path: str
    name: str
    base_version: str
    errors: dict[str, list[str]]

    modified_hooks: list[str] = attrs.field(factory=list)
    checksums: dict[str, int] = attrs.field(factory=dict)
    hook_checksums: dict[str, str] = attrs.field(factory=dict)
    modified_hook_functions: list[str] = attrs.field(factory=list)
    latest: str = attrs.field(default=None)

    def load_game(self, game_table: dict):
        if game_table is None:
            return
        game = game_table.get("game", {})
        creator = game_table.get("creator", "") or game_table.get("player", "")
        if game and creator:
            self.name = f"Manual_{game}_{creator}"

    def to_embed(self) -> Embed:
        embed = Embed(title=self.name)
        ver = self.base_version
        if self.latest:
            ver += f" (Latest {self.latest})"
        embed.add_field(name="Manual Version", value=ver or "Unknown")
        #if self.name.lower() not in self.filename.lower():
        #    self.errors[self.filename] = [f"Filename should be {self.name.lower()}.apworld"]
        for fn, errors in self.errors.items():
            embed.add_field(name=f'{fn} errors', value="\n".join(f'`{e}`' for e in errors), inline=False)
        if self.modified_hooks:
            embed.add_field(name="Modified Hook Files", value="\n".join(self.modified_hooks), inline=False)
        if self.modified_hook_functions:
            embed.add_field(name="Modified Hook Functions", value="\n".join(self.modified_hook_functions), inline=False)
        return embed

    @property
    def filename(self) -> str:
        return os.path.basename(self.path)
