from django.utils import translation

from .models import Profile


class UserPreferencesMiddleware:
    """Kirgan foydalanuvchi uchun profildagi tilni qo'llaydi (cookie va brauzer tilidan ustun)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # Birinchi marta profil yaratilsa, foydalanuvchi hozir tanlab turgan til saqlanadi
            profile, _ = Profile.objects.get_or_create(user=request.user, defaults={"language": request.LANGUAGE_CODE})
            request.profile = profile
            if profile.language != request.LANGUAGE_CODE:
                translation.activate(profile.language)
                request.LANGUAGE_CODE = profile.language
        return self.get_response(request)
