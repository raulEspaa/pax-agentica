"""Print the BigQuery DDL for the analytics external tables, from the schemas in scripts/bigquery/.

    python3 scripts/bigquery_ddl.py --project P --dataset pax_analytics --bucket B

One `CREATE OR REPLACE EXTERNAL TABLE` per kind (idempotent), over the NDJSON files the tables
server writes to gs://B/analytics/<kind>/dt=YYYY-MM-DD/*.ndjson, with `dt` as a Hive partition
column. Standard library only, so it runs anywhere `bq` does. See docs/analytics.md.
"""

import argparse
import json
from pathlib import Path
from typing import Any

SCHEMAS = Path(__file__).parent / "bigquery"
KINDS = ("games", "decisions", "audience")
TYPES = {"INTEGER": "INT64", "FLOAT": "FLOAT64", "BOOLEAN": "BOOL"}  # legacy names to SQL


def column_type(field: dict[str, Any]) -> str:
    if field["type"] == "RECORD":
        inner = ", ".join(f"`{f['name']}` {column_type(f)}" for f in field["fields"])
        kind = f"STRUCT<{inner}>"
    else:
        kind = TYPES.get(field["type"], field["type"])
    return f"ARRAY<{kind}>" if field.get("mode") == "REPEATED" else kind


def ddl(kind: str, project: str, dataset: str, bucket: str) -> str:
    fields = json.loads((SCHEMAS / f"{kind}.json").read_text(encoding="utf-8"))
    columns = ",\n".join(f"  `{f['name']}` {column_type(f)}" for f in fields)
    prefix = f"gs://{bucket}/analytics/{kind}"
    return (
        f"CREATE OR REPLACE EXTERNAL TABLE `{project}.{dataset}.{kind}` (\n{columns}\n)\n"
        "WITH PARTITION COLUMNS (dt DATE)\n"
        "OPTIONS (\n"
        "  format = 'NEWLINE_DELIMITED_JSON',\n"
        f"  uris = ['{prefix}/*'],\n"
        f"  hive_partition_uri_prefix = '{prefix}',\n"
        "  ignore_unknown_values = TRUE\n"
        ");\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Print the analytics external tables DDL.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--dataset", default="pax_analytics")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--kind", choices=KINDS, action="append", help="default: every kind")
    args = parser.parse_args()
    print("\n".join(ddl(k, args.project, args.dataset, args.bucket) for k in args.kind or KINDS))


if __name__ == "__main__":
    main()
