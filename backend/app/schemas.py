from pydantic import BaseModel, Field


class SandboxRunCreate(BaseModel):
    repo: str = Field(min_length=3)
    ref: str = "main"
    stack_trace: str | None = None

class ApprovalRequest(BaseModel):
    device_id: str = Field(min_length=1)
    otp_code: str | None = Field(default=None, min_length=6, max_length=8)
    approval_token: str | None = None
    token_ts: int | None = None


class RunControlRequest(BaseModel):
    device_id: str = Field(min_length=1)
    otp_code: str | None = Field(default=None, min_length=6, max_length=8)


class DeviceRegister(BaseModel):
    device_id: str = Field(min_length=1)
    fcm_token: str = Field(min_length=1)
    label: str = ""


class StackFrameOut(BaseModel):
    file: str
    line: int
    function: str


class ErrorIngestResponse(BaseModel):
    ok: bool = True
    provider: str
    id: int
    exception_type: str | None = None
    message: str | None = None
    frames: list[StackFrameOut]