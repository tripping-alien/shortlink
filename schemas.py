from typing import Optional
from pydantic import BaseModel, HttpUrl, field_validator

class LinkCreate(BaseModel):
    """Schema for incoming link creation request."""
    # Ensure long_url is a valid HTTP URL
    long_url: HttpUrl
    # Time-to-live string (e.g., '1h', '1d', '1w', 'never')
    ttl: str = '1d'
    # Optional custom short code
    custom_code: Optional[str] = None

    @field_validator('custom_code')
    def validate_custom_code(cls, value):
        """Server-side validation for the custom code format."""
        if value is None:
            return value

        # Force lowercase and check for alphanumeric only (strictest safe format)
        normalized_value = value.strip().lower()
        
        if not normalized_value.isalnum():
            raise ValueError("Invalid short code format: custom code must only contain lowercase letters and numbers.")
        
        # Check length constraints if necessary (assuming they align with the generated code length)
        # if len(normalized_value) > 10: 
        #     raise ValueError("Custom short code is too long.")
        
        return normalized_value

class ShortLinkResponse(BaseModel):
    """Schema for successful link creation response."""
    long_url: str
    short_url: str # The complete short URL (e.g., https://shorty.app/Bx7vq)
    deletion_token: str
