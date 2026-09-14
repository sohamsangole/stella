"""LLM File Utility toolkit for inspecting and modifying repository files safely."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union


class FileToolError(Exception):
    """Base exception for file tool errors."""
    pass


class SecurityError(FileToolError, RuntimeError):
    """Raised when an operation violates workspace sandbox boundaries (e.g. path traversal, external symlink)."""
    pass


class TargetNotFoundError(FileToolError):
    """Raised when target content for code replacement is not found."""
    pass


class AmbiguousMatchError(FileToolError):
    """Raised when target content matches multiple locations and allow_multiple is False."""
    pass


@dataclass
class ToolResult:
    """Standard execution result returned by file tools."""
    success: bool
    output: str = ""
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "metadata": self.metadata,
        }


class FileTools:
    """
    LLM-oriented file utility providing safe, sandboxed file operations
    within a target workspace directory.
    """

    def __init__(self, workspace_root: Union[str, Path]) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def _resolve_safe_path(self, rel_path: Union[str, Path], must_exist: bool = False) -> Path:
        """
        Safely resolve a path relative to workspace_root.
        Prevents directory traversal, `.git` tampering, and symlink breakout.
        """
        raw_str = str(rel_path).strip()
        if not raw_str:
            raise FileToolError("Path cannot be empty.")

        # Normalize relative path and remove leading slashes
        clean_rel = Path(raw_str).as_posix().lstrip("/\\")

        # Disallow tampering with .git internals
        path_parts = Path(clean_rel).parts
        if ".git" in path_parts:
            raise SecurityError(f"Access to git internal path '{rel_path}' is forbidden.")

        # Build candidate path
        candidate = (self.workspace_root / clean_rel).resolve()

        # Check directory traversal outside workspace_root
        try:
            candidate.relative_to(self.workspace_root)
        except ValueError:
            raise SecurityError(
                f"unsafe {rel_path}: Path resolves outside workspace root '{self.workspace_root}'."
            )

        # Check symlink destination (both if file is symlink or already exists)
        target_to_check = self.workspace_root / clean_rel
        if target_to_check.is_symlink() or target_to_check.exists():
            real_path = Path(os.path.realpath(target_to_check))
            try:
                real_path.relative_to(self.workspace_root)
            except ValueError:
                raise SecurityError(
                    f"unsafe {rel_path}: Symlink points outside workspace root."
                )

        if must_exist and not target_to_check.exists():
            raise FileNotFoundError(f"File '{rel_path}' does not exist.")

        return target_to_check

    def read_file(
        self,
        path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        line_numbers: bool = True,
        max_bytes: int = 500_000,
    ) -> str:
        """
        Read file contents, optionally slicing by line range and prefixing 1-indexed line numbers.
        """
        target = self._resolve_safe_path(path, must_exist=True)
        if target.is_dir():
            raise FileToolError(f"Cannot read '{path}': target is a directory.")

        # Binary check
        with target.open("rb") as f:
            chunk = f.read(min(max_bytes, 8192))
            if b"\x00" in chunk:
                raise FileToolError(f"Cannot read '{path}': binary file detected.")

        file_size = target.stat().st_size
        if file_size > max_bytes:
            raise FileToolError(
                f"File '{path}' ({file_size} bytes) exceeds maximum read limit ({max_bytes} bytes)."
            )

        text = target.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        total_lines = len(lines)

        if total_lines == 0:
            return ""

        effective_start = 1 if start_line is None else max(1, start_line)
        effective_end = total_lines if end_line is None else min(total_lines, end_line)

        if effective_start > total_lines:
            raise FileToolError(
                f"start_line ({effective_start}) exceeds total line count ({total_lines})."
            )
        if effective_end < effective_start:
            raise FileToolError(
                f"Invalid line range: start_line ({effective_start}) is greater than end_line ({effective_end})."
            )

        sliced_lines = lines[effective_start - 1 : effective_end]
        if line_numbers:
            return "\n".join(
                f"{effective_start + i}: {line}" for i, line in enumerate(sliced_lines)
            )
        return "\n".join(sliced_lines)

    def create_file(self, path: str, content: str, overwrite: bool = False) -> str:
        """
        Create a new file in the workspace. Auto-creates parent directories.
        """
        target = self._resolve_safe_path(path, must_exist=False)
        if target.exists():
            if target.is_dir():
                raise FileToolError(f"Cannot create file '{path}': path is an existing directory.")
            if not overwrite:
                raise FileExistsError(
                    f"File '{path}' already exists. Pass overwrite=True or use update_file to modify."
                )

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        line_count = len(content.splitlines())
        return f"Successfully created file '{path}' ({len(content)} bytes, {line_count} lines)."

    def delete_file(self, path: str, missing_ok: bool = False) -> str:
        """
        Delete a file from the workspace.
        """
        target = self._resolve_safe_path(path, must_exist=not missing_ok)
        if not target.exists():
            if missing_ok:
                return f"File '{path}' did not exist (missing_ok=True)."
            raise FileNotFoundError(f"File '{path}' does not exist.")

        if target.is_dir():
            raise FileToolError(f"Cannot delete '{path}': target is a directory, not a file.")

        target.unlink()
        return f"Successfully deleted file '{path}'."

    def update_file(self, path: str, content: str, append: bool = False) -> str:
        """
        Overwrite or append content to a file in the workspace.
        """
        target = self._resolve_safe_path(path, must_exist=False)
        if target.exists() and target.is_dir():
            raise FileToolError(f"Cannot update '{path}': target is a directory.")

        target.parent.mkdir(parents=True, exist_ok=True)

        if append and target.exists():
            existing = target.read_text(encoding="utf-8")
            to_append = content
            if existing and not existing.endswith("\n") and not to_append.startswith("\n"):
                to_append = "\n" + to_append
            with target.open("a", encoding="utf-8") as f:
                f.write(to_append)
            return f"Successfully appended content to file '{path}'."

        target.write_text(content, encoding="utf-8")
        return f"Successfully updated file '{path}' ({len(content.splitlines())} lines)."

    def replace_code(
        self,
        path: str,
        target_content: str,
        replacement_content: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        allow_multiple: bool = False,
    ) -> str:
        """
        Replace target content or code lines with replacement content.
        Supports exact block matching, line-scoped matching, and occurrence validation.
        """
        target = self._resolve_safe_path(path, must_exist=True)
        if not target.is_file():
            raise FileToolError(f"Cannot replace code in '{path}': target is not a regular file.")

        original_text = target.read_text(encoding="utf-8")
        # Normalize line endings to \n for consistent matching
        normalized_text = original_text.replace("\r\n", "\n")
        norm_target = target_content.replace("\r\n", "\n")
        norm_replacement = replacement_content.replace("\r\n", "\n")

        # Scoped line-range replacement
        if start_line is not None and end_line is not None:
            lines = normalized_text.splitlines(keepends=True)
            total = len(lines)
            if start_line < 1 or start_line > total:
                raise FileToolError(f"start_line ({start_line}) is out of bounds (1..{total}).")
            if end_line < start_line or end_line > total:
                raise FileToolError(f"end_line ({end_line}) is out of bounds ({start_line}..{total}).")

            chunk = "".join(lines[start_line - 1 : end_line])

            # Check if target_content matches chunk or within chunk
            if norm_target in chunk:
                new_chunk = chunk.replace(norm_target, norm_replacement, 1)
                lines[start_line - 1 : end_line] = [new_chunk]
                new_text = "".join(lines)
            elif chunk.strip() == norm_target.strip():
                lines[start_line - 1 : end_line] = [norm_replacement + ("\n" if chunk.endswith("\n") else "")]
                new_text = "".join(lines)
            else:
                raise TargetNotFoundError(
                    f"Target content not found within specified lines {start_line}-{end_line} of '{path}'."
                )

            target.write_text(new_text, encoding="utf-8")
            return f"Successfully replaced code within lines {start_line}-{end_line} in '{path}'."

        # Unscoped replacement
        matches = normalized_text.count(norm_target)
        if matches == 0:
            # Check whitespace-stripped fallback
            if norm_target.strip() in normalized_text:
                # Target exists with different trailing whitespace
                norm_target = norm_target.strip()
                matches = normalized_text.count(norm_target)

            if matches == 0:
                raise TargetNotFoundError(
                    f"Target content not found in '{path}'. Please ensure exact indentation and matching characters."
                )

        if matches > 1 and not allow_multiple:
            raise AmbiguousMatchError(
                f"Target content matched {matches} occurrences in '{path}'. "
                f"Please specify start_line and end_line, or include unique surrounding context."
            )

        count_to_replace = matches if allow_multiple else 1
        new_text = normalized_text.replace(norm_target, norm_replacement, count_to_replace)

        target.write_text(new_text, encoding="utf-8")
        return f"Successfully replaced {count_to_replace} occurrence(s) in '{path}'."

    def execute_tool(self, name: str, arguments: Dict[str, Any]) -> ToolResult:
        """
        Unified tool executor dispatching calls to file tool methods.
        Returns a standardized ToolResult.
        """
        tool_map: Dict[str, Callable[..., Any]] = {
            "read_file": self.read_file,
            "create_file": self.create_file,
            "delete_file": self.delete_file,
            "update_file": self.update_file,
            "replace_code": self.replace_code,
        }

        if name not in tool_map:
            return ToolResult(
                success=False,
                error=f"Unknown tool '{name}'. Available tools: {list(tool_map.keys())}",
                metadata={"tool": name},
            )

        try:
            output = tool_map[name](**arguments)
            return ToolResult(
                success=True,
                output=str(output),
                metadata={"tool": name, "arguments": arguments},
            )
        except Exception as err:
            return ToolResult(
                success=False,
                error=f"{type(err).__name__}: {str(err)}",
                metadata={"tool": name, "arguments": arguments},
            )

    @staticmethod
    def get_tool_schemas() -> List[Dict[str, Any]]:
        """
        Get JSON tool specifications formatted for LLM tool calling (OpenAI function calling style).
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read file content from the workspace, optionally sliced by line range with line numbers.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative path to file in workspace."},
                            "start_line": {"type": "integer", "description": "1-indexed optional start line number."},
                            "end_line": {"type": "integer", "description": "1-indexed optional end line number."},
                            "line_numbers": {"type": "boolean", "description": "Whether to prefix each line with line numbers (default: true)."},
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "create_file",
                    "description": "Create a new file with specified content in the workspace. Auto-creates parent directories.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative path to the new file."},
                            "content": {"type": "string", "description": "Text content of the file."},
                            "overwrite": {"type": "boolean", "description": "If true, overwrite if file already exists (default: false)."},
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "delete_file",
                    "description": "Delete a file from the workspace.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative path to the file to delete."},
                            "missing_ok": {"type": "boolean", "description": "If true, do not fail if file already absent (default: false)."},
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "update_file",
                    "description": "Completely overwrite an existing file or append content to it in the workspace.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative path to the file."},
                            "content": {"type": "string", "description": "Text content to write or append."},
                            "append": {"type": "boolean", "description": "If true, append to file instead of overwriting (default: false)."},
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "replace_code",
                    "description": "Replace specific code lines or text chunk with new code content in an existing file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative path to the file."},
                            "target_content": {"type": "string", "description": "Exact text or code block to replace."},
                            "replacement_content": {"type": "string", "description": "New replacement code block."},
                            "start_line": {"type": "integer", "description": "Optional 1-indexed start line to scope replacement."},
                            "end_line": {"type": "integer", "description": "Optional 1-indexed end line to scope replacement."},
                            "allow_multiple": {"type": "boolean", "description": "If true, replace all occurrences (default: false)."},
                        },
                        "required": ["path", "target_content", "replacement_content"],
                    },
                },
            },
        ]


# Alias for agent clarity
LLMFileUtility = FileTools
