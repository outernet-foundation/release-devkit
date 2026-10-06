# noqa-wrapper: MSBuild csproj reading over stdlib xml.etree — inputs are first-party
# authored project files inside the consuming repo, not untrusted XML, so the
# entity-expansion hardening S314 demands (defusedxml) would add a runtime
# dependency without changing the trust model.
import re
from dataclasses import dataclass
from pathlib import Path
from xml.etree.ElementTree import Element, parse  # ruff: ignore[suspicious-xml-etree-import]

NUGET_PROPERTY_PATTERN = re.compile(r"^\$\(([\w.]+)\)$")


@dataclass(frozen=True)
class PackageReference:
    identity: str
    version: str
    property_name: str | None


def load_project_roots(package_path: Path) -> list[Element]:
    project_paths = [
        project_path
        for project_path in package_path.rglob("*.csproj")
        if "bin" not in project_path.parts and "obj" not in project_path.parts
    ]
    if not project_paths:
        raise ValueError(f"no csproj under '{package_path}' but the nuget registry is declared")
    return [
        parse(project_path).getroot()  # ruff: ignore[suspicious-xml-element-tree-usage]
        for project_path in sorted(project_paths)
    ]


def read_package_references(root: Element) -> list[PackageReference]:
    defaults: dict[str, str] = {}
    for group in root.iter():
        if local_name(group) != "PropertyGroup":
            continue
        for child in group:
            defaults[local_name(child)] = (child.text or "").strip()

    references: list[PackageReference] = []
    for element in root.iter():
        if local_name(element) != "PackageReference":
            continue
        identity = element.get("Include")
        version = element.get("Version")
        if identity is None or version is None:
            continue
        property_match = NUGET_PROPERTY_PATTERN.match(version)
        if property_match is None:
            references.append(PackageReference(identity=identity, version=version, property_name=None))
            continue
        property_name = property_match.group(1)
        default = defaults.get(property_name)
        if default is None:
            raise ValueError(
                f"csproj property '{property_name}' carries no default; "
                "the sentinel default is what validates the sibling edge"
            )
        references.append(PackageReference(identity=identity, version=default, property_name=property_name))
    return references


def local_name(element: Element) -> str:
    return element.tag.rsplit("}", 1)[-1]
