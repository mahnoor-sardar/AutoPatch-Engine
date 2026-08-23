from pydantic import BaseModel, Field


class SandboxRunCreate(BaseModel):
    repo: str = Field(min_length=3)
    ref: str = "main"


class DeviceRegister(BaseModel):
    device_id: str = Field(min_length=1)
    fcm_token: str = Field(min_length=1)
    label: str = ""
