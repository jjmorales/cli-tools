# cli-tools

A growing collection of small, standalone command-line utilities. Each tool lives
in its own folder, is fully self-contained (its own `pyproject.toml`, tests, and
README), and can be installed directly from GitHub without cloning this repo or
installing any of the other tools.

## Tools

| Tool | Command | Summary |
|---|---|---|
| [convert-to-ascii](convert-to-ascii/README.md) | `convert-to-ascii` | Converts GIFs and images into per-frame ASCII art JSON. |

## Importing (installing) a tool

Every tool installs the same way. Requires Python 3.9+ and [pipx](https://pipx.pypa.io/)
(plain `pip` works too).

1. Install the tool straight from GitHub, pointing at its folder with `#subdirectory=`
   (replace `<you>` with the GitHub owner of this repo):

   ```
   pipx install "git+https://github.com/jjmorales/cli-tools.git#subdirectory=<tool-folder>"
   ```

2. Run it by its command name, e.g. `<tool-folder> --help`.
3. Check the tool's own README for any one-time setup.

Pin a version with `...cli-tools.git@v0.1.0#subdirectory=<tool-folder>`, and upgrade
with `pipx upgrade <tool-folder>`.

### Example: convert-to-ascii

```
pipx install "git+https://github.com/jjmorales/cli-tools.git#subdirectory=convert-to-ascii"
convert-to-ascii install     # one-time browser download (see the tool's README)
convert-to-ascii --help
```

## Adding a new tool

1. Create a new top-level folder named after the tool (e.g. `my-tool/`).
2. Make it self-contained: its own `pyproject.toml` (with a `[project.scripts]`
   entry), `src/`, `tests/`, `.gitignore`, and `README.md`. Don't import code from
   other tools or from the repo root.
3. Add a row to the **Tools** table above.

## Developing a tool

```
git clone https://github.com/jjmorales/cli-tools.git
cd cli-tools/<tool-folder>
python -m venv .venv && .venv\Scripts\activate     # source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
pytest
```
