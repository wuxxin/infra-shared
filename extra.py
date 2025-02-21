import time
import random
import pulumi
from pulumi.dynamic import (
    Resource,
    ResourceProvider,
    CreateResult,
    DiffResult,
    UpdateResult,
    CheckResult,
    CheckFailure,
    ReadResult,
)
from typing import Optional, Any, Dict, List


@pulumi.input_type
class TimedResourceArgs:
    def __init__(
        self,
        *,
        timeout_sec: pulumi.Input[int],
        creation_type: pulumi.Input[str],
        base: Optional[pulumi.Input[int]] = None,
        range: Optional[pulumi.Input[int]] = None,
    ):
        pulumi.set(self, "timeout_sec", timeout_sec)
        pulumi.set(self, "creation_type", creation_type)
        if base is not None:
            pulumi.set(self, "base", base)
        if range is not None:
            pulumi.set(self, "range", range)

    @property
    @pulumi.getter
    def timeout_sec(self) -> pulumi.Input[int]:
        return pulumi.get(self, "timeout_sec")

    @property
    @pulumi.getter
    def creation_type(self) -> pulumi.Input[str]:
        return pulumi.get(self, "creation_type")

    @property
    @pulumi.getter
    def base(self) -> Optional[pulumi.Input[int]]:
        return pulumi.get(self, "base")

    @property
    @pulumi.getter
    def range(self) -> Optional[pulumi.Input[int]]:
        return pulumi.get(self, "range")


@pulumi.output_type
class TimedResourceResult:
    def __init__(self, value: Any, creation_timestamp: int):
        pulumi.set(self, "value", value)
        pulumi.set(self, "creation_timestamp", creation_timestamp)

    @property
    @pulumi.getter
    def value(self) -> Any:
        return pulumi.get(self, "value")

    @property
    @pulumi.getter
    def creation_timestamp(self) -> int:
        return pulumi.get(self, "creation_timestamp")


class TimedResourceProvider(ResourceProvider):
    def check(self, _olds, news):
        failures = []
        if news["creation_type"] not in ["random_int", "unixtime"]:
            failures.append(
                CheckFailure("creation_type", "Must be 'random_int' or 'unixtime'")
            )
        if news["creation_type"] == "random_int":
            if "base" not in news or news["base"] is None:
                failures.append(
                    CheckFailure("base", "Must be provided for 'random_int'")
                )
            if "range" not in news or news["range"] is None:
                failures.append(
                    CheckFailure("range", "Must be provided for 'random_int'")
                )
        if (
            "timeout_sec" not in news
            or news["timeout_sec"] is None
            or news["timeout_sec"] <= 0
        ):
            failures.append(CheckFailure("timeout_sec", "Must be a positive integer"))

        return CheckResult(news, failures)

    def create(self, props):
        value, timestamp = self._generate_value(props)
        return CreateResult(
            f"timed-{props['creation_type']}-{timestamp}",  # Unique ID
            outs={"value": value, "creation_timestamp": timestamp},
        )

    def diff(self, _id, olds, news):
        replaces = []
        if olds["creation_type"] != news["creation_type"]:
            replaces.append("creation_type")
        if news["creation_type"] == "random_int":
            if olds.get("base") != news.get("base"):
                replaces.append("base")
            if olds.get("range") != news.get("range"):
                replaces.append("range")

        if replaces:
            return DiffResult(changes=True, replaces=replaces)

        time_elapsed = time.time() - olds["creation_timestamp"]
        changes = time_elapsed > news["timeout_sec"]
        return DiffResult(changes=changes)

    def update(self, _id, _olds, news):
        value, timestamp = self._generate_value(news)
        return UpdateResult(outs={"value": value, "creation_timestamp": timestamp})

    def read(self, id: str, props: Dict[str, Any]) -> ReadResult:
        return ReadResult(id_=id, outs=props)

    def _generate_value(self, props):
        timestamp = int(time.time())
        if props["creation_type"] == "random_int":
            value = props["base"] + random.randrange(props["range"])
        else:  # "unixtime"
            value = timestamp
        return value, timestamp


class TimedResource(Resource):
    output: pulumi.Output[TimedResourceResult]

    def __init__(
        self,
        name: str,
        timeout_sec: int,
        creation_type: str,
        base: Optional[int] = None,
        range: Optional[int] = None,
        opts: Optional[pulumi.ResourceOptions] = None,
        **kwargs,
    ):
        args = TimedResourceArgs(
            timeout_sec=timeout_sec, creation_type=creation_type, base=base, range=range
        )
        super().__init__(TimedResourceProvider(), name, vars(args), opts)
