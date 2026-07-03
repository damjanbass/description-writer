"""Shared, app-agnostic views.

Currently just the rate-limited login view. This lives in `common` (not an
installed app of its own — it holds cross-cutting helpers like
`common.org`) so `config.urls` can wire it without depending on any single
feature app.
"""
from django.contrib.auth import views as auth_views
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit

# Serbian latinica, deliberately generic: it must NOT reveal whether the
# submitted username/account exists — only that too many attempts were made.
_RATE_LIMIT_MESSAGE = (
    "Previše pokušaja prijave. Pokušajte ponovo za nekoliko minuta."
)


def _username_ip_key(group, request):
    """Rate-limit key combining the submitted username with the client IP.

    Caps credential-stuffing against a single account from one source
    harder than the coarse per-IP limit, while still keying on IP so a
    shared username guessed from many IPs isn't locked out globally by one
    attacker. Username is normalized (lower/stripped) so trivial casing
    variations don't dodge the bucket.
    """
    username = (request.POST.get("username") or "").strip().lower()
    ip = request.META.get("REMOTE_ADDR", "") or ""
    return f"{username}|{ip}"


# Two stacked limits, POST only. django-ratelimit ORs `request.limited`
# across stacked decorators, so tripping EITHER bucket flags the request:
#   - 10/min per IP: blunt volumetric cap regardless of target account.
#   - 5/min per (username+IP): tighter cap on hammering one account.
# block=False: we never raise Ratelimited (which would 403); instead post()
# inspects request.limited and re-renders the login page with a 429 so the
# response is indistinguishable from a normal failed login attempt.
@method_decorator(
    ratelimit(key="ip", rate="10/m", method="POST", block=False),
    name="post",
)
@method_decorator(
    ratelimit(key=_username_ip_key, rate="5/m", method="POST", block=False),
    name="post",
)
class RateLimitedLoginView(auth_views.LoginView):
    """LoginView with per-IP and per-(username+IP) POST rate limiting.

    Uses the standard `registration/login.html` template unchanged. On a
    throttled request it returns HTTP 429 with the login form carrying a
    generic non-field error, never disclosing whether the account exists.
    """

    def post(self, request, *args, **kwargs):
        if getattr(request, "limited", False):
            form = self.get_form()
            form.add_error(None, _RATE_LIMIT_MESSAGE)
            return self.render_to_response(
                self.get_context_data(form=form), status=429
            )
        return super().post(request, *args, **kwargs)
