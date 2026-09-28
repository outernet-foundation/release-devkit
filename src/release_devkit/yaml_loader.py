# noqa-wrapper: wraps PyYAML loading with strict semantics (duplicate-key rejection, string-preserving scalars); PyYAML stubs are incompletely typed
from typing import Any

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode, ScalarNode


class _StrictLoader(yaml.SafeLoader):
    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[object] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)  # pyright: ignore[reportUnknownMemberType]
            if key in seen:
                raise ConstructorError(None, None, f"duplicate key: {key!r}", key_node.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep)  # pyright: ignore[reportUnknownMemberType]


def _construct_str(loader: yaml.SafeLoader, node: ScalarNode) -> str:
    return loader.construct_scalar(node)


for scalar_tag in (
    "tag:yaml.org,2002:int",
    "tag:yaml.org,2002:float",
    "tag:yaml.org,2002:bool",
    "tag:yaml.org,2002:timestamp",
    "tag:yaml.org,2002:binary",
):
    _StrictLoader.add_constructor(scalar_tag, _construct_str)


def load_yaml(text: str) -> object:
    return _StrictLoader(text).get_single_data()
