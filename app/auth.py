"""Enkel HTTP Basic Auth för familjeappen."""
import os
import secrets
from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from typing import Optional

security = HTTPBasic(auto_error=False)


def verify_credentials(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = Depends(security),
):
    """Verifierar Basic Auth. Hoppar över om AUTH_USERNAME/AUTH_PASSWORD inte är satta."""
    username = os.environ.get("AUTH_USERNAME", "")
    password = os.environ.get("AUTH_PASSWORD", "")

    # Om inga credentials konfigurerade, hoppa över auth (lokal utveckling)
    if not username and not password:
        return

    # Auth är konfigurerat men inga credentials skickades
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inloggning krävs",
            headers={"WWW-Authenticate": "Basic"},
        )

    correct_username = secrets.compare_digest(credentials.username, username)
    correct_password = secrets.compare_digest(credentials.password, password)

    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Felaktigt användarnamn eller lösenord",
            headers={"WWW-Authenticate": "Basic"},
        )


class ProtectedStaticFiles(StaticFiles):
    """Filmapp bakom samma inloggning som resten av appen.

    Appens dependencies=[Depends(verify_credentials)] gäller bara vanliga
    sökvägar, inte monterade filmappar som /static och /images. Utan den här
    klassen kunde receptbilder hämtas utan lösenord av den som kände till filnamnet.
    """

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope, receive)
            try:
                verify_credentials(request, await security(request))
            except HTTPException as exc:
                response = JSONResponse(
                    {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers,
                )
                await response(scope, receive, send)
                return
        await super().__call__(scope, receive, send)
