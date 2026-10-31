from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .taxonomy import CATEGORIES,SUBTYPES,infer_category,product_type

def utcnow():
    return datetime.now(timezone.utc).isoformat()

class PreferenceAssumption(BaseModel):
    model_config=ConfigDict(extra='forbid')
    value:str|float|bool|list[str]|dict[str,str]|None
    reason:str=Field(max_length=500)

class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str | None = "laptop"
    product_type: str | None = None
    gpu_requirement: Literal['any','dedicated','high_end'] = 'any'
    gpu_models: list[str] = Field(default_factory=list,max_length=8)
    min_vram_gb: int | None = Field(default=None,gt=0,le=96)
    attributes: dict[str,str] = Field(default_factory=dict)
    allow_partial_matches: bool = False
    sort_by: Literal['relevance','price_asc','price_desc'] = 'relevance'
    priorities:list[Literal['gpu','ram','storage','price','weight']]=Field(default_factory=list,max_length=5)
    clarification_needed:str|None=Field(default=None,max_length=250)
    currency: Literal["INR"] = "INR"
    max_price: float | None = Field(default=None, gt=0, le=10_000_000)
    max_price_exclusive: bool = False
    min_price: float = Field(default=0, ge=0)
    any_budget: bool = False
    price_preference:Literal['any','budget','midrange','premium']='any'
    release_preference:Literal['any','recent','latest']='any'
    assumptions:dict[str,PreferenceAssumption]=Field(default_factory=dict)
    min_ram_gb: int | None = Field(default=None, ge=1, le=256)
    min_storage_gb: int | None = Field(default=None, ge=1, le=16384)
    max_weight_kg: float | None = Field(default=None, gt=0, le=10)
    brands: list[str] = Field(default_factory=list, max_length=10)
    excluded_brands: list[str] = Field(default_factory=list, max_length=10)
    exclude_gaming: bool = False
    require_upgradeable_ram: bool = False
    required_features: list[str] = Field(default_factory=list,max_length=20)
    use_cases: list[str] = Field(default_factory=list, max_length=8)
    unverified_requirements: list[str] = Field(default_factory=list, max_length=12)
    query: str = Field(default="laptop", max_length=2000)

    @model_validator(mode="after")
    def valid_budget(self):
        if self.category is not None and self.category not in CATEGORIES:raise ValueError('Unsupported category.')
        if self.product_type and self.product_type not in SUBTYPES.get(self.category,{}) and infer_category(self.product_type)==self.category:
            self.product_type=None
        if self.max_price is not None and self.min_price > self.max_price:
            raise ValueError("Minimum budget cannot exceed maximum budget.")
        return self

class Listing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    retailer: Literal["Amazon", "Flipkart"]
    source_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=8, max_length=1500)
    url: str
    brand: str = ""
    model: str = ""
    category: str = "laptop"
    product_type: str | None = None
    attributes: dict[str,str] = Field(default_factory=dict)
    vram_gb: int | None = Field(default=None,gt=0,le=96)
    ram_gb: int | None = Field(default=None, gt=0, le=256)
    storage_gb: int | None = Field(default=None, gt=0, le=16384)
    cpu: str | None = None
    gpu: str | None = None
    color: str | None = None
    weight_kg: float | None = Field(default=None, gt=0, le=10)
    gaming: bool | None = None
    upgradeable_ram: bool | None = None
    features: list[str] = Field(default_factory=list)
    price: float | None = Field(default=None, gt=0, le=10_000_000)
    shipping: float | None = Field(default=None, ge=0)
    currency: Literal["INR"] = "INR"
    availability: Literal["in_stock", "out_of_stock", "unknown"] = "unknown"
    condition: Literal["new", "used", "refurbished", "unknown"] = "unknown"
    observed_at: str | None = None
    imported_at: str = Field(default_factory=utcnow)
    source_kind: Literal["web", "manual", "historical", "fixture"]
    source_note: str = Field(default="", max_length=2000)
    evidence: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_timestamp(self):
        if 'category' not in self.model_fields_set:self.category=infer_category(self.title) or 'other'
        if self.product_type is None:self.product_type=product_type(self.title,self.category)
        if self.category not in CATEGORIES:raise ValueError('Unsupported category.')
        if self.observed_at:
            dt = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                raise ValueError("observed_at must include a timezone")
            if dt > datetime.now(timezone.utc):
                raise ValueError("observed_at cannot be in the future")
        return self

