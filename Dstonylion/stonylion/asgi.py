import os
from asgiref.wsgi import WsgiToAsgi
from django.core.asgi import get_asgi_application
from django.core.wsgi import get_wsgi_application


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stonylion.settings')

#django_asgi_app = get_asgi_application()
django_wsgi_app = get_wsgi_application()
django_asgi_wrapped = WsgiToAsgi(django_wsgi_app)

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
import AI.routing

#application = get_asgi_application()
application = ProtocolTypeRouter({
    "http":django_asgi_wrapped,
    "websocket":
    AuthMiddlewareStack(
        AllowedHostsOriginValidator(
            URLRouter(
                AI.routing.websocket_urlpatterns
            )
        )
    )
})
