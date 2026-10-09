"""3단계 영업 프로필 템플릿(카테고리 → 품목 → 소구점).

업종별 문구는 코드가 아니라 app/data/sales_templates.json 데이터로만 관리한다.
새 업종을 추가할 때 코드 수정 없이 JSON만 늘리면 된다.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from app.domain.models import StrictBaseModel, SalesProfile

TEMPLATE_FILE = Path(__file__).resolve().parent.parent / "data" / "sales_templates.json"

ValuePropGroupId = Literal["COST", "TAX", "OPS"]
MIN_VALUE_PROPS = 1
MAX_VALUE_PROPS = 3


class ValuePropGroup(StrictBaseModel):
    id: ValuePropGroupId
    label: str


class ValueProp(StrictBaseModel):
    id: str
    group: ValuePropGroupId
    label: str


class ProductTemplate(StrictBaseModel):
    id: str
    label: str


class CategoryTemplate(StrictBaseModel):
    id: str
    label: str
    products: list[ProductTemplate] = Field(..., min_length=1)
    value_props: list[ValueProp] = Field(..., min_length=1)

    def find_product(self, product_id: str) -> ProductTemplate | None:
        return next((p for p in self.products if p.id == product_id), None)

    def find_value_prop(self, value_prop_id: str) -> ValueProp | None:
        return next((v for v in self.value_props if v.id == value_prop_id), None)


class SalesTemplateCatalog(StrictBaseModel):
    version: str
    value_prop_groups: list[ValuePropGroup]
    categories: list[CategoryTemplate] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "SalesTemplateCatalog":
        category_ids = [c.id for c in self.categories]
        if len(category_ids) != len(set(category_ids)):
            raise ValueError("Duplicate category id in sales template catalog")
        for c in self.categories:
            product_ids = [p.id for p in c.products]
            vp_ids = [v.id for v in c.value_props]
            if len(product_ids) != len(set(product_ids)) or len(vp_ids) != len(set(vp_ids)):
                raise ValueError(f"Duplicate product/value_prop id in category {c.id}")
        return self

    def find_category(self, category_id: str) -> CategoryTemplate | None:
        return next((c for c in self.categories if c.id == category_id), None)

    def group_label(self, group_id: str) -> str:
        return next((g.label for g in self.value_prop_groups if g.id == group_id), group_id)


@lru_cache(maxsize=1)
def load_sales_template_catalog() -> SalesTemplateCatalog:
    return SalesTemplateCatalog.model_validate(json.loads(TEMPLATE_FILE.read_text(encoding="utf-8")))


class SelectedValueProp(StrictBaseModel):
    """질문 3선의 솔루션 브리지(Q3)에서 인용할 수 있는 선택 소구점."""
    id: str
    group: ValuePropGroupId
    group_label: str
    label: str


class SalesTemplateSelection(StrictBaseModel):
    """영업사원이 온보딩에서 고른 3단계 템플릿 선택값 (ID만 저장)."""
    category_id: str = Field(..., description="솔루션 카테고리 ID (예: mobility)")
    product_id: str = Field(..., description="세부 품목 ID (예: long_term_rental)")
    value_prop_ids: list[str] = Field(
        ..., min_length=MIN_VALUE_PROPS, max_length=MAX_VALUE_PROPS, description="핵심 소구점 ID 1~3개"
    )

    @model_validator(mode="after")
    def validate_against_catalog(self) -> "SalesTemplateSelection":
        if len(self.value_prop_ids) != len(set(self.value_prop_ids)):
            raise ValueError("Duplicate value_prop_id in selection")
        catalog = load_sales_template_catalog()
        category = catalog.find_category(self.category_id)
        if category is None:
            raise ValueError(f"Unknown category_id: {self.category_id}")
        if category.find_product(self.product_id) is None:
            raise ValueError(f"product_id {self.product_id} does not belong to category {self.category_id}")
        unknown = [v for v in self.value_prop_ids if category.find_value_prop(v) is None]
        if unknown:
            raise ValueError(f"value_prop_id(s) {unknown} do not belong to category {self.category_id}")
        return self

    def resolve(self) -> "ResolvedSalesTemplate":
        catalog = load_sales_template_catalog()
        category = catalog.find_category(self.category_id)
        assert category is not None  # validate_against_catalog에서 보장
        product = category.find_product(self.product_id)
        assert product is not None
        value_props = []
        for vid in self.value_prop_ids:
            vp = category.find_value_prop(vid)
            assert vp is not None
            value_props.append(
                SelectedValueProp(id=vp.id, group=vp.group, group_label=catalog.group_label(vp.group), label=vp.label)
            )
        return ResolvedSalesTemplate(
            category_id=category.id,
            category_label=category.label,
            product_id=product.id,
            product_label=product.label,
            value_props=value_props,
        )


class ResolvedSalesTemplate(StrictBaseModel):
    """ID를 사람이 읽는 라벨로 풀어낸 템플릿. 프롬프트와 메신저 출력에 사용한다."""
    category_id: str
    category_label: str
    product_id: str
    product_label: str
    value_props: list[SelectedValueProp]

    def value_prop_ids(self) -> set[str]:
        return {v.id for v in self.value_props}

    def to_sales_profile(self, seller_company: str = "미입력") -> SalesProfile:
        """기존 P1~P4 파이프라인이 그대로 동작하도록 자유 텍스트 SalesProfile로 변환한다."""
        value_text = ", ".join(f"[{v.group_label}] {v.label}" for v in self.value_props)
        return SalesProfile(
            company=seller_company,
            industry=self.category_label,
            product_service=self.product_label,
            target_customer="B2B 법인 고객",
            sales_goal=f"{self.product_label} 도입 제안 (핵심 소구점: {value_text})",
        )
