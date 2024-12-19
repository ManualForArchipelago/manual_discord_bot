import json
import aiohttp
import jsonschema
from jsonschema.exceptions import ValidationError

SCHEMAS = {}

async def validate_json(schema_table_name, table):
    errors = []
    githubSchemaBaseUrl = "https://raw.githubusercontent.com/ManualForArchipelago/Manual/main/schemas/"
    schema = None
    if isinstance(table, dict) and table.get("$schema"):
        url = table["$schema"]
        if await download_schema(schema_table_name, url):
            schema = SCHEMAS[url]
    if not schema:
        url = githubSchemaBaseUrl + "Manual." + schema_table_name + ".schema.json"
        await download_schema(schema_table_name, url)

    schema = SCHEMAS.get(url, None)
    if schema:
        try:
            jsonschema.validators.validate(instance=table, schema=schema)
        except ValidationError as e:
            print(f"Validation error for {schema_table_name}: {e.message}")
            errors.append(e.message)
    else:
        print(f"Could not find schema for {schema_table_name}")
    return errors

async def download_schema(schema_table_name, url):
    if url in SCHEMAS:
        return True
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    print(f"Could not fetch schema for {schema_table_name}")
                    return False
                SCHEMAS[url] = json.loads(await response.text())
                return True
    except aiohttp.InvalidUrlClientError:
        print(f"Invalid schema url for {schema_table_name}")
        return False
    except json.JSONDecodeError:
        print(f"Invalid schema for {schema_table_name}")
        return False
