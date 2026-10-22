# Smoke-test settings: PostgreSQL + Redis, shared cache so uwsgi and daphne agree.
from pgsettings import *  # noqa

BROKER_URL = 'redis://127.0.0.1:56379/0'
CHANNEL_LAYERS = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer", "CONFIG": {"hosts": [BROKER_URL]}}}
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.redis.RedisCache', 'LOCATION': 'redis://127.0.0.1:56379/1'}}
ALLOWED_HOSTS = ['*']
DEBUG = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
# Without /etc/tower/SECRET_KEY every process generates its own random key, which
# breaks sessions and encrypted fields across uwsgi workers and daphne.
SECRET_KEY = 'smoke-test-fixed-secret-key-shared-by-all-processes'
BROADCAST_WEBSOCKET_SECRET = 'smoke-test-relay-secret'
