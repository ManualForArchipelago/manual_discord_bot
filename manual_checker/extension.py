import os
import zipfile
import json
import pathlib
import glob

import aiohttp
from interactions.models import Extension, Message, Attachment, DMChannel
from interactions import events, listen
from interactions.models.internal import tasks

from manual_checker.report import Report
from .schema_validate import validate_json
from shared import configuration

SUPPORT_CHANNELS = [
    1097538232914296944, # manual-dev
    1097891385190928504, # manual-unstable
    1098306155492687892, # manual-support
    1098306190414450779, # manual-support-unstable
]

class ManualChecker(Extension):
    known_checksums = {}

    @listen()
    async def on_ready(self, event: events.Ready) -> None:
        for checksums in glob.glob("checksums/*.checksums"):
            with open(checksums) as f:
                data = json.load(f)
                self.known_checksums[os.path.splitext(os.path.basename(checksums))[0]] = data
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
        await message.reply(embed=report.to_embed())


    async def check_apworld(self, path: str) -> Report:
        checksums: dict[str, int] = {}
        jsons = {}
        errors = {}

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
                    with zf.open(info) as f:
                        try:
                            jsons[fn] = json.load(f)
                        except json.JSONDecodeError as e:
                            print(f"Failed to load {fn}")
                            jsons[fn] = None
                            errors[fn] = [str(e)]
        with open(os.path.join(os.path.splitext(path)[0] + ".checksums"), "w") as f:
            json.dump(checksums, f, indent=1)

        report = Report(path, os.path.basename(path), None, errors)
        report.load_game(jsons.get("data/game.json", {}))
        report.checksums = checksums

        found_version = self.identify_base_version(checksums, report)

        print(f"{path} matches {found_version}")
        for fn, data in jsons.items():
            if data is None:
                continue
            table = os.path.splitext(os.path.basename(fn))[0]
            v = await validate_json(table, data)
            if v:
                errors[fn] = v

        print(errors)
        return report


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
                break
        return found_version

    async def download_base_versions(self):
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.github.com/repos/ManualForArchipelago/Manual/releases") as response:
                data = await response.json()
                for release in data:
                    for asset in release["assets"]:
                        if asset["name"].endswith(".apworld"):
                            path = os.path.join("apworlds", release["tag_name"] + ".apworld")
                            checksum_path = os.path.join("checksums", f"{release['tag_name']}.checksums")
                            if os.path.exists(checksum_path):
                                continue
                            url = asset["browser_download_url"]
                            data = await download_apworld(url)
                            with open(path, "wb") as f:
                                f.write(data)
                            report = await self.check_apworld(path)

                            with open(checksum_path, "w") as f:
                                json.dump(report.checksums, f, indent=1)
                            self.known_checksums[release["tag_name"]] = report.checksums

    @tasks.Task.create(tasks.CronTrigger("0 0 * * *"))
    async def daily_tasks(self) -> None:
        await self.download_base_versions()


async def download_apworld(url) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.read()
