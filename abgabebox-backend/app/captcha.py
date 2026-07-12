import httpx

from app.config import settings


async def verify_captcha(solution: str) -> bool:
    if not settings.friendly_captcha_api_key or not settings.friendly_captcha_sitekey:
        # Nicht konfiguriert (z.B. lokale Entwicklung) - fail closed, kein Upload ohne Captcha.
        return False
    if not solution:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                settings.friendly_captcha_verify_url,
                json={
                    "solution": solution,
                    "secret": settings.friendly_captcha_api_key,
                    "sitekey": settings.friendly_captcha_sitekey,
                },
            )
    except httpx.HTTPError:
        return False
    if response.status_code != 200:
        return False
    data = response.json()
    return bool(data.get("success"))
