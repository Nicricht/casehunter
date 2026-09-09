from pydantic import BaseModel, Field


class CompanyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    rut: str | None = Field(default=None, max_length=30)


class ScanRequest(BaseModel):
    url: str
    max_pages: int = Field(default=10, ge=1, le=50)
    enrich: bool = True
    enrich_limit: int = Field(default=25, ge=0, le=100)


class StatusUpdate(BaseModel):
    status: str


class BlockerUpdate(BaseModel):
    blocker: str = Field(min_length=3, max_length=100)
    reason: str | None = Field(default=None, max_length=3000)


class CompanyLink(BaseModel):
    company_id: int


class DocumentUpdate(BaseModel):
    status: str
    note: str | None = Field(default=None, max_length=2000)


class ActionCreate(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    action_type: str = Field(default="MANUAL", max_length=80)
    due_date: str | None = None
    responsible: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=2000)


class ActionUpdate(BaseModel):
    status: str
    note: str | None = Field(default=None, max_length=2000)


class TimelineCreate(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    details: str | None = Field(default=None, max_length=5000)
    event_type: str = Field(default="NOTE", max_length=80)
    event_date: str | None = None
    source_url: str | None = Field(default=None, max_length=1000)


class MercadoPublicoSyncRequest(BaseModel):
    start_date: str
    end_date: str


class AutoRunRequest(BaseModel):
    source_urls: list[str] | None = None
    min_priority: int | None = Field(default=None, ge=0, le=100)
    max_pages: int | None = Field(default=None, ge=1, le=50)
    enrich_limit: int | None = Field(default=None, ge=0, le=100)
    discover_contacts: bool | None = None
    send_approved: bool | None = None


class OutreachApprove(BaseModel):
    recipient_email: str | None = Field(default=None, max_length=320)


class OutreachRecipientUpdate(BaseModel):
    recipient_email: str = Field(min_length=5, max_length=320)
