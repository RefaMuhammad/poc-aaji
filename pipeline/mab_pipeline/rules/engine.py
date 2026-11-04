"""Evaluator ekspresi kondisi aturan yang aman (tanpa eval).

Ekspresi di YAML di-parse dengan `ast` lalu dicek terhadap daftar node yang
diizinkan. Yang boleh dipakai:
  - field klaim: kelompok.field, mis. lab.platelet_min
  - konstanta: angka, teks, True/False/None, tuple/list konstanta
  - and, or, not, minus unary
  - perbandingan: == != < <= > >= in, not in, is, is not
  - fungsi len(...)
Semua yang lain (pemanggilan fungsi lain, akses atribut bertingkat, subscript,
lambda, dunder, dsb.) ditolak saat aturan dimuat.

Data kosong (None) tidak membuat crash. Jika sebuah perbandingan urutan
(< <= > >=) atau len() bertemu None, aturan dianggap tidak bisa dinilai dan
dilaporkan sebagai "skipped" beserta field yang kosong. Ini sama dengan
perilaku evaluator lama (TypeError -> tidak terpicu).
"""
from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass, field
from typing import Any

from mab_pipeline.schemas import GROUPS, ClaimData


class ExpressionError(ValueError):
    """Ekspresi aturan tidak valid atau memakai konstruksi yang tidak diizinkan."""


class MissingData(Exception):
    """Data yang dibutuhkan ekspresi kosong (None)."""

    def __init__(self, fields: list[str]):
        super().__init__(", ".join(fields))
        self.fields = fields


_ALLOWED_FUNCS = {"len"}

_COMPARE_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}
_ORDER_OPS = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)


@dataclass(frozen=True)
class CompiledExpression:
    source: str
    tree: ast.Expression
    fields: tuple[str, ...] = field(default_factory=tuple)


def compile_expression(source: str) -> CompiledExpression:
    """Parse dan validasi ekspresi. Melempar ExpressionError bila tidak aman."""
    normalized = " ".join(str(source).split())
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"sintaks tidak valid: {normalized!r} ({exc.msg})") from exc
    fields: list[str] = []
    _validate(tree.body, fields)
    return CompiledExpression(normalized, tree, tuple(dict.fromkeys(fields)))


def _validate(node: ast.AST, fields: list[str]) -> None:
    if isinstance(node, ast.BoolOp):
        for value in node.values:
            _validate(value, fields)
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.Not, ast.USub)):
            raise ExpressionError(f"operator tidak diizinkan: {type(node.op).__name__}")
        _validate(node.operand, fields)
    elif isinstance(node, ast.Compare):
        for op in node.ops:
            if type(op) not in _COMPARE_OPS:
                raise ExpressionError(f"perbandingan tidak diizinkan: {type(op).__name__}")
        _validate(node.left, fields)
        for comparator in node.comparators:
            _validate(comparator, fields)
    elif isinstance(node, ast.Attribute):
        if not (isinstance(node.value, ast.Name) and node.value.id in GROUPS):
            raise ExpressionError("akses atribut hanya boleh berbentuk kelompok.field")
        if node.attr.startswith("_"):
            raise ExpressionError(f"nama field tidak valid: {node.attr}")
        fields.append(f"{node.value.id}.{node.attr}")
    elif isinstance(node, ast.Call):
        if not (isinstance(node.func, ast.Name) and node.func.id in _ALLOWED_FUNCS):
            raise ExpressionError("hanya fungsi len() yang diizinkan")
        if len(node.args) != 1 or node.keywords:
            raise ExpressionError("len() menerima tepat satu argumen")
        _validate(node.args[0], fields)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for elt in node.elts:
            if not isinstance(elt, ast.Constant):
                raise ExpressionError("tuple/list hanya boleh berisi konstanta")
    elif isinstance(node, ast.Constant):
        if not isinstance(node.value, (str, int, float, bool, type(None))):
            raise ExpressionError(f"konstanta tidak diizinkan: {node.value!r}")
    elif isinstance(node, ast.Name):
        raise ExpressionError(f"nama tidak dikenal: {node.id} (pakai kelompok.field)")
    else:
        raise ExpressionError(f"konstruksi tidak diizinkan: {type(node).__name__}")


def evaluate(expr: CompiledExpression, claim: ClaimData) -> bool:
    """Nilai ekspresi terhadap klaim. Melempar MissingData bila data kosong menghalangi."""
    return bool(_eval(expr.tree.body, claim))


def _eval(node: ast.AST, claim: ClaimData) -> Any:
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result: Any = True
            for value in node.values:
                result = _eval(value, claim)
                if not result:
                    return result
            return result
        result = False
        for value in node.values:
            result = _eval(value, claim)
            if result:
                return result
        return result
    if isinstance(node, ast.UnaryOp):
        operand = _eval(node.operand, claim)
        if isinstance(node.op, ast.Not):
            return not operand
        if operand is None:
            raise MissingData(_fields_in(node.operand))
        return -operand
    if isinstance(node, ast.Compare):
        left = _eval(node.left, claim)
        left_node = node.left
        for op, right_node in zip(node.ops, node.comparators):
            right = _eval(right_node, claim)
            if isinstance(op, _ORDER_OPS) and (left is None or right is None):
                raise MissingData(_fields_in(left_node) + _fields_in(right_node))
            if isinstance(op, (ast.In, ast.NotIn)) and right is None:
                raise MissingData(_fields_in(right_node))
            if not _COMPARE_OPS[type(op)](left, right):
                return False
            left, left_node = right, right_node
        return True
    if isinstance(node, ast.Attribute):
        return claim.get_field(f"{node.value.id}.{node.attr}")  # type: ignore[attr-defined]
    if isinstance(node, ast.Call):
        arg = _eval(node.args[0], claim)
        if arg is None:
            raise MissingData(_fields_in(node.args[0]))
        return len(arg)
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(elt.value for elt in node.elts)  # type: ignore[attr-defined]
    if isinstance(node, ast.Constant):
        return node.value
    raise ExpressionError(f"konstruksi tidak diizinkan: {type(node).__name__}")  # pragma: no cover


def _fields_in(node: ast.AST) -> list[str]:
    return [
        f"{n.value.id}.{n.attr}"
        for n in ast.walk(node)
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
    ]


_PLACEHOLDER = re.compile(r"\{([a-z_]+)\.([a-z_0-9]+)\}")


def message_fields(template: str) -> list[str]:
    return [f"{g}.{f}" for g, f in _PLACEHOLDER.findall(template)]


def render_message(template: str, claim: ClaimData) -> str:
    """Ganti {kelompok.field} dengan nilai klaim, dalam format yang enak dibaca."""

    def replace(match: re.Match) -> str:
        return _format_value(claim.get_field(f"{match.group(1)}.{match.group(2)}"))

    return " ".join(_PLACEHOLDER.sub(replace, template).split())


def _format_value(value: Any) -> str:
    if value is None:
        return "tidak diketahui"
    if isinstance(value, bool):
        return "ya" if value else "tidak"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int):
        return f"{value:,}".replace(",", ".")  # 120000 -> 120.000
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value) if value else "-"
    return str(value)
