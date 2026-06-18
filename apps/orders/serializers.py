from __future__ import annotations

from rest_framework import serializers

from .models import Order, OrderLine


class OrderLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderLine
        fields = (
            "id",
            "sku",
            "title",
            "quantity",
            "unit_price_base",
            "line_total_base",
            "unit_price_charged",
            "line_total_charged",
            "fulfillment_type",
        )


class OrderSerializer(serializers.ModelSerializer):
    lines = OrderLineSerializer(many=True, read_only=True)
    paid_by_label = serializers.SerializerMethodField()
    shipments = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = (
            "id",
            "number",
            "status",
            "currency",
            "base_currency",
            "fx_rate_locked",
            "subtotal_base",
            "discount_base",
            "total_base",
            "subtotal_charged",
            "discount_charged",
            "total_charged",
            "contact_email",
            "contact_name",
            "payer_email",
            "payer_name",
            "paid_by_label",
            "ship_name",
            "ship_line1",
            "ship_line2",
            "ship_city",
            "ship_region",
            "ship_postal_code",
            "ship_country",
            "coupon_codes",
            "paid_at",
            "created_at",
            "lines",
            "shipments",
        )

    def get_paid_by_label(self, obj: Order) -> str:
        if obj.paid_by_user_id:
            return obj.paid_by_user.email
        return obj.payer_email or ""

    def get_shipments(self, obj: Order) -> list[dict]:
        # `shipments` is a reverse relation on the fulfillment app; absent until Phase 7.
        shipments = getattr(obj, "shipments", None)
        if shipments is None:
            return []
        return [
            {
                "kind": s.kind,
                "status": s.status,
                "tracking_number": s.tracking_number,
                "carrier": s.carrier,
            }
            for s in shipments.all()
        ]


class ContactSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True)
    name = serializers.CharField(required=False, allow_blank=True)


class ShippingSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, allow_blank=True)
    line1 = serializers.CharField(required=False, allow_blank=True)
    line2 = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField(required=False, allow_blank=True)
    region = serializers.CharField(required=False, allow_blank=True)
    postal_code = serializers.CharField(required=False, allow_blank=True)
    country = serializers.CharField(required=False, allow_blank=True, max_length=2)
    phone = serializers.CharField(required=False, allow_blank=True)


class CheckoutSerializer(serializers.Serializer):
    currency = serializers.CharField(required=False, allow_blank=True)
    shipping = ShippingSerializer(required=False)
    contact = ContactSerializer(required=False)
    # Use a saved address book entry instead of inline shipping.
    address_id = serializers.UUIDField(required=False, allow_null=True)
    # Save the inline shipping address to the signed-in user's address book.
    save_address = serializers.BooleanField(required=False, default=False)


class SharedCheckoutSerializer(serializers.Serializer):
    currency = serializers.CharField(required=False, allow_blank=True)
    payer = ContactSerializer(required=False)
    shipping = ShippingSerializer(required=False)  # only honoured if owner allows it


class OrderChatSerializer(serializers.Serializer):
    """Input for the 'chat to order' button (product / cart / checkout)."""

    channel = serializers.ChoiceField(choices=["telegram", "whatsapp", "call"])
    context = serializers.ChoiceField(choices=["product", "cart", "checkout"])
    variant = serializers.UUIDField(required=False, allow_null=True)
    quantity = serializers.IntegerField(required=False, default=1, min_value=1)
    customer_name = serializers.CharField(required=False, allow_blank=True, default="")
    customer_phone = serializers.CharField(required=False, allow_blank=True, default="")
    note = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs: dict) -> dict:
        if attrs["context"] == "product" and not attrs.get("variant"):
            raise serializers.ValidationError("A variant is required for a product inquiry.")
        return attrs
