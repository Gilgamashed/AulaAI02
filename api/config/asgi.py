import os
import sys
from pathlib import Path

# Sobe um nível para que o pacote `config` seja importável.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.asgi import get_asgi_application

application = get_asgi_application()