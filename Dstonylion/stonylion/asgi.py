import os
import django
from channels.routing import get_default_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import story.routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'project_root.settings')
django.setup()

application = ProtocolTypeRouter({
    "http": get_default_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter(
            story.routing.websocket_urlpatterns
        )
    ),
})

