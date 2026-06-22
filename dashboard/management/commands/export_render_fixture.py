import json
import os
from collections import Counter
from io import StringIO

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Export local dashboard + auth data to fixture.json for Render deploys."

    def add_arguments(self, parser):
        parser.add_argument(
            "-o", "--output",
            default="fixture.json",
            help="Output fixture path (default: fixture.json)",
        )

    def handle(self, *args, **options):
        output = os.path.abspath(options["output"])

        self.stdout.write("Dumping dashboard + auth.user …")
        buffer = StringIO()
        call_command(
            "dumpdata",
            "dashboard",
            "auth.user",
            indent=0,
            stdout=buffer,
        )
        data = json.loads(buffer.getvalue())

        DATE_FIELDS = {
            "dashboard.soilmetrics": ["measurement_date"],
            "dashboard.climatemetrics": ["measurement_date"],
            "dashboard.droughtindices": ["measurement_date"],
            "dashboard.agriculturalmetrics": ["measurement_date"],
            "dashboard.remotesensingmetrics": ["measurement_date"],
            "dashboard.hydrologymetrics": ["measurement_date"],
        }

        DATETIME_FIELDS = {
            "dashboard.dataimportlog": ["import_date"],
        }

        def _normalize_date(value):
            if not isinstance(value, str) or not value:
                return value
            if "T" in value:
                return value.split("T", 1)[0]
            return value

        def _normalize_datetime(value):
            if not isinstance(value, str) or not value:
                return value
            if value.endswith("Z"):
                return value[:-1] + "+00:00"
            if "T" in value and "+" not in value and not value.endswith("Z"):
                return value + "+00:00"
            return value

        for obj in data:
            for field in DATE_FIELDS.get(obj["model"], []):
                if field in obj["fields"] and obj["fields"][field]:
                    obj["fields"][field] = _normalize_date(obj["fields"][field])
            for field in DATETIME_FIELDS.get(obj["model"], []):
                if field in obj["fields"] and obj["fields"][field]:
                    obj["fields"][field] = _normalize_datetime(obj["fields"][field])

        # PostgreSQL enforces unique (region, year) on EnvironmentalSnapshot;
        # keep the latest row per pair when SQLite allowed duplicates locally.
        best_snapshots = {}
        rest = []
        removed = 0
        for obj in data:
            if obj["model"] == "dashboard.environmentalsnapshot":
                key = (obj["fields"]["region"], obj["fields"]["year"])
                prev = best_snapshots.get(key)
                if prev is None or obj["pk"] > prev["pk"]:
                    if prev is not None:
                        removed += 1
                    best_snapshots[key] = obj
                else:
                    removed += 1
            else:
                rest.append(obj)

        if removed:
            self.stdout.write(
                self.style.WARNING(
                    f"Deduplicated {removed} EnvironmentalSnapshot row(s) for PostgreSQL."
                )
            )

        merged = rest + list(best_snapshots.values())
        with open(output, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, ensure_ascii=False, separators=(",", ":"))

        size_mb = os.path.getsize(output) / (1024 * 1024)
        counts = Counter(obj["model"] for obj in merged)
        self.stdout.write(self.style.SUCCESS(f"Wrote {output} ({size_mb:.1f} MB, {len(merged)} records)"))
        for model, count in sorted(counts.items()):
            self.stdout.write(f"  {model}: {count}")
