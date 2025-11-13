#!/usr/bin/env python
# /// script
# dependencies = [
#   "mkdocs_gen_files",
#   "docstring-parser",
# ]
# ///
"""
This script auto-generates Markdown pages for a glob list of sources
to create a markdown display them with syntax highlighting.
"""

import os
import sys
import argparse
import re
from pathlib import Path

from docstring_parser import parse
import mkdocs_gen_files

LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".go": "golang",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
    ".sh": "bash",
    ".bu": "yaml",
    ".sls": "jinja",
    ".jinja": "jinja",
    "Containerfile": "dockerfile",
    ".toml": "toml",
    ".container": "toml",
    ".volume": "toml",
    ".service": "toml",
    ".conf": "toml",
    "Makefile": "makefile",
}

# List of extensions that are NOT processed by this script and are common in markdown
MEDIA_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".pdf",
    ".zip",
    ".gz",
    ".tar",
    ".tgz",
    ".mp4",
    ".webm",
    ".ogg",
)


# A list of glob patterns to search for from the project root
SOURCE_LIST = [
    "authority.py",
    "tools.py",
    "template.py",
    "os/__init__.py",
    "examples/**/*",
    "scripts/*",
]

OUTPUT_DOCS_DIR = "."
BASE_DIR = Path.cwd()


def _link_replacer(match):
    """
    Internal helper for re.sub to process a single link match.
    """
    link_text = match.group(1)
    link_url = match.group(2)

    # Check for external links
    if link_url.startswith("http://") or link_url.startswith("https://"):
        return match.group(0)  # Keep original
    # Check for anchor links
    if link_url.startswith("#"):
        return match.group(0)  # Keep original
    # Check for mailto links
    if link_url.startswith("mailto:"):
        return match.group(0)  # Keep original
    # Check if it already ends in .md
    if link_url.endswith(".md"):
        return match.group(0)  # Keep original
    # Check if it ends with a media file extension or is a directory link
    if link_url.endswith("/") or any(
        link_url.lower().endswith(ext) for ext in MEDIA_EXTENSIONS
    ):
        return match.group(0)  # Keep original

    # split out optional fragments or query params from path_part
    parts = link_url.split("#", 1)
    url_part = parts[0]
    fragment_part = f"#{parts[1]}" if len(parts) > 1 else ""
    url_parts = url_part.split("?", 1)
    path_part = url_parts[0]
    query_part = f"?{url_parts[1]}" if len(url_parts) > 1 else ""

    # Check if the path part is not empty
    if not path_part:
        return match.group(0)  # Keep original

    # Append .md, e.g. [link](path/to/file.py) -> [link](path/to/file.py.md)
    new_link_url = f"{path_part}.md{query_part}{fragment_part}"
    return f"[{link_text}]({new_link_url})"


def fix_markdown_links(content: str) -> str:
    """
    Parses Markdown content and appends .md to relative links
    that do not have a file extension or are known source files.
    """
    # Regex to find links: [text](url)
    # It's non-greedy to handle multiple links on one line
    link_regex = r"\[([^\]]+?)\]\(([^)]+?)\)"

    return re.sub(link_regex, _link_replacer, content)


def format_docstring(docstring, title, level=2):
    """Formats a single docstring into a Markdown section."""
    md = f"{'#' * level} {title}\n\n"
    if docstring.short_description:
        md += f"{docstring.short_description}\n\n"
    if docstring.long_description:
        md += f"{docstring.long_description}\n\n"

    if docstring.params:
        md += f"{'#' * (level + 1)} Parameters\n\n"
        for param in docstring.params:
            param_type = f"`{param.type_name}`" if param.type_name else ""
            md += f"- `{param.arg_name}` ({param_type}): {param.description}\n"
        md += "\n"

    if docstring.returns:
        md += f"{'#' * (level + 1)} Returns\n\n"
        return_type = f"`{docstring.returns.type_name}`" if docstring.returns.type_name else ""
        md += f"- {return_type}: {docstring.returns.description}\n\n"

    return md


def parse_python_file(file_path: Path) -> str:
    """Parses a Python file and generates Markdown documentation from its docstrings."""
    content = file_path.read_text()
    docstring = parse(content)
    md = ""

    if file_path.name == "__init__.py":
        md = f"# {file_path.parent.name}\n\n"
    else:
        md = f"# {file_path.name}\n\n"

    if docstring.short_description:
        md += f"{docstring.short_description}\n\n"
    if docstring.long_description:
        md += f"{docstring.long_description}\n\n"

    # The `parse` function returns a single Docstring object,
    # and we need to handle its contents directly.
    if hasattr(docstring, "params") and docstring.params:
        md += "## Parameters\n\n"
        for param in docstring.params:
            param_type = f"`{param.type_name}`" if param.type_name else ""
            md += f"- `{param.arg_name}` ({param_type}): {param.description}\n"
        md += "\n"

    if hasattr(docstring, "returns") and docstring.returns:
        md += "## Returns\n\n"
        return_type = f"`{docstring.returns.type_name}`" if docstring.returns.type_name else ""
        md += f"- {return_type}: {docstring.returns.description}\n\n"

    return md


def generate_docs(is_dry_run: bool):
    """
    Generates Markdown documentation from source files.
    """
    if is_dry_run:
        print("DRY-RUN --- NOT ACTUALLY TOUCHING ANY FILES")
    else:
        print("LIVE-RUN --- Generating files for mkdocs")

    for pattern in SOURCE_LIST:
        for file_path in sorted(BASE_DIR.glob(pattern)):
            if file_path.is_file():
                language = LANGUAGE_MAP.get(file_path.suffix)
                if language is None:
                    language = LANGUAGE_MAP.get(file_path.name)

                if language is None:
                    print(
                        f"Skipping  : {file_path.relative_to(BASE_DIR)}, (no language map)",
                        file=sys.stderr,
                    )
                    continue
                print(f"Processing: {file_path.relative_to(BASE_DIR)}", file=sys.stderr)
                relative_file_path = file_path.relative_to(BASE_DIR)

                # if file_path.suffix == ".py":
                # md_file_rel_path = (
                #     Path(OUTPUT_DOCS_DIR) / relative_file_path
                # ).with_suffix(".py.md")
                # content = parse_python_file(file_path)

                # print(
                #     f"  py-mod -> {md_file_rel_path}",
                #     file=sys.stderr,
                # )
                if file_path.suffix == ".md":
                    md_file_rel_path = Path(OUTPUT_DOCS_DIR) / relative_file_path
                    content = file_path.read_text()
                    content = fix_markdown_links(content)
                    print(
                        f"  verbat -> {md_file_rel_path}",
                        file=sys.stderr,
                    )
                else:
                    md_file_rel_path = (
                        Path(OUTPUT_DOCS_DIR) / relative_file_path
                    ).with_suffix(f"{file_path.suffix}.md")
                    content = f"""
# Source: `{relative_file_path}`

```{language} linenums="1"
--8<-- "{relative_file_path.as_posix()}"
```
"""
                    print(f"  source -> {md_file_rel_path}", file=sys.stderr)

                md_out_path_str = md_file_rel_path.as_posix()

                if not is_dry_run:
                    with mkdocs_gen_files.open(md_out_path_str, "w") as fd:
                        fd.write(content)
                    mkdocs_gen_files.set_edit_path(
                        md_out_path_str, relative_file_path.as_posix()
                    )


def main():
    parser = argparse.ArgumentParser(
        description="""
Generates Markdown documentation from source files.
- Run standalone (no args): Defaults to --dry-run.
- Run by mkdocs: Defaults to 'live' mode.
- --dry-run: select dry-run mode if needed.
- --force: Forces write of files outside of Markdown, for standalone testing.
""",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    _ = parser.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        help="Force script to run in simulation (dry-run) mode.",
    )
    _ = parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force script to run in 'live' mode (overrides --dry-run).",
    )

    args, unknown = parser.parse_known_args()
    IS_DRY_RUN = ((len(sys.argv) == 1) or args.dry_run) and not args.force
    generate_docs(is_dry_run=IS_DRY_RUN)


print(f"__name__:{__name__}")
main()
