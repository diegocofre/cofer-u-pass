from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExchangeInputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy: Literal["auto", "inline", "attachments"] = "auto"


class ExchangeOutputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["text", "files", "bundle"] = "text"
    filename: str | None = None
    required_files: list[str] = Field(default_factory=list)
    optional_files: list[str] = Field(default_factory=list)
    allow_extra_files: bool = True

    @model_validator(mode="after")
    def validate_output(self):
        names = self.required_files + self.optional_files
        if len(names) != len(set(names)):
            raise ValueError("required_files and optional_files must not contain duplicates")
        if any(not name or name.startswith(("/", "\\")) or ".." in name.replace("\\", "/").split("/") for name in names):
            raise ValueError("output file names must be safe relative paths")
        if self.kind == "text" and (self.filename or names):
            raise ValueError("text output cannot declare filenames")
        if self.kind == "files" and self.filename:
            raise ValueError("files output does not use a bundle filename")
        if self.kind == "bundle" and not self.filename:
            self.filename = "result.zip"
        if self.filename:
            cleaned = self.filename.replace("\\", "/")
            if cleaned.startswith("/") or ".." in cleaned.split("/") or "/" in cleaned:
                raise ValueError("output filename must be a safe file name")
            if self.kind == "bundle" and not cleaned.lower().endswith(".zip"):
                raise ValueError("bundle output filename must end in .zip")
        return self


class ExchangeProtocol(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    schema_: Literal["cofer-u-pass.exchange/1"] = Field(default="cofer-u-pass.exchange/1", alias="schema")
    input: ExchangeInputSpec = Field(default_factory=ExchangeInputSpec)
    output: ExchangeOutputSpec = Field(default_factory=ExchangeOutputSpec)
