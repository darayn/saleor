from collections.abc import Iterable
from typing import TYPE_CHECKING, Optional

from django.db import transaction
from django.db.models import Exists, OuterRef, QuerySet

from ...attribute import AttributeType
from ...discount.models import PromotionRule
from ..models import ProductVariant

if TYPE_CHECKING:
    from ...attribute.models import AssignedVariantAttribute, Attribute


def generate_and_set_variant_name(
    variant: "ProductVariant", sku: Optional[str], save: Optional[bool] = True
):
    """Generate ProductVariant's name based on its attributes."""
    attributes_display = []

    variant_selection_attributes = variant.attributes.filter(
        assignment__variant_selection=True,
        assignment__attribute__type=AttributeType.PRODUCT_TYPE,
    )
    attribute_rel: AssignedVariantAttribute
    for attribute_rel in variant_selection_attributes.iterator():
        values_qs = attribute_rel.values.all()
        attributes_display.append(", ".join([str(value) for value in values_qs]))

    name = " / ".join(sorted(attributes_display))
    if not name:
        name = sku or variant.get_global_id()

    variant.name = name
    if save:
        variant.save(update_fields=["name", "updated_at"])
    return variant


def get_variant_selection_attributes(
    attributes: Iterable[tuple["Attribute", bool]],
) -> list[tuple["Attribute", bool]]:
    """Return attributes that can be used in variant selection.

    Attribute must be product attribute and attribute input type must be
    in ALLOWED_IN_VARIANT_SELECTION list.
    """
    return [
        (attribute, variant_selection)
        for attribute, variant_selection in attributes
        if variant_selection and attribute.type == AttributeType.PRODUCT_TYPE
    ]


def fetch_variants_for_promotion_rules(
    rules: QuerySet[PromotionRule],
):
    from ...graphql.discount.utils import get_variants_for_predicate

    PromotionRuleVariant = PromotionRule.variants.through
    promotion_rule_variants = []
    for rule in list(rules.iterator()):
        variants = get_variants_for_predicate(rule.catalogue_predicate)
        promotion_rule_variants.extend(
            [
                PromotionRuleVariant(
                    promotionrule_id=rule.pk, productvariant_id=variant.pk
                )
                for variant in variants
            ]
        )

    with transaction.atomic():
        # Clear existing variants assigned to promotion rules
        PromotionRuleVariant.objects.filter(
            Exists(rules.filter(pk=OuterRef("promotionrule_id")))
        ).delete()
        PromotionRuleVariant.objects.bulk_create(promotion_rule_variants)
