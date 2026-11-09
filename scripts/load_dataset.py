"""Dataset loader script for initializing local SQLite database with benchmark attendance data."""

import argparse
import sys
from pathlib import Path

# Add backend directory to sys.path so app modules are resolvable
repo_root = Path(__file__).resolve().parents[1]
backend_dir = repo_root / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import app.models  # noqa: F401
from app.database import Base, SessionLocal, engine
from app.services.dataset_service import load_dataset_from_file


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load attendance dataset into SQLite database."
    )
    parser.add_argument(
        "--file",
        type=str,
        default=str(repo_root / "data" / "sample_attendance.json"),
        help="Path to JSON dataset file (defaults to data/sample_attendance.json)",
    )
    parser.add_argument(
        "--init-tables",
        action="store_true",
        default=True,
        help="Create tables if they do not exist (default: True)",
    )
    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.is_file():
        print(f"Error: dataset file '{file_path}' not found.", file=sys.stderr)
        sys.exit(1)

    print(f"Initializing database tables on {engine.url}...")
    Base.metadata.create_all(bind=engine)

    print(f"Loading dataset from: {file_path}")
    db = SessionLocal()
    try:
        result = load_dataset_from_file(db, file_path)
        print("Dataset ingestion complete:")
        print(f"  Newly inserted records ({result.total_inserted}):")
        print(f"    - Employees:  {result.employees_loaded}")
        print(f"    - Schedules:  {result.schedules_loaded}")
        print(f"    - Punches:    {result.punches_loaded}")
        print(f"    - Exceptions: {result.exceptions_loaded}")
        print(f"  Existing records updated ({result.total_updated}):")
        print(f"    - Employees:  {result.employees_updated}")
        print(f"    - Schedules:  {result.schedules_updated}")
        print(f"    - Punches:    {result.punches_updated}")
        print(f"    - Exceptions: {result.exceptions_updated}")
        print(f"  Records genuinely skipped (identical): {result.skipped_count}")

        if result.errors:
            print(f"\nValidation errors ({len(result.errors)}):")
            for err in result.errors:
                print(f"  [!] {err}")
            sys.exit(1)
        else:
            print("\nSuccess: Database loaded successfully.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
