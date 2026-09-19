"""Stage-scoped dependency identities for immutable v23 artifacts."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml


STAGE_CONTRACT_FIELDS = {
    "kind",
    "execution_revision",
    "base_specification_version",
    "stage_order",
    "stage_graph",
    "change_impacts",
    "fingerprints",
    "carry_forward_stages",
}
FINGERPRINT_FIELDS = {
    "python_dependencies",
    "config_dependencies",
    "file_dependencies",
    "runtime_manifest_fields",
}
FILE_DEPENDENCY_ROLES = {"data", "model", "upstream_artifact"}


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _require_sorted_strings(value: Any, *, field: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not all(isinstance(item, str) and item for item in value)
        or value != sorted(value)
        or len(value) != len(set(value))
    ):
        raise RuntimeError(f"stage_contract_list_invalid:{field}")
    return list(value)


def _require_unique_strings(value: Any, *, field: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not all(isinstance(item, str) and item for item in value)
        or len(value) != len(set(value))
    ):
        raise RuntimeError(f"stage_contract_list_invalid:{field}")
    return list(value)


def _validate_relative_path(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RuntimeError(f"stage_contract_path_invalid:{field}")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"stage_contract_path_invalid:{field}")
    return value


def validate_stage_dependency_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    contract = copy.deepcopy(dict(value))
    if set(contract) != STAGE_CONTRACT_FIELDS:
        raise RuntimeError("stage_contract_schema_drift")
    if (
        contract["kind"] != "pcv_v23_stage_dependency_contract"
        or contract["execution_revision"]
        != "pcv-restoration-first-v23-design-r6-execution-e1"
        or contract["base_specification_version"]
        != "pcv-restoration-first-v23-design-r6"
    ):
        raise RuntimeError("stage_contract_identity_drift")

    order = _require_unique_strings(contract["stage_order"], field="stage_order")
    graph = contract["stage_graph"]
    if not isinstance(graph, Mapping) or set(graph) != set(order):
        raise RuntimeError("stage_contract_graph_stage_drift")
    for stage in order:
        node = graph[stage]
        if not isinstance(node, Mapping) or set(node) != {"upstream"}:
            raise RuntimeError(f"stage_contract_graph_schema_drift:{stage}")
        upstream = _require_sorted_strings(
            node["upstream"], field=f"stage_graph.{stage}.upstream"
        )
        if stage in upstream or not set(upstream).issubset(graph):
            raise RuntimeError(f"stage_contract_graph_edge_invalid:{stage}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(stage: str) -> None:
        if stage in visiting:
            raise RuntimeError("stage_contract_graph_cycle")
        if stage in visited:
            return
        visiting.add(stage)
        for parent in graph[stage]["upstream"]:
            visit(parent)
        visiting.remove(stage)
        visited.add(stage)

    for stage in order:
        visit(stage)

    impacts = contract["change_impacts"]
    if not isinstance(impacts, Mapping) or not impacts:
        raise RuntimeError("stage_contract_change_impacts_invalid")
    for name, roots in impacts.items():
        if not isinstance(name, str) or not name:
            raise RuntimeError("stage_contract_change_class_invalid")
        normalized = _require_sorted_strings(
            roots, field=f"change_impacts.{name}"
        )
        if not set(normalized).issubset(graph):
            raise RuntimeError(f"stage_contract_change_root_unknown:{name}")

    fingerprints = contract["fingerprints"]
    if not isinstance(fingerprints, Mapping) or not set(fingerprints).issubset(graph):
        raise RuntimeError("stage_contract_fingerprints_invalid")
    for stage, specification in fingerprints.items():
        if not isinstance(specification, Mapping) or set(specification) != FINGERPRINT_FIELDS:
            raise RuntimeError(f"stage_contract_fingerprint_schema_drift:{stage}")
        python_dependencies = specification["python_dependencies"]
        if not isinstance(python_dependencies, list):
            raise RuntimeError(f"stage_contract_python_dependencies_invalid:{stage}")
        python_paths: list[str] = []
        for index, dependency in enumerate(python_dependencies):
            if not isinstance(dependency, Mapping) or set(dependency) != {"path", "symbols"}:
                raise RuntimeError(f"stage_contract_python_dependency_schema:{stage}:{index}")
            python_paths.append(
                _validate_relative_path(
                    dependency["path"], field=f"fingerprints.{stage}.python.path"
                )
            )
            _require_sorted_strings(
                dependency["symbols"],
                field=f"fingerprints.{stage}.python.symbols",
            )
        if python_paths != sorted(python_paths) or len(python_paths) != len(set(python_paths)):
            raise RuntimeError(f"stage_contract_python_paths_not_canonical:{stage}")

        config_dependencies = specification["config_dependencies"]
        if not isinstance(config_dependencies, list):
            raise RuntimeError(f"stage_contract_config_dependencies_invalid:{stage}")
        config_paths: list[str] = []
        for index, dependency in enumerate(config_dependencies):
            if not isinstance(dependency, Mapping) or set(dependency) != {"path", "selectors"}:
                raise RuntimeError(f"stage_contract_config_dependency_schema:{stage}:{index}")
            config_paths.append(
                _validate_relative_path(
                    dependency["path"], field=f"fingerprints.{stage}.config.path"
                )
            )
            _require_sorted_strings(
                dependency["selectors"],
                field=f"fingerprints.{stage}.config.selectors",
            )
        if config_paths != sorted(config_paths) or len(config_paths) != len(set(config_paths)):
            raise RuntimeError(f"stage_contract_config_paths_not_canonical:{stage}")

        file_dependencies = specification["file_dependencies"]
        if not isinstance(file_dependencies, list):
            raise RuntimeError(f"stage_contract_file_dependencies_invalid:{stage}")
        file_paths: list[str] = []
        for index, dependency in enumerate(file_dependencies):
            if not isinstance(dependency, Mapping) or set(dependency) != {"path", "role"}:
                raise RuntimeError(f"stage_contract_file_dependency_schema:{stage}:{index}")
            file_paths.append(
                _validate_relative_path(
                    dependency["path"], field=f"fingerprints.{stage}.file.path"
                )
            )
            if dependency["role"] not in FILE_DEPENDENCY_ROLES:
                raise RuntimeError(f"stage_contract_file_dependency_role:{stage}:{index}")
        if file_paths != sorted(file_paths) or len(file_paths) != len(set(file_paths)):
            raise RuntimeError(f"stage_contract_file_paths_not_canonical:{stage}")
        _require_sorted_strings(
            specification["runtime_manifest_fields"],
            field=f"fingerprints.{stage}.runtime_manifest_fields",
        )

    carry_forward = _require_sorted_strings(
        contract["carry_forward_stages"], field="carry_forward_stages"
    )
    if not set(carry_forward).issubset(fingerprints):
        raise RuntimeError("stage_contract_carry_forward_stage_invalid")
    return contract


def load_stage_dependency_contract(path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise RuntimeError("stage_contract_root_invalid")
    return validate_stage_dependency_contract(payload)


def affected_stages(
    contract: Mapping[str, Any], change_class: str
) -> list[str]:
    validated = validate_stage_dependency_contract(contract)
    impacts = validated["change_impacts"]
    if change_class not in impacts:
        raise RuntimeError(f"stage_contract_change_class_unknown:{change_class}")
    graph = validated["stage_graph"]
    reverse: dict[str, set[str]] = {stage: set() for stage in graph}
    for stage, node in graph.items():
        for parent in node["upstream"]:
            reverse[parent].add(stage)
    affected = set(impacts[change_class])
    frontier = list(affected)
    while frontier:
        parent = frontier.pop()
        for child in reverse[parent]:
            if child not in affected:
                affected.add(child)
                frontier.append(child)
    return [stage for stage in validated["stage_order"] if stage in affected]


class _DocstringStripper(ast.NodeTransformer):
    @staticmethod
    def _without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            return body[1:]
        return body

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        node = copy.deepcopy(node)
        node.body = self._without_docstring(node.body)
        return self.generic_visit(node)

    def visit_Module(self, node: ast.Module) -> ast.AST:
        node = copy.deepcopy(node)
        node.body = self._without_docstring(node.body)
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        node = copy.deepcopy(node)
        node.body = self._without_docstring(node.body)
        return self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        node = copy.deepcopy(node)
        node.body = self._without_docstring(node.body)
        return self.generic_visit(node)


def _top_level_nodes(module: ast.Module) -> dict[str, ast.AST]:
    output: dict[str, ast.AST] = {}
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            output[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    output[target.id] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            output[node.target.id] = node
    return output


def _resolve_symbol(module: ast.Module, symbol: str) -> ast.AST:
    parts = symbol.split(".")
    if not parts or any(not part for part in parts):
        raise RuntimeError(f"stage_dependency_symbol_invalid:{symbol}")
    top = _top_level_nodes(module).get(parts[0])
    if top is None:
        raise RuntimeError(f"stage_dependency_symbol_missing:{symbol}")
    node = top
    for part in parts[1:]:
        if not isinstance(node, ast.ClassDef):
            raise RuntimeError(f"stage_dependency_symbol_not_class:{symbol}")
        matches = [
            item
            for item in node.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and item.name == part
        ]
        if len(matches) != 1:
            raise RuntimeError(f"stage_dependency_symbol_missing:{symbol}")
        node = matches[0]
    return node


def python_symbol_dependency(
    source: str, *, path: str, symbols: Sequence[str]
) -> dict[str, Any]:
    try:
        module = ast.parse(source, filename=path)
    except SyntaxError as exc:
        raise RuntimeError(f"stage_dependency_python_parse_failed:{path}") from exc
    stripper = _DocstringStripper()
    rows: list[dict[str, str]] = []
    selected = list(symbols) if symbols else ["__whole_file__"]
    for symbol in selected:
        node = (
            stripper.visit(copy.deepcopy(module))
            if symbol == "__whole_file__"
            else stripper.visit(copy.deepcopy(_resolve_symbol(module, symbol)))
        )
        rows.append(
            {
                "symbol": symbol,
                "ast_sha256": canonical_sha256(
                    ast.dump(node, annotate_fields=True, include_attributes=False)
                ),
            }
        )
    return {
        "path": path,
        "symbols": rows,
        "dependency_sha256": canonical_sha256(rows),
    }


def _select_config(value: Any, selector: str) -> Any:
    current = value
    for part in selector.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise RuntimeError(f"stage_dependency_config_selector_missing:{selector}")
        current = current[part]
    return current


def compute_stage_dependency_fingerprint(
    contract: Mapping[str, Any],
    stage: str,
    *,
    python_source_loader: Callable[[str], str],
    config_source_loader: Callable[[str], str],
    file_bytes_loader: Callable[[str], bytes] | None = None,
    runtime_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_stage_dependency_contract(contract)
    specifications = validated["fingerprints"]
    if stage not in specifications:
        raise RuntimeError(f"stage_fingerprint_not_defined:{stage}")
    specification = specifications[stage]
    python_rows = [
        python_symbol_dependency(
            python_source_loader(dependency["path"]),
            path=dependency["path"],
            symbols=dependency["symbols"],
        )
        for dependency in specification["python_dependencies"]
    ]
    config_rows: list[dict[str, Any]] = []
    for dependency in specification["config_dependencies"]:
        parsed = yaml.safe_load(config_source_loader(dependency["path"]))
        if not isinstance(parsed, Mapping):
            raise RuntimeError(
                f"stage_dependency_config_root_invalid:{dependency['path']}"
            )
        selected = {
            selector: _select_config(parsed, selector)
            for selector in dependency["selectors"]
        }
        config_rows.append(
            {
                "path": dependency["path"],
                "selectors": selected,
                "dependency_sha256": canonical_sha256(selected),
            }
        )
    file_rows: list[dict[str, str]] = []
    for dependency in specification["file_dependencies"]:
        if file_bytes_loader is None:
            raise RuntimeError("stage_dependency_file_loader_missing")
        raw = file_bytes_loader(dependency["path"])
        if not isinstance(raw, bytes):
            raise RuntimeError(
                f"stage_dependency_file_bytes_invalid:{dependency['path']}"
            )
        file_rows.append(
            {
                "path": dependency["path"],
                "role": dependency["role"],
                "file_sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    runtime_fields: dict[str, Any] = {}
    for field in specification["runtime_manifest_fields"]:
        if field not in runtime_manifest:
            raise RuntimeError(f"stage_dependency_runtime_field_missing:{field}")
        runtime_fields[field] = runtime_manifest[field]
    payload = {
        "kind": "pcv_v23_stage_dependency_fingerprint",
        "base_specification_version": validated["base_specification_version"],
        "stage": stage,
        "python_dependencies": python_rows,
        "config_dependencies": config_rows,
        "file_dependencies": file_rows,
        "runtime_manifest_fields": runtime_fields,
    }
    return {
        **payload,
        "stage_dependency_fingerprint": canonical_sha256(payload),
    }


def stage_execution_identity(
    *,
    stage: str,
    stage_dependency_fingerprint: str,
    runtime_bundle_sha256: str,
    protocol_revision_id: str,
) -> str:
    return canonical_sha256(
        {
            "kind": "pcv_v23_stage_execution_identity",
            "stage": stage,
            "stage_dependency_fingerprint": stage_dependency_fingerprint,
            "runtime_bundle_sha256": runtime_bundle_sha256,
            "protocol_revision_id": protocol_revision_id,
        }
    )
