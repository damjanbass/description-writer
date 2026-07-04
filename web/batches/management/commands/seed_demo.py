"""Seed a fully-populated demo batch for an organization.

Usage: python web/manage.py seed_demo <org_slug> [--username admin]
"""
from accounts.models import Organization
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from batches.demo import seed_demo_batch


class Command(BaseCommand):
    help = "Create a demo batch (fake provider, mixed statuses) for an organization."

    def add_arguments(self, parser):
        parser.add_argument("org_slug")
        parser.add_argument(
            "--username",
            default=None,
            help="User recorded as the actor (defaults to the first superuser).",
        )

    def handle(self, *args, **options):
        try:
            org = Organization.objects.get(slug=options["org_slug"])
        except Organization.DoesNotExist as exc:
            raise CommandError(f"No organization with slug '{options['org_slug']}'.") from exc

        User = get_user_model()
        if options["username"]:
            try:
                user = User.objects.get(username=options["username"])
            except User.DoesNotExist as exc:
                raise CommandError(f"No user '{options['username']}'.") from exc
        else:
            user = User.objects.filter(is_superuser=True).first()
            if user is None:
                raise CommandError("No superuser found; pass --username explicitly.")

        batch = seed_demo_batch(org, user)
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo batch '{batch.name}' (id {batch.pk}) created: "
                f"/app/{org.slug}/batches/{batch.pk}/"
            )
        )
