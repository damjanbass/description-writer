"""One-click demo data: a realistic, fully-populated batch for a fresh org.

`seed_demo_batch` runs the REAL pipeline (FakeProvider — no LLM cost, no
API key) over the same sample catalog users can download from the upload
screen, then applies a demonstrative status mix so every screen in the app
has something to show: pending, approved, rejected (with a reason),
published, and at least one needs-review item with an unsupported claim.

The status mix goes through the model transition methods (`approve`,
`reject`, `mark_published`) so real AuditLog rows exist — this is fixture
data for exploration and sales demos, not a bypass of the review flow.

Called synchronously from both the `seed_demo` management command and
`DemoSeedView`; the fake provider makes generation near-instant, so no
background task is needed.
"""
from __future__ import annotations

from pathlib import Path

from django.core.files.base import ContentFile

from . import tasks
from .models import Batch

# Single source of truth: the downloadable sample and the demo batch use the
# literal same file.
SAMPLE_CSV_PATH = Path(__file__).resolve().parents[1] / "static" / "samples" / "korpus-primer.csv"

_DEMO_NAME = "Demo serija"

_REJECT_REASON = "Primer odbijene stavke — pogrešan rod prideva."

# Injected into one pending item so the amber "NEMA IZVORA" provenance state
# is always demonstrable regardless of what the fake provider produced.
_UNSUPPORTED_ENTRY = {
    "sentence": "Otporna na vodu do 50 m.",
    "supporting_attributes": [],
    "supported": False,
}


def _unique_demo_name(org) -> str:
    name = _DEMO_NAME
    counter = 2
    while Batch.objects.filter(organization=org, name=name).exists():
        name = f"{_DEMO_NAME} ({counter})"
        counter += 1
    return name


def seed_demo_batch(org, user) -> Batch:
    """Create and fully populate a demo batch for `org`. Returns the batch."""
    batch = Batch.objects.create(
        organization=org,
        name=_unique_demo_name(org),
        provider=Batch.Provider.FAKE,
        created_by=user,
    )
    batch.source_file.save(
        "korpus-primer.csv", ContentFile(SAMPLE_CSV_PATH.read_bytes()), save=True
    )

    tasks.run_generation(batch.pk)
    batch.refresh_from_db()

    items = list(batch.items.order_by("product_id"))
    if len(items) >= 5:
        items[0].approve(user)
        items[1].approve(user)
        items[2].reject(user, _REJECT_REASON)
        items[3].approve(user)
        items[3].mark_published()

        # Guarantee one pending item demonstrates the flagged/unsupported
        # state (demo fixture data, clearly not produced by the checker).
        flagged = items[4]
        provenance = dict(flagged.provenance or {"is_clean": True, "entries": []})
        provenance["entries"] = list(provenance.get("entries", [])) + [_UNSUPPORTED_ENTRY]
        provenance["is_clean"] = False
        flagged.provenance = provenance
        flagged.needs_review = True
        flagged.save(update_fields=["provenance", "needs_review"])

        batch.needs_review_count = batch.items.filter(needs_review=True).count()
        batch.save(update_fields=["needs_review_count"])

    return batch
