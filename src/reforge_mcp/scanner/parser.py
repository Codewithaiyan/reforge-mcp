"""
AST Parser Module.

Uses tree-sitter to parse source files into abstract syntax trees (ASTs) and extract
symbols (functions, classes, imports) from multiple programming languages.

WHAT IS TREE-SITTER:
Tree-sitter is an incremental parsing library that builds a concrete syntax tree from
source code. Unlike regex, it understands the actual grammar of the language - it can
distinguish between a function definition and a function call, even if they look similar.

HOW AST PARSING WORKS:
1. Load a language grammar (e.g., tree-sitter-python) - this defines the syntax rules
2. Feed source code to the parser
3. Parser returns a tree where each node is a syntactic construct (function, class, etc.)
4. Query the tree using patterns to find specific constructs

WHY USE TREE-SITTER OVER REGEX:
- Regex can't handle nested structures (functions inside classes inside modules)
- Regex can't distinguish context (is "foo(" a definition or a call?)
- Tree-sitter handles all edge cases: decorators, generics, multiline signatures

LANGUAGE SUPPORT:
- Python: via tree-sitter-python
- JavaScript: via tree-sitter-javascript
- TypeScript: via tree-sitter-typescript
- Go: via tree-sitter-go
"""

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tree_sitter import Language, Parser, Query

from ..utils.security import should_skip_file

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FunctionInfo:
    """
    Represents a function definition extracted from source code.

    Attributes:
        name: Function name (e.g., "calculate_total")
        file: Relative file path where the function is defined
        start_line: Starting line number (1-indexed)
        end_line: Ending line number (inclusive)
        body_hash: SHA256 hash of the function body (for duplicate detection)
        language: Programming language (e.g., "python", "javascript")
        decorators: List of decorator names (Python) or empty list
    """

    name: str
    file: str
    start_line: int
    end_line: int
    body_hash: str
    language: str
    decorators: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClassInfo:
    """
    Represents a class definition extracted from source code.

    Attributes:
        name: Class name (e.g., "UserService")
        file: Relative file path where the class is defined
        start_line: Starting line number (1-indexed)
        end_line: Ending line number (inclusive)
        methods: List of method names defined in the class
        language: Programming language
    """

    name: str
    file: str
    start_line: int
    end_line: int
    methods: tuple[str, ...] = ()
    language: str = ""


@dataclass(frozen=True)
class ImportInfo:
    """
    Represents an import statement extracted from source code.

    Attributes:
        names: What is imported (e.g., ["Path", "os"] for "from os import Path")
        from_module: Where imported from (e.g., "os" or None for bare imports like "import os")
        file: Relative file path
        line: Line number of the import statement
        alias: Alias used (e.g., "np" for "import numpy as np")
        language: Programming language
    """

    names: tuple[str, ...]
    from_module: str | None
    file: str
    line: int
    alias: str | None = None
    language: str = ""


@dataclass(frozen=True)
class ParseResult:
    """
    Complete parse result for a single file.

    Attributes:
        file: Relative file path
        language: Detected language
        functions: All function definitions found
        classes: All class definitions found
        imports: All import statements found
        total_lines: Total lines in the file
        error: Error message if parsing failed, None otherwise
    """

    file: str
    language: str
    functions: tuple[FunctionInfo, ...]
    classes: tuple[ClassInfo, ...]
    imports: tuple[ImportInfo, ...]
    total_lines: int
    error: str | None = None


class LanguageAdapter(Protocol):
    """
    Protocol for language-specific tree-sitter adapters.

    Each language needs its own adapter because:
    - Different tree-sitter grammar packages
    - Different query syntax for finding functions/classes
    - Different AST node structures
    """

    def get_language(self) -> Language:
        """Return the tree-sitter Language for this language."""
        ...

    def get_file_extensions(self) -> set[str]:
        """Return file extensions for this language (e.g., {'.py'})."""
        ...

    def get_language_name(self) -> str:
        """Return the language name identifier (e.g., 'python')."""
        ...


class PythonAdapter:
    """
    Tree-sitter adapter for Python.

    QUERY EXPLANATION:
    Tree-sitter queries use S-expressions (Lisp-like syntax) to match AST patterns.

    For Python functions:
    (function_definition
        name: (identifier) @name
        body: (_) @body
    ) @function

    This matches:
    - A function_definition node
    - Captures its name identifier as @name
    - Captures its body as @body
    - Captures the whole definition as @function

    For decorators, we check if the function has a decorator node parent.
    """

    def __init__(self):
        import tree_sitter_python

        self._language = Language(tree_sitter_python.language())
        self._parser = Parser(self._language)

    def get_language(self) -> Language:
        return self._language

    def get_file_extensions(self) -> set[str]:
        return {".py", ".pyw"}

    def get_language_name(self) -> str:
        return "python"

    def parse(self, source: bytes, file_path: str) -> ParseResult:
        """Parse Python source code and extract symbols."""
        tree = self._parser.parse(source)
        root = tree.root_node

        functions = []
        classes = []
        imports = []

        # Query for function definitions (including inside decorated_definition)
        # We need two queries: one for regular functions, one for decorated ones
        func_query = Query(
            self._language,
            """
            (function_definition
                name: (identifier) @name
                body: (_) @body
            ) @function
            """,
        )

        # Query for class definitions
        class_query = Query(
            self._language,
            """
            (class_definition
                name: (identifier) @name
                body: (_) @body
            ) @class
            """,
        )

        # Query for imports
        import_query = Query(
            self._language,
            """
            (import_statement
                name: (dotted_name) @name
            ) @import

            (import_from_statement
                module_name: (dotted_name) @module
                name: (dotted_name | aliased_import) @name
            ) @from_import
            """,
        )

        # Helper to extract function from node
        def extract_function(func_node: "Node") -> FunctionInfo | None:
            name_node = None
            body_node = None
            decorators = []

            for child in func_node.children:
                if child.type == "identifier":
                    name_node = child
                elif child.type == "block":
                    body_node = child
                elif child.type == "decorator":
                    # Extract decorator name (e.g., @app.route -> "app.route")
                    dec_parts = []
                    for dec_child in child.children:
                        if dec_child.type == "identifier":
                            dec_parts.append(dec_child.text.decode("utf-8"))
                        elif dec_child.type == ".":
                            dec_parts.append(".")
                    if dec_parts:
                        decorators.append("".join(dec_parts))

            if name_node and body_node:
                name = name_node.text.decode("utf-8")
                start_line = name_node.start_point[0] + 1
                end_line = body_node.end_point[0] + 1
                body = source[body_node.start_byte : body_node.end_byte].decode("utf-8")
                body_hash = _hash_body(body)

                return FunctionInfo(
                    name=name,
                    file=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    body_hash=body_hash,
                    language="python",
                    decorators=tuple(decorators),
                )
            return None

        # First, find all decorated definitions and extract their functions
        decorated_query = Query(
            self._language,
            """
            (decorated_definition
                decorator: (_) @decorator
                function_definition @func
            ) @decorated_func
            """,
        )

        processed_nodes = set()

        for match in decorated_query.captures(root):
            node, capture_name = match
            if capture_name == "decorated_func":
                # Find the function_definition child
                for child in node.children:
                    if child.type == "function_definition":
                        func_info = extract_function(child)
                        if func_info:
                            functions.append(func_info)
                            processed_nodes.add(id(child))

        # Extract regular functions (not decorated, not already processed)
        for match in func_query.captures(root):
            node, capture_name = match
            if capture_name == "function":
                # Skip if already processed (was inside decorated_definition)
                if id(node) in processed_nodes:
                    continue

                func_info = extract_function(node)
                if func_info:
                    functions.append(func_info)

        # Extract classes
        for match in class_query.captures(root):
            node, capture_name = match
            if capture_name == "class":
                class_node = node
                name_node = None
                body_node = None

                for child in class_node.children:
                    if child.type == "identifier":
                        name_node = child
                    elif child.type == "block":
                        body_node = child

                if name_node:
                    name = name_node.text.decode("utf-8")
                    start_line = name_node.start_point[0] + 1
                    end_line = (
                        body_node.end_point[0] + 1 if body_node else start_line
                    )

                    # Extract methods from class body
                    methods = []
                    if body_node:
                        for child in body_node.children:
                            if child.type == "function_definition":
                                for grandchild in child.children:
                                    if grandchild.type == "identifier":
                                        methods.append(
                                            grandchild.text.decode("utf-8")
                                        )

                    classes.append(
                        ClassInfo(
                            name=name,
                            file=file_path,
                            start_line=start_line,
                            end_line=end_line,
                            methods=tuple(methods),
                            language="python",
                        )
                    )

        # Extract imports
        for match in import_query.captures(root):
            node, capture_name = match
            if capture_name == "import":
                # Bare import: import os
                name_parts = []
                for child in node.children:
                    if child.type == "dotted_name":
                        for name_child in child.children:
                            if name_child.type == "identifier":
                                name_parts.append(name_child.text.decode("utf-8"))
                if name_parts:
                    imports.append(
                        ImportInfo(
                            names=tuple(name_parts),
                            from_module=None,
                            file=file_path,
                            line=node.start_point[0] + 1,
                            language="python",
                        )
                    )
            elif capture_name == "from_import":
                # From import: from os import Path
                module_name = None
                import_names = []

                for child in node.children:
                    if child.type == "dotted_name" and not module_name:
                        module_name = ".".join(
                            c.text.decode("utf-8") for c in child.children
                        )
                    elif child.type in ("dotted_name", "aliased_import"):
                        for name_child in child.children:
                            if name_child.type == "identifier":
                                import_names.append(name_child.text.decode("utf-8"))

                if module_name and import_names:
                    imports.append(
                        ImportInfo(
                            names=tuple(import_names),
                            from_module=module_name,
                            file=file_path,
                            line=node.start_point[0] + 1,
                            language="python",
                        )
                    )

        total_lines = source.count(b"\n") + 1

        return ParseResult(
            file=file_path,
            language="python",
            functions=tuple(functions),
            classes=tuple(classes),
            imports=tuple(imports),
            total_lines=total_lines,
            error=None,
        )


class JavaScriptAdapter:
    """
    Tree-sitter adapter for JavaScript and TypeScript.

    Handles both .js and .ts files, including:
    - Function declarations: function foo() {}
    - Arrow functions: const foo = () => {}
    - Method definitions: class Foo { bar() {} }
    - Export statements: export function foo() {}
    """

    def __init__(self, typescript: bool = False):
        import tree_sitter_javascript
        import tree_sitter_typescript

        if typescript:
            self._language = Language(tree_sitter_typescript.language_typescript())
            self._extensions = {".ts", ".tsx"}
            self._name = "typescript"
        else:
            self._language = Language(tree_sitter_javascript.language())
            self._extensions = {".js", ".jsx", ".mjs", ".cjs"}
            self._name = "javascript"

        self._parser = Parser(self._language)

    def get_language(self) -> Language:
        return self._language

    def get_file_extensions(self) -> set[str]:
        return self._extensions

    def get_language_name(self) -> str:
        return self._name

    def parse(self, source: bytes, file_path: str) -> ParseResult:
        """Parse JavaScript/TypeScript source code and extract symbols."""
        tree = self._parser.parse(source)
        root = tree.root_node

        functions = []
        classes = []
        imports = []

        # Query for function declarations and arrow functions
        func_query = self._language.query(
            """
            (function_declaration
                name: (identifier) @name
                body: (_) @body
            ) @function

            (generator_function_declaration
                name: (identifier) @name
                body: (_) @body
            ) @function

            (method_definition
                name: (property_identifier) @name
                body: (_) @body
            ) @method

            (variable_declarator
                name: (identifier) @name
                value: (arrow_function
                    body: (_) @body
                )
            ) @arrow
            """
        )

        # Query for class declarations
        class_query = self._language.query(
            """
            (class_declaration
                name: (identifier) @name
                body: (class_body) @body
            ) @class
            """
        )

        # Query for imports
        import_query = self._language.query(
            """
            (import_statement
                (import_clause
                    (named_imports (import_specifier (identifier) @name))?
                    (namespace_import (identifier) @namespace)?
                )
                source: (string) @source
            ) @import
            """
        )

        # Extract functions
        for match in func_query.captures(root):
            node, capture_name = match
            if capture_name in ("function", "method", "arrow"):
                func_node = node
                name_node = None
                body_node = None

                for child in func_node.children:
                    if child.type in ("identifier", "property_identifier"):
                        name_node = child
                    elif child.type in ("statement_block", "body"):
                        body_node = child

                # For arrow functions, name is in the variable_declarator
                if capture_name == "arrow":
                    for child in func_node.children:
                        if child.type == "identifier":
                            name_node = child
                        elif child.type == "arrow_function":
                            for arrow_child in child.children:
                                if arrow_child.type == "statement_block":
                                    body_node = arrow_child

                if name_node and body_node:
                    name = name_node.text.decode("utf-8")
                    start_line = name_node.start_point[0] + 1
                    end_line = body_node.end_point[0] + 1
                    body = source[body_node.start_byte : body_node.end_byte].decode(
                        "utf-8"
                    )
                    body_hash = _hash_body(body)

                    functions.append(
                        FunctionInfo(
                            name=name,
                            file=file_path,
                            start_line=start_line,
                            end_line=end_line,
                            body_hash=body_hash,
                            language=self._name,
                        )
                    )

        # Extract classes
        for match in class_query.captures(root):
            node, capture_name = match
            if capture_name == "class":
                class_node = node
                name_node = None
                body_node = None

                for child in class_node.children:
                    if child.type == "identifier":
                        name_node = child
                    elif child.type == "class_body":
                        body_node = child

                if name_node:
                    name = name_node.text.decode("utf-8")
                    start_line = name_node.start_point[0] + 1
                    end_line = (
                        body_node.end_point[0] + 1 if body_node else start_line
                    )

                    # Extract methods
                    methods = []
                    if body_node:
                        for child in body_node.children:
                            if child.type == "method_definition":
                                for grandchild in child.children:
                                    if grandchild.type == "property_identifier":
                                        methods.append(
                                            grandchild.text.decode("utf-8")
                                        )

                    classes.append(
                        ClassInfo(
                            name=name,
                            file=file_path,
                            start_line=start_line,
                            end_line=end_line,
                            methods=tuple(methods),
                            language=self._name,
                        )
                    )

        # Extract imports
        for match in import_query.captures(root):
            node, capture_name = match
            if capture_name == "import":
                source_node = None
                names = []

                for child in node.children:
                    if child.type == "string":
                        # Remove quotes
                        source_node = child.text.decode("utf-8")[1:-1]
                    elif child.type == "import_clause":
                        for clause_child in child.children:
                            if clause_child.type == "named_imports":
                                for spec_child in clause_child.children:
                                    if spec_child.type == "import_specifier":
                                        for spec_name_child in spec_child.children:
                                            if spec_name_child.type == "identifier":
                                                names.append(
                                                    spec_name_child.text.decode(
                                                        "utf-8"
                                                    )
                                                )
                            elif clause_child.type == "namespace_import":
                                for ns_child in clause_child.children:
                                    if ns_child.type == "identifier":
                                        names.append(ns_child.text.decode("utf-8"))

                if source_node:
                    imports.append(
                        ImportInfo(
                            names=tuple(names) if names else ("*",),
                            from_module=source_node,
                            file=file_path,
                            line=node.start_point[0] + 1,
                            language=self._name,
                        )
                    )

        total_lines = source.count(b"\n") + 1

        return ParseResult(
            file=file_path,
            language=self._name,
            functions=tuple(functions),
            classes=tuple(classes),
            imports=tuple(imports),
            total_lines=total_lines,
            error=None,
        )


class GoAdapter:
    """
    Tree-sitter adapter for Go.

    Handles:
    - Function declarations: func foo() {}
    - Method declarations: func (r Receiver) foo() {}
    - Type declarations: type Foo struct {}
    - Import statements: import "package"
    """

    def __init__(self):
        import tree_sitter_go

        self._language = Language(tree_sitter_go.language())
        self._parser = Parser(self._language)

    def get_language(self) -> Language:
        return self._language

    def get_file_extensions(self) -> set[str]:
        return {".go"}

    def get_language_name(self) -> str:
        return "go"

    def parse(self, source: bytes, file_path: str) -> ParseResult:
        """Parse Go source code and extract symbols."""
        tree = self._parser.parse(source)
        root = tree.root_node

        functions = []
        classes = []
        imports = []

        # Query for function and method declarations
        func_query = self._language.query(
            """
            (function_declaration
                name: (identifier) @name
                body: (_) @body
            ) @function

            (method_declaration
                name: (field_identifier) @name
                body: (_) @body
            ) @method
            """
        )

        # Query for type declarations (structs, interfaces)
        type_query = self._language.query(
            """
            (type_declaration
                (type_spec
                    name: (identifier) @name
                    type: (_) @type
                )
            ) @type
            """
        )

        # Query for imports
        import_query = self._language.query(
            """
            (import_declaration
                (import_spec
                    (interpreted_string_literal) @path
                )
            ) @import

            (import_declaration
                (import_spec_list
                    (import_spec
                        (interpreted_string_literal) @path
                    )
                )
            ) @import_list
            """
        )

        # Extract functions
        for match in func_query.captures(root):
            node, capture_name = match
            if capture_name in ("function", "method"):
                func_node = node
                name_node = None
                body_node = None

                for child in func_node.children:
                    if child.type in ("identifier", "field_identifier"):
                        name_node = child
                    elif child.type == "block":
                        body_node = child

                if name_node and body_node:
                    name = name_node.text.decode("utf-8")
                    start_line = name_node.start_point[0] + 1
                    end_line = body_node.end_point[0] + 1
                    body = source[body_node.start_byte : body_node.end_byte].decode(
                        "utf-8"
                    )
                    body_hash = _hash_body(body)

                    functions.append(
                        FunctionInfo(
                            name=name,
                            file=file_path,
                            start_line=start_line,
                            end_line=end_line,
                            body_hash=body_hash,
                            language="go",
                        )
                    )

        # Extract types (classes in Go are structs with methods)
        for match in type_query.captures(root):
            node, capture_name = match
            if capture_name == "type":
                type_node = node
                name_node = None

                for child in type_node.children:
                    if child.type == "identifier":
                        name_node = child

                if name_node:
                    name = name_node.text.decode("utf-8")
                    start_line = name_node.start_point[0] + 1
                    end_line = type_node.end_point[0] + 1

                    classes.append(
                        ClassInfo(
                            name=name,
                            file=file_path,
                            start_line=start_line,
                            end_line=end_line,
                            language="go",
                        )
                    )

        # Extract imports
        for match in import_query.captures(root):
            node, capture_name = match
            if capture_name in ("import", "import_list"):
                for child in node.children:
                    if child.type == "interpreted_string_literal":
                        # Remove quotes
                        path = child.text.decode("utf-8")[1:-1]
                        imports.append(
                            ImportInfo(
                                names=("*",),
                                from_module=path,
                                file=file_path,
                                line=node.start_point[0] + 1,
                                language="go",
                            )
                        )

        total_lines = source.count(b"\n") + 1

        return ParseResult(
            file=file_path,
            language="go",
            functions=tuple(functions),
            classes=tuple(classes),
            imports=tuple(imports),
            total_lines=total_lines,
            error=None,
        )


def _hash_body(body: str) -> str:
    """
    Compute SHA256 hash of a normalized function body.

    Normalization:
    - Strip leading/trailing whitespace from each line
    - Remove empty lines
    - Remove single-line comments
    - Remove extra whitespace between tokens

    This ensures that copy-pasted code with minor formatting differences
    is detected as a duplicate.
    """
    lines = body.split("\n")
    normalized_lines = []

    for line in lines:
        stripped = line.strip()
        # Skip empty lines and comments
        if not stripped:
            continue
        if stripped.startswith(("#", "//", "/*", "*")):
            continue
        normalized_lines.append(stripped)

    normalized = "\n".join(normalized_lines)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# Global adapter registry
_ADAPTERS: list[LanguageAdapter] = []


def _init_adapters() -> list[LanguageAdapter]:
    """Initialize all language adapters."""
    return [
        PythonAdapter(),
        JavaScriptAdapter(typescript=False),
        JavaScriptAdapter(typescript=True),
        GoAdapter(),
    ]


def get_adapter_for_file(file_path: Path) -> LanguageAdapter | None:
    """
    Get the appropriate language adapter for a file based on its extension.

    Returns None if no adapter is found for the file's extension.
    """
    if not _ADAPTERS:
        _ADAPTERS.extend(_init_adapters())

    suffix = file_path.suffix.lower()

    for adapter in _ADAPTERS:
        if suffix in adapter.get_file_extensions():
            return adapter

    return None


def get_adapter_for_language(language: str) -> LanguageAdapter | None:
    """
    Get the appropriate language adapter by language name.

    Returns None if no adapter is found for the language.
    """
    if not _ADAPTERS:
        _ADAPTERS.extend(_init_adapters())

    language_lower = language.lower()

    for adapter in _ADAPTERS:
        if adapter.get_language_name().lower() == language_lower:
            return adapter

    return None


def parse_file(
    file_path: Path, repo_root: Path, relative_to: Path | None = None
) -> ParseResult | None:
    """
    Parse a source file and extract symbols.

    Args:
        file_path: Absolute path to the file to parse
        repo_root: Repository root for security validation
        relative_to: Path to compute relative paths from (default: repo_root)

    Returns:
        ParseResult with extracted symbols, or None if file should be skipped

    Raises:
        SecurityError: If file path validation fails
        No other exceptions - parse errors are logged and returned as error field
    """
    from ..utils.security import SecurityError, validate_path

    # Security: validate path is within repo
    try:
        validate_path(str(file_path), str(repo_root))
    except SecurityError as e:
        logger.warning(f"Security validation failed for {file_path}: {e}")
        return None

    # Check if file should be skipped
    if should_skip_file(file_path):
        logger.debug(f"Skipping file (binary/lock/oversized): {file_path}")
        return None

    # Get adapter for this file
    adapter = get_adapter_for_file(file_path)
    if adapter is None:
        logger.debug(f"No adapter for file extension: {file_path.suffix}")
        return None

    # Compute relative path
    base_path = relative_to or repo_root
    try:
        rel_path = str(file_path.relative_to(base_path))
    except ValueError:
        rel_path = str(file_path)

    # Read and parse file
    try:
        source = file_path.read_bytes()
    except (OSError, IOError) as e:
        logger.warning(f"Failed to read file {file_path}: {e}")
        return ParseResult(
            file=rel_path,
            language=adapter.get_language_name(),
            functions=(),
            classes=(),
            imports=(),
            total_lines=0,
            error=f"Failed to read file: {e}",
        )

    try:
        result = adapter.parse(source, rel_path)
        logger.debug(
            f"Parsed {rel_path}: {len(result.functions)} functions, "
            f"{len(result.classes)} classes, {len(result.imports)} imports"
        )
        return result
    except Exception as e:
        logger.warning(f"Parse error for {file_path}: {e}")
        return ParseResult(
            file=rel_path,
            language=adapter.get_language_name(),
            functions=(),
            classes=(),
            imports=(),
            total_lines=source.count(b"\n") + 1,
            error=f"Parse error: {e}",
        )


def parse_directory(
    directory: Path,
    repo_root: Path,
    ignore_dirs: set[str] | None = None,
    languages: list[str] | None = None,
) -> list[ParseResult]:
    """
    Parse all source files in a directory recursively.

    Args:
        directory: Directory to scan
        repo_root: Repository root for path validation
        ignore_dirs: Directory names to skip (e.g., {"node_modules", ".git"})
        languages: Optional filter for languages to parse

    Returns:
        List of ParseResult for each successfully parsed file
    """
    if ignore_dirs is None:
        ignore_dirs = {
            "node_modules",
            ".git",
            "__pycache__",
            ".venv",
            "venv",
            "dist",
            "build",
            ".egg-info",
            ".pytest_cache",
            ".mypy_cache",
        }

    results = []

    # Get adapters for requested languages
    if languages:
        adapters = []
        for lang in languages:
            adapter = get_adapter_for_language(lang)
            if adapter:
                adapters.append(adapter)
        if not adapters:
            logger.warning(f"No adapters found for languages: {languages}")
            return results
        valid_extensions = set()
        for adapter in adapters:
            valid_extensions.update(adapter.get_file_extensions())
    else:
        # Initialize all adapters
        if not _ADAPTERS:
            _ADAPTERS.extend(_init_adapters())
        valid_extensions = set()
        for adapter in _ADAPTERS:
            valid_extensions.update(adapter.get_file_extensions())

    # Walk directory
    for path in directory.rglob("*"):
        if not path.is_file():
            continue

        # Skip ignored directories
        skip = False
        for part in path.relative_to(directory).parts:
            if part in ignore_dirs:
                skip = True
                break
        if skip:
            continue

        # Check extension
        if path.suffix.lower() not in valid_extensions:
            continue

        # Parse file
        result = parse_file(path, repo_root, directory)
        if result:
            results.append(result)

    return results
