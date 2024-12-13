import os
import zipfile
import json
import pathlib
import glob

import aiohttp
from interactions.models import Extension, Message, InteractionContext, BaseChannel, Attachment
from interactions import events, listen

from .schema_validate import validate_json

class ManualChecker(Extension):
    known_checksums = {}

    @listen()
    async def on_ready(self, event: events.Ready) -> None:
        for checksums in glob.glob("checksums/*.checksums"):
            with open(checksums) as f:
                data = json.load(f)
                self.known_checksums[os.path.splitext(os.path.basename(checksums))[0]] = data

        for apworld in glob.glob("apworlds/*.apworld"):
            await self.check_apworld(apworld)
        pass

    @listen()
    async def on_message(self, event: events.MessageCreate) -> None:
        if event.message.author.bot:
            return

        if event.message.attachments:
            for attachment in event.message.attachments:
                if attachment.filename.endswith(".apworld"):
                    await self.inspect_apworld(event.message.channel, attachment)
                    return

    async def inspect_apworld(self, ctx: BaseChannel | InteractionContext, attachment: Attachment) -> None:
        data = await download_apworld(attachment.url)
        path = os.path.join("apworlds", attachment.filename)
        with open(path, "wb") as f:
            f.write(data)

        await self.check_apworld(path)

    async def check_apworld(self, path: str) -> None:
        checksums: dict[str, int] = {}
        jsons = {}
        errors = {}

        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
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

        found_version = self.identify_base_version(checksums)

        print(f"{path} matches {found_version}")
        for fn, data in jsons.items():
            if data is None:
                continue
            table = os.path.splitext(os.path.basename(fn))[0]
            v = await validate_json(table, data)
            if v:
                errors[fn] = v

        print(errors)


    def identify_base_version(self, checksums):
        found_version = None
        for version, known_checksums in self.known_checksums.items():
            match = True
            for fn, checksum in checksums.items():
                if fn not in known_checksums:
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
        return found_version

async def download_apworld(url) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.read()
