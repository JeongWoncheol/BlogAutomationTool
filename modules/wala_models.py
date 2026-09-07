"""Immutable records parsed from Wala's public article data."""

from datetime import datetime
from typing import Annotated, ClassVar, Literal

from pydantic import (
    AliasChoices,
    AliasPath,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
)


def _text(value: str | None) -> str:
    return value or ""


Text = Annotated[str, BeforeValidator(_text)]


class WalaProduct(BaseModel):
    """A direct publisher-linked product; recommendations remain nested."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    id: int
    type: Literal["STORE", "CONTENT"]
    title: str
    brand: str
    price: int
    basic_info: str
    image_url: str
    url: str
    alternatives: tuple["WalaProduct", ...] = ()


class WalaArticle(BaseModel):
    """A public article with original publisher data retained for provenance."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    id: int
    title: str
    title_eng: str
    description: str
    published_at: datetime
    tags: tuple[str, ...]
    images: tuple[str, ...]
    source_name: str
    source_link: str
    source_name2: str
    source_link2: str
    products: tuple[WalaProduct, ...]
    url: str
    status: str
    raw_json: str


class RawTag(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    title_kor: Text = Field(default="", alias="titleKor")
    title_eng: Text = Field(default="", alias="titleEng")


class RawProduct(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    id: int = Field(validation_alias=AliasChoices("productId", "id"), gt=0)
    type: Literal["STORE", "CONTENT"]
    title: Text = ""
    link: Text = ""
    title_eng: Text = Field(default="", alias="titleEng")
    brand: Text = Field(default="", alias="brandTitle")
    brand_eng: Text = Field(
        default="", validation_alias=AliasChoices("branTitleEng", "brandTitleEng")
    )
    price: int | None = Field(default=0, alias="listPrice", ge=0)
    basic_price: int | None = Field(default=0, alias="basicPrice", ge=0)
    basic_info: Text = Field(default="", alias="basicInfo")
    image_url: Text = Field(default="", alias="thumbnailImage")
    alternatives: tuple["RawProduct", ...] | None = Field(
        default=(), alias="productList"
    )


class RawArticle(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    id: int = Field(gt=0)
    title: Text = ""
    title_eng: Text = Field(default="", alias="titleEng")
    description: Text = ""
    status: str
    published_at: datetime = Field(alias="createdAt")
    tags: tuple[RawTag, ...] | None = Field(default=(), alias="tagList")
    images: tuple[str, ...] | None = Field(default=(), alias="subImageList")
    source_name: Text = Field(default="", alias="sourceName")
    source_link: Text = Field(default="", alias="sourceLink")
    source_name2: Text = Field(default="", alias="sourceName2")
    source_link2: Text = Field(default="", alias="sourceLink2")
    products: tuple[RawProduct, ...] | None = Field(
        default=(), alias="contentProductList"
    )


class QueryState(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    data: JsonValue = None


class NextQuery(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    key: tuple[JsonValue, ...] = Field(alias="queryKey")
    state: QueryState


class NextDocument(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    queries: tuple[NextQuery, ...] = Field(
        validation_alias=AliasPath("props", "pageProps", "dehydratedState", "queries")
    )


class ArticleResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    code: int
    value: JsonValue = None
