from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from master_control.config_manager import ConfigTarget, build_default_config_targets

SUPPORTED_POLICY_VERSION = 1
SUPPORTED_VALIDATORS = frozenset({"ini_parse", "json_parse", "command"})
SUPPORTED_SCOPES = frozenset({"system", "user"})


@dataclass(frozen=True, slots=True)
class ToolPolicyRule:
    enabled: bool | None = None
    require_confirmation: bool = False
    allowed_scopes: tuple[str, ...] = ()
    service_patterns: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "require_confirmation": self.require_confirmation,
        }
        if self.enabled is not None:
            payload["enabled"] = self.enabled
        if self.allowed_scopes:
            payload["allowed_scopes"] = list(self.allowed_scopes)
        if self.service_patterns:
            payload["service_patterns"] = list(self.service_patterns)
        return payload


@dataclass(frozen=True, slots=True)
class LoadedPolicy:
    path: Path
    exists: bool
    version: int
    using_default: bool
    error: str | None
    tool_rules: dict[str, ToolPolicyRule]
    config_targets: tuple[ConfigTarget, ...]

    def diagnostics(self) -> dict[str, object]:
        summary = "loaded operator policy"
        if self.error is not None:
            summary = f"policy error: {self.error}"
        elif self.using_default:
            summary = "using default safe policy"
        return {
            "ok": self.error is None,
            "path": str(self.path),
            "exists": self.exists,
            "version": self.version,
            "using_default": self.using_default,
            "summary": summary,
            "error": self.error,
            "tool_rule_count": len(self.tool_rules),
            "tools_with_rules": sorted(self.tool_rules),
            "config_target_count": len(self.config_targets),
            "config_targets": [target.name for target in self.config_targets],
        }


class PolicyLoader:
    def __init__(self, path: Path, state_dir: Path) -> None:
        self.path = path
        self.state_dir = state_dir.resolve(strict=False)
        self._cached_key: tuple[bool, int | None] | None = None
        self._cached_policy: LoadedPolicy | None = None

    def load(self) -> LoadedPolicy:
        exists = self.path.exists()
        stamp = self.path.stat().st_mtime_ns if exists else None
        cache_key = (exists, stamp)
        if self._cached_key == cache_key and self._cached_policy is not None:
            return self._cached_policy

        if not exists:
            policy = LoadedPolicy(
                path=self.path,
                exists=False,
                version=SUPPORTED_POLICY_VERSION,
                using_default=True,
                error=None,
                tool_rules={},
                config_targets=build_default_config_targets(self.state_dir),
            )
        else:
            try:
                raw_payload = tomllib.loads(self.path.read_text(encoding="utf-8"))
                policy = self._parse_loaded_policy(raw_payload)
            except Exception as exc:
                policy = LoadedPolicy(
                    path=self.path,
                    exists=True,
                    version=SUPPORTED_POLICY_VERSION,
                    using_default=False,
                    error=str(exc),
                    tool_rules={},
                    config_targets=(),
                )

        self._cached_key = cache_key
        self._cached_policy = policy
        return policy

    def diagnostics(self) -> dict[str, object]:
        return self.load().diagnostics()

    def config_targets(self) -> tuple[ConfigTarget, ...]:
        return self.load().config_targets

    def _parse_loaded_policy(self, raw_payload: object) -> LoadedPolicy:
        if not isinstance(raw_payload, dict):
            raise ValueError("Policy document must be a TOML table at the root.")

        version = raw_payload.get("version", SUPPORTED_POLICY_VERSION)
        if not isinstance(version, int) or isinstance(version, bool):
            raise ValueError("Policy field 'version' must be an integer.")
        if version != SUPPORTED_POLICY_VERSION:
            raise ValueError(f"Unsupported policy version: {version}")

        tool_rules = self._parse_tool_rules(raw_payload.get("tools"))
        config_targets = self._parse_config_targets(raw_payload.get("config_targets"))
        return LoadedPolicy(
            path=self.path,
            exists=True,
            version=version,
            using_default=False,
            error=None,
            tool_rules=tool_rules,
            config_targets=config_targets,
        )

    def _parse_tool_rules(self, raw_tools: object) -> dict[str, ToolPolicyRule]:
        if raw_tools is None:
            return {}
        if not isinstance(raw_tools, dict):
            raise ValueError("Policy field 'tools' must be a TOML table.")

        tool_rules: dict[str, ToolPolicyRule] = {}
        for tool_name, raw_rule in raw_tools.items():
            if not isinstance(tool_name, str) or not tool_name:
                raise ValueError("Policy tool rule names must be non-empty strings.")
            if not isinstance(raw_rule, dict):
                raise ValueError(f"Policy rule for '{tool_name}' must be a TOML table.")
            enabled = self._optional_bool(raw_rule, "enabled")
            require_confirmation = self._bool_with_default(
                raw_rule,
                "require_confirmation",
                default=False,
            )
            allowed_scopes = tuple(self._optional_string_list(raw_rule, "allowed_scopes"))
            for scope in allowed_scopes:
                if scope not in SUPPORTED_SCOPES:
                    raise ValueError(
                        f"Policy rule for '{tool_name}' contains unsupported scope '{scope}'."
                    )
            service_patterns = tuple(self._optional_string_list(raw_rule, "service_patterns"))
            tool_rules[tool_name] = ToolPolicyRule(
                enabled=enabled,
                require_confirmation=require_confirmation,
                allowed_scopes=allowed_scopes,
                service_patterns=service_patterns,
            )
        return tool_rules

    def _parse_config_targets(self, raw_targets: object) -> tuple[ConfigTarget, ...]:
        if raw_targets is None:
            return build_default_config_targets(self.state_dir)
        if not isinstance(raw_targets, list):
            raise ValueError("Policy field 'config_targets' must be an array of tables.")

        parsed_targets: list[ConfigTarget] = []
        for index, raw_target in enumerate(raw_targets, start=1):
            if not isinstance(raw_target, dict):
                raise ValueError(f"Config target #{index} must be a TOML table.")
            name = self._required_string(raw_target, "name", index=index)
            description = self._required_string(raw_target, "description", index=index)
            roots = tuple(
                self._resolve_policy_path(path_text)
                for path_text in self._required_string_list(raw_target, "roots", index=index)
            )
            file_globs = tuple(self._required_string_list(raw_target, "file_globs", index=index))
            validator_kind = self._required_string(raw_target, "validator", index=index)
            if validator_kind not in SUPPORTED_VALIDATORS:
                raise ValueError(
                    f"Config target '{name}' uses unsupported validator '{validator_kind}'."
                )
            validator_command_items = self._optional_string_list(raw_target, "validator_command")
            validator_command = tuple(validator_command_items) if validator_command_items else None
            if validator_kind == "command" and not validator_command:
                raise ValueError(
                    f"Config target '{name}' requires 'validator_command' for validator=command."
                )
            if validator_kind != "command" and validator_command is not None:
                raise ValueError(
                    f"Config target '{name}' may only set 'validator_command' when validator=command."
                )
            parsed_targets.append(
                ConfigTarget(
                    name=name,
                    description=description,
                    roots=roots,
                    file_globs=file_globs,
                    validator_kind=validator_kind,
                    validator_command=validator_command,
                )
            )
        return tuple(parsed_targets)

    def _resolve_policy_path(self, raw_path: str) -> Path:
        expanded = raw_path.replace("$STATE_DIR", str(self.state_dir))
        candidate = Path(expanded).expanduser()
        if not candidate.is_absolute():
            candidate = self.path.parent / candidate
        return candidate.resolve(strict=False)

    def _required_string(
        self,
        payload: dict[str, object],
        key: str,
        *,
        index: int | None = None,
    ) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            location = f" in config target #{index}" if index is not None else ""
            raise ValueError(f"Policy field '{key}'{location} must be a non-empty string.")
        return value.strip()

    def _required_string_list(
        self,
        payload: dict[str, object],
        key: str,
        *,
        index: int | None = None,
    ) -> list[str]:
        value = payload.get(key)
        if not isinstance(value, list) or not value:
            location = f" in config target #{index}" if index is not None else ""
            raise ValueError(f"Policy field '{key}'{location} must be a non-empty string list.")
        items: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(f"Policy field '{key}' contains an invalid string item.")
            items.append(item.strip())
        return items

    def _optional_string_list(self, payload: dict[str, object], key: str) -> list[str]:
        value = payload.get(key)
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError(f"Policy field '{key}' must be a string list when provided.")
        items: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(f"Policy field '{key}' contains an invalid string item.")
            items.append(item.strip())
        return items

    def _optional_bool(self, payload: dict[str, object], key: str) -> bool | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, bool):
            raise ValueError(f"Policy field '{key}' must be a boolean when provided.")
        return value

    def _bool_with_default(
        self,
        payload: dict[str, object],
        key: str,
        *,
        default: bool,
    ) -> bool:
        value = payload.get(key, default)
        if not isinstance(value, bool):
            raise ValueError(f"Policy field '{key}' must be a boolean.")
        return value
