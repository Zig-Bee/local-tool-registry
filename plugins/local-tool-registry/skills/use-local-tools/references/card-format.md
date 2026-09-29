# Capability card

The registry CLI accepts `register --file CARD.json`. The required field is `path`; `name` is recommended and otherwise defaults to the directory name.

```json
{
  "name": "Example local converter",
  "path": "/absolute/path/to/project",
  "description": "Convert the documented input format to plain text.",
  "capabilities": ["document conversion"],
  "input_types": ["document"],
  "output_types": ["text"],
  "invocation": {
    "argv": ["/absolute/path/to/environment/bin/converter"],
    "cwd": "/absolute/path/to/project",
    "required_env": []
  }
}
```

Use actual installed locations, not this illustrative path. Keep the entrypoint in argv as an argument array; user task arguments are chosen when executing. required_env lists names only, never values or secrets. Metadata does not authorize execution. Unknown project metadata is discovered as candidate; registration with an entrypoint becomes configured. An existing path or a README claim is not functional verification.
