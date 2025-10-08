from datetime import datetime
from enum import Enum

from pydantic import BaseModel, HttpUrl, field_validator, Field


# --- TTL Options ---
class TTL(str, Enum):
    ONE_HOUR = "1h"
    ONE_DAY = "1d"
    ONE_WEEK = "1w"
    NEVER = "never"


# --- Pydantic Models ---
class LinkBase(BaseModel):
    long_url: HttpUrl = Field(..., example="https://github.com/fastapi/fastapi",
                              description="The original, long URL to be shortened.")
    ttl: TTL = Field(TTL.ONE_DAY, description="Time-to-live for the link. Determines when it will expire.")

    @field_validator('long_url', mode='before')
    @classmethod
    def prepend_scheme_if_missing(cls, v: str):
        """
        Prepends 'https://' to the URL if no scheme (http:// or https://) is present.
        """
        if not isinstance(v, str):
            return v  # It's already a Pydantic object, do nothing
        if '.' not in v:
            raise ValueError("Invalid URL: must contain a domain name.")
        if not v.startswith(('http://', 'https://')):
            return 'https://' + v
        return v


class HateoasLink(BaseModel):
    """A HATEOAS-compliant link object."""
    rel: str = Field(..., description="The relationship of the link to the resource (e.g., 'self').")
    href: HttpUrl = Field(..., description="The URL of the related resource.")
    method: str = Field(..., description="The HTTP method to use for the action (e.g., 'GET', 'DELETE').")


class LinkResponse(BaseModel):
    """The response model for a successfully created or retrieved link."""
    short_url: HttpUrl = Field(..., example="https://shortlinks.art/11", description="The generated short URL.")
    long_url: HttpUrl = Field(..., example="https://github.com/fastapi/fastapi", description="The original long URL.")
    expires_at: datetime | None = Field(..., example="2023-10-27T10:00:00Z",
                                        description="The UTC timestamp when the link will expire. `null` if it never expires.")
    deletion_token: str = Field(..., example="Kq_y_d_M5a..._x_s", description="The secret token required to delete this link.")
    links: list[HateoasLink] = Field(..., description="HATEOAS links for related actions.")


class ErrorResponse(BaseModel):
    """A standardized error response model."""
    detail: str