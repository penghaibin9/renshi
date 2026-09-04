"""
widgets.py

This page is used to write custom form widget or override some functionalities.

"""

from django import forms
from django.templatetags.static import static
from django.utils.html import format_html

# your your widgets


class RecruitmentAjaxWidget(forms.Widget):
    """
    This widget class is used to load the ajax script for the recruitment,
    the job position and to the stage.
    """

    def render(self, name, value, attrs=None, renderer=None):
        # Exclude the label from the rendered HTML
        attrs = attrs or {}
        attrs["required"] = False
        return format_html(
            '<link rel="stylesheet" href="{}">'
            '<script src="{}"></script>'
            '<script id="{}Script">$(document).ready(function () {{'
            '$("[for=\'id_{}\']").remove();'
            '$("#{}Script").remove();}});</script>',
            static("recruitment/widget/recruitment_widget_style.css"),
            static("recruitment/widget/recruitmentAjax.js"),
            name,
            name,
            name,
        )
