"""Base Pydantic model configuring camelCase alias serialization."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base model that generates camelCase aliases for JSON serialization.

    Attributes in Python remain idiomatic snake_case (e.g. employee_id),
    while public API JSON output uses camelCase (e.g. employeeId).
    Setting populate_by_name=True ensures incoming requests can accept
    either snake_case or camelCase.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )
