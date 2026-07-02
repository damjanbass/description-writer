"""Admin for connector credentials.

The secret material must never be echoed back to the browser. The encrypted
columns (``key_encrypted`` / ``secret_encrypted``) are excluded from the form
entirely; instead the form exposes two write-only password fields whose
values are encrypted through the model setters on save. ``render_value=False``
guarantees the change form never re-renders a previously stored value.
"""
from __future__ import annotations

from django import forms
from django.contrib import admin

from .models import ConnectorCredential


class ConnectorCredentialForm(forms.ModelForm):
    """ModelForm exposing write-only credential inputs.

    ``consumer_key``/``consumer_secret`` are extra password fields, not model
    fields — the encrypted columns are excluded so plaintext never binds to a
    persisted attribute except through the encrypting setters. On add the key
    is required; on change both are optional ("leave blank to keep current").
    """

    consumer_key = forms.CharField(
        label="Consumer key",
        widget=forms.PasswordInput(render_value=False),
        required=False,
        help_text="Leave blank to keep the current value.",
    )
    consumer_secret = forms.CharField(
        label="Consumer secret",
        widget=forms.PasswordInput(render_value=False),
        required=False,
        help_text="Leave blank to keep the current value.",
    )

    class Meta:
        model = ConnectorCredential
        # Encrypted columns are intentionally NOT form fields.
        fields = ("organization", "connector_type", "label", "base_url")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # On add (no PK yet) the consumer key is mandatory; on change it may be
        # left blank to preserve the stored ciphertext.
        if self.instance is None or self.instance.pk is None:
            self.fields["consumer_key"].required = True
            self.fields["consumer_key"].help_text = ""

    def save(self, commit: bool = True):
        instance = super().save(commit=False)
        # Only overwrite stored credentials when a new value was actually
        # entered; a blank password field means "keep current".
        raw_key = self.cleaned_data.get("consumer_key")
        if raw_key:
            instance.set_consumer_key(raw_key)
        raw_secret = self.cleaned_data.get("consumer_secret")
        if raw_secret:
            instance.set_consumer_secret(raw_secret)
        if commit:
            instance.save()
            self.save_m2m()
        return instance


@admin.register(ConnectorCredential)
class ConnectorCredentialAdmin(admin.ModelAdmin):
    form = ConnectorCredentialForm
    # Never surface any secret material in the changelist.
    list_display = ("organization", "label", "connector_type", "created_at")
    list_filter = ("connector_type", "organization")
    search_fields = ("label",)
    readonly_fields = ("created_at",)
