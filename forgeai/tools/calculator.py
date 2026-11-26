"""Safe AST-based arithmetic calculator tool (no eval/exec)."""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

_BIN_OPS: dict[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS: dict[type[ast.unaryop], Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_ALLOWED_FUNCS: dict[str, Any] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "sqrt": math.sqrt,
    "ceil": math.ceil,
    "floor": math.floor,
}


class UnsafeExpressionError(ValueError):
    """Raised when an expression contains disallowed syntax or operations."""


def _eval_node(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise UnsafeExpressionError(f"Unsupported constant type: {type(node.value).__name__}")
        return node.value
    if isinstance(node, ast.BinOp):
        op_fn = _BIN_OPS.get(type(node.op))
        if op_fn is None:
            raise UnsafeExpressionError(f"Unsupported binary operator: {type(node.op).__name__}")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise UnsafeExpressionError("Exponent magnitude > 1000 is disallowed.")
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
            raise UnsafeExpressionError("Division by zero.")
        return op_fn(left, right)
    if isinstance(node, ast.UnaryOp):
        op_fn = _UNARY_OPS.get(type(node.op))
        if op_fn is None:
            raise UnsafeExpressionError(f"Unsupported unary operator: {type(node.op).__name__}")
        return op_fn(_eval_node(node.operand))
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval_node(elt) for elt in node.elts]
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
            raise UnsafeExpressionError("Function call not allowed.")
        if node.keywords:
            raise UnsafeExpressionError("Keyword arguments are not allowed in calculator.")
        args = [_eval_node(arg) for arg in node.args]
        return _ALLOWED_FUNCS[node.func.id](*args)

    raise UnsafeExpressionError(f"Disallowed AST node: {type(node).__name__}")


def safe_calculate(expression: str) -> float | int:
    """Safely evaluate an arithmetic expression using AST inspection."""
    cleaned = expression.strip()
    if not cleaned:
        raise UnsafeExpressionError("Empty expression.")
    if len(cleaned) > 300:
        raise UnsafeExpressionError("Expression exceeds maximum length (300 chars).")
    try:
        tree = ast.parse(cleaned, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpressionError(f"Invalid syntax: {exc}") from exc
    result = _eval_node(tree)
    if not isinstance(result, (int, float)) or isinstance(result, bool):
        raise UnsafeExpressionError("Expression did not evaluate to a number.")
    return result


def calculator_tool(expression: str = "") -> str:
    """Tool callable returning the arithmetic result or a structured error."""
    try:
        value = safe_calculate(expression)
        if isinstance(value, float) and value.is_integer():
            formatted = str(int(value))
        elif isinstance(value, float):
            formatted = f"{value:.6g}"
        else:
            formatted = str(value)
        return f"expression={expression} -> result={formatted}"
    except Exception as exc:
        return f"calculator_error: {exc}"
