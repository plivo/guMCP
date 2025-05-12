from typing import TypedDict, cast


class CustomFieldConfig(TypedDict):
    create: bool
    view: bool
    edit: bool


CustomFields = dict[str, CustomFieldConfig]


def has_view_permission(custom_fields: CustomFields, field_id) -> bool:
    """Check if a field has 'view' permission in the configuration"""
    if not custom_fields or str(field_id) not in custom_fields:
        return False  # Not in config, so no permission
    field_config = cast(CustomFieldConfig, custom_fields.get(str(field_id), {}))
    return field_config.get("view", False)


def has_edit_permission(custom_fields: CustomFields, field_id) -> bool:
    """Check if a field has 'edit' permission in the configuration"""
    if not custom_fields or str(field_id) not in custom_fields:
        return False  # Not in config, so no permission
    field_config = cast(CustomFieldConfig, custom_fields.get(str(field_id), {}))
    return field_config.get("edit", False)


def has_create_permission(custom_fields: CustomFields, field_id) -> bool:
    """Check if a field has 'create' permission in the configuration"""
    if not custom_fields or str(field_id) not in custom_fields:
        return False  # Not in config, so no permission
    field_config = cast(CustomFieldConfig, custom_fields.get(str(field_id), {}))
    return field_config.get("create", False)
