from typing import Optional, Literal
from pydantic import BaseModel, Field, validator, constr

import config

class LinkResponse(BaseModel):
    """Response model for a successfully created link."""
    short_url: str
    stats_url: str
    delete_url: str
    qr_code_data: str

class LinkCreatePayload(BaseModel):
    """Request model for creating links."""
    long_url: str = Field(..., min_length=1, max_length=config.MAX_URL_LENGTH) 
    ttl: Literal["1h", "24h", "1w", "never"] = "24h"
    custom_code: Optional[constr(pattern=r'^[a-zA-Z0-9]{4,20}$')] = None
    utm_tags: Optional[str] = Field(None, max_length=500)
    owner_id: Optional[str] = Field(None, max_length=100)
    
    @validator('long_url')
    def validate_url(cls, v):
        if not v or not v.strip():
            raise ValueError("URL cannot be empty")
        return v.strip()
    
    @validator('utm_tags')
    def validate_utm_tags(cls, v):
        if v:
            v = v.strip()
            # Basic validation, can be expanded
        return v