import io
import os
import re
import time
import zipfile
import json
import pathlib
import glob
import ast
import base64
import difflib

import aiohttp
from interactions.models import Extension, Message, Attachment, DMChannel, ComponentContext, component_callback
from interactions.models.discord.components import Button, ButtonStyle, spread_to_rows
from interactions import File, events, listen
from interactions.models.internal import tasks

from .report import Report
from .validate_logic import validate_regions
from .schema_validate import validate_json
from shared import configuration, limited_dict

SUPPORT_CHANNELS = [
    1097538232914296944, # manual-dev
    1097891385190928504, # manual-unstable
    1098306155492687892, # manual-support
    1098306190414450779, # manual-support-unstable
    1174806714130898964, # Rhythm Game Thread
]

class ManualChecker(Extension):
    known_checksums = {}
    known_hooks = {}
    latest_stable = None
    latest_unstable = None

    reports = limited_dict.LimitedSizeDict(size_limit=100)

    @listen()
    async def on_ready(self, event: events.Ready) -> None:
        for checksums in glob.glob("checksums/*.checksums"):
            with open(checksums) as f:
                data = json.load(f)
                self.known_checksums[os.path.splitext(os.path.basename(checksums))[0]] = data
        for checksums in glob.glob("checksums/*.hooks"):
            with open(checksums) as f:
                data = json.load(f)
                self.known_hooks[os.path.splitext(os.path.basename(checksums))[0]] = data
        await self.download_base_versions()
        if configuration.get("check_existing_apworlds", False):
            for apworld in glob.glob("apworlds/*.apworld"):
                await self.check_apworld(apworld)

    @listen()
    async def on_message(self, event: events.MessageCreate) -> None:
        if event.message.author.bot:
            return
        if event.message._channel_id not in SUPPORT_CHANNELS and not isinstance(event.message.channel, DMChannel):
            return

        if event.message.attachments:
            for attachment in event.message.attachments:
                if attachment.filename.endswith(".apworld"):
                    await self.inspect_apworld(event.message, attachment)
                    return

    async def inspect_apworld(self, message: Message, attachment: Attachment) -> None:
        data = await download_apworld(attachment.url)
        path = os.path.join("apworlds", attachment.filename)
        with open(path, "wb") as f:
            f.write(data)

        report = await self.check_apworld(path)
        components = []
        if report.modified_hook_functions: # or report.modified_hooks:
            components.append(Button(label="View Modified Hooks", custom_id=f"view_hooks:{report.id}", style=ButtonStyle.BLURPLE))
        if "Missing archipelago.json" in report.errors.get("archipelago.json", []):
            components.append(Button(label="Add missing archipelago.json", custom_id=f"add_ap_manifest:{report.id}", style=ButtonStyle.GREEN))
        await message.reply(embed=report.to_embed(), components=components)


    @component_callback(re.compile(r"view_hooks:(\d+)"))
    async def list_modifications(self, ctx: ComponentContext) -> None:
        report = self.reports.get(int(ctx.custom_id.split(":")[1]))
        if not report:
            await ctx.send("Report has expired", ephemeral=True)
            return
        components = []
        # for i, hook in enumerate(report.modified_hooks):
        #     components.append(Button(label=hook, custom_id=f"view_file:{report.id}:{i}", style=ButtonStyle.BLURPLE))
        for i, hook in enumerate(report.modified_hook_functions):
            components.append(Button(label=hook, custom_id=f"view_func:{report.id}:{i}", style=ButtonStyle.GREEN))
        return await ctx.send("Select a hook to view", components=spread_to_rows(*components) if components else None, ephemeral=True)

    @component_callback(re.compile(r"view_func:(\d+):(\d+)"))
    async def view_function(self, ctx: ComponentContext) -> None:
        report = self.reports.get(int(ctx.custom_id.split(":")[1]))
        if not report:
            await ctx.send("Report has expired", ephemeral=True)
            return
        index = int(ctx.custom_id.split(":")[2])
        hook_name = report.modified_hook_functions[index]
        hook = base64.b64decode(report.hook_checksums.get(hook_name).encode()).decode()
        base = base64.b64decode(self.known_hooks[report.base_version].get(hook_name).encode()).decode()
        diff = difflib.unified_diff(base.splitlines(), hook.splitlines(), lineterm="")
        diff_text = "\n".join(diff)
        if len(diff_text) > 2000:
            buffer = io.BytesIO()
            buffer.write(diff_text.encode())
            buffer.seek(0)
            diff_file = File(file=buffer, file_name=f"{hook_name}.txt")
            return await ctx.send("", file=diff_file, ephemeral=True)
        await ctx.send("```diff\n" + diff_text + "```", ephemeral=True)

    @component_callback(re.compile(r"add_ap_manifest:(\d+)"))
    async def add_ap_manifest(self, ctx: ComponentContext) -> None:
        await ctx.defer(ephemeral=True)
        report: Report = self.reports.get(int(ctx.custom_id.split(":")[1]))
        if not report:
            await ctx.send("Report has expired", ephemeral=True)
            return

        # Logic to add the missing archipelago.json
        with zipfile.ZipFile(report.path, 'a') as zf:
            ap_manifest = {
                "version": 7,
                "compatible_version": 7,
                "game": report.name,
            }
            filename = os.path.splitext(report.filename)[0] + "/archipelago.json"
            zf.writestr(filename, json.dumps(ap_manifest, indent=4))
        await ctx.send(content="Updated APWorld with archipelago.json:", file=File(report.path, os.path.basename(report.path)))

    async def check_apworld(self, path: str) -> Report:
        checksums: dict[str, int] = {}
        hook_checksums: dict[str, int] = {}
        jsons = {}
        errors = {}
        asts: dict[str, ast.Module] = {}


        report_id = int(time.time() % 1735650000)
        report = Report(report_id, path, os.path.basename(path), None, errors)
        self.reports[report.id] = report

        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                if info.filename.startswith("__MACOSX"):
                    continue
                p = pathlib.Path(info.filename)
                fn = '/'.join(p.parts[1:])
                if '__pycache__' in fn:
                    continue

                checksums[fn] = zf.getinfo(info.filename).CRC
                if fn.endswith(".json"):
                    self.parse_json_file(jsons, errors, zf, info, fn)
                elif fn.endswith('.py'):
                    self.parse_source_code(asts, report, zf, info, fn)

        if not [fn for fn in asts if '/' not in fn]:
            init_location = [p.filename for p in zf.infolist() if p.filename.endswith('__init__.py')][0]
            subfolder = init_location.split('/')[0] + '/'
            report.errors[os.path.basename(path)] = [f"__init__.py found in {init_location}, should be in {init_location.removeprefix(subfolder)}"]
            badfolder = init_location.split('/')[1] + '/'
            asts = {fn.removeprefix(badfolder): asts[fn] for fn in asts if fn.startswith(badfolder)}
            checksums = {fn.removeprefix(badfolder): checksums[fn] for fn in checksums if fn.startswith(badfolder)}

        self.hash_functions(hook_checksums, asts)


        with open(os.path.join(os.path.splitext(path)[0] + ".checksums"), "w") as f:
            json.dump(checksums, f, indent=1)
        with open(os.path.join(os.path.splitext(path)[0] + ".hooks"), "w") as f:
            json.dump(hook_checksums, f, indent=1)

        report.load_game(jsons.get("data/game.json", {}))
        report.checksums = checksums
        report.hook_checksums = hook_checksums

        found_version = self.identify_base_version(checksums, report)

        print(f"{path} matches {found_version}")
        ap_manifest = None
        for fn, data in jsons.items():
            if data is None:
                continue
            table = os.path.splitext(os.path.basename(fn))[0]
            v = await validate_json(table, data)
            if v:
                errors[fn] = v
            if table == "regions":
                validate_regions(data, report)
            if fn == "archipelago.json":
                ap_manifest = data

        # if not ap_manifest:
        #     errors["archipelago.json"] = ["Missing archipelago.json"]
        if ap_manifest and ap_manifest.get("game") != report.name:
            errors["archipelago.json"] = [f"archipelago.json game field should be `{report.name}`"]

        print(errors)
        return report

    def parse_json_file(self, jsons, errors, zf, info, fn):
        with zf.open(info) as f:
            try:
                jsons[fn] = json.load(f)
            except json.JSONDecodeError as e:
                print(f"Failed to load {fn}")
                jsons[fn] = None
                errors[fn] = [str(e)]

    def parse_source_code(self, asts, report, zf, info, fn):
        try:
            with zf.open(info) as f:
                asts[fn] = ast.parse(f.read(), report.filename + '/' + fn)
        except SyntaxError as e:
            print(f"Failed to parse {fn}")
            report.errors[fn] = [str(e)]

    def hash_functions(self, hook_checksums, asts):
        for fn, tree in asts.items():
            module_name = os.path.splitext(os.path.basename(fn))[0]
            if fn.startswith('hooks/'):
                for obj in tree.body:
                    if isinstance(obj, ast.FunctionDef):
                        hook_checksums[f'{module_name}.{obj.name}'] = base64.b64encode(ast.unparse(obj).encode()).decode()


    def identify_base_version(self, checksums, report: Report) -> str:
        found_version = None
        for version, known_checksums in self.known_checksums.items():
            match = True
            modified_hooks = []
            for fn, checksum in checksums.items():
                if fn not in known_checksums:
                    continue
                if fn.startswith("hooks/") and known_checksums[fn] != checksum:
                    modified_hooks.append(fn)
                    continue
                if '/' in fn:
                    continue
                else:
                    if '/' not in fn and known_checksums[fn] != checksum:
                        # print(f"{path} does not match {version} because {fn} does not match: {known_checksums[fn]} != {checksum}")
                        match = False
                        continue
            if match:
                found_version = version
                report.base_version = version
                report.modified_hooks = modified_hooks
                if found_version == self.latest_stable:
                    report.latest = "Stable"
                elif found_version == self.latest_unstable:
                    report.latest = "Unstable"
                break
        if found_version:
            if found_version in self.known_hooks:
                for hook, checksum in report.hook_checksums.items():
                    if hook not in self.known_hooks[found_version]:
                        continue
                    elif self.known_hooks[found_version][hook] != checksum:
                        report.modified_hook_functions.append(hook)
                        print(f"Hook {hook} has been modified")
        return found_version

    async def download_base_versions(self):
        latest_stable = None
        latest_unstable = None
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.github.com/repos/ManualForArchipelago/Manual/releases") as response:
                data = await response.json()
                for release in data:
                    for asset in release["assets"]:
                        if asset["name"].endswith(".apworld"):
                            if latest_unstable is None and latest_stable is None and "unstable" in release["tag_name"]:
                                latest_unstable = release['tag_name']
                            elif latest_stable is None and "manual_stable" in release["tag_name"]:
                                latest_stable = release['tag_name']
                            path = os.path.join("apworlds", release["tag_name"] + ".apworld")
                            checksum_path = os.path.join("checksums", f"{release['tag_name']}.checksums")
                            hooks_path = os.path.join("checksums", f"{release['tag_name']}.hooks")
                            if os.path.exists(checksum_path) and os.path.exists(hooks_path):
                                continue
                            url = asset["browser_download_url"]
                            if not os.path.exists(path):
                                data = await download_apworld(url)
                                with open(path, "wb") as f:
                                    f.write(data)
                            report = await self.check_apworld(path)

                            with open(checksum_path, "w") as f:
                                json.dump(report.checksums, f, indent=1)
                            with open(hooks_path, "w") as f:
                                json.dump(report.hook_checksums, f, indent=1)
                            self.known_checksums[release["tag_name"]] = report.checksums
        self.latest_stable = latest_stable
        self.latest_unstable = latest_unstable

    @tasks.Task.create(tasks.CronTrigger("0 0 * * *"))
    async def daily_tasks(self) -> None:
        await self.download_base_versions()


async def download_apworld(url) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.read()
