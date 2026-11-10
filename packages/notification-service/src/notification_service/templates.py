"""
Template registry for alert and runbook notifications.

FILE HEADER
-----------
Business problem this file solves:
    Email, Slack, SMS, and push notifications share recurring message shapes (severity banners,
    runbook steps, event context). A template registry lets operators define and render those
    messages by name instead of hardcoding text in every channel, keeping notifications
    consistent and easy to update.

Where it sits in the flow:
    Rendering layer. PushChannel (and potentially other channels) call TemplateRegistry.render()
    to turn a notification's template_name + context into a message body before delivery.

What calls it / what it calls:
    Called by: channels/push.py, router tests, consumers.
    Calls: jinja2 if installed, else stdlib string formatting.

What breaks if removed:
    Template-based rendering falls back to raw notification.body; named templates are
    unavailable.

Language conventions:
    Python 3.11+. render(name, context) -> str. Uses Jinja2 when available and falls back to
    str.format so the module is dependency-free by default.
"""
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Matches Jinja2-style {{ var }} placeholders for the str.format fallback.
_VAR_RE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")

try:  # pragma: no cover - jinja2 is optional
    from jinja2 import Environment, BaseUndefined

    _HAS_JINJA2 = True
except Exception:  # pragma: no cover - jinja2 not installed
    _HAS_JINJA2 = False


# Default alert/runbook templates. Operators can override by registering new templates.
DEFAULT_TEMPLATES: Dict[str, str] = {
    "alert": "Alert: {{ subject }}\nSeverity: {{ severity }}\n{{ body }}",
    "alert_page": "PAGE: {{ subject }}\nSeverity: {{ severity }}\n{{ body }}",
    "runbook": "Runbook: {{ subject }}\nSteps:\n{% for step in steps %}- {{ step }}{% endfor %}\n{{ body }}",
    "runbook_short": "Runbook {{ subject }}: {{ body }}",
}


class TemplateRegistry:
    """Registry of named notification templates.

    WHAT: Holds name -> template-string mappings and renders a template with a context dict.
        Uses Jinja2 when installed, otherwise a small str.format-based formatter.
    WHY: One place to manage notification message templates; channels render by name instead of
        duplicating message text.
    EXAMPLE:
        registry = TemplateRegistry()
        body = registry.render("alert_page", {"subject": "Down", "severity": "page",
                                              "body": "DB is unreachable"})
    INPUTS: render receives a template name and a context dict.
    OUTPUTS: rendered string.
    SIDE EFFECTS: none.
    FAILURE MODES: unknown template name -> returns the name unchanged (fallback); render error
        -> logged and the raw template returned as a last resort.
    ALTERNATIVE: load templates from files/Jinja2 FileSystemLoader. Chosen an in-memory registry
        for zero file dependencies and simple tests.
    """

    def __init__(self, templates: Optional[Dict[str, str]] = None) -> None:
        self._templates: Dict[str, str] = dict(DEFAULT_TEMPLATES)
        if templates:
            self._templates.update(templates)
        self._env = Environment(undefined=BaseUndefined) if _HAS_JINJA2 else None

    def register(self, name: str, template: str) -> None:
        """Register (or override) a named template.

        WHAT: Adds name -> template to the registry.
        WHY: Operators/tests can inject custom templates without subclassing.
        INPUTS: name (str), template (str).
        OUTPUTS: none.
        SIDE EFFECTS: mutates the registry.
        FAILURE MODES: none.
        """
        self._templates[name] = template

    def render(self, name: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Render a named template with the given context.

        WHAT: Looks up name in the registry and renders it with context. Falls back to str.format
            when Jinja2 is unavailable, and returns the name unchanged when the template is
            unknown.
        WHY: Deterministic, dependency-free rendering by default with an optional Jinja2 upgrade.
        INPUTS: name (str), context (dict, optional).
        OUTPUTS: rendered string.
        SIDE EFFECTS: none.
        FAILURE MODES: unknown template -> name returned unchanged; render error -> logged and
            the raw template returned as a fallback.
        ALTERNATIVE: raise KeyError on unknown template. Chosen a graceful fallback so a missing
            template never blocks delivery.
        """
        context = context or {}
        template = self._templates.get(name)
        if template is None:
            logger.warning("Unknown template %r; returning name as body", name)
            return name

        if self._env is not None:
            try:
                return self._env.from_string(template).render(**context)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Jinja2 render failed for %r: %s", name, exc)

        # Fallback: Jinja2-style {{ var }} substitution (no str.format braces needed),
        # leaving unknown placeholders intact so a missing key never blocks delivery.
        try:
            return _VAR_RE.sub(
                lambda m: str(context.get(m.group(1), m.group(0))), template
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Template render failed for %r: %s", name, exc)
            return template
