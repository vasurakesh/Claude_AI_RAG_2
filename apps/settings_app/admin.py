from django.contrib import admin
from .models import SettingCategory, PlatformSetting


class PlatformSettingInline(admin.TabularInline):
    model = PlatformSetting
    extra = 0
    fields = ("key", "value", "data_type", "is_sensitive", "is_editable", "description")
    readonly_fields = ("key",)


@admin.register(SettingCategory)
class SettingCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "order", "created_at")
    ordering = ("order", "name")
    inlines = [PlatformSettingInline]


@admin.register(PlatformSetting)
class PlatformSettingAdmin(admin.ModelAdmin):
    list_display = ("key", "masked_value", "data_type", "category", "is_editable", "is_sensitive")
    list_filter = ("data_type", "category", "is_sensitive", "is_editable")
    search_fields = ("key", "description")
    readonly_fields = ("created_at", "modified_at")

    @admin.display(description="Value")
    def masked_value(self, obj):
        return "***" if obj.is_sensitive else obj.value[:80]

    def get_readonly_fields(self, request, obj=None):
        if obj and not obj.is_editable:
            return self.readonly_fields + ("key", "value", "data_type")
        return self.readonly_fields
