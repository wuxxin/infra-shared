#!/usr/bin/env python
"""request a port forwarding so that serve-port is reachable on public-port
  either '--from-stdin' with 'serve_port: <port>' from STDIN
  or     '--serve-port <port>' must be set

  can be used in combination with serve_once.py, eg.:
    result="$(printf 'serve_port: 48443\\nrequest_method: POST\\npayload: true\\n
      \\nrequest_body_stdout: true\\n' | port_forward.py --from-stdin | serve_once.py --yes)"

request public ip from gateway, print to STDOUT and exit
  '--get-public-ip' must be set

"""


import argparse
import copy
import socket
import sys
import textwrap

import yaml


def error_print(message, print_help=False):
    print("Error:  {}".format(message), file=sys.stderr)
    if print_help:
        print("        use -h, --help for a complete list of arguments")
    sys.exit(1)


def merge_dict_struct(self, dict1, dict2):
    "merge and return two dict like structs, dict2 takes precedence over dict1"

    def is_dict_like(v):
        return hasattr(v, "keys") and hasattr(v, "values") and hasattr(v, "items")

    def is_list_like(v):
        return hasattr(v, "append") and hasattr(v, "extend") and hasattr(v, "pop")

    dmerge = copy.deepcopy(dict1)
    if is_dict_like(dict1) and is_dict_like(dict2):
        for key in dict2:
            if key in dict1:
                # if the key is present in both dictionaries, recursively merge the values
                dmerge[key] = merge_dict_struct(dict1[key], dict2[key])
            else:
                dmerge[key] = dict2[key]
    elif is_list_like(dict1) and is_list_like(dict2):
        for item in dict2:
            if item not in dict1:
                dmerge.append(item)
    else:
        # if neither input is a dictionary or list, the second input overwrites the first input
        dmerge = dict2
    return dmerge


def get_gateway_ip():
    try:
        gateway_addr = socket.gethostbyname(socket.gethostname())
        if (
            not socket.inet_pton(socket.AF_INET, gateway_addr)
            or gateway_addr.startswith("127.")
            or gateway_addr.startswith("::1")
        ):
            gateway_addr = None
    except socket.gaierror:
        gateway_addr = None
    return gateway_addr


def get_public_ip(gateway_ip, protocol):
    if protocol == "natpmp":
        return "1.2.3.4"


def port_forward(serve_port, public_port, gateway_ip, protocol):
    if protocol == "natpmp":
        return "1.2.3.4", public_port


default_config_str = """
serve_port:
port_forward:
  protocol: "natpmp"
  gateway_ip:
  public_ip:
  public_port:
  lifetime: 3600
  retry: 9
"""

default_config = yaml.safe_load(default_config_str)
default_short = textwrap.fill(
    ", ".join(["{}: {}".format(k, v) for k, v in default_config.items()]),
    width=80,
    initial_indent="  ",
    subsequent_indent="  ",
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__ + "\ndefaults:\n{}\n".format(default_short),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    public_private_group = parser.add_argument_group("Serving/Public Port Options")
    public_private_group.add_argument(
        "--serve-port", type=int, help="internal port to connect to"
    )
    public_private_group.add_argument(
        "--public-port", type=int, help="public port, will be set to serve port if unset"
    )
    stdin_group = parser.add_argument_group("STDIN, STDOUT Options")
    stdin_group.add_argument("--from-stdin", action="store_true", help="Read input from STDIN")
    get_public_ip_group = parser.add_argument_group("return public IP Options")
    get_public_ip_group.add_argument(
        "--get-public-ip", action="store_true", help="get public ip from gateway"
    )
    parser.add_argument(
        "--gateway-ip", type=str, help="gateway IP, will be inferred from network if unset"
    )
    parser.add_argument(
        "--protocol",
        type=str,
        default="natpmp",
        choices=["natpmp"],
        help="port forwarding protocol",
    )
    parser.add_argument("--lifetime", type=int, help="lifetime in seconds")
    parser.add_argument("--retry", type=int, help="number of retries")
    args = parser.parse_args()
    loaded_config = {"port_forward": {}}

    if not args.from_stdin and not args.serve_port and not args.get_public_ip:
        error_print(
            "Missing args, '--from-stdin', '--serve-port' or '--get-public-ip' must be set",
            print_help=True,
        )

    if args.get_public.ip:
        public_ip = get_public_ip()
        print(public_ip)
        sys.exit(0)

    if args.from_stdin:
        stdin_str = sys.stdin.read()
        if not stdin_str.strip():
            error_print("Error: Arg --from-stdin supplied, but no data from STDIN")
        loaded_config = yaml.safe_load(stdin_str)
        if "serve_port" not in loaded_config:
            error_print("serve_port: <port> must be part of STDIN if --from-stdin")
        if "port_forward" not in loaded_config:
            loaded_config["port_forward"] = {}

    if args.serve_port:
        loaded_config["serve_port"] = args.serve_port

    for i in ["public_port", "gateway_ip", "lifetime", "retry"]:
        if args[i]:
            loaded_config["port_forward"][i] = args["i"]

    # merge YAML config with defaults
    config = merge_dict_struct(default_config, loaded_config)

    # if still missing, fill in public_port and gateway_ip
    if not config["port_forward"]["public_port"]:
        config["port_forward"]["public_port"] = config["serve_port"]
    if not config["port_forward"]["gateway_ip"]:
        config["port_forward"]["gateway_ip"] = get_gateway_ip()

    public_ip, public_port = port_forward(
        serve_port=config["serve_port"],
        public_port=config["port_forward"]["public_port"],
        gateway_ip=config["port_forward"]["gateway_ip"],
        protocol=config["port_forward"]["protocol"],
    )
    config["port_forward"]["public_ip"] = public_ip
    config["port_forward"]["public_port"] = public_port

    # print update config (with a copy read from STDIN) to STDOUT
    print(yaml.safe_dump(config))
