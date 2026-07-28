from __future__ import annotations

import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from cofer_u_pass.config.settings import AppConfig

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".py", ".cs", ".vb", ".fs", ".fsx", ".js", ".jsx",
    ".ts", ".tsx", ".json", ".yaml", ".yml", ".xml", ".html", ".htm", ".css", ".scss",
    ".sql", ".sh", ".bash", ".ps1", ".toml", ".ini", ".cfg", ".conf", ".log", ".csv",
    ".java", ".kt", ".kts", ".go", ".rs", ".c", ".cc", ".cpp", ".h", ".hpp", ".php",
    ".rb", ".swift", ".dart", ".vue", ".svelte", ".dockerfile", ".gitignore", ".env.example",
}
ARCHIVE_EXTENSIONS = {".zip"}


@dataclass(slots=True)
class NormalizedInputs:
    inline_context: str = ""
    attachments: list[Path] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    _tempdirs: list[TemporaryDirectory] = field(default_factory=list, repr=False)

    def cleanup(self) -> None:
        while self._tempdirs:
            self._tempdirs.pop().cleanup()


def _is_text(path: Path) -> bool:
    name = path.name.lower()
    return path.suffix.lower() in TEXT_EXTENSIONS or name in {"dockerfile", "makefile", "license", "readme"}


def _read_text(path: Path) -> tuple[str, str | None]:
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig"), None
    except UnicodeDecodeError:
        return data.decode("latin-1"), f"decoded {path.name} as latin-1"


def _safe_member_name(info: zipfile.ZipInfo) -> PurePosixPath:
    raw = info.filename.replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe ZIP member path: {info.filename!r}")
    mode = (info.external_attr >> 16) & 0xFFFF
    if mode and (stat.S_ISLNK(mode) or stat.S_ISCHR(mode) or stat.S_ISBLK(mode) or stat.S_ISFIFO(mode)):
        raise ValueError(f"unsupported ZIP member type: {info.filename!r}")
    return path


def _extract_zip(path: Path, config: AppConfig) -> tuple[list[Path], TemporaryDirectory]:
    temp = TemporaryDirectory(prefix="cupass-bundle-", dir=config.temp_path)
    root = Path(temp.name).resolve()
    extracted: list[Path] = []
    total = 0
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > config.security.max_archive_entries:
            temp.cleanup()
            raise ValueError("ZIP exceeds max_archive_entries")
        for info in infos:
            if info.is_dir():
                continue
            member = _safe_member_name(info)
            if len(member.parts) > config.security.max_archive_depth:
                temp.cleanup()
                raise ValueError(f"ZIP member exceeds max_archive_depth: {info.filename}")
            if PurePosixPath(info.filename).suffix.lower() in ARCHIVE_EXTENSIONS:
                temp.cleanup()
                raise ValueError(f"nested archives are not supported: {info.filename}")
            total += info.file_size
            if info.file_size > config.security.max_input_file_bytes:
                temp.cleanup()
                raise ValueError(f"ZIP member exceeds max_input_file_bytes: {info.filename}")
            if total > config.security.max_archive_uncompressed_bytes:
                temp.cleanup()
                raise ValueError("ZIP exceeds max_archive_uncompressed_bytes")
            target = (root / Path(*member.parts)).resolve()
            if root not in target.parents:
                temp.cleanup()
                raise ValueError(f"ZIP member escapes extraction root: {info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, target.open("wb") as dst:
                remaining = config.security.max_input_file_bytes + 1
                while remaining > 0:
                    chunk = src.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    dst.write(chunk)
                    remaining -= len(chunk)
                if remaining <= 0 and src.read(1):
                    temp.cleanup()
                    raise ValueError(f"ZIP member expanded beyond declared safety limit: {info.filename}")
            extracted.append(target)
    return extracted, temp


def normalize_input_files(paths: list[Path], config: AppConfig, *, strategy: str = "auto") -> NormalizedInputs:
    result = NormalizedInputs()
    expanded: list[tuple[Path, str]] = []
    for original in paths:
        resolved = original.expanduser().resolve(strict=True)
        if resolved.suffix.lower() == ".zip":
            extracted, temp = _extract_zip(resolved, config)
            result._tempdirs.append(temp)
            for item in extracted:
                expanded.append((item, f"{resolved.name}/{item.relative_to(Path(temp.name)).as_posix()}"))
        else:
            expanded.append((resolved, resolved.name))

    text_sections: list[str] = []
    text_bytes = 0
    for path, logical_name in expanded:
        result.source_files.append(logical_name)
        if _is_text(path):
            text, warning = _read_text(path)
            if warning:
                result.warnings.append(warning)
            encoded_size = len(text.encode("utf-8"))
            if text_bytes + encoded_size > config.security.max_combined_text_bytes:
                result.attachments.append(path)
                result.warnings.append(f"{logical_name} kept as attachment because combined text limit was reached")
                continue
            text_bytes += encoded_size
            text_sections.append(f"\n<cofer-file path={logical_name!r}>\n{text}\n</cofer-file>\n")
        else:
            result.attachments.append(path)

    combined = "".join(text_sections).strip()
    if not combined:
        return result

    inline = strategy == "inline" or (strategy == "auto" and len(combined.encode("utf-8")) <= config.security.max_inline_text_bytes)
    if inline:
        result.inline_context = combined
        return result

    temp = TemporaryDirectory(prefix="cupass-context-", dir=config.temp_path)
    result._tempdirs.append(temp)
    context_path = Path(temp.name) / "CUPASS_CONTEXT.md"
    context_path.write_text(
        "# Cofer U Pass normalized context\n\nThe following sections preserve the source file paths and textual contents.\n\n" + combined,
        encoding="utf-8",
    )
    result.attachments.insert(0, context_path)
    return result


def validate_output_bundle(
    path: Path,
    config: AppConfig,
    *,
    required_files: list[str],
    optional_files: list[str] | None = None,
    allow_extra_files: bool = True,
) -> list[str]:
    """Validate a provider-produced ZIP without trusting member metadata or extracting it."""
    if path.suffix.lower() != ".zip":
        raise ValueError(f"expected ZIP bundle, got {path.name}")
    names: list[str] = []
    total = 0
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > config.security.max_archive_entries:
            raise ValueError("output ZIP exceeds max_archive_entries")
        for info in infos:
            if info.is_dir():
                continue
            member = _safe_member_name(info)
            if len(member.parts) > config.security.max_archive_depth:
                raise ValueError(f"output ZIP member exceeds max_archive_depth: {info.filename}")
            if member.suffix.lower() in ARCHIVE_EXTENSIONS:
                raise ValueError(f"nested archives are not supported in output bundles: {info.filename}")
            total += info.file_size
            if info.file_size > config.security.max_artifact_bytes:
                raise ValueError(f"output ZIP member exceeds max_artifact_bytes: {info.filename}")
            if total > config.security.max_archive_uncompressed_bytes:
                raise ValueError("output ZIP exceeds max_archive_uncompressed_bytes")
            names.append(member.as_posix())
    missing = [name for name in required_files if name not in names]
    if missing:
        raise ValueError(f"output bundle is missing required files: {missing}")
    if not allow_extra_files:
        expected = set(required_files) | set(optional_files or [])
        extras = [name for name in names if name not in expected]
        if extras:
            raise ValueError(f"output bundle contains unexpected files: {extras}")
    return names
