"""The contract between the game and its rulers, frozen and versioned.

A ruler reads a `NationView` and answers with `Orders`; that is all it may know or do. Both are
Pydantic models, and their JSON schemas are the contract an AI ruler is written against. They are
kept in `docs/contract/`, with a fingerprint, so that a change to either is always deliberate:

- `CONTRACT_VERSION` follows semantic versioning. The **major** number changes when a ruler
  written for the old contract could break: a field or an order removed or renamed, a type
  changed, a field that was optional made required. The **minor** number changes when something
  is only added: a new field in the view, a new order, a new optional field in an order.
- `make contract` writes the schemas and the fingerprint, and the reference of orders in
  `docs/agent-contract.md`. A test fails while they disagree with the code.

Every `NationView` carries the version (`view.contract`), so a ruler can check what it reads.
"""

import enum
import hashlib
import inspect
import json
import re
import types
import typing
from typing import Any, Literal

from pydantic import BaseModel

from pax_agentica.engine.actions import Action, Orders

CONTRACT_VERSION = "1.0.0"


def action_types() -> list[type[BaseModel]]:
    """Every order a ruler may give, in the order the union lists them."""
    union = typing.get_args(Action.__value__)[0]
    return list(typing.get_args(union))


def contract_schemas() -> dict[str, dict[str, Any]]:
    """The JSON schemas of what a ruler reads and what it answers."""
    from pax_agentica.engine.view import NationView  # the view builds on this module's version

    return {
        "nation_view": NationView.model_json_schema(),
        "orders": Orders.model_json_schema(),
    }


def canonical(schema: dict[str, Any]) -> str:
    """A schema as it is kept on disk: sorted keys, two-space indents, a final newline."""
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def contract_fingerprint() -> str:
    """A short hash of both schemas: it changes with the slightest change to the contract."""
    text = "".join(canonical(s) for _, s in sorted(contract_schemas().items()))
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _type_name(annotation: Any) -> str:
    """A field's type as a ruler reads it: `int`, `ProvinceId`, `list[UnitKind]`, `"a" | "b"`."""
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if origin is typing.Annotated:
        return _type_name(args[0])
    if origin is Literal:
        return " | ".join(json.dumps(a) for a in args)
    if origin in (typing.Union, types.UnionType):
        return " | ".join(_type_name(a) for a in args)
    if origin is not None:
        inner = ", ".join(_type_name(a) for a in args)
        return f"{getattr(origin, '__name__', str(origin))}[{inner}]"
    if annotation is type(None):
        return "null"
    if annotation is Ellipsis:
        return "..."
    if isinstance(annotation, typing.TypeAliasType):
        return annotation.__name__
    return getattr(annotation, "__name__", str(annotation))


def _values(annotation: Any) -> list[str]:
    """The values of the enums a field takes, to list them beside it."""
    found = []
    for a in typing.get_args(annotation) or (annotation,):
        if inspect.isclass(a) and issubclass(a, enum.Enum):
            found.append(f"{a.__name__}: " + ", ".join(f"`{m.value}`" for m in a))
        elif typing.get_args(a):
            found += _values(a)
    return found


def orders_reference() -> str:
    """Every order a ruler may give: its `type`, its fields and what it does, from the code."""
    out = []
    for kind in action_types():
        fields = kind.model_fields
        tag = typing.get_args(fields["type"].annotation)[0]
        doc = inspect.cleandoc(kind.__doc__ or "").replace("\n", " ")
        out.append(f"### `{tag}`\n\n{doc}\n")
        rows, enums = [], []
        for name, info in fields.items():
            if name == "type":
                continue
            if info.is_required():
                need = "required"
            elif info.default_factory is not None:
                need = "optional"
            else:
                value = info.default.value if isinstance(info.default, enum.Enum) else info.default
                need = f"default `{json.dumps(value, default=str)}`"
            shown = _type_name(info.annotation).replace("|", "\\|")  # a pipe would end the cell
            rows.append(f"| `{name}` | `{shown}` | {need} |")
            enums += [e for e in _values(info.annotation) if e not in enums]
        if rows:
            out.append("| Field | Type | |\n|---|---|---|\n" + "\n".join(rows) + "\n")
        if enums:
            out.append("\n".join(f"- {e}" for e in enums) + "\n")
    return "\n".join(out)


def _comments(cls: type) -> dict[str, str]:
    """The comment beside each field in a class's source: what the field means. A field whose
    type runs over several lines carries its comment on the closing line."""
    out: dict[str, str] = {}
    source = inspect.getsource(cls).splitlines()
    for i, line in enumerate(source):
        m = re.match(r"    (\w+): (.*)$", line)
        if not m or m.group(1) == "model_config":
            continue
        rest, at = m.group(2), i
        if rest.rstrip().endswith(("[", "(")):  # the type goes on: find where it closes
            at = next(
                (k for k in range(i + 1, len(source)) if re.match(r"\s{4}[\])]", source[k])), i
            )
            rest = source[at]
        text = rest.split("#", 1)[1].strip() if "#" in rest else ""
        for more in source[at + 1 :]:  # a comment may run on over the next lines
            follow = re.match(r"\s{4,}#\s*(.*)$", more)
            if not follow:
                break
            text += " " + follow.group(1)
        out[m.group(1)] = text.strip()
    return out


OBVIOUS = {"id": "its id", "name": "its name", "title": "its title", "lore": "its story, in words",
           "text": "what it says, in words"}  # fmt: skip


def view_reference() -> str:
    """What a ruler reads: every model of the view, its fields, their types and meanings."""
    from pax_agentica.engine import view

    first = ["NationView", "MyNation", "ProvinceView", "NationSummary"]
    models = {
        name: cls
        for name, cls in vars(view).items()
        if inspect.isclass(cls) and issubclass(cls, view._View) and cls is not view._View
    }
    order = first + sorted(n for n in models if n not in first)
    out = []
    for name in order:
        cls = models[name]
        notes = _comments(cls)
        doc = inspect.cleandoc(cls.__doc__ or "").replace("\n", " ") if cls.__doc__ else ""
        out.append(f"### `{name}`\n" + (f"\n{doc}\n" if doc else ""))
        rows = []
        for field, info in cls.model_fields.items():
            shown = _type_name(info.annotation).replace("|", "\\|")
            meaning = notes.get(field) or info.description or OBVIOUS.get(field, "")
            meaning = meaning.replace("|", "\\|")
            rows.append(f"| `{field}` | `{shown}` | {meaning} |")
        out.append("| Field | Type | What it is |\n|---|---|---|\n" + "\n".join(rows) + "\n")
    return "\n".join(out)
