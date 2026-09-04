"""
Custom form widgets for conditional visibility and styling.
"""

from django import forms
from django.templatetags.static import static
from django.utils.html import format_html
from django.utils.safestring import SafeText


class AllowanceConditionalVisibility(forms.Widget):
    """
    A custom widget that loads conditional js to the form.

    Example:
    class MyForm(forms.Form):
        my_field = forms.CharField(widget=AllowanceConditionalVisibility, required=False)

    """

    def render(self, name, value, attrs=None, renderer=None):
        # Exclude the label from the rendered HTML
        attrs = attrs or {}
        attrs["required"] = False
        return format_html(
            '<script src="{}"></script>'
            '<script id="{}Script">$(document).ready(function () {{'
            '$("[for=\'id_{}\']").remove();'
            '$("#{}Script").remove();}});</script>',
            static("build/js/allowanceWidget.js"),
            name,
            name,
            name,
        )


class DeductionConditionalVisibility(forms.Widget):
    """
    A custom widget that loads conditional js to the form.

    Example:
    class MyForm(forms.Form):
        my_field = forms.CharField(widget=DeductionConditionalVisibility, required=False)

    """

    def render(self, name, value, attrs, renderer) -> SafeText:
        # Exclude the label from the rendered HTML
        attrs = attrs or {}
        attrs["required"] = False
        return format_html(
            '<script src="{}"></script>'
            '<script id="{}Script">$(document).ready(function () {{'
            '$("[for=\'id_{}\']").remove();'
            '$("#{}Script").remove();}});</script>',
            static("build/js/deductionWidget.js"),
            name,
            name,
            name,
        )


class StyleWidget(forms.Widget):
    """
    A custom widget that enhances the styling and functionality of elements.

    Example:
    class MyForm(forms.Form):
        my_field = forms.CharField(widget=styleWidget, required=False)

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.fields['style'].widget = widget.styleWidget(form=self)

    """

    def __init__(self, *args, form=None, **kwargs):
        if form is not None:
            for _, field in form.fields.items():
                field.widget.attrs.update(
                    {"data-widget": "style-widget", "class": "style-widget"}
                )
        super().__init__(*args, **kwargs)

    def render(self, name, value, attrs=None, renderer=None):
        """
        Renders the widget as HTML, including the necessary scripts and styles for select2.

        Args:
            name (str): The name of the form field.
            value (Any): The current value of the form field.
            attrs (dict, optional): Additional HTML attributes for the widget.
            renderer: A custom renderer to use, if applicable.

        Returns:
            str: The rendered HTML representation of the widget.
        """
        script_url = static("build/js/styleWidget.js")
        stylesheet_url = static("build/css/styleWidget.css")
        additional_script = """
        <script id="{}Script">
            $(document).ready(function () {{
                $("[for='id_{}']").remove()
                $("#{}Script").remove()
                // Select all select elements with select2 initialized
                var selects = $("select[data-widget='style-widget']").select2();
                function toggleSelect2() {{
                    selects.each(function() {{
                        var select = $(this);
                        var select2Container = select.nextAll(".select2.select2-container").first();
                        if (select.is(":hidden")) {{
                        select2Container.hide();
                        }} else {{
                            select2Container.show();
                        }}
                    }});
                }}
                $("select, [type='checkbox'], [type='radio']").change(function (e) {{
                    e.preventDefault();
                    toggleSelect2();
                }});
                toggleSelect2();
            }});
        </script>
        <link rel="stylesheet" type="text/css" href="{}">
        """
        attrs = attrs or {}
        attrs["required"] = False
        return format_html(
            '<script src="{}"></script>' + additional_script,
            script_url,
            name,
            name,
            name,
            stylesheet_url,
        )
