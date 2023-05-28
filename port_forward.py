#!/usr/bin/env python
"""request a port forwarding so that serve-port is reachable on public-port

  either '--from-stdin' with yaml 'serve_port: <port>' from STDIN
  or     '--serve-port <port>' must be set

  outputs resulting configuration yaml to STDOUT, merged from STDIN yaml if '--from-stdin'

  can be used in combination with serve_once.py, eg.:
    result="$(printf 'serve_port: 48443\\nrequest_method: POST\\npayload: true\\n
      \\nrequest_body_stdout: true\\n' | port_forward.py --from-stdin | serve_once.py --yes)"
"""


import argparse
import copy
import os
import socket
import sys
import textwrap

import natpmp
import yaml


def error_print(message, print_help=False):
    print("Error:  {}".format(message), file=sys.stderr)
    if print_help:
        print("        use -h, --help for a complete list of arguments")
    sys.exit(1)


def merge_dict_struct(dict1, dict2):
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


def get_default_gateway_ip():
    if os.path.exists("/proc/net/route"):
        r_data = open("/proc/net/route", "r").read()
        for r_line in r_data.splitlines():
            r_fields = r_line.strip().split("\t")
            if len(r_fields) >= 3 and r_fields[1] == "00000000":
                ip_hex = r_fields[2]
                if sys.byteorder == "little":
                    ip_bytes = bytes.fromhex(ip_hex)[::-1]
                else:
                    ip_bytes = bytes.fromhex(ip_hex)
                ip_address = socket.inet_ntoa(ip_bytes)
                return ip_address
    return None


def get_default_host_ip():
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
        request = natpmp.PublicAddressRequest()
        response = natpmp.send_request_with_retry(
            gateway_ip=gateway_ip,
            request=request,
            response_data_class=natpmp.PublicAddressResponse,
            retry=config["port_forward"]["retry"],
            response_size=12,
        )
        if response.result == 0:
            return response.ip
        else:
            print(natpmp.error_str(response.result), file=sys.stderr)
            return None


def port_forward(serve_port, public_port, gateway_ip, protocol):
    if protocol == "natpmp":
        request = natpmp.PortMapRequest(
            protocol=natpmp.NATPMP_PROTOCOL_TCP,
            private_port=serve_port,
            public_port=public_port,
            lifetime=config["port_forward"]["lifetime"],
        )
        response = natpmp.send_request_with_retry(
            gateway_ip=gateway_ip,
            request=request,
            response_data_class=natpmp.PortMapResponse,
            retry=config["port_forward"]["retry"],
        )
        if response.result == 0:
            return response.public_port
        else:
            print(natpmp.error_str(response.result), file=sys.stderr)
            return None


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
    parser.add_argument("--from-stdin", action="store_true", help="Read input from STDIN")
    parser.add_argument("--serve-port", type=int, help="internal port to be forwarded to")
    parser.add_argument(
        "--public-port",
        type=int,
        help="public port of packets incoming, will be set to serve-port if unset",
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
    parser.add_argument(
        "--silent", action="store_true", help="don't print configuration YAML to STDOUT"
    )
    get_group = parser.add_argument_group("other Functions").add_mutually_exclusive_group()
    get_group.add_argument(
        "--get-host-ip", action="store_true", help="print default route host IP"
    )
    get_group.add_argument(
        "--get-gateway-ip", action="store_true", help="print default gateway IP"
    )
    get_group.add_argument(
        "--get-public-ip",
        action="store_true",
        help="request the public IP from gateway and print",
    )
    args = parser.parse_args()
    loaded_config = {"port_forward": {}}

    if not any(
        [
            args.from_stdin,
            args.serve_port,
            args.get_public_ip,
            args.get_gateway_ip,
            args.get_host_ip,
        ]
    ):
        error_print(
            "Need one of '--from-stdin', '--serve-port', '--get-public-ip', '--get-gateway-ip', '--get-host-ip'",
            print_help=True,
        )

    if args.get_host_ip:
        host_ip = get_default_host_ip()
        print(host_ip)
        sys.exit(0) if host_ip else sys.exit(1)

    if args.get_gateway_ip:
        gateway_ip = get_default_gateway_ip()
        print(gateway_ip)
        sys.exit(0) if gateway_ip else sys.exit(1)

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
        if hasattr(args, i):
            loaded_config["port_forward"][i] = getattr(args, i)

    # merge YAML config with defaults
    config = merge_dict_struct(default_config, loaded_config)

    # if still missing, fill in public_port and gateway_ip
    if not config["port_forward"]["public_port"]:
        config["port_forward"]["public_port"] = config["serve_port"]
    if not config["port_forward"]["gateway_ip"]:
        config["port_forward"]["gateway_ip"] = get_default_gateway_ip()

    public_ip = get_public_ip(
        config["port_forward"]["gateway_ip"], config["port_forward"]["protocol"]
    )
    if not public_ip:
        sys.exit(1)

    if args.get_public_ip:
        print(public_ip)
        sys.exit(0)

    public_port = port_forward(
        serve_port=config["serve_port"],
        public_port=config["port_forward"]["public_port"],
        gateway_ip=config["port_forward"]["gateway_ip"],
        protocol=config["port_forward"]["protocol"],
    )
    if not public_port:
        sys.exit(1)

    config["port_forward"]["public_ip"] = public_ip
    config["port_forward"]["public_port"] = public_port

    # print updated config to STDOUT if not --silent
    if not args.silent:
        print(yaml.safe_dump(config))
