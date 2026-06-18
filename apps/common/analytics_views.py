"""Admin analytics summary — KPIs + chart series for the dashboard.

Read-only, role-gated to ``admin``. All money is reported in the store's base
currency so figures are comparable regardless of how each order was charged.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, DecimalField, F, Sum, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role, User
from apps.accounts.permissions import IsAdminRole
from apps.catalog.models import Product, Variant
from apps.currency import selectors as currency_selectors
from apps.inventory.models import StockItem
from apps.orders.models import Order, OrderLine, OrderStatus

# Orders that represent realised revenue (payment captured, not reversed).
PAID_STATUSES = [
    OrderStatus.PAID,
    OrderStatus.ROUTING,
    OrderStatus.PARTIALLY_FULFILLED,
    OrderStatus.FULFILLED,
    OrderStatus.COMPLETED,
]
LOW_STOCK_THRESHOLD = 5
TREND_DAYS = 14
TOP_PRODUCTS = 5


def _d(value: Any) -> str:
    return str((value or Decimal("0")).quantize(Decimal("0.01")))


class AdminAnalyticsView(APIView):
    permission_classes = [IsAdminRole]

    @extend_schema(responses={200: dict}, tags=["admin-analytics"])
    def get(self, request: Request) -> Response:
        paid = Order.objects.filter(status__in=PAID_STATUSES)
        revenue = paid.aggregate(
            total=Coalesce(Sum("total_base"), Value(0, output_field=DecimalField()))
        )["total"]
        paid_count = paid.count()
        orders_total = Order.objects.count()
        avg_order = (revenue / paid_count) if paid_count else Decimal("0")

        # Orders grouped by status (pie).
        status_counts = {
            row["status"]: row["n"]
            for row in Order.objects.values("status").annotate(n=Count("id"))
        }
        orders_by_status = [
            {"status": s.value, "label": s.label, "count": status_counts.get(s.value, 0)}
            for s in OrderStatus
            if status_counts.get(s.value, 0) > 0
        ]

        # Revenue + order count per day for the trend window (bar/line).
        start = timezone.now().date() - timedelta(days=TREND_DAYS - 1)
        by_day = {
            row["d"]: row
            for row in paid.filter(created_at__date__gte=start)
            .annotate(d=TruncDate("created_at"))
            .values("d")
            .annotate(
                revenue=Coalesce(Sum("total_base"), Value(0, output_field=DecimalField())),
                orders=Count("id"),
            )
        }
        revenue_by_day = []
        for i in range(TREND_DAYS):
            day = start + timedelta(days=i)
            row = by_day.get(day)
            revenue_by_day.append(
                {
                    "date": day.isoformat(),
                    "revenue": _d(row["revenue"] if row else Decimal("0")),
                    "orders": row["orders"] if row else 0,
                }
            )

        # Top products by units sold (bar).
        top = (
            OrderLine.objects.filter(order__status__in=PAID_STATUSES)
            .values("title")
            .annotate(
                quantity=Coalesce(Sum("quantity"), Value(0)),
                revenue=Coalesce(Sum("line_total_base"), Value(0, output_field=DecimalField())),
            )
            .order_by("-quantity")[:TOP_PRODUCTS]
        )
        top_products = [
            {"title": r["title"], "quantity": r["quantity"], "revenue": _d(r["revenue"])}
            for r in top
        ]

        # Fulfilment split by units (pie).
        fulfil = (
            OrderLine.objects.filter(order__status__in=PAID_STATUSES)
            .values("fulfillment_type")
            .annotate(quantity=Coalesce(Sum("quantity"), Value(0)))
        )
        fulfillment_split = [
            {"type": r["fulfillment_type"], "quantity": r["quantity"]} for r in fulfil
        ]

        # Low-stock active variants (available = on_hand - reserved <= threshold).
        avail = dict(
            StockItem.objects.values("variant")
            .annotate(a=Sum(F("on_hand") - F("reserved")))
            .values_list("variant", "a")
        )
        low_stock = sum(
            1
            for vid in Variant.objects.filter(is_active=True).values_list("id", flat=True)
            if (avail.get(vid) or 0) <= LOW_STOCK_THRESHOLD
        )

        return Response(
            {
                "kpis": {
                    "currency": currency_selectors.base_code(),
                    "revenue": _d(revenue),
                    "orders": orders_total,
                    "paid_orders": paid_count,
                    "avg_order_value": _d(avg_order),
                    "products": Product.objects.filter(is_active=True).count(),
                    "customers": User.objects.filter(role=Role.CUSTOMER).count(),
                    "low_stock": low_stock,
                },
                "orders_by_status": orders_by_status,
                "revenue_by_day": revenue_by_day,
                "top_products": top_products,
                "fulfillment_split": fulfillment_split,
            }
        )
