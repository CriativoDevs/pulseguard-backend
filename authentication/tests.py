from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model


class AuthJWTTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="authuser", email="auth@example.com", password="secret123"
        )

    def test_obtain_token(self):
        url = reverse("token_obtain_pair")
        resp = self.client.post(
            url, {"username": "authuser", "password": "secret123"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("access", resp.data)  # type: ignore[attr-defined]
        self.assertIn("refresh", resp.data)  # type: ignore[attr-defined]

    def test_refresh_token(self):
        url = reverse("token_obtain_pair")
        resp = self.client.post(
            url, {"username": "authuser", "password": "secret123"}, format="json"
        )
        refresh = resp.data["refresh"]  # type: ignore[attr-defined]

        refresh_url = reverse("token_refresh")
        refresh_resp = self.client.post(
            refresh_url, {"refresh": refresh}, format="json"
        )
        self.assertEqual(refresh_resp.status_code, status.HTTP_200_OK)
        self.assertIn("access", refresh_resp.data)  # type: ignore[attr-defined]

    def test_verify_token(self):
        obtain_url = reverse("token_obtain_pair")
        resp = self.client.post(
            obtain_url,
            {"username": "authuser", "password": "secret123"},
            format="json",
        )
        access = resp.data["access"]  # type: ignore[attr-defined]

        verify_url = reverse("token_verify")
        verify_resp = self.client.post(verify_url, {"token": access}, format="json")
        self.assertEqual(verify_resp.status_code, status.HTTP_200_OK)
