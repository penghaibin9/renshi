from django.contrib import admin

from hr_changes.models import HrChangeAction, HrChangeFieldDefinition, HrChangeReason


@admin.register(HrChangeAction)
class HrChangeActionAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "enabled", "is_temporary", "version")
    list_filter = ("enabled", "is_temporary")
    search_fields = ("code", "name")


@admin.register(HrChangeReason)
class HrChangeReasonAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "action_code", "active", "requires_approval")
    list_filter = ("active", "action_code")
    search_fields = ("code", "name")


@admin.register(HrChangeFieldDefinition)
class HrChangeFieldDefinitionAdmin(admin.ModelAdmin):
    list_display = ("domain", "field_code", "label", "edit_mode")
    list_filter = ("domain", "edit_mode")
