#!/usr/bin/env python3
"""Restore Nyan Wallet's ZIP/CSV backup into a NEW, EMPTY PostgreSQL database.

Use NYAN_RESTORE_SCHEMA_ONLY=1 so importing models never runs Telegram sends,
payments, one-shot grants, notifications or other application startup actions.
The data COPY is one PostgreSQL transaction: failures roll back every imported row.
"""
import argparse
import csv
import io
import os
import sys
import zipfile
from pathlib import Path

# A script executed from tools/ must still import the parent server/ package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import Integer, inspect
from sqlalchemy.types import LargeBinary


def stop(reason):
    raise SystemExit("RESTORE STOPPED: " + reason)


def restore(path, preview):
    if os.environ.get("NYAN_RESTORE_SCHEMA_ONLY") != "1":
        stop("NYAN_RESTORE_SCHEMA_ONLY must be 1")
    if not os.getenv("DATABASE_URL"):
        stop("DATABASE_URL missing")
    if not path.is_file():
        stop("ZIP not found: " + str(path))

    # All models are imported; only the schema is created.
    from server import backend_app as core

    if core.engine.url.database != "nyan_wallet_db":
        stop("Refusing a target database other than nyan_wallet_db")
    if core.engine.url.host not in ("127.0.0.1", "localhost", None):
        stop("Target must be local PostgreSQL")

    metadata = core.Base.metadata
    db_tables = metadata.tables
    catalog = inspect(core.engine)
    csv.field_size_limit(sys.maxsize)

    with zipfile.ZipFile(path, "r") as archive:
        corrupt = archive.testzip()
        if corrupt:
            stop("ZIP is corrupt: " + corrupt)
        try:
            manifest = archive.read("manifest.txt").decode("utf-8")
        except KeyError:
            stop("Missing backup manifest")
        if "Nyan Wallet automatic backup" not in manifest:
            stop("Unexpected backup format")

        tables = [
            name[7:-4] for name in archive.namelist()
            if name.startswith("tables/") and name.endswith(".csv")
        ]
        if len(tables) != 72 or len(set(tables)) != 72:
            stop("Expected 72 unique CSV files, found " + str(len(tables)))
        if set(tables) != set(db_tables):
            stop("Table mismatch, missing in schema: " + str(sorted(set(tables) - set(db_tables)))
                 + "; missing in ZIP: " + str(sorted(set(db_tables) - set(tables))))
        headers = {}
        for table in tables:
            with archive.open("tables/" + table + ".csv") as source:
                reader = csv.reader(io.TextIOWrapper(source, encoding="utf-8-sig", newline=""))
                columns = next(reader, [])
            if columns != [col.name for col in db_tables[table].columns]:
                stop("CSV header/model mismatch: " + table)
            actual_columns = {col["name"] for col in catalog.get_columns(table)}
            if actual_columns != set(columns):
                stop("Postgres column mismatch: " + table)
            headers[table] = columns

        print("ZIP OK; 72 tables and database schema match.", flush=True)
        with core.engine.connect() as connection:
            occupied = [
                table for table in tables
                if connection.exec_driver_sql('SELECT EXISTS(SELECT 1 FROM "' + table + '" LIMIT 1)').scalar()
            ]
        if occupied:
            stop("Destination has existing rows, NO changes made: " + ", ".join(occupied))
        if preview:
            print("PREVIEW OK: database empty; no backup rows imported.")
            return

        counts = {}
        with core.engine.begin() as connection:
            driver = connection.connection.driver_connection
            for table in tables:
                header = headers[table]
                columns = db_tables[table].columns
                binary = {
                    col.name for col in db_tables[table].columns
                    if isinstance(col.type, LargeBinary)
                }
                sqlcols = ", ".join('"' + col + '"' for col in header)
                command = 'COPY "' + table + '" (' + sqlcols + ') FROM STDIN'
                count = 0
                with archive.open("tables/" + table + ".csv") as source:
                    reader = csv.DictReader(
                        io.TextIOWrapper(source, encoding="utf-8-sig", newline="")
                    )
                    with driver.cursor() as cursor:
                        with cursor.copy(command) as copy:
                            for record in reader:
                                if None in record or record.keys() != set(header):
                                    stop("Unexpected CSV columns: " + table)
                                values = []
                                for name in header:
                                    raw = record[name]
                                    col = columns[name]
                                    if raw == "" and col.nullable:
                                        value = None
                                    elif name in binary:
                                        value = bytes.fromhex(raw)
                                    else:
                                        value = raw
                                    values.append(value)
                                copy.write_row(values)
                                count += 1
                counts[table] = count
                print(table + ": " + str(count), flush=True)

            # Restore SERIAL/IDENTITY counters, so new inserts cannot collide.
            for table in tables:
                for col in db_tables[table].columns:
                    auto = col.autoincrement is True or (
                        col.autoincrement == "auto"
                        and col.primary_key and isinstance(col.type, Integer)
                    )
                    if not auto or not counts[table]:
                        continue
                    seq = connection.exec_driver_sql(
                        "SELECT pg_get_serial_sequence(%s, %s)",
                        ("public." + table, col.name),
                    ).scalar()
                    if seq:
                        maximum = connection.exec_driver_sql(
                            'SELECT MAX("' + col.name + '") FROM "' + table + '"'
                        ).scalar_one()
                        connection.exec_driver_sql(
                            "SELECT setval(%s::regclass, %s, true)", (seq, maximum)
                        )

            for table, expected in counts.items():
                actual = connection.exec_driver_sql(
                    'SELECT COUNT(*) FROM "' + table + '"'
                ).scalar_one()
                if actual != expected:
                    stop("Count mismatch: " + table)
            if counts.get("users") != 312 or counts.get("transactions") != 5249:
                stop("Critical user or transaction counts did not match the backup")
            print("Validated all rows, committing transaction...", flush=True)
        print("RESTORE COMPLETE: 72 tables, PostgreSQL transaction committed.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    restore(args.archive, args.preview)
