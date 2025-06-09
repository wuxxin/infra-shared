#!/usr/bin/env python
"""
## resource_call.py

- `. .venv/bin/activate && $0 [--stack sim] library function *stringargs`

"""

import argparse
import importlib
import inspect
import os
import sys

this_dir = os.path.dirname(os.path.abspath(__file__))
shared_dir = os.path.abspath(os.path.join(this_dir, ".."))
project_dir = os.path.abspath(os.path.join(this_dir, "../.."))
project_name = os.path.basename(project_dir)


def main():
    # add base of project to begin of python import path list
    sys.path.insert(0, project_dir)

    parser = argparse.ArgumentParser(
        description="""
Equivalent to calling `pulumi up` on the selected library.function on the selected stack.
useful for oneshots like image building or transfer. calling example:
`. .venv/bin/activate && {shared_dir_short}/scripts/resource_call.py --stack sim {shared_dir_short}.build build_openwrt`""".format(
            shared_dir_short=os.path.basename(shared_dir)
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--stack", type=str, help="Name of the stack", default="sim")
    parser.add_argument("--preview", action="store_true", help="preview only", default=False)
    parser.add_argument("library", type=str, help="Name of the library")
    parser.add_argument(
        "function",
        type=str,
        nargs="?",
        help="function name, will list all functions of library if empty",
    )
    parser.add_argument(
        "args",
        type=str,
        nargs="*",
        help="optional string args for function",
        default=[],
    )

    args = parser.parse_args()
    library = importlib.import_module(args.library)

    if not args.function:
        print("Available functions in library {}:".format(args.library))
        for name in dir(library):
            if callable(getattr(library, name)) and not name.startswith("__"):
                func = getattr(library, name)
                sig = inspect.signature(func)
                doc = "" if func.__doc__ is None else func.__doc__
                params = sig.parameters
                param_list = ", ".join(params.keys())
                print("{}({})  {}".format(name, param_list, doc))
        sys.exit()

    os.environ["PULUMI_SKIP_UPDATE_CHECK"] = "1"
    target_function = getattr(library, args.function)

    def target_prog(stack):
        target_function(stack, *args.args)

    from pulumi.automation import LocalWorkspaceOptions, select_stack

    # workspace_opts = LocalWorkspaceOptions(work_dir=project_dir)
    #     project_name="{}-{}-{}".format(project_name, library, args.function),
    #     program=target_prog,
    #     opts=workspace_opts,

    stack = select_stack(
        stack_name=args.stack,
        work_dir=project_dir,
    )
    target_prog(stack)

    # if args.preview:
    #     stack.preview(log_to_std_err=True, on_output=print)
    # else:
    #     stack.up(log_to_std_err=True, on_output=print)


if __name__ == "__main__":
    main()
