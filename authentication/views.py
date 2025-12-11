from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from monitoring.models import Membership


class InviteUserView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        admin_membership = Membership.objects.filter(
            user=request.user, role__in=["owner", "admin"]
        ).first()
        if not admin_membership:
            raise PermissionDenied("Only admins can invite users")

        email = request.data.get("email")
        password = request.data.get("password")
        role = request.data.get("role", "member")
        if not email:
            return Response({"detail": "email is required"}, status=400)

        User = get_user_model()
        username = request.data.get("username") or email.split("@")[0]
        if not password:
            password = User.objects.make_random_password()

        user, created = User.objects.get_or_create(
            email=email,
            defaults={"username": username},
        )
        if created:
            user.set_password(password)
            user.save()

        Membership.objects.get_or_create(
            user=user,
            organization=admin_membership.organization,
            defaults={"role": role},
        )

        return Response(
            {
                "user_id": user.id,
                "email": user.email,
                "role": role,
                "organization": admin_membership.organization.id,
                "created": created,
            }
        )
