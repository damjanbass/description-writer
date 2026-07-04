"""The in-app guide (/app/vodic/): what Korpus is and how the flow works.

Stub wired by the orchestrator; content template built by task A3.
"""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


class GuideView(LoginRequiredMixin, TemplateView):
    template_name = "guide.html"
