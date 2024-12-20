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
            print(f"Validation error for {schema_table_name}: {parseJsonSchemaException(e)}")
            errors.append(parseJsonSchemaException(e))
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

def parseJsonSchemaException(e: ValidationError) -> str:
    error = e.message
    if e.validator == 'type':
        error = f"Type error in the property '{e.json_path.lstrip('$.')}': " + e.message
    elif e.validator == 'oneOf':
        error = f"At least one of the following properties must be present: {[p['required'] for p in e.validator_value]}"
    elif e.validator == "additionalProperties":
        error = f"One of your defined property is invalid, it was found at/in '{e.json_path.lstrip('$.')}' and may have unexpected results. \n   Full error: {e.message}"
    # elif e.validator == 'required':
    #     error = f"" + e.message
    return error
