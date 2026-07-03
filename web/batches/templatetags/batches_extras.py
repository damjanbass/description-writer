"""Template filters for the batches app: status -> badge label/class.

Fixed vocabulary (per doc/CLAUDE.md-style contract, see `views.py`'s
module docstring): ReviewItem statuses map to
pending->"NA CEKANJU"/badge-pending, approved->"ODOBRENO"/badge-approved,
rejected->"ODBIJENO"/badge-rejected, published->"OBJAVLJENO"/badge-published.
Batch statuses get an analogous (not spec-fixed, but consistent) mapping
onto the same badge classes so the two status vocabularies read the same way
in templates.

Kept as filters (not view-context dicts) because both batch_list.html and
review templates need the same lookup for two different status
enumerations, and "no logic in templates beyond simple lookups" is the goal.
"""
from __future__ import annotations

from django import template

from batches.models import Batch, ReviewItem

register = template.Library()

_ITEM_STATUS_BADGES = {
    ReviewItem.Status.PENDING: ("NA ČEKANJU", "badge-pending"),
    ReviewItem.Status.APPROVED: ("ODOBRENO", "badge-approved"),
    ReviewItem.Status.REJECTED: ("ODBIJENO", "badge-rejected"),
    ReviewItem.Status.PUBLISHED: ("OBJAVLJENO", "badge-published"),
}

_BATCH_STATUS_BADGES = {
    Batch.Status.UPLOADED: ("UČITANO", "badge-pending"),
    Batch.Status.RUNNING: ("U TOKU", "badge-pending"),
    Batch.Status.COMPLETED: ("ZAVRŠENO", "badge-approved"),
    Batch.Status.FAILED: ("NEUSPEŠNO", "badge-rejected"),
}


@register.filter
def item_status_label(status):
    return _ITEM_STATUS_BADGES.get(status, (status, "badge-pending"))[0]


@register.filter
def item_status_class(status):
    return _ITEM_STATUS_BADGES.get(status, (status, "badge-pending"))[1]


@register.filter
def batch_status_label(status):
    return _BATCH_STATUS_BADGES.get(status, (status, "badge-pending"))[0]


@register.filter
def batch_status_class(status):
    return _BATCH_STATUS_BADGES.get(status, (status, "badge-pending"))[1]
