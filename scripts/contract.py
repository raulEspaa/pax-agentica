"""Write the frozen contract between the game and its rulers to disk.

    make contract

Writes the JSON schemas of `NationView` and `Orders` to `docs/contract/`, the version and the
fingerprint to `docs/contract/CONTRACT.lock`, and the generated references (every order, every
field of the view) into `docs/agent-contract.md`, between its markers. `tests/test_contract.py`
fails while any of them disagrees with the code: change the contract on purpose, bump
`CONTRACT_VERSION` in `engine/contract.py`, run this, and note the change in the changelog.
"""

import json
from pathlib import Path

from pax_agentica.engine.contract import (
    CONTRACT_VERSION,
    action_types,
    canonical,
    contract_fingerprint,
    contract_schemas,
    orders_reference,
    view_reference,
)

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "docs" / "contract"
DOC = ROOT / "docs" / "agent-contract.md"


def lock() -> dict[str, object]:
    return {
        "version": CONTRACT_VERSION,
        "fingerprint": contract_fingerprint(),
        "orders": [t.model_fields["type"].default for t in action_types()],
    }


def splice(text: str, name: str, body: str) -> str:
    """Put `body` between the `<!-- name:begin -->` and `<!-- name:end -->` markers."""
    begin, end = f"<!-- {name}:begin -->", f"<!-- {name}:end -->"
    head, rest = text.split(begin)
    _, tail = rest.split(end)
    return f"{head}{begin}\n\n{body.strip()}\n\n{end}{tail}"


def main() -> None:
    FOLDER.mkdir(parents=True, exist_ok=True)
    for name, schema in contract_schemas().items():
        (FOLDER / f"{name}.schema.json").write_text(canonical(schema), encoding="utf-8")
    (FOLDER / "CONTRACT.lock").write_text(canonical(lock()), encoding="utf-8")
    text = DOC.read_text(encoding="utf-8")
    text = splice(text, "orders", orders_reference())
    text = splice(text, "view", view_reference())
    DOC.write_text(text, encoding="utf-8")
    print(f"contract {CONTRACT_VERSION}, fingerprint {json.dumps(contract_fingerprint())}")


if __name__ == "__main__":
    main()
