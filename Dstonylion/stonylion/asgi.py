import os
from django.core.asgi import get_asgi_application
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stonylion.settings')

django_asgi_app = get_asgi_application()
#django_wsgi_app = get_wsgi_application()

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from AI import routing as ai_routing
from story import routing as story_routing

#application = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(
            ai_routing.websocket_urlpatterns +
            story_routing.websocket_urlpatterns
        )
    ),
})

