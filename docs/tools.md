## Tools

### jinja

jinja_run: renders a template string with environment, with optional includes from searchpath
jinja_run_template: renders a template file available from searchpath with environment

#### file related custom filter

- "sub_dir/filename"|get_file_mode()
    - a string with the octal filemode of the file in searchpath[0]/filename, or "" if not found
- "sub_dir/filename"|has_executable_bit()
    - a string with either "true" or "false" depending the executable bit, or "" if not found
- "sub_dir"|list_files()
    - a string with a newline seperated list of files in searchpath/sub_dir
    - each of these listed files are available for "import x as y" in jinja
- "sub_dir"|list_dirs()
    - a string with a newline seperated list of directories in searchpath/sub_dir

#### regex related custom filter

- "text"|regex_escape()
- "text"|regex_search(pattern)
- "text"|regex_match(pattern)
- "text"|regex_replace(pattern, replacement)

search,match,replace support additional args
- ignorecase=True/*False
- multiline=True/*False

#### Example

import files available under subdir "test" and translate into a saltstack state file

```jinja

{% for f in 'test'|list_files().split('\\n') %}{% import f as c %}
{{ f }}:
    file.managed:
    - contents: |
        {{ c|string()|indent(8) }}
{% endfor %}
```


