import json
import aiohttp
import jsonschema
from jsonschema.exceptions import ValidationError

SCHEMAS = {}

async def validate_json(schema_table_name, table):
    errors = []
    githubSchemaBaseUrl = "https://raw.githubusercontent.com/ManualForArchipelago/Manual/main/schemas/"
    if isinstance(table, dict) and table.get("$schema"):
        url = table["$schema"]
    else:
        url = githubSchemaBaseUrl + "Manual." + schema_table_name + ".schema.json"

    if url not in SCHEMAS:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                SCHEMAS[url] = json.loads(await response.text())

    schema = SCHEMAS[url]
    if schema:
        try:
            jsonschema.validators.validate(instance=table, schema=schema)
        except ValidationError as e:
            print(f"Validation error for {schema_table_name}: {e.message}")
            errors.append(e.message)
    else:
        print(f"Could not find schema for {schema_table_name}")
    return errors
