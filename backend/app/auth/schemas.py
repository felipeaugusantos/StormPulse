"""Auth request/response schemas.

Input schemas are explicit (no mass assignment): only these fields are ever
read from the client, so a caller can never set ``role``, ``tenant_id`` or
``is_active`` on themselves.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, model_validator


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)
    # Optional: name of the tenant to create/join. Defaults to a personal tenant.
    tenant_name: str | None = Field(default=None, max_length=120)
    # Module selection (FASE 30) — Tempestade is the platform's core
    # product (defaults on), Agro is an opt-in add-on (defaults off). At
    # least one must be selected; enforced below rather than left for the
    # UI alone, since this is a request-validation concern.
    storm_module: bool = True
    agro_module: bool = False
    # Must be explicitly true — a client that omits it or sends false gets
    # a 422, not a silent "assume yes" (FASE 8, ADR-0059).
    accept_terms: bool = Field(default=False)
    # Present only when ANTI_CAPTCHA is configured server-side
    # (`Settings.hcaptcha_secret_key`) — otherwise ignored entirely.
    captcha_token: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _at_least_one_module(self) -> RegisterIn:
        if not self.storm_module and not self.agro_module:
            raise ValueError("Selecione pelo menos um módulo: Tempestade ou Agro")
        return self

    @model_validator(mode="after")
    def _must_accept_terms(self) -> RegisterIn:
        if not self.accept_terms:
            raise ValueError("É preciso aceitar os Termos de Uso e a Política de Privacidade")
        return self


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    captcha_token: str | None = Field(default=None, max_length=4000)


class VerifyEmailIn(BaseModel):
    token: str = Field(min_length=1)


class ResendVerificationOut(BaseModel):
    sent: bool


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)


class RefreshIn(BaseModel):
    # Optional: when the refresh-token cookie is enabled (ADR-0029), the
    # browser sends it automatically and the body may omit it entirely.
    # With the cookie disabled (default today), this is required exactly
    # as before.
    refresh_token: str | None = Field(default=None, min_length=1)


class GoogleAuthIn(BaseModel):
    # A Google Identity Services ID token (JWT), verified server-side
    # against Google's public keys before any claim is trusted.
    id_token: str = Field(min_length=1)


class TokenPair(BaseModel):
    access_token: str
    # None when the refresh-token cookie is enabled (ADR-0029) — the token
    # went out as an HttpOnly Set-Cookie instead, never in a JS-readable
    # response body. With the cookie disabled (default today), this is
    # always populated exactly as before.
    refresh_token: str | None = None
    token_type: str = "bearer"
