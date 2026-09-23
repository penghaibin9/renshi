"""Repository-clean boundary for the V16 canonical Chinese HR frontend."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HR_BASE = ROOT / "frontend/templates/hr/base.html"
HR_HEADER = ROOT / "frontend/templates/hr/components/header_clean_v16.html"
SETTINGS = ROOT / "backend/horilla/settings/base.py"
HR_URLS = ROOT / "backend/horilla/hr_urls.py"
LANG_MW = ROOT / "backend/horilla/canonical_hr_language.py"


def canonical_templates():
    yield from (ROOT / "frontend/templates/hr").rglob("*.html")
    for app in (ROOT / "backend").glob("hr_*"):
        template_dir = app / "templates"
        if template_dir.exists():
            yield from template_dir.rglob("*.html")


def test_no_canonical_hr_template_inherits_cloned_index_shell():
    offenders = []
    for path in canonical_templates():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r'{%\\s*extends\\s+["\\\']index\\.html["\\\']\\s*%}', text):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_canonical_shell_contains_only_hr_navigation_not_legacy_escape_components():
    text = HR_BASE.read_text(encoding="utf-8") + HR_HEADER.read_text(encoding="utf-8")
    required = [
        'hr/components/sidebar_brand_v16.html',
        'hr/components/module_sidebar.html',
        'hr/components/header_breadcrumb.html',
        'hr/components/page_search_v16.html',
        'hr-shell-clean-v16.css',
        'hr-shell-clean-v16.js',
    ]
    for token in required:
        assert token in text
    forbidden = [
        'floating_button.html',
        'attendance/components/in_out_component.html',
        'language_settings.html',
        'company_selection.html',
        'base/navbar_components/profile_section.html',
        "url 'employee-profile'",
        "url 'change-username'",
        "url 'change-password'",
    ]
    for token in forbidden:
        assert token not in text


def test_language_firewall_runs_after_django_locale_and_covers_hr_settings():
    settings = SETTINGS.read_text(encoding="utf-8")
    assert settings.index("django.middleware.locale.LocaleMiddleware") < settings.index("CanonicalHrLanguageMiddleware")
    assert 'HR_CANONICAL_LANGUAGE = "zh-hans"' in settings
    middleware = LANG_MW.read_text(encoding="utf-8")
    for prefix in ('/hr/', '/recruit/', '/settings/'):
        assert prefix in middleware


def test_high_risk_old_shell_utility_entries_do_not_win_over_canonical_surface():
    urls = HR_URLS.read_text(encoding="utf-8")
    assert 'path("settings/", RedirectView.as_view(pattern_name="system-admin-center"' in urls
    assert 'path("notifications/", RedirectView.as_view(url="/hr/todos"' in urls


def test_system_admin_landing_uses_clean_shell_and_known_business_cards_go_canonical():
    path = ROOT / "backend/base/templates/base/settings/system_admin_center.html"
    text = path.read_text(encoding="utf-8")
    assert "{% extends 'hr/base.html' %}" in text
    assert 'href="/hr/staff/"' in text
    assert 'href="/hr/structure/organizations"' in text
    assert 'href="/hr/structure/post-catalogs"' in text


def test_legacy_shells_are_explicitly_quarantined_in_source():
    legacy_index = (ROOT / "backend/horilla_theme/templates/index.html").read_text(encoding="utf-8")
    fallback_index = (ROOT / "frontend/templates/index.html").read_text(encoding="utf-8")
    assert legacy_index.startswith("{# LEGACY NON-HR SHELL")
    assert fallback_index.startswith("{# LEGACY FALLBACK SNAPSHOT")
