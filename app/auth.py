"""Enkel HTTP Basic Auth för familjeappen."""
import os
import secrets
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
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
