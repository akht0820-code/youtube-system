"""チャンネル設定 JSON の strict validation (pure function).

本モジュールは import / file system / 環境変数に一切触らない pure validator.
load_channel() (scripts/_channel.py) から呼ばれる。
本 Step では健康チャンネルの現行ハードコード値を写すだけで、既存コードパスに影響を与えない。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping, Sequence, Tuple


class ChannelSchemaError(Exception):
    """チャンネル設定の validation 失敗."""


@dataclass(frozen=True)
class ChannelPaths:
    output_subdir: str
    themes_file: str
    lock_file: str


@dataclass(frozen=True)
class ChannelOAuth:
    credentials: str
    token: str


@dataclass(frozen=True)
class ChannelScript:
    min_chars: int
    max_chars: int


@dataclass(frozen=True)
class ChannelTags:
    default: Tuple[str, ...]


@dataclass(frozen=True)
class ChannelConfig:
    schema_version: int
    id: str
    paths: ChannelPaths
    oauth: ChannelOAuth
    script: ChannelScript
    tags: ChannelTags


_ROOT_REQUIRED = ("schema_version", "id", "paths", "oauth", "script", "tags")
_PATHS_REQUIRED = ("output_subdir", "themes_file", "lock_file")
_OAUTH_REQUIRED = ("credentials", "token")
_SCRIPT_REQUIRED = ("min_chars", "max_chars")
_TAGS_REQUIRED = ("default",)


def _require_dict(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ChannelSchemaError(f"{field}: dict 必須 (got {type(value).__name__})")
    return value


def _check_known_keys(obj: Mapping[str, Any], allowed: Sequence[str], field: str) -> None:
    extra = set(obj.keys()) - set(allowed)
    if extra:
        raise ChannelSchemaError(
            f"{field}: 未知のキー {sorted(extra)} (許容: {list(allowed)})"
        )
    missing = set(allowed) - set(obj.keys())
    if missing:
        raise ChannelSchemaError(
            f"{field}: 必須キーが不足 {sorted(missing)}"
        )


def _require_str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ChannelSchemaError(f"{field}: str 必須 (got {type(value).__name__})")
    if not value:
        raise ChannelSchemaError(f"{field}: 空文字禁止")
    return value


def _require_int(value: Any, field: str) -> int:
    # bool は int のサブクラスなので明示的に除外する
    if isinstance(value, bool) or not isinstance(value, int):
        raise ChannelSchemaError(f"{field}: int 必須 (got {type(value).__name__})")
    return value


def _validate_path_like(value: Any, field: str) -> str:
    """path-like field に絶対パス / drive letter / traversal / UNC を許さない."""
    s = _require_str(value, field)
    # Windows と POSIX の両方の Path モデルで anchor / drive / .. を検査
    for PathModel in (PureWindowsPath, PurePosixPath):
        p = PathModel(s)
        if p.anchor:
            raise ChannelSchemaError(
                f"{field}: 絶対パス / root / UNC 禁止 ({PathModel.__name__} anchor={p.anchor!r}): {s!r}"
            )
        if getattr(p, "drive", ""):
            raise ChannelSchemaError(
                f"{field}: drive letter 禁止 ({PathModel.__name__} drive={p.drive!r}): {s!r}"
            )
        if ".." in p.parts:
            raise ChannelSchemaError(
                f"{field}: .. traversal 禁止 ({PathModel.__name__} parts={p.parts!r}): {s!r}"
            )
    return s


def _build_paths(raw: Any) -> ChannelPaths:
    d = _require_dict(raw, "paths")
    _check_known_keys(d, _PATHS_REQUIRED, "paths")
    return ChannelPaths(
        output_subdir=_validate_path_like(d["output_subdir"], "paths.output_subdir"),
        themes_file=_validate_path_like(d["themes_file"], "paths.themes_file"),
        lock_file=_validate_path_like(d["lock_file"], "paths.lock_file"),
    )


def _build_oauth(raw: Any) -> ChannelOAuth:
    d = _require_dict(raw, "oauth")
    _check_known_keys(d, _OAUTH_REQUIRED, "oauth")
    return ChannelOAuth(
        credentials=_validate_path_like(d["credentials"], "oauth.credentials"),
        token=_validate_path_like(d["token"], "oauth.token"),
    )


def _build_script(raw: Any) -> ChannelScript:
    d = _require_dict(raw, "script")
    _check_known_keys(d, _SCRIPT_REQUIRED, "script")
    min_chars = _require_int(d["min_chars"], "script.min_chars")
    max_chars = _require_int(d["max_chars"], "script.max_chars")
    if min_chars <= 0:
        raise ChannelSchemaError(f"script.min_chars: 正の int 必須 (got {min_chars})")
    if max_chars <= 0:
        raise ChannelSchemaError(f"script.max_chars: 正の int 必須 (got {max_chars})")
    if min_chars > max_chars:
        raise ChannelSchemaError(
            f"script: min_chars ({min_chars}) > max_chars ({max_chars})"
        )
    return ChannelScript(min_chars=min_chars, max_chars=max_chars)


def _build_tags(raw: Any) -> ChannelTags:
    d = _require_dict(raw, "tags")
    _check_known_keys(d, _TAGS_REQUIRED, "tags")
    default = d["default"]
    if not isinstance(default, list):
        raise ChannelSchemaError(
            f"tags.default: list 必須 (got {type(default).__name__})"
        )
    if len(default) == 0:
        raise ChannelSchemaError("tags.default: 1 個以上の要素必須")
    for i, item in enumerate(default):
        if not isinstance(item, str):
            raise ChannelSchemaError(
                f"tags.default[{i}]: str 必須 (got {type(item).__name__})"
            )
        if not item:
            raise ChannelSchemaError(f"tags.default[{i}]: 空文字禁止")
    return ChannelTags(default=tuple(default))


def validate_and_build(raw: Any, file_stem: str) -> ChannelConfig:
    """parse 済 dict を pure に検証し ChannelConfig を返す.

    - import も file system も環境変数も触らない
    - 失敗は必ず ChannelSchemaError (silent failure 禁止)
    - file_stem と `id` の整合を検証
    """
    root = _require_dict(raw, "root")
    _check_known_keys(root, _ROOT_REQUIRED, "root")

    schema_version = root["schema_version"]
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ChannelSchemaError(
            f"schema_version: int 必須 (got {type(schema_version).__name__})"
        )
    if schema_version != 1:
        raise ChannelSchemaError(f"schema_version: 1 のみ許容 (got {schema_version})")

    channel_id = _require_str(root["id"], "id")
    if channel_id != file_stem:
        raise ChannelSchemaError(
            f"id と file_stem の不一致: id={channel_id!r}, file_stem={file_stem!r}"
        )

    return ChannelConfig(
        schema_version=schema_version,
        id=channel_id,
        paths=_build_paths(root["paths"]),
        oauth=_build_oauth(root["oauth"]),
        script=_build_script(root["script"]),
        tags=_build_tags(root["tags"]),
    )
