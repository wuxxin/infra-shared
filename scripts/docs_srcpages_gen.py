"""
This script auto-generates Markdown pages for a glob list of sources
to create a markdown display them with syntax highlighting.
"""

import os
import sys
from pathlib import Path
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
    ".container": "toml",
    ".volume": "toml",
    ".service": "toml",
    ".conf": "toml",
}

# A list of glob patterns to search for from the project root
SOURCE_LIST = [
    "examples/**",
    # e.g., "src/**/*.py", "config.toml"
]

OUTPUT_DOCS_DIR = "src"
BASE_DIR = Path(__file__).resolve().parent.parent

for pattern in SOURCE_LIST:
    # Find all files matching the glob pattern, relative to the project root
    for file_path in sorted(BASE_DIR.glob(pattern)):
        if file_path.is_file():
            # Determine the language
            language = LANGUAGE_MAP.get(file_path.suffix)
            if language is None:
                # Check for full filenames like 'Containerfile'
                language = LANGUAGE_MAP.get(file_path.name)

            if language is None:
                # Skip files we don't know how to highlight
                print(
                    f"  Skipping (no language map): {file_path.relative_to(BASE_DIR)}",
                    file=sys.stderr,
                )
                continue

            print(f"  Processing: {file_path.relative_to(BASE_DIR)}", file=sys.stderr)

            # Calculate paths and content
            # Path of the source file relative to the project root
            relative_file_path = file_path.relative_to(BASE_DIR)

            if file_path.suffix == ".md":
                # It's a Markdown file
                # Path: Keep original name, just place under OUTPUT_DOCS_DIR
                md_file_rel_path = Path(OUTPUT_DOCS_DIR) / relative_file_path
                # Content: Read the original file verbatim
                content = file_path.read_text()
                print(f"    -> as verbatim markdown: {md_file_rel_path}", file=sys.stderr)
            else:
                # It's another source code file
                # Path: Add .md suffix for the new page
                md_file_rel_path = (Path(OUTPUT_DOCS_DIR) / relative_file_path).with_suffix(
                    f"{file_path.suffix}.md"
                )
                # Content: Create the snippet
                content = f"""
# Source: `{file_path.name}`

```{language} linenums="1"
--8<-- "{relative_file_path.as_posix()}"
```

"""
            print(f" -> as source view: {md_file_rel_path}", file=sys.stderr)

            # Write the new file
            md_out_path_str = md_file_rel_path.as_posix()
            with mkdocs_gen_files.open(md_out_path_str, "w") as fd:
                fd.write(content)

            # Set the edit path to point to the *original* source file
            mkdocs_gen_files.set_edit_path(md_out_path_str, relative_file_path.as_posix())
