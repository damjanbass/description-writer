"""Forms for the batches app.

Two forms: `BatchUploadForm` (a `Batch` ModelForm driving the upload screen)
and `BatchPublishForm` (a plain Form driving the publish screen, since its
`credential` queryset must be scoped to one organization at construction
time -- see `views.BatchPublishView`).
"""
from __future__ import annotations

from pathlib import Path

from connections.models import ConnectorCredential
from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator

from .models import Batch

# Mirrors config/settings/base.py's DATA_UPLOAD_MAX_MEMORY_SIZE (that setting
# excludes file-upload data per Django's docs, so it does not itself cap
# `source_file` -- this is the real enforcement of the 50 MB upload cap).
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB

_PROVIDER_LABELS = {
    Batch.Provider.FAKE: "Test (bez LLM)",
    Batch.Provider.ANTHROPIC: "Anthropic",
}


class BatchUploadForm(forms.ModelForm):
    """New-batch upload form: catalog file + generation settings.

    `name` is optional -- if left blank, `clean()` defaults it to the
    uploaded file's stem, so a user who doesn't bother naming the batch still
    gets something sensible in the batch list. (The template also offers a
    small JS auto-fill on file selection, for the common "notices the field
    still says the default" case -- but the server-side fallback here is what
    actually guarantees a non-empty name.)
    """

    class Meta:
        model = Batch
        fields = ["name", "source_file", "source_script", "provider", "model"]
        labels = {
            "name": "Naziv serije",
            "source_file": "Katalog (CSV ili XLSX)",
            "source_script": "Izvorno pismo",
            "provider": "Provajder",
            "model": "Model (opciono)",
        }
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "input", "placeholder": "npr. Jesenja kolekcija"}
            ),
            "source_file": forms.ClearableFileInput(attrs={"class": "input"}),
            "source_script": forms.Select(attrs={"class": "select"}),
            "provider": forms.Select(attrs={"class": "select"}),
            "model": forms.TextInput(
                attrs={"class": "input", "placeholder": "podrazumevani model"}
            ),
        }
        help_texts = {
            "name": "Interni naziv, samo za vas. Ako ga izostavite, koristi se ime fajla.",
            "source_file": "CSV ili XLSX do 50 MB. Svaki red je jedan proizvod sa atributima.",
            "source_script": "Pismo u kojem su UNETI podaci — oba pisma se uvek generišu.",
            "provider": (
                "„Test (bez LLM)“ pravi demo opise bez troška — idealno za probu. "
                "„Anthropic“ koristi pravi AI model."
            ),
            "model": "Ostavite prazno za podrazumevani model.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].required = False
        self.fields["model"].required = False
        self.fields["source_file"].validators.append(
            FileExtensionValidator(allowed_extensions=["csv", "xlsx"])
        )
        self.fields["provider"].choices = [
            (value, _PROVIDER_LABELS[value]) for value in Batch.Provider.values
        ]

    def clean_source_file(self):
        source_file = self.cleaned_data["source_file"]
        if source_file.size > MAX_UPLOAD_SIZE:
            raise ValidationError("Fajl je prevelik (maksimalno 50 MB).")
        return source_file

    def clean(self):
        cleaned = super().clean()
        source_file = cleaned.get("source_file")
        if not cleaned.get("name") and source_file:
            cleaned["name"] = Path(source_file.name).stem or source_file.name
        return cleaned


class BatchPublishForm(forms.Form):
    """Publish-screen form: which store credential + which script to push.

    `credential`'s queryset is scoped to one organization at construction
    time (`org=` kwarg, required) -- this is the tenancy boundary for
    publishing: a credential id from another organization is simply not a
    valid choice, so Django's own ModelChoiceField validation refuses it
    before the view logic even runs (the view re-asserts this belt-and-braces
    in `form_valid`).
    """

    credential = forms.ModelChoiceField(
        queryset=ConnectorCredential.objects.none(),
        label="Prodavnica",
        widget=forms.Select(attrs={"class": "select"}),
    )
    publish_script = forms.ChoiceField(
        choices=Batch.SourceScript.choices,
        label="Pismo za objavu",
        widget=forms.Select(attrs={"class": "select"}),
    )

    def __init__(self, *args, org=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = ConnectorCredential.objects.none()
        if org is not None:
            queryset = ConnectorCredential.objects.filter(organization=org).order_by("label")
        self.fields["credential"].queryset = queryset
