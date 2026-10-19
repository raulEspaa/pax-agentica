"""The contract between the game and its rulers is frozen: the schemas, the lock and the
references on disk must say exactly what the code says, and every view carries the version."""

import json
import re
from pathlib import Path

from pax_agentica.engine import Orders, new_game, view_for
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
DOC = (ROOT / "docs" / "agent-contract.md").read_text(encoding="utf-8")
HOW = (
    "The agent contract changed. If you meant it: bump CONTRACT_VERSION in engine/contract.py "
    "(major if an old ruler could break, minor if you only added), run `make contract`, and add "
    "a line to the changelog in docs/agent-contract.md."
)


def between(name: str) -> str:
    return DOC.split(f"<!-- {name}:begin -->")[1].split(f"<!-- {name}:end -->")[0].strip()


def test_the_schemas_on_disk_are_the_code_s() -> None:
    for name, schema in contract_schemas().items():
        kept = (FOLDER / f"{name}.schema.json").read_text(encoding="utf-8")
        assert kept == canonical(schema), f"{name}: {HOW}"


def test_the_lock_holds_the_version_and_the_fingerprint() -> None:
    lock = json.loads((FOLDER / "CONTRACT.lock").read_text(encoding="utf-8"))
    assert lock["fingerprint"] == contract_fingerprint(), HOW
    assert lock["version"] == CONTRACT_VERSION, HOW
    assert lock["orders"] == [t.model_fields["type"].default for t in action_types()], HOW


def test_the_references_in_the_doc_are_the_code_s() -> None:
    assert between("orders") == orders_reference().strip(), HOW
    assert between("view") == view_reference().strip(), HOW


def test_the_doc_and_every_view_carry_the_version() -> None:
    assert f"**Version {CONTRACT_VERSION}**" in DOC
    assert f"- **{CONTRACT_VERSION}**" in DOC  # its line in the changelog
    assert view_for(new_game(1), "france").contract == CONTRACT_VERSION


def test_the_example_year_in_the_doc_is_valid_orders() -> None:
    example = re.search(r"## An example year.*?```json\n(.*?)```", DOC, re.S)
    assert example is not None
    orders = Orders.model_validate_json(example.group(1))
    assert [a.type for a in orders.actions] == [
        "develop",
        "research",
        "propose_marriage",
        "send_message",
    ]
