"""Thin auth/account views. Business logic lives in :mod:`apps.accounts.services`."""

from __future__ import annotations

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from . import services
from .emails import send_password_reset_email
from .models import Address
from .serializers import (
    AddressSerializer,
    ChangePasswordSerializer,
    EmailVerifyConfirmSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    ProfileUpdateSerializer,
    RegisterSerializer,
    UserSerializer,
)


class LoginView(TokenObtainPairView):
    """Issue access + refresh tokens (uses the custom claim serializer)."""

    permission_classes = [AllowAny]


class RefreshView(TokenRefreshView):
    """Rotate the refresh token and issue a fresh access token."""

    permission_classes = [AllowAny]


class RegisterView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=RegisterSerializer, responses={201: UserSerializer}, tags=["auth"])
    def post(self, request: Request) -> Response:
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.register_user(**serializer.validated_data)
        from apps.notifications.notify import send_email_verification

        # The verification email welcomes the user and asks them to confirm.
        token = services.generate_email_verification_token(user)
        send_email_verification(user, token=token)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class LogoutView(APIView):
    """Blacklist a refresh token so it can no longer be rotated."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request={"application/json": {"type": "object"}}, responses={205: None}, tags=["auth"]
    )
    def post(self, request: Request) -> Response:
        refresh = request.data.get("refresh")
        if not refresh:
            return Response(
                {"error": {"code": "missing_refresh", "message": "A refresh token is required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            RefreshToken(refresh).blacklist()
        except TokenError:
            # Already expired/blacklisted — treat as idempotent success.
            pass
        return Response(status=status.HTTP_205_RESET_CONTENT)


class MeView(APIView):
    """Retrieve or update the authenticated user + profile."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: UserSerializer}, tags=["auth"])
    def get(self, request: Request) -> Response:
        return Response(UserSerializer(request.user).data)

    @extend_schema(request=ProfileUpdateSerializer, responses={200: UserSerializer}, tags=["auth"])
    def patch(self, request: Request) -> Response:
        serializer = ProfileUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = services.update_profile(user=request.user, **serializer.validated_data)
        return Response(UserSerializer(user).data)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ChangePasswordSerializer, responses={204: None}, tags=["auth"])
    def post(self, request: Request) -> Response:
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.change_password(user=request.user, **serializer.validated_data)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=PasswordResetRequestSerializer, responses={200: None}, tags=["auth"])
    def post(self, request: Request) -> Response:
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        result = services.generate_password_reset(email=email)
        if result is not None:
            uid, token = result
            send_password_reset_email(email=email, uid=uid, token=token)
        # Always 200 — never reveal whether the email is registered.
        return Response(
            {"detail": "If that email is registered, a reset link has been sent."},
            status=status.HTTP_200_OK,
        )


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=PasswordResetConfirmSerializer, responses={204: None}, tags=["auth"])
    def post(self, request: Request) -> Response:
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.reset_password(**serializer.validated_data)
        return Response(status=status.HTTP_204_NO_CONTENT)


class EmailVerifyRequestView(APIView):
    """Send (or resend) the email-verification link to the signed-in user."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: None}, tags=["auth"])
    def post(self, request: Request) -> Response:
        from apps.notifications.notify import send_email_verification

        if getattr(request.user.profile, "email_verified", False):
            return Response({"detail": "Email already verified."}, status=status.HTTP_200_OK)
        token = services.generate_email_verification_token(request.user)
        send_email_verification(request.user, token=token)
        return Response({"detail": "Verification email sent."}, status=status.HTTP_200_OK)


class EmailVerifyConfirmView(APIView):
    """Confirm an email-verification token (from the emailed link)."""

    permission_classes = [AllowAny]

    @extend_schema(
        request=EmailVerifyConfirmSerializer, responses={200: UserSerializer}, tags=["auth"]
    )
    def post(self, request: Request) -> Response:
        serializer = EmailVerifyConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.confirm_email_verification(serializer.validated_data["token"])
        return Response(UserSerializer(user).data, status=status.HTTP_200_OK)


class AddressViewSet(viewsets.ModelViewSet):
    """The signed-in shopper's saved-address book (CRUD + set-default)."""

    serializer_class = AddressSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):  # type: ignore[override]
        return Address.objects.filter(user=self.request.user)

    @transaction.atomic
    def perform_create(self, serializer: AddressSerializer) -> None:
        user = self.request.user
        first = not Address.objects.filter(user=user).exists()
        # First address is the default; or honour an explicit request.
        make_default = first or serializer.validated_data.get("is_default", False)
        if make_default:
            Address.objects.filter(user=user, is_default=True).update(is_default=False)
        serializer.save(user=user, is_default=make_default)

    @transaction.atomic
    def perform_update(self, serializer: AddressSerializer) -> None:
        user = self.request.user
        if serializer.validated_data.get("is_default"):
            Address.objects.filter(user=user, is_default=True).exclude(
                pk=serializer.instance.pk
            ).update(is_default=False)
        serializer.save()

    def perform_destroy(self, instance: Address) -> None:
        was_default = instance.is_default
        instance.delete()
        # Promote another address to default so there's always one if possible.
        if was_default:
            nxt = Address.objects.filter(user=self.request.user).first()
            if nxt is not None:
                nxt.is_default = True
                nxt.save(update_fields=["is_default"])

    @extend_schema(responses={200: AddressSerializer}, tags=["addresses"])
    @action(detail=True, methods=["post"], url_path="set-default")
    @transaction.atomic
    def set_default(self, request: Request, pk: str | None = None) -> Response:
        address = self.get_object()
        Address.objects.filter(user=request.user, is_default=True).update(is_default=False)
        address.is_default = True
        address.save(update_fields=["is_default"])
        return Response(AddressSerializer(address).data)
